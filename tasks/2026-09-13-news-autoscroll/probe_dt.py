"""一次性取证：逐帧原始轨迹（rAF 时间戳 / scrollTop / 应用内部 _newsLast / paused）。

目的：确认 `_newsStep` 内部 `dt <= 0` 早退是否是「卡顿」的机制根因。
用法：venv/Scripts/python tasks/2026-09-13-news-autoscroll/probe_dt.py
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

TRACE_JS = r"""
(ms) => new Promise((resolve) => {
  const el = document.getElementById('news-body');
  const rows = [];
  const t0 = performance.now();
  const tick = (now) => {
    rows.push({ t: +(now - t0).toFixed(2), st: +el.scrollTop.toFixed(3),
                last: window._newsLast ? +(window._newsLast - t0).toFixed(2) : null,
                paused: window._newsPaused, raf: window._newsRaf });
    if (now - t0 < ms) requestAnimationFrame(tick);
    else resolve({ rows: rows, now0: t0 });
  };
  requestAnimationFrame(tick);
})
"""


def _summarize(trace: dict) -> dict:
    rows = trace["rows"]
    ts = [r["t"] for r in rows]
    sts = [r["st"] for r in rows]
    lasts = [r["last"] for r in rows if r["last"] is not None]
    diffs = [round(ts[i] - ts[i - 1], 2) for i in range(1, len(ts))]
    st_deltas = [round(sts[i] - sts[i - 1], 3) for i in range(1, len(sts))]
    return {
        "frames": len(rows),
        "ts_repeated_frames": sum(1 for d in diffs if d <= 0),
        "ts_delta_first10": diffs[:10],
        "scrollTop_first10": sts[:10],
        "scrollTop_delta_first10": st_deltas[:10],
        "net_scrollTop": round(sts[-1] - sts[0], 2) if rows else None,
        "paused_seen": sorted({r["paused"] for r in rows}) if rows else None,
        "newsLast_minus_now_negative": sum(
            1 for r, t in zip(rows, ts) if r["last"] is not None and r["last"] < t - 0.5),
        "last_delta_first10": [round(lasts[i] - lasts[i - 1], 2) for i in range(1, min(11, len(lasts)))],
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
            page.goto(url, wait_until="load")
            try:
                page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            page.mouse.move(5, 5)
            page.evaluate("() => { document.getElementById('news-body').scrollTop = 0; }")
            page.wait_for_timeout(200)

            out["A_baseline"] = _summarize(page.evaluate(TRACE_JS, 1500))
            print("A_baseline:", json.dumps(out["A_baseline"], ensure_ascii=False))

            page.add_style_tag(content=".__noop{color:red;}")
            page.wait_for_timeout(300)
            out["B_after_style_inject"] = _summarize(page.evaluate(TRACE_JS, 1500))
            print("B_after_style_inject:", json.dumps(out["B_after_style_inject"], ensure_ascii=False))

            # 反向验证：把 _newsLast 手动置后（模拟 startNewsAutoScroll 用 performance.now() 的偏移）
            page.evaluate("() => { window._newsLast = performance.now() - 100000; }")
            page.wait_for_timeout(400)
            out["C_after_last_reset"] = _summarize(page.evaluate(TRACE_JS, 1500))
            print("C_after_last_reset:", json.dumps(out["C_after_last_reset"], ensure_ascii=False))
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    path = Path(vu.OUT_DIR) / "probe-dt.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
