"""一次性取证：资讯自动滚动的「卡顿」根因量化（掉帧 vs 逐帧重排/重绘）。

判据：
- 掉帧：rAF 帧间隔的 p95 / 长帧占比（>25ms）
- 布局抖动：CDP Performance.getMetrics 的 LayoutCount / RecalcStyleCount 在一个 3s 窗口内的增量
- A/B：临时禁用 #news 的 backdrop-filter（运行时注入，不改仓库文件）后复测

用法：venv/Scripts/python tasks/2026-09-13-news-autoscroll/probe_scroll_smoothness.py
"""
from __future__ import annotations

import importlib.util
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "vu", ROOT / "tasks" / "2026-09-11-frontend-bento-redesign" / "verify_ui.py"
)
vu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vu)

# 采样 ~3s：每帧记录 rAF 间隔、scrollTop、以及第一个 .news-item 的**绘制位置**（rect.top）
SAMPLE = r"""
() => new Promise((resolve) => {
  const el = document.getElementById('news-body');
  const item = el.querySelector('.news-item');
  const rec = [];
  const t0 = performance.now();
  let last = t0;
  const tick = (now) => {
    rec.push([+(now - t0).toFixed(1), +(now - last).toFixed(1),
              +el.scrollTop.toFixed(3), +item.getBoundingClientRect().top.toFixed(3)]);
    last = now;
    if (now - t0 < 3000) requestAnimationFrame(tick);
    else resolve({ rec: rec, dpr: window.devicePixelRatio,
                   blur: getComputedStyle(document.getElementById('news')).backdropFilter });
  };
  requestAnimationFrame(tick);
})
"""


def _stats(rec: list) -> dict:
    dts = [r[1] for r in rec[1:]]
    tops = [r[3] for r in rec]
    sts = [r[2] for r in rec]
    moved = sum(1 for i in range(1, len(tops)) if abs(tops[i] - tops[i - 1]) > 0.001)
    uniq = sorted({round(tops[i] - tops[i - 1], 3) for i in range(1, len(tops))})
    dur = (rec[-1][0] - rec[0][0]) / 1000 if len(rec) > 1 else 0
    return {
        "frames": len(rec),
        "duration_s": round(dur, 2),
        "fps": round(len(rec) / dur, 1) if dur else None,
        "dt_median_ms": round(statistics.median(dts), 2) if dts else None,
        "dt_p95_ms": round(sorted(dts)[int(len(dts) * 0.95)], 2) if dts else None,
        "dt_max_ms": round(max(dts), 2) if dts else None,
        "long_frames_gt25ms": sum(1 for d in dts if d > 25),
        "long_frames_gt50ms": sum(1 for d in dts if d > 50),
        "moved_frames": moved,
        "moved_ratio": round(moved / max(1, len(dts)), 3),
        "distinct_paint_steps": uniq[:12],
        "paint_px_per_s": round((tops[0] - tops[-1]) / dur, 2) if dur else None,
        "scrollTop_px_per_s": round((sts[-1] - sts[0]) / dur, 2) if dur else None,
        "blur": None,
    }


def main() -> int:
    port = vu.free_port()
    url = f"http://127.0.0.1:{port}/"
    proc = subprocess.Popen(
        [str(vu.PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    out: dict = {"url": url}
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
            page.mouse.move(5, 5)          # 保证不在 hover 暂停态

            cdp = page.context.new_cdp_session(page)
            cdp.send("Performance.enable")

            def metrics() -> dict:
                return {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}

            # --- 基线（生产 CSS，含 backdrop-filter）---
            page.evaluate("() => { document.getElementById('news-body').scrollTop = 0; }")
            m0 = metrics()
            base = page.evaluate(SAMPLE)
            m1 = metrics()
            out["baseline"] = _stats(base["rec"])
            out["baseline"]["blur"] = base["blur"]
            out["baseline"]["dpr"] = base["dpr"]
            out["baseline"]["LayoutCount_delta"] = round(m1.get("LayoutCount", 0) - m0.get("LayoutCount", 0))
            out["baseline"]["RecalcStyleCount_delta"] = round(m1.get("RecalcStyleCount", 0) - m0.get("RecalcStyleCount", 0))
            out["baseline"]["TaskDuration_delta_ms"] = round(
                (m1.get("TaskDuration", 0) - m0.get("TaskDuration", 0)) * 1000)
            out["baseline"]["ScriptDuration_delta_ms"] = round(
                (m1.get("ScriptDuration", 0) - m0.get("ScriptDuration", 0)) * 1000)
            out["baseline"]["LayoutDuration_delta_ms"] = round(
                (m1.get("LayoutDuration", 0) - m0.get("LayoutDuration", 0)) * 1000, 2)

            # --- A/B：运行时禁用 #news 的 backdrop-filter（不改仓库文件）---
            page.add_style_tag(content="#news{backdrop-filter:none !important;-webkit-backdrop-filter:none !important;}")
            page.evaluate("() => { document.getElementById('news-body').scrollTop = 0; }")
            m2 = metrics()
            noblur = page.evaluate(SAMPLE)
            m3 = metrics()
            out["no_backdrop_filter"] = _stats(noblur["rec"])
            out["no_backdrop_filter"]["blur"] = noblur["blur"]
            out["no_backdrop_filter"]["LayoutCount_delta"] = round(m2.get("LayoutCount", 0) - m2.get("LayoutCount", 0))
            out["no_backdrop_filter"]["RecalcStyleCount_delta"] = round(m3.get("RecalcStyleCount", 0) - m2.get("RecalcStyleCount", 0))
            out["no_backdrop_filter"]["TaskDuration_delta_ms"] = round(
                (m3.get("TaskDuration", 0) - m2.get("TaskDuration", 0)) * 1000)

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    path = Path(vu.OUT_DIR) / "probe-scroll-smoothness.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {path}")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
