#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek Harness 启动器：图标生成 + 打包 exe + 创建快捷方式
==========================================================

一条命令搞定（直接双击本文件也可以，前提是装了 Python）：

    python build_and_install.py                 # 生成图标 -> 打包 exe -> 桌面 + 开始菜单快捷方式
    python build_and_install.py --skip-build    # 不重新打包，只用现有 exe 重建快捷方式
    python build_and_install.py --no-shortcuts  # 只打包，不建快捷方式
    python build_and_install.py --windowed      # 打包成无控制台窗口的版本
    python build_and_install.py --mac           # 在 macOS 上创建 .command / .app

产物：
    dsh-harness.ico / dsh-harness.png     图标
    dist/DeepSeekHarness.exe              独立可执行文件
    桌面、开始菜单的 "DeepSeek Harness" 快捷方式
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP_NAME = "DeepSeek Harness"
EXE_NAME = "DeepSeekHarness"
IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"
ROOT = Path(__file__).resolve().parent
# 快捷方式的"起始位置"。注意：启动器默认用 last 模式（接着上次的工作区）在运行时
# 决定真正的工作目录，所以这里只影响 --workspace cwd 模式。
DEFAULT_WORKSPACE = str(ROOT)


def say(message: str = "") -> None:
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(message).encode(enc, "replace").decode(enc, "replace"), flush=True)


# --------------------------------------------------------------------------
# 1. 图标（DeepSeek 官方鲸鱼标志，见 make_logo_icon.py）
# --------------------------------------------------------------------------
def ensure_icon(style: str = "blue-on-white", regen: bool = False) -> tuple[Path | None, Path | None]:
    """返回 (ico, png)。配色没变就复用现成的 dsh-harness.ico，变了就重画。"""
    ico_path = ROOT / "dsh-harness.ico"
    png_path = ROOT / "dsh-harness.png"

    recorded = None
    try:
        recorded = (ROOT / ".icon-style").read_text(encoding="utf-8").strip()
    except OSError:
        pass

    if ico_path.is_file() and not regen and recorded == style:
        say(f"[*] 复用已有图标: {ico_path.name}（配色 {style}；要重画用 --regen-icon）")
        return ico_path, (png_path if png_path.is_file() else None)

    try:
        import make_logo_icon
    except ImportError as exc:
        say(f"[!] 无法导入 make_logo_icon.py（{exc}），跳过图标生成")
        return (ico_path if ico_path.is_file() else None,
                png_path if png_path.is_file() else None)

    if recorded and recorded != style:
        say(f"[*] 配色从 {recorded} 改为 {style}，重新生成图标…")
    else:
        say(f"[*] 用 DeepSeek 官方标志生成图标（配色 {style}）…")
    try:
        ico = make_logo_icon.build(style, 1024)
    except SystemExit as exc:
        say(f"[!] 官方标志不可用（{exc}），沿用已有图标")
        return (ico_path if ico_path.is_file() else None,
                png_path if png_path.is_file() else None)

    if IS_MACOS:
        try:
            from PIL import Image

            icon = Image.open(png_path)
            make_icns_macos(icon, ROOT / "dsh-harness.icns")
        except Exception:
            pass
    return ico, (png_path if png_path.is_file() else None)



def make_icns_macos(icon, out_path: Path) -> None:
    """借用 macOS 自带 iconutil 生成 .icns（仅 macOS）。"""
    iconutil = shutil.which("iconutil")
    if not iconutil:
        return
    try:
        from PIL import Image
    except ImportError:
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 64, 128, 256, 512):
            icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            icon.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run([iconutil, "-c", "icns", str(iconset), "-o", str(out_path)], check=False)
        if out_path.exists():
            say(f"[OK] 图标已生成: {out_path.name}")


# --------------------------------------------------------------------------
# 2. 打包 exe
# --------------------------------------------------------------------------
def prepare_target(target: Path) -> str | None:
    """打包前处理"目标 exe 正被运行中的实例占用"。

    Windows 不允许覆盖正在运行的 exe，但允许给它改名。因为快捷方式启动的
    DeepSeek Harness 可能正开着（甚至就是正在跑这条命令的那个窗口），所以这里
    把被占用的旧 exe 改名让位：正在运行的实例完全不受影响，下次启动才换新版本。

    返回 None 表示无需处理，返回以 "__FAIL__" 开头表示必须由用户先关掉。
    """
    if not target.exists():
        cleanup_stale(target)
        return None
    try:
        with open(target, "r+b"):
            cleanup_stale(target)  # 没被占用，顺手清理上次留下的旧 exe
            return None
    except PermissionError:
        pass
    except OSError:
        return None

    stale = target.with_name(f"{target.stem}-old{target.suffix}")
    try:
        if stale.exists():
            stale.unlink()  # 上一次打包留下的，可能已经解锁
    except OSError:
        pass
    try:
        target.rename(stale)
    except OSError as exc:
        return f"__FAIL__{exc}"
    return (f"[!] {target.name} 正被运行中的 DeepSeek Harness 占用。\n"
            f"    已改名为 {stale.name} 让位，继续打包；正在运行的那个窗口不受影响，\n"
            f"    下次关掉它、用快捷方式重新打开时就会用上新版本。")


def cleanup_stale(target: Path) -> None:
    """删掉上次"让位改名"留下的 *-old.exe（还锁着就留到下次）。"""
    stale = target.with_name(f"{target.stem}-old{target.suffix}")
    try:
        if stale.exists():
            stale.unlink()
            say(f"[*] 已清理上次留下的 {stale.name}")
    except OSError:
        pass


def ensure_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401

        return True
    except ImportError:
        pass
    say("[*] 正在安装 PyInstaller …（首次需要联网，约十几 MB）")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"],
        text=True,
    )
    if proc.returncode != 0:
        say("[X] PyInstaller 安装失败。可手动执行: python -m pip install pyinstaller")
        return False
    try:
        import PyInstaller  # noqa: F401

        return True
    except ImportError:
        say("[X] PyInstaller 安装后仍无法导入，请检查 Python 环境。")
        return False


def build_exe(icon: Path | None, windowed: bool) -> Path | None:
    if not ensure_pyinstaller():
        return None

    entry = ROOT / "dsh_launcher.py"
    if not entry.is_file():
        say(f"[X] 找不到入口脚本: {entry}")
        return None

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--console" if not windowed else "--windowed",
        "--name", EXE_NAME,
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if icon and icon.is_file():
        cmd += ["--icon", str(icon)]
    cmd.append(str(entry))

    say("")
    say(f"[*] 开始打包: {' '.join(cmd)}")
    say("")

    note = prepare_target(ROOT / "dist" / (EXE_NAME + (".exe" if IS_WINDOWS else "")))
    if note and note.startswith("__FAIL__"):
        say(f"[X] 无法为打包腾出 {EXE_NAME}（{note[8:]}）。")
        say("    请先关闭正在运行的 DeepSeek Harness 窗口，然后重新运行本脚本。")
        return None
    if note:
        say(note)

    proc = subprocess.run(cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        say("")
        say("[X] 打包失败。常见原因：")
        say("    - 当前 Python 版本太新/太旧，PyInstaller 不支持（可换 py -3.12 再试）")
        say("    - 杀毒软件拦截写入 dist/ 目录")
        return None

    exe = ROOT / "dist" / (EXE_NAME + (".exe" if IS_WINDOWS else ""))
    if not exe.is_file():
        say("[X] 打包结束但没有找到产物，请检查 dist 目录。")
        return None
    say("")
    say(f"[OK] 打包完成: {exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    return exe


# --------------------------------------------------------------------------
# 3. Windows 快捷方式
# --------------------------------------------------------------------------
def ps_quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def create_windows_shortcuts(target: Path, workspace: str, icon: Path | None,
                            extra_args: str, name: str, do_desktop: bool,
                            do_startmenu: bool) -> int:
    ps_exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    icon_loc = f"{icon},0" if icon and icon.is_file() else f"{target},0"

    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$exe = {ps_quote(target)}",
        f"$ws  = {ps_quote(workspace)}",
        f"$ico = {ps_quote(icon_loc)}",
        f"$arg = {ps_quote(extra_args)}",
        f"$nm  = {ps_quote(name)}",
        "$targets = @()",
    ]
    if do_desktop:
        lines.append("$targets += Join-Path ([Environment]::GetFolderPath('Desktop')) ($nm + '.lnk')")
    if do_startmenu:
        lines.append("$targets += Join-Path ([Environment]::GetFolderPath('Programs')) ($nm + '.lnk')")
    lines += [
        "foreach ($t in $targets) {",
        "  $dir = Split-Path -Parent $t",
        "  if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }",
        "  $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($t)",
        "  $sh.TargetPath = $exe",
        "  $sh.WorkingDirectory = $ws",
        "  $sh.IconLocation = $ico",
        "  $sh.Description = 'DeepSeek Harness - 一键启动'",
        "  $sh.WindowStyle = 1",
        "  if ($arg -ne '') { $sh.Arguments = $arg }",
        "  $sh.Save()",
        "  Write-Output ('[OK] 快捷方式: ' + $t)",
        "}",
    ]

    script = "\n".join(lines) + "\n"
    tmp = Path(tempfile.gettempdir()) / "dsh_make_shortcuts.ps1"
    # 必须带 BOM：Windows PowerShell 5.1 否则按 ANSI 读取，中文路径会乱码
    tmp.write_text(script, encoding="utf-8-sig")

    proc = subprocess.run(
        [ps_exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.stdout:
        for line in proc.stdout.splitlines():
            say(line)
    if proc.returncode != 0:
        say("[X] 创建快捷方式失败：")
        say((proc.stderr or "").strip() or "(PowerShell 无错误输出)")
        return 1
    return 0


# --------------------------------------------------------------------------
# 4. macOS 快捷方式（.command 与 .app 包）
# --------------------------------------------------------------------------
def create_macos_shortcuts(target: Path | None, workspace: str, port: int,
                           do_desktop: bool, do_applications: bool) -> int:
    if target and target.is_file():
        launcher_cmd = f'exec {shlex_quote(str(target))} --workspace {shlex_quote(workspace)} --port {port}'
    else:
        script = ROOT / "dsh_launcher.py"
        launcher_cmd = (
            f'exec /usr/bin/env python3 {shlex_quote(str(script))} '
            f'--workspace {shlex_quote(workspace)} --port {port}'
        )

    body = "#!/bin/zsh\n# DeepSeek Harness 启动脚本\n" + launcher_cmd + "\n"
    count = 0

    if do_desktop:
        path = Path.home() / "Desktop" / f"{APP_NAME}.command"
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
        say(f"[OK] 快捷方式: {path}")
        count += 1

    if do_applications:
        app = Path.home() / "Applications" / f"{APP_NAME}.app"
        macos_dir = app / "Contents" / "MacOS"
        res_dir = app / "Contents" / "Resources"
        macos_dir.mkdir(parents=True, exist_ok=True)
        res_dir.mkdir(parents=True, exist_ok=True)

        runner = macos_dir / EXE_NAME
        runner.write_text(body, encoding="utf-8")
        runner.chmod(0o755)

        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>{APP_NAME}</string>
  <key>CFBundleDisplayName</key><string>{APP_NAME}</string>
  <key>CFBundleExecutable</key><string>{EXE_NAME}</string>
  <key>CFBundleIdentifier</key><string>ai.deepseek.harness.launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleIconFile</key><string>icon.icns</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
"""
        (app / "Contents" / "Info.plist").write_text(plist, encoding="utf-8")
        icns = ROOT / "dsh-harness.icns"
        if icns.is_file():
            shutil.copy2(icns, res_dir / "icon.icns")
        say(f"[OK] 应用包: {app}")
        count += 1

    if count == 0:
        say("[!] 没有创建任何 macOS 快捷方式（需要 --desktop 或 --applications）")
    return 0


def shlex_quote(text: str) -> str:
    import shlex

    return shlex.quote(text)


# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="打包 DeepSeek Harness 启动器并创建快捷方式")
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE,
                        help="快捷方式的起始位置目录（仅 --workspace cwd 模式会用到）")
    parser.add_argument("--port", type=int, default=3080, help="端口（用于 macOS 脚本与快捷方式参数）")
    parser.add_argument("--name", default=APP_NAME, help="快捷方式显示名称")
    parser.add_argument("--exe", help="指定现成的 exe（配合 --skip-build）")
    parser.add_argument("--icon", help="指定现成的 .ico")
    parser.add_argument("--icon-style", choices=["white-on-blue", "blue-on-white"],
                        default="blue-on-white",
                        help="蓝鲸鱼+白底（默认）或白鲸鱼+官方品牌蓝底")
    parser.add_argument("--regen-icon", action="store_true",
                        help="强制用 DeepSeek 官方标志重画图标")
    parser.add_argument("--skip-build", action="store_true", help="跳过打包")
    parser.add_argument("--windowed", action="store_true", help="打包为无控制台窗口")
    parser.add_argument("--no-shortcuts", action="store_true", help="只打包，不创建快捷方式")
    parser.add_argument("--desktop", action="store_true", help="只创建桌面快捷方式")
    parser.add_argument("--startmenu", action="store_true", help="只创建开始菜单快捷方式")
    parser.add_argument("--applications", action="store_true", help="(macOS) 创建 ~/Applications 应用包")
    parser.add_argument("--args", default="", help="写进快捷方式的固定参数，例如 --args \"--port 3081\"")
    opts = parser.parse_args()

    say("=" * 62)
    say(f" {APP_NAME} 安装器")
    say("=" * 62)
    say(f"[*] 项目目录: {ROOT}")
    say(f"[*] workspace: {opts.workspace}")
    say("")

    icon = Path(opts.icon).expanduser() if opts.icon else None
    if icon is None:
        ico, _png = ensure_icon(opts.icon_style, opts.regen_icon)
        icon = ico

    target: Path | None = None
    if opts.exe:
        target = Path(opts.exe).expanduser().resolve()
        if not target.is_file():
            say(f"[X] 指定的 exe 不存在: {target}")
            return 1
    elif not opts.skip_build:
        target = build_exe(icon, opts.windowed)
        if target is None:
            return 1
    else:
        guess = ROOT / "dist" / (EXE_NAME + (".exe" if IS_WINDOWS else ""))
        if guess.is_file():
            target = guess
            say(f"[*] 使用已有产物: {target}")

    if opts.no_shortcuts:
        say("[*] 按要求跳过快捷方式创建。")
        return 0

    # 决定创建哪些快捷方式
    explicit = opts.desktop or opts.startmenu or opts.applications
    if IS_WINDOWS:
        do_desktop = opts.desktop or not explicit
        do_startmenu = opts.startmenu or not explicit
    else:
        do_desktop = opts.desktop or not explicit
        do_applications = opts.applications or not explicit

    if target is None or not target.is_file():
        if not IS_MACOS:
            say("[X] 没有可用的可执行文件，无法创建快捷方式。先去掉 --skip-build 重新运行。")
            return 1
        say("[!] 没有 exe，将为 macOS 生成调用 python 脚本的启动器。")

    say("")
    if IS_WINDOWS:
        return create_windows_shortcuts(
            target, opts.workspace, icon, opts.args, opts.name, do_desktop, do_startmenu
        )
    return create_macos_shortcuts(target, opts.workspace, opts.port, do_desktop, do_applications)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
