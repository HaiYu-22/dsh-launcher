#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 官方鲸鱼标志 -> 应用图标
================================

用法：
    python make_logo_icon.py                 # 生成两种配色的 ico/png
    python make_logo_icon.py --ascii         # 顺便在终端里用字符画出图标，肉眼确认
    python make_logo_icon.py --style white-on-blue

标志来源：DeepSeek Harness 自带前端资源里的官方 favicon
（.../dsh-web-frontend/dist/favicon.svg，即 DeepSeek 自己产品里的官方鲸鱼路径）。
品牌蓝 #4D6BFE 为 DeepSeek 官方品牌色。

渲染方式：优先用本机 Edge/Chrome 无头模式栅格化（最忠实），
没有浏览器时退回内置的纯 Python 路径光栅化器（近似，够用）。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRAND_BLUE = "#4D6BFE"
ASSET_SVG = ROOT / "assets" / "deepseek-logo.svg"

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def say(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(msg).encode(enc, "replace").decode(enc, "replace"), flush=True)


# --------------------------------------------------------------------------
# 官方标志 SVG
# --------------------------------------------------------------------------
def official_svg_candidates() -> list[Path]:
    here = ROOT / "assets" / "deepseek-logo.svg"
    cands = [here]
    env = os.environ.get("DSH_LOGO_SVG")
    if env:
        cands.insert(0, Path(env).expanduser())
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        cands.append(
            Path(appdata) / "npm" / "node_modules" / "@deepseek-ai" / "dsh"
            / "node_modules" / "@deepseek-ai" / "dsh-web-frontend" / "dist" / "favicon.svg"
        )
    cands += [
        Path("/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-web-frontend/dist/favicon.svg"),
        Path("/opt/homebrew/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-web-frontend/dist/favicon.svg"),
    ]
    return cands


def extract_path_data(svg_text: str) -> str:
    """取出 <path d="..."> 里的路径数据（注意别匹配到 id="path"）。"""
    match = re.search(r'\sd="([^"]+)"', svg_text)
    if not match:
        raise ValueError("SVG 里找不到 path 的 d 属性")
    return match.group(1)


def load_logo_path() -> str:
    for cand in official_svg_candidates():
        try:
            if cand.is_file():
                data = extract_path_data(cand.read_text(encoding="utf-8", errors="replace"))
                if len(data) > 100:
                    say(f"[*] 标志来源: {cand}")
                    return data
        except Exception:
            continue
    raise SystemExit(
        "[X] 找不到官方标志 SVG。\n"
        "    请把 favicon.svg 放到 assets/deepseek-logo.svg，"
        "或用环境变量 DSH_LOGO_SVG 指定路径。"
    )


def write_asset_svg(path_data: str, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        '<!-- DeepSeek 官方鲸鱼标志（取自 DeepSeek Harness 前端 favicon.svg），'
        f'品牌蓝 {BRAND_BLUE} -->\n'
        '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50" viewBox="0 0 50 50">\n'
        f'\t<path fill="{BRAND_BLUE}" d="{path_data}"/>\n'
        "</svg>\n",
        encoding="utf-8",
    )


# --------------------------------------------------------------------------
# 渲染方式一：本机浏览器无头栅格化
# --------------------------------------------------------------------------
def find_browser() -> str | None:
    for cand in BROWSERS:
        if Path(cand).is_file():
            return cand
    for name in ("chrome", "msedge", "chromium", "chromium-browser",
                 "google-chrome", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def render_with_browser(path_data: str, size: int, color: str) -> "Image.Image | None":
    browser = find_browser()
    if not browser:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None

    html = (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        "html,body{margin:0;padding:0;background:transparent;overflow:hidden}"
        "</style></head><body>"
        f'<svg width="{size}" height="{size}" viewBox="0 0 50 50" '
        'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{path_data}" fill="{color}"/></svg></body></html>'
    )
    tmp = Path(tempfile.mkdtemp(prefix="dsh-logo-"))
    html_path = tmp / "logo.html"
    png_path = tmp / "logo.png"
    html_path.write_text(html, encoding="utf-8")

    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--default-background-color=00000000",
        f"--user-data-dir={tmp / 'profile'}",
        f"--window-size={size},{size}",
        f"--screenshot={png_path}",
        html_path.as_uri(),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
    except Exception:
        return None
    if not png_path.is_file():
        return None
    image = Image.open(png_path).convert("RGBA")
    if image.size != (size, size):
        image = image.crop((0, 0, min(size, image.width), min(size, image.height)))
    return image


# --------------------------------------------------------------------------
# 渲染方式二：纯 Python 路径光栅化（离线兜底）
# --------------------------------------------------------------------------
NUM_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
CMD_RE = re.compile(r"([MmLlHhVvCcSsZz])([^MmLlHhVvCcSsZz]*)")


def _cubic(p0, p1, p2, p3, steps=26):
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        pts.append((
            mt**3 * p0[0] + 3 * mt * mt * t * p1[0] + 3 * mt * t * t * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt * mt * t * p1[1] + 3 * mt * t * t * p2[1] + t**3 * p3[1],
        ))
    return pts


def parse_path(path_data: str) -> list[list[tuple[float, float]]]:
    """把 SVG path 解析成若干多边形（支持 M/L/H/V/C/S/Z，绝对与相对）。"""
    subpaths: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    pos = (0.0, 0.0)
    start = (0.0, 0.0)
    prev_ctrl = None

    for cmd, args_text in CMD_RE.findall(path_data):
        nums = [float(n) for n in NUM_RE.findall(args_text)]
        upper = cmd.upper()
        rel = cmd.islower()

        if upper == "M":
            for i in range(0, len(nums) - 1, 2):
                pt = (nums[i], nums[i + 1])
                if rel:
                    pt = (pos[0] + pt[0], pos[1] + pt[1])
                if i == 0:
                    if len(current) >= 3:
                        subpaths.append(current)
                    current = [pt]
                    start = pt
                else:
                    current.append(pt)
                pos = pt
                prev_ctrl = None
        elif upper in ("L", "H", "V"):
            step = 2 if upper == "L" else 1
            for i in range(0, len(nums) - step + 1, step):
                if upper == "L":
                    pt = (nums[i], nums[i + 1])
                elif upper == "H":
                    pt = (nums[i], pos[1])
                else:
                    pt = (pos[0], nums[i])
                if rel:
                    pt = (pos[0] + pt[0], pos[1] + pt[1])
                current.append(pt)
                pos = pt
                prev_ctrl = None
        elif upper == "C":
            for i in range(0, len(nums) - 5, 6):
                c1 = (nums[i], nums[i + 1])
                c2 = (nums[i + 2], nums[i + 3])
                end = (nums[i + 4], nums[i + 5])
                if rel:
                    c1 = (pos[0] + c1[0], pos[1] + c1[1])
                    c2 = (pos[0] + c2[0], pos[1] + c2[1])
                    end = (pos[0] + end[0], pos[1] + end[1])
                current.extend(_cubic(pos, c1, c2, end))
                pos, prev_ctrl = end, c2
        elif upper == "S":
            for i in range(0, len(nums) - 3, 4):
                c2 = (nums[i], nums[i + 1])
                end = (nums[i + 2], nums[i + 3])
                if rel:
                    c2 = (pos[0] + c2[0], pos[1] + c2[1])
                    end = (pos[0] + end[0], pos[1] + end[1])
                c1 = pos if prev_ctrl is None else (2 * pos[0] - prev_ctrl[0], 2 * pos[1] - prev_ctrl[1])
                current.extend(_cubic(pos, c1, c2, end))
                pos, prev_ctrl = end, c2
        elif upper == "Z":
            if len(current) >= 3:
                subpaths.append(current)
            current = []
            pos = start
            prev_ctrl = None

    if len(current) >= 3:
        subpaths.append(current)
    return subpaths


def render_pure_python(path_data: str, size: int, color: str, ss: int = 4):
    """用 Pillow 把路径填成蒙版（奇偶填充，带超采样抗锯齿）。"""
    from PIL import Image, ImageChops, ImageDraw

    subpaths = parse_path(path_data)
    if not subpaths:
        return None
    xs = [p[0] for sp in subpaths for p in sp]
    ys = [p[1] for sp in subpaths for p in sp]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    span = max(maxx - minx, maxy - miny) or 1.0
    scale = (size * ss) / span
    dim = size * ss

    # 每个子路径单独画，再用异或合成（等价于奇偶填充），logical_xor 在 C 层执行
    mask = Image.new("1", (dim, dim), 0)
    for sub in subpaths:
        layer = Image.new("1", (dim, dim), 0)
        ImageDraw.Draw(layer).polygon(
            [((x - minx) * scale, (y - miny) * scale) for x, y in sub], fill=1
        )
        mask = ImageChops.logical_xor(mask, layer)

    mask = mask.convert("L").resize((size, size), Image.LANCZOS)
    rgb = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(Image.new("RGBA", (size, size), rgb + (255,)), (0, 0), mask)
    return out


def render_whale(path_data: str, size: int, color: str):
    image = render_with_browser(path_data, size, color)
    if image is not None:
        say("[*] 渲染方式: 本机浏览器无头渲染（最忠实）")
        return image
    say("[!] 没找到 Edge/Chrome，改用内置光栅化器（近似结果）")
    return render_pure_python(path_data, size, color)


# --------------------------------------------------------------------------
# 组装图标
# --------------------------------------------------------------------------
def compose(whale, style: str, size: int = 1024):
    """把鲸鱼放进圆角方形里。style: white-on-blue | blue-on-white"""
    from PIL import Image, ImageDraw

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    margin = int(size * 0.039)
    radius = int(size * 0.205)

    if style == "white-on-blue":
        card_color, whale_color = BRAND_BLUE, (255, 255, 255, 255)
        border = None
    else:
        card_color, whale_color = "#FFFFFF", BRAND_BLUE
        border = (222, 226, 238, 255)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle([margin, margin, size - margin, size - margin],
                           radius=radius, fill=card_color,
                           outline=border, width=max(2, size // 200) if border else 0)

    # 鲸鱼本身是横向的（约 4:3），按宽度缩放到卡片宽度的 ~60% 再居中
    target_w = int((size - 2 * margin) * 0.62)
    ratio = target_w / whale.width
    wh = whale.resize((target_w, max(1, int(whale.height * ratio))), Image.LANCZOS)

    if style == "blue-on-white":
        alpha = wh.split()[3]
        tinted = Image.new("RGBA", wh.size, whale_color)
        tinted.putalpha(alpha)
        wh = tinted

    left = (size - wh.width) // 2
    top = (size - wh.height) // 2 - int(size * 0.012)  # 轻微上移，视觉居中
    canvas.alpha_composite(wh, (left, top))
    return canvas


def ascii_preview(image, cols: int = 74, rows: int = 33) -> str:
    """把图缩成字符画，方便在终端里肉眼确认形状。"""
    from PIL import Image
    small = image.convert("L").resize((cols, rows * 2), Image.LANCZOS)
    px = small.load()
    ramp = " .:-=+*#%@"
    lines = []
    for y in range(rows):
        row = []
        for x in range(cols):
            v = max(px[x, y * 2], px[x, y * 2 + 1])
            row.append(ramp[min(9, v // 26)])
        lines.append("".join(row))
    return "\n".join(lines)


def build(style: str, size: int = 1024, ascii_show: bool = False):
    path_data = load_logo_path()
    whale = render_whale(path_data, size, "#FFFFFF")
    if whale is None:
        raise SystemExit("[X] 鲸鱼标志渲染失败。")
    bbox = whale.split()[3].getbbox()
    if not bbox:
        raise SystemExit("[X] 渲染结果是空白的，标志数据可能有问题。")
    whale = whale.crop(bbox)
    say(f"[*] 标志尺寸: {whale.width}x{whale.height}")

    icon = compose(whale, style, size)

    # 每种配色都留一份带名字的副本
    variant_ico = ROOT / f"dsh-harness-{style}.ico"
    variant_png = ROOT / f"dsh-harness-{style}.png"
    icon.save(variant_png)
    icon.save(variant_ico, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])

    # dsh-harness.ico/.png 永远等于"当前这套配色"——exe 内嵌图标和快捷方式都用这个名字，
    # 这样换配色时不会出现"exe 是 A 版、快捷方式是 B 版"的错配。
    canonical_ico = ROOT / "dsh-harness.ico"
    canonical_png = ROOT / "dsh-harness.png"
    shutil.copy2(variant_ico, canonical_ico)
    shutil.copy2(variant_png, canonical_png)
    try:
        (ROOT / ".icon-style").write_text(style + "\n", encoding="utf-8")
    except OSError:
        pass
    say(f"[OK] 当前图标 {canonical_ico.name} = {style}（副本 {variant_ico.name}）")

    if ascii_show:
        say("")
        say(ascii_preview(icon))
        say("")
    return canonical_ico


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 DeepSeek 官方标志图标")
    parser.add_argument("--style", choices=["white-on-blue", "blue-on-white"],
                        default="blue-on-white",
                        help="蓝鲸鱼+白底（默认，官方应用图标观感）或白鲸鱼+品牌蓝底")
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--ascii", action="store_true", help="在终端用字符画出图标")
    parser.add_argument("--write-asset", action="store_true",
                        help="把官方 SVG 落盘到 assets/deepseek-logo.svg（需能读到本机 DSH 安装）")
    opts = parser.parse_args()

    if opts.write_asset:
        data = load_logo_path()
        write_asset_svg(data, ASSET_SVG)
        say(f"[OK] 已写入 {ASSET_SVG}")

    build(opts.style, opts.size, opts.ascii)
    return 0


if __name__ == "__main__":
    sys.exit(main())
