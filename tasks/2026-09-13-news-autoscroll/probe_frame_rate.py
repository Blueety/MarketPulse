"""一次性取证：区分「无头 Chromium 帧节流」与「页面真的卡」。

对同一页面测 4 组 rAF 帧率：默认启动 vs 关闭 vsync/帧率限制启动，各测 about:blank 与真实页面。
若 about:blank 也只有 ~10fps → 是环境节流，测量结论不能代表用户浏览器。

用法：venv/Scripts/python tasks/2026-09-13-news-autoscroll/probe_frame_rate.py
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
  let n = 0;
  const t0 = performance.now();
  const tick = () => {
    n++;
    const el = performance.now() - t0;
    if (el < ms) requestAnimationFrame(tick);
    else resolve({ frames: n, fps: +(n / (el / 1000)).toFixed(1) });
  };
  requestAnimationFrame(tick);
})
"""

FLAGS = ["--disable-gpu-vsync", "--disable-frame-rate-limit",
         "--run-all-compositor-stages-before-draw"]


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
            for label, args in (("default", []), ("no_vsync", FLAGS)):
                browser = p.chromium.launch(args=args)
                page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
                page.goto("about:blank")
                page.wait_for_timeout(300)
                blank = page.evaluate(FPS_JS, 1500)
                page.goto(url, wait_until="load")
                try:
                    page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
                except Exception:
                    pass
                page.wait_for_timeout(1200)
                page.mouse.move(5, 5)
                live = page.evaluate(FPS_JS, 1500)
                out[label] = {"about_blank": blank, "page": live}
                browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
