"""Bento 看板 UI 验收脚本（Playwright + 真实渲染测量）。

用法（项目根执行）：
    venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

行为：
- 自动挑一个**空闲端口**起 uvicorn（每次新端口 = 新 origin，规避 304/陈旧 CSS 造成的假阴性，
  见 docs/pitfalls.md「跨端口 CSS 缓存假阴性」），跑完后自动结束该进程。
- 1920×1080 / 1280×720 / 375×812 三视口（DPR=1）测量 + 断言，另在 1920 下验证主题切换与 4 个类别 tab。
- 截图与 JSON 报告写入系统临时目录（**不落仓库**，避免二进制入库 + 被 auto-commit cron 扫入）。
- 退出码 0 = 全部通过；1 = 有断言失败（逐条打印 FAIL 原因）。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "venv" / "Scripts" / "python.exe"
OUT_DIR = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "marketpulse-verify"

VIEWPORTS = [(1920, 1080), (1280, 720), (375, 812)]

FAILURES: list[str] = []


def check(cond: bool, label: str, actual=None, expect=None) -> None:
    """记录一条断言结果（失败进 FAILURES，最后统一汇总）。"""
    if cond:
        print(f"  PASS  {label}")
    else:
        detail = ""
        if actual is not None or expect is not None:
            detail = f" (actual={actual!r} expect={expect!r})"
        FAILURES.append(f"{label}{detail}")
        print(f"  FAIL  {label}{detail}")


def to_int(v, default: int = 0) -> int:
    """z-index 取值容错：'auto' / None / 非数字 → default。"""
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return
        except Exception:
            time.sleep(0.4)
    raise RuntimeError(f"服务未在 {timeout}s 内就绪: {url}")


MEASURE_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const cs = (el) => el ? getComputedStyle(el) : null;
  const cols = (sel) => {
    const el = q(sel);
    if (!el) return null;
    return cs(el).gridTemplateColumns.trim().split(/\s+/).length;
  };
  const box = (sel) => {
    const el = q(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  };
  const canvasCmp = (sel) => {
    const c = q(sel);
    if (!c) return null;
    return {
      bitmapW: c.width, bitmapH: c.height,
      cssW: c.offsetWidth, cssH: c.offsetHeight,
      dpr: window.devicePixelRatio || 1,
    };
  };
  const cardStyle = (() => {
    const c = q('#overview');   // 勿用 '.card'：首个 .card 是 promo（仅渐变背景，background-color 恒 transparent）
    if (!c) return null;
    const s = cs(c);
    return { boxSizing: s.boxSizing, borderRadius: s.borderRadius, background: s.backgroundColor,
             border: s.borderTopWidth, shadow: s.boxShadow !== 'none' };
  })();
  const sidebar = q('#sidebar');
  const sbRect = sidebar ? sidebar.getBoundingClientRect() : null;
  // 各视觉行 / 各卡片实际高度（定位「谁把页面撑高」）
  const sections = {};
  ['.row-kpi', '.row-main', '.row-3', '.row-news', '.dash'].forEach((sel) => {
    const el = q(sel);
    sections[sel] = el ? Math.round(el.getBoundingClientRect().height) : null;
  });
  document.querySelectorAll('.card[id]').forEach((el) => {
    sections['#' + el.id] = Math.round(el.getBoundingClientRect().height);
  });
  // 横向溢出定位（定位「谁把页面撑宽」）
  const overflowers = [];
  const vw = window.innerWidth;
  document.querySelectorAll('body *').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    if (el.closest && el.closest('.table-scroll')) return;   // 表内横向滚动是设计行为，不计入页面溢出
    if (r.right > vw + 1 || r.left < -1) {
      overflowers.push({
        tag: el.tagName.toLowerCase(),
        id: el.id || '',
        cls: (el.className && el.className.toString ? el.className.toString().slice(0, 40) : ''),
        left: Math.round(r.left), right: Math.round(r.right),
      });
    }
  });
  return {
    sections: sections,
    overflowers: overflowers.slice(0, 12),
    innerW: window.innerWidth, innerH: window.innerHeight,
    scrollW: document.scrollingElement.scrollWidth,
    scrollH: document.scrollingElement.scrollHeight,
    chartFailed: !!window.__chartFailed, zoomFailed: !!window.__zoomFailed,
    hasChart: !!(window.Chart && window.Chart.getChart && window.Chart.getChart(q('#chart-main'))),
    chartCount: (window.Chart && window.Chart.instances) ? Object.keys(window.Chart.instances).length : null,
    kpiCount: document.querySelectorAll('#lede .kpi-card').length,
    kpiBox: box('.kpi-card'),
    kpiVal: (q('.kpi-card .kpi-val') || {}).textContent || null,
    chartWrapH: q('#chart-main-wrap') ? Math.round(q('#chart-main-wrap').getBoundingClientRect().height) : null,
    canvas: canvasCmp('#chart-main'),
    rowKpi: cols('.row-kpi'), rowMain: cols('.row-main'), row3: cols('.row-3'), rowNews: cols('.row-news'),
    dashExists: !!q('.dash'),
    overviewCards: document.querySelectorAll('#overview-body .mini-card').length,
    sectorRows: document.querySelectorAll('#sector-body tr').length,
    usSectorRows: document.querySelectorAll('#us-sectors-body .bar-row').length,
    watchRows: document.querySelectorAll('#watchlist-body tr').length,
    watchHidden: !!q('#watchlist-section.hidden'),
    alertCards: document.querySelectorAll('.alert-card').length,
    placeholderCards: document.querySelectorAll('[data-placeholder="1"]').length,
    phNotes: [...document.querySelectorAll('[data-placeholder="1"] .ph-note')].map(e => e.textContent),
    topbarDate: (q('#topbar-date') || {}).textContent || null,
    marketStatus: (q('#market-status') || {}).textContent || null,
    marketTime: (q('#market-time') || {}).textContent || null,
    card: cardStyle,
    sidebar: sidebar ? {
      w: Math.round(sbRect.width), h: Math.round(sbRect.height),
      position: cs(sidebar).position, top: Math.round(sbRect.top),
      bottom: Math.round(sbRect.bottom), innerH: window.innerHeight,
    } : null,
    zTopbar: cs(q('.topbar')).zIndex, zSidebar: cs(q('#sidebar')).zIndex,
    zBackdrop: cs(q('.nav-backdrop')).zIndex,
    htmlTheme: document.documentElement.getAttribute('data-theme'),
    isWeekendFri: (typeof isWeekendDate === 'function') ? isWeekendDate('2026-09-11') : null,
    isWeekendSat: (typeof isWeekendDate === 'function') ? isWeekendDate('2026-09-12') : null,
    tabCount: document.querySelectorAll('#trend-tabs button').length,
  };
}
"""


GLASS_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const cs = (el) => (el ? getComputedStyle(el) : null);
  const alphaOf = (color) => {
    if (!color) return null;
    const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)/.exec(color);
    if (!m) return null;
    return m[4] === undefined ? 1 : parseFloat(m[4]);
  };
  // 按顶层逗号切分 box-shadow（括号内逗号不算）
  const splitTop = (s) => {
    const out = []; let depth = 0, cur = '';
    for (const ch of s) {
      if (ch === '(') depth++;
      else if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; }
      else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  };
  // inset 段取白色 alpha 最大值；非 inset 段取最大模糊半径（第 3 个长度）
  const shadowInfo = (el) => {
    const sh = el ? (cs(el).boxShadow || '') : '';
    if (!sh || sh === 'none') return { insetAlpha: null, blur: null, raw: sh };
    let insetAlpha = null, blur = null;
    for (const seg of splitTop(sh)) {
      if (/inset/.test(seg)) {
        const a = alphaOf(seg);
        if (a !== null && (insetAlpha === null || a > insetAlpha)) insetAlpha = a;
      } else {
        const nums = seg.match(/-?[\d.]+px/g) || [];
        if (nums.length >= 3) {
          const b = Math.abs(parseFloat(nums[2]));
          if (blur === null || b > blur) blur = b;
        }
      }
    }
    return { insetAlpha, blur, raw: sh };
  };
  const countGradients = (bg) => (!bg || bg === 'none') ? 0 : (bg.match(/gradient\(/g) || []).length;
  const cards = [...document.querySelectorAll('.card:not(.card.promo), .kpi-card')];
  const mainCard = q('#overview');
  const si = shadowInfo(mainCard);
  const dataCards = ['#overview', '#trend', '#alerts'];
  return {
    theme: document.documentElement.getAttribute('data-theme'),
    cardCount: cards.length,
    coveredCount: cards.filter((el) => cs(el).backdropFilter !== 'none').length,
    glassCovered: cards.length > 0 && cards.every((el) => cs(el).backdropFilter !== 'none'),
    promoBackdrop: q('.card.promo') ? cs(q('.card.promo')).backdropFilter : null,
    kpiAlpha: (() => { const k = q('.kpi-card'); return k ? alphaOf(cs(k).backgroundColor) : null; })(),
    dataCardAlphas: (() => {
      const o = {}; dataCards.forEach((s) => { const el = q(s); o[s] = el ? alphaOf(cs(el).backgroundColor) : null; }); return o;
    })(),
    bodyLayers: countGradients(cs(document.body).backgroundImage),
    bodyBgImage: (cs(document.body).backgroundImage || '').slice(0, 200),
    highlightAlpha: si.insetAlpha,
    shadowBlur: si.blur,
    shadowRaw: si.raw,
    borderAlpha: mainCard ? alphaOf(cs(mainCard).borderTopColor) : null,
    borderRaw: mainCard ? cs(mainCard).borderTopColor : null,
    topbarBackdrop: q('.topbar') ? cs(q('.topbar')).backdropFilter : null,
    sidebarBg: q('#sidebar') ? cs(q('#sidebar')).backgroundColor : null,
    sidebarBackdrop: q('#sidebar') ? cs(q('#sidebar')).backdropFilter : null,
    cardBox: mainCard ? { w: mainCard.offsetWidth, h: mainCard.offsetHeight } : null,
    scrollH: document.scrollingElement.scrollHeight,
    scrollW: document.scrollingElement.scrollWidth,
    innerW: window.innerWidth,
  };
}
"""

# G-1 断言 5/6 的目标区间（**分主题**）。
# plan §6 G-1 给的是单一区间（highlight ≥0.08 / border 0.08~0.14），按 §4.2 早期建议值（.10）
# 且只按 dark 写；§4.6.2「效果图校准值」把 dark 改成 highlight .07 / border .20，
# 两者对不上（照原区间实现必然恒 FAIL）。按 plan §12.1「实施以 §4.6.2 为准」，此处按校准值
# 给区间，并在 journal 记录该偏差。断言 2/3 同理：只在 dark 生效（light 的 .66/.88 天然超区间）。
GLASS_RANGES = {
    "dark": {"kpiMax": 0.2, "dataLo": 0.6, "dataHi": 0.8,
             "highlight": (0.04, 0.15), "border": (0.15, 0.30)},
    "light": {"kpiMax": 1.0, "dataLo": 0.5, "dataHi": 1.01,
              "highlight": (0.85, 1.01), "border": (0.75, 1.01)},
}


def assert_glass(w: int, h: int, g: dict) -> None:
    """G-1 玻璃判据断言（1~7）。数值区间随当前主题取（dark 为主验收口径）。"""
    theme = g.get("theme") or "dark"
    r = GLASS_RANGES.get(theme, GLASS_RANGES["dark"])
    print(f"\n--- 玻璃判据 {w}x{h}（theme={theme}）---")
    print(f"  body 层={g['bodyLayers']} 覆盖={g['coveredCount']}/{g['cardCount']} "
          f"kpiAlpha={g['kpiAlpha']} dataAlpha={g['dataCardAlphas']} "
          f"highlight={g['highlightAlpha']} border={g['borderAlpha']} blur={g['shadowBlur']}")
    if g.get("shadowRaw"):
        print(f"  shadow={g['shadowRaw'][:120]}")

    check(g["glassCovered"], f"{w} 卡片 backdrop-filter 全覆盖（{g['coveredCount']}/{g['cardCount']}）",
          g["coveredCount"], g["cardCount"])
    check((g["promoBackdrop"] or "none") == "none", f"{w} promo 卡显式 backdrop-filter=none（1b）",
          g["promoBackdrop"])
    check(g["kpiAlpha"] is not None and g["kpiAlpha"] < r["kpiMax"],
          f"{w} .kpi-card 背景 alpha < {r['kpiMax']}", g["kpiAlpha"])
    for sel, a in (g["dataCardAlphas"] or {}).items():
        check(a is not None and r["dataLo"] <= a <= r["dataHi"],
              f"{w} 数据卡 {sel} alpha ∈ [{r['dataLo']}, {r['dataHi']}]", a)
    check(g["bodyLayers"] >= 2, f"{w} body 氛围渐变层 ≥ 2", g["bodyLayers"])
    lo, hi = r["highlight"]
    check(g["highlightAlpha"] is not None and lo <= g["highlightAlpha"] <= hi,
          f"{w} 顶边内高光白 alpha ∈ [{lo}, {hi}]", g["highlightAlpha"])
    lo, hi = r["border"]
    check(g["borderAlpha"] is not None and lo <= g["borderAlpha"] <= hi,
          f"{w} 卡片边框 alpha ∈ [{lo}, {hi}]", g["borderAlpha"])
    check(g["shadowBlur"] is not None and g["shadowBlur"] >= 24,
          f"{w} 卡片外阴影模糊半径 ≥ 24px", g["shadowBlur"])
    # G-6：顶栏做玻璃层、侧栏只透明（规避 R19 sticky + blur 残影）
    check((g["topbarBackdrop"] or "none") != "none", f"{w} .topbar backdrop-filter 生效",
          g["topbarBackdrop"])
    check((g["sidebarBackdrop"] or "none") == "none"
          and (g["sidebarBg"] or "") in ("rgba(0, 0, 0, 0)", "transparent"),
          f"{w} #sidebar 透明且无 backdrop-filter", (g["sidebarBg"], g["sidebarBackdrop"]))


def measure(page, url: str, w: int, h: int) -> dict:
    page.set_viewport_size({"width": w, "height": h})
    page.goto(url, wait_until="load")
    # 自选股首次请求走 AkShare 冷启动（服务端限时 10s），须等卡片状态确定后再测量，
    # 否则 #watchlist-section 仍在 .hidden 态（height=0）会被误判为布局缺陷。
    try:
        page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
    except Exception:
        pass   # 无配置时整卡隐藏属预期行为
    page.wait_for_timeout(1200)
    data = page.evaluate(MEASURE_JS)
    dark = os.path.join(OUT_DIR, f"shot-{w}x{h}.png")
    page.screenshot(path=dark, full_page=True)
    return data


def assert_viewport(w: int, h: int, m: dict) -> None:
    print(f"\n--- {w}x{h} ---")
    print(f"  scrollH={m['scrollH']} sections={m.get('sections')}")
    if m.get("overflowers"):
        print(f"  overflowers={m['overflowers']}")
    check(m["dashExists"], ".dash 骨架存在")
    check(m["scrollW"] == m["innerW"], f"{w} 无横向溢出", m["scrollW"], m["innerW"])
    check(m["chartFailed"] is False, "Chart.js CDN 正常")

    # canvas 位图 == 显示尺寸（C2 回归护栏；DPR=1 严格相等）
    c = m["canvas"]
    if c:
        check(c["bitmapW"] == c["cssW"] and c["bitmapH"] == c["cssH"],
              f"{w} canvas 位图 == 显示尺寸",
              (c["bitmapW"], c["bitmapH"]), (c["cssW"], c["cssH"]))
        check(m["chartWrapH"] and m["chartWrapH"] > 0, f"{w} 主图容器有确定高度 (R1)", m["chartWrapH"])
    else:
        check(False, f"{w} canvas#chart-main 存在")

    # 卡片 token
    card = m["card"] or {}
    check(card.get("boxSizing") == "border-box", f"{w} .card box-sizing=border-box", card.get("boxSizing"))
    check(card.get("borderRadius") == "12px", f"{w} .card 圆角 12px", card.get("borderRadius"))
    check(bool(card.get("shadow")), f"{w} .card 有卡片阴影")

    # 模块渲染
    check(m["kpiCount"] == 4, f"{w} KPI 卡 4 张", m["kpiCount"])
    check(m["overviewCards"] == 6, f"{w} 市场概览 6 小卡", m["overviewCards"])
    check(m["sectorRows"] >= 1, f"{w} A 股板块有行", m["sectorRows"])
    check(m["usSectorRows"] >= 1, f"{w} 美股行业板块有行", m["usSectorRows"])
    check((not m["watchHidden"]) and m["watchRows"] >= 1, f"{w} 自选列表可见且有行", m["watchRows"])
    check(len(m["phNotes"]) == 3 and all(n == "数据未接入" for n in m["phNotes"]),
          f"{w} 3 个占位模块文案", m["phNotes"])
    check(m["tabCount"] == 4, f"{w} 趋势类别 tab 4 个", m["tabCount"])
    check(m["isWeekendFri"] is False and m["isWeekendSat"] is True,
          f"{w} isWeekendDate(周五)=false / (周六)=true", (m["isWeekendFri"], m["isWeekendSat"]))
    check("2026-09-11" in (m["topbarDate"] or ""), f"{w} 顶栏显示数据日", m["topbarDate"])


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"启动 uvicorn: {url}")
    if not PY.exists():
        print(f"找不到 venv python: {PY}")
        return 1
    proc = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    report: dict = {"url": url, "viewports": {}}
    try:
        wait_ready(url)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            # 玻璃判据以 dark 为验收口径（plan §7.2 的「修复前实测」就是 dark 数值；light 的
            # KPI/数据卡 alpha 天然超出 G-1 的 <0.2 / 0.6~0.8 区间，见 GLASS_RANGES 注释）。
            # 用 add_init_script 固定主题，避免浏览器默认 light 导致断言口径错配。
            page.add_init_script("try { localStorage.setItem('mp-theme', 'dark'); } catch (e) {}")
            errors: list[str] = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))

            for (w, h) in VIEWPORTS:
                m = measure(page, url, w, h)
                assert_viewport(w, h, m)
                g = page.evaluate(GLASS_JS)      # G-1 玻璃判据（1~7）
                assert_glass(w, h, g)
                m["glass"] = g
                report["viewports"][f"{w}x{h}"] = m

            # 1920 档位：布局列数 / 主图高度 / 侧栏贴底 / 层级 / 主题 / tab 切换
            m = report["viewports"]["1920x1080"]
            print("\n--- 1920 专项 ---")
            check(m["rowKpi"] == 5, "row-kpi 5 列同排", m["rowKpi"])
            check(m["rowMain"] == 2, "row-main 主图 + 自选同排", m["rowMain"])
            check(m["row3"] == 3, "row-3 三列同排", m["row3"])
            check(m["rowNews"] == 4, "row-news 四列", m["rowNews"])
            check(m["chartWrapH"] == 432, "主图容器 = 40vh = 432px", m["chartWrapH"])
            check(m["scrollH"] <= 1240, "1920 页面总高 ≤ 1240（≤1.15 屏）", m["scrollH"])
            check(m["kpiBox"] and m["kpiBox"]["w"] >= 260 and m["kpiBox"]["h"] >= 96,
                  "KPI 卡 ≥260×96", m["kpiBox"])
            sb = m["sidebar"] or {}
            check(abs(sb.get("bottom", 0) - sb.get("innerH", 0)) <= 2,
                  "侧栏贴底（sticky 生效）", (sb.get("bottom"), sb.get("innerH")))
            check(to_int(m["zSidebar"]) > to_int(m["zBackdrop"]) and to_int(m["zTopbar"]) > to_int(m["zSidebar"]),
                  "层级 topbar > sidebar > backdrop", (m["zTopbar"], m["zSidebar"], m["zBackdrop"]))
            check(m["marketStatus"] in ("市场已开盘", "休市") and "北京时间" in (m["marketTime"] or ""),
                  "侧栏市场状态 + 北京时间", (m["marketStatus"], m["marketTime"]))

            # 主题切换（深浅双套 token）—— 含断言 12：卡片底色与边框色都要随主题变
            bg_before = m["card"]["background"]
            border_before = (m.get("glass") or {}).get("borderRaw")
            theme_after = page.evaluate(
                """() => {
                    document.getElementById('sidebar-theme').click();
                    const c = document.getElementById('overview');
                    return { theme: document.documentElement.getAttribute('data-theme'),
                             ls: localStorage.getItem('mp-theme'),
                             bg: getComputedStyle(c).backgroundColor,
                             border: getComputedStyle(c).borderTopColor,
                             chartAlive: !!(window.Chart && window.Chart.getChart(document.getElementById('chart-main'))) };
                }"""
            )
            page.wait_for_timeout(600)
            check(theme_after["theme"] != m["htmlTheme"], "切换后 data-theme 变化",
                  (m["htmlTheme"], theme_after["theme"]))
            check(theme_after["ls"] == theme_after["theme"], "localStorage 与主题一致", theme_after["ls"])
            check(bg_before != theme_after["bg"], "切换后卡片底色变化", (bg_before, theme_after["bg"]))
            check(border_before != theme_after["border"], "切换后卡片边框色变化（断言 12）",
                  (border_before, theme_after["border"]))
            check(theme_after["chartAlive"], "切主题后图表实例存活")

            # 4 个类别 tab 切换（无「Canvas is already in use」）
            errors.clear()
            tab_result = page.evaluate(
                """async () => {
                    const out = [];
                    const n = document.querySelectorAll('#trend-tabs button').length;
                    for (let i = 0; i < n; i++) {
                      // 每轮重新取节点：若实现重建了 tab DOM，旧引用会脱离文档导致 classList 断言假失败
                      document.querySelectorAll('#trend-tabs button')[i].click();
                      await new Promise(r => setTimeout(r, 350));
                      const cur = document.querySelectorAll('#trend-tabs button')[i];
                      out.push({ name: cur.textContent,
                                 active: cur.classList.contains('active'),
                                 chart: !!(window.Chart && window.Chart.getChart(document.getElementById('chart-main'))),
                                 meta: document.querySelectorAll('#trend-meta .meta-item').length });
                    }
                    return out;
                }"""
            )
            for t in tab_result:
                check(t["chart"] and t["active"] and t["meta"] >= 1,
                      f"tab「{t['name']}」切换后图表可用", t)
            check(not errors, "tab 切换无 console error", errors)

            # 时间范围 1Y
            page.evaluate("() => document.querySelector('#range-bar button[data-days=\"365\"]').click()")
            page.wait_for_timeout(2500)
            y = page.evaluate(MEASURE_JS)
            check(y["canvas"] and y["canvas"]["bitmapH"] == y["canvas"]["cssH"], "1Y 档 canvas 尺寸仍一致", y["canvas"])
            check("近 1 年" in page.evaluate("() => document.getElementById('range-label').textContent"),
                  "1Y 档标签为「近 1 年」")
            # Step 10 端到端证据：回填后 1Y 档必须真的渲染出 ~1 年交易日（而非仍 90 点）。
            # 注意：x 轴是 category 且 labels 由 options.scales.x 提供 → chart.data.labels 恒为空，
            # 渲染点数只能从 datasets[].data 取（每个点是 {x, y} 对象）。
            pts = page.evaluate(
                """() => {
                    const c = window.Chart && window.Chart.getChart(document.getElementById('chart-main'));
                    if (!c) return null;
                    return { points: c.data.datasets.map(d => d.data.length),
                             axisLabels: ((c.options.scales || {}).x || {}).labels ? c.options.scales.x.labels.length : 0 };
                }"""
            )
            check(bool(pts) and max(pts["points"] or [0]) >= 200,
                  "1Y 档主图实际渲染 ≥200 个交易日（历史回填生效）", pts)

            # 375 档：抽屉 + 单列
            page.set_viewport_size({"width": 375, "height": 812})
            page.goto(url, wait_until="load")
            page.wait_for_timeout(3500)
            # 抽屉：点击后必须等过渡（.25s）结束再读 transform，否则读到的是动画起始值
            mob_before = page.evaluate(
                """() => {
                    const sb = document.getElementById('sidebar');
                    const r = sb.getBoundingClientRect();
                    return { pos: getComputedStyle(sb).position, left: Math.round(r.left),
                             hidden: getComputedStyle(sb).transform };
                }"""
            )
            page.evaluate("() => document.getElementById('menu-toggle').click()")
            page.wait_for_timeout(600)
            mob = page.evaluate(
                """() => {
                    const sb = document.getElementById('sidebar');
                    const r = sb.getBoundingClientRect();
                    return { open: document.body.classList.contains('nav-open'),
                             transform: getComputedStyle(sb).transform,
                             left: Math.round(r.left),
                             chartWrapH: Math.round(document.getElementById('chart-main-wrap').getBoundingClientRect().height),
                             scrollW: document.scrollingElement.scrollWidth,
                             innerW: window.innerWidth };
                }"""
            )
            check(mob_before["pos"] == "fixed", "375 侧栏为 fixed 抽屉", mob_before["pos"])
            check(mob_before["left"] < 0, "375 抽屉初始收起（translateX(-100%)）", mob_before["left"])
            check(mob["open"] and mob["left"] == 0, "点击菜单后抽屉完全展开", mob)
            check(mob["chartWrapH"] == 280, "375 主图高度 280px", mob["chartWrapH"])
            check(mob["scrollW"] == mob["innerW"], "375 无横向溢出", (mob["scrollW"], mob["innerW"]))
            mob_card = page.evaluate(MEASURE_JS)
            assert_viewport(375, 812, mob_card)

            check(not errors, "全流程 console error = 0", errors[:5])
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        report["failures"] = FAILURES
        out = OUT_DIR / "verify-report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告: {out}")

    print("\n===== 结果 =====")
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 条")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
