#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek Harness 一键启动器 (Windows / macOS / Linux)
=====================================================

作用：双击快捷方式即可启动 `dsh web` 并在浏览器里打开 DeepSeek Harness，
      不需要再打开终端手动输入命令。

行为：
  1. 解析配置（默认值 -> dsh_launcher.json -> 环境变量 -> 命令行参数）。
  2. 检查目标端口：
       - 已是 DSH 服务  -> 直接打开浏览器，不重复启动（避免抢端口报错）。
       - 被别的程序占用 -> 明确报错，提示换端口。
  3. 决定工作区（workspace）：
       - last（默认）   -> 接着 DSH 上次用的工作区打开（读 workspace.json）
       - ask            -> 每次弹系统原生文件夹选择框
       - home           -> 主目录（中立起点，不绑项目）
       - cwd            -> 快捷方式"起始位置"所在目录
       - <具体目录>     -> 固定目录
  4. 在该工作区目录下启动 `dsh web`（启动目录 = 本次会话的 workspace 根目录）。
  5. 轮询等待服务就绪后再打开浏览器，随后持续显示服务日志。
  6. 关闭窗口 / Ctrl+C 即停止服务。

常用参数：
  --workspace <last|ask|home|cwd|目录>   工作区模式或固定目录（默认 last）
  --port <n>          监听端口（默认 3080）
  --no-browser        启动后不自动打开浏览器
  --new               即使已有实例在运行，也强制新开一个（端口冲突则报错）
  --list-workspaces   列出 DSH 记录过的工作区
  --selftest          只做环境体检并打印结果，不启动任何服务
  --print-config      打印最终生效的配置后退出
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_TITLE = "DeepSeek Harness"
IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"

# dsh 0.1.5+ 对不带 token 的请求返回 401，响应体固定包含这句话
AUTH_REQUIRED_MARKER = "authentication required"
# 启动横幅里的可用地址（可能带 ?token=...）
URL_IN_LINE_RE = re.compile(r"(https?://[^\s]+)")


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def base_dir() -> Path:
    """返回“程序所在目录”。打包成 exe 后是 exe 所在目录，而不是解包临时目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def dsh_home() -> Path:
    """DSH 主目录：优先环境变量，否则 ~/.dsh。"""
    env = os.environ.get("DSH_HOME", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".dsh"


WORKSPACE_MODES = ("last", "ask", "home", "cwd")

DEFAULTS = {
    # 工作区模式（可用 --workspace 临时覆盖）：
    #   "last"   -> DSH 最近使用过的那个工作区（读 <DSH_HOME>/storages/workspace.json，默认）
    #   "ask"    -> 每次启动弹系统原生文件夹选择框
    #   "home"   -> 用户主目录（中立起点，不绑定任何项目工作区）
    #   "cwd"    -> 快捷方式"起始位置"所在目录
    #   "<路径>" -> 固定目录
    "workspace": "last",
    "fallback_workspace": "",  # last 解析不出来时用这里；留空 = 主目录
    "host": "127.0.0.1",
    "port": 3080,
    "open_browser": True,
    # dsh 启动器级参数；默认走 web profile
    "dsh_args": ["web"],
    # dsh 应用级参数（跟在 dsh_args 之后），支持 {host} {port} {workspace} 占位符
    "app_args": ["--host", "{host}", "--port", "{port}", "--no-open"],
    "reuse_existing": True,
    "startup_timeout": 180,
    "pause_on_error": True,
    "reuse_exit_delay": 1.0,
    "log_file": "",
}

ENV_MAP = {
    "DSH_LAUNCH_WORKSPACE": "workspace",
    "DSH_LAUNCH_HOST": "host",
    "DSH_LAUNCH_PORT": "port",
    "DSH_LAUNCH_OPEN_BROWSER": "open_browser",
    "DSH_LAUNCH_REUSE": "reuse_existing",
    "DSH_LAUNCH_LOG": "log_file",
    "DSH_LAUNCH_TIMEOUT": "startup_timeout",
}

_log_lock = threading.Lock()
_log_stream = None


def _truthy(value: str) -> bool:
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


def open_log(path: Path):
    """打开日志文件；任何异常都不应影响启动。"""
    global _log_stream
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 1_000_000:
            path.replace(path.with_suffix(path.suffix + ".1"))
        _log_stream = open(path, "a", encoding="utf-8", errors="replace")
    except Exception:
        _log_stream = None


def say(message: str = "") -> None:
    """同时输出到控制台和日志文件；控制台编码不支持时降级为替换字符。"""
    line = str(message)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"), flush=True)
    except Exception:
        pass
    if _log_stream is not None:
        with _log_lock:
            try:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                for part in (line.splitlines() or [""]):
                    _log_stream.write(f"[{stamp}] {part}\n")
                _log_stream.flush()
            except Exception:
                pass


def banner() -> None:
    say("=" * 62)
    say(f" {APP_TITLE} 一键启动器")
    say("=" * 62)


def set_console_title(title: str) -> None:
    if not IS_WINDOWS:
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(title)
    except Exception:
        pass


def has_console() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


# --------------------------------------------------------------------------
# 配置解析
# --------------------------------------------------------------------------
def deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in (extra or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        elif value is not None:
            out[key] = value
    return out


def config_candidates() -> list[Path]:
    return [
        base_dir() / "dsh_launcher.json",
        dsh_home() / "dsh_launcher.json",
        Path.cwd() / "dsh_launcher.json",
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="DeepSeek Harness",
        description="一键启动 dsh web 并打开浏览器。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--workspace",
                        help="工作区：last(默认，接着上次的工作区) / ask(每次弹框选) / "
                             "home(主目录) / cwd(快捷方式起始位置) / <具体目录>")
    parser.add_argument("--fallback-workspace",
                        help="last 解析不出来时使用的目录，默认主目录")
    parser.add_argument("--host", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, help="监听端口，默认 3080")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--new", action="store_true", help="强制新开实例，不复用已运行的")
    parser.add_argument("--timeout", type=int, help="等待服务就绪的秒数")
    parser.add_argument("--config", help="额外指定一个 JSON 配置文件")
    parser.add_argument("--log-file", help="日志文件路径")
    parser.add_argument("--no-pause", action="store_true", help="出错后不等待回车")
    parser.add_argument("--quiet", action="store_true", help="减少输出")
    parser.add_argument("--print-config", action="store_true", help="打印配置后退出")
    parser.add_argument("--list-workspaces", action="store_true",
                        help="列出 DSH 记录过的工作区后退出")
    parser.add_argument("--selftest", action="store_true", help="只体检环境，不启动服务")
    return parser


def resolve_config(argv=None) -> dict:
    args = build_parser().parse_args(argv)
    cfg = dict(DEFAULTS)

    paths = []
    if args.config:
        paths.append(Path(args.config).expanduser())
    paths.extend(config_candidates())
    seen = set()
    for path in paths:
        try:
            key = str(path.resolve()).lower()
        except Exception:
            key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg = deep_merge(cfg, data)
                    cfg["_config_file"] = str(path)
            except Exception as exc:  # 配置写坏了不应该阻止启动
                say(f"[!] 配置文件无法解析，已忽略: {path} ({exc})")

    for env_key, cfg_key in ENV_MAP.items():
        raw = os.environ.get(env_key)
        if raw is None or raw.strip() == "":
            continue
        if cfg_key in ("port", "startup_timeout"):
            try:
                cfg[cfg_key] = int(raw)
            except ValueError:
                say(f"[!] 环境变量 {env_key}={raw!r} 不是整数，已忽略")
        elif cfg_key in ("open_browser", "reuse_existing"):
            cfg[cfg_key] = _truthy(raw)
        else:
            cfg[cfg_key] = raw

    if args.workspace:
        cfg["workspace"] = args.workspace
    if args.fallback_workspace:
        cfg["fallback_workspace"] = args.fallback_workspace
    if args.host:
        cfg["host"] = args.host
    if args.port:
        cfg["port"] = args.port
    if args.no_browser:
        cfg["open_browser"] = False
    if args.new:
        cfg["reuse_existing"] = False
    if args.timeout:
        cfg["startup_timeout"] = args.timeout
    if args.log_file:
        cfg["log_file"] = args.log_file
    if args.no_pause:
        cfg["pause_on_error"] = False

    cfg["quiet"] = bool(args.quiet)
    # 模式关键字保持原样，"last"/"ask"/"home"/"cwd" 之外的按目录展开
    workspace = str(cfg.get("workspace") or "last").strip()
    if workspace.lower() not in WORKSPACE_MODES:
        workspace = str(Path(workspace).expanduser())
    cfg["workspace"] = workspace
    cfg["_selftest"] = bool(args.selftest)
    cfg["_print_config"] = bool(args.print_config)
    cfg["_list_workspaces"] = bool(args.list_workspaces)
    cfg["url"] = f"http://{cfg['host']}:{cfg['port']}/"
    return cfg


def apply_app_args(cfg: dict) -> list:
    mapping = {
        "host": cfg["host"],
        "port": cfg["port"],
        "workspace": cfg["workspace"],
        "url": cfg["url"],
    }
    out = []
    for item in cfg.get("app_args") or []:
        try:
            out.append(str(item).format(**mapping))
        except (KeyError, IndexError, ValueError):
            out.append(str(item))
    return out


# --------------------------------------------------------------------------
# 定位 node 与 dsh
# --------------------------------------------------------------------------
def find_node() -> str | None:
    env = os.environ.get("DSH_NODE", "").strip()
    if env and Path(env).is_file():
        return env
    found = shutil.which("node")
    if found:
        return found
    candidates = [
        Path(r"C:\Program Files\nodejs\node.exe"),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "nodejs" / "node.exe",
        Path("/usr/local/bin/node"),
        Path("/opt/homebrew/bin/node"),
        Path.home() / ".nvm" / "current" / "bin" / "node",
    ]
    for cand in candidates:
        try:
            if cand.is_file():
                return str(cand)
        except Exception:
            continue
    return None


def dsh_entry_candidates() -> list[Path]:
    """收集可能的 @deepseek-ai/dsh/lib/bin.js 路径。"""
    roots: list[Path] = []

    env = os.environ.get("DSH_ENTRY", "").strip()
    if env:
        roots.append(Path(env).expanduser())

    # 从 PATH 上的 dsh / dsh.cmd 反推 npm 全局前缀
    for name in ("dsh", "dsh.cmd", "dsh.ps1"):
        found = shutil.which(name)
        if found:
            shim = Path(found)
            roots.append(shim.parent / "node_modules")
            roots.append(shim.parent.parent / "lib" / "node_modules")

    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")

    if appdata:
        roots.append(Path(appdata) / "npm" / "node_modules")
    if localappdata:
        roots.append(Path(localappdata) / "npm" / "node_modules")
    roots.append(Path(program_files) / "nodejs" / "node_modules")
    # node 安装目录旁边的 node_modules（自定义安装位置的情况）
    node = find_node()
    if node:
        roots.append(Path(node).parent / "node_modules")
    roots += [
        Path("/usr/local/lib/node_modules"),
        Path("/opt/homebrew/lib/node_modules"),
        Path.home() / ".npm-global" / "lib" / "node_modules",
        Path.home() / ".nvm" / "versions" / "node" / "current" / "lib" / "node_modules",
    ]

    entries: list[Path] = []
    for root in roots:
        try:
            if root.name == "bin.js" and root.is_file():
                entries.append(root)
            else:
                entries.append(root / "@deepseek-ai" / "dsh" / "lib" / "bin.js")
        except Exception:
            continue
    return entries


def find_dsh_entry() -> Path | None:
    for cand in dsh_entry_candidates():
        try:
            if cand.is_file():
                return cand
        except Exception:
            continue
    # 最后手段：问 npm 要全局根目录
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm:
        try:
            proc = subprocess.run(
                [npm, "root", "-g"],
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            if proc.returncode == 0:
                root = Path(proc.stdout.strip().splitlines()[-1].strip())
                cand = root / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
                if cand.is_file():
                    return cand
        except Exception:
            pass
    return None


def resolve_dsh_command(cfg: dict) -> list[str] | None:
    """拼出完整启动命令：优先直接调用 node + bin.js，其次退回 PATH 上的 dsh。"""
    tail = list(cfg.get("dsh_args") or []) + apply_app_args(cfg)
    node = find_node()
    entry = find_dsh_entry()
    if node and entry:
        cfg["_how"] = f"node + {entry}"
        return [node, str(entry), *tail]
    shim = shutil.which("dsh") or shutil.which("dsh.cmd")
    if shim:
        cfg["_how"] = f"PATH 上的 {shim}"
        return [shim, *tail]
    if node and entry is None:
        cfg["_how"] = "未找到"
        return None
    cfg["_how"] = "未找到"
    return None


# --------------------------------------------------------------------------
# 工作区（workspace）解析
#
# DSH 的架构里，一次会话一定有一个 workspace 根目录
# （dsh-sandbox-policy: workspaceRoot = config.workspaceRoot ?? process.cwd()），
# 也就是"启动时所在目录 = 本次会话的工作目录"。所以不存在"完全没有工作目录"的
# 会话；但"不属于任何已注册工作区"是存在的 —— 那样的会话在侧栏显示为 Ungrouped。
#
# 这里读 DSH 自己维护的工作区注册表，实现"接着上次的工作区打开"。
# --------------------------------------------------------------------------
def dsh_workspace_file() -> Path:
    return dsh_home() / "storages" / "workspace.json"


def read_dsh_workspaces() -> list[dict]:
    """读 DSH 的工作区注册表，返回 [{path,title,updatedAt,createdAt}, ...]。"""
    try:
        data = json.loads(dsh_workspace_file().read_text(encoding="utf-8"))
    except Exception:
        return []
    table = (data.get("tables") or {}).get("workspaces") or {}
    rows = []
    for record in table.values():
        if not isinstance(record, dict):
            continue
        raw = record.get("path")
        if not raw:
            continue
        rows.append({
            "path": str(raw),
            "title": record.get("title") or Path(str(raw)).name,
            "updatedAt": record.get("updatedAt") or record.get("createdAt") or "",
            "createdAt": record.get("createdAt") or "",
        })
    return rows


def last_used_workspace() -> tuple[str | None, str]:
    """返回 DSH 最近使用的工作区（目录必须仍然存在）。"""
    rows = [r for r in read_dsh_workspaces() if Path(r["path"]).is_dir()]
    if not rows:
        return None, "注册表里没有仍然存在的工作区"
    rows.sort(key=lambda r: (r["updatedAt"], r["createdAt"]), reverse=True)
    top = rows[0]
    return top["path"], f"上一个工作区「{top['title']}」(共 {len(rows)} 个可用记录)"


def ps_quote(text: str) -> str:
    """引用成 PowerShell 单引号字符串（单引号需双写转义）。"""
    return "'" + str(text).replace("'", "''") + "'"


def pick_directory_native(initial: str | None = None) -> str | None:
    """弹系统原生的文件夹选择框；取消或失败返回 None。"""
    if IS_WINDOWS:
        ps = shutil.which("pwsh") or shutil.which("powershell")
        if not ps:
            return None
        script = f"""$ErrorActionPreference = 'Stop'
# 让父进程按 UTF-8 读取输出（PowerShell 5.1 默认按控制台代码页输出）
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms | Out-Null
$dlg = New-Object System.Windows.Forms.FolderBrowserDialog
$dlg.Description = '选择 DeepSeek Harness 的工作目录'
$dlg.ShowNewFolderButton = $true
$initial = {ps_quote(initial or '')}
if ($initial -ne '' -and (Test-Path -LiteralPath $initial)) {{ $dlg.SelectedPath = $initial }}
if ($env:DSH_PICKER_SELFTEST -eq '1') {{ Write-Output $dlg.SelectedPath; exit 0 }}
if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{ Write-Output $dlg.SelectedPath }}
"""
        tmp = Path(tempfile.gettempdir()) / "dsh_pick_folder.ps1"
        try:
            # 必须带 BOM，否则 Windows PowerShell 5.1 会把中文当 ANSI 读
            tmp.write_text(script, encoding="utf-8-sig")
            proc = subprocess.run(
                [ps, "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        except Exception as exc:
            say(f"[!] 打开文件夹选择框失败: {exc}")
            return None
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        if lines and Path(lines[-1]).is_dir():
            return lines[-1]
        if proc.returncode not in (0, None) and proc.stderr:
            say(f"[!] 文件夹选择框出错: {proc.stderr.strip().splitlines()[-1]}")
        return None

    if IS_MACOS:
        try:
            proc = subprocess.run(
                ["osascript", "-e",
                 'POSIX path of (choose folder with prompt "选择 DeepSeek Harness 的工作目录")'],
                capture_output=True, text=True, timeout=600,
            )
            chosen = (proc.stdout or "").strip()
            if proc.returncode == 0 and chosen and Path(chosen).is_dir():
                return chosen
        except Exception as exc:
            say(f"[!] 打开文件夹选择框失败: {exc}")
        return None

    for tool, args in (
        ("zenity", ["--file-selection", "--directory", "--title=选择工作目录"]),
        ("kdialog", ["--getexistingdirectory", str(Path.home())]),
    ):
        exe = shutil.which(tool)
        if not exe:
            continue
        try:
            proc = subprocess.run([exe, *args], capture_output=True, text=True, timeout=600)
            chosen = (proc.stdout or "").strip()
            if proc.returncode == 0 and chosen and Path(chosen).is_dir():
                return chosen
        except Exception:
            continue
    return None


def resolve_workspace(cfg: dict) -> tuple[Path | None, str]:
    """把 workspace 配置解析成一个真实目录。返回 (目录, 说明)；取消选择时目录为 None。"""
    mode = str(cfg.get("workspace", "last")).strip()
    low = mode.lower()

    if low == "last":
        found, why = last_used_workspace()
        if found:
            return Path(found), why
        fallback = cfg.get("fallback_workspace") or str(Path.home())
        return Path(str(fallback)).expanduser(), f"{why}，回退到 {fallback}"

    if low == "ask":
        initial = cfg.get("_initial_workspace")
        if not initial:
            initial, _ = last_used_workspace()
        chosen = pick_directory_native(initial)
        if not chosen:
            return None, "已取消选择目录"
        return Path(chosen), "手动选择"

    if low == "home":
        return Path.home(), "主目录（中立起点，不属于任何项目工作区）"

    if low == "cwd":
        return Path.cwd(), "快捷方式「起始位置」目录"

    return Path(mode).expanduser(), "固定目录"


# --------------------------------------------------------------------------
# 端口探测
# --------------------------------------------------------------------------
def port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    for family, addr in ((socket.AF_INET, (host, port)),):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                if sock.connect_ex(addr) == 0:
                    return True
        except Exception:
            continue
    return False


def looks_like_dsh(body: str) -> bool:
    return "DeepSeek Harness" in body or "__DSH_BOOT__" in body


def probe_url(url: str, timeout: float = 2.5) -> str | None:
    """返回 'dsh' / 'other' / None(无响应)。

    注意：从 dsh 0.1.5 起，Web GUI 用"进程 token"保护，不带 token 访问 / 会返回
    401 + 固定文案。这也算"DSH 正在运行"，不能当成别的程序占用端口。
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "dsh-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(300_000).decode("utf-8", "replace")
        return "dsh" if looks_like_dsh(body) else "other"
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(20_000).decode("utf-8", "replace")
        except Exception:
            body = ""
        if exc.code in (401, 403) and AUTH_REQUIRED_MARKER in body:
            return "dsh"
        return "other"
    except Exception:
        return None


# --------------------------------------------------------------------------
# 会话地址记录
#
# dsh 0.1.5+ 的 Web GUI 需要"进程 token"：启动时打印的地址形如
#     dsh web: http://127.0.0.1:3080/?token=xxxx
# 这个 token 只存在于进程内存里（不落盘），浏览器用它换一个持久 cookie。
# 所以启动器必须：
#   1. 从子进程输出里抓到这个带 token 的地址，用它打开浏览器；
#   2. 把它记下来，下次"复用已有实例"时才能依然打开可用的页面。
# --------------------------------------------------------------------------
def session_state_file() -> Path:
    return dsh_home() / "launcher-session.json"


def save_session_state(url: str, port: int, pid: int | None) -> None:
    try:
        path = session_state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "url": url,
                "port": port,
                "pid": pid,
                "savedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        say(f"[!] 记录会话地址失败: {exc}")


def load_session_state() -> dict:
    try:
        data = json.loads(session_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def clear_session_state() -> None:
    try:
        session_state_file().unlink()
    except OSError:
        pass


def token_url_from_line(line: str) -> str | None:
    """从 dsh 的输出行里取出带 token 的地址（形如 `dsh web: http://...?token=...`）。"""
    if "dsh web:" not in line:
        return None
    match = URL_IN_LINE_RE.search(line)
    return match.group(1) if match else None


def reuse_url_for(port: int, bare_url: str) -> tuple[str, bool]:
    """复用已有实例时，优先用上次记录的带 token 地址。返回 (地址, 是否带 token 有效)。"""
    state = load_session_state()
    if state.get("port") == port and isinstance(state.get("url"), str):
        recorded = state["url"]
        if probe_url(recorded, timeout=2.0) == "dsh":
            return recorded, True
    return bare_url, False


def open_browser(url: str) -> None:
    say(f"[*] 正在打开浏览器: {url}")
    try:
        if not webbrowser.open(url, new=2):
            raise RuntimeError("webbrowser.open 返回 False")
    except Exception as exc:
        say(f"[!] 自动打开浏览器失败({exc})，请手动访问: {url}")


def pause_if_needed(cfg: dict) -> None:
    if not cfg.get("pause_on_error") or not has_console():
        return
    try:
        input("按回车键关闭此窗口...")
    except Exception:
        pass


def child_env() -> dict:
    """准备给 dsh 子进程的环境变量。

    重点是清掉 PyInstaller onefile 注入的引导变量（_PYI_*/_MEI*）：本启动器就是
    用 PyInstaller 打包的，这些变量会被 dsh 服务继承进整个 DSH 会话；之后在会话里
    再运行任何 PyInstaller 打包的 exe，都会撞上
    "Security validation failure: parent process has different executable"。
    """
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("_PYI") or k.startswith("_MEI")]:
        env.pop(key, None)

    if not env.get("DSH_HOME"):
        guess = Path.home() / ".dsh"
        try:
            if guess.exists():
                env["DSH_HOME"] = str(guess)
        except Exception:
            pass

    node = find_node()
    if node:
        node_dir = str(Path(node).parent)
        if node_dir.lower() not in env.get("PATH", "").lower():
            env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
    return env


def fail(cfg: dict, message: str, code: int = 1) -> int:
    say("")
    say(f"[X] {message}")
    say(f"    详细日志: {cfg.get('_log_path', '(未启用)')}")
    pause_if_needed(cfg)
    return code


def run_server(cfg: dict) -> int:
    url = cfg["url"]

    # --- 1) 端口上已有服务？（先判断，复用时就无需再问工作目录） ---
    if port_open(cfg["host"], cfg["port"]):
        kind = probe_url(url)
        if kind == "dsh":
            if cfg["reuse_existing"]:
                say(f"[=] 检测到 {APP_TITLE} 已在 {url} 运行，直接复用现有实例。")
                target, fresh = reuse_url_for(cfg["port"], url)
                if fresh:
                    say("[*] 使用上次记录的带 token 地址打开。")
                else:
                    say("[!] 没有可用的带 token 地址（这个实例不是本启动器拉起的，或它重启过）。")
                    say("    新版 dsh 需要进程 token；若页面提示需要认证，请到那个实例的窗口里")
                    say("    复制它以 `dsh web:` 开头打印的完整链接打开一次（浏览器会记住 cookie）。")
                if cfg["open_browser"]:
                    open_browser(target)
                time.sleep(max(0.0, float(cfg["reuse_exit_delay"])))
                return 0
            return fail(
                cfg,
                f"端口 {cfg['port']} 上已有 DSH 服务在运行，且当前使用 --new（强制新开）。\n"
                f"    请改用其它端口，例如: DeepSeekHarness.exe --port 3081",
                3,
            )
        return fail(
            cfg,
            f"端口 {cfg['port']} 已被其它程序占用（响应的不是 DSH）。\n"
            f"    请换一个端口，例如: DeepSeekHarness.exe --port 3081",
            2,
        )

    # --- 2) 解析工作目录（last / ask / home / cwd / 固定目录） ---
    workspace, reason = resolve_workspace(cfg)
    if workspace is None:
        say(f"[*] {reason}，本次不启动。")
        return 0
    try:
        workspace.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return fail(cfg, f"无法创建/访问工作目录 {workspace}: {exc}")
    cfg["workspace"] = str(workspace)
    say(f"[*] 工作目录(workspace): {workspace}")
    say(f"    依据: {reason}")

    # --- 3) 组装命令 ---
    command = resolve_dsh_command(cfg)
    if not command:
        return fail(
            cfg,
            "找不到 dsh 或 node。请确认已安装 Node.js，并执行过:\n"
            "    npm i -g @deepseek-ai/dsh",
            4,
        )

    say(f"[*] 启动方式: {cfg.get('_how')}")
    say(f"[*] 执行命令: {' '.join(command)}")
    say("")

    # --- 4) 准备子进程环境 ---
    env = child_env()

    # 始终用管道接管子进程输出：既要写日志/控制台，也要从里面抓带 token 的地址
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(workspace),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except Exception as exc:
        return fail(cfg, f"启动失败: {exc}", 5)

    captured: dict[str, str | None] = {"url": None}

    def pump() -> None:
        stream = proc.stdout
        if stream is None:
            return
        try:
            for line in stream:
                text = line.rstrip("\n")
                if captured["url"] is None:
                    found = token_url_from_line(text)
                    if found:
                        captured["url"] = found
                say(text)
        except Exception:
            pass

    threading.Thread(target=pump, name="dsh-output", daemon=True).start()

    # --- 5) 等服务就绪 ---
    deadline = time.time() + max(5, int(cfg["startup_timeout"]))
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        target = captured["url"] or url
        if port_open(cfg["host"], cfg["port"]) and probe_url(target, timeout=2.0) == "dsh":
            ready = True
            break
        time.sleep(0.5)

    if not ready and proc.poll() is not None:
        code = proc.returncode
        say("")
        return fail(cfg, f"dsh 进程提前退出（退出码 {code}），服务未能启动。", 6 if code == 0 else code)

    # 给抓取线程一点时间把地址那行读完
    for _ in range(10):
        if captured["url"]:
            break
        time.sleep(0.2)
    open_url = captured["url"] or url

    if not ready:
        say(f"[!] 等待 {cfg['startup_timeout']} 秒仍未就绪，先尝试打开浏览器…")
    else:
        say("")
        say(f"[OK] {APP_TITLE} 已就绪: {open_url}")

    if captured["url"]:
        save_session_state(captured["url"], cfg["port"], proc.pid)
    else:
        say("[!] 没能从 dsh 输出里抓到带 token 的地址（新版 dsh 会要求 token）。")
        say("    如果页面提示需要认证，请看本窗口上方 `dsh web: ...` 那行并手动打开。")

    if cfg["open_browser"]:
        open_browser(open_url)

    say("")
    say("[*] 服务运行中。关闭本窗口或按 Ctrl+C 即可停止 DeepSeek Harness。")
    say("")

    try:
        code = proc.wait()
    except KeyboardInterrupt:
        say("")
        say("[*] 收到 Ctrl+C，正在停止服务…")
        try:
            proc.terminate()
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        say("[OK] 已停止。")
        return 0

    if code not in (0, None):
        return fail(cfg, f"dsh 进程退出，退出码 {code}。", code)
    say("[OK] 服务已退出。")
    return 0


# --------------------------------------------------------------------------
# 体检
# --------------------------------------------------------------------------
def selftest(cfg: dict) -> int:
    banner()
    say("[环境体检]")
    say(f"  平台            : {sys.platform} / Python {sys.version.split()[0]}")
    say(f"  程序所在目录    : {base_dir()}")
    say(f"  配置文件        : {cfg.get('_config_file', '(未使用)')}")
    mode = str(cfg["workspace"])
    label = f"{mode}（模式）" if mode.lower() in WORKSPACE_MODES else f"{mode}（固定目录）"
    say(f"  工作区设置      : {label}")
    rows = read_dsh_workspaces()
    usable = [r for r in rows if Path(r["path"]).is_dir()]
    say(f"  DSH 工作区记录  : {len(rows)} 个，其中目录仍存在 {len(usable)} 个")
    last, why = last_used_workspace()
    say(f"  上一个工作区    : {last or '无'}  ({why})")
    say(f"  注册表文件      : {dsh_workspace_file()}  存在={dsh_workspace_file().is_file()}")
    say(f"  监听地址        : {cfg['host']}:{cfg['port']}")
    say(f"  DSH_HOME        : {os.environ.get('DSH_HOME') or str(dsh_home()) + ' (默认)'}")
    say(f"  日志文件        : {cfg.get('_log_path', '(未启用)')}")
    node = find_node()
    say(f"  node            : {node or '未找到'}")
    entry = find_dsh_entry()
    say(f"  dsh 入口        : {entry or '未找到'}")
    command = resolve_dsh_command(cfg)
    say(f"  启动命令        : {' '.join(command) if command else '不可用'}")
    occupied = port_open(cfg["host"], cfg["port"])
    kind = probe_url(cfg["url"]) if occupied else None
    if occupied and kind == "dsh":
        state = "DSH 服务在运行（双击快捷方式将直接复用并打开浏览器）"
    elif occupied:
        state = "被其它程序占用（需要换端口）"
    else:
        state = "空闲（可以正常启动）"
    say(f"  端口 {cfg['port']} 状态 : {state}")
    say("")
    say("体检完成。" if command else "体检发现问题：无法定位 dsh，请检查 Node.js / 全局安装。")
    return 0 if command else 4


def list_workspaces() -> int:
    banner()
    rows = read_dsh_workspaces()
    if not rows:
        say(f"[!] 没读到工作区记录: {dsh_workspace_file()}")
        return 1
    rows.sort(key=lambda r: (r["updatedAt"], r["createdAt"]), reverse=True)
    say(f"DSH 记录过的工作区（按最近使用排序）: {dsh_workspace_file()}")
    say("")
    for i, row in enumerate(rows, 1):
        exists = "存在" if Path(row["path"]).is_dir() else "目录已不存在"
        mark = " <- 上一个工作区（默认会用它）" if i == 1 and Path(row["path"]).is_dir() else ""
        say(f"  {i}. {row['title']}")
        say(f"     {row['path']}")
        say(f"     {exists} · 最近更新 {row['updatedAt'] or '未知'}{mark}")
    say("")
    say("想固定用其中某个: DeepSeekHarness.exe --workspace \"<上面的路径>\"")
    return 0


def print_config(cfg: dict) -> int:
    public = {k: v for k, v in cfg.items() if not k.startswith("_")}
    say(json.dumps(public, ensure_ascii=False, indent=2))
    return 0


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    set_console_title(f"{APP_TITLE} 启动器")
    cfg = resolve_config(argv)
    log_file = Path(cfg["log_file"]).expanduser() if cfg.get("log_file") else (dsh_home() / "launcher.log")
    cfg["_log_path"] = str(log_file)
    open_log(log_file)

    # ask 模式下预选"上一个工作区"，让弹框一打开就停在上次的位置
    if str(cfg["workspace"]).lower() == "ask":
        cfg["_initial_workspace"] = last_used_workspace()[0]

    if cfg["_print_config"]:
        return print_config(cfg)
    if cfg["_list_workspaces"]:
        return list_workspaces()
    if cfg["_selftest"]:
        return selftest(cfg)

    if not cfg.get("quiet"):
        banner()
        say(f"[*] 目标地址: {cfg['url']}")
    return run_server(cfg)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
