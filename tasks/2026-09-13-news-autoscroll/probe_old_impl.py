"""一次性取证（反证）：同一页面、同样 0.4px/帧 的增量，对比「旧实现」与「新实现」。

旧：el.scrollTop += 0.4            （每帧读回整数 → 小数被抹掉）
新：_newsPos += 0.4; el.scrollTop = _newsPos   （浮点累加）

用法：venv/Scripts/python tasks/2026-09-13-news-autoscroll/probe_old_impl.py
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

SIM = r"""
(kind) => new Promise((resolve) => {
  const el = document.getElementById('news-body');
  if (window.stopNewsAutoScroll) window.stopNewsAutoScroll();
  el.scrollTop = 0;
  let pos = 0, n = 0, firstMoves = [];
  const tick = () => {
    if (kind === 'old') { el.scrollTop += 0.4; }
    else { pos += 0.4; el.scrollTop = pos; }
    firstMoves.push(+el.scrollTop.toFixed(3));
    if (++n < 60) requestAnimationFrame(tick);
    else resolve({ kind: kind, frames: n, final: +el.scrollTop.toFixed(3),
                   first10: firstMoves.slice(0, 10) });
  };
  requestAnimationFrame(tick);
})
"""


def main() -> int:
    port = vu.free_port()
    url = f"http://127.0.0.1:{port}/"
    proc = subprocess.Popen(
        [str(vu.PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        vu.wait_ready(url)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            page.add_init_script("try { localStorage.setItem('mp-theme', 'dark'); } catch (e) {}")
            page.goto(url, wait_until="load")
            page.wait_for_timeout(2500)
            page.mouse.move(5, 5)
            out = {"old_impl_0.4px_per_frame": page.evaluate(SIM, "old"),
                   "new_impl_0.4px_per_frame": page.evaluate(SIM, "new")}
            for k, v in out.items():
                print(f"{k}: {json.dumps(v, ensure_ascii=False)}")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
