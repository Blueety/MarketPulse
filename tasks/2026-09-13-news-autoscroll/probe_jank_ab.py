"""一次性取证：定位「页面只有 ~9fps」的被拖累层（A/B 逐层排除）。

每轮 goto 全新加载 → 注入单个 CSS 变量 → 测 rAF 帧率 2s。对照项：
  idle            : 停掉自动滚动（stopNewsAutoScroll）→ 判断是「滚动触发」还是「页面本身」
  running         : 自动滚动运行中（基线，应 ≈9-10fps）
  no_blur         : 全页禁用 backdrop-filter（11 张玻璃卡 + 顶栏）
  no_ambient      : 去掉 body 的 4 层背景渐变（background-attachment: fixed）
  promote_news    : #news-body 加 will-change:scroll-position + contain:paint
  blur_and_ambient: 同时禁用上面两者

用法：venv/Scripts/python tasks/2026-09-13-news-autoscroll/probe_jank_ab.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "vu", ROOT / "tasks" / "2026-09-11-frontend-bento-redesign" / "verify_ui.py"
)
vu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vu)

FPS_JS = r"""
(ms) => new Promise((resolve) => {
  const el = document.getElementById('news-body');
  let n = 0, moved = 0, prev = el.scrollTop;
  const t0 = performance.now();
  const tick = () => {
    n++;
    if (Math.abs(el.scrollTop - prev) > 0.001) { moved++; prev = el.scrollTop; }
    const e = performance.now() - t0;
    if (e < ms) requestAnimationFrame(tick);
    else resolve({ frames: n, fps: +(n / (e / 1000)).toFixed(1),
                   movedRatio: +(moved / n).toFixed(2),
                   scrollTop: +el.scrollTop.toFixed(1) });
  };
  requestAnimationFrame(tick);
})
"""

CSS = {
    "no_blur": "*{backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}",
    "no_ambient": "body{background-image:none !important;}",
    "promote_news": "#news-body{will-change:scroll-position;contain:paint;}",
    "blur_and_ambient": ("*{backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}"
                         "body{background-image:none !important;}"),
}


def main() -> int:
    port = vu.free_port()
    url = f"http://127.0.0.1:{port}/"
    proc = subprocess.Popen(
        [str(vu.PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    out: dict = {}
    try:
        vu.wait_ready(url)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            page.add_init_script("try { localStorage.setItem('mp-theme', 'dark'); } catch (e) {}")

            def phase(name: str, css: str | None = None, idle: bool = False) -> None:
                page.goto(url, wait_until="load")
                try:
                    page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
                except Exception:
                    pass
                page.wait_for_timeout(1200)
                page.mouse.move(5, 5)
                if css:
                    page.add_style_tag(content=css)
                    page.wait_for_timeout(200)
                if idle:
                    page.evaluate("() => window.stopNewsAutoScroll && window.stopNewsAutoScroll()")
                    page.wait_for_timeout(300)
                out[name] = page.evaluate(FPS_JS, 2000)
                print(f"{name}: {json.dumps(out[name], ensure_ascii=False)}")

            phase("running")
            phase("idle", idle=True)
            phase("no_blur", css=CSS["no_blur"])
            phase("no_ambient", css=CSS["no_ambient"])
            phase("promote_news", css=CSS["promote_news"])
            phase("blur_and_ambient", css=CSS["blur_and_ambient"])
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    path = Path(vu.OUT_DIR) / "probe-jank-ab.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
