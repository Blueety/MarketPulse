"""MarketPulse 看板 UI 验收 / 视觉根因测量脚本（可复跑，有意入库）。

用法：
    venv/Scripts/python -m uvicorn web.app:app --port 8015   # 每次换新端口，防 CSS 缓存假阴性
    venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py --port 8015

输出：
    - stdout：JSON（布局 + 计算样式 + 玻璃感判据）
    - 截图：$env:TEMP/mp_verify/（不落仓库，避免二进制入库 —— 见 plan.md R14）
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

# 玻璃感关键选点
GLASS_SELECTORS = [
    "html", "body", ".topbar", "#sidebar", ".topsearch", ".date-chip",
    ".card", ".kpi-card", ".card.promo", "#trend", "#watchlist-section", "#alerts",
]

JS = r"""
(sels) => {
  const glassProps = ["backgroundColor", "backgroundImage", "backdropFilter",
                      "webkitBackdropFilter", "borderTopColor", "borderTopWidth",
                      "borderRadius", "boxShadow", "opacity", "position", "zIndex"];

  const pick = (el) => {
    const cs = getComputedStyle(el);
    const o = {};
    for (const p of glassProps) o[p] = cs[p];
    // alpha 解析：rgb(...)=不透明 / rgba(...,a) a<1 = 半透明
    const m = /^rgba?\(([^)]+)\)$/.exec(cs.backgroundColor);
    if (m) {
      const parts = m[1].split(",").map(s => s.trim());
      o.bgAlpha = parts.length === 4 ? parseFloat(parts[3]) : 1;
      o.bgIsOpaque = o.bgAlpha >= 1;
    } else {
      o.bgAlpha = null; o.bgIsOpaque = null;   // transparent 关键字等
    }
    o.hasBackdropFilter = cs.backdropFilter && cs.backdropFilter !== "none";
    o.hasGradientBg = cs.backgroundImage && cs.backgroundImage !== "none";
    return o;
  };

  const out = {
    viewport: {
      innerW: innerWidth, innerH: innerHeight, dpr: devicePixelRatio,
      scrollH: document.scrollingElement.scrollHeight,
      scrollW: document.scrollingElement.scrollWidth,
      theme: document.documentElement.getAttribute("data-theme"),
      chartFailed: !!window.__chartFailed,
    },
    tokens: {},
    glass: {},
    // 全量扫描：哪些元素带渐变 / 哪些元素有 backdrop-filter
    gradientElements: [],
    backdropElements: [],
    cards: { count: 0, kpi: 0, promoGradient: null },
    consoleErrors: [],
  };

  for (const t of ["--bg-primary", "--bg-elevated", "--bg-hover", "--border",
                   "--card-shadow", "--card-glow", "--radius-card"]) {
    out.tokens[t] = getComputedStyle(document.documentElement).getPropertyValue(t).trim();
  }

  for (const s of sels) {
    const el = document.querySelector(s);
    if (!el) { out.glass[s] = null; continue; }
    out.glass[s] = pick(el);
  }

  // 全量扫描背景层（找"可被模糊的内容"——玻璃感的前提）
  document.querySelectorAll("*").forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.backgroundImage && cs.backgroundImage !== "none") {
      out.gradientElements.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && el.className.toString().slice(0, 60)) || "",
        bgImage: cs.backgroundImage.slice(0, 120),
      });
    }
    if (cs.backdropFilter && cs.backdropFilter !== "none") {
      out.backdropElements.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && el.className.toString().slice(0, 60)) || "",
        filter: cs.backdropFilter,
      });
    }
  });

  out.cards.count = document.querySelectorAll(".card").length;
  out.cards.kpi = document.querySelectorAll(".kpi-card").length;
  const promo = document.querySelector(".card.promo");
  out.cards.promoGradient = promo ? getComputedStyle(promo).backgroundImage.slice(0, 160) : null;

  return out;
}
"""


def run(url: str, width: int, height: int, theme: str, shot: Path, errors: list[str]):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        pg.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        pg.add_init_script("try{localStorage.setItem('mp-theme','%s')}catch(e){}" % theme)
        pg.goto(url, wait_until="load", timeout=30000)
        pg.wait_for_timeout(15000)  # 等 watchlist（12s 超时）+ 图表绘制
        data = pg.evaluate(JS, GLASS_SELECTORS)
        data["consoleErrors"] = list(errors)
        data["shot"] = str(shot)
        shot.parent.mkdir(parents=True, exist_ok=True)
        pg.screenshot(path=str(shot), full_page=True)
        b.close()
        return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8015)
    ap.add_argument("--theme", default="dark", choices=["dark", "light", "both"])
    args = ap.parse_args()

    url = f"http://127.0.0.1:{args.port}/"
    outdir = Path(tempfile.gettempdir()) / "mp_verify"
    themes = ["dark", "light"] if args.theme == "both" else [args.theme]

    report = []
    for theme in themes:
        for (w, h) in ((1920, 1080), (1280, 720)):
            shot = outdir / f"shot-{w}-{theme}.png"
            report.append(run(url, w, h, theme, shot, []))
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
