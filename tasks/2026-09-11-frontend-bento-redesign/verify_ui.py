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
import re
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
    // G-8 降级块存在性（无头 Chromium 恒支持 backdrop-filter，无法真实触发降级分支 →
    // plan §6 G-8 允许「改用 @supports 断言存在」作为等价验证）
    hasFallbackRule: (() => {
      try {
        for (const sheet of document.styleSheets) {
          let rules;
          try { rules = sheet.cssRules; } catch (e) { continue; }
          for (const r of rules) {
            if (r.constructor && r.constructor.name === 'CSSSupportsRule'
                && /backdrop-filter/.test(r.conditionText || '')) return true;
          }
        }
      } catch (e) { /* 跨域样式表等 */ }
      return false;
    })(),
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
    check(g["hasFallbackRule"] is True, f"{w} 存在 backdrop-filter 的 @supports 降级块（G-8）",
          g["hasFallbackRule"])


G9_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const cs = (el) => (el ? getComputedStyle(el) : null);
  const vis = (el) => !!el && cs(el).display !== 'none';
  const navItem = [...document.querySelectorAll('#sidebar .nav-item')]
    .find((a) => a.getAttribute('data-target') === 'us-sectors');
  const radio = q('#sector-tab-cn'), panels = q('.tab-panels');
  return {
    rowNewsCols: cs(q('.row-news')).gridTemplateColumns.trim().split(/\s+/).length,
    sectorBlocks: q('#sectors') ? q('#sectors').querySelectorAll('.sub-block').length : 0,
    phCount: document.querySelectorAll('[data-placeholder="1"]').length,
    phNotes: [...document.querySelectorAll('[data-placeholder="1"] .ph-note')].map((e) => e.textContent),
    fundFlowBody: !!q('#fund-flow-body'),
    riskBody: !!q('#risk-appetite-body'),
    newsBody: !!q('#news-body'),
    sectorBody: !!q('#sector-body'),
    usSectorsBody: !!q('#us-sectors-body'),
    sectorBodyRows: document.querySelectorAll('#sector-body tr').length,
    usSectorRows: document.querySelectorAll('#us-sectors-body .bar-row').length,
    panelsCount: document.querySelectorAll('#us-sectors .panel').length,
    cnVisible: vis(q('.panel-cn')),
    usVisible: vis(q('.panel-us')),
    cnInPanel: !!(q('.panel-cn') && q('.panel-cn').contains(q('#sector-body'))),
    usInPanel: !!(q('.panel-us') && q('.panel-us').contains(q('#us-sectors-body'))),
    // 坑②：radio 必须是 .tab-panels 的前置同级兄弟（FOLLOWING ⇒ panels 在 radio 之后）
    radiosBeforePanels: !!(radio && panels && (radio.compareDocumentPosition(panels) & Node.DOCUMENT_POSITION_FOLLOWING)),
    radioDisplay: radio ? cs(radio).display : null,   // 坑①：不得为 none
    navLabel: navItem ? navItem.textContent.trim() : null,
    sectorH: q('#sectors') ? Math.round(q('#sectors').getBoundingClientRect().height) : null,
    rowNewsH: q('.row-news') ? Math.round(q('.row-news').getBoundingClientRect().height) : null,
    // row-3 三卡的「自然内容高」（border-box 含 padding，累加非绝对定位子元素 + 其 margin）：
    // 用于定位"谁把 .row-3 撑高进而顶破 scrollHeight ≤1240"（stretch 等高时 getBoundingClientRect 无法区分）
    row3ContentH: (() => {
      const out = {};
      ['#overview', '#sectors', '#us-sectors'].forEach((sel) => {
        const el = q(sel);
        if (!el) { out[sel] = null; return; }
        const st = getComputedStyle(el);
        let h = parseFloat(st.paddingTop) + parseFloat(st.paddingBottom);
        [...el.children].forEach((ch) => {
          const cst = getComputedStyle(ch);
          if (cst.position === 'absolute') return;
          h += ch.getBoundingClientRect().height + parseFloat(cst.marginTop) + parseFloat(cst.marginBottom);
        });
        out[sel] = Math.round(h);
      });
      return out;
    })(),
    scrollH: document.scrollingElement.scrollHeight,
  };
}
"""


def assert_g9(page, g9: dict) -> None:
    """G-9 双 tab + 行 3/行 4 重排断言（含三个 :checked 坑的守卫）。需在 1920 视口调用。"""
    print("\n--- G-9 行3/行4 重排 + 双 tab ---")
    print(f"  rowNews 列={g9['rowNewsCols']} 子块={g9['sectorBlocks']} 占位={g9['phCount']} "
          f"panels={g9['panelsCount']} nav={g9['navLabel']} sectorH={g9['sectorH']} "
          f"rowNewsH={g9['rowNewsH']} scrollH={g9['scrollH']}")
    print(f"  row-3 自然内容高={g9['row3ContentH']}")

    check(g9["rowNewsCols"] == 2, "行 4 为 2 列（1fr 2.4fr）", g9["rowNewsCols"])
    check(g9["sectorBlocks"] == 3, "#sectors 内 3 个子块（风险偏好/资金流向/市场关系）", g9["sectorBlocks"])
    # 三十三期：news 点亮后占位 2→1（仅 fund-flow）
    check(g9["phCount"] == 1, "全站 data-placeholder 计数 = 1", g9["phCount"])
    check(len(g9["phNotes"]) == 1 and g9["phNotes"] == ["数据未接入"],
          "占位文案仍为「数据未接入」（资金流向）", g9["phNotes"])
    for key in ("fundFlowBody", "riskBody", "newsBody", "sectorBody", "usSectorsBody"):
        check(g9[key], f"app.js 契约 id 保留：{key}")
    check(g9["panelsCount"] == 2, "双 tab 有 2 个 panel", g9["panelsCount"])
    check(g9["cnInPanel"] and g9["usInPanel"], "sector-body / us-sectors-body 分属不同 tab 面板")
    check(g9["radiosBeforePanels"] is True, "radio 是 .tab-panels 的前置同级兄弟（坑②）", g9["radiosBeforePanels"])
    check(g9["radioDisplay"] != "none", "radio 未 display:none（坑①）", g9["radioDisplay"])
    check(g9["navLabel"] == "板块表现", "侧栏 nav 文案为「板块表现」", g9["navLabel"])
    check(g9["sectorBodyRows"] >= 1 and g9["usSectorRows"] >= 1,
          "两个面板各自渲染出行数", (g9["sectorBodyRows"], g9["usSectorRows"]))
    check(g9["cnVisible"] and not g9["usVisible"],
          "默认激活 A股 tab（panel-cn 可见 / panel-us 隐藏）", (g9["cnVisible"], g9["usVisible"]))

    after = page.evaluate(
        """() => {
            const cn = document.querySelector('.panel-cn'), us = document.querySelector('.panel-us');
            const vis = (el) => !!el && getComputedStyle(el).display !== 'none';
            document.getElementById('sector-tab-us').checked = true;
            const lab = document.querySelector('label[for="sector-tab-us"]');
            return { cn: vis(cn), us: vis(us), labelBg: getComputedStyle(lab).backgroundColor };
        }"""
    )
    page.wait_for_timeout(250)
    check(after["us"] and not after["cn"], "切到美股 tab：panel-us 可见 / panel-cn 隐藏", after)

    back = page.evaluate(
        """() => {
            document.getElementById('sector-tab-cn').checked = true;
            const a = [...document.querySelectorAll('#sidebar .nav-item')]
              .find((x) => x.getAttribute('data-target') === 'us-sectors');
            a.click();
            const el = document.getElementById('us-sectors');
            return { cn: getComputedStyle(document.querySelector('.panel-cn')).display !== 'none',
                     inView: Math.abs(el.getBoundingClientRect().top) < window.innerHeight };
        }"""
    )
    page.wait_for_timeout(700)
    check(back["cn"], "切回 A股 tab 生效", back)
    check(back["inView"], "nav「板块表现」锚点仍能定位到 #us-sectors", back)


def assert_crosshair(page) -> None:
    """CS-1~CS-7 悬停水平参考线断言（chart-hover-crosshair 任务）。

    在 1920 视口（dark）跑一次即可——鼠标交互与视口无关。画布指纹统一用
    canvas.toDataURL()（同实例前后比对，DPR 无关）；chart 实例统一经
    window.Chart.getChart(canvas) 获取。红跑预期：CS-1/CS-2/CS-4/CS-7b FAIL
    （它们测的就是插件行为本身），CS-3/CS-5/CS-6/CS-7a PASS（回归护栏）。
    """
    print("\n--- 悬停水平参考线（crosshair）---")
    info = page.evaluate(
        """() => {
            const c = window.Chart && window.Chart.getChart(document.getElementById('chart-main'));
            if (!c) return null;
            const r = document.getElementById('chart-main').getBoundingClientRect();
            const a = c.chartArea;
            return { area: {left: a.left, top: a.top, right: a.right, bottom: a.bottom},
                     rect: {left: r.left, top: r.top},
                     plugins: (c.config.plugins || []).map(function (p) { return p && p.id; }),
                     optPlugin: c.options.plugins ? (c.options.plugins.hoverCrosshair !== undefined) : false };
        }"""
    )
    check(bool(info), "chart-main 实例可达")
    if not info:
        return
    # CS-1 内联插件已挂载（内联插件登记在 chart.config.plugins；options.plugins 作兜底）
    has_plugin = "hoverCrosshair" in (info["plugins"] or []) or info["optPlugin"]
    check(has_plugin, "CS-1 插件 hoverCrosshair 已挂载", info["plugins"])
    # CS-5 布局回归（与 1920 专项「总高 ≤1240」同口径，就地复核）
    sh = page.evaluate("() => document.scrollingElement.scrollHeight")
    check(sh <= 1240, "CS-5 scrollHeight @1920 ≤ 1240", sh)

    cx = info["rect"]["left"] + (info["area"]["left"] + info["area"]["right"]) / 2
    h = info["area"]["bottom"] - info["area"]["top"]
    y1 = info["rect"]["top"] + info["area"]["top"] + h * 0.3
    y2 = info["rect"]["top"] + info["area"]["top"] + h * 0.7
    snap = "() => document.getElementById('chart-main').toDataURL()"
    baseline = page.evaluate(snap)
    page.mouse.move(cx, y1)
    page.wait_for_timeout(600)   # tooltip 出场动画稳定后再取指纹
    snap1 = page.evaluate(snap)
    # CS-6 tooltip 与横线并存（R5：横线画在 tooltip 之下，不得遮盖）
    tip = page.evaluate(
        "() => { const c = window.Chart.getChart(document.getElementById('chart-main'));"
        " return c.tooltip ? c.tooltip.opacity : null; }"
    )
    check(tip is not None and tip > 0, "CS-6 悬停后 tooltip 仍显示（opacity>0）", tip)
    page.mouse.move(cx, y2)
    page.wait_for_timeout(400)
    snap2 = page.evaluate(snap)
    # CS-2 核心判据：同 x 不同 Y 画布指纹必然变化（横线跟手；无插件时两次相同）
    check(snap1 != snap2, "CS-2 不同 Y 位置画布指纹不同（横线实时跟随）")
    # CS-4 气泡文本 = 刻度同源格式化函数对该高度的输出，且格式 [+-]d.d%
    c4 = page.evaluate(
        """() => { const c = window.Chart.getChart(document.getElementById('chart-main'));
            if (c.$crossY == null) return null;
            return { label: c.$crosshairLabel,
                     expect: fmtAxisPct(c.scales.y.getValueForPixel(c.$crossY)) }; }"""
    )
    ok4 = bool(c4) and c4["label"] == c4["expect"] \
        and re.fullmatch(r"[+-]?\d+\.\d%", c4["label"] or "") is not None
    check(ok4, "CS-4 气泡文本 = fmtAxisPct(getValueForPixel($crossY)) 且格式匹配", c4)
    # CS-3 移出绘图区即隐藏（等 tooltip 出场动画结束再与进入前基线比对）
    page.mouse.move(10, 500)
    page.wait_for_timeout(900)
    snap3 = page.evaluate(snap)
    check(snap3 == baseline, "CS-3 移出绘图区后画布回到基线（横线+气泡+tooltip 全消失）")
    # CS-7 切 tab 重建后不丢：实例唯一（R9）+ 新实例仍带插件（重建走同一条 renderMainChart）
    page.evaluate("() => document.querySelectorAll('#trend-tabs button')[1].click()")
    page.wait_for_timeout(1200)
    c7 = page.evaluate(
        """() => { const c = window.Chart.getChart(document.getElementById('chart-main'));
            return { alive: !!c,
                     count: window.Chart.instances ? Object.keys(window.Chart.instances).length : null,
                     plugins: c ? (c.config.plugins || []).map(function (p) { return p && p.id; }) : null }; }"""
    )
    check(c7["alive"] and c7["count"] == 1, "CS-7a 切 tab 后实例存活且唯一（R9）", c7)
    check("hoverCrosshair" in (c7["plugins"] or []),
          "CS-7b 重建后的新实例仍带 hoverCrosshair", c7["plugins"])


FIDELITY_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const navBad = [];
  document.querySelectorAll('#sidebar .nav-item').forEach(function (el) {
    const t = el.getAttribute('data-target');
    if (t) { if (!document.getElementById(t)) navBad.push(el.textContent.trim() + '→' + t); }
    else if (!el.classList.contains('is-disabled')) navBad.push(el.textContent.trim());
  });
  const c = window.Chart && window.Chart.getChart(document.getElementById('chart-main'));
  const av = q('.avatar');
  return {
    ovIcons: document.querySelectorAll('#overview .mini-card .ico').length,
    ovCards: document.querySelectorAll('#overview .mini-card').length,
    watchIcons: document.querySelectorAll('#watchlist-body tr .ico').length,
    watchRows: document.querySelectorAll('#watchlist-body tr').length,
    usIcons: document.querySelectorAll('#us-sectors-body .bar-row .ico').length,
    usRows: document.querySelectorAll('#us-sectors-body .bar-row').length,
    secIcons: document.querySelectorAll('#sector-body tr .ico').length,
    secRows: document.querySelectorAll('#sector-body tr').length,
    yPos: c ? c.scales.y.position : null,
    brandText: q('.brand-mark') ? q('.brand-mark').textContent.trim() : null,
    avatarRadius: av ? getComputedStyle(av).borderRadius : null,
    navCount: document.querySelectorAll('#sidebar .nav-item').length,
    navDisabled: document.querySelectorAll('#sidebar .nav-item.is-disabled').length,
    navBad: navBad,
    flagUs: document.querySelectorAll('#overview .ico.ico-flag-us').length,
    flagCn: document.querySelectorAll('#overview .ico.ico-flag-cn').length,
    flagImgs: document.querySelectorAll('#overview .ico-flag-img').length,
    icoSize: (() => { const i = q('.ico'); return i ? [i.offsetWidth, i.offsetHeight] : null; })()
  };
}
"""


def assert_fidelity(page, m: dict) -> None:
    """V1~V5 视觉保真断言（visual-fidelity 任务，F-1~F-7a）。

    在 1920 dark 下跑一次；末尾把鼠标移出绘图区，保证后续 assert_crosshair 的基线干净。
    红跑预期：F-1a~d/F-2/F-3/F-4/F-5/F-7a FAIL（测的就是本次改动），F-6 回归护栏 PASS。
    """
    print("\n--- 视觉保真（V1 图标 / V2 y轴右侧 / V3 品牌字 / V4 头像 / V5 导航）---")
    f = page.evaluate(FIDELITY_JS)
    # F-1 四处列表：图标数 == 行/卡数（Q2：内含 1 字符，数据驱动）
    check(f["ovCards"] > 0 and f["ovIcons"] == f["ovCards"],
          "F-1a 市场概览图标数 == 卡数", (f["ovIcons"], f["ovCards"]))
    check(f["watchRows"] > 0 and f["watchIcons"] == f["watchRows"],
          "F-1b 自选列表图标数 == 行数", (f["watchIcons"], f["watchRows"]))
    check(f["usRows"] > 0 and f["usIcons"] == f["usRows"],
          "F-1c 美股行业板块图标数 == 行数", (f["usIcons"], f["usRows"]))
    check(f["secRows"] > 0 and f["secIcons"] == f["secRows"],
          "F-1d A股热点板块图标数 == 行数", (f["secIcons"], f["secRows"]))
    if f["icoSize"]:
        check(f["icoSize"][0] == 16 and f["icoSize"][1] == 16, "F-1e 图标尺寸 16×16", f["icoSize"])
    # F-2 / F-3 / F-4 / F-5
    check(f["yPos"] == "right", "F-2 趋势图 y 轴 position=right", f["yPos"])
    check(f["brandText"] == "MarketPulse", "F-3 品牌字为 MarketPulse", f["brandText"])
    check(f["avatarRadius"] is not None and f["avatarRadius"] != "50%",
          "F-4 头像为圆角方块（radius≠50%）", f["avatarRadius"])
    # F-8 市场概览图标（需求方 2026-09-12 参照效果图定稿）：美股→旗 US、A股→旗 CN，
    # 其余 4 卡（美元/10Y/黄金/原油）→ 圆形图形素材（/static/icons/*.svg，上铺 img、底层色块兜底）。
    check(f["flagUs"] == 1 and f["flagCn"] == 1 and f["flagImgs"] == 6,
          "F-8 市场概览图标：旗 US×1 + 旗 CN×1 + 图形素材×4（img 全挂）",
          (f["flagUs"], f["flagCn"], f["flagImgs"]))
    check(f["navCount"] == 10 and f["navDisabled"] == 3 and not f["navBad"],
          "F-5 nav=10 项（7 真实+3 占位）且 data-target 全命中", f)
    # F-6 回归（1920 口径就地复核布局三件套；console error 由 main() 末尾既有断言覆盖）
    check(m["scrollH"] <= 1240, "F-6a scrollHeight @1920 ≤ 1240", m["scrollH"])
    check(m["scrollW"] == m["innerW"], "F-6b 无横向溢出", (m["scrollW"], m["innerW"]))
    g = m.get("glass") or {}
    check(g.get("glassCovered") is True, "F-6c backdrop 全覆盖",
          (g.get("coveredCount"), g.get("cardCount")))
    # F-7a 跨任务：y 轴移右后 crosshair 读数仍产生（气泡贴右侧由 %TEMP% 像素探针另行取证）
    r = page.evaluate(
        """() => { const cv = document.getElementById('chart-main');
                   const c = window.Chart.getChart(cv);
                   const rect = cv.getBoundingClientRect(), a = c.chartArea;
                   return { cx: rect.left + (a.left + a.right) / 2,
                            cy: rect.top + a.top + (a.bottom - a.top) * 0.4 }; }"""
    )
    page.mouse.move(r["cx"], r["cy"])
    page.wait_for_timeout(500)
    f7 = page.evaluate(
        "() => { const c = window.Chart.getChart(document.getElementById('chart-main'));"
        " return { pos: c.scales.y.position, label: c.$crosshairLabel }; }"
    )
    check(f7["pos"] == "right" and bool(f7["label"]),
          "F-7a 轴在右时 crosshair 读数仍产生", f7)
    page.mouse.move(10, 500)
    page.wait_for_timeout(900)   # 鼠标移出 + tooltip 收场，给 assert_crosshair 留干净基线


NEWS_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const body = q('#news-body');
  const items = [...document.querySelectorAll('#news-body .news-item')];
  const links = [...document.querySelectorAll('#news-body .news-item a')];
  const cs = body ? getComputedStyle(body) : null;
  const a0 = links[0] ? getComputedStyle(links[0]) : null;
  const lens = links.map((a) => a.textContent.length);
  return {
    count: items.length,
    textLens: lens,
    maxLen: lens.length ? Math.max(...lens) : 0,
    invalidHref: links.filter((a) => !/^https?:/.test(a.getAttribute('href') || '')).length,
    missingTitle: links.filter((a) => !a.getAttribute('title')).length,
    metaCount: document.querySelectorAll('#news-body .news-meta').length,
    summaryCount: document.querySelectorAll('#news-body .news-summary').length,
    maxHeight: cs ? cs.maxHeight : null,
    overflowY: cs ? cs.overflowY : null,
    clientHeight: body ? body.clientHeight : null,
    bodyScrollHeight: body ? body.scrollHeight : null,
    cardH: q('#news') ? q('#news').offsetHeight : null,
    alertsH: q('#alerts') ? q('#alerts').offsetHeight : null,
    itemH: items.length ? items[0].offsetHeight : null,
    weight: a0 ? a0.fontWeight : null,
    whiteSpace: a0 ? a0.whiteSpace : null,
    overflowX: a0 ? a0.overflowX : null,
    textOverflow: a0 ? a0.textOverflow : null,
    // 滚动条实测宽度：offsetWidth - clientWidth - 左右边框（#sidebar 有 border-right，必须扣掉）
    scrollbarW: (() => {
      const sbw = (el) => {
        if (!el) return null;
        const s = getComputedStyle(el);
        const b = parseFloat(s.borderLeftWidth || 0) + parseFloat(s.borderRightWidth || 0);
        return el.offsetWidth - el.clientWidth - b;
      };
      const out = {};
      ['#news-body', '.alert-list', '#sidebar'].forEach((sel) => { out[sel] = sbw(q(sel)); });
      return out;
    })(),
    // headless Chromium 用 overlay 滚动条（不占布局宽 → 上面恒测到 0），故另查 CSSOM 里
    // ::-webkit-scrollbar 的 width 声明，保证「细滚动条规则确实存在且被解析」。
    sbRuleWidth: (() => {
      for (const sheet of document.styleSheets) {
        let rules;
        try { rules = sheet.cssRules; } catch (e) { continue; }
        for (const r of rules) {
          if (r.selectorText === '::-webkit-scrollbar' && r.style.width) return r.style.width;
        }
      }
      return null;
    })(),
    scrollH: document.scrollingElement.scrollHeight,
  };
}
"""


def assert_news(page, base_url: str) -> None:
    """N-7 最新资讯（宏观一句话新闻条）：DOM 渲染契约 + /api/news 落盘切句。

    同时补齐 plan §7.2 要求、架构师未完成的 `#news` / `#news-body` DOM 实测值。
    """
    print("\n--- N-7 最新资讯（一句话新闻条）---")
    dom = page.evaluate(NEWS_JS)
    try:
        with urllib.request.urlopen(base_url + "api/news", timeout=10) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        payload = {}
        print(f"  /api/news 读取失败: {exc}")
    items = payload.get("items") or []
    sums = [len(it.get("summary") or "") for it in items]
    print(f"  api items={len(items)} sumLens={sums} | dom items={dom['count']} maxLen={dom['maxLen']}")
    print(f"  #news={dom['cardH']} #alerts={dom['alertsH']} itemH={dom['itemH']} "
          f"body client={dom['clientHeight']} scroll={dom['bodyScrollHeight']} "
          f"maxH={dom['maxHeight']} ovf={dom['overflowY']}")
    print(f"  a weight={dom['weight']} whiteSpace={dom['whiteSpace']} overflowX={dom['overflowX']} "
          f"scrollH={dom['scrollH']}")

    check(dom["count"] > 0 and dom["count"] == len(items),
          "N-1 DOM .news-item 数 == /api/news items 数", (dom["count"], len(items)))
    check(dom["maxLen"] <= 121, "N-2 每行文本 ≤121 字（上限与落盘 MAX_SUMMARY_LEN 一致，不再二次截断）",
          dom["textLens"])
    check(dom["metaCount"] == 0 and dom["summaryCount"] == 0,
          "N-3 无 .news-meta / .news-summary（死元素清零）", (dom["metaCount"], dom["summaryCount"]))
    check(dom["overflowY"] == "auto" and dom["maxHeight"] == "132px",
          "N-4 #news-body max-height 132px + overflow-y auto", (dom["maxHeight"], dom["overflowY"]))
    check(dom["invalidHref"] == 0 and dom["missingTitle"] == 0,
          "N-5 href 均 http(s) 且 title 属性非空（tooltip 保信息）",
          (dom["invalidHref"], dom["missingTitle"]))
    check(all(s <= 120 for s in sums),
          "N-7 /api/news 每条 summary ≤120 字（落盘切句生效）", sums)
    print(f"  scrollbarW={dom['scrollbarW']} sbRuleWidth={dom['sbRuleWidth']}")
    check(dom["sbRuleWidth"] == "6px",
          "N-11a 样式表含 ::-webkit-scrollbar{width:6px}（系统默认 15px）",
          dom["sbRuleWidth"])
    check(all((v is not None and v <= 8) for v in dom["scrollbarW"].values()),
          "N-11b 各滚动容器实测宽 ≤8px（headed 实测 6px；headless overlay 为 0）",
          dom["scrollbarW"])
    check(dom["weight"] == "400", "N-8 .news-item a 字重 400（它是正文不是标题）", dom["weight"])
    check(dom["whiteSpace"] == "nowrap" or dom["whiteSpace"] == "normal",
          "N-9 white-space 合法（nowrap 桌面 / normal 小屏换行）", dom["whiteSpace"])
    check(dom["overflowX"] == "auto",
          "N-9b 桌面单行放不下时可横向滚动（overflow-x:auto，替代省略号吞字）", dom["overflowX"])
    check(dom["cardH"] is not None and dom["alertsH"] is not None and abs(dom["cardH"] - dom["alertsH"]) <= 2,
          "N-10 #news 与 #alerts 等高（行高不随条数漂移）", (dom["cardH"], dom["alertsH"]))


POLISH_JS = r"""
() => {
  const root = getComputedStyle(document.documentElement);
  // 探针：把 CSS 变量解析成 computed rgb，并生成一对 .chg-pill 供比色
  // （探针绝对定位于屏外 → 不参与布局、不影响 scrollHeight）
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;left:-9999px;top:0';
  probe.innerHTML = '<span class="chg-pill pos">+1.00%</span><span class="chg-pill neg">-1.00%</span>' +
                    '<i id="__g"></i><i id="__r"></i>';
  const gEl = probe.querySelector('#__g');
  const rEl = probe.querySelector('#__r');
  gEl.style.color = 'var(--green)';
  rEl.style.color = 'var(--red)';
  document.body.appendChild(probe);
  const pillPos = probe.querySelector('.chg-pill.pos');
  const pillNeg = probe.querySelector('.chg-pill.neg');
  const refGreen = getComputedStyle(gEl).color;
  const refRed = getComputedStyle(rEl).color;
  const data = {
    muted: root.getPropertyValue('--text-muted').trim(),
    refGreen: refGreen, refRed: refRed,
    pillPosColor: getComputedStyle(pillPos).color,
    pillNegColor: getComputedStyle(pillNeg).color,
    pillPosBg: getComputedStyle(pillPos).backgroundColor,
    pillNegBg: getComputedStyle(pillNeg).backgroundColor,
  };
  probe.remove();

  // P-4 真实页面已渲染的 .chg-pill：类名与颜色必须一致（防撞 .pill.pos 的「涨变红」反转）
  const real = [...document.querySelectorAll('.chg-pill')];
  data.realPillCount = real.length;
  data.realPillBad = real.filter((el) => {
    const c = getComputedStyle(el).color;
    const p = el.classList.contains('pos'), n = el.classList.contains('neg');
    if (!p && !n) return true;
    if (p && c !== refGreen) return true;
    if (n && c !== refRed) return true;
    return false;
  }).length;

  // P-2 千分位：4 位以上整数缺逗号 = 未生效（非纯数字文本如「数据未接入」不计入）
  const numRe = /^([\d,]+)\.(\d{1,2})$/;
  const texts = (sel) => [...document.querySelectorAll(sel)].map((e) => e.textContent.trim());
  const mini = texts('#overview-body .mini-val');
  const kpi = texts('.kpi-val');
  const badSep = (arr) => arr.filter((t) => {
    const m = numRe.exec(t);
    if (!m) return false;
    return m[1].replace(/,/g, '').length >= 4 && m[1].indexOf(',') < 0;
  }).length;
  data.miniTexts = mini;
  data.kpiTexts = kpi;
  data.miniNumCount = mini.filter((t) => numRe.test(t)).length;
  data.miniBadSep = badSep(mini);
  data.kpiBadSep = badSep(kpi);
  data.hasSep = mini.concat(kpi).some((t) => t.indexOf(',') >= 0);

  // P-3 无溢出（千分位多 1 字符不得撑出省略号）
  data.overflow = [...document.querySelectorAll('.kpi-val, #overview-body .mini-val')]
    .filter((el) => el.scrollWidth > el.clientWidth + 1).length;

  // P-5 涨跌幅未复用 .pill（.pill.pos 是相关性语义且配色相反）
  data.pillInData = document.querySelectorAll('.data-table .pill, .bar-row .pill').length;

  // P-4 骨架屏：数据到达后可见骨架必须清零（5 处加载态都被真实内容替换）
  data.skVisible = [...document.querySelectorAll('.skeleton')].filter((el) => el.offsetParent !== null).length;

  data.scrollH = document.scrollingElement.scrollHeight;
  data.scrollW = document.scrollingElement.scrollWidth;
  data.innerW = window.innerWidth;
  return data;
}
"""


def assert_polish(page, base_url: str) -> None:
    """P-1~P-7 前端评审落地（frontend-polish 任务）：对比度 / 千分位 / 涨跌 Badge / 骨架屏 + 护栏回归。"""
    print("\n--- P 前端评审落地（对比度 / 千分位 / Badge / 骨架屏）---")
    d = page.evaluate(POLISH_JS)
    print(f"  muted={d['muted']} chg-pill real={d['realPillCount']} bad={d['realPillBad']} "
          f"bg=({d['pillPosBg'], d['pillNegBg']})")
    print(f"  mini={d['miniTexts']} | kpi={d['kpiTexts']}")
    print(f"  overflow={d['overflow']} pillInData={d['pillInData']} skVisible={d['skVisible']} "
          f"scrollH={d['scrollH']}")

    check(d["muted"].upper() == "#8E9BAE",
          "P-1 dark --text-muted = #8E9BAE（对比度 ≈6.9:1）", d["muted"])
    check(d["miniNumCount"] > 0 and d["miniBadSep"] == 0 and d["kpiBadSep"] == 0 and d["hasSep"],
          "P-2 价格带千分位（≥4 位整数必含逗号）",
          (d["miniNumCount"], d["miniBadSep"], d["kpiBadSep"], d["hasSep"]))
    check(d["overflow"] == 0,
          "P-3 .kpi-val / .mini-val 无溢出（千分位多 1 字符不撑破）", d["overflow"])
    check(d["realPillCount"] > 0 and d["realPillBad"] == 0
          and d["pillPosColor"] == d["refGreen"] and d["pillNegColor"] == d["refRed"],
          "P-4 .chg-pill 绿涨红跌（未撞 .pill.pos 的反转配色）",
          (d["realPillCount"], d["realPillBad"], d["pillPosColor"], d["refGreen"]))
    check(d["pillInData"] == 0, "P-5 涨跌幅未复用 .pill（独立命名空间）", d["pillInData"])

    # P-6 骨架屏 colspan 走「静态模板源」断言：加载态转瞬即逝，运行时抓不稳定（未打补丁的
    # 旧模板 colspan 也是 5，故此条是**防回退护栏**而非「先红」项）。
    html = ""
    try:
        with urllib.request.urlopen(base_url, timeout=10) as r:
            html = r.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"  首页 HTML 读取失败: {exc}")
    sk_colspans = re.findall(r'<tr class="sk-row"><td colspan="(\d+)"', html)
    check(bool(sk_colspans) and all(c == "5" for c in sk_colspans),
          "P-6 骨架行 colspan 全为 5（图标列已使表头变 5 列）", sk_colspans)
    check('class="skeleton sk-card"' in html and 'class="skeleton sk-item"' in html,
          "P-6b 首屏骨架屏已就位（概览卡 + 告警条）", html.count('class="skeleton'))

    check(d["skVisible"] == 0, "P-4b 数据到达后可见骨架清零（加载态被真实内容替换）", d["skVisible"])

    # P-7 回归护栏（与 F-6a/CS-5 同口径，此处独立复测一次）
    check(d["scrollH"] <= 1240, "P-7a scrollHeight @1920 ≤1240", d["scrollH"])
    check(d["scrollW"] == d["innerW"], "P-7b 无横向溢出", (d["scrollW"], d["innerW"]))


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
    check(len(m["phNotes"]) == 1 and m["phNotes"] == ["数据未接入"],
          f"{w} 1 个占位模块文案（资金流向）", m["phNotes"])
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
            check(m["rowNews"] == 2, "row-news 2 列（G-9 行 4 改版：告警窄 + 资讯宽）", m["rowNews"])
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

            # G-9 断言需在 1920 视口（行 4 断点 ≥1400px）；三视口循环结束时页面停在 375 → 重新加载
            page.set_viewport_size({"width": 1920, "height": 1080})
            page.goto(url, wait_until="load")
            try:
                page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(800)
            assert_g9(page, page.evaluate(G9_JS))
            assert_news(page, url)   # N-7 最新资讯（含 §7.2 要求的 #news DOM 实测）
            assert_polish(page, url)  # P-1~P-7 前端评审落地（对比度 / 千分位 / Badge / 骨架屏）

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
            # §8.4 双主题各自调参：light 档同样跑一遍玻璃判据（GLASS_RANGES 按当前主题自动切区间）
            assert_glass(1920, 1080, page.evaluate(GLASS_JS))

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

            # 视觉保真（visual-fidelity 任务）：F-1~F-7a；末尾移出鼠标给 crosshair 留干净基线
            assert_fidelity(page, m)
            # 悬停水平参考线（chart-hover-crosshair 任务）：鼠标交互与视口无关，1920 跑一次
            assert_crosshair(page)

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
