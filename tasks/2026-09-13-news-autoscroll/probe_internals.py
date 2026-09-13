"""一次性取证：同一页面内按时间线切换 CSS 条件，并读取自动滚动内部状态。

关键：不再每次 goto（会引入混淆变量），改为一次加载后分段时间线：
  A 基线 → B 禁 blur → C 去背景渐变 → D 加 will-change/contain
每段记录：fps、ΔscrollTop、movedRatio、以及窗口内部量
(`_newsRaf` / `_newsHalf` / `_newsPaused` / scrollHeight / clientHeight / 条目数 / 每秒推进 px)。

用法：venv/Scripts/python tasks/2026-09-13-news-autoscroll/probe_internals.py
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
  let n = 0, moved = 0, prev = el.scrollTop, maxJump = 0;
  const t0 = performance.now();
  const tick = () => {
    n++;
    const d = el.scrollTop - prev;
    if (Math.abs(d) > 0.001) moved++;
    if (d > maxJump) maxJump = d;
    prev = el.scrollTop;
    const e = performance.now() - t0;
    if (e < ms) requestAnimationFrame(tick);
    else resolve({
      frames: n, fps: +(n / (e / 1000)).toFixed(1),
      dScrollTop: +d.toFixed(1), movedRatio: +(moved / n).toFixed(2),
      pxPerSec: +(d / (e / 1000)).toFixed(2), maxFrameJump: +maxJump.toFixed(2),
      raf: window._newsRaf, half: window._newsHalf, paused: window._newsPaused,
      clientH: el.clientHeight, scrollH: el.scrollHeight,
      items: el.querySelectorAll('.news-item').length,
      constRate: window.NEWS_SCROLL_PX_PER_SEC,
    });
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
    out: dict = {}
    try:
        vu.wait_ready(url)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            page.add_init_script("try { localStorage.setItem('mp-theme', 'dark'); } catch (e) {}")
            page.goto(url, wait_until="load")
            try:
                page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            page.mouse.move(5, 5)
            page.evaluate("() => { document.getElementById('news-body').scrollTop = 0; }")
            page.wait_for_timeout(200)

            def seg(name: str, css: str | None = None) -> None:
                if css:
                    page.add_style_tag(content=css)
                    page.wait_for_timeout(300)
                r = page.evaluate(SEG_JS, 2000)
                out[name] = r
                print(f"{name}: {json.dumps(r, ensure_ascii=False)}")

            seg("A_baseline")
            seg("B_no_blur", css="*{backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}")
            seg("C_no_ambient", css="body{background-image:none !important;}")
            seg("D_promote", css="#news-body{will-change:scroll-position;}")
            # 反向验证：注入一个**与本页无关**的通用规则（纯 style 注入本身不应改变滚动）
            seg("E_control_inject", css=".__noop_control{color:red;}")
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    path = Path(vu.OUT_DIR) / "probe-internals.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
