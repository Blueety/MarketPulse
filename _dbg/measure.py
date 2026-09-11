"""临时基线测量脚本（架构阶段只读；用完即删）。"""
import json
import sys

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8014/"

SELECTORS = [
    "html", "body", ".topbar", ".shell", "#sidebar", ".main", "#lede",
    ".lede-cell", "#overview", "#trend", ".charts-grid", ".chart-box",
    ".chart-box canvas", "#sectors", "#watchlist-section", "#alerts",
    ".sidebar-footer", ".nav",
]

JS = r"""
(sel) => {
  const out = { viewport: {
      innerW: window.innerWidth, innerH: window.innerHeight,
      dpr: window.devicePixelRatio,
      scrollH: document.scrollingElement.scrollHeight,
      scrollW: document.scrollingElement.scrollWidth,
      chartFailed: !!window.__chartFailed, zoomFailed: !!window.__zoomFailed,
      hasChart: !!window.Chart,
      theme: document.documentElement.getAttribute('data-theme'),
    }, els: [], counts: {}, errors: [] };
  for (const s of sel) {
    const list = document.querySelectorAll(s);
    out.counts[s] = list.length;
    if (!list.length) continue;
    const e = list[0];
    const r = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    out.els.push({
      sel: s,
      rect: { x: +r.x.toFixed(1), y: +r.y.toFixed(1), w: +r.width.toFixed(1), h: +r.height.toFixed(1) },
      offset: { top: e.offsetTop, left: e.offsetLeft, w: e.offsetWidth, h: e.offsetHeight },
      client: { w: e.clientWidth, h: e.clientHeight },
      box: cs.boxSizing, pos: cs.position, z: cs.zIndex, disp: cs.display,
      pad: cs.padding, mar: cs.margin, h: cs.height, maxH: cs.maxHeight,
      overflow: cs.overflow, flexDir: cs.flexDirection,
      gridCols: cs.gridTemplateColumns, align: cs.alignItems,
    });
  }
  out.counts['chartInstances'] = (window.Chart && window.Chart.instances)
      ? Object.keys(window.Chart.instances).length : -1;
  out.counts['overviewRows'] = document.querySelectorAll('#overview-body tr').length;
  out.counts['watchRows'] = document.querySelectorAll('#watchlist-body tr').length;
  out.counts['sectorRows'] = document.querySelectorAll('#sector-body tr').length;
  out.counts['alertCards'] = document.querySelectorAll('#alert-list .alert-card').length;
  out.counts['navItems'] = document.querySelectorAll('#sidebar .nav-item').length;
  out.counts['chartEmpty'] = document.querySelectorAll('.chart-empty').length;
  const canvases = [...document.querySelectorAll('.chart-box canvas')];
  out.canvases = canvases.map(c => ({
    id: c.id,
    cssH: getComputedStyle(c).height,
    attrW: c.width, attrH: c.height,
    parentH: c.parentElement ? c.parentElement.getBoundingClientRect().height : null,
  }));
  return out;
}
"""


def run(width: int, height: int, theme: str, shot: str, label: str):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": width, "height": height},
                        device_scale_factor=1)
        errs = []
        pg.on("console", lambda m: errs.append(m.type + ": " + m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
        pg.add_init_script(
            "try{localStorage.setItem('mp-theme','%s')}catch(e){}" % theme
        )
        pg.goto(URL, wait_until="load", timeout=30000)
        pg.wait_for_timeout(16000)  # 等 watchlist（12s 超时）+ 图表绘制
        data = pg.evaluate(JS, SELECTORS)
        data["consoleErrors"] = errs
        data["label"] = label
        pg.screenshot(path=shot, full_page=True)
        b.close()
        return data


if __name__ == "__main__":
    results = []
    results.append(run(1920, 1080, "dark", "_dbg/shot-1920-dark.png", "1920x1080 dark"))
    results.append(run(1280, 720, "dark", "_dbg/shot-1280-dark.png", "1280x720 dark"))
    results.append(run(1920, 1080, "light", "_dbg/shot-1920-light.png", "1920x1080 light"))
    print(json.dumps(results, ensure_ascii=False, indent=1))
