"""背景细纹理「强度与周期」标定（一次性设计工具，可复跑）。

用途：需求方选定方案 H（G 光斑 + 细纹理）。但 plan 里给的第一版纹理 alpha=.022、
周期 6px 经实测**仅在感知阈值附近**（G vs H 差分：3.1% 像素、最大 6 个色阶）→
等于「拿到的基本还是 G」。本工具标定纹理的 alpha 与周期，使其真正可见，
并给出「局部高频振幅」作为客观判据。

要点（第一版设计缺陷）：纹理原为 `--ambient-1` 的**最后一层**（最底），会被上面
3 层渐变按 (1-α) 逐层衰减（在光斑最亮处衰减到约 52%）。本工具把纹理放到**最上层**，
保持标称振幅。

用法（项目根执行）：
    venv/Scripts/python -m uvicorn web.app:app --port 8031
    venv/Scripts/python tasks/2026-09-11-glassmorphism-fix/probe_texture.py --port 8031

产出（落 %TEMP%/mp_glass_cmp/，不进仓库）：
    tex-{case}.png + stdout 的 RESULT 行
"""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageStat
from playwright.sync_api import sync_playwright

OUT_DIR = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "mp_glass_cmp"

# 与方案 G 相同的强光斑氛围（纹理叠加在它之上）
GLOW = (
    "radial-gradient(760px 520px at 30% 12%, rgba(150,200,255,.35), transparent 58%), "
    "radial-gradient(900px 620px at 74% 34%, rgba(120,170,255,.14), transparent 60%), "
    "linear-gradient(148deg, transparent 18%, rgba(120,160,220,.07) 40%, transparent 64%)"
)

# (case, tex_alpha, tex_period_px)；tex_alpha=None 表示不加纹理（基准）
CASES = [
    ("base", None, None),
    ("t1", 0.022, 6),
    ("t2", 0.045, 6),
    ("t3", 0.055, 6),
    ("t4", 0.070, 6),
]

# 取样框 A：卡片之间的背景缝隙（.row-kpi 与 .row-main 之间 16px 高、全宽）
#           → 纹理「未被 backdrop-filter 糊掉」的真实可见处
FLAT_GAP = (320, 178, 1380, 192)
# 取样框 B：卡片内部（#watchlist-section 空白处）
#           → 纹理已被 backdrop-filter 模糊，理论上振幅应显著低于 A（磨砂玻璃的正确表现）
FLAT_INCARD = (1500, 470, 1860, 570)


def tex_layer(alpha: float, period: int) -> str:
    return ("repeating-linear-gradient(115deg, rgba(255,255,255,"
            + ("%.3f" % alpha) + ") 0 1px, rgba(255,255,255,0) 1px "
            + str(period) + "px)")


def css(alpha, period) -> str:
    layers = ([tex_layer(alpha, period)] if alpha else []) + [GLOW]
    return (":root,[data-theme=dark]{"
            "--glass-bg:rgba(255,255,255,.035);"
            "--glass-blur:blur(20px) saturate(150%);"
            "--ambient-1:" + ", ".join(layers) + ";"
            "--ambient-2:none;}")


def amplitude(path: Path, box) -> float:
    """局部高频振幅：区域减去高斯模糊自身后的标准差（越高 = 纹路越明显）。"""
    im = Image.open(path).convert("L").crop(box)
    resid = ImageChops.difference(im, im.filter(ImageFilter.GaussianBlur(2)))
    return ImageStat.Stat(resid).stddev[0]


def amp_pair(path: Path) -> tuple[float, float]:
    """返回 (背景缝隙振幅, 卡内振幅)。"""
    return amplitude(path, FLAT_GAP), amplitude(path, FLAT_INCARD)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8031)
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.add_init_script('try{localStorage.setItem("mp-theme","dark")}catch(e){}')
        for name, alpha, period in CASES:
            page.goto(url, wait_until="load")
            try:
                page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(1000)
            page.add_style_tag(content=css(alpha, period))
            page.wait_for_timeout(700)
            page.screenshot(path=str(OUT_DIR / f"tex-{name}.png"), full_page=True)
        browser.close()

    base_path = OUT_DIR / "tex-base.png"
    base_img = Image.open(base_path).convert("RGB")
    for name, alpha, period in CASES:
        path = OUT_DIR / f"tex-{name}.png"
        gap, incard = amp_pair(path)
        if alpha is None:
            print("RESULT %-5s tex=none        gapAmp=%.2f  cardAmp=%.2f  (baseline)"
                  % (name, gap, incard))
            continue
        diff = ImageChops.difference(base_img, Image.open(path).convert("RGB")).convert("L")
        px = list(diff.getdata())
        n = len(px)
        print("RESULT %-5s alpha=%.3f/%dpx  gapAmp=%.2f  cardAmp=%.2f  vs_base>2=%.1f%%  max=%d"
              % (name, alpha, period, gap, incard,
                 100.0 * sum(1 for v in px if v > 2) / n, max(px)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
