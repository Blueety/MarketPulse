"""一次性取证（修正指标版）：定位把帧率压到 ~10fps 的绘制层。

指标已修正：netScrollTop（净增量）与 pxPerSec，避免上一版「最后一帧增量」的误读。
每个相位**全新加载**（隔离），记录 fps / netScrollTop / pxPerSec / movedRatio / paused / raf。

用法：venv/Scripts/python tasks/2026-09-13-news-autoscroll/probe_ab2.py
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

SEG_JS = r"""
(ms) => new Promise((resolve) => {
  const el = document.getElementById('news-body');
  const st0 = el.scrollTop;
  let n = 0, moved = 0, prev = st0;
  const t0 = performance.now();
  const tick = (now) => {
    n++;
    if (Math.abs(el.scrollTop - prev) > 0.001) { moved++; prev = el.scrollTop; }
    const e = now - t0;
    if (e < ms) requestAnimationFrame(tick);
    else resolve({
      frames: n, fps: +(n / (e / 1000)).toFixed(1),
      netScrollTop: +(el.scrollTop - st0).toFixed(1),
      pxPerSec: +((el.scrollTop - st0) / (e / 1000)).toFixed(2),
      movedRatio: +(moved / n).toFixed(2),
      paused: window._newsPaused, raf: window._newsRaf, half: window._newsHalf,
      clientH: el.clientHeight, scrollH: el.scrollHeight,
    });
  };
  requestAnimationFrame(tick);
})
"""

PHASES = {
    "baseline": None,
    "news_blur_off": "#news{backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}",
    "all_blur_off": "*{backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}",
    "body_bg_off": "body{background-image:none !important;}",
    "willchange_scroll": "#news-body{will-change:scroll-position;}",
    "contain_paint": "#news{contain:paint;}",
    "news_layer": "#news{transform:translateZ(0);}",
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

            for name, css in PHASES.items():
                page.goto(url, wait_until="load")
                try:
                    page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                page.mouse.move(5, 5)
                if css:
                    page.add_style_tag(content=css)
                    page.wait_for_timeout(250)
                page.evaluate("() => { document.getElementById('news-body').scrollTop = 0; }")
                page.wait_for_timeout(200)
                r = page.evaluate(SEG_JS, 2000)
                out[name] = r
                print(f"{name}: {json.dumps(r, ensure_ascii=False)}")

            # 对照：完全停掉自动滚动（证明「滚动本身」是帧率杀手）
            page.goto(url, wait_until="load")
            try:
                page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            page.evaluate("() => window.stopNewsAutoScroll()")
            page.wait_for_timeout(200)
            out["autoscroll_stopped"] = page.evaluate(SEG_JS, 2000)
            print(f"autoscroll_stopped: {json.dumps(out['autoscroll_stopped'], ensure_ascii=False)}")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    path = Path(vu.OUT_DIR) / "probe-ab2.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
