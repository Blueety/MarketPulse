"""一次性取证：A 股板块表（#us-sectors .panel-cn）各列的实际对齐与几何。

用途：用户反馈「成交额那边没对齐」→ 先量化真实渲染（textAlign / 左右边缘 / 是否省略号），
再决定改表头还是改数据格。验证完可删除本文件。

用法：venv/Scripts/python tasks/2026-09-12-frontend-polish/probe_sector.py
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

PROBE_JS = r"""
() => {
  const out = { th: [], rows: [] };
  const table = document.querySelector('#us-sectors .panel-cn table.data-table');
  if (!table) return { error: 'table not found' };
  [...table.querySelectorAll('thead th')].forEach((th) => {
    const cs = getComputedStyle(th);
    const r = th.getBoundingClientRect();
    out.th.push({ text: th.textContent.trim(), cls: th.className,
                  align: cs.textAlign, left: Math.round(r.left), right: Math.round(r.right) });
  });
  [...table.querySelectorAll('tbody tr')].forEach((tr) => {
    const cells = [...tr.children].map((td) => {
      const cs = getComputedStyle(td);
      const r = td.getBoundingClientRect();
      return { text: td.textContent.trim(), cls: td.className, align: cs.textAlign,
               left: Math.round(r.left), right: Math.round(r.right),
               padL: cs.paddingLeft, padR: cs.paddingRight,
               clientW: td.clientWidth, scrollW: td.scrollWidth };
    });
    // 第 3 列 = 成交额；测其文本节点的真实左右边缘（用 Range 取文本盒）
    const turnover = tr.children[3];
    let tRect = null;
    if (turnover && turnover.firstChild) {
      const rng = document.createRange();
      rng.selectNodeContents(turnover);
      const r = rng.getBoundingClientRect();
      tRect = { left: Math.round(r.left), right: Math.round(r.right), w: Math.round(r.width) };
    }
    out.rows.push({ cells: cells, turnoverText: tRect });
  });
  return out;
}
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
            try:
                page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
            data = page.evaluate(PROBE_JS)
            page.screenshot(path=str(Path(vu.OUT_DIR) / "probe-sector.png"), full_page=False)
            browser.close()
        out = Path(vu.OUT_DIR) / "probe-sector.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"probe json -> {out}")
        print("th:", json.dumps(data.get("th"), ensure_ascii=False))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
