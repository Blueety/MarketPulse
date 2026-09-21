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
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "venv" / "Scripts" / "python.exe"
OUT_DIR = Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "marketpulse-verify"

# 2026-09-14（kpi-responsive-fix）：三视口 → 五视口。
# ⚠️ 原 1920/1280/375 恰好**避开**两个坏带（1500–1919 五列无断点、769–1024 三列挤爆），
#    所以脚本报全绿却漏掉了真实的响应式缺陷 —— 补 1600（空档 A）与 900（空档 B）。
VIEWPORTS = [(1920, 1080), (1600, 900), (1280, 720), (900, 800), (375, 812)]

FAILURES: list[str] = []
#: 未判定的断言（**SKIP 不等于通过**）：每条 `{label, reason, detail}`，与 stdout 同源写进 report.json。
#: 引入它的目的见 plan §0：把「上游不可用」与「代码回归」分开，免得真回归被红色背景淹没。
SKIPPED: list[dict] = []
#: PASS 计数（只用于"SKIP 占比"护栏：SKIPPED > 总数 × 0.5 时提示环境不可信）
N_PASS = 0

#: 上游可用性快照（main() 在跑断言**之前**探测一次，避免运行中状态漂移）
UPSTREAM: dict = {"macro": True, "econ": True, "detail": {}}

#: `--strict`：有 SKIP 也判失败（供"我要全量验证"时用；plan §10.2）
STRICT = "--strict" in sys.argv

#: 直连探测用（**刻意独立于被测链路**：不 import `src.fetcher` / `web.app` 的任何函数）
_PROBE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PROBE_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=5d&interval=1d"
PROBE_BLS = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def _probe_get(url: str, timeout: float) -> tuple[bool, str]:
    """GET 探测：返回 `(是否可用, 说明)`。

    🔴 plan §3.3 约束②（**主要安全性来源**）：**只有"明确知道上游挂了"才算不可用**；
    超时、探测自身异常、响应无法解读一律**视为可用** ⇒ 那些失败继续报 FAIL。
    这样 SKIP 永远不可能掩盖"我们自己的 bug"。
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _PROBE_UA,
                                                  "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096)
        if resp.status != 200:
            return False, f"HTTP {resp.status}"
        try:                                  # 结果解读不了 ⇒ 不确定 ⇒ 视为可用
            json.loads(body.decode("utf-8", errors="replace"))
        except Exception:                     # noqa: BLE001
            return True, "响应无法解读(视为可用)"
        return True, "HTTP 200"
    except urllib.error.HTTPError as exc:     # 明确拿到非 2xx ⇒ 上游不可用
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:      # 连接错误 ⇒ 上游不可用（但超时另算）
        if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
            return True, "超时(视为可用)"
        return False, f"URLError: {str(getattr(exc, 'reason', exc))[:60]}"
    except (TimeoutError, socket.timeout):
        return True, "超时(视为可用)"
    except Exception as exc:                  # noqa: BLE001 —— 探测自身异常 ⇒ 视为可用
        return True, f"{type(exc).__name__}(视为可用)"


def _probe_bls(timeout: float) -> tuple[bool, str]:
    """BLS 是 POST 接口，单独探一次（同样的"不确定即视为可用"）。"""
    try:
        payload = json.dumps({"seriesid": ["CUUR0000SA0"], "startyear": "2025",
                              "endyear": "2025"}).encode("utf-8")
        req = urllib.request.Request(PROBE_BLS, data=payload,
                                     headers={"User-Agent": _PROBE_UA,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read(4096)
        return (resp.status == 200), f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
            return True, "超时(视为可用)"
        return False, f"URLError: {str(getattr(exc, 'reason', exc))[:60]}"
    except (TimeoutError, socket.timeout):
        return True, "超时(视为可用)"
    except Exception as exc:                  # noqa: BLE001
        return True, f"{type(exc).__name__}(视为可用)"


def probe_upstream(timeout: float = 8.0) -> dict:
    """直连上游判定可用性 → `{"macro": bool, "econ": bool, "detail": {}}`。

    - `macro` = Yahoo chart（`/api/macro` 的源）；`econ` = BLS publicAPI（`/api/econ` 的源）。
    - 🔴 **独立口径**（约束①）：**直连上游 URL**，不复用 `src/fetcher` / `web/app` 的任何函数 ——
      否则"我们的代码坏了"会让探测也失败，于是 bug 被误判成"上游挂了"而被 SKIP。
      URL 与 fetcher 有重复是**有意的**（本项目「独立期望值预言机」方法论同源）。
    - `MP_VERIFY_UPSTREAM_DOWN=1`：仅供**验证分层机制本身**（强制判 DOWN，不联网）——
      用它可以在上游正常时也复现"SKIP 而非 FAIL"。
    """
    if os.environ.get("MP_VERIFY_UPSTREAM_DOWN") == "1":
        return {"macro": False, "econ": False,
                "detail": {"macro": "强制 DOWN(MP_VERIFY_UPSTREAM_DOWN=1)",
                           "econ": "强制 DOWN(MP_VERIFY_UPSTREAM_DOWN=1)"}}
    macro_ok, macro_why = _probe_get(PROBE_YAHOO, timeout)
    econ_ok, econ_why = _probe_bls(timeout)
    return {"macro": macro_ok, "econ": econ_ok, "detail": {"macro": macro_why, "econ": econ_why}}


def check(cond: bool, label: str, actual=None, expect=None, deps=()) -> None:
    """记录一条断言结果：三态 `PASS` / `FAIL` / `SKIP`。

    `deps=("macro", "econ")`：声明该断言**依赖哪个上游**。
    **仅当**该 dep 被 `probe_upstream()` 独立确认"不可用"时，失败才降级为 `SKIP`；
    否则（含探测不确定 / 上游可用但数据为空）**一律 FAIL** —— 后者恰恰说明是我们自己的 bug。

    `deps=()`（默认）⇒ **永不 SKIP**，行为与改造前完全一致（保守默认）。
    ⚠️ 逐条标记、**宁少勿多**：漏标只会让该红维持 FAIL（安全），多标才会掩盖回归。
    """
    global N_PASS
    if cond:
        N_PASS += 1
        print(f"  PASS  {label}")
        return
    down = [d for d in deps if not UPSTREAM.get(d, True)]
    if down:
        why = "上游 %s 不可用（已直连确认）" % "/".join(down)
        SKIPPED.append({"label": label, "reason": why,
                        "detail": {d: UPSTREAM.get("detail", {}).get(d) for d in down}})
        print(f"  SKIP  {label}  ← {why}")
        return
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
    usSectorRows: document.querySelectorAll('#us-sectors-body tr').length,
    watchRows: document.querySelectorAll('#watchlist-body tr').length,
    watchHidden: !!q('#watchlist-section.hidden'),
    alertCards: document.querySelectorAll('.alert-card').length,
    placeholderCards: document.querySelectorAll('[data-placeholder="1"]').length,
    phNotes: [...document.querySelectorAll('[data-placeholder="1"] .ph-note')].map(e => e.textContent),
    topbarDate: (q('#topbar-date') || {}).textContent || null,
    // 2026-09-16（market-session-status）：单行 #market-status → 两行 #market-status-cn / -us。
    // ⚠️ 不要再引用 #market-status 单数 id：它已不存在，取值恒 null ⇒ 断言会静默变假绿。
    marketCn: (q('#market-status-cn') || {}).textContent || null,
    marketUs: (q('#market-status-us') || {}).textContent || null,
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
    // 抽屉覆盖层的实底色（2026-09-17 drawer-opaque-fixes：≤768 抽屉必须不透明）
    elevatedBg: (() => { const t = document.createElement('div');
        t.style.backgroundColor = 'var(--bg-elevated)'; t.style.position = 'absolute';
        t.style.visibility = 'hidden'; document.body.appendChild(t);
        const c = cs(t).backgroundColor; t.remove(); return c; })(),
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
    # G-6：顶栏做玻璃层、侧栏只透明（规避 R19 sticky + blur 残影）—— **仅桌面（>768）**。
    check((g["topbarBackdrop"] or "none") != "none", f"{w} .topbar backdrop-filter 生效",
          g["topbarBackdrop"])
    #   ⚠️ 2026-09-17（drawer-opaque-fixes）按视口分语义：≤768 时侧栏是 **fixed 抽屉覆盖层**，
    #   沿用 transparent 会叠在遮罩上 ⇒ 内容透出、文字不可读（用户真机 + 浅色主题实测）。
    #   ⇒ 抽屉必须为实底 `--bg-elevated`（light #FFF / dark #111827），且同样**不加** backdrop-filter
    #   （半透明玻璃在压暗背景上还是透，修不彻底）。桌面分支保持 G-6 原判据逐字不变。
    check((g["sidebarBackdrop"] or "none") == "none",
          f"{w} #sidebar 无 backdrop-filter（两个分支共同要求）",
          (g["sidebarBg"], g["sidebarBackdrop"]))
    if w > 768:
        check((g["sidebarBg"] or "") in ("rgba(0, 0, 0, 0)", "transparent"),
              f"{w} #sidebar 透明且无 backdrop-filter（G-6：桌面与页面同层）",
              (g["sidebarBg"], g["sidebarBackdrop"]))
    else:
        check((g["sidebarBg"] or "") == (g["elevatedBg"] or ""),
              f"{w} #sidebar 抽屉为实底 --bg-elevated（覆盖层不可透，drawer-opaque-fixes）",
              (g["sidebarBg"], g["elevatedBg"]))
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
    usSectorRows: document.querySelectorAll('#us-sectors-body tr').length,
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
    # CS-2（旧）已由下方 `assert_crosshair_snap` 的 CS-2a / CS-2b 取代（plan §6 Step 4）：
    #   原判据「同 x 不同 Y 指纹必不同」测的是横线**跟手**；吸附后该语义**反转**
    #   （同 x 纵移会吸在同一条线上）→ plan §3.6 实测必红。
    #   ⚠️ 不是"删断言让它变绿"：替代断言 CS-2b 在**改动前**必红（跟手 → 两个 y 必然不同）。
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


# —— 吸附（crosshair snap，2026-09-15 crosshair-snap 任务）——
# 独立探针：**不用插件的 $crossSource 当期望值**，而是自己按几何规则算出「应该吸到哪一点」，
# 再与插件的 $crossY / $crossSource 比对 —— 否则就是「用插件验证插件」（恒真断言）。
# 坐标系纪律：全部 **CSS 像素**（e.x/e.y 与 meta.data[].y 同空间），**不乘 devicePixelRatio**；
# 并列（tie）取**较小索引**（plan §3.4(2) 实测 colCount 曾为 4，必须确定性）。
SNAP_JS = r"""
({id, mx, my}) => {
  const cv = document.getElementById(id);
  const c = window.Chart && window.Chart.getChart(cv);
  if (!c) return null;
  const r = cv.getBoundingClientRect();
  const a = c.chartArea;
  // ⚠️ Chart.js 的 getRelativePosition 对事件坐标做了 **Math.round**（整数像素）——
  //    探针必须**同口径取整**，否则在两点并列（tie）处会算出与插件不同的索引
  //    （实测：mouse.x=667.803 → 探针取 32、插件取 33；取整后两边都是 668 → 33）。
  const px = Math.round(mx - r.left), py = Math.round(my - r.top);
  const cx = Math.min(Math.max(px, a.left), a.right);   // x 钳制（可见性仍只判 y）
  let idx0 = null, bestDx = Infinity;
  c.data.datasets.forEach((ds, i) => {
    const m = c.getDatasetMeta(i);
    if (m.hidden) return;
    (m.data || []).forEach((p, idx) => {
      if (!p || !isFinite(p.x)) return;
      const d = Math.abs(p.x - cx);
      if (d < bestDx - 1e-9 || (Math.abs(d - bestDx) <= 1e-9 && idx0 !== null && idx < idx0)) {
        bestDx = d; idx0 = idx;
      }
    });
  });
  if (idx0 === null) return { ok: false };
  const OFFS = [0, -1, 1, -2, 2, -3, 3];               // 缺口回退（NaN 必经）
  let best = null, usedIdx = null;
  for (const off of OFFS) {
    const idx = idx0 + off;
    let b = null;
    c.data.datasets.forEach((ds, i) => {
      const m = c.getDatasetMeta(i);
      if (m.hidden) return;
      const p = (m.data || [])[idx];
      if (!p || !isFinite(p.y)) return;
      if (!b || Math.abs(p.y - py) < Math.abs(b.y - py)) b = { y: p.y, dsIndex: i };
    });
    if (b) { best = b; usedIdx = idx; break; }
  }
  const col = [];
  if (usedIdx !== null) {
    c.data.datasets.forEach((ds, i) => {
      const m = c.getDatasetMeta(i);
      if (m.hidden) return;
      const p = (m.data || [])[usedIdx];
      if (p && isFinite(p.y)) col.push({ dsIndex: i, y: p.y });
    });
  }
  return {
    ok: true,
    mouse: { x: px, y: py },
    idx0, usedIdx,
    expectY: best ? best.y : null,
    expectDs: best ? best.dsIndex : null,
    col,
    crossY: c.$crossY === undefined ? null : c.$crossY,
    source: c.$crossSource || null,
    label: c.$crosshairLabel === undefined ? null : c.$crosshairLabel,
    axisValue: c.$crossY == null ? null : c.scales.y.getValueForPixel(c.$crossY),
    dsCount: c.data.datasets.filter((d, i) => !c.getDatasetMeta(i).hidden).length,
    dpr: window.devicePixelRatio,
    bitmapW: cv.width, cssW: cv.offsetWidth
  };
}
"""


def _snap_geom(page, canvas_id: str):
    """画布/绘图区几何（CSS 像素 + 视口偏移）。"""
    return page.evaluate(
        """(id) => {
            const cv = document.getElementById(id);
            const c = window.Chart && window.Chart.getChart(cv);
            if (!c) return null;
            const r = cv.getBoundingClientRect();
            const a = c.chartArea;
            return { rect: {left: r.left, top: r.top},
                     area: {left: a.left, top: a.top, right: a.right, bottom: a.bottom} };
        }""", canvas_id)


def _snap_probe(page, canvas_id: str, frac_x: float, frac_y: float, settle: int = 350):
    """鼠标移到绘图区 (frac_x, frac_y) → 独立预测 + 插件实测状态（坐标系：CSS 像素）。"""
    g = _snap_geom(page, canvas_id)
    if not g:
        return None
    a, r = g["area"], g["rect"]
    mx = r["left"] + a["left"] + (a["right"] - a["left"]) * frac_x
    my = r["top"] + a["top"] + (a["bottom"] - a["top"]) * frac_y
    page.mouse.move(mx, my)
    page.wait_for_timeout(settle)
    # 二次派发同源事件：首次 mousemove 可能落在图表**入场动画未结束**的时刻（元素坐标仍在变），
    # 插件按当时坐标吸附、探针随后读到的是稳定坐标 → 两者不一致。再移动一次（同坐标）让插件用
    # 稳定坐标重算（节流仅在吸附 y 未变时早退，故动画场景下必然重算）。
    page.mouse.move(mx, my)
    page.wait_for_timeout(150)
    return page.evaluate(SNAP_JS, {"id": canvas_id, "mx": mx, "my": my})


def _second_mouse_y(probe, geom):
    """推导「与 probe 吸到同一条线」的第二个鼠标 y（视口坐标）；推不出 → None。

    单数据集：任意 y 都吸同一点。多数据集：从吸附点朝**背离最近邻线**方向偏移 30% 间距
    （|0.3Δ| < |1.3Δ| ⇒ 最近数据集不变），越界则反向。
    """
    if not probe or not probe.get("ok") or probe.get("expectY") is None:
        return None
    a, r = geom["area"], geom["rect"]
    y0 = probe["expectY"]
    others = [c["y"] for c in (probe.get("col") or []) if c["dsIndex"] != probe["expectDs"]]
    if not others:
        step = 24.0
        cand = y0 + (step if (y0 - a["top"]) < (a["bottom"] - y0) else -step)
    else:
        near = min(others, key=lambda y: abs(y - y0))
        delta = y0 - near
        step = abs(delta) * 0.3
        cand = y0 + (step if delta > 0 else -step)
    lo, hi = a["top"] + 2, a["bottom"] - 2
    if not (lo <= cand <= hi):
        cand = y0 - (cand - y0)
    if not (lo <= cand <= hi):
        return None
    return r["top"] + cand


def _snap_same_line(page, canvas_id: str, geom, base) -> bool:
    """同 x、两个都靠近同一条线的鼠标 y → $crossY 是否相同（吸附"吸住"的核心判据）。"""
    y2 = _second_mouse_y(base, geom)
    if y2 is None:
        return False
    a, r = geom["area"], geom["rect"]
    mx = r["left"] + a["left"] + (a["right"] - a["left"]) * 0.5
    y1 = r["top"] + base["expectY"]
    page.mouse.move(mx, y1)
    page.wait_for_timeout(300)
    page.mouse.move(mx, y1)      # 二次派发：规避入场动画未结束时按旧坐标吸附（同 _snap_probe）
    page.wait_for_timeout(150)
    s1 = page.evaluate(SNAP_JS, {"id": canvas_id, "mx": mx, "my": y1})
    page.mouse.move(mx, y2)
    page.wait_for_timeout(300)
    page.mouse.move(mx, y2)
    page.wait_for_timeout(150)
    s2 = page.evaluate(SNAP_JS, {"id": canvas_id, "mx": mx, "my": y2})
    return bool(s1 and s2 and s1["crossY"] is not None and s2["crossY"] is not None
                and abs(s1["crossY"] - s2["crossY"]) < 0.5)


def assert_crosshair_snap(page) -> None:
    """CS-2a/2b/8/8b/9/10：横悬线吸附到数据线（crosshair-snap 任务）。

    取代旧的「CS-2 同 x 不同 Y 指纹必不同」（= 横线跟手）：吸附后该语义**反转** —— 同 x 纵移
    会吸在同一条线上。plan §3.6 已实测旧 CS-2 必红，故按 plan 拆成 CS-2a + CS-2b（补强，不删除）。
    ⚠️ 先红后绿：CS-2b / CS-8 / CS-9 / CS-10 在**改动前**必红（$crossY 恒等于鼠标 y）。
    """
    print("\n--- 悬停横线吸附（crosshair snap）---")
    cid = "chart-main"
    geom = _snap_geom(page, cid)
    check(bool(geom), "CS-8 前 #chart-main 实例可达")
    if not geom:
        return

    # CS-8 核心数值判据（多宽度：吸附精度随点间距变化，1500 是既有脚本的盲区）
    sampled, far = [], []
    for w in (1920, 1500, 1280, 375):
        page.set_viewport_size({"width": w, "height": 812 if w == 375 else 1080})
        page.wait_for_timeout(600)
        p = _snap_probe(page, cid, 0.5, 0.5)
        if not p or not p.get("ok"):
            continue
        sampled.append(w)
        dy = None if (p["crossY"] is None or p["expectY"] is None) else abs(p["crossY"] - p["expectY"])
        check(dy is not None and dy < 0.5,
              f"CS-8 {w} 档 $crossY 吸附到最近数据点（误差<0.5px）", (p["crossY"], p["expectY"]))
        if p["crossY"] is not None:
            far.append(abs(p["crossY"] - p["mouse"]["y"]))
    check(len(sampled) == 4, "CS-8 覆盖度：四档全部取样成功（防选择器一变就空跑）", sampled)
    # 注：标签只用 ASCII + 中文（Windows GBK 控制台打不出 U+2212 等符号，会 UnicodeEncodeError）
    check(bool(far) and max(far) > 20, "CS-8b 横线不再跟手（|$crossY - mouseY| 显著大于 0）",
          [round(d, 1) for d in far])

    page.set_viewport_size({"width": 1920, "height": 1080})
    page.wait_for_timeout(600)
    geom = _snap_geom(page, cid)

    # CS-9 目标选择正确：独立几何推算 vs 插件 $crossSource 挂钩（含 tie 确定性）
    p = _snap_probe(page, cid, 0.5, 0.5)
    src = (p or {}).get("source")
    if p and p.get("ok") and src:
        check(src.get("dataIdx") == p["usedIdx"] and src.get("dsIndex") == p["expectDs"],
              "CS-9 $crossSource = 最近 x 的列 + 该列 y 最近的数据集",
              (src, p["usedIdx"], p["expectDs"]))
    else:
        check(False, "CS-9 $crossSource 已写入（可测挂钩存在且非空）", src)

    # CS-2a 随 x 沿数据滑行：不同的 x → 不同的数据列
    p1 = _snap_probe(page, cid, 0.3, 0.5)
    p2 = _snap_probe(page, cid, 0.7, 0.5)
    ok2a = bool(p1 and p2 and p1.get("usedIdx") is not None
                and p2.get("usedIdx") is not None and p1["usedIdx"] != p2["usedIdx"])
    check(ok2a, "CS-2a 不同 x 吸附到不同数据列（横线随数据走）",
          ((p1 or {}).get("usedIdx"), (p2 or {}).get("usedIdx")))

    # CS-10 读数随日期变化（第二个缺陷：旧实现恒读"鼠标高度处的轴值"，与 x 无关）
    labels = []
    for fx in (0.25, 0.5, 0.75):
        pp = _snap_probe(page, cid, fx, 0.5)
        if pp and pp.get("label"):
            labels.append(pp["label"])
    check(len(set(labels)) >= 2, "CS-10 不同 x 的读数不全相同（读数随日期变）", labels)

    # CS-2b 同 x 吸住（改动前必红：跟手时两个 y 必然给出不同的 $crossY）
    base = _snap_probe(page, cid, 0.5, 0.5)
    if base and base.get("expectY") is not None:
        check(_snap_same_line(page, cid, geom, base),
              "CS-2b 同 x 不同鼠标 Y 吸在同一条线上（不再跟手）", base.get("expectY"))
    else:
        check(False, "CS-2b 能取到吸附目标 y", base and base.get("expectY"))


def assert_crosshair_dpr2(browser, url: str) -> None:
    """CS-D1~D4：DPR=2 取证（默认 DPR=1 **测不出**坐标系混用，见 plan §7 陷阱 2）。"""
    print("\n--- 吸附 · DPR=2 取证 ---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
    try:
        page = ctx.new_page()
        errs: list[str] = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(url, wait_until="load")
        page.wait_for_timeout(3500)
        p = _snap_probe(page, "chart-main", 0.5, 0.5)
        check(bool(p and p.get("ok")), "CS-D0 首页主图实例可达（DPR=2）", p and p.get("ok"))
        if not p or not p.get("ok"):
            return
        check(p["dpr"] == 2, "CS-D1 devicePixelRatio = 2", p["dpr"])
        # 容差 1px：CSS 宽可能是 1024.5 → offsetWidth 取 1024、位图取 2049（取整残差，非坐标系问题）
        check(abs(p["bitmapW"] - p["cssW"] * 2) <= 1, "CS-D2 canvas 位图宽 == 显示宽×2（C2 回归）",
              (p["bitmapW"], p["cssW"]))
        dy = None if (p["crossY"] is None or p["expectY"] is None) else abs(p["crossY"] - p["expectY"])
        check(dy is not None and dy < 0.5,
              "CS-D3 DPR=2 下吸附误差仍 <0.5 CSS px（未混用位图坐标）", (p["crossY"], p["expectY"]))
        check(not errs, "CS-D4 DPR=2 无 pageerror", errs[:3])
    finally:
        ctx.close()


def assert_macro_cn_crosshair(browser, url: str) -> None:
    """CNC-0~6：`#cn-chart` 的 crosshair 断言（plan §6 Step 4 记录的**覆盖缺口** —— 此前为零）。

    该图默认单数据集，是"读数与 x 无关"缺陷最纯净的观察点（旧实现横向移动读数恒定）。
    """
    print("\n--- CNC /macro/cn 悬停参考线 ---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        errs: list[str] = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
        page.goto(url + "macro/cn", wait_until="load")
        page.wait_for_timeout(3500)
        info = page.evaluate(
            """() => { const cv = document.getElementById('cn-chart');
                const c = window.Chart && window.Chart.getChart(cv);
                if (!c) return null;
                return { plugins: (c.config.plugins || []).map((p) => p && p.id) }; }"""
        )
        check(bool(info), "CNC-0 #cn-chart 实例可达")
        if not info:
            return
        check("hoverCrosshair" in (info["plugins"] or []),
              "CNC-1 #cn-chart 已挂 hoverCrosshair", info["plugins"])

        p = _snap_probe(page, "cn-chart", 0.5, 0.5)
        if p and p.get("ok"):   # 诊断（不参与断言）：列/索引/坐标口径一目了然
            print(f"  cn: idx0={p['idx0']} usedIdx={p['usedIdx']} expectY={p['expectY']} "
                  f"crossY={p['crossY']} src={p['source']} dsCount={p['dsCount']} mouse={p['mouse']} "
                  f"col={[(c['dsIndex'], round(c['y'], 2)) for c in p['col']]}")
        check(bool(p and p.get("ok")), "CNC-2 探针取到吸附目标", p and p.get("ok"))
        if p and p.get("ok"):
            dy = None if (p["crossY"] is None or p["expectY"] is None) else abs(p["crossY"] - p["expectY"])
            check(dy is not None and dy < 0.5,
                  "CNC-2 $crossY 吸附到最近数据点（误差<0.5px）", (p["crossY"], p["expectY"]))
            labels = []
            for fx in (0.25, 0.5, 0.75):
                pp = _snap_probe(page, "cn-chart", fx, 0.5)
                if pp and pp.get("label"):
                    labels.append(pp["label"])
            check(len(set(labels)) >= 2, "CNC-3 不同 x 读数不全相同（旧实现恒为同一值）", labels)
            geom = _snap_geom(page, "cn-chart")
            check(bool(geom) and _snap_same_line(page, "cn-chart", geom, p),
                  "CNC-4 同 x 不同 Y 吸在同一条线上", p.get("expectY"))

        page.mouse.move(5, 5)
        page.wait_for_timeout(500)
        out = page.evaluate(
            """() => { const c = window.Chart.getChart(document.getElementById('cn-chart'));
                return c.$crossY === undefined ? null : c.$crossY; }"""
        )
        check(out is None, "CNC-5 移出绘图区后 $crossY 清空", out)
        check(not errs, "CNC-6 /macro/cn 悬停交互 console error = 0", errs[:3])
    finally:
        ctx.close()


FIDELITY_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const navBad = [];
  // ⚠️ 2026-09-14 中国宏观页：跨页链接从 1 个变 2 个（`macroHref` 单值 → `macroHrefs` 数组）。
  //    原写法 `if (href === '/macro') macroHref = href` 会让新链接**静默不被任何断言覆盖**
  //    —— 比断言变红更危险（新增了导航项却没人检查它是否合规）。
  const macroHrefs = [];
  document.querySelectorAll('#sidebar .nav-item').forEach(function (el) {
    const t = el.getAttribute('data-target');
    const href = el.getAttribute('href') || '';
    if (t) { if (!document.getElementById(t)) navBad.push(el.textContent.trim() + '→' + t); }
    // 跨页链接（2026-09-14 宏观页）：href 以 / 开头 = 路由跳转，不是页内锚点 → 合规
    else if (href.charAt(0) === '/') { macroHrefs.push(href); }
    else if (!el.classList.contains('is-disabled')) navBad.push(el.textContent.trim());
  });
  const c = window.Chart && window.Chart.getChart(document.getElementById('chart-main'));
  const av = q('.avatar');
  return {
    ovIcons: document.querySelectorAll('#overview .mini-card .ico').length,
    ovCards: document.querySelectorAll('#overview .mini-card').length,
    watchIcons: document.querySelectorAll('#watchlist-body tr .ico').length,
    watchRows: document.querySelectorAll('#watchlist-body tr').length,
    usIcons: document.querySelectorAll('#us-sectors-body tr .ico').length,
    usRows: document.querySelectorAll('#us-sectors-body tr').length,
    secIcons: document.querySelectorAll('#sector-body tr .ico').length,
    secRows: document.querySelectorAll('#sector-body tr').length,
    yPos: c ? c.scales.y.position : null,
    brandText: q('.brand-mark') ? q('.brand-mark').textContent.trim() : null,
    avatarRadius: av ? getComputedStyle(av).borderRadius : null,
    navCount: document.querySelectorAll('#sidebar .nav-item').length,
    navDisabled: document.querySelectorAll('#sidebar .nav-item.is-disabled').length,
    navBad: navBad,
    macroHrefs: macroHrefs,
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
    # F-5 nav=12 项：7 个页内锚点 + 4 个**跨页链接**（/macro 全球 + /macro/cn 中国 + /timeline 市场日历
    #     + /backtest 阈值回测）+ 1 个占位（设置）。
    # ⚠️ 2026-09-19：`/timeline` 这一项**接手了 2026-09-12 起空着的同名占位项「市场日历」**
    #    （原占位来历见 tasks/2026-09-12-visual-fidelity/plan.md §12 Q1）⇒ 占位删除、位置原地保留，
    #    navCount 12 → 11、navDisabled 2 → 1。**内部命名仍是 timeline**（路由/JS/断言前缀都不变）。
    # ⚠️ 2026-09-20：新增「阈值回测」（`/backtest`）⇒ navCount 11 → **12**、跨页链接 3 → **4**。
    #    🔴 **本断言有两处硬编码**：`navCount` 的值 **和** `macroHrefs` 的数组 —— 加 nav 项时**两处都要改**
    #    （plan §2.3 只写了"navCount 三处"，实测漏改数组会让 F-5 变红而 navCount 明明是对的，
    #     极易误判成"新页面改坏了侧栏"）。
    # ⚠️ 判别（pitfalls「抽 include 后失败先分清方案不可行 vs 断言脆弱」）：include/渲染路径
    #    未变，只是产品决定多了一个合法跨页链接 → 属**断言脆弱**（navCount 写死），
    #    处置是**补强**而非删除/放松：单值 macroHref 升级为数组，逐个链接都纳入判据。
    check(f["navCount"] == 12 and f["navDisabled"] == 0 and not f["navBad"]
          and sorted(f["macroHrefs"]) == sorted(["/macro", "/macro/cn", "/timeline", "/backtest", "/settings"]),
          "F-5 nav=12（7 锚点 + 5 跨页 /macro·/macro/cn·/timeline·/backtest·/settings + 设置已转正）且 data-target/href 全命中", f)
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
  // 自动滚动任务后内容渲染两遍（克隆半）→ N-1~N-9 一律只取**第一半**，保持原有语义
  // （「接口返回的条目都被渲染」）；克隆半的数量与 aria-hidden 由 A-4 断言覆盖。
  const clone = q('#news-body .news-clone');
  const firstHalf = (sel) => [...document.querySelectorAll(sel)]
    .filter((el) => !(clone && clone.contains(el)));
  const items = firstHalf('#news-body .news-item');
  const links = firstHalf('#news-body .news-item a');
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
  // 2026-09-14：美股 tab 表格化后 .bar-row 已不存在 → 该选择器去掉（数据区应为 0 个 .pill）
  data.pillInData = document.querySelectorAll('.data-table .pill').length;

  // P-4 骨架屏：数据到达后可见骨架必须清零（5 处加载态都被真实内容替换）
  data.skVisible = [...document.querySelectorAll('.skeleton')].filter((el) => el.offsetParent !== null).length;

  // P-8 表头与数据格的水平对齐必须一致（用户反馈：成交额 th 漏 num → 表头左 / 数值右）
  // 注：th 被 .data-table th 置 left、td 默认计算值为 start → 归一化后再比。
  const norm = (v) => (v === 'start' ? 'left' : (v === 'end' ? 'right' : v));
  data.alignMismatch = [];
  // 2026-09-14：美股 tab 也改成同构表格 → 一并纳入（否则新表格的对齐问题无人看守）
  ['#us-sectors .panel-cn table.data-table', '#us-sectors .panel-us table.data-table',
   '.watchlist-table'].forEach((sel) => {
    const t = document.querySelector(sel);
    if (!t) return;
    const ths = [...t.querySelectorAll('thead th')].map((e) => norm(getComputedStyle(e).textAlign));
    [...t.querySelectorAll('tbody tr')].forEach((tr) => {
      [...tr.children].forEach((td, i) => {
        if (i >= ths.length) return;
        // 占位符 `.empty`（「数据暂缺」）是刻意居中的，不参与「表头 vs 数据」对齐比对
        if (td.classList.contains('empty')) return;
        const a = norm(getComputedStyle(td).textAlign);
        if (a !== ths[i]) data.alignMismatch.push(sel + ' 第' + (i + 1) + '列 th=' + ths[i] + ' td=' + a);
      });
    });
  });

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
          f"alignMismatch={d['alignMismatch']} scrollH={d['scrollH']}")

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
    check(not d["alignMismatch"],
          "P-8 表头与数据格水平对齐一致（防「成交额」类表头漏 num）", d["alignMismatch"])

    # P-6 骨架屏 colspan 走「静态模板源」断言：加载态转瞬即逝，运行时抓不稳定（未打补丁的
    # 旧模板 colspan 也是 5，故此条是**防回退护栏**而非「先红」项）。
    html = ""
    try:
        with urllib.request.urlopen(base_url, timeout=10) as r:
            html = r.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"  首页 HTML 读取失败: {exc}")
    # ⚠️ 2026-09-20：自选卡加了「持仓盈亏」列 ⇒ **自选表**骨架 colspan 变 6，
    #    而板块/美股等其它表仍是 5 ⇒ 必须**分表断言**：
    #      - 自选 = 6（加列的护栏）
    #      - 其余 ≥5 处仍为 5（**防误伤**：谁把 10 处 colspan 全局替换成 6，这条立刻红）
    wl_block = html.split("watchlist-table", 1)[1].split("</table>", 1)[0] if "watchlist-table" in html else ""
    wl_spans = re.findall(r'<td colspan="(\d+)"', wl_block)
    check(bool(wl_spans) and all(c == "6" for c in wl_spans),
          "P-6 自选卡骨架 colspan 全为 6（持仓盈亏列）", wl_spans)
    all_spans = re.findall(r'<tr class="sk-row"><td colspan="(\d+)"', html)
    check(all_spans.count("5") >= 5,
          "P-6c 其它表骨架仍为 5 列（未被全局替换误伤）", sorted(set(all_spans)))
    check('class="skeleton sk-card"' in html and 'class="skeleton sk-item"' in html,
          "P-6b 首屏骨架屏已就位（概览卡 + 告警条）", html.count('class="skeleton'))

    check(d["skVisible"] == 0, "P-4b 数据到达后可见骨架清零（加载态被真实内容替换）", d["skVisible"])

    # P-7 回归护栏（与 F-6a/CS-5 同口径，此处独立复测一次）
    check(d["scrollH"] <= 1240, "P-7a scrollHeight @1920 ≤1240", d["scrollH"])
    check(d["scrollW"] == d["innerW"], "P-7b 无横向溢出", (d["scrollW"], d["innerW"]))


# —— U 美股板块表格化（2026-09-14 us-sector-table 任务）——
# mock 用：结构与 fetch_us_sector_heat 的真实返回一致（name 为「行业 (代码)」，top_stock 为 ETF 代码）
US_MOCK_GAINERS = [
    {"name": "科技 (XLK)", "change": 3.21, "turnover": "$1.2B", "top_stock": "XLK"},
    {"name": "可选消费 (XLY)", "change": 2.15, "turnover": "$960.9M", "top_stock": "XLY"},
    {"name": "工业 (XLI)", "change": 1.07, "turnover": "$447.8M", "top_stock": "XLI"},
    {"name": "通信服务 (XLC)", "change": 0.99, "turnover": "$301.4M", "top_stock": "XLC"},
    {"name": "医疗健康 (XLV)", "change": -1.32, "turnover": "$260.2M", "top_stock": "XLV"},
]

US_TABLE_JS = r"""
() => {
  const norm = (v) => (v === 'start' ? 'left' : (v === 'end' ? 'right' : v));
  const usT = document.querySelector('#us-sectors .panel-us table.data-table');
  const cnT = document.querySelector('#us-sectors .panel-cn table.data-table');
  const body = document.getElementById('us-sectors-body');
  const rows = body ? [...body.querySelectorAll('tr')] : [];
  const ths = (t) => (t ? [...t.querySelectorAll('thead th')].map((e) => e.textContent.trim()) : null);
  // 只取涨跌幅列（td.chg）：成交额列同为 td.num 但 padding 是 4px，混进来会误判零增高对冲
  const chgCells = body ? [...body.querySelectorAll('tr td.chg')] : [];
  const firstTd = rows.length === 1 ? rows[0].querySelector('td') : null;
  return {
    usIsTable: !!(usT && usT.tagName === 'TABLE' && body && usT.contains(body)),
    wrapIsTableScroll: !!(usT && usT.parentElement && usT.parentElement.classList.contains('table-scroll')),
    thsUs: ths(usT), thsCn: ths(cnT),
    thAlignUs: usT ? [...usT.querySelectorAll('thead th.num')].map((e) => norm(getComputedStyle(e).textAlign)) : [],
    chgCells: chgCells.map((e) => {
      const s = getComputedStyle(e);
      return { align: norm(s.textAlign), pad: s.paddingTop + '/' + s.paddingBottom };
    }),
    rows: rows.length, cnRows: document.querySelectorAll('#sector-body tr').length,
    icons: body ? body.querySelectorAll('tr td.col-ico .ico').length : 0,
    pills: body ? body.querySelectorAll('td.chg .chg-pill').length : 0,
    emptyText: (rows.length === 1 && firstTd && firstTd.hasAttribute('colspan'))
               ? rows[0].textContent.trim() : null,
    barLeft: document.querySelectorAll('#us-sectors-body .bar-row, #us-sectors .bar-list').length,
    panelVisible: (() => { const p = document.querySelector('.panel-us');
                           return !!p && getComputedStyle(p).display !== 'none'; })(),
  };
}
"""


def assert_us_table(page, browser, url: str) -> None:
    """U-1~U-7 美股板块表格化：结构同构 + 零增高对冲 + 死代码残留 + 护栏回归。

    今天 `us_sector_heat` 为空（R2 后果：日报运行时 11 并发超时返回 ([],[])），真实数据只能验到空态。
    故另开 context 用 `page.route` 把 `/api/latest` 换成本地注入 5 条美股数据的响应 ——
    否则「有数据时」的 5 行形态与 U-7（两 tab 行数相等）这两条护栏永远没人看守。
    """
    print("\n--- U 美股板块表格化（与 A股 同构）---")
    page.evaluate("() => { document.getElementById('sector-tab-us').checked = true; }")
    page.wait_for_timeout(200)
    d = page.evaluate(US_TABLE_JS)
    print(f"  真实数据：rows={d['rows']} cnRows={d['cnRows']} ths={d['thsUs']} "
          f"thAlign={d['thAlignUs']} barLeft={d['barLeft']}")

    check(d["panelVisible"], "U-3 切到美股 tab 后 .panel-us 可见", d["panelVisible"])
    check(d["usIsTable"] and d["wrapIsTableScroll"],
          "U-2 #us-sectors-body 是 table.data-table 的 tbody（外层 .table-scroll）",
          (d["usIsTable"], d["wrapIsTableScroll"]))
    check(bool(d["thsUs"]) and d["thsUs"] == d["thsCn"] and len(d["thsUs"]) == 5,
          "U-2b 两 tab 表头逐列相同（5 列）", (d["thsUs"], d["thsCn"]))
    check(d["rows"] >= 1, "U-3b 美股 tab 表格内有行（空态也占一行）", d["rows"])
    check(d["barLeft"] == 0, "U-5 无 .bar-row / .bar-list 残留", d["barLeft"])
    check(bool(d["thAlignUs"]) and all(a == "right" for a in d["thAlignUs"]),
          "U-4 美股表格表头数字列右对齐", d["thAlignUs"])
    if d["rows"] == 1:
        check(d["emptyText"] == "数据暂缺", "U-3c 空态 = 表格内一行「数据暂缺」", d["emptyText"])
        # 注意：不要在本文件 print 里用 emoji —— Windows 控制台是 GBK，非 GBK 字符会
        # UnicodeEncodeError 让验收脚本中途崩掉（本次踩过）。
        print("  真实数据为空（今日美股板块取数超时）->「有数据时」的 5 行形态改用 mock 验证")
        # 目视证据：真实空态（表格内一行「数据暂缺」，而非旧版居中的 .empty 占位）
        try:
            page.locator("#us-sectors").screenshot(path=str(OUT_DIR / "shot-us-tab-empty.png"))
        except Exception as exc:  # noqa: BLE001
            print(f"  截图失败（不影响断言）: {exc}")

    page.evaluate("() => { document.getElementById('sector-tab-cn').checked = true; }")
    page.wait_for_timeout(150)

    try:
        with urllib.request.urlopen(url + "api/latest", timeout=15) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        check(False, "U-1 读取 /api/latest 以构造 mock（验证「有数据时」形态的前提）", exc)
        return
    payload["us_sector_heat"] = {"gainers": US_MOCK_GAINERS, "losers": US_MOCK_GAINERS}
    body_json = json.dumps(payload, ensure_ascii=False)

    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        p2 = ctx.new_page()
        p2.route("**/api/latest", lambda route: route.fulfill(
            status=200, content_type="application/json", body=body_json))
        p2.goto(url, wait_until="load")
        try:
            p2.wait_for_selector("#us-sectors-body .chg-pill", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        p2.evaluate("() => { document.getElementById('sector-tab-us').checked = true; }")
        p2.wait_for_timeout(200)
        m = p2.evaluate(US_TABLE_JS)
        scroll_h = p2.evaluate("() => document.scrollingElement.scrollHeight")
        scroll_w = p2.evaluate("() => document.scrollingElement.scrollWidth")
        inner_w = p2.evaluate("() => window.innerWidth")
        # 目视证据：美股 tab（mock 有数据）+ A股 tab 各截一张卡片图，便于人工比对是否逐列同构
        try:
            p2.locator("#us-sectors").screenshot(path=str(OUT_DIR / "shot-us-tab-us.png"))
            p2.evaluate("() => { document.getElementById('sector-tab-cn').checked = true; }")
            p2.wait_for_timeout(200)
            p2.locator("#us-sectors").screenshot(path=str(OUT_DIR / "shot-us-tab-cn.png"))
        except Exception as exc:  # noqa: BLE001
            print(f"  截图失败（不影响断言）: {exc}")
        print(f"  mock 5 条：rows={m['rows']} cnRows={m['cnRows']} icons={m['icons']} "
              f"pills={m['pills']} chgCells={m['chgCells'][:2]} scrollH={scroll_h}/{inner_w}")

        check(m["rows"] == 5, "U-1 有数据时美股表格 5 行（slice(0,5)）", m["rows"])
        check(m["rows"] == m["cnRows"],
              "U-7 两 tab 行数相等（行高护栏：改回 8 行会撑高 .row-3）", (m["rows"], m["cnRows"]))
        check(m["icons"] == m["rows"] and m["pills"] == 5,
              "U-7b 每行 1 个图标 + 5 行涨跌幅均走 .chg-pill", (m["icons"], m["pills"]))
        check(bool(m["chgCells"]) and all(c["align"] == "right" for c in m["chgCells"]),
              "U-4b 涨跌幅列右对齐", m["chgCells"][:3])
        check(bool(m["chgCells"]) and all(c["pad"] == "3px/3px" for c in m["chgCells"]),
              "U-4c td.chg padding 3px（P-3 零增高对冲，漏 chg 会变 4px→每行 +2px）", m["chgCells"][:3])
        check(scroll_h <= 1240, "U-6 mock 5 行后 scrollHeight @1920 ≤1240", scroll_h)
        check(scroll_w == inner_w, "U-6b mock 5 行后无横向溢出", (scroll_w, inner_w))
    finally:
        ctx.close()


# —— V 板块陈旧回填标注（2026-09-14 sector-stale-fallback 任务）——
# 开关 tab 必须**手动 dispatch change**：程序化改 .checked 不会触发 change 事件，而标注正是
# 靠 radio 的 change 监听更新的（纯 CSS tab 没有切换事件）→ 这样顺带验证了监听确实挂上了。
ASOF_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const h2 = q('#us-sectors .card-head h2');
  const el = document.getElementById('us-sectors-asof');
  const card = q('#us-sectors');
  const cn = document.getElementById('sector-tab-cn');
  const us = document.getElementById('sector-tab-us');
  const setTab = (r) => { r.checked = true; r.dispatchEvent(new Event('change')); };
  const out = {};

  setTab(cn);
  out.cnText = el ? el.textContent : null;
  out.cnH2 = h2 ? h2.offsetHeight : null;
  out.cnCard = card ? card.offsetHeight : null;

  setTab(us);
  out.usText = el ? el.textContent : null;
  out.usH2 = h2 ? h2.offsetHeight : null;
  out.usCard = card ? card.offsetHeight : null;

  // 零增高判据：把标注文本清空后高度是否变化（在美股 tab 下测，标注此时非空）
  const keep = el.textContent;
  el.textContent = '';
  out.usH2NoLabel = h2.offsetHeight;
  out.usCardNoLabel = card.offsetHeight;
  el.textContent = keep;

  // 375 换行判据：h2 实际高 vs 单行 line-height
  const cs = getComputedStyle(h2);
  // line-height 可能是 'normal'（parseFloat → NaN）→ 用 fontSize × 1.6 兜底，保证判据恒有数值
  out.lineHeight = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) * 1.6);
  out.h2ClientH = h2.clientHeight;
  out.labelInH2 = !!(el && el.closest('h2') === h2);

  setTab(cn);                       // 复位到默认 tab，别影响后续断言
  out.resetToCn = el.textContent;
  return out;
}
"""


_LATEST_CACHE: dict = {}


def api_latest(url: str) -> dict:
    """读 /api/latest（按 url 缓存）。

    用途：让"期望值"**取自数据**而不是写死在断言里（2026-09-14：顶栏数据日与 V-2/V-4 都曾写死/隐含
    "今天数据一定新鲜"，换一天就必然变红 —— 与 K-5「只断不变量、不断死数值」相冲突）。
    """
    if url not in _LATEST_CACHE:
        with urllib.request.urlopen(url + "api/latest", timeout=10) as r:
            _LATEST_CACHE[url] = json.loads(r.read().decode("utf-8"))
    return _LATEST_CACHE[url]


def assert_sector_asof(page, url: str) -> None:
    """V-1~V-6 板块数据日标注：tab-aware 文案（**总是**标注该 tab 的 as_of）+ 零增高 + 标注在 h2 内。

    ⚠️ 2026-09-19：语义由「仅陈旧时标注」改为「总是标注」——见 V-2/V-3 处的说明。
    """
    print("\n--- V 板块「数据截至」标注（陈旧回填）---")
    try:
        payload = api_latest(url)
    except Exception as exc:  # noqa: BLE001
        check(False, "V-1 读取 /api/latest（标注断言的期望值来源）", exc)
        return
    cn_as_of = payload["sector_heat"].get("as_of")
    us_as_of = payload["us_sector_heat"].get("as_of")
    cur = payload.get("date")
    d = page.evaluate(ASOF_JS)
    print(f"  api: date={cur} cn.as_of={cn_as_of} us.as_of={us_as_of}")
    print(f"  cnText={d['cnText']!r} usText={d['usText']!r} "
          f"h2={d['cnH2']}/{d['usH2']} card={d['cnCard']}/{d['usCard']} "
          f"noLabelH2={d['usH2NoLabel']} h2ClientH={d['h2ClientH']} lineHeight={d['lineHeight']}")

    check(d["labelInH2"], "V-1 标注 span 在 h2 内（零增高的前提）", d["labelInH2"])
    # ⚠️ 2026-09-14（macro-page-refine）：这里原为"假设 A股 今天数据一定新鲜（as_of == date）→ 标注必须为空"。
    #    但 as_of / date 都由**快照数据**决定（周末、节假日、盘中都会让两者不等），该前提在周末档不成立
    #    （实测 09-14 周一：date=2026-09-14 而 cn.as_of=2026-09-13 → 页面**正确地**标注了"截至 09-13"）。
    #    改为与 V-3 同款的**数据驱动期望值**：只断言"标注内容 == 陈旧与否对应的文案"，
    #    不变量（标注跟着数据走）保持不变，去掉环境耦合（原来换一天必红）。
    # ⚠️ 2026-09-19（用户反馈"A股/美股两个 tab 结构不一致"）：实现由「**仅陈旧时**标注」改为
    #    「**总是**标注该 tab 的数据日」→ 期望值随之去掉 `!= cur` 条件。
    #    **判据是变严不是放松**：原期望在"数据新鲜"时退化成空串（弱），现在恒为具体日期，
    #    只有在 `as_of` 真正缺失时才为空 —— 比原判据更难通过。
    exp_cn = ("· 数据截至 " + cn_as_of) if cn_as_of else ""
    check(d["cnText"] == exp_cn,
          "V-2 A股 tab 标注 == 该 tab 的 as_of（期望值取自 API）", (d["cnText"], exp_cn))
    # 美股 tab：标注必须**跟着数据走**（陈旧才显示）—— 期望值直接取自 API，避免写死日期。
    # ⚠️ 2026-09-17 修：原为 `d["usText"] == expected and (us_as_of is None or d["usText"] != "")`，
    #    第二个合取项与第一个**逻辑冲突**：当 `as_of == date`（数据新鲜）时 `expected` 恒为 `""`，
    #    而它却要求「as_of 非 None ⇒ 文案必须非空」⇒ **数据一新鲜就必红**。
    #    实测（2026-09-17）`date=cn.as_of=us.as_of=2026-09-16`：页面**正确地**两条标注都为空，
    #    与 V-2 输入完全相同、输出完全相同，却一个绿一个红 ⇒ 差异只在断言。
    #    改为与 V-2 同款的**数据驱动期望值**（判据是"与数据推导出的文案逐字相等"，不比"非空"弱）。
    #    原第二合取项想防的是"期望值退化成空 ⇒ 真空通过"，改用**输入前置**（V-3a）表达更准确。
    # ⚠️ 2026-09-19：同 V-2，期望值去掉 `!= cur`。
    #    V-3a 保留 —— 它现在的意义是「页面数据日本身要有值」（顶栏数据日等以它为基准），
    #    不再兼作 V-3 的真空保护（V-3 现已恒有具体期望值，不会因期望为空而真空通过）。
    check(bool(cur), "V-3a /api/latest 提供 date（页面数据日基准）", cur)
    expected = ("· 数据截至 " + us_as_of) if us_as_of else ""
    check(d["usText"] == expected,
          "V-3 美股 tab 标注 == 该 tab 的 as_of（期望值取自 API）",
          (d["usText"], expected, us_as_of, cur))
    check(d["resetToCn"] == exp_cn,
          "V-4 切回 A股 tab 后标注与 A股 状态一致（radio change 监听生效）", (d["resetToCn"], exp_cn))
    check(d["usH2"] == d["cnH2"] and d["usCard"] == d["cnCard"]
          and d["usH2"] == d["usH2NoLabel"] and d["usCard"] == d["usCardNoLabel"],
          "V-5 标注零增高（h2 与 #us-sectors 高度都不变）",
          (d["cnH2"], d["usH2"], d["usH2NoLabel"]))


def assert_asof_narrow(page) -> None:
    """375 档专项：长文案是否让 h2 换行（换行会 +~20px → 威胁护栏）。"""
    print("\n--- V-7 375 档 h2 换行实测 ---")
    d = page.evaluate(ASOF_JS)
    print(f"  usText={d['usText']!r} h2ClientH={d['h2ClientH']} lineHeight={d['lineHeight']} "
          f"h2={d['cnH2']}/{d['usH2']}")
    check(d["h2ClientH"] is not None and d["lineHeight"] is not None
          and d["h2ClientH"] <= d["lineHeight"] * 1.6,
          "V-7 375 档 h2 未换行（单行：clientHeight ≈ line-height）",
          (d["h2ClientH"], d["lineHeight"]))
    check(d["cnH2"] == d["usH2"], "V-7b 375 档标注零增高", (d["cnH2"], d["usH2"]))


# —— MX 宏观数据独立页（2026-09-14 macro-page 任务）——
MACRO_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const txt = (s) => { const e = q(s); return e ? e.textContent.trim() : null; };
  const canvas = q('#macro-chart');
  const chart = (window.Chart && canvas) ? window.Chart.getChart(canvas) : null;
  const ds = chart ? chart.data.datasets : [];
  const firstVal = (d) => { const a = (d && d.data) || [];
    for (const v of a) { if (v != null) return v; } return null; };
  const varRow = (needle) => {
    const rows = [...document.querySelectorAll('#macro-vars .mac-var')];
    const hit = rows.find((e) => (e.querySelector('.v-label') || {}).textContent
                                 && e.querySelector('.v-label').textContent.indexOf(needle) >= 0);
    return hit ? hit.querySelector('.v-value').textContent.trim() : null;
  };
  const relRows = [...document.querySelectorAll('#macro-rel .mac-rel-row')];
  return {
    moduleIds: ['mac-regime', 'mac-market', 'mac-vars', 'mac-factors',
                'mac-relation', 'mac-history', 'mac-econ'].filter((id) => !!document.getElementById(id)).length,
    canvasBitmapW: canvas ? canvas.width : null, canvasCssW: canvas ? canvas.offsetWidth : null,
    canvasBitmapH: canvas ? canvas.height : null, canvasCssH: canvas ? canvas.offsetHeight : null,
    chartWrapH: q('#macro-chart-wrap') ? Math.round(q('#macro-chart-wrap').getBoundingClientRect().height) : null,
    pills: [...document.querySelectorAll('#macro-pills .mac-pill')].map((e) => e.textContent.trim()),
    ranges: [...document.querySelectorAll('#macro-range .mac-pill')].map((e) => e.textContent.trim()),
    activePill: txt('#macro-pills .mac-pill.active'),
    activeRange: txt('#macro-range .mac-pill.active'),
    dsCount: ds.length, dsFirst: ds.map(firstVal), pointCount: ds.length ? ds[0].data.length : 0,
    level: txt('#regime-level'), quadrant: txt('#regime-quadrant'), score: txt('#regime-score'),
    factorCount: document.querySelectorAll('#regime-factors li').length,
    tenYear: varRow('10Y'), varCount: document.querySelectorAll('#macro-vars .mac-var').length,
    relRows: relRows.length,
    // 2026-09-14（macro-page-refine）：默认只列最强的 2~3 条 + 「查看全部」折叠其余（PRD 要点 6）
    relMoreShown: !!(q('#macro-rel-more') && !q('#macro-rel-more').hidden),
    relSignificant: document.querySelectorAll('#macro-rel .mac-rel-row.strong').length,
    relInsufficient: [...document.querySelectorAll('#macro-rel .rel-r')]
      .filter((e) => e.textContent.trim() === '样本不足').length,
    // 每对必须给出「可读结果」：数值 或 「样本不足」；不允许 —/空/其它
    relBadR: [...document.querySelectorAll('#macro-rel .rel-r')]
      .map((e) => e.textContent.trim())
      .filter((t) => t !== '样本不足' && !/^[+-]?\d+(\.\d+)?$/.test(t)).length,
    histRows: document.querySelectorAll('#macro-history .mac-hist-row').length,
    econAsOf: txt('#econ-asof'), econItems: document.querySelectorAll('#macro-econ .mac-econ-item').length,
    econSectionText: q('#mac-econ') ? q('#mac-econ').textContent : '',
    econEmpty: !!q('#macro-econ .mac-empty'),
    scrollW: document.scrollingElement.scrollWidth, innerW: window.innerWidth,
    twoColCols: q('.mac-2col') ? getComputedStyle(q('.mac-2col')).gridTemplateColumns.trim().split(/\s+/).length : null,
    theme: document.documentElement.getAttribute('data-theme'),
  };
}
"""


def assert_macro_page(browser, url: str) -> None:
    """MX-1~MX-15 宏观页（/macro）：7 模块 + 主图（C2）+ 口径（10Y / 归一化 / 数据月份）+ 降级 + 双主题 + 375。

    独立 context（不污染首页主页面状态）。`/api/econ` 降级另开 context 用 `page.route` 断掉。
    """
    print("\n--- MX 宏观数据独立页（/macro）---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        resp = page.goto(url + "macro", wait_until="load")
        check(resp is not None and resp.status == 200, "MX-1 /macro 返回 200",
              resp.status if resp else None)
        page.wait_for_timeout(3500)          # /api/macro 冷启动 ~2.2s + /api/econ
        d = page.evaluate(MACRO_JS)
        # /api/econ 依赖**外部 BLS**：瞬时失败时页面会显示「数据暂缺」（端点按设计不缓存失败结果）。
        # ⚠️ 这里**只重试一次**（重载会再次触发取数）—— 判据不放松（仍要求显示「YYYY年M月」），
        #    只是不把外部 API 的一次网络抖动判成页面缺陷（实测 2026-09-14 遇到过 1 次）。
        if not (d["econAsOf"] and "年" in d["econAsOf"]):
            print("  [retry] /api/econ 首次返回空（外部 BLS 瞬时失败）→ 重载一次再测")
            page.reload(wait_until="load")
            page.wait_for_timeout(3500)
            d = page.evaluate(MACRO_JS)
        print(f"  level={d['level']!r} quadrant={d['quadrant']!r} score={d['score']!r} "
              f"factors={d['factorCount']}")
        print(f"  canvas={d['canvasBitmapW']}x{d['canvasBitmapH']} css={d['canvasCssW']}x{d['canvasCssH']} "
              f"wrapH={d['chartWrapH']}")
        print(f"  pills={d['pills']} active={d['activePill']!r} ranges={d['ranges']} "
              f"pts={d['pointCount']} ds={d['dsCount']} dsFirst={[round(v, 2) if v is not None else None for v in d['dsFirst']]}")
        print(f"  tenYear={d['tenYear']!r} rel={d['relRows']}(strong={d['relSignificant']},"
              f"n/a={d['relInsufficient']}) hist={d['histRows']} econAsOf={d['econAsOf']!r}")

        check(d["moduleIds"] == 7, "MX-2 七个模块骨架齐全", d["moduleIds"])
        # C2：canvas 位图 == 显示尺寸；容器必须显式高度（否则 Chart.js 塌成 0）
        check(d["canvasBitmapW"] == d["canvasCssW"] and d["canvasBitmapH"] == d["canvasCssH"],
              "MX-3 canvas 位图 == 显示尺寸（C2）",
              (d["canvasBitmapW"], d["canvasBitmapH"], d["canvasCssW"], d["canvasCssH"]))
        check(d["chartWrapH"] is not None and d["chartWrapH"] >= 300,
              "MX-3b 主图容器有确定高度 ≥300px（R1/C2）", d["chartWrapH"])
        check(len(d["pills"]) == 5 and len(d["ranges"]) == 5,
              "MX-4 胶囊 5 品种 + 时间范围 5 档", (d["pills"], d["ranges"]))
        check(d["activePill"] == "美元指数" and d["activeRange"] == "1Y",
              "MX-4b 默认选中 美元指数 / 1Y", (d["activePill"], d["activeRange"]))
        # ⚠️ 10Y 口径：Yahoo 返回的就是百分数（实测 4.985 = 4.985%），**不能 ÷10**。
        # 取到的文本可能带单位（如 "4.985%"）→ 剥离非数字字符后再比。
        ten_raw = d["tenYear"] or ""
        ten_val = None
        try:
            ten_val = float(re.sub(r"[^\d.\-]", "", ten_raw) or "")
        except ValueError:
            ten_val = None
        check(ten_val is not None and 0 < ten_val < 20,
              "MX-6 10Y 显示为 ≈4.xx%（不是 42.5%，也不是 ÷10 后的 0.4985%）", ten_raw,
              deps=("macro",))
        check(d["varCount"] == 4, "MX-6b 核心宏观变量 4 张", d["varCount"], deps=("macro",))
        # ⚠️ 2026-09-14（macro-page-refine 任务）**契约变更**：宏观关系默认只列「最重要的 2~3 条」，
        #    其余折叠进「查看全部」（PRD 要点 6）→ 不再要求一次列出 6 对，改为「默认 ≤3 + 展开后 6 对齐全」。
        #    原断言 `relRows == 6` 会随之失效（那不是回归，是刻意的信息层级调整）。
        check(2 <= d["relRows"] <= 3 and d["relMoreShown"],
              "MX-9 宏观关系默认只列 2~3 条 + 「查看全部」可展开", (d["relRows"], d["relMoreShown"]),
              deps=("macro",))
        page.evaluate("() => { const b = document.getElementById('macro-rel-more'); if (b) b.click(); }")
        page.wait_for_timeout(250)
        d_all = page.evaluate(MACRO_JS)
        check(d_all["relRows"] == 6, "MX-9b 展开后 6 对齐全", d_all["relRows"], deps=("macro",))
        # MX-9c **不加 deps**：它的判据本身就把「样本不足」当合法结果 ⇒ 上游挂了它照样该过
        # （与 MX-11c 同一类，plan §2.4① 的反例）。
        check(d_all["relBadR"] == 0,
              "MX-9c 每对都给出可读结果（数值或「样本不足」），不把 None 显示成 0.00",
              (d_all["relBadR"], d_all["relInsufficient"], d_all["relSignificant"]))
        check(d["histRows"] == 3, "MX-10 历史宏观环境 3 行三态分布", d["histRows"], deps=("macro",))
        # 经济数据：**必须显示数据月份**，不得出现「最新/实时」
        check(d["econAsOf"] and "年" in d["econAsOf"] and "月" in d["econAsOf"],
              "MX-11 经济数据标注「YYYY年M月」（数据月份）", d["econAsOf"], deps=("econ",))
        check(d["econItems"] == 4, "MX-11b 经济数据 4 项", d["econItems"], deps=("econ",))
        # MX-11c **不加 deps**：空态也必须满足（plan §2.4① 明确点名的反例）
        check("最新" not in d["econSectionText"] and "实时" not in d["econSectionText"],
              "MX-11c 经济数据区不含「最新/实时」字样")
        # MX-15 **不加 deps**：console error 是我们的 bug，与上游无关
        check(not errors, "MX-15 /macro console error = 0", errors[:3])

        page.screenshot(path=str(OUT_DIR / "shot-macro-1920.png"), full_page=True)

        # 多变量：起点归一化 100（量纲不同，不可共用价格轴）
        page.evaluate("() => document.querySelector('#macro-pills .mac-pill[data-pick=\"__all__\"]').click()")
        page.wait_for_timeout(900)
        dm = page.evaluate(MACRO_JS)
        check(dm["dsCount"] == 4 and all(v is not None and abs(v - 100) < 0.01 for v in dm["dsFirst"]),
              "MX-7 多变量对比：4 条线且起点归一化为 100", [round(v, 3) for v in dm["dsFirst"]],
              deps=("macro",))
        page.evaluate("() => document.querySelector('#macro-range .mac-pill[data-range=\"5y\"]').click()")
        page.wait_for_timeout(1200)
        d5 = page.evaluate(MACRO_JS)
        check(d5["pointCount"] > 1000, "MX-8 5Y 档点数 > 1000", d5["pointCount"], deps=("macro",))
        # MX-8b **不加 deps**：胶囊高亮是纯 UI 状态，与上游无关
        check(d5["activeRange"] == "5Y", "MX-8b 5Y 档胶囊高亮", d5["activeRange"])

        # 双主题：切换后 data-theme 变化且图表实例存活
        before = d5["theme"]
        page.evaluate("() => document.getElementById('sidebar-theme').click()")
        page.wait_for_timeout(700)
        dt = page.evaluate(MACRO_JS)
        check(dt["theme"] != before and dt["dsCount"] > 0,
              "MX-13 宏观页主题切换生效且图表存活（R10）", (before, dt["theme"], dt["dsCount"]),
              deps=("macro",))
        page.screenshot(path=str(OUT_DIR / "shot-macro-dark.png"), full_page=True)

        # 375：自然降为单列 + 无横向溢出
        page.set_viewport_size({"width": 375, "height": 812})
        page.wait_for_timeout(900)
        d375 = page.evaluate(MACRO_JS)
        check(d375["scrollW"] == d375["innerW"], "MX-14a 375 档无横向溢出",
              (d375["scrollW"], d375["innerW"]))
        check(d375["twoColCols"] == 1, "MX-14b 375 档两列区降为单列", d375["twoColCols"])
        page.screenshot(path=str(OUT_DIR / "shot-macro-375.png"), full_page=True)
    finally:
        ctx.close()

    # 降级：/api/econ 不可用 → 模块 7「数据暂缺」+ 四象限占位，页面不崩
    ctx2 = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    try:
        p2 = ctx2.new_page()
        p2.route("**/api/econ", lambda route: route.abort())
        r2 = p2.goto(url + "macro", wait_until="load")
        p2.wait_for_timeout(3500)
        de = p2.evaluate(MACRO_JS)
        print(f"  [econ 断供] econEmpty={de['econEmpty']} quadrant={de['quadrant']!r} "
              f"level={de['level']!r}")
        check(r2 is not None and r2.status == 200 and de["moduleIds"] == 7,
              "MX-12 /api/econ 不可用时页面仍 200 且 7 模块在位", r2.status if r2 else None)
        check(de["econEmpty"] is True and "数据暂缺" in (de["quadrant"] or ""),
              "MX-12b /api/econ 不可用 → 模块 6/7 显示「数据暂缺」（不崩）",
              (de["econEmpty"], de["quadrant"]))
    finally:
        ctx2.close()


# —— MR 宏观页 refinement（2026-09-14 macro-page-refine 任务）——
# 断言口径：**只断不变量**（"标注阈值与列出的行一致""线条有主次""轴不超数据范围""留白 ≤20px"），
# 不断死数值（不断"恰好 2.4px"/"恰好 18px"）—— 否则调参就退化成"改断言让它变绿"（plan R2）。
MACRO_REFINE_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const txt = (s) => { const e = q(s); return e ? e.textContent.trim() : null; };
  const canvas = q('#macro-chart');
  const chart = (window.Chart && canvas) ? window.Chart.getChart(canvas) : null;
  const ds = chart ? chart.data.datasets : [];
  const relBox = q('#macro-rel');
  const note = txt('#macro-rel-note') || '';
  const m = note.match(/\|r\|\s*≥\s*([\d.]+)/);      // 标注里声明的阈值（若声明了）
  const rows = [...document.querySelectorAll('#macro-rel .mac-rel-row')];
  const rAt = (li) => { const e = li.querySelector('.rel-r'); if (!e) return null;
    const t = e.textContent.trim();
    return /^[+-]?\d+(\.\d+)?$/.test(t) ? Math.abs(parseFloat(t)) : null; };
  const vals = [];
  ds.forEach((d) => (d.data || []).forEach((v) => { if (v != null) vals.push(v); }));
  const y = (chart && chart.scales && chart.scales.y) ? chart.scales.y : null;
  // 模块"额外留白" = 元素高 − 标题 − 内容 − 上下 padding（与 plan §2.4 同一算法）
  const slack = (sel) => {
    const box = q(sel); if (!box) return null;
    const cs = getComputedStyle(box);
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const head = box.querySelector('.mac-card-head');
    const headH = head ? head.getBoundingClientRect().height : 0;
    let inner = 0;
    [...box.children].forEach((c) => { if (c !== head) inner += c.getBoundingClientRect().height; });
    return Math.round(box.getBoundingClientRect().height - headH - inner - pad);
  };
  const regime = q('#mac-regime');
  const wrap = q('#macro-chart-wrap');
  const more = q('#macro-rel-more');
  return {
    theme: document.documentElement.getAttribute('data-theme'),
    bodyBg: getComputedStyle(document.body).backgroundColor,
    relNote: note, relThreshold: m ? parseFloat(m[1]) : null,
    relMode: relBox ? relBox.getAttribute('data-rel-mode') : null,
    relRows: rows.length, relR: rows.map(rAt), relSig: rows.map((li) => li.getAttribute('data-sig')),
    relMoreShown: !!(more && !more.hidden),
    dsCount: ds.length, dsLabels: ds.map((d) => d.label), dsBorder: ds.map((d) => d.borderWidth),
    yMin: y ? y.min : null, yMax: y ? y.max : null,
    dataMin: vals.length ? Math.min(...vals) : null, dataMax: vals.length ? Math.max(...vals) : null,
    factorsSlack: slack('#mac-factors'), varsSlack: slack('#mac-vars'),
    regimeIsCard: regime ? regime.classList.contains('mac-card') : null,
    regimeBorderTop: regime ? getComputedStyle(regime).borderTopWidth : null,
    // 分层证据：一级块无边框/无底色，二级"重卡"有边框有底色（dark 下肉眼可辨）
    heroBg: q('#mac-market') ? getComputedStyle(q('#mac-market')).backgroundColor : null,
    heroBorder: q('#mac-market') ? getComputedStyle(q('#mac-market')).borderTopWidth : null,
    quietBg: q('#mac-econ') ? getComputedStyle(q('#mac-econ')).backgroundColor : null,
    // 一级块三段式（左中右）的列宽 —— 用来量化"左中右之间的大片空白"（plan 要点 2）
    regimeColW: q('.mac-regime')
      ? [...q('.mac-regime').children].map((c) => Math.round(c.getBoundingClientRect().width)) : null,
    regimeW: q('.mac-regime') ? Math.round(q('.mac-regime').getBoundingClientRect().width) : null,
    twoColCols: q('.mac-2col') ? getComputedStyle(q('.mac-2col')).gridTemplateColumns.trim().split(/\s+/).length : null,
    chartWrapH: wrap ? Math.round(wrap.getBoundingClientRect().height) : null,
    docH: Math.round(document.scrollingElement.scrollHeight),
    scrollW: document.scrollingElement.scrollWidth, innerW: window.innerWidth,
  };
}
"""


CN_MACRO_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const wrap = q('#cn-chart-wrap');
  const cv = q('#cn-chart');
  const reg = q('#cn-regime');
  const econ = q('#cn-econ');
  const estate = q('#cn-estate');
  const c = window.Chart && window.Chart.getChart(cv);
  const cnLink = q('#sidebar a[href="/macro/cn"]');
  return {
    moduleIds: ['cn-regime', 'cn-market', 'cn-vars', 'cn-factors',
                'cn-rate-list', 'cn-estate', 'cn-econ']
      .filter((i) => document.getElementById(i)).length,
    chartWrapH: wrap ? Math.round(wrap.getBoundingClientRect().height) : null,
    canvasBitmapW: cv ? cv.width : null, canvasBitmapH: cv ? cv.height : null,
    canvasCssW: cv ? cv.offsetWidth : null, canvasCssH: cv ? cv.offsetHeight : null,
    quadrant: reg ? reg.getAttribute('data-quadrant') : null,
    basisText: (q('#cn-basis') || {}).textContent || '',
    estateText: estate ? estate.textContent : '',
    estateCities: estate ? estate.querySelectorAll('.cn-city').length : 0,
    econAsOf: (q('#cn-econ-asof') || {}).textContent || '',
    econText: econ ? econ.textContent : '',
    econItems: econ ? econ.querySelectorAll('.mac-econ-item').length : 0,
    navCount: document.querySelectorAll('#sidebar .nav-item').length,
    cnActive: !!(cnLink && cnLink.classList.contains('active')),
    // 2026-09-15 用户反馈：「+21.20% 配 ↓ 箭头」看着像 bug —— 数值符号（同比本身）与箭头
    // （同比较上期）是两个口径，必须靠 title 消歧；同时不得出现「—%」（空同比拼了百分号）。
    chgTitles: [...document.querySelectorAll('#cn-vars .v-chg, #cn-rate-list .v-chg, #cn-econ .e-yoy')]
      .map((e) => e.getAttribute('title') || ''),
    // 利率类改造（2026-09-15）：Δ = 与 6 个月前相比（bp），10Y 不再恒「—」；单位写在格子里
    rateChgTexts: [...document.querySelectorAll('#cn-rate-list .v-chg')].map((e) => e.textContent.trim()),
    rateNote: (q('#cn-rate-col .mac-note') || {}).textContent || '',
    varsText: (q('#cn-vars') ? q('#cn-vars').textContent : '') +
              (q('#cn-rate-list') ? q('#cn-rate-list').textContent : ''),
    macroActive: (() => { const a = q('#sidebar a[href="/macro"]');
                          return !!(a && a.classList.contains('active')); })(),
    theme: document.documentElement.getAttribute('data-theme'),
    pills: [...document.querySelectorAll('#cn-pills .mac-pill')].map((b) => b.textContent.trim()),
    pointCount: c ? Math.max(...c.data.datasets.map((d) => d.data.length)) : 0,
    scrollW: document.scrollingElement.scrollWidth, innerW: window.innerWidth,
  };
}
"""


def _expect_chart_wrap_h(vw: int, vh: int) -> float:
    """`#cn-chart-wrap` 的期望高度（**从 CSS 定义推导，不写死数值**）。

    复用 `.mac-chart-wrap`：`height: clamp(340px, 46vh, 560px)`；
    `@media (max-width: 768px)` 覆盖为 `clamp(360px, 48vh, 420px)`。
    """
    lo, ratio, hi = (360, 0.48, 420) if vw <= 768 else (340, 0.46, 560)
    return min(max(lo, ratio * vh), hi)


def assert_macro_cn_page(browser, url: str) -> None:
    """CN-1~CN-10 中国宏观页（/macro/cn）：模块 + C2 + 两个纠正项（C1 房价 2 城 / C2 PMI 水平）
    + 数据月份口径 + 侧栏联动 + 主题同源 + 三档视口高度。

    独立 context（不污染首页主页面状态），主题用 add_init_script 固定为 dark
    —— 与首页同偏好进入本页，若本页 head 内联脚本缺少 dark 分支会**静默变白**。
    """
    print("\n--- CN 中国宏观独立页（/macro/cn）---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.add_init_script("try { localStorage.setItem('mp-theme', 'dark'); } catch (e) {}")
        # CN-12 探针（2026-09-15 用户反馈「吸附有了但虚线没跟上」）：
        #   图表实例被**重建**会清空插件的 $crossY/$crossSource → 虚线消失/不跟随。
        #   这里给实例打标记并轮询计数，把"加载期重建次数"变成可断言量（原实现实测 8 次）。
        page.add_init_script(
            "window.__cnRecreate = 0; window.__cnSeen = null;"
            "setInterval(() => { const cv = document.getElementById('cn-chart');"
            "  const c = window.Chart && window.Chart.getChart(cv); if (!c) return;"
            "  if (!c.__tag) c.__tag = 'chart#' + (++window.__cnRecreate);"
            "  window.__cnSeen = c.__tag; }, 120);"
        )
        resp = page.goto(url + "macro/cn", wait_until="load")
        check(resp is not None and resp.status == 200, "CN-1 /macro/cn 返回 200",
              resp.status if resp else None)
        # R1 分组端点分两波加载（全量 ≈10~14s）→ 等到「经济数据」与「地产」都真的渲染出来
        def _wait_cn_ready() -> None:
            """等到**所有分组**都渲染出来 —— 判据必须把 rate 组的行算进去。

            ⚠️ 2026-09-15 实测踩坑：原判据只有 `#cn-econ ≥ 10 项 && #cn-estate ≥ 1 城`，
               而 price(2)+growth(2)+money(3)+labor(2)+estate(2) = **11 项** →
               **rate 组还在飞也能满足** → `#cn-rate-list` 只剩「社融」一行，
               利率三行缺失 → CN-4f 报红。端点侧实测 `failed=[]`、`bp=[0,11.44,-8.96]`，
               纯前端等待竞态（不是数据缺陷，也不是代码缺陷）。
            """
            page.wait_for_function(
                "() => document.querySelectorAll('#cn-econ .mac-econ-item').length >= 10"
                " && document.querySelectorAll('#cn-estate .cn-city').length >= 1"
                " && document.querySelectorAll('#cn-rate-list .mac-var').length >= 4",
                timeout=40000)

        try:
            _wait_cn_ready()
        except Exception:  # noqa: BLE001 —— 超时后照常取数，由下方断言如实报红
            print("  [warn] /macro/cn 数据未就绪（AkShare 超时/失败）→ 断言会如实反映")
        page.wait_for_timeout(1200)
        d = page.evaluate(CN_MACRO_JS)
        # 外部 AkShare 瞬时失败 → **重载一次**（**不放松判据**，只是不把一次网络抖动当页面缺陷；
        # 与 MX 段对 BLS 的处置同纪律：pitfalls「依赖外部 API 的断言要容忍一次瞬时失败」）
        if len([t for t in d["rateChgTexts"] if t.endswith("bp")]) < 3:
            print("  [retry] rate 组首轮未渲染齐（外部 AkShare 瞬时失败）→ 重载一次再测")
            page.reload(wait_until="load")
            try:
                _wait_cn_ready()
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(1200)
            d = page.evaluate(CN_MACRO_JS)
        # CN-12 重建次数：>1 就是「虚线会消失」的回归（修复前实测 8 次）
        rec = page.evaluate("() => window.__cnRecreate || 0")
        check(rec <= 1, "CN-12 加载期图表重建 ≤1 次（重建会清空悬停态 → 虚线消失）", rec)

        # CN-13 悬停吸附态必须**跨一次 re-render 存活**：程序化点 refresh（**不动鼠标**，
        #   避免 mouseout 把吸附态清掉）→ 实例不应重建、$crossY 不应变化。
        _g13 = page.evaluate(
            """() => { const cv = document.getElementById('cn-chart');
                       const c = window.Chart && window.Chart.getChart(cv);
                       const r = cv.getBoundingClientRect(); const a = c.chartArea;
                       return { rect: {left: r.left, top: r.top},
                                area: {left: a.left, right: a.right, top: a.top, bottom: a.bottom} }; }"""
        )
        _a13, _r13 = _g13["area"], _g13["rect"]
        _mx = _r13["left"] + _a13["left"] + (_a13["right"] - _a13["left"]) * 0.5
        _my = _r13["top"] + _a13["top"] + (_a13["bottom"] - _a13["top"]) * 0.5
        page.mouse.move(_mx, _my)
        page.wait_for_timeout(400)
        page.mouse.move(_mx, _my)
        page.wait_for_timeout(200)
        # ⚠️ 不变量：**虚线必须钉在吸附点上**（`$crossY === meta.data[dataIdx].y`）。
        #    2026-09-16 实测踩坑：原地换数据（`chart.update("none")`）后元素坐标已重算，
        #    若沿用旧 `$crossY` → **圆点移到新位置、虚线冻在旧高度**（用户原话
        #    "虚线要跟着吸附在线上的那个点走"）。故更新后必须**重新对齐**，且用本条钉住。
        _state_js = ("() => { const c = window.Chart.getChart(document.getElementById('cn-chart'));"
                     " const s = c.$crossSource;"
                     " const p = s ? c.getDatasetMeta(s.dsIndex).data[s.dataIdx] : null;"
                     " return { tag: c.__tag, crossY: c.$crossY === undefined ? null : c.$crossY,"
                     "          dotY: p ? p.y : null }; }")
        _before = page.evaluate(_state_js)
        page.evaluate("() => document.getElementById('refresh-btn').click()")
        page.wait_for_timeout(4000)
        _after = page.evaluate(_state_js)
        check(_before["crossY"] is not None and _after["crossY"] == _before["crossY"]
              and _after["tag"] == _before["tag"],
              "CN-13 悬停吸附态跨 re-render 存活（实例不重建 + $crossY 不变）",
              (_before, _after))
        _aligned = (lambda s: s["crossY"] is not None and s["dotY"] is not None
                    and abs(s["crossY"] - s["dotY"]) < 0.5)
        check(_aligned(_after), "CN-14 数据原地更新后虚线仍钉在吸附点上（$crossY == 圆点 y）",
              (_after["crossY"], _after["dotY"]))

        print(f"  quadrant={d['quadrant']!r} econItems={d['econItems']} "
              f"econAsOf={d['econAsOf']!r} cities={d['estateCities']} pts={d['pointCount']}")
        print(f"  canvas={d['canvasBitmapW']}x{d['canvasBitmapH']} "
              f"css={d['canvasCssW']}x{d['canvasCssH']} wrapH={d['chartWrapH']}")

        check(d["moduleIds"] == 7, "CN-2 七个模块骨架齐全（含 #cn-regime / #cn-chart-wrap / #cn-econ）",
              d["moduleIds"])
        # C2：canvas 位图 == 显示尺寸（容器显式高度 + maintainAspectRatio:false + 无 !important 覆盖）
        check(d["canvasBitmapW"] == d["canvasCssW"] and d["canvasBitmapH"] == d["canvasCssH"],
              "CN-3 canvas 位图 == 显示尺寸（C2）",
              (d["canvasBitmapW"], d["canvasBitmapH"], d["canvasCssW"], d["canvasCssH"]))
        # C2 纠正项：增长轴口径必须写进页面（水平 vs 50，不是同比方向）
        check(bool(d["quadrant"]), "CN-4a 四象限已渲染（data-quadrant 非空）", d["quadrant"])
        check("PMI 与 50" in d["basisText"] and "水平口径" in d["basisText"],
              "CN-4b 口径注释写明「PMI 与 50 比较 · 水平口径」（非同比方向）", d["basisText"][:80])
        # C1 纠正项：房价只有「北京 · 上海」，文案**不得**写成 70 城
        check("北京" in d["estateText"] and "上海" in d["estateText"] and d["estateCities"] == 2,
              "CN-5 地产模块为北京/上海双序列（仅 2 城）", (d["estateCities"], d["estateText"][:60]))
        check("70 城" not in d["estateText"], "CN-5b 文案不含「70 城」（C1 回归）", d["estateText"][:80])
        # 反馈回归护栏（2026-09-15 用户反馈「+21.20% 却配 ↓ 箭头」）：
        #   同一格里「数值符号」= 同比本身、「箭头」= 同比较上期 → **必须**有 title 写明口径。
        #   ⚠️ 别把这条改成"箭头跟随数值符号"：那会变成纯冗余，丢掉"增速回落"这层信息。
        check(len(d["chgTitles"]) >= 10 and all(t.strip() for t in d["chgTitles"]),
              "CN-4c 同比单元格全部带口径 title（数值符号 vs 箭头语义消歧）",
              (len(d["chgTitles"]), [t for t in d["chgTitles"] if not t.strip()]))
        check(any("去年同月" in t for t in d["chgTitles"]),
              "CN-4d title 写明「去年同月」口径（自证 title 非空壳）", d["chgTitles"][:2])
        check("—%" not in d["varsText"] and "—%" not in d["econText"],
              "CN-4e 无「—%」（同比缺失时只显示「—」，不拼百分号）")
        # 利率类 bp 口径（2026-09-15 改造）：LPR / SHIBOR / 10Y 三格都应是 `±X.Xbp`
        #   —— 10Y 原先因中债接口只有 6 个月窗口而恒为「—」（那一格是死数据）。
        bp_cells = [t for t in d["rateChgTexts"] if t.endswith("bp")]
        check(len(bp_cells) >= 3, "CN-4f 利率与流动性三格均为 bp 口径（10Y 不再是死格）",
              d["rateChgTexts"])
        # ⚠️ 行数必须一起断言：否则「rate 组没到」时这条会**空跑并假绿**（2026-09-15 实测）。
        #    下限 4 = LPR/SHIBOR/10Y + 社融（**利率三行必须到**）；上限不写死 ——
        #    第 5 行「信用利差」来自 `/api/cn/quotes`，它失败时该行按设计不出现。
        check(len(d["rateChgTexts"]) >= 4 and "—" not in d["rateChgTexts"],
              "CN-4g 利率与流动性 ≥4 行（LPR/SHIBOR/10Y/社融）且无「—」",
              d["rateChgTexts"])
        check("bp" in d["rateNote"], "CN-4h 利率列说明写明单位 bp（两种单位同列必须自描述）",
              d["rateNote"])
        # as_of 口径：**必须显示数据月份**，不得写「最新 / 实时」
        check(bool(re.search(r"\d{4}年\d{1,2}月", d["econText"])),
              "CN-6a 经济数据显示数据月份（形如 2026年8月）", d["econAsOf"])
        check("最新" not in d["econText"] and "实时" not in d["econText"],
              "CN-6b 不得标注「最新 / 实时」（月度数据有发布滞后）")
        # F-5 联动：本页高亮「中国宏观」且「宏观数据」不再 active
        check(d["navCount"] == 12 and d["cnActive"] and not d["macroActive"],
              "CN-7 侧栏 12 项且仅「中国宏观」active", (d["navCount"], d["cnActive"], d["macroActive"]))
        # R9 主题分叉：带 dark 偏好进入本页，data-theme 必须仍是 dark
        check(d["theme"] == "dark", "CN-8 带 dark 偏好进入本页仍为 dark（主题初始化同源）", d["theme"])
        check(len(d["pills"]) == 6 and d["pointCount"] > 0,
              "CN-9 品种胶囊 6 项 + 主图有数据点", (d["pills"], d["pointCount"]))
        check(d["scrollW"] == d["innerW"], "CN-10a 1920 无横向溢出", (d["scrollW"], d["innerW"]))

        # §7.4：三个视口 + 两个中间盲区（1500 / 1024）—— 只改视口不重载，媒体查询即时重算
        scanned = []
        for (vw, vh) in ((1920, 1080), (1500, 900), (1280, 720), (1024, 768), (375, 812)):
            page.set_viewport_size({"width": vw, "height": vh})
            page.wait_for_timeout(500)
            m = page.evaluate(CN_MACRO_JS)
            scanned.append(vw)
            exp = _expect_chart_wrap_h(vw, vh)
            check(m["chartWrapH"] is not None and abs(m["chartWrapH"] - exp) <= 2,
                  f"CN-10b {vw} 主图容器 ≈{exp:.0f}px（clamp 生效，非固定值）", m["chartWrapH"])
            check(m["scrollW"] == m["innerW"], f"CN-10c {vw} 无横向溢出",
                  (m["scrollW"], m["innerW"]))
        # 覆盖度护栏：宽度扫描若选择器/渲染变化会**空跑并全绿**（KY-3 同款）
        check(len(scanned) == 5, "CN-10d 已扫满 5 个宽度（含 1500 / 1024 两个中间盲区）", scanned)

        check(not errors, "CN-11 console error = 0", errors[:5])
    finally:
        ctx.close()


def assert_macro_refine(browser, url: str) -> None:
    """MR/M-1~M-10 宏观页 refinement（plan K-5 的 M-1~M-9）。

    覆盖：D1 主题 / D2 关系口径 / D3 主图主次 / D4 Y 轴 / D5-D6 留白 / D7 分层 / D10 1280 两列 / D11 375 主图。

    ⚠️ 主题判据必须**显式给 localStorage 再加载** —— 只点切换按钮测不出"带偏好进入页面"的缺陷（D1 就是这么漏的）。
    """
    print("\n--- MR 宏观页 refinement（macro-page-refine）---")
    themes: dict = {}
    for pref in ("dark", "light"):
        for path, tag in (("/", "首页"), ("/macro", "宏观页")):
            ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            try:
                pg = ctx.new_page()
                pg.add_init_script("try { localStorage.setItem('mp-theme', '%s'); } catch (e) {}" % pref)
                pg.goto(url + path.lstrip("/"), wait_until="load")
                pg.wait_for_timeout(3500)
                themes[(pref, tag)] = pg.evaluate(MACRO_REFINE_JS)
                if pref == "dark" and tag == "宏观页":
                    pg.screenshot(path=str(OUT_DIR / "shot-macro-refine-dark.png"), full_page=True)
            finally:
                ctx.close()
    dk, lt = themes[("dark", "宏观页")], themes[("light", "宏观页")]
    print(f"  pref=dark  -> attr={dk['theme']!r} bg={dk['bodyBg']!r} "
          f"(首页 attr={themes[('dark', '首页')]['theme']!r} bg={themes[('dark', '首页')]['bodyBg']!r})")
    print(f"  pref=light -> attr={lt['theme']!r} bg={lt['bodyBg']!r} "
          f"(首页 attr={themes[('light', '首页')]['theme']!r} bg={themes[('light', '首页')]['bodyBg']!r})")
    check(dk["theme"] == "dark", "M-1 /macro 在 localStorage=dark 下 data-theme=dark（D1 回归护栏）", dk["theme"])
    check(dk["bodyBg"] != lt["bodyBg"], "M-1b dark / light 页面底色确实不同（attr 与 CSS 未脱节）",
          (dk["bodyBg"], lt["bodyBg"]))
    check(all(themes[(p, "首页")]["theme"] == themes[(p, "宏观页")]["theme"] for p in ("dark", "light")),
          "M-2 /macro 与 / 的同偏好主题行为一致",
          {p: (themes[(p, "首页")]["theme"], themes[(p, "宏观页")]["theme"]) for p in ("dark", "light")})

    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.goto(url + "macro", wait_until="load")
        page.wait_for_timeout(3500)
        d = page.evaluate(MACRO_REFINE_JS)
        print(f"  rel: mode={d['relMode']} rows={d['relRows']} r={d['relR']} sig={d['relSig']}")
        print(f"  note={d['relNote']!r}")
        print(f"  slack: factors={d['factorsSlack']}px vars={d['varsSlack']}px | regimeIsCard={d['regimeIsCard']} "
              f"borderTop={d['regimeBorderTop']} | docH={d['docH']}")
        print(f"  layers: hero bg={d['heroBg']} border={d['heroBorder']} | quiet bg={d['quietBg']} | "
              f"regime cols={d['regimeColW']} of {d['regimeW']}")
        check(d["scrollW"] == d["innerW"], "M-9 1920 档无横向溢出", (d["scrollW"], d["innerW"]))

        # M-3：**标注必须与实际行为一致**（D2 核心缺陷：标注写 ≥0.5，实际列出 6 行全 < 0.5）
        #      以 data-rel-mode 为主判据（"有显著对"还是"无显著对兜底"），再校验文案/行数是否自洽。
        mode, thr, rs = d["relMode"], d["relThreshold"], d["relR"]
        if mode == "significant":
            bad = [v for v in rs if v is not None and v < thr] if thr is not None else None
            check(thr is not None and not bad and 1 <= len(rs) <= 3,
                  f"M-3 宏观关系（显著模式）：标注阈值 {thr} 与列出的行一致，且 ≤3 条",
                  (d["relNote"], rs))
        elif mode == "fallback":
            check(len(rs) <= 2 and "无" in d["relNote"],
                  "M-3 宏观关系（兜底模式）：标注显式说明「无显著对」且仅列 ≤2 条",
                  (d["relNote"], rs))
        else:
            check(False, "M-3 宏观关系容器必须声明 data-rel-mode（过滤口径可被验收）", mode)
        check(d["relMoreShown"], "M-3b 存在被折叠的对 → 「查看全部」可点", d["relMoreShown"])
        try:
            page.evaluate("() => { const b = document.getElementById('macro-rel-more'); if (b) b.click(); }")
            page.wait_for_timeout(250)
            d_exp = page.evaluate(MACRO_REFINE_JS)
            check(d_exp["relRows"] == 6, "M-3c 展开后 6 对齐全（n= 次级信息保留）", d_exp["relRows"])
            page.evaluate("() => { const b = document.getElementById('macro-rel-more'); if (b) b.click(); }")
            page.wait_for_timeout(250)
            check(page.evaluate(MACRO_REFINE_JS)["relRows"] == d["relRows"], "M-3d 再点收起回到默认视图")
        except Exception as exc:  # noqa: BLE001
            check(False, "M-3c 展开按钮可交互（点开 + 收起）", exc)

        # M-7：一级模块必须**不再是等权卡片**（PRD「降卡片感」；plan §3.2）
        check(d["regimeIsCard"] is False and str(d["regimeBorderTop"]).startswith("0"),
              "M-7 「当前宏观环境」为无边框区块（不再是等权卡片）", (d["regimeIsCard"], d["regimeBorderTop"]))
        # M-6：宏观因子列不得有空转留白（D5：改前 77px）
        check(d["factorsSlack"] is not None and d["factorsSlack"] <= 20,
              "M-6 宏观因子列额外留白 ≤ 20px（D5 改前 77px）", (d["factorsSlack"], d["varsSlack"]))

        # M-4 / M-5：全部对比模式的线条主次 + Y 轴自适应（D3 / D4）
        page.evaluate("() => document.querySelector('#macro-pills .mac-pill[data-pick=\"__all__\"]').click()")
        page.wait_for_timeout(1300)
        dm = page.evaluate(MACRO_REFINE_JS)
        bw = dm["dsBorder"]
        rng = (dm["yMax"] - dm["yMin"]) if (dm["yMax"] is not None and dm["yMin"] is not None) else None
        drng = (dm["dataMax"] - dm["dataMin"]) if (dm["dataMax"] is not None and dm["dataMin"] is not None) else None
        print(f"  multi: ds={dm['dsCount']} border={bw} labels={dm['dsLabels']}")
        print(f"  multi: y=[{dm['yMin']}, {dm['yMax']}] data=[{dm['dataMin']}, {dm['dataMax']}]")
        check(bool(bw) and len(set(bw)) > 1 and max(bw) >= 2.0 and min(bw) <= 1.4,
              "M-4 全部对比：选中序列描边显著重于其他（有主次，D3）", bw, deps=("macro",))
        check(rng is not None and drng is not None and drng <= rng <= drng * 1.25,
              "M-5 全部对比 Y 轴贴合数据（≤ 数据范围 ×1.25 且不裁数据）",
              (rng, drng, dm["yMin"], dm["yMax"]), deps=("macro",))

        # M-8 / M-10：1280 保持两列（D10）/ 375 主图 ≥360px（D11）+ 无横向溢出
        for (w, h, label) in ((1280, 720, "1280"), (375, 812, "375")):
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(700)
            dv = page.evaluate(MACRO_REFINE_JS)
            print(f"  {label}: docH={dv['docH']} twoCol={dv['twoColCols']} chartWrapH={dv['chartWrapH']} "
                  f"scrollW={dv['scrollW']}/{dv['innerW']}")
            check(dv["scrollW"] == dv["innerW"], f"M-9 {label} 档无横向溢出", (dv["scrollW"], dv["innerW"]))
            if w == 1280:
                check(dv["twoColCols"] == 2, "M-10 1280 档两列区保持两列（D10）", dv["twoColCols"])
            else:
                check(dv["twoColCols"] == 1, "M-10b 375 档两列区降为单列", dv["twoColCols"])
                check(dv["chartWrapH"] is not None and dv["chartWrapH"] >= 360,
                      "M-8 375 档主图高 ≥360px（D11 改前 325px）", dv["chartWrapH"])
        check(not errors, "M-9b /macro 三档 console error = 0", errors[:3])
    finally:
        ctx.close()


# —— XC 宏观页悬停参考线（2026-09-14 macro-chart-crosshair 任务）——
# ⚠️ 标签用 `XC-*` 而不是 plan 里写的 `MX-*` —— `MX-*` 已被宏观页断言（assert_macro_page）占用，
#    重名会让失败报告无法定位是哪一处红（偏离记入 journal）。
XC_JS = r"""
() => {
  const c = window.Chart && window.Chart.getChart(document.getElementById('macro-chart'));
  if (!c) return null;
  const a = c.chartArea;
  const r = document.getElementById('macro-chart').getBoundingClientRect();
  // ⚠️ formatter 只从 config.plugins 的插件对象上读：**读 options.plugins.hoverCrosshair 会触发
  //    Chart.js 的 scriptable-option 解析**（把函数值立即以 context 调用）→ 探针自己会把页面搞崩。
  let entry = null;
  ((c.config && c.config.plugins) || []).forEach((p) => { if (p && p.id === 'hoverCrosshair') entry = p; });
  return {
    plugins: (c.config.plugins || []).map((p) => p && p.id),
    hasFormatter: !!(entry && typeof entry.formatter === 'function'),
    area: { top: a.top, bottom: a.bottom, left: a.left, right: a.right },
    rect: { top: r.top, left: r.left },
    label: c.$crosshairLabel === undefined ? null : c.$crosshairLabel,
    crossY: c.$crossY === undefined ? null : c.$crossY,
    axisValue: (c.$crossY == null) ? null : c.scales.y.getValueForPixel(c.$crossY),
    axisPos: c.scales.y.position,
  };
}
"""


def assert_macro_crosshair(browser, url: str) -> None:
    """XC-1~XC-9 宏观页悬停参考线（plan X-4；标签改 `XC-*`，见上方注释）。

    核心价值：锁住"读数按**轴语义**分派"这条不变量 —— 单变量黄金不得出现 `%`、
    10Y 不得被二次换算（4.987 → 0.4987）。plan 的 MX-8（首页 CS-*/F-7a 回归）由本脚本
    既有的 `assert_crosshair` / `assert_fidelity` 覆盖，故此处不重复断言。
    """
    print("\n--- XC 宏观页悬停参考线（crosshair）---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.goto(url + "macro", wait_until="load")
        page.wait_for_timeout(3500)

        def probe(frac: float, click: str | None = None) -> dict:
            """点（可选）品种胶囊 → 把鼠标移到绘图区纵向 frac 处 → 读回插件状态。"""
            if click:
                page.evaluate(
                    "() => document.querySelector('#macro-pills .mac-pill[data-pick=\"%s\"]').click()" % click
                )
                page.wait_for_timeout(1000)
            base = page.evaluate(XC_JS)
            if not base:
                return {}
            y = base["rect"]["top"] + base["area"]["top"] + \
                (base["area"]["bottom"] - base["area"]["top"]) * frac
            x = base["rect"]["left"] + (base["area"]["left"] + base["area"]["right"]) / 2
            page.mouse.move(x, y)
            page.wait_for_timeout(400)
            out = page.evaluate(XC_JS)
            out["snap"] = page.evaluate("() => document.getElementById('macro-chart').toDataURL()")
            return out

        def num(s):
            mo = re.search(r"[-+]?\d+(?:\.\d+)?", s or "")
            return float(mo.group(0)) if mo else None

        d0 = page.evaluate(XC_JS)
        # XC-0 之后紧跟 `if not d0: return` ⇒ 本组其余断言都被它挡住（图表实例不存在就整组跳过）
        check(bool(d0), "XC-0 #macro-chart 实例可达", deps=("macro",))
        if not d0:
            return
        print(f"  plugins={d0['plugins']} hasFormatter={d0['hasFormatter']} axisPos={d0['axisPos']}")
        check("hoverCrosshair" in (d0["plugins"] or []),
              "XC-1 宏观页主图已挂 hoverCrosshair（防 script 顺序错 → plugins:[undefined] 静默失效）",
              d0["plugins"])
        check(d0["hasFormatter"], "XC-1b 实例级 formatter 已注入（读数口径可注入，不改共享插件）")

        # XC-2 单变量·黄金：真实价格 + $，**绝不能是 '+4286.6%'**（plan 的头号后果）
        # ⚠️ 胶囊的 `data-pick` 用的是 PICKS 里的键：黄金 `gc=f`（**无 `^`**）、10Y `^tnx`（有 `^`）
        g = probe(0.5, "gc=f")
        print(f"  gold:   label={g.get('label')!r} axis={g.get('axisValue')}")
        try:   # 目视证据：横线 + 轴端读数气泡（不参与断言）
            page.locator("#macro-chart-wrap").screenshot(path=str(OUT_DIR / "shot-macro-crosshair.png"))
        except Exception as exc:  # noqa: BLE001
            print(f"  截图失败（不影响断言）: {exc}")
        check(g.get("label") and "%" not in g["label"] and g["label"].startswith("$")
              and abs((num(g["label"]) or 0) - (g.get("axisValue") or 0)) < 0.005,
              "XC-2 单变量·黄金读数 = 真实价 + $（不是 +4286.6%）", (g.get("label"), g.get("axisValue")))
        # XC-3 单变量·10Y：3 位小数 + %，且**未被二次换算**（4.987 不能变成 0.4987）
        t = probe(0.5, "^tnx")
        print(f"  10Y:    label={t.get('label')!r} axis={t.get('axisValue')}")
        tv = num(t.get("label"))
        check(t.get("label") and t["label"].endswith("%") and tv is not None
              and abs(tv - (t.get("axisValue") or 0)) < 0.0006,
              "XC-3 单变量·10Y 读数 = 轴值 + %（未被 displayValue 二次换算）",
              (t.get("label"), t.get("axisValue")))
        # XC-4 全部对比：指数值，纯数字（无 % / 无 $）
        a = probe(0.5, "__all__")
        print(f"  all:    label={a.get('label')!r} axis={a.get('axisValue')}")
        check(a.get("label") and "%" not in a["label"] and "$" not in a["label"]
              and re.fullmatch(r"\d+\.\d{2}", a["label"]) is not None
              and abs((num(a["label"]) or 0) - (a.get("axisValue") or 0)) < 0.005,
              "XC-4 全部对比读数 = 纯指数数字（无单位）", (a.get("label"), a.get("axisValue")))
        # XC-5（旧「不同 Y 指纹不同」= 跟手）→ 拆为 XC-5a + XC-5b（plan §6 Step 4）。
        # ⚠️ plan §3.6 实测 XC-5 **仍会绿**（两点吸到不同的线）—— 绿的理由是"换了目标线"，
        #    而非"吸附正确"，属语义漂移；绿 ≠ 不用改，故同样替换。
        x1 = _snap_probe(page, "macro-chart", 0.3, 0.5)
        x2 = _snap_probe(page, "macro-chart", 0.7, 0.5)
        ok5a = bool(x1 and x2 and x1.get("usedIdx") is not None
                    and x2.get("usedIdx") is not None and x1["usedIdx"] != x2["usedIdx"])
        check(ok5a, "XC-5a 不同 x 吸附到不同数据列（横线随数据走）",
              ((x1 or {}).get("usedIdx"), (x2 or {}).get("usedIdx")))
        dy5 = None
        if x1 and x1.get("expectY") is not None and x1.get("crossY") is not None:
            dy5 = abs(x1["crossY"] - x1["expectY"])
        check(dy5 is not None and dy5 < 0.5,
              "XC-5b $crossY 吸附到最近数据点（误差<0.5px）",
              ((x1 or {}).get("crossY"), (x1 or {}).get("expectY")))
        # XC-6 移出绘图区 → 隐藏
        page.mouse.move(5, 5)
        page.wait_for_timeout(500)
        d_out = page.evaluate(XC_JS)
        check(d_out.get("crossY") is None, "XC-6 鼠标移出绘图区后 $crossY 清空（横线隐藏）", d_out.get("crossY"))
        # XC-7 切品种/切范围重建实例后插件不丢（与首页 CS-7b 同源风险）
        page.evaluate("() => document.querySelector('#macro-range .mac-pill[data-range=\"5y\"]').click()")
        page.wait_for_timeout(1200)
        d7 = page.evaluate(XC_JS)
        check(bool(d7) and "hoverCrosshair" in (d7["plugins"] or []) and d7["hasFormatter"],
              "XC-7 切范围重建后新实例仍带 hoverCrosshair + formatter",
              (d7 or {}).get("plugins"))
        # XC-9 本块内 console 干净（插件缺 helper / 顺序错都会在这里冒出来）
        check(not errors, "XC-9 /macro 悬停交互期间 console error = 0", errors[:3])
    finally:
        ctx.close()


# —— KY KPI 无静默截断（2026-09-14 kpi-responsive-fix 任务）——
# ⚠️ 断的是**不变量**（"KPI 数值不得被省略号截断"），不是具体字号/断点数值 ——
#    否则每调一次参数就要改一次断言，最后会变成"改断言让它变绿"（plan R2）。
KPI_WIDTHS = [1920, 1760, 1600, 1500, 1440, 1366, 1280, 1100, 1024, 900, 800, 769]

SCAN_JS = r"""
() => {
  const SEL = '.kpi-val, .kpi-sub, .kpi-label';
  const bad = [];
  document.querySelectorAll(SEL).forEach((e) => {
    if (e.scrollWidth > e.clientWidth + 1) {
      bad.push({ cls: (e.className || ''), text: e.textContent.trim(),
                 need: e.scrollWidth, have: e.clientWidth });
    }
  });
  // 其它 ellipsis 元素：**只报告不判失败**（便于逐步收敛）
  // 显式排除 .news-item 内的元素 —— 它们是设计上就横向滚动（overflow-x:auto），不是缺陷
  const others = [];
  document.querySelectorAll('body *').forEach((e) => {
    const cs = getComputedStyle(e);
    if (cs.textOverflow !== 'ellipsis') return;
    if (cs.overflowX === 'auto' || cs.overflowX === 'scroll') return;
    if (e.matches(SEL) || e.closest('.news-item') || e.closest('.kpi-card')) return;
    if (e.scrollWidth > e.clientWidth + 1) {
      others.push({ cls: (e.className || e.tagName), text: e.textContent.trim().slice(0, 24) });
    }
  });
  const kpi = document.querySelector('.row-kpi');
  const card = document.querySelector('.kpi-card');
  const val = document.querySelector('.kpi-val');
  const spark = document.querySelector('.kpi-spark');
  return {
    bad: bad, others: others,
    cols: kpi ? getComputedStyle(kpi).gridTemplateColumns.trim().split(/\s+/).length : null,
    cardW: card ? Math.round(card.getBoundingClientRect().width) : null,
    font: val ? getComputedStyle(val).fontSize : null,
    sparkW: spark ? Math.round(spark.getBoundingClientRect().width) : null,
    cardPad: card ? getComputedStyle(card).paddingLeft : null,
  };
}
"""


def assert_kpi_no_truncation(browser, url: str) -> None:
    """KY-1~KY-3：跨 12 个宽度扫 KPI 是否被 `text-overflow: ellipsis` 静默截断。

    单次页面加载 + 逐宽度 `set_viewport_size()`（媒体查询即时重算，不重新加载）。
    输出各宽度的列数 / 卡宽 / 字号 / spark 宽，便于定稿 `clamp()` 系数与断点（plan §3.3 的模型校准）。
    """
    print("\n--- KY KPI 无静默截断（跨宽度扫描）---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    rows = []
    other_hits: dict[str, list] = {}
    try:
        page = ctx.new_page()
        page.goto(url, wait_until="load")
        try:
            page.wait_for_selector("#watchlist-section:not(.hidden)", timeout=25000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(1200)
        for w in KPI_WIDTHS:
            page.set_viewport_size({"width": w, "height": 900})
            page.wait_for_timeout(200)
            d = page.evaluate(SCAN_JS)
            rows.append((w, d))
            print(f"  W={w:<5} 列={d['cols']} 卡宽={d['cardW']} 字号={d['font']} "
                  f"spark={d['sparkW']} 截断={len(d['bad'])}"
                  + (f" 最严重={max(b['need'] - b['have'] for b in d['bad'])}px" if d["bad"] else ""))
            if d["bad"]:
                print(f"        例：{d['bad'][0]['cls']} {d['bad'][0]['text']!r} "
                      f"need={d['bad'][0]['need']} have={d['bad'][0]['have']}")
            if d["others"]:
                other_hits[str(w)] = d["others"]
        for w, d in rows:
            check(not d["bad"],
                  f"KY-1 W={w} KPI（数值/副标题/标签）无省略号截断",
                  (len(d["bad"]), d["bad"][0] if d["bad"] else None))
        # KY-2 其它 ellipsis 元素：只报告（不 fail），便于逐步收敛
        if other_hits:
            w0 = sorted(other_hits)[0]
            print(f"  [报告] 其它 ellipsis 元素也出现截断（不判失败）：{other_hits[w0][:3]}")
        check(True, "KY-2 其它 ellipsis 元素仅报告（设计上横滚的 .news-item 已排除）",
              list(other_hits.keys())[:4])
        # KY-3 扫描覆盖度：确认真的扫到了 12 个宽度（防"空扫描假绿"）
        check(len(rows) == len(KPI_WIDTHS), "KY-3 扫描覆盖全部 12 个宽度", len(rows))
    finally:
        ctx.close()


# === 侧栏市场状态：两行两市场（market-session-status，2026-09-16）===
#
# 注入 UTC → 期望（A股 / 美股 标签 + 该市场此刻是否交易中）。
# 口径 = plan §4.1「按**各市场本地时钟**判定，含左不含右；周末按 local weekday」。
# ⚠️ 期望值不是手算的：由临时探针用 Python `zoneinfo` 独立核算后写入（证据见 journal §）。
# ⚠️ 两个 12 月用例是 **DST 护栏**：任何写死「北京 21:30 / 22:30 = 美股开盘」的实现都会在此变红。
# ⚠️ 与 plan §4.2 / Step 6 表格有**两处出入**，已实测复核并**按 §4.1 修正**（plan 表格笔误）：
#    ① 北京 12:00 = 美东 00:00，美东 local weekday 仍是周三 ⇒ `t < 09:30` ⇒ **未开盘**（plan 写「已收盘」）；
#    ② `2026-09-19T04:00Z` = 美东 09-19 00:00 是**周六** ⇒ **休市**（plan Step 6 写「已收盘」）。
MS_CASES = [
    # (注入 UTC,              期望 A股,        期望 美股,       A股绿, 美股绿, 说明)
    ("2026-09-16T12:44:00Z", "A股 已收盘",   "美股 未开盘",  False, False, "用户截图场景（北京 20:44 / 美东 08:44 EDT）"),
    ("2026-09-16T13:30:00Z", "A股 已收盘",   "美股 交易中",  False, True,  "北京 21:30 / 美东 09:30（EDT）"),
    ("2026-12-01T13:30:00Z", "A股 已收盘",   "美股 未开盘",  False, False, "DST 护栏：北京 21:30 = 美东 08:30（EST）"),
    ("2026-12-01T14:30:00Z", "A股 已收盘",   "美股 交易中",  False, True,  "DST 护栏：北京 22:30 = 美东 09:30（EST）"),
    ("2026-09-16T04:00:00Z", "A股 午间休市", "美股 未开盘",  False, False, "北京 12:00 午休 / 美东 00:00"),
    ("2026-09-16T02:00:00Z", "A股 交易中",   "美股 已收盘",  True,  False, "北京 10:00 盘中 / 美东前一日 22:00"),
    ("2026-09-16T21:30:00Z", "A股 未开盘",   "美股 已收盘",  False, False, "北京次日 05:30 / 美东 17:30"),
    ("2026-09-19T04:00:00Z", "A股 休市",     "美股 休市",    False, False, "周六 12:00（两个市场各自本地都是周六）"),
    ("2026-09-18T19:00:00Z", "A股 休市",     "美股 交易中",  False, True,  "北京周六 03:00 = 美东周五 15:00（§4.1 点名的跨时区场景）"),
]

# 侧栏几何护栏（V6）：可见宽度预算在 ≥769px 全档恒 169px ⇒ 扫 3 档即覆盖全部风险面。
# 769 是抽屉断点（`@media (max-width: 768px)`）的**下沿内联态**，必采（本项目踩过断点空档盲区）。
MS_VIEWPORTS = [(1920, 1080), (1280, 720), (769, 720)]

MS_JS = r"""
() => {
  const hook = (iso) => (typeof window.__marketSession === 'function')
      ? window.__marketSession(iso) : null;

  // 期望色不写死 rgb：从 CSS 变量现场解析（主题/改色后自动跟随）
  const rgbVar = (name) => {
    const t = document.createElement('div');
    t.style.backgroundColor = 'var(' + name + ')';
    t.style.position = 'absolute'; t.style.visibility = 'hidden';
    document.body.appendChild(t);
    const c = getComputedStyle(t).backgroundColor;
    t.remove();
    return c;
  };

  const nowState = hook(null);
  const rows = {};
  document.querySelectorAll('.market-status .ms-row').forEach((r) => {
    const dot = r.querySelector('.ms-dot');
    const txt = r.querySelector('span');
    rows[r.dataset.market || '?'] = {
      text: txt ? txt.textContent : null,
      dotId: dot ? dot.id : null,
      openClass: dot ? dot.classList.contains('open') : null,
      color: dot ? getComputedStyle(dot).backgroundColor : null,
      scrollW: r.scrollWidth, clientW: r.clientWidth,
    };
  });
  const cases = {};
  __CASES__.forEach((iso) => {
    const s = hook(iso);
    cases[iso] = s ? { cn: s.cn.label, us: s.us.label,
                       cnOpen: !!s.cn.open, usOpen: !!s.us.open } : null;
  });
  const sb = document.getElementById('sidebar');
  const ms = document.querySelector('.market-status');
  const ft = document.querySelector('.sidebar-footer');
  const rb = sb ? sb.getBoundingClientRect() : { bottom: 0 };
  return {
    rows: rows,
    cases: cases,
    hasHook: typeof window.__marketSession === 'function',
    now: nowState ? { cn: nowState.cn.label, us: nowState.us.label,
                      cnOpen: !!nowState.cn.open, usOpen: !!nowState.us.open } : null,
    greenRgb: rgbVar('--green'), mutedRgb: rgbVar('--text-muted'),
    footerH: ft ? Math.round(ft.getBoundingClientRect().height) : null,
    msH: ms ? Math.round(ms.getBoundingClientRect().height) : null,
    sbScrollH: sb ? sb.scrollHeight : null,
    sbClientH: sb ? sb.clientHeight : null,
    sbBottom: Math.round(rb.bottom), innerH: window.innerHeight,
    scrollW: document.scrollingElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    time: (document.getElementById('market-time') || {}).textContent || null,
  };
}
"""


def _ms_js() -> str:
    """把注入时刻表填进 MS_JS（只注入"要问的时刻"，期望值留在 Python 侧比对）。"""
    return MS_JS.replace("__CASES__", json.dumps([c[0] for c in MS_CASES]))


def _ms_labels(m: dict) -> dict:
    """把一次 MS_JS 结果压成 {iso: 'A股 xx|美股 yy'}，供三页逐字比对。"""
    return {iso: f"{v['cn']}|{v['us']}" for iso, v in (m.get("cases") or {}).items() if v}


def assert_market_session(browser, url: str) -> None:
    """MS-* 侧栏市场状态「两行两市场」（market-session-status，2026-09-16）。

    MS-1 同源断言（DOM 文案 == 页面内同一函数 window.__marketSession）
    MS-2 两行结构（data-market=cn/us 各行存在、点 id 对应、无占位符、两行文案不同）
    MS-3 §4.1 覆盖表 9 例（含 2 例 DST 护栏 + 1 例跨时区周末）
    MS-4 逐点着色（.open 类 + 实际色 == --green / --text-muted，不写死 rgb）
    MS-5 三页逐字同口径（同一注入时刻表，/ · /macro · /macro/cn 全表一致）
    MS-6 几何护栏 3 档视口（footer 63 / .market-status 50 / 无纵向滚动条 / 零横向溢出 / 贴底）
    MS-7 本组页面 console error = 0

    独立 context（不污染首页主页面），主题不固定（默认偏好）—— 色断言从 CSS 变量现场解析。
    """
    print("\n--- MS 侧栏市场状态（两行两市场 market-session-status）---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))
        page.goto(url, wait_until="load")
        page.wait_for_timeout(900)
        ms = page.evaluate(_ms_js())

        # --- MS-1 同源断言 ---
        # 容差处理：DOM 在页面加载时写入、hook 在断言时重算，二者若**恰好跨越**
        # 09:30/11:30/13:00/15:00/16:00 这类边界就会不一致 —— 等一个刷新周期重读一次
        # （不是放松判据：重读后仍不一致即 FAIL）。
        def _read() -> tuple:
            m = page.evaluate(_ms_js())
            rows = m.get("rows") or {}
            n = m.get("now") or {}
            return (m,
                    ((rows.get("cn") or {}).get("text") or "").strip(),
                    ((rows.get("us") or {}).get("text") or "").strip(),
                    n.get("cn"), n.get("us"))

        ms, dom_cn, dom_us, exp_cn, exp_us = _read()
        if dom_cn != exp_cn or dom_us != exp_us:
            page.wait_for_timeout(1500)      # > updateMarketStatus 的 60s 间隔之外的"重绘"不保证，
            ms, dom_cn, dom_us, exp_cn, exp_us = _read()   # 故这里只是给"跨边界"留一次机会
        check(ms.get("hasHook") is True, "MS-1a 页面暴露 window.__marketSession（验收同源钩子）",
              ms.get("hasHook"))
        check(dom_cn != "" and dom_cn == exp_cn and dom_us != "" and dom_us == exp_us,
              "MS-1b DOM 两行文案 == window.__marketSession（同源，不写死词）",
              (dom_cn, dom_us), (exp_cn, exp_us))

        # --- MS-2 两行结构 ---
        rows = ms.get("rows") or {}
        check(sorted(rows.keys()) == ["cn", "us"],
              "MS-2a .ms-row 恰两行且带 data-market=cn/us", sorted(rows.keys()))
        check((rows.get("cn") or {}).get("dotId") == "market-dot-cn"
              and (rows.get("us") or {}).get("dotId") == "market-dot-us",
              "MS-2b 两行的点 id 分别为 market-dot-cn / market-dot-us",
              ((rows.get("cn") or {}).get("dotId"), (rows.get("us") or {}).get("dotId")))
        check("—" not in (rows.get("cn", {}).get("text") or "—")
              and "—" not in (rows.get("us", {}).get("text") or "—"),
              "MS-2c 两行文案已由脚本填充（不含占位符）",
              ((rows.get("cn") or {}).get("text"), (rows.get("us") or {}).get("text")))
        check((rows.get("cn") or {}).get("text") != (rows.get("us") or {}).get("text"),
              "MS-2d 两行文案互不相同（防两行同一份拷贝）",
              ((rows.get("cn") or {}).get("text"), (rows.get("us") or {}).get("text")))
        check("北京时间" in (ms.get("time") or ""), "MS-2e 第三行仍为北京时间", ms.get("time"))

        # --- MS-3 覆盖表（含 DST 护栏）---
        # MS-0 覆盖度护栏：`_ms_labels` 会把 None 过滤掉 ⇒ 若不钉死条数，
        # "所有用例都取不到值"会退化成"0 条 vs 0 条 = 一致"的**假绿**（红跑实测踩过）。
        check(len(ms.get("cases") or {}) == len(MS_CASES)
              and all(v is not None for v in (ms.get("cases") or {}).values()),
              f"MS-0 注入用例全部产出**非空**结果（{len(MS_CASES)} 例，防空集假绿）",
              {k: v for k, v in (ms.get("cases") or {}).items() if v is None}, "no-null")
        for iso, e_cn, e_us, e_cno, e_uso, note in MS_CASES:
            got = (ms.get("cases") or {}).get(iso)
            ok = bool(got) and got.get("cn") == e_cn and got.get("us") == e_us \
                and got.get("cnOpen") == e_cno and got.get("usOpen") == e_uso
            check(ok, f"MS-3 {iso} → {e_cn} / {e_us}（{note}）",
                  got, (e_cn, e_us, e_cno, e_uso))

        # --- MS-4 逐点着色 ---
        n = ms.get("now") or {}
        green, muted = ms.get("greenRgb"), ms.get("mutedRgb")
        for key, base in (("cn", "A股"), ("us", "美股")):
            row = rows.get(key) or {}
            exp_open = n.get(key + "Open")
            # ⚠️ 必须显式要求两侧都是 bool：旧选择器取不到元素时 openClass/exp_open 同为 None，
            #    `None == None` 会让断言**恒真（假绿）**（红跑实测踩过）。
            check(isinstance(exp_open, bool) and row.get("openClass") is exp_open,
                  f"MS-4a {base} 点的 .open 类 == 该市场此刻是否交易中",
                  row.get("openClass"), exp_open)
            check(row.get("color") == (green if exp_open else muted),
                  f"MS-4b {base} 点色 == {'--green' if exp_open else '--text-muted'}",
                  row.get("color"), (green if exp_open else muted))
        check(green != muted, "MS-4c --green 与 --text-muted 可区分（色断言非同值假绿）",
              (green, muted))

        # --- MS-5 三页逐字同口径（注入时刻表 ⇒ 与真实 now 无关，确定性）---
        base_labels = _ms_labels(ms)
        for path, name in (("macro", "/macro"), ("macro/cn", "/macro/cn")):
            p2 = ctx.new_page()
            errs2: list[str] = []
            p2.on("console", lambda m: errs2.append(m.text) if m.type == "error" else None)
            p2.on("pageerror", lambda e: errs2.append(f"pageerror: {e}"))
            p2.goto(url + path, wait_until="load")
            p2.wait_for_timeout(1200)
            m2 = p2.evaluate(_ms_js())
            lab2 = _ms_labels(m2)
            diff = {k: (base_labels.get(k), lab2.get(k))
                    for k in base_labels if base_labels.get(k) != lab2.get(k)}
            # ⚠️ 必须同时钉死条数：空集 vs 空集 会"一致"（假绿），见 MS-0 同源教训。
            check(len(lab2) == len(MS_CASES) and not diff,
                  f"MS-5a {name} 与首页同口径（{len(MS_CASES)} 例注入时刻全表逐字一致）",
                  (len(lab2), list(diff.items())[:2]), len(MS_CASES))
            check(sorted((m2.get("rows") or {}).keys()) == ["cn", "us"],
                  f"MS-5b {name} 侧栏同样是两行两市场", sorted((m2.get("rows") or {}).keys()))
            check(not errs2, f"MS-5c {name} console error = 0", errs2[:5])
            p2.close()

        # --- MS-6 几何护栏（3 档视口）---
        for (w, h) in MS_VIEWPORTS:
            page.set_viewport_size({"width": w, "height": h})
            page.goto(url, wait_until="load")
            page.wait_for_timeout(800)
            g = page.evaluate(_ms_js())
            # ⚠️ 2026-09-17（UX 走查 F1）：.ms-time 10→11px ⇒ 该行 +2px，footer 63→65、.market-status 50→52
            #    （三档实测一致，非抖动）。钉子随**有意的几何变更**同步更新，语义不变（防"无意的几何漂移"）。
            check(g.get("footerH") == 65, f"MS-6a {w}x{h} .sidebar-footer 高 65（45+18+2，F1 .ms-time 11px）",
                  g.get("footerH"), 65)
            check(g.get("msH") == 52, f"MS-6b {w}x{h} .market-status 高 52（16+16+17+gap2×2）",
                  g.get("msH"), 52)
            check(g.get("sbScrollH") is not None and g["sbScrollH"] <= g["sbClientH"],
                  f"MS-6c {w}x{h} #sidebar 无纵向滚动条", (g.get("sbScrollH"), g.get("sbClientH")))
            bad = [r for r in (g.get("rows") or {}).values()
                   if r.get("scrollW", 0) > r.get("clientW", 0) + 0.5]
            check(not bad and sorted((g.get("rows") or {}).keys()) == ["cn", "us"],
                  f"MS-6d {w}x{h} 两行均不溢出（nowrap 溢出会撑出侧栏横向滚动条）",
                  [(r.get("scrollW"), r.get("clientW")) for r in (g.get("rows") or {}).values()])
            check(g.get("scrollW") == g.get("clientW"), f"MS-6e {w}x{h} 无横向溢出",
                  (g.get("scrollW"), g.get("clientW")))
            check(abs(g.get("sbBottom", 0) - g.get("innerH", 0)) <= 2,
                  f"MS-6f {w}x{h} 侧栏贴底", (g.get("sbBottom"), g.get("innerH")))

        check(not errors, "MS-7 本组页面 console error = 0", errors[:5])
    finally:
        ctx.close()


# —— NA /macro 四态 + 因子 chip + Score 语义色（2026-09-16 macro-page-frontend-refactor 任务）——
# ⚠️ 标签用 `NA-*` 而不是 plan 里写的 `N-*` —— `N-*` 已被首页「最新资讯」断言占用
#    （N-1 / N-7 / N-11 / N-12a…），重名会让失败报告无法定位是哪一处红（同 `XC-*` 的既有先例）。
#
# 四态口径（prd §4 N1）：loading（模板里的静态 .skeleton）→ ok / empty（.mac-empty）/
#   failed（.mac-empty.is-failed + 重试条）。
# ⚠️ `.mac-empty` 类名与「数据暂缺」文案是**可测契约**（MX-12b 依赖）→ 失败态只能**追加** is-failed；
#    本组断言必须同时看住"mac-empty 还在"。
# ⚠️ 1500 悬挂轮等三个场景都用 `page.route` mock，**不为上游红项造数**（C4）：mock 只存在于验收脚本。

NA_DATES = ["2026-09-14", "2026-09-15", "2026-09-16"]


def _na_payload(level="risk_on", score100=68.8, impacts=(2, 1, -1, 1)):
    """构造 `/api/macro` 的 mock payload。

    ⚠️ 因子名必须与服务端一致（`web/app.py:766-794` 的 **风险偏好/美元/利率/商品**），
       否则 N3 的"资产 chip"映射走不到真实分支（`FACTOR_ASSETS` 按名字子串匹配）。
    ⚠️ `score100` 与 `level` **有意解耦**：NA-7 要用"level=risk_off 但 score100=80"这类**矛盾输入**
       证明颜色由 level 推导、而不是由 `score100 > 50` 推导（PRD §3 E1 的核心缺陷）。
    """
    names = ["风险偏好", "美元", "利率", "商品"]
    units = ["", "%", "pp", "%"]
    factors = [{"name": names[i], "value": 0.5, "unit": units[i], "impact": impacts[i], "note": "mock"}
               for i in range(len(names))]
    return {
        "stocks": [{"symbol": "DX-Y.NYB", "label": "美元指数", "value": 98.1, "change_pct": 0.4},
                   {"symbol": "^TNX", "label": "10Y美债", "value": 4.97, "change_pct": -0.2}],
        "trend": {"dates": NA_DATES,
                  "series": [{"key": "dx-y.nyb", "raw": [100.0, 101.0, 102.0]},
                             {"key": "^tnx", "raw": [4.90, 4.95, 4.97]},
                             {"key": "cl=f", "raw": [70.0, 71.0, 72.0]},
                             {"key": "gc=f", "raw": [3300.0, 3310.0, 3320.0]}]},
        "regime": {"level": level, "score": 5, "score100": score100,
                   "normalized": (score100 / 100.0) * 2 - 1, "factors": factors,
                   "basis": "mock 口径说明"},
        "correlation": [{"pair": "美元 ↔ 黄金", "r": -0.62, "n": 250},
                        {"pair": "原油 ↔ 美债", "r": 0.31, "n": 250}],
        "history_regime": {"days": 30, "risk_on": 12, "neutral": 10, "risk_off": 8},
    }


NA_ECON = {
    "as_of": "2026-08",
    "series": [{"key": "cpi", "label": "CPI-U", "unit": "index", "latest": 320.5, "date": "2026-08",
                "yoy": 2.8, "prev_yoy": 2.6, "direction": "up", "history": []}],
    "quadrant": "reflation", "quadrant_label": "再通胀",
    "inflation_axis": "up", "growth_axis": "expanding",
    "basis": {"inflation": "CPI 同比", "growth": "就业"},
}

NA_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const rgbVar = (name) => {
    const t = document.createElement('div');
    t.style.backgroundColor = 'var(' + name + ')';
    t.style.position = 'absolute'; t.style.visibility = 'hidden';
    document.body.appendChild(t);
    const c = getComputedStyle(t).backgroundColor;
    t.remove();
    return c;
  };
  const rows = [...document.querySelectorAll('#macro-factors .mac-factor-row')];
  const imgs = [...document.querySelectorAll('#macro-factors .fr-chip img')];
  const score = q('#regime-score'), level = q('#regime-level'), fac = q('#mac-factors');
  let slack = null;
  if (fac) {
    const cs = getComputedStyle(fac);
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const head = fac.querySelector('.mac-card-head');
    const headH = head ? head.getBoundingClientRect().height : 0;
    let inner = 0;
    [...fac.children].forEach((c) => { if (c !== head) inner += c.getBoundingClientRect().height; });
    slack = Math.round(fac.getBoundingClientRect().height - headH - inner - pad);
  }
  const bar = q('#mac-fail-bar');
  const retry = q('#mac-retry');
  const st = (typeof window.__macroState === 'function') ? window.__macroState() : null;
  return {
    skeletons: document.querySelectorAll('.skeleton').length,
    skelVisible: [...document.querySelectorAll('.skeleton')].filter((n) => n.offsetParent !== null).length,
    skelInChart: document.querySelectorAll('#macro-chart-wrap .skeleton').length,
    hasHook: typeof window.__macroState === 'function',
    blocks: st ? st.blocks : null,
    retryUsed: st ? st.retryUsed : null,
    failBarShown: bar ? !bar.classList.contains('hidden') : null,
    failBarDisplay: bar ? getComputedStyle(bar).display : null,
    failMsg: (q('#mac-fail-msg') || {}).textContent || null,
    retry: retry ? { text: retry.textContent, disabled: !!retry.disabled } : null,
    emptyCount: document.querySelectorAll('.mac-empty').length,
    // ⚠️ 排除失败条自身：它的 `<p class="mac-empty is-failed">` 是**模板里常驻**的（靠 .hidden 控制显隐）
    //    → 不排除的话"成功态不残留 is-failed"这条断言永远假红（实测踩过）。
    emptyFailed: [...document.querySelectorAll('.mac-empty.is-failed')]
      .filter((n) => !n.closest('#mac-fail-bar')).length,
    econFailed: !!q('#macro-econ .mac-empty.is-failed'),
    factorsFailed: !!q('#macro-factors .mac-empty.is-failed'),
    econEmpty: !!q('#macro-econ .mac-empty'),
    chartFailHidden: (q('#macro-chart-fail') || {}).classList
        ? q('#macro-chart-fail').classList.contains('hidden') : null,
    score: score ? { text: score.textContent.trim(), cls: score.className,
                     color: getComputedStyle(score).color } : null,
    level: level ? { text: level.textContent.trim(), cls: level.className } : null,
    rowCount: rows.length,
    chipsPerRow: rows.map((r) => r.querySelectorAll('.fr-chip').length),
    imgPerRow: rows.map((r) => r.querySelectorAll('.fr-chip img').length),
    badges: rows.map((r) => (r.querySelector('.fr-badge') || {}).textContent || null),
    // ⚠️ 2026-09-17（用户反馈「怎么又受益又承压的」）：一个"影响资产"格里会同时出现**两个方向**
    //    （如「利率偏空 → 黄金受益 · 长久期承压」）→ 若 badge 与 chip 只是平铺，元素会排成
    //    `受益 黄金 承压 长久期`，中间的 chip 被两个 badge **夹心** → 必被读成同一资产自相矛盾。
    //    不变量：① 每个 chip 必须在 `.fr-grp` 组内；② 组内 badge 必须在 chip **之后**（资产在前、方向在后）。
    chipsOutsideGrp: [...document.querySelectorAll('#mac-factors .fr-chip')]
      .filter((c) => !c.closest('.fr-grp')).length,
    grpCount: document.querySelectorAll('#mac-factors .fr-grp').length,
    badgeNotAfterChip: [...document.querySelectorAll('#mac-factors .fr-grp')]
      .filter((g) => {
        const b = g.querySelector('.fr-badge'); if (!b) return false;
        const c = g.querySelector('.fr-chip');
        return !c || !(c.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
      }).length,
    // 中性行不得把「中性」写两遍（badge 一个 + 文案里一个 = 读起来像 bug）
    neutralDup: [...document.querySelectorAll('#macro-factors .fr-assets')]
      .filter((a) => (a.textContent.match(/中性/g) || []).length > 1).length,
    // 每行的「资产 + 方向」配对（NA-11 用：校验影响资产方向与后端 inverse 语义同源）
    assetPairs: (() => {
      const out = {};
      rows.forEach((r) => {
        const nm = ((r.querySelector('.fr-name') || {}).textContent || '?').trim();
        out[nm] = [...r.querySelectorAll('.fr-grp')].map((g) => g.textContent.trim());
      });
      return out;
    })(),
    imgSrc: imgs.map((i) => i.getAttribute('src')),
    imgBroken: imgs.filter((i) => !i.complete || i.naturalWidth === 0).length,
    factorsSlack: slack,
    green: rgbVar('--green'), red: rgbVar('--red'), muted: rgbVar('--text-muted'),
    scrollW: document.scrollingElement.scrollWidth, innerW: window.innerWidth,
  };
}
"""

# 合法映射（**独立于 macro.js 的 LEVEL_CLASS**，即"需求"本身）：level → score 的 class
NA_LEVEL_CLASS = {"risk_on": "up", "risk_off": "down", "neutral": "flat", "none": "flat"}

# 本组"成功态"统一用的固定 payload（4 因子齐全 → N3 的素材映射走真实分支）
NA_OK_PAYLOAD = _na_payload(level="risk_on", score100=68.8)


def _has_pair(groups, asset: str, direction: str) -> bool:
    """该行的「资产 + 方向」配对里是否存在「asset 且 direction」同组。"""
    return any(asset in g and direction in g for g in (groups or []))


# NA-11：影响资产方向的对照用例（impacts 顺序与 _na_payload 一致：风险偏好 / 美元 / 利率 / 商品）
#   ⚠️ 期望值来自**需求口径**（inverse ⇒ 变量下行 = 正分），不是从 macro.js 抄的
NA_ASSET_CASES = [
    ((2, 1, -1, 1), "美元弱/利率上行",
     [("美元", "黄金", "受益", True), ("美元", "原油", "受益", True),
      ("利率", "黄金", "承压", True), ("利率", "长久期", "承压", True),
      ("利率", "黄金", "受益", False)]),
    ((2, -1, 1, 1), "美元强/利率下行",
     [("美元", "黄金", "承压", True), ("美元", "原油", "承压", True),
      ("利率", "黄金", "受益", True), ("利率", "长久期", "受益", True),
      ("利率", "黄金", "承压", False)]),
]


# ==================== QM 四象限矩阵（2026-09-18）====================
# 任务档 tasks/2026-09-18-macro-quadrant-matrix。数据只有两个二元离散量
# （inflation_axis / growth_axis）⇒ 2x2 矩阵 + 当前格高亮，位置本身就是信息。
# 排列固定为教材口径（横轴通胀 左低右高 / 纵轴增长 上高下低），**渲染顺序 = 视觉顺序**：
#   cells[0]=左上 复苏(goldilocks) / cells[1]=右上 再通胀(reflation)
#   cells[2]=左下 通缩衰退(deflation) / cells[3]=右下 滞胀(stagflation)
QM_CELL_ORDER = ["goldilocks", "reflation", "deflation", "stagflation"]  # 与 macro.js QUAD_CELLS 同序
QM_CELL_LABELS = {"goldilocks": "复苏", "reflation": "再通胀",
                  "deflation": "通缩衰退", "stagflation": "滞胀"}
# /macro 的轴标签（口径 A）：通胀 ↓/↑ + 增长 ↑/↓
QM_AXES_MACRO = ["通胀 ↓", "通胀 ↑", "增长 ↑", "增长 ↓"]

QM_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const pick = (sel) => [...document.querySelectorAll(sel)];
  const cells = pick('#regime-matrix .rm-cell');
  const cn = pick('#cn-matrix .rm-cell');
  const now = cells.filter((c) => c.classList.contains('is-now'));
  const cnNow = cn.filter((c) => c.classList.contains('is-now'));
  const mx = q('#regime-matrix'), cmx = q('#cn-matrix');
  return {
    exists: !!mx,
    cellCount: cells.length,
    texts: cells.map((c) => c.textContent.trim()),
    nowCount: now.length,
    nowText: now.length ? now[0].textContent.trim() : null,
    unknown: mx ? mx.classList.contains('is-unknown') : null,
    axes: pick('#regime-matrix .rm-axis').map((a) => a.textContent.trim()),
    quadText: (q('#regime-quadrant') || {}).textContent || null,
    matrixW: mx ? Math.round(mx.getBoundingClientRect().height > 0 ? mx.getBoundingClientRect().width : 0) : null,
    matrixH: mx ? Math.round(mx.getBoundingClientRect().height) : null,
    skelH: (() => { const s = q('#regime-matrix .rm-skel');
        return s ? Math.round(s.getBoundingClientRect().height) : null; })(),
    cnExists: !!cmx,
    cnCells: cn.length,
    cnTexts: cn.map((c) => c.textContent.trim()),
    cnNowCount: cnNow.length,
    cnNowText: cnNow.length ? cnNow[0].textContent.trim() : null,
    cnAxes: pick('#cn-matrix .rm-axis').map((a) => a.textContent.trim()),
    cnUnknown: cmx ? cmx.classList.contains('is-unknown') : null,
    cnMatrixW: cmx ? Math.round(cmx.getBoundingClientRect().width) : null,
    cnQuadrant: (() => { const e = q('#cn-regime');
        return e ? (e.getAttribute('data-quadrant') || '') : null; })(),
    cnLevelText: (q('#cn-level') || {}).textContent || null,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}
"""


def assert_quadrant_matrix(browser, url: str) -> None:
    """QM-1~QM-5 四象限矩阵（/macro + /macro/cn）。

    QM-1 两页容器存在且各 4 格（防漏格/重复格）
    QM-2 四格文案集合 == {复苏, 再通胀, 通缩衰退, 滞胀}（防改名漂移；名字以服务端 QUADRANTS 为准）
    QM-2b /macro 轴标签口径（通胀 ↓/↑ + 增长 ↑/↓）
    QM-2d /macro/cn 轴标签**必须**用 上行/回落 + 扩张/收缩，**不得**出现 ↑/↓
          （中国页增长轴是 PMI 与 50 比较的水平口径，写成箭头会误导）
    QM-3 有 quadrant 时**恰好 1 格**高亮、文案 == 服务端 quadrant_label、且**位置映射**正确
          （三组不同 key 各跑一遍 —— 单个用例可能是"蒙对"）
    QM-4 /api/econ 断供：四格照常渲染、0 高亮 + is-unknown，且既有「数据暂缺」文案契约不破
    QM-5 375 档矩阵不横向溢出、且不改变容器外的横向溢出
    """
    print("\n--- QM 四象限矩阵（/macro + /macro/cn）---")

    # ---------- QM-1 / QM-2 / QM-3：三组不同 quadrant 的 mock ----------
    for key in ("reflation", "goldilocks", "stagflation"):
        label = QM_CELL_LABELS[key]
        econ = json.loads(json.dumps(NA_ECON))
        econ["quadrant"] = key
        econ["quadrant_label"] = label
        econ["inflation_axis"] = "up" if key in ("reflation", "stagflation") else "down"
        econ["growth_axis"] = "contracting" if key in ("deflation", "stagflation") else "expanding"

        def ok(which, route, econ=econ):
            body = NA_OK_PAYLOAD if which == "macro" else econ
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(body, ensure_ascii=False))

        ctx, page, _msgs, perrs = _na_open(browser, url, ok)
        try:
            page.goto(url + "macro", wait_until="load")
            page.wait_for_timeout(1200)
            d = page.evaluate(QM_JS)
            print(f"  [{key}] cells={d['cellCount']} texts={d['texts']} now={d['nowCount']}:"
                  f"{d['nowText']!r} axes={d['axes']} w={d['matrixW']}x{d['matrixH']}")
            check(d["exists"] and d["cellCount"] == 4,
                  f"QM-1 [{key}] #regime-matrix 存在且恰好 4 格", (d["exists"], d["cellCount"]))
            check(sorted(d["texts"]) == sorted(QM_CELL_LABELS.values()),
                  f"QM-2 [{key}] 四格文案 == 复苏/再通胀/通缩衰退/滞胀（防改名漏格）", d["texts"])
            check([a for a in d["axes"] if a] == QM_AXES_MACRO,
                  f"QM-2b [{key}] 轴标签口径（通胀 ↓/↑ + 增长 ↑/↓）", d["axes"])
            # 位置映射：投三组不同 key，逐组验"高亮格在数组里的下标"== 教材口径下标
            exp_idx = QM_CELL_ORDER.index(key)
            check(d["nowCount"] == 1 and d["nowText"] == label
                  and d["texts"][exp_idx] == label and d["unknown"] is False,
                  f"QM-3 [{key}] 恰好 1 格高亮、文案取自服务端、且位于教材口径位置（下标 {exp_idx}）",
                  (d["nowCount"], d["nowText"], d["texts"], d["unknown"]))
            check(d["nowCount"] == 1 and isinstance(d["quadText"], str)
                  and d["nowText"] in d["quadText"],
                  f"QM-3c [{key}] 高亮格与 #regime-quadrant 文字行**同源**（同一 label；"
                  "前置 nowCount==1 —— 否则无高亮时该断言平凡成立）",
                  (d["nowCount"], d["nowText"], d["quadText"]))
            check(not perrs, f"QM-3d [{key}] 无 pageerror", perrs[:2])
        finally:
            ctx.close()

    # ---------- QM-4：/api/econ 断供 ----------
    def no_econ(which, route):
        if which == "macro":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(NA_OK_PAYLOAD, ensure_ascii=False))
        else:
            route.abort()

    ctx, page, _msgs, perrs = _na_open(browser, url, no_econ)
    try:
        page.goto(url + "macro", wait_until="load")
        page.wait_for_timeout(1500)
        d = page.evaluate(QM_JS)
        print(f"  [econ 断供] cells={d['cellCount']} now={d['nowCount']} unknown={d['unknown']} "
              f"quadText={d['quadText']!r}")
        check(d["cellCount"] == 4 and d["nowCount"] == 0 and d["unknown"] is True,
              "QM-4 econ 断供时四格照常渲染、**0 高亮** + is-unknown（不假高亮、不跳变）",
              (d["cellCount"], d["nowCount"], d["unknown"]))
        check(isinstance(d["quadText"], str) and "数据暂缺" in d["quadText"],
              "QM-4b 断供时既有「数据暂缺」文案契约不破（#regime-quadrant 一行未改）", d["quadText"])
        check(not perrs, "QM-4c 断供路径无 pageerror", perrs[:2])
    finally:
        ctx.close()

    # ---------- QM-5：375 档不横向溢出 ----------
    econ375 = json.loads(json.dumps(NA_ECON))
    ctx, page, _msgs, perrs = _na_open(browser, url, lambda w, r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(NA_OK_PAYLOAD if w == "macro" else econ375, ensure_ascii=False)),
        viewport=(375, 812))
    try:
        page.goto(url + "macro", wait_until="load")
        page.wait_for_timeout(1200)
        d = page.evaluate(QM_JS)
        print(f"  [375] matrixW={d['matrixW']} overflow={d['overflow']} cells={d['cellCount']}")
        check(d["cellCount"] == 4 and d["overflow"] == 0
              and d["matrixW"] is not None and d["matrixW"] <= 375,
              "QM-5 375 档矩阵渲染完整且无横向溢出（MX-14a 同口径）",
              (d["cellCount"], d["matrixW"], d["overflow"]))
    finally:
        ctx.close()

    # ---------- QM-1c / QM-3g：`/macro/cn` **确定性 mock**（上游不可用时正向分支也能被验到）----------
    #   ⚠️ 实数据那一段是**数据驱动**的：AkShare 取不到时只会走"0 高亮"分支 ⇒ 若不补这段，
    #      "有 quadrant 时必须 1 格高亮"就永远没被真跑过（2026-09-18 实测：首轮绿跑正是这种情形）。
    for key in ("reflation", "deflation"):
        label = QM_CELL_LABELS[key]
        cn_body = {
            "as_of": "2026-08", "series": [], "groups": {}, "failed": [],
            "quadrant": key, "quadrant_label": label,
            "inflation_axis": "up" if key in ("reflation", "stagflation") else "down",
            "growth_axis": "contracting" if key in ("deflation", "stagflation") else "expanding",
            "basis": {"inflation": "mock", "growth": "mock"}, "growth_inputs": {},
        }
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        try:
            page = ctx.new_page()
            cperrs: list[str] = []
            page.on("pageerror", lambda e: cperrs.append(str(e)))

            def _mk_route(body):
                """⚠️ handler **必须只有 1 个形参**：Playwright Python 见到 2 个形参时会按
                `(route, request)` 调用 —— 用 `lambda r, b=body:` 这种"默认参数捕获"写法，
                `b` 会变成 Request 对象，`json.dumps` 抛 TypeError，且异常要到后续某个
                API 调用处才重抛（2026-09-18 实测：表现为"mock 不生效、页面停在空态"）。"""
                def _route(route):
                    route.fulfill(status=200, content_type="application/json",
                                  body=json.dumps(body, ensure_ascii=False))
                return _route

            page.route("**/api/econ/cn*", _mk_route(cn_body))
            page.goto(url + "macro/cn", wait_until="load")
            # ⚠️ 等**数据被应用**（#cn-level == mock 的 quadrant_label），不要等"4 格出现"——
            #    四格在首帧（数据未到时）就已经渲染出来了，等它会立刻返回、拿到空态
            #    （2026-09-18 实测踩到：报红其实是等待条件错）。
            try:
                page.wait_for_function(
                    "() => (document.querySelector('#cn-level') || {}).textContent === " + json.dumps(label),
                    timeout=20000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(600)
            d = page.evaluate(QM_JS)
            exp_idx = QM_CELL_ORDER.index(key)
            print(f"  [cn mock {key}] cells={d['cnCells']} now={d['cnNowCount']}:{d['cnNowText']!r} "
                  f"level={d['cnLevelText']!r} axes={d['cnAxes']}")
            check(d["cnCells"] == 4 and d["cnNowCount"] == 1 and d["cnNowText"] == label
                  and d["cnTexts"][exp_idx] == label and d["cnUnknown"] is False,
                  f"QM-3g [cn mock {key}] 恰好 1 格高亮、位于教材口径位置（下标 {exp_idx}）、"
                  "文案取自服务端 quadrant_label",
                  (d["cnCells"], d["cnNowCount"], d["cnNowText"], d["cnTexts"], d["cnUnknown"]))
            check(d["cnNowText"] == d["cnLevelText"],
                  f"QM-3h [cn mock {key}] 高亮格与 #cn-level 同源（同一 quadrant_label）",
                  (d["cnNowText"], d["cnLevelText"]))
            check(not cperrs, f"QM-3i [cn mock {key}] 无 pageerror", cperrs[:2])
        finally:
            ctx.close()

    # ---------- QM-1b / QM-2c / QM-2d / QM-3e：`/macro/cn` 实数据（数据驱动）----------
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        perrs: list[str] = []
        page.on("pageerror", lambda e: perrs.append(str(e)))
        page.goto(url + "macro/cn", wait_until="load")
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('#cn-matrix .rm-cell').length >= 4", timeout=40000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(800)
        d = page.evaluate(QM_JS)
        print(f"  [cn] cells={d['cnCells']} texts={d['cnTexts']} quadrant={d['cnQuadrant']!r} "
              f"now={d['cnNowCount']}:{d['cnNowText']!r} axes={d['cnAxes']}")
        check(d["cnExists"] and d["cnCells"] == 4,
              "QM-1b /macro/cn #cn-matrix 存在且恰好 4 格", (d["cnExists"], d["cnCells"]))
        check(sorted(d["cnTexts"]) == sorted(QM_CELL_LABELS.values()),
              "QM-2c /macro/cn 四格文案与服务端 QUADRANTS 一致（两页共享同一字典）", d["cnTexts"])
        cn_axes = [a for a in d["cnAxes"] if a]
        joined = "".join(cn_axes)
        check(len(cn_axes) == 4
              and not any(("↑" in a or "↓" in a) for a in cn_axes)
              and "上行" in joined and "回落" in joined
              and "扩张" in joined and "收缩" in joined,
              "QM-2d /macro/cn 轴标签为 上行/回落 + 扩张/收缩（**不用** ↑/↓：增长轴是 PMI 水平口径）",
              cn_axes)
        # 数据驱动（不假设上游一定可用）：有 quadrant 就必须 1 格且与 #cn-level **同源**；
        # 无 quadrant 就必须 0 高亮 + is-unknown —— 两个分支都各有要求，不是真空绿。
        if d["cnQuadrant"]:
            exp_idx = QM_CELL_ORDER.index(d["cnQuadrant"])
            check(d["cnNowCount"] == 1 and d["cnTexts"][exp_idx] == d["cnNowText"]
                  and d["cnNowText"] == d["cnLevelText"] and d["cnUnknown"] is False,
                  "QM-3e 有 quadrant 时恰好 1 格高亮、位置正确且与 #cn-level 同源（数据驱动）",
                  (d["cnQuadrant"], d["cnNowCount"], d["cnNowText"], d["cnLevelText"], d["cnTexts"]))
        else:
            check(d["cnNowCount"] == 0 and d["cnUnknown"] is True,
                  "QM-3f 无 quadrant（上游不可用）时 0 高亮 + is-unknown（不假高亮）",
                  (d["cnNowCount"], d["cnUnknown"]))
        check(not perrs, "QM-4d /macro/cn 无 pageerror", perrs[:2])
    finally:
        ctx.close()


def _na_open(browser, url: str, handler, *, timeout_ms=None, viewport=(1440, 900)):
    """开一个 /macro 独立 context 并挂 mock。返回 (ctx, page, console_msgs, pageerrors)。

    handler(pattern → route) 由调用方给：可 fulfill(200/json) / fulfill(500) / **不结算**（悬挂）。
    """
    ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]},
                              device_scale_factor=1)
    page = ctx.new_page()
    msgs: list[tuple] = []
    pageerrors: list[str] = []
    page.on("console", lambda m: msgs.append((m.type, m.text)))
    page.on("pageerror", lambda e: pageerrors.append(str(e)))
    if timeout_ms is not None:
        page.add_init_script("window.__macroTimeoutMs = %d;" % timeout_ms)
    page.route("**/api/macro", lambda r: handler("macro", r))
    page.route("**/api/econ", lambda r: handler("econ", r))
    return ctx, page, msgs, pageerrors


def assert_macro_states(browser, url: str) -> None:
    """NA-1~NA-11 `/macro` 四态 + 因子 chip + Score 语义色 + 影响资产方向（macro-page-frontend-refactor）。

    NA-1 loading（悬挂 + 短超时）：静态骨架屏在场
    NA-2 **超时 → failed**（R1 核心护栏：不得停在骨架屏；上游 403 常态下这决定体验比现状好还是更糟）
    NA-3 500 → failed + 重试真的重发请求 + 用满上限后禁用（R5：失败路径不得产生 console.error）
    NA-4 成功 → 骨架清零（N2 验收）、fail-bar 收起
    NA-5 因子 chip（N3）：每行 ≥1 chip、有素材的资产渲染 `<img>` 且 naturalWidth>0、无破图
    NA-6 `#mac-factors` slack ≤ 20（M-6 上限；N3 加内容后须实测并记录前后值）
    NA-7 `#regime-score` 颜色**由 level 同源推导**（N4）：含两组"score100 与 level 矛盾"的反向护栏
    NA-8 `/macro/cn` 零影响（R3）：新类名/新元素都不出现，共享 `.mac-factor-row` 网格未被改
    NA-10 双主题截图留档（V6）
    NA-11 影响资产方向与后端 `inverse` 语义同源（2026-09-17 用户追问后修复）
    """
    print("\n--- NA 宏观页四态 / 因子 chip / Score 语义色（macro-page-frontend-refactor）---")

    # ---------- NA-1 / NA-2：悬挂 → loading → 超时切 failed ----------
    held: list = []

    def hanging(_which, route):
        held.append(route)          # ★ 不结算 → 请求悬挂，页面停在 loading

    ctx, page, msgs, pageerrors = _na_open(browser, url, hanging, timeout_ms=2000)
    try:
        page.goto(url + "macro", wait_until="load")
        page.wait_for_timeout(500)
        a1 = page.evaluate(NA_JS)
        page.screenshot(path=str(OUT_DIR / "shot-na-loading.png"), full_page=True)
        print(f"  [悬挂 t=0.5s] skel={a1['skeletons']} visible={a1['skelVisible']} "
              f"chart={a1['skelInChart']} blocks={a1['blocks']}")
        check(a1["hasHook"] and a1["skelVisible"] >= 8,
              "NA-1 loading 期静态骨架屏在场（可见 ≥8 个）", (a1["skeletons"], a1["skelVisible"]))
        check(a1["skelInChart"] >= 1, "NA-1b 主图区有自己的骨架屏（不改变容器高度）", a1["skelInChart"])
        check(a1["failBarShown"] is False and a1["failBarDisplay"] == "none",
              "NA-1c loading 期不显示失败条", (a1["failBarShown"], a1["failBarDisplay"]))
        check(a1["hasHook"] is True and not a1["blocks"],
              "NA-1d loading 期各块尚未结算（blocks 为空）", (a1["hasHook"], a1["blocks"]))

        page.wait_for_timeout(2700)          # 越过注入的 2s 客户端超时
        a2 = page.evaluate(NA_JS)
        page.screenshot(path=str(OUT_DIR / "shot-na-failed.png"), full_page=True)
        print(f"  [悬挂 t>超时] skel={a2['skeletons']} failBar={a2['failBarShown']}/{a2['failBarDisplay']} "
              f"blocks={sorted(set((a2['blocks'] or {}).values()))} retry={a2['retry']}")
        check(a1["skelVisible"] >= 8 and a2["skeletons"] == 0 and a2["skelVisible"] == 0
              and a2["skelInChart"] == 0,
              "NA-2 超时后骨架屏**全部**撤掉（不得永远停在骨架屏，R1）",
              (a1["skelVisible"], a2["skeletons"], a2["skelVisible"], a2["skelInChart"]))
        check(a2["failBarShown"] is True and a2["failBarDisplay"] == "flex",
              "NA-2b 超时 → 失败条出现（display 由 :not(.hidden) 承担）",
              (a2["failBarShown"], a2["failBarDisplay"], a2["failMsg"]))
        # ⚠️ 必须显式判 None：改动前页面没有 __macroState 钩子（blocks=None），
        #    `len(None)` 会直接把整组断言炸掉 —— 红跑要"报红"，不是"崩溃"。
        check(bool(a2["blocks"]) and len(a2["blocks"]) == 11
              and all(v == "failed" for v in a2["blocks"].values()),
              "NA-2c 两个取数源的所有块都结算为 failed（11 块）", a2["blocks"])
        check(a2["retry"] is not None and a2["retry"]["disabled"] is False,
              "NA-2d 失败态给可用的重试按钮", a2["retry"])
        check(a2["emptyCount"] >= 1 and a2["emptyFailed"] >= 1 and a2["econFailed"]
              and a2["factorsFailed"],
              "NA-2e 失败态沿用 .mac-empty（块级也追加 is-failed，类名/文案不换）",
              (a2["emptyCount"], a2["emptyFailed"], a2["econFailed"], a2["factorsFailed"]))
        # R5：超时是"有意的容错动作" → 只能 warn（否则撞 M-9b 的 console error = 0）
        # ⚠️ 必须带上"降级确实发生了"这个前置：改动前页面**没有** 2s 超时（写死 15s），
        #    此处若只判"无 error"会**真空变绿**（红跑实测过）。
        settled = bool(a2["blocks"]) and all(v == "failed" for v in a2["blocks"].values())
        our_err = [t for (ty, t) in msgs if ty == "error" and "[macro]" in t]
        check(settled and not our_err and not pageerrors,
              "NA-2f 超时降级路径只 warn 不 error（M-9b 护栏）",
              (settled, our_err[:2], pageerrors[:2]))
    finally:
        for r in held:            # 结算悬挂的 route：否则 context 关闭时 Playwright 会打一堆取消堆栈
            try:
                r.abort()
            except Exception:  # noqa: BLE001
                pass
        ctx.close()

    # ---------- NA-3：500 → failed + 重试真的重发 + 上限禁用 ----------
    hits: list = []

    def bad(_which, route):
        hits.append(route.request.url)
        route.fulfill(status=500, content_type="text/html", body="boom")

    ctx, page, msgs, pageerrors = _na_open(browser, url, bad)
    try:
        page.goto(url + "macro", wait_until="load")
        page.wait_for_timeout(1200)
        b1 = page.evaluate(NA_JS)
        n0 = len(hits)
        check(b1["failBarShown"] is True and bool(b1["blocks"])
              and all(v == "failed" for v in b1["blocks"].values()),
              "NA-3 上游 500 → 失败态（含默认 15s 超时之外的错误分支）", b1["blocks"])
        check(b1["retry"] is not None and not b1["retry"]["disabled"],
              "NA-3b 500 后重试按钮可用", b1["retry"])
        btns = []
        for i in range(3):
            # ⚠️ 容忍按钮不存在（改动前页面没有它）→ 返回 False 而不是抛异常，否则红跑会崩在整组中间
            page.evaluate(
                "() => { const b = document.getElementById('mac-retry');"
                " if (!b || b.disabled) return false; b.click(); return true; }")
            page.wait_for_timeout(500)
            st = page.evaluate(NA_JS)
            btns.append((len(hits), st["retryUsed"],
                         st["retry"]["disabled"] if st["retry"] else None))
        print(f"  [重试] 请求数/重试计数/禁用 -> {btns}")
        check(all(b[0] > n0 for b in btns), "NA-3c 点重试后**真的**再次发起请求", (n0, btns))
        check(btns[-1][1] == 3 and btns[-1][2] is True,
              "NA-3d 重试 3 次后按钮禁用（不无限打上游）", btns[-1])
        our_err = [t for (ty, t) in msgs if ty == "error" and "[macro]" in t]
        check(not our_err and not pageerrors,
              "NA-3e 失败/重试路径只 warn 不 error（M-9b 护栏）", (our_err[:2], pageerrors[:2]))
    finally:
        ctx.close()

    # ---------- NA-4 / NA-5 / NA-6：成功 → 骨架清零 + chip + slack ----------
    def ok(which, route):
        payload = NA_OK_PAYLOAD if which == "macro" else NA_ECON
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload, ensure_ascii=False))

    ctx, page, msgs, pageerrors = _na_open(browser, url, ok)
    try:
        page.goto(url + "macro", wait_until="load")
        page.wait_for_timeout(1200)
        d = page.evaluate(NA_JS)
        print(f"  [成功] skel={d['skeletons']} blocks={sorted(set((d['blocks'] or {}).values()))} "
              f"chips/行={d['chipsPerRow']} img/行={d['imgPerRow']} badges={d['badges']} "
              f"slack={d['factorsSlack']}px")
        check(d["skeletons"] == 0 and d["skelVisible"] == 0 and bool(d["blocks"])
              and all(v == "ok" for v in d["blocks"].values()),
              "NA-4 取数成功后全页骨架清零且各块结算为 ok（N2 验收；不留永久 shimmer）",
              (d["skeletons"], d["skelVisible"], sorted(set((d["blocks"] or {}).values()))))
        check(d["failBarShown"] is False and not d["emptyFailed"],
              "NA-4b 成功态不显示失败条、也不残留 is-failed",
              (d["failBarShown"], d["emptyFailed"]))

        check(d["rowCount"] == 4 and all(c >= 1 for c in d["chipsPerRow"]),
              "NA-5 每行因子都有资产 chip（≥1）", (d["rowCount"], d["chipsPerRow"]))
        check(len(d["badges"]) == d["rowCount"] and all(b for b in d["badges"]),
              "NA-5b 每行都带方向 Badge（受益/承压/中性）", d["badges"])
        check(d["imgSrc"] and all("/static/icons/" in s for s in d["imgSrc"]),
              "NA-5c 有素材的资产渲染既有 4 个 SVG 之一", d["imgSrc"])
        check(bool(d["imgSrc"]) and d["imgBroken"] == 0,
              "NA-5d 有图标且无破图（离线时 onerror 自移除）", (len(d["imgSrc"]), d["imgBroken"]))
        # 美元(dollar) / 利率(bond) / 商品→原油+能源(oil) 应出图标；风险偏好 → 纯文字 chip（无素材）
        # ⚠️ 下标访问前先判长度（行数为 0 时不炸整组）
        check(len(d["imgPerRow"]) == 4 and d["imgPerRow"][0] == 0 and d["imgPerRow"][1] >= 1
              and d["imgPerRow"][2] >= 1 and d["imgPerRow"][3] >= 1,
              "NA-5e 风险偏好行无素材→纯文字 chip；美元/利率/商品行有图标",
              d["imgPerRow"])
        check(d["factorsSlack"] is not None and d["factorsSlack"] <= 20,
              "NA-6 加 chip 后 #mac-factors 留白仍 ≤20px（M-6 上限；基线 12px）",
              d["factorsSlack"])

        # --- NA-5f/g：方向 Badge 与资产 chip 的**配对不可拆散**（2026-09-17 用户反馈「又受益又承压」）---
        check(d["chipsOutsideGrp"] == 0,
              "NA-5f 每个资产 chip 都在 .fr-grp 组内（不裸平铺）", d["chipsOutsideGrp"])
        check(d["badgeNotAfterChip"] == 0 and d["grpCount"] >= d["rowCount"],
              "NA-5g 组内**资产在前、方向在后**（防「受益 X 承压」夹心读法）",
              (d["badgeNotAfterChip"], d["grpCount"], d["rowCount"]))
    finally:
        ctx.close()

    # ---------- NA-5h：中性因子行（impact=0）不得把「中性」写两遍 ----------
    flat_payload = _na_payload(level="neutral", score100=50.0, impacts=(0, 0, 0, 0))
    ctx, page, msgs, pageerrors = _na_open(
        browser, url,
        lambda which, route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(flat_payload if which == "macro" else NA_ECON, ensure_ascii=False)))
    try:
        page.goto(url + "macro", wait_until="load")
        page.wait_for_timeout(1000)
        f = page.evaluate(NA_JS)
        print(f"  [全中性因子] rows={f['rowCount']} chips/行={f['chipsPerRow']} "
              f"badges={f['badges']} neutralDup={f['neutralDup']} "
              f"chipsOutsideGrp={f['chipsOutsideGrp']}")
        check(f["rowCount"] == 4 and all(c >= 1 for c in f["chipsPerRow"]),
              "NA-5h 中性因子行仍各带 ≥1 个 chip（PRD 验收：每行 chip ≥1）", f["chipsPerRow"])
        check(f["neutralDup"] == 0,
              "NA-5h2 中性行不把「中性」写两遍（badge 一个 + 文案里一个）",
              (f["neutralDup"], f["badges"]))
        check(f["chipsOutsideGrp"] == 0, "NA-5h3 中性行的 chip 同样在组内", f["chipsOutsideGrp"])
    finally:
        ctx.close()

    # ---------- NA-7：Score 语义色与 level 同源（含矛盾输入的反向护栏）----------
    # (level, score100, 期望 class, 期望色键, 说明)
    cases = [
        ("risk_on", 68.8, "up", "green", "正常一致：Risk-On 且 score100>50"),
        ("risk_off", 80.0, "down", "red", "★反向护栏：score100=80>50 但 level=risk_off → 必须**红**"),
        ("risk_on", 35.0, "up", "green", "★反向护栏：score100=35<50 但 level=risk_on → 必须**绿**"),
        ("neutral", 50.0, "flat", "muted", "中性不得染绿/染红"),
    ]
    for (lvl, sc100, want_cls, want_color, note) in cases:
        payload = _na_payload(level=lvl, score100=sc100)
        ctx, page, msgs, pageerrors = _na_open(
            browser, url,
            lambda which, route, _p=payload: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_p if which == "macro" else NA_ECON, ensure_ascii=False)))
        try:
            page.goto(url + "macro", wait_until="load")
            page.wait_for_timeout(1000)
            d = page.evaluate(NA_JS)
            got_cls = (d["score"] or {}).get("cls", "")
            lv_cls = (d["level"] or {}).get("cls", "").split()[-1]
            # ① score 的 class 必须是 level 的**同源映射**（用需求表独立校验，不读 macro.js 的映射）
            # ② 实际渲染色必须等于该 class 对应的 token 色
            ok_pair = got_cls.split()[-1] == want_cls == NA_LEVEL_CLASS.get(lv_cls, "flat")
            ok_color = (d["score"] or {}).get("color") == d[want_color]
            if want_cls == "flat":
                ok_color = ok_color and (d["score"] or {}).get("color") not in (d["green"], d["red"])
            check(ok_pair and ok_color,
                  f"NA-7 {lvl}/score100={sc100} → score class={want_cls} 且色=--{want_color}（{note}）",
                  ((d["score"] or {}).get("cls"), (d["score"] or {}).get("color"), lv_cls),
                  (f"score-num {want_cls}", d[want_color]))
        finally:
            ctx.close()

    # ---------- NA-8：/macro/cn 零影响 ----------
    CN_NA_JS = r"""
    () => {
      const fac = document.querySelector('#cn-factors .mac-factor-row');
      return {
        skeletons: document.querySelectorAll('.skeleton').length,
        failBar: document.querySelectorAll('#mac-fail-bar').length,
        chips: document.querySelectorAll('.fr-chip').length,
        badges: document.querySelectorAll('.fr-badge').length,
        failed: document.querySelectorAll('.is-failed').length,
        emptyColor: (() => { const e = document.querySelector('#cn-econ .mac-empty, #cn-rate-list .mac-empty');
          return e ? getComputedStyle(e).color : null; })(),
        rowCols: fac ? getComputedStyle(fac).gridTemplateColumns.split(/\s+/).slice(0, 2) : null,
        scrollW: document.scrollingElement.scrollWidth, innerW: window.innerWidth,
      };
    }
    """
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    try:
        pg = ctx.new_page()
        pg.goto(url + "macro/cn", wait_until="load")
        pg.wait_for_timeout(9000)            # 中国页分组加载 ≈10s
        cn = pg.evaluate(CN_NA_JS)
        pg.screenshot(path=str(OUT_DIR / "shot-na-cn.png"), full_page=True)
        print(f"  [CN] skel={cn['skeletons']} chips={cn['chips']} badges={cn['badges']} "
              f"failed={cn['failed']} rowCols={cn['rowCols']}")
        check(cn["skeletons"] == 0 and cn["chips"] == 0 and cn["badges"] == 0
              and cn["failBar"] == 0 and cn["failed"] == 0,
              "NA-8 /macro/cn 零影响（新骨架/失败条/chip 都不出现在中国页）",
              (cn["skeletons"], cn["chips"], cn["badges"], cn["failBar"], cn["failed"]))
        check(cn["rowCols"] == ["72px", "70px"],
              "NA-8b 共享 .mac-factor-row 网格未被改（CN 页仍是 72px/70px）", cn["rowCols"])
        check(cn["scrollW"] == cn["innerW"], "NA-8c /macro/cn 无横向溢出",
              (cn["scrollW"], cn["innerW"]))
    finally:
        ctx.close()

    # ---------- NA-11：影响资产方向必须与后端 inverse 语义同源 ----------
    # 口径（`web/app.py:685-695` 的 `_band_score` docstring）：`inverse=True` 的维度
    #   **数值上行 = 风险偏好下行** ⇒ impact>0 表示**该变量下行**、impact<0 表示**上行**。
    #   「美元」「利率」两维都用 inverse；「商品」不用（impact>0 = 油价上行）。
    # ⚠️ 2026-09-17 实测缺陷：`FACTOR_ASSETS` 的 美元/利率 两支按"变量上行 = pos"写 ⇒ **整体反了**，
    #    表现为「利率 ↓偏空（= 收益率上行）」那行却写「黄金 受益」，而同一张截图里黄金就是 −0.36%。
    # ⚠️ 断言只用"页面渲染出的资产+方向配对"，不读 `macro.js` 的映射表（避免拿实现自证）。
    for impacts, note, expect in NA_ASSET_CASES:
        payload = _na_payload(level="neutral", score100=50.0, impacts=impacts)
        ctx, page, msgs, pageerrors = _na_open(
            browser, url,
            lambda which, route, _p=payload: route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_p if which == "macro" else NA_ECON, ensure_ascii=False)))
        try:
            page.goto(url + "macro", wait_until="load")
            page.wait_for_timeout(1000)
            g = page.evaluate(NA_JS)
            pairs = g["assetPairs"] or {}
            print(f"  [NA-11 {note}] 配对 = {pairs}")
            for (row, asset, direction, must) in expect:
                # ⚠️ 变量名**不能叫 `ok`** —— 那是本函数后面 NA-9 用的 route handler 函数名，
                #    覆盖成 bool 后 `_na_open(..., ok)` 会让 handler 不可调用，整组**崩溃**
                #    （2026-09-17 实测踩到：表现为 `Page.wait_for_timeout: 'bool' object is not callable`）。
                hit = _has_pair(pairs.get(row), asset, direction)
                check((hit if must else not hit),
                      f"NA-11 {note} → {row} 行{'必须' if must else '不得'}出现「{asset} {direction}」",
                      (row, pairs.get(row)))
            # 覆盖度护栏：两个维度必须都真的渲染出来了（否则上面全是真空绿）
            check(all(bool(pairs.get(r)) for r in ("美元", "利率")),
                  f"NA-11 覆盖度：{note} 下 美元/利率 两行均有配对（防空集假绿）",
                  {k: v for k, v in pairs.items() if k in ("美元", "利率")})
        finally:
            ctx.close()

    # ---------- NA-9：双主题截图留档（V6） ----------
    for theme in ("light", "dark"):
        ctx, page, msgs, pageerrors = _na_open(browser, url, ok)
        try:
            page.add_init_script("try { localStorage.setItem('mp-theme', '%s'); } catch (e) {}" % theme)
            page.goto(url + "macro", wait_until="load")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT_DIR / f"shot-na-macro-{theme}.png"), full_page=True)
            dt = page.evaluate(NA_JS)
            check(dt["skeletons"] == 0 and bool(dt["imgSrc"]),
                  f"NA-9 {theme} 主题下四态/chip 同样成立（截图留档）",
                  (dt["skeletons"], len(dt["imgSrc"])))
        finally:
            ctx.close()


# —— UX 前端体验走查整改（2026-09-17，任务档 tasks/2026-09-17-frontend-ux-audit-fixes）——
# F1 浅色对比度 / F2 刷新反馈 + 首页失败条 / F3 主题初始化同源 / F4 抽屉滚动锁定 + 焦点管理
# ⚠️ 判读必须以完成标记为准（本组的探针会打印 UX-COMPLETE；中途崩溃 = 结果无效）。

HOME_UX_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const cs = (e) => getComputedStyle(e);
  const varColor = (name) => {
    const t = document.createElement('div');
    t.style.color = 'var(' + name + ')';
    t.style.position = 'absolute'; t.style.visibility = 'hidden';
    document.body.appendChild(t);
    const c = cs(t).color;
    t.remove();
    return c;
  };
  const bgOf = (el) => {           // 沿祖先找第一个非透明背景
    let e = el;
    while (e) {
      const c = cs(e).backgroundColor;
      if (c && c !== 'transparent' && !/rgba\(\s*\d+,\s*\d+,\s*\d+,\s*0\s*\)/.test(c)) return c;
      e = e.parentElement;
    }
    return 'rgb(255, 255, 255)';
  };
  const chan = (c) => c.match(/[\d.]+/g).slice(0, 3).map(Number);
  const lum = (rgb) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2]);
  };
  const contrast = (fg, bg) => {
    const a = lum(chan(fg)), b = lum(chan(bg));
    const hi = Math.max(a, b), lo = Math.min(a, b);
    return (hi + 0.05) / (lo + 0.05);
  };
  const msTime = q('.ms-time');
  const bar = q('#home-fail-bar');
  return {
    theme: document.documentElement.getAttribute('data-theme'),
    mutedRgb: varColor('--text-muted'),
    ixicRgb: varColor('--c-ixic'),
    bodyBg: bgOf(document.body),
    cardBg: bgOf(q('.card') || document.body),
    msTimeFont: msTime ? parseFloat(cs(msTime).fontSize) : null,
    failBarShown: bar ? !bar.classList.contains('hidden') : null,
    failMsg: (q('#home-fail-msg') || {}).textContent || null,
    failBarLive: bar ? bar.getAttribute('aria-live') : null,
    retry: (() => { const b = q('#home-retry'); return b ? { disabled: !!b.disabled } : null; })(),
    refreshDisabled: (() => { const b = q('#refresh-btn'); return b ? !!b.disabled : null; })(),
    chartAlive: !!(window.Chart && window.Chart.getChart && window.Chart.getChart(q('#chart-main'))),
    metaLive: q('#trend-meta') ? q('#trend-meta').getAttribute('aria-live') : null,
    drawerOpen: document.body.classList.contains('nav-open'),
    bodyOverflow: cs(document.body).overflow,
    // drawer-opaque-fixes（2026-09-17）：≤768 抽屉必须为实底 --bg-elevated（覆盖层不可透）
    sidebarBg: q('#sidebar') ? cs(q('#sidebar')).backgroundColor : null,
    elevatedBg: (() => { const t = document.createElement('div');
        t.style.backgroundColor = 'var(--bg-elevated)'; t.style.position = 'absolute';
        t.style.visibility = 'hidden'; document.body.appendChild(t);
        const c = cs(t).backgroundColor; t.remove(); return c; })(),
    activeInSidebar: (() => {
      const a = document.activeElement, sb = q('#sidebar');
      return !!(a && sb && sb.contains(a));
    })(),
    activeIsMenuToggle: document.activeElement === q('#menu-toggle'),
  };
}
"""


def _contrast(fg_rgb: str, bg_rgb: str) -> float:
    """WCAG 对比度（输入为 'rgb(r, g, b)' 字符串）。"""
    def chan(c: str):
        return [float(x) for x in c.replace('rgb(', '').replace('rgba', 'rgb(').replace(')', '')
                .split(',')[:3]]
    def lum(rgb):
        def f(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])
    a, b = lum(chan(fg_rgb)), lum(chan(bg_rgb))
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def assert_home_ux(browser, url: str) -> None:
    """UX-1~UX-5 前端体验走查整改（F1–F4，2026-09-17）。

    UX-1 浅色/深色对比度（F1）：--text-muted 与 --c-ixic（被 renderTrendMeta 当文字色用）≥ 4.5:1
    UX-2 主题初始化（F3）：**隔离 app.js**（route abort）后，头部内联脚本必须自己落对 light/dark
    UX-3 刷新反馈（F2）：history 失败 ⇒ 失败条 + 旧图仍在 + 刷新/重试按钮禁用；恢复 + 重试 ⇒ 失败条消失
    UX-4 抽屉（F4）：开抽屉 ⇒ body 滚动锁定 + 焦点移入侧栏；Escape 关 ⇒ 焦点归还 #menu-toggle
    UX-5 .ms-time 字号 ≥ 11px（走查项：10px 过小）
    """
    print("\n--- UX 前端体验走查整改（对比度 / 刷新反馈 / 主题初始化 / 抽屉）---")

    # ---------- UX-1 对比度（两主题）----------
    for theme in ("light", "dark"):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        try:
            pg = ctx.new_page()
            pg.add_init_script("try { localStorage.setItem('mp-theme', '%s'); } catch (e) {}" % theme)
            pg.goto(url, wait_until="load")
            pg.wait_for_timeout(1200)
            d = pg.evaluate(HOME_UX_JS)
            c_muted = _contrast(d["mutedRgb"], d["bodyBg"])
            print(f"  [{theme}] muted={d['mutedRgb']} bg={d['bodyBg']} → {c_muted:.2f}:1 | "
                  f"ixic={d['ixicRgb']} | ms-time={d['msTimeFont']}px")
            check(c_muted >= 4.5,
                  f"UX-1 {theme} --text-muted 对页底对比度 ≥4.5（走查报告：light 2.54:1）", round(c_muted, 2))
            if theme == "light":
                c_ixic = _contrast(d["ixicRgb"], d["cardBg"])
                print(f"  [light] --c-ixic 对卡片底 → {c_ixic:.2f}:1")
                check(c_ixic >= 4.5,
                      "UX-1b light --c-ixic（被 .chart-meta 当文字色用）对比度 ≥4.5（原 #13C2C2 ≈2.21:1）",
                      round(c_ixic, 2))
            check(d["msTimeFont"] is not None and d["msTimeFont"] >= 11,
                  "UX-5 .ms-time 字号 ≥11px（走查报告：10px 过小）", d["msTimeFont"])
            # drawer-opaque-fixes：修复只落在 ≤768 媒体查询内 ⇒ 桌面（1440）侧栏必须仍是透明的
            check(d["sidebarBg"] in ("rgba(0, 0, 0, 0)", "transparent"),
                  "UX-1c 桌面端 #sidebar 保持透明（G-6 不回退；透明只允许出现在 >768）",
                  d["sidebarBg"])
        finally:
            ctx.close()

    # ---------- UX-2 主题初始化（隔离 app.js，专测头部内联脚本）----------
    for theme in ("dark", "light"):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        try:
            pg = ctx.new_page()
            pg.add_init_script("try { localStorage.setItem('mp-theme', '%s'); } catch (e) {}" % theme)
            # 隔离 app.js：页面层主题只可能来自 <head> 的内联脚本（FOUC 的唯一来源）
            pg.route("**/static/app.js*", lambda r: r.abort())
            pg.goto(url, wait_until="domcontentloaded")
            got = pg.evaluate("() => document.documentElement.getAttribute('data-theme')")
            check(got == theme,
                  f"UX-2 {theme}：隔离 app.js 后头部内联脚本仍落对主题（P2-③：旧实现只处理 light）",
                  got)
        finally:
            ctx.close()

    # ---------- UX-3 刷新反馈（history 失败 ≠ 静默）----------
    held: list = []
    hang = {"on": False}

    def history_route(route):
        if hang["on"]:
            held.append(route)            # 悬挂：refresh 停在 in-flight
        else:
            route.continue_()

    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    try:
        pg = ctx.new_page()
        pg.route("**/api/history*", history_route)
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(2500)          # 初始 refresh 正常通过（有数据可画）
        d0 = pg.evaluate(HOME_UX_JS)
        check(d0["chartAlive"] is True and d0["failBarShown"] is False,
              "UX-3a 初始加载：图表在、无失败条", (d0["chartAlive"], d0["failBarShown"]))

        hang["on"] = True
        pg.evaluate("() => document.getElementById('refresh-btn').click()")
        pg.wait_for_timeout(400)
        d1 = pg.evaluate(HOME_UX_JS)
        print(f"  [悬挂] refreshDisabled={d1['refreshDisabled']} failBar={d1['failBarShown']}")
        check(d1["refreshDisabled"] is True,
              "UX-3b 刷新期间刷新按钮禁用（P1-②：无 loading 反馈）", d1["refreshDisabled"])
        check(d1["failBarShown"] is False,
              "UX-3c in-flight 期不误报失败", d1["failBarShown"])

        for r in held:                     # 放行失败：fetch reject → 失败态
            try:
                r.abort()
            except Exception:              # noqa: BLE001
                pass
        pg.wait_for_timeout(500)
        d2 = pg.evaluate(HOME_UX_JS)
        print(f"  [失败] failBar={d2['failBarShown']} msg={d2['failMsg']!r} "
              f"chartAlive={d2['chartAlive']} live={d2['failBarLive']}")
        check(d2["failBarShown"] is True and "趋势数据" in (d2["failMsg"] or ""),
              "UX-3d history 失败 → 失败条出现（不再静默）", (d2["failBarShown"], d2["failMsg"]))
        check(d2["chartAlive"] is True,
              "UX-3e 失败后**旧图仍在**（保留离线看旧数据的既有行为）", d2["chartAlive"])
        check(d2["failBarLive"] == "polite",
              "UX-3f 失败条 aria-live=polite（刷数据不是紧急事件，不用 role=alert）", d2["failBarLive"])
        check(d2["refreshDisabled"] is False and (d2["retry"] or {}).get("disabled") is False,
              "UX-3g 失败态下刷新/重试按钮恢复可用", (d2["refreshDisabled"], d2["retry"]))

        hang["on"] = False                 # 恢复路由
        # ⚠️ 容忍按钮不存在（改动前首页没有它）→ 否则红跑会崩在整组中间（2026-09-17 实测）
        pg.evaluate("() => { const b = document.getElementById('home-retry'); if (b) b.click(); }")
        # /api/history 实测 ~2.5s（固定 1500ms 会误判"重试无效"）→ 等失败条真的消失，超时再取态
        try:
            pg.wait_for_function(
                "() => { const b = document.getElementById('home-fail-bar');"
                " return b && b.classList.contains('hidden'); }", timeout=9000)
        except Exception:                  # noqa: BLE001
            pass                           # 超时就按当前态取值判红（不崩）
        pg.wait_for_timeout(300)
        d3 = pg.evaluate(HOME_UX_JS)
        check(d3["failBarShown"] is False and d3["chartAlive"] is True,
              "UX-3h 恢复后重试 → 失败条消失、图表在", (d3["failBarShown"], d3["chartAlive"]))
    finally:
        ctx.close()

    # ---------- UX-4 抽屉滚动锁定 + 焦点管理（375 视口）----------
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, device_scale_factor=1)
    try:
        pg = ctx.new_page()
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(1200)
        pg.evaluate("() => document.getElementById('menu-toggle').click()")
        pg.wait_for_timeout(600)
        d = pg.evaluate(HOME_UX_JS)
        print(f"  [抽屉开] overflow={d['bodyOverflow']} activeInSidebar={d['activeInSidebar']} "
              f"drawerOpen={d['drawerOpen']}")
        check(d["drawerOpen"] is True and d["bodyOverflow"] == "hidden",
              "UX-4a 抽屉打开 -> body 滚动锁定（P2-④：背景仍可滚动）",
              (d["drawerOpen"], d["bodyOverflow"]))
        check(d["activeInSidebar"] is True,
              "UX-4b 抽屉打开 -> 焦点移入侧栏（首个可聚焦项）", d["activeInSidebar"])
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        d2 = pg.evaluate(HOME_UX_JS)
        print(f"  [Escape 关] overflow={d2['bodyOverflow']} activeIsMenuToggle={d2['activeIsMenuToggle']}")
        check(d2["drawerOpen"] is False and d2["bodyOverflow"] != "hidden",
              "UX-4c Escape 关闭抽屉并解除滚动锁定", (d2["drawerOpen"], d2["bodyOverflow"]))
        check(d2["activeIsMenuToggle"] is True,
              "UX-4d 关闭后焦点归还触发按钮 #menu-toggle", d2["activeIsMenuToggle"])
        # UX-4e（drawer-opaque-fixes）：≤768 侧栏是覆盖层 ⇒ 必须实底 --bg-elevated（开/关都一样）
        check(d2["sidebarBg"] == d2["elevatedBg"] and d2["elevatedBg"] is not None,
              "UX-4e 抽屉为实底 --bg-elevated（覆盖层不可透；修复前为 rgba(0,0,0,0)）",
              (d2["sidebarBg"], d2["elevatedBg"]))
    finally:
        ctx.close()



# —— PW 产线走查整改（2026-09-17，任务档 tasks/2026-09-17-production-walkthrough-fixes）——
# G1 告警卡时间锚点 / G2 相关性空态文案 / G3 自选表头语义 / G4 趋势卡 loading-empty-failed 三态

PW_ALERT_FIXTURE = [{
    "symbol": "VIX", "date": "2026-09-11", "level": "WARN", "type": "回落", "state": "Neutral 中性",
    "current": 15.84, "last": 17.84, "change_pct": -11.21, "threshold": 10,
    "suggestion": "mock 建议", "report": "mock 报告",
}]

PW_LATEST_EMPTY = {            # correlation 为空 ⇒ 走 G2 的空态文案
    "date": "2026-09-16",
    "sector_heat": {"as_of": "2026-09-16", "items": []},
    "us_sector_heat": {"as_of": "2026-09-16", "items": []},
    "correlation": [],
}

PW_LATEST_HAS = json.loads(json.dumps(PW_LATEST_EMPTY))
PW_LATEST_HAS["correlation"] = [{"pair": "标普500 ↔ 纳斯达克", "r": 0.72, "n": 30}]

PW_HISTORY_EMPTY = {"dates": [], "series": []}   # G4 的 empty 分支

PW_HISTORY_OK = {              # G4 的 ok 分支（GROUPS[0].keys = gspc/ixic）
    "dates": ["2026-09-14", "2026-09-15", "2026-09-16"],
    "series": [{"key": "gspc", "label": "标普500", "raw": [100.0, 101.0, 102.0], "change_7d": 2.0}],
}

PW_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const alertText = [...document.querySelectorAll('.alert-card .alert-row')]
    .map((e) => e.textContent.trim());
  const wrap = q('#chart-main-wrap');
  return {
    alertText: alertText,
    relNote: (q('#market-relation .ph-note') || {}).textContent || null,
    relTitle: (q('#market-relation .ph-note') || {}).getAttribute
        ? q('#market-relation .ph-note').getAttribute('title') : null,
    pillCount: document.querySelectorAll('#market-relation .pill').length,
    icoLabel: (() => { const t = q('#watchlist-section thead th.col-ico');
        return t ? t.getAttribute('aria-label') : null; })(),
    barLabel: (() => { const t = q('#watchlist-section thead th.col-bar');
        return t ? t.getAttribute('aria-label') : null; })(),
    colspan: (() => { const td = q('#watchlist-body td[colspan]');
        return td ? td.getAttribute('colspan') : null; })(),
    skelShown: (() => { const s = q('#home-chart-skel'); return s ? !s.classList.contains('hidden') : null; })(),
    wrapH: wrap ? Math.round(wrap.getBoundingClientRect().height) : null,
    emptyText: (q('#chart-main-empty') || {}).textContent || null,
    emptyHidden: (q('#chart-main-empty') || {}).classList
        ? q('#chart-main-empty').classList.contains('hidden') : null,
    chartAlive: !!(window.Chart && window.Chart.getChart && window.Chart.getChart(q('#chart-main'))),
    failBarShown: (() => { const b = q('#home-fail-bar'); return b ? !b.classList.contains('hidden') : null; })(),
  };
}
"""


def assert_walkthrough(browser, url: str) -> None:
    """PW-1~PW-4 产线走查整改（G1 告警时间锚点 / G2 相关性文案 / G3 表头语义 / G4 趋势三态）。

    ⚠️ 全部用 mock 夹具（确定性；不为上游红项造数 —— mock 只存在于验收脚本）。
    """
    print("\n--- PW 产线走查整改（告警锚点 / 相关性文案 / 表头语义 / 趋势三态）---")

    # ---------- PW-1 / PW-2 / PW-3：mock /api/alerts + /api/latest ----------
    for case, latest in (("empty", PW_LATEST_EMPTY), ("has", PW_LATEST_HAS)):
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        try:
            pg = ctx.new_page()
            pg.route("**/api/alerts", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(PW_ALERT_FIXTURE, ensure_ascii=False)))
            pg.route("**/api/latest", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(latest, ensure_ascii=False)))
            pg.route("**/api/history*", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(PW_HISTORY_OK, ensure_ascii=False)))
            pg.goto(url, wait_until="load")
            pg.wait_for_timeout(1200)
            d = pg.evaluate(PW_JS)
            joined = " ".join(d["alertText"])
            # G1：措辞锚定告警日（日期由卡片头部承载 —— 实测带日期的行会折行、撞 B-12 护栏，
            #     见 journal §4.3）。断言：① 行内出现「告警日收盘：」且不再有「当前值：」；
            #     ② 头部的告警日期仍在（时间锚点由头部承载）。
            check(("告警日收盘：" in joined) and ("当前值：" not in joined),
                  f"PW-1 [{case}] 告警行措辞锚定告警日、不再出现「当前值：」", d["alertText"])
            # G2：空态文案 + 解释（title）；有数据时 pills 正常（不得被新文案分支误伤）
            if case == "empty":
                check("均低于 0.5" in (d["relNote"] or "") and d["relTitle"],
                      "PW-2 [empty] 相关性空态文案改为可读表述且带解释（title）",
                      (d["relNote"], d["relTitle"]))
                check(d["pillCount"] == 0, "PW-2 [empty] 不渲染 pills", d["pillCount"])
            else:
                check(d["pillCount"] >= 1 and d["relNote"] is None,
                      "PW-2 [has] 有显著对时 pills 正常列出（新文案分支不误伤）",
                      (d["pillCount"], d["relNote"]))
            # PW-1b：时间锚点由卡片头部承载（alert-head 内必须有告警日期）
            head_date = pg.evaluate(
                "() => { const h = document.querySelector('.alert-card .alert-head');"
                " return h ? h.textContent : null; }") or ""
            check("2026-09-11" in head_date,
                  f"PW-1b [{case}] 告警日期在卡片头部（时间锚点）", head_date)
            # G3：表头语义 + colspan 契约不变
            check(d["icoLabel"] == "标记" and d["barLabel"] == "涨跌幅分布",
                  f"PW-3 [{case}] 空表头补 aria-label（标记 / 涨跌幅分布）",
                  (d["icoLabel"], d["barLabel"]))
            # ⚠️ colspan 是"模板骨架"契约：数据到达后骨架被真实行替换，运行时 DOM 里没有
            #    （运行时断言会恒红）⇒ 改为对模板源的静态断言（P-6b 同款手法）
            tpl_src = (Path(__file__).resolve().parents[2] / "web" / "templates" / "index.html").read_text(encoding="utf-8")
            check(tpl_src.count('colspan="5"') >= 2
                  and 'th class="col-ico" aria-label="标记"' in tpl_src,
                  f"PW-3b [{case}] 模板骨架 colspan=5 契约不变 + 空表头标注在位（源级断言）",
                  (tpl_src.count('colspan="5"'), 'th class="col-ico" aria-label="标记"' in tpl_src))
        finally:
            ctx.close()

    # ---------- PW-4：趋势卡三态（loading / failed / empty / ok）----------
    held: list = []
    hang = {"on": False}

    mode = {"empty": False}
    def history_route(route):
        if hang["on"]:
            held.append(route)
            return
        body = PW_HISTORY_EMPTY if mode["empty"] else PW_HISTORY_OK
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(body, ensure_ascii=False))

    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    try:
        pg = ctx.new_page()
        pg.route("**/api/history*", history_route)
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(1200)
        d0 = pg.evaluate(PW_JS)
        check(d0["chartAlive"] is True and d0["skelShown"] is False,
              "PW-4a ok：图表渲染、骨架已撤", (d0["chartAlive"], d0["skelShown"]))
        base_h = d0["wrapH"]

        # loading：悬挂 → 骨架在场、容器高度不变（R3：canvas 位图==显示尺寸护栏的前提）
        hang["on"] = True
        pg.evaluate("() => document.getElementById('refresh-btn').click()")
        pg.wait_for_timeout(400)
        d1 = pg.evaluate(PW_JS)
        print(f"  [loading] skel={d1['skelShown']} wrapH={d1['wrapH']}（基准 {base_h}）")
        check(d1["skelShown"] is True, "PW-4b loading 期趋势卡骨架在场", d1["skelShown"])
        check(d1["wrapH"] == base_h and base_h is not None,
              "PW-4c 骨架不改变 #chart-main-wrap 高度（clamp 护栏）", (base_h, d1["wrapH"]))

        # failed：abort → 失败条 + 骨架撤
        for r in held:
            try:
                r.abort()
            except Exception:      # noqa: BLE001
                pass
        pg.wait_for_timeout(500)
        d2 = pg.evaluate(PW_JS)
        check(d2["failBarShown"] is True and d2["skelShown"] is False,
              "PW-4d 失败：失败条出现且骨架撤走（不停在 loading）",
              (d2["failBarShown"], d2["skelShown"]))

        # empty：history 为空结构 → 「暂无趋势数据」而非报错样式
        hang["on"] = False
        mode["empty"] = True
        pg.evaluate("() => document.getElementById('refresh-btn').click()")
        try:
            pg.wait_for_function(
                "() => { const e = document.getElementById('chart-main-empty');"
                " return e && !e.classList.contains('hidden'); }", timeout=9000)
        except Exception:          # noqa: BLE001
            pass
        pg.wait_for_timeout(300)
        d3 = pg.evaluate(PW_JS)
        print(f"  [empty] emptyText={d3['emptyText']!r} skel={d3['skelShown']} "
              f"failBar={d3['failBarShown']}")
        check((d3["emptyText"] or "").find("暂无趋势数据") >= 0,
              "PW-4e empty：history 为空 → 「暂无趋势数据」（复用既有空态通道）", d3["emptyText"])
        check(d3["skelShown"] is False, "PW-4f empty 态骨架已撤", d3["skelShown"])
    finally:
        ctx.close()


# ============ TL 市场日历（/timeline，内部名 timeline / 事件时间线，2026-09-18）============
# 任务档 tasks/2026-09-18-event-timeline-page（plan v3 定稿）。
# 页面 = 官方发布日历（骨架）× 行情（影响）× 新闻（叙事）；事件与行情**并列展示**、不构成因果。
TL_KINDS = ("FOMC", "非农", "CPI", "PPI", "GDP", "PCE", "零售", "工业产出", "其他")
# ⚠️ 上面这份枚举是**刻意第二份**（与 src/econ_calendar.KINDS 同源）：枚举本身由
#    tests/test_econ_calendar.py 的归一化用例锁定；本脚本只负责"页面上不得出现枚举外的类型"。
TL_CAUSAL = ("因为", "导致", "利好", "利空", "由于")

TL_JS = r"""
() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const txt = document.body.innerText;
  const days = q('.tl-day').map((d) => ({
    date: d.dataset.date,
    kinds: [...d.querySelectorAll('.tl-ev')].map((e) => e.dataset.kind),
    fwd: (d.querySelector('.tl-fwd') || {}).innerText || '',
    causal: (d.innerText.match(/因为|导致|利好|利空|由于/g) || []),
    // 每条事件的**英文原文**（挂在 data-title-en 上；TL-10b 逐日对账，防中文化丢原文）
    titlesEn: [...d.querySelectorAll('.tl-ev .tl-title')].map((e) => e.getAttribute('data-title-en') || ''),
  }));
  return {
    modules: ['tl-upcoming', 'tl-past', 'tl-meta'].filter((id) => document.getElementById(id)).length,
    dayCount: days.length,
    days: days,
    evCount: q('.tl-ev').length,
    allKinds: [...new Set(q('.tl-kind').map((k) => k.textContent.trim()))],
    titles: q('.tl-ev .tl-title').map((e) => e.textContent.trim()),
    titlesEn: q('.tl-ev .tl-title').map((e) => e.getAttribute('data-title-en') || ''),
    cancelled: (txt.match(/CANCELLED/gi) || []).length,
    causalOutside: days.reduce((n, d) => n + d.causal.length, 0),
    honest: ['不构成因果', '第三方镜像', '至少'].filter((k) => txt.includes(k)).length,
    navCount: q('#sidebar .nav-item').length,
    active: (document.querySelector('#sidebar .nav-item.active span') || {}).textContent || null,
    srcCount: q('.tl-src li').length,
    newsCount: q('.tl-news').length,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}
"""


def _tl_fmt(v):
    """与 timeline.js 的 fmtPct 同口径（2 位小数；|v|<0.005 不写符号）。"""
    if v is None:
        return "待走满"
    s = "%.2f%%" % abs(v)
    if abs(v) < 0.005:
        return s
    return ("+" if v > 0 else "-") + s


def assert_timeline(browser, url: str) -> None:
    """TL-1~TL-9 市场日历（/timeline；2026-09-19 起用户可见名字为「市场日历」，
    接手 2026-09-12 起空着的同名占位项；内部命名仍是 timeline）。

    TL-1 页面 200 + 三块骨架齐全 + 至少有事件行
    TL-2 **独立口径**核对事件数：sqlite3 直查 db 的 distinct (date,kind) 窗口计数 == API stats == 页面 DOM
    TL-3 事件类型 ∈ 归一化枚举（防 §4.2 漏配把原始事件名漏到页面上），且 DOM 类型集 == API 类型集
    TL-4 无 CANCELLED（过滤生效；DOM 与 API 两侧都查）
    TL-5 同一天内 (date, kind) 不重复渲染
    TL-6 forward 为 null 时渲染「待走满」、**不得显示 0.00%**（逐格与 API 对打；合法四舍五入到 0 的除外）
    TL-7 无因果措辞（只查 .tl-day；页面同时必须写明三条诚实边界）
    TL-8 375/768/1280/1920 四视口无横向溢出
    TL-9 侧栏 12 项且本页 active
    """
    print("\n--- TL 市场日历（/timeline）---")
    import sqlite3

    # 前置容错：改动前的基线里 `/api/timeline` 与 `econ_events` 表都不存在 ——
    # 红跑必须**报红**而不是崩溃（pitfalls「红跑要报红而不是崩溃」）⇒ 降级成空壳继续，
    # 后续每条断言各自据实报红。
    api_err = None
    try:
        api = json.loads(urllib.request.urlopen(url + "api/timeline?days=90&future_days=30",
                                                timeout=30).read().decode("utf-8"))
    except Exception as exc:            # noqa: BLE001
        api_err = "{}: {}".format(type(exc).__name__, exc)
        api = {"as_of": "", "stats": {}, "past": [], "upcoming": [], "sources": [], "failed": []}
    check(api_err is None, "TL-0 /api/timeline 可取（本组其余断言的前提）", api_err)

    # ---------- TL-2 的独立口径：直接查 db（绕过 API 与 storage 代码路径）----------
    today = api.get("as_of") or ""
    d0 = _date_from_iso(today) if today else None
    past_from = (d0 - timedelta(days=90)).isoformat() if d0 else ""
    fut_to = (d0 + timedelta(days=30)).isoformat() if d0 else ""
    db = ROOT / "data" / "marketpulse.db"
    db_err = None
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute("SELECT DISTINCT date, kind FROM econ_events").fetchall()
        conn.close()
    except Exception as exc:            # noqa: BLE001
        db_err = "{}: {}".format(type(exc).__name__, exc)
        rows = []
    check(db_err is None, "TL-2c econ_events 表可查（独立核算前提）", db_err)
    uniq = {(d, k) for d, k in rows}
    exp_past = sum(1 for (d, _k) in uniq if past_from <= d < today)
    exp_up = sum(1 for (d, _k) in uniq if today <= d <= fut_to)
    print(f"  [db 独立核算] 全库 {len(uniq)} 条去重事件；窗口 past={exp_past} upcoming={exp_up}")
    stats = api.get("stats") or {}
    check((stats.get("past_events"), stats.get("upcoming_events")) == (exp_past, exp_up),
          "TL-2 API 事件数与 db 独立核算一致（不复用服务端代码路径）",
          (stats.get("past_events"), stats.get("upcoming_events"), exp_past, exp_up))

    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        perrs: list[str] = []
        page.on("pageerror", lambda e: perrs.append(str(e)))
        resp = page.goto(url + "timeline", wait_until="load")
        page.wait_for_timeout(1200)
        d = page.evaluate(TL_JS)
        print(f"  [page] modules={d['modules']} days={d['dayCount']} events={d['evCount']} "
              f"kinds={d['allKinds']} news={d['newsCount']} src={d['srcCount']}")

        # ---------- TL-1 ----------
        check(resp is not None and resp.status == 200 and d["modules"] == 3 and d["dayCount"] >= 1,
              "TL-1 /timeline 200 且三块骨架齐全、有事件行",
              (resp.status if resp else None, d["modules"], d["dayCount"]))

        # ---------- TL-2b：DOM 侧事件数 ----------
        dom_ev = d["evCount"]
        check(dom_ev >= 1 and dom_ev == exp_past + exp_up,
              "TL-2b 页面渲染的事件数 == db 独立核算的窗口事件数（前置 dom_ev>=1：空集相等不算过）",
              (dom_ev, exp_past + exp_up))

        # ---------- TL-3 ----------
        api_kinds = {e["kind"] for day in (api["past"] + api["upcoming"]) for e in day["events"]}
        bad = [k for k in (set(d["allKinds"]) | api_kinds) if k not in TL_KINDS]
        check(bool(api_kinds) and not bad and set(d["allKinds"]) == api_kinds,
              "TL-3 事件类型全部落在归一化枚举内，且页面与 API 类型集一致"
              "（前置 api_kinds 非空：两侧都空时集合相等无意义）", (bad, sorted(api_kinds)))

        # ---------- TL-4 ----------
        api_cancelled = [e["title"] for day in (api["past"] + api["upcoming"]) for e in day["events"]
                         if "CANCELLED" in (e["title"] or "").upper()]
        check(d["dayCount"] >= 1 and d["cancelled"] == 0 and not api_cancelled,
              "TL-4 无 CANCELLED 事件（STATUS 过滤生效；DOM + API 双侧查）",
              (d["cancelled"], api_cancelled[:2]))

        # ---------- TL-5 ----------
        dup = [day["date"] for day in d["days"] if len(day["kinds"]) != len(set(day["kinds"]))]
        check(len(d["days"]) >= 1 and not dup,
              "TL-5 同一天内 (date, kind) 不重复渲染（两源同事件已去重；前置有事件行）", dup[:3])

        # ---------- TL-6：逐日逐窗口与 API 对打 ----------
        mismatches, legit_zero = [], 0
        for day in api["past"]:
            dom = next((x for x in d["days"] if x["date"] == day["date"]), None)
            if dom is None:
                mismatches.append((day["date"], "DOM 缺该天"))
                continue
            for h in ("1", "3", "5", "10"):
                v = ((day.get("forward") or {}).get(h) or {}).get("gspc")
                want = _tl_fmt(v)
                if v is not None and abs(v) < 0.005:
                    legit_zero += 1
                if want not in dom["fwd"]:
                    mismatches.append((day["date"], h, v, want, dom["fwd"][:60]))
        zero_on_page = sum(x["fwd"].count("0.00%") for x in d["days"])
        check(bool(api["past"]) and not mismatches and zero_on_page <= legit_zero,
              "TL-6 forward 未走满渲染「待走满」、null 绝不显示 0.00%（逐格对打；"
              "页面上 0.00% 的个数不超过 API 里合法四舍五入到 0 的个数）",
              (mismatches[:3], zero_on_page, legit_zero))

        # ---------- TL-7 ----------
        check(d["causalOutside"] == 0 and d["honest"] == 3,
              "TL-7 事件区无因果措辞（仅在诚实边界声明里出现「不构成因果」），且三条边界齐全",
              (d["causalOutside"], d["honest"]))

        # ---------- TL-10：事件名必须中文化（用户 2026-09-19：「英文看不懂」）----------
        # 口径：**只翻译"结构"（类型 + 数据期 + 估计阶段），不翻译"内容"** —— 事件名由模板生成，
        #       原文（源站英文）保留在 payload 的 `title` 与 DOM 的 `data-title-en`（悬停可见）。
        # ⚠️ 新闻标题**不在此列**（那是检索原文，翻译即二次加工）。
        EN_SKELETON = re.compile(r"Release|Data\b|Estimate|Monthly|Report|Quarter|Outlays", re.I)
        CJK = re.compile(r"[\u4e00-\u9fff]")
        bad_api = [(d["date"], e.get("title_zh")) for d in (api["past"] + api["upcoming"])
                   for e in d["events"] if not (e.get("title_zh") or "") or not CJK.search(e["title_zh"])]
        bad_dom = [t for t in d["titles"] if not CJK.search(t) or EN_SKELETON.search(t)]
        check(not bad_api and not bad_dom,
              "TL-10 事件名已中文化（API 的 title_zh 非空且含中文；页面标题无英文骨架词）",
              (bad_api[:3], bad_dom[:3]))
        # TL-10b：DOM 的 data-title-en 必须等于 API 的 title（**原文不能丢**）
        api_title_by_date: dict = {}
        for day in list(api["past"]) + list(api["upcoming"]):
            api_title_by_date.setdefault(day["date"], []).extend(
                e["title"] for e in sorted(day["events"], key=lambda e: (e.get("time_et") or "99:99", e["kind"])))
        dom_title_by_date = {x["date"]: x["titlesEn"] for x in d["days"]}
        en_mismatch = [(dt, api_title_by_date.get(dt), dom) for dt, dom in dom_title_by_date.items()
                       if sorted(api_title_by_date.get(dt, [])) != sorted(dom)]
        check(not en_mismatch,
              "TL-10b 页面保留英文原文（DOM data-title-en == API title，未因中文化丢失原文）",
              en_mismatch[:2])

        # ---------- TL-9 ----------
        # ⚠️ 用户可见名字是「市场日历」（2026-09-19 接手同名占位项）；内部命名仍是 timeline
        check(d["navCount"] == 12 and d["active"] == "市场日历",
              "TL-9 侧栏 12 项且本页 active = 市场日历", (d["navCount"], d["active"]))
        check(resp is not None and resp.status == 200 and not perrs,
              "TL-9b /timeline 200 且无 pageerror（前置 200：404 页面上无报错不算过）",
              (resp.status if resp else None, perrs[:2]))
    finally:
        ctx.close()

    # ---------- TL-8：四视口无横向溢出 ----------
    for w, h in ((375, 812), (768, 1024), (1280, 900), (1920, 1080)):
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
        try:
            page = ctx.new_page()
            page.goto(url + "timeline", wait_until="load")
            page.wait_for_timeout(900)
            o = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
            days = page.evaluate("() => document.querySelectorAll('.tl-day').length")
            check(o == 0 and days >= 1, f"TL-8 {w} 档无横向溢出且有事件行", (o, days))
        finally:
            ctx.close()


# ============ EV 结果值层（/timeline 的 实际/预期/前值，2026-09-19）============
# 任务档 tasks/2026-09-19-timeline-event-values（plan 定稿，方案 A「骨架不动 + 值层 join」）。
#
# ⚠️ 断言分层（plan §7.2 把两层的判据写在一起了，实测只能这样落地）：
#    本组（浏览器侧）只能验**页面能看见的**：键透传、三方计数、真实数据、无 0/None 混淆、
#    未来文案、`unit` 缺失不加后缀、两态断点、失败降级后页面不崩。
#    "既有值不被清空（preserve）" 与 "failed 含 tradingview" 发生在**同步脚本侧**
#    （浏览器看不到 TV 请求）=> 由 pytest 锁：tests/test_econ_values.py（preserve / 只 UPDATE 不 INSERT /
#    全源失败返回空 / 同日多期次择优）。
# ⚠️ 断言标签**禁用 GBK 外字符**（`⇒` / `→` 会让本脚本在 cp936 控制台 UnicodeEncodeError 中途死掉）。
EV_KEYS = ("actual", "forecast", "previous", "unit", "importance",
           "value_source", "value_title", "value_fetched_at")

EV_JS = r"""
() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const rows = q('.tl-ev').map((e) => {
    const day = e.closest('.tl-day');
    const v = e.querySelector('.tl-val');
    return {
      date: day ? day.dataset.date : '',
      kind: e.dataset.kind,
      val: v ? v.innerText : '',
      mode: v ? (v.dataset.valMode || '') : '',
      valCount: e.querySelectorAll('.tl-val').length,
    };
  });
  return {
    rows: rows,
    valCount: q('.tl-val').length,
    evCount: q('.tl-ev').length,
    modes: [...new Set(q('.tl-val').map((v) => v.dataset.valMode || ''))],
    withValue: rows.filter((r) => r.val).length,
    honest: q('.tl-honest li').map((li) => li.innerText),
    src: q('.tl-src li').map((li) => li.innerText),
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    bodyTxt: document.body.innerText,
  };
}
"""


def _ev_mk_route(payload):
    """构造单参 route handler（pitfalls：handler 多于 1 个形参会被按 (route, request) 调用，静默出错）。"""
    def _route(route):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(payload, ensure_ascii=False))
    return _route


# ============ AUTH 访问控制（HTTP Basic Auth，2026-09-19）============
# 任务档 tasks/2026-09-19-web-basic-auth/（方案 A）。
#
# ⚠️ 分层：**本组另起一个带鉴权的服务实例**跑（D-4b），不去动 `main()` 起的那台 ——
#    `main()` 在起服前已注入 `MP_AUTH_DISABLED=1`（D-4a）⇒ 既有 700+ 条断言零改动、零新增失败，
#    （G8 教训：红色背景会淹没真回归）。鉴权行为本身由本组独立覆盖。
# ⚠️ 新建实例必须**显式清掉** `MP_AUTH_DISABLED`（父进程已注入，子进程会继承）。
AUTH_USER, AUTH_PASS = "mpdemo", "s3cret-pass-16"


def _http_status(url: str, user: str | None = None, pwd: str | None = None) -> tuple:
    """带/不带 Basic 凭据请求，返回 `(status, headers)`；4xx/5xx 也按正常返回（不抛）。"""
    import base64
    import urllib.error
    req = urllib.request.Request(url)
    if user is not None:
        raw = ("%s:%s" % (user, pwd or "")).encode("utf-8")
        req.add_header("Authorization", "Basic " + base64.b64encode(raw).decode())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {})


def assert_auth(browser) -> None:
    """AUTH-1~AUTH-5 访问控制。

    AUTH-1 无凭据 `GET /` → 401 且带 `WWW-Authenticate: Basic realm="MarketPulse"`
    AUTH-2 无凭据 `GET /api/watchlist` → 401（**直接验 P0 那个暴露自选股的端点**）
    AUTH-3 无凭据 `GET /healthz` → 200（🔴 R1：给 `/` 返 401 且 healthcheck 打 `/` = 部署重启循环）
    AUTH-4 错凭据 401 / 正确凭据 200
    AUTH-5 Playwright `new_context(http_credentials=...)` 打开 `/` → 渲染成功、console error 0
           （⚠️ 必须：这是 D-3「静态资源不豁免」唯一能被证伪的地方 —— 单测覆盖不到
             浏览器自动为同域后续请求带凭据的行为）
    """
    print("\n--- AUTH 访问控制（HTTP Basic Auth）---")
    port = free_port()
    url = "http://127.0.0.1:%d/" % port
    env = dict(os.environ)
    env["MP_AUTH_USER"] = AUTH_USER
    env["MP_AUTH_PASS"] = AUTH_PASS
    env.pop("MP_AUTH_DISABLED", None)       # 关键：父进程已注入 1，这里必须清掉
    proc = subprocess.Popen([str(PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
                            cwd=str(ROOT), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_ready(url + "healthz")
        print(f"  带鉴权实例就绪: {url}")

        code, hdrs = _http_status(url)
        check(code == 401 and (hdrs.get("www-authenticate") or "") == 'Basic realm="MarketPulse"',
              "AUTH-1 无凭据 GET / → 401 且带 WWW-Authenticate（缺该头浏览器不弹窗）",
              (code, hdrs.get("www-authenticate")))

        code2, _ = _http_status(url + "api/watchlist")
        check(code2 == 401, "AUTH-2 无凭据 GET /api/watchlist → 401（P0 端点本身）", code2)

        code3, _ = _http_status(url + "healthz")
        check(code3 == 200, "AUTH-3 无凭据 GET /healthz → 200（Railway healthcheck 必须通）", code3)

        code4, _ = _http_status(url, AUTH_USER, "wrong-pass")
        code5, _ = _http_status(url, AUTH_USER, AUTH_PASS)
        check(code4 == 401 and code5 == 200, "AUTH-4 错凭据 401 / 正确凭据 200", (code4, code5))

        # AUTH-5：浏览器带凭据（http_credentials 等价于原生 Basic 弹窗后浏览器记住的凭据）
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=1,
                                  http_credentials={"username": AUTH_USER, "password": AUTH_PASS})
        try:
            page = ctx.new_page()
            perrs: list[str] = []
            page.on("pageerror", lambda e: perrs.append(str(e)))
            cerrs: list[str] = []
            page.on("console", lambda m: cerrs.append(m.text) if m.type == "error" else None)
            resp = page.goto(url, wait_until="load")
            page.wait_for_timeout(1500)
            d = page.evaluate("""() => ({
              dash: !!document.querySelector('.dash'),
              cards: document.querySelectorAll('.card').length,
              nav: document.querySelectorAll('#sidebar .nav-item').length,
              overflow: document.documentElement.scrollWidth - window.innerWidth,
            })""")
            print(f"  [page] dash={d['dash']} cards={d['cards']} nav={d['nav']} overflow={d['overflow']}")
            check(resp is not None and resp.status == 200 and d["dash"] and d["cards"] >= 4
                  and d["nav"] == 12 and not perrs,
                  "AUTH-5 浏览器带凭据打开 / → 200 且渲染成功（页面 + 静态资源 + 后续请求都过了鉴权）",
                  (resp.status if resp else None, d, perrs[:2]))
            check(d["overflow"] == 0, "AUTH-5b 带凭据页面无横向溢出", d["overflow"])
            # 「静态资源不豁免」（D-3）能被证伪的关键：CSS 真的加载到了（否则页面会裸奔成无样式）
            bg = page.evaluate(
                "() => getComputedStyle(document.body).backgroundColor")
            check(bool(bg) and bg != "rgba(0, 0, 0, 0)" and bg != "",
                  "AUTH-5c 静态 CSS 已加载（body 有背景色 ⇒ /static 在鉴权下正常送达）", bg)
        finally:
            ctx.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def assert_timeline_values(browser, url: str) -> None:
    """EV-1~EV-11 结果值层。

    EV-1  每个事件含 actual/forecast/previous/unit/value_source 等 8 键（值可 null，键必须在）
    EV-2  **三方对账**（沿用 TL-2 的独立口径手法）：sqlite3 直查 db == API 计数 == 页面 DOM 渲染数
    EV-3  真实数据锁死：2026-09-16 FOMC（actual=4 / previous=3.75，页面含 25bp）、2026-09-11 CPI（334.98 / 334.85）
    EV-4  无 0/None 混淆：`actual` 为 null 的行**不得**出现「实际」项（绝不渲染成 0）
    EV-5  同一行**至多一个值片段**（同日同 kind 不出现两份值；真实双非农的择优由 pytest 的 fixture 锁）
    EV-6  失败降级：mock `/api/timeline` 全空值 -> 事件行仍在、页面不崩、仍不渲染 0
    EV-7  preserve 语义在同步脚本侧 -> 由 tests/test_econ_values.py 锁（本组只确认库里值在页面上可见）
    EV-8  TL-7 复跑仍绿（无因果措辞）+ 新增口径文案存在 + 四视口无横向溢出
    EV-9  `unit` 缺失不加单位后缀（CPI 行无 `%`/`点`/`千人`），而 FOMC 行必须带 `%`
    EV-10 未来事件文案：无 actual 的未来行必须含「待公布」，且不得留空白
    EV-11 两态断点：768 含「实际/预期/前值」三项，375 只含「实际/变动」两项，且两份文案不同时在 DOM 里
    """
    print("\n--- EV 结果值层（/timeline 实际/预期/前值）---")
    import sqlite3

    api = json.loads(urllib.request.urlopen(url + "api/timeline?days=90&future_days=30",
                                            timeout=30).read().decode("utf-8"))
    as_of = api.get("as_of") or ""
    api_ev = [(d["date"], e) for d in (api.get("past") or []) + (api.get("upcoming") or [])
              for e in d["events"]]

    # ---------- EV-1：键必须全在（值可为 null）----------
    missing = [(dt, e.get("kind"), k) for dt, e in api_ev for k in EV_KEYS if k not in e]
    check(bool(api_ev) and not missing, "EV-1 /api/timeline 每个事件含 8 个值层键（值可 null，键必须在）",
          missing[:3])

    # ---------- EV-2：三方对账（sqlite 直查 vs API vs DOM）----------
    d0 = _date_from_iso(as_of) if as_of else None
    past_from = (d0 - timedelta(days=90)).isoformat() if d0 else ""
    fut_to = (d0 + timedelta(days=30)).isoformat() if d0 else ""
    db = ROOT / "data" / "marketpulse.db"
    db_err = None
    db_hits = 0
    try:
        conn = sqlite3.connect(str(db))
        # ⚠️ 必须**限制到与页面同一窗口**：值层只 enrich 窗口内的骨架行（VALUE_PAST_DAYS/ FUTURE_DAYS
        #    与页面默认窗口取齐），全库计数会大于页面计数。
        db_hits = conn.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT date, kind FROM econ_events "
            "WHERE actual IS NOT NULL AND date >= ? AND date <= ?)", (past_from, fut_to)).fetchone()[0]
        conn.close()
    except Exception as exc:            # noqa: BLE001
        db_err = "{}: {}".format(type(exc).__name__, exc)
    check(db_err is None, "EV-2c econ_events 的 actual 列可查（独立核算前提）", db_err)
    api_hits = sum(1 for _dt, e in api_ev if e.get("actual") is not None)

    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        perrs: list[str] = []
        page.on("pageerror", lambda e: perrs.append(str(e)))
        page.goto(url + "timeline", wait_until="load")
        page.wait_for_timeout(1200)
        d = page.evaluate(EV_JS)
        print("  [page] events={} withValue={} valSpans={} modes={}".format(
            d["evCount"], d["withValue"], d["valCount"], d["modes"]))
        dom_hits = sum(1 for r in d["rows"] if "实际" in r["val"])
        print("  [db 独立核算] 窗口 {} ~ {} 带 actual 的 (date,kind) = {}；API = {}；DOM = {}".format(
            past_from, fut_to, db_hits, api_hits, dom_hits))
        check(db_hits > 0 and db_hits == api_hits == dom_hits,
              "EV-2 三方对账一致（sqlite 直查 == API 计数 == 页面渲染数；前置 >0，空集相等不算过）",
              (db_hits, api_hits, dom_hits))

        by_key = {(r["date"], r["kind"]): r for r in d["rows"]}
        api_by_key = {(dt, e["kind"]): e for dt, e in api_ev}

        # ---------- EV-3：真实数据锁死 ----------
        fomc = by_key.get(("2026-09-16", "FOMC"))
        cpi = by_key.get(("2026-09-11", "CPI"))
        fomc_api = api_by_key.get(("2026-09-16", "FOMC")) or {}
        cpi_api = api_by_key.get(("2026-09-11", "CPI")) or {}
        check(fomc is not None and cpi is not None
              and fomc_api.get("actual") == 4 and fomc_api.get("previous") == 3.75
              and "25bp" in (fomc or {}).get("val", "")
              and cpi_api.get("actual") == 334.98 and cpi_api.get("forecast") == 334.85
              and "334.98" in (cpi or {}).get("val", ""),
              "EV-3 真实数据锁死（FOMC act=4/prev=3.75 且页面含 25bp；CPI act=334.98/fc=334.85）",
              ((fomc or {}).get("val"), (cpi or {}).get("val")))

        # ---------- EV-4：actual 为 null 的行不得出现「实际」项（绝不渲染成 0）----------
        bad_zero = [(r["date"], r["kind"], r["val"]) for r in d["rows"]
                    if (api_by_key.get((r["date"], r["kind"])) or {}).get("actual") is None
                    and "实际" in r["val"]]
        check(d["evCount"] >= 1 and not bad_zero,
              "EV-4 actual 为 null 时不得渲染「实际」项（防 None 被显示成 0）", bad_zero[:3])

        # ---------- EV-5：同一行至多一个值片段 ----------
        multi = [(r["date"], r["kind"], r["valCount"]) for r in d["rows"] if r["valCount"] > 1]
        check(d["evCount"] >= 1 and not multi,
              "EV-5 每行至多一个值片段（(date,kind) 已去重，不出现两份值）", multi[:3])

        # ---------- EV-9：unit 缺失不加单位后缀 ----------
        cpi_val = (cpi or {}).get("val", "")
        cpi_bad = [u for u in ("%", "点", "千人") if u in cpi_val]
        fomc_val = (fomc or {}).get("val", "")
        check(cpi is not None and "实际 334.98" in cpi_val and not cpi_bad
              and fomc is not None and "4.00%" in fomc_val,
              "EV-9 unit 缺失时不给数字补单位（CPI 行无 %/点/千人），unit=% 时带 %（FOMC 4.00%）",
              (cpi_val, cpi_bad, fomc_val))

        # ---------- EV-10：未来事件的「待公布」----------
        pending = [(dt, e["kind"]) for dt, e in api_ev
                   if e.get("actual") is None and dt >= as_of]
        no_pending_text = []
        for dt, kind in pending:
            r = by_key.get((dt, kind))
            txt = (r or {}).get("val", "")
            if not txt or "待公布" not in txt or "实际" in txt:
                no_pending_text.append((dt, kind, txt))
        check(bool(pending) and not no_pending_text,
              "EV-10 未公布事件的值区必含「待公布」、且不得留空白或渲染 0（前置 pending>0）",
              (len(pending), no_pending_text[:3]))

        # ---------- EV-8：口径文案 + 无因果措辞 ----------
        honest = "\n".join(d["honest"] + d["src"])
        causal = len(re.findall("因为|导致|利好|利空|由于", "\n".join(
            x["val"] + " " + x["kind"] for x in d["rows"])))
        check("指数水平" in honest and "原始数值" in honest and "TradingView" in honest,
              "EV-8 口径区新增三条（CPI 指数水平 / 源未提供单位按原始数值 / 值来源 TradingView）",
              [k for k in ("指数水平", "原始数值", "TradingView") if k not in honest])
        check(causal == 0, "EV-8b 值片段无因果措辞（高于/低于/符合预期是客观比较，非利好利空）", causal)
        check(d["overflow"] == 0, "EV-8c 1440 档无横向溢出（加值后 TL-8 复跑）", d["overflow"])
        check(not perrs, "EV-8d /timeline 无 pageerror", perrs[:2])
    finally:
        ctx.close()

    # ---------- EV-6：失败降级（mock 全空值 -> 行还在、不渲染 0）----------
    blank = json.loads(json.dumps(api))
    for _day in (blank.get("past") or []) + (blank.get("upcoming") or []):
        for _e in _day["events"]:
            for _k in ("actual", "forecast", "previous", "unit", "importance",
                       "value_source", "value_title", "value_fetched_at"):
                _e[_k] = None
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        perrs6: list[str] = []
        page.on("pageerror", lambda e: perrs6.append(str(e)))
        page.route("**/api/timeline*", _ev_mk_route(blank))
        page.goto(url + "timeline", wait_until="load")
        page.wait_for_timeout(1200)
        d6 = page.evaluate(EV_JS)
        bad6 = [r for r in d6["rows"] if "实际" in r["val"] or "0.00%" in r["val"]]
        check(d6["evCount"] >= 1 and not bad6 and not perrs6,
              "EV-6 值侧全空时页面仍有事件行、不渲染 0、无 pageerror（降级成「只有事件名」）",
              (d6["evCount"], bad6[:2], perrs6[:2]))
    finally:
        ctx.close()

    # ---------- EV-11：两态断点（768 = 完整三项 / 375 = 精简两项）----------
    # ⚠️ 「变动项」在 FOMC 上按 D2.1④ 走的是 `加息 25bp` / `降息 25bp` / `维持不变` 文案，
    #    不是字面「变动」=> 断言必须按**文案族**判，不能只找字面「变动」（初版就因此假红）。
    DELTA_WORDS = ("变动", "加息", "降息", "维持不变")
    # 参照行取「三个操作数都非空」的事件（自有实际值 + 有预期 + 有前值），否则"三项 vs 两项"无从谈起。
    ref_key = None
    for _dt, _e in api_ev:
        if _e.get("actual") is not None and _e.get("forecast") is not None and _e.get("previous") is not None:
            ref_key = (_dt, _e["kind"])
            if _dt == "2026-09-11" and _e["kind"] == "CPI":
                break                       # 优先用断言里已锁死的那条真实数据
    for vw, vh in ((768, 1024), (375, 812)):
        ctx = browser.new_context(viewport={"width": vw, "height": vh}, device_scale_factor=1)
        try:
            page = ctx.new_page()
            page.goto(url + "timeline", wait_until="load")
            page.wait_for_timeout(1000)
            d11 = page.evaluate(EV_JS)
            rows11 = {(r["date"], r["kind"]): r for r in d11["rows"]}
            ref = rows11.get(ref_key) or {}
            published = [r for r in d11["rows"] if r["val"]]
            modes = d11["modes"]
            full = vw >= 768
            if full:
                ok_ref = ("实际" in ref.get("val", "") and "预期" in ref.get("val", "")
                          and "前值" in ref.get("val", ""))
                # 逐行按 API 字段算应有项（独立期望值：不从页面反推）
                bad = []
                for r in d11["rows"]:
                    e = api_by_key.get((r["date"], r["kind"])) or {}
                    if e.get("actual") is None:
                        continue
                    need = ["实际"]
                    if e.get("forecast") is not None:
                        need.append("预期")
                    if e.get("previous") is not None:
                        need.append("前值")
                    miss = [k for k in need if k not in r["val"]]
                    if miss:
                        bad.append((r["date"], r["kind"], miss, r["val"]))
            else:
                ok_ref = ("实际" in ref.get("val", "")
                          and any(w in ref.get("val", "") for w in DELTA_WORDS)
                          and not any(k in ref.get("val", "") for k in ("预期", "前值")))
                # ⚠️ 只对**有实际值的行**生效：未公布行走「待公布」分支（那里必须有 预期/前值 才算
                #    不留空白，见 EV-10）=> 把范围收宽到全页会把正确的待公布行判成红。
                bad = [(r["date"], r["kind"], r["val"]) for r in d11["rows"]
                       if "实际" in r["val"] and ("预期" in r["val"] or "前值" in r["val"])]
            dup11 = [r for r in d11["rows"] if r["valCount"] > 1]
            print("  [{}px] 值行={} modes={} 参照行 {}={}".format(
                vw, len(published), modes, ref_key, (ref.get("val") or "-")[:80]))
            check(ref_key is not None and bool(ref.get("val")) and ok_ref and not bad and not dup11
                  and len(modes) == 1 and modes[0] == ("full" if full else "lite"),
                  "EV-11 {}px 值为{}态（{}），且 DOM 里只有一份文案".format(
                      vw, "完整三项 实际/预期/前值" if full else "精简两项 实际/变动",
                      "参照行三词齐全" if full else "参照行只剩实际+变动族，且全页无 预期/前值"),
                  (ref.get("val"), bad[:1], dup11[:1], modes))
            check(d11["overflow"] == 0, "EV-11b {}px 无横向溢出".format(vw), d11["overflow"])
        finally:
            ctx.close()


def _date_from_iso(s: str):
    from datetime import date as _d
    return _d.fromisoformat(s)


def _tpl(js: str, cfg: dict) -> str:
    """把探针模板里的占位符替换为该容器的 id / 选择器 / 滚动器键。"""
    return (js.replace("__BODY__", cfg["body_id"])
              .replace("__ITEM__", cfg["item_sel"])
              .replace("__CLONE__", cfg["clone_sel"])
              .replace("__KEY__", cfg["key"]))


def autoscroll_js(cfg: dict) -> str:
    """滚动容器契约探针（资讯卡 / 告警卡共用同一份，只换 id 与选择器）。"""
    return _tpl(r"""
() => {
  const el = document.getElementById('__BODY__');
  if (!el) return { error: 'no #__BODY__' };
  const cs = getComputedStyle(el);
  const items = el.querySelectorAll('__ITEM__');
  const n = Math.floor(items.length / 2);
  // 一个完整循环的像素长度（与 makeAutoScroller 的启动判定同一口径：
  // 「周期 ≤ clientHeight」→ 内容不足一屏 → 不启动）
  const period = (n > 0 && items[n]) ? (items[n].offsetTop - items[0].offsetTop) : 0;
  const clone = el.querySelector('__CLONE__');
  const alerts = document.getElementById('alerts');
  const news = document.getElementById('news');
  return {
    itemCount: items.length,
    period: period,
    cloneItemCount: clone ? clone.querySelectorAll('__ITEM__').length : 0,
    cloneAriaHidden: clone ? clone.getAttribute('aria-hidden') : null,
    offsetHeight: el.offsetHeight,
    clientHeight: el.clientHeight,
    scrollHeight: el.scrollHeight,
    scrollTop: el.scrollTop,
    maxHeight: cs.maxHeight,
    overflowY: cs.overflowY,
    alertH: alerts ? alerts.offsetHeight : null,
    newsH: news ? news.offsetHeight : null,
    scrollH: document.scrollingElement.scrollHeight,
    scrollW: document.scrollingElement.scrollWidth,
    innerW: window.innerWidth,
  };
}
""", cfg)


def sample_js(cfg: dict) -> str:
    """按**时间**采样 ~600ms 的 scrollTop（按帧数采样会在高帧率下采到「几乎没动」→ 假红）。"""
    return _tpl(r"""
() => new Promise((resolve) => {
  const el = document.getElementById('__BODY__');
  const s = [];
  const t0 = performance.now();
  const tick = () => {
    s.push(Math.round(el.scrollTop * 100) / 100);
    if (performance.now() - t0 < 600) requestAnimationFrame(tick); else resolve(s);
  };
  requestAnimationFrame(tick);
})
""", cfg)


def wrap_js(cfg: dict) -> str:
    """顶到「循环点前 2px」后采样，直到观察到回绕，并**回绕后再多采 10 帧**（否则「回绕后是否
    继续前进」无法观测 → 断言假红）。

    周期取 `items[n].offsetTop - items[0].offsetTop`（克隆半首条相对第一半首条的偏移）：
    对 border 分隔（`.news-item`）与 flex gap（`.alert-list`）两种布局都精确 ——
    用「前一半 offsetHeight 之和」在 gap 布局下会差 n×gap。

    ⚠️ **预置位必须"验证生效 + 可重试"（2026-09-19 实测）**：页面自身的 TTL 刷新会重建 ticker DOM，
    而 `renderAlerts/renderNews` 里都有 `body.scrollTop = 0` ⇒ 若这一次重建正好落在预置与采样之间，
    预置位被冲成 0 → 采样窗口内看不到回绕 → `{p}-6b` **假红**（实测记录：`first=777 → 0/1`，
    同一个页面把加载后静默从 1.5s 拉到 5s 就 3/3 通过，而"被冲掉"与否只取决于那次刷新的落点）。
    故：起始帧若发现位置没落到位，**重新预置**，并把重试次数带回结果里（`armTries`）——
    红的时候能一眼分辨「真的是循环停住了」还是「一次都没预置上」。
    ⚠️ 重试的**触发条件**在下方二次修正里被改写过（原为"尚未采样 + 20 帧"，现为"尚未观测到回绕 + ≤3 轮重采"）。

    ⚠️⚠️ **2026-09-19 二次修正：首样本必须"同步"取，重试判据不能是"还没采样"**（逐帧诊断实证）。
    预置点 `start = period - 2` 距回绕点**只有 2px**，而 scroller 是持续运行的
    （16px/s ÷ 60fps ≈ 0.27px/帧 ⇒ **约 8 帧后它自己就会回绕**）。旧实现把首样本留给第一次
    `requestAnimationFrame`，于是 arm → 首帧之间只要有 >2px 的延迟（布局 / GC / TTL 重建 / 低帧率），
    scroller 就**抢先正常回绕**，`cur` 变成 0 附近，被旧判据 `out.length === 0 && cur < start-1`
    判成「预置没生效」→ 重新 arm → 再被抢先 → **20 帧耗尽，采样窗口里一个回绕都没记到** → 假红。
    实测签名：`period=777 first=0 last=503 drops=[] armTries=20`（而同一页面 8 帧后的回绕是**正常行为**）。
    逐帧证据（2026-09-19）：`after-arm 931 → f7 933 → f8 0`（`st.pos >= st.period` 减周期）。
    修法：① `arm()` 后**同步**读一次作首样本（同帧读回必等于 start，不可能被抢先）；
    ② 重试判据改为「**尚未观测到回绕** + 位置掉回起点附近」，正常回绕不再被误判成预置失败，
    而 TTL 重建把位置冲掉时仍会重试。**判据本身未放松**：始终没见过回绕依然判红。
    """
    return _tpl(r"""
() => new Promise((resolve) => {
  const el = document.getElementById('__BODY__');
  if (!el) return resolve({ error: 'no el' });
  const items = [...el.querySelectorAll('__ITEM__')];
  const n = Math.max(1, Math.floor(items.length / 2));
  const period = items[n] ? (items[n].offsetTop - items[0].offsetTop) : 0;
  const start = Math.max(0, period - 2);
  // ★ 必须同时重置**浮点累加器**，否则下一帧会把 scrollTop 写回旧位置
  const sc = window.__scroll && window.__scroll['__KEY__'];
  const arm = () => { if (sc) sc.state.pos = start; el.scrollTop = start; };
  const out = [];
  let wrapIdx = -1;
  let armTries = 0;
  const sn = () => Math.round(el.scrollTop * 100) / 100;
  const tick = () => {
    const cur = sn();
    out.push(cur);
    if (wrapIdx < 0 && out.length > 1 && out[out.length - 1] < out[out.length - 2]) {
      wrapIdx = out.length - 1;
    }
    // 兜底重试：**还没见到回绕**且位置掉回起点附近（页面 TTL 重建把预置位冲了）→
    // 重新预置并**丢弃这批样本**重来。正常回绕不会走到这里（那时 wrapIdx 已置位）。
    if (wrapIdx < 0 && start > 0 && armTries < 3 && out.length >= 30 && cur < 5) {
      armTries += 1;
      out.length = 0;
      arm();
      return requestAnimationFrame(tick);
    }
    if ((wrapIdx >= 0 && out.length - wrapIdx >= 10) || out.length >= 200) {
      resolve({ samples: out, period: period, wrapIdx: wrapIdx, armTries: armTries });
    } else requestAnimationFrame(tick);
  };
  arm();
  // ★ 同步首样本：与 arm 同帧读回（必等于 start），不会被 scroller 的抢先回绕吃掉。
  //   旧实现把首样本留给第一次 raf —— 而 start 距回绕点仅 2px（≈8 帧），任何 >2px 的延迟
  //   都让 scroller 先回绕，随即被旧判据当成「预置失败」重试到耗尽（见 docstring 二次修正）。
  out.push(sn());
  requestAnimationFrame(tick);
})
""", cfg)


def halves_js(cfg: dict) -> str:
    """两半逐条比对（文本 + 高度）→ 证明「减周期」回绕在视觉上无缝。"""
    return _tpl(r"""
() => {
  const el = document.getElementById('__BODY__');
  const items = [...el.querySelectorAll('__ITEM__')];
  const n = Math.floor(items.length / 2);
  const mismatches = [];
  for (let i = 0; i < n; i++) {
    const a = items[i], b = items[i + n];
    if (!b) { mismatches.push({ i: i, missing: true }); continue; }
    if (a.textContent !== b.textContent || a.offsetHeight !== b.offsetHeight) {
      mismatches.push({ i: i, h: [a.offsetHeight, b.offsetHeight] });
    }
  }
  return { n: n, mismatches: mismatches };
}
""", cfg)


def rate_js(cfg: dict) -> str:
    """实测滚动速率（先归零 → 1.5s 内不会跨越一个周期，结果稳定）。"""
    return _tpl(r"""
() => new Promise((resolve) => {
  const el = document.getElementById('__BODY__');
  // 同时重置浮点累加器，否则下一次 step 会把 scrollTop 写回旧位置 → 速率虚高
  const sc = window.__scroll && window.__scroll['__KEY__'];
  if (sc) sc.state.pos = 0;
  el.scrollTop = 0;
  const t0 = performance.now();
  setTimeout(() => {
    const dt = (performance.now() - t0) / 1000;
    resolve({ px_per_sec: el.scrollTop / dt, constant: window.NEWS_SCROLL_PX_PER_SEC });
  }, 1500);
})
""", cfg)


SHORT_NEWS = json.dumps({"date": "2026-09-13", "items": [{
    "title": "短内容占位条目", "url": "https://example.com/x", "source": "测试",
    "published": "2026-09-13", "summary": "内容不足一屏时应保持静止不滚动",
}]}, ensure_ascii=False)

SHORT_ALERTS = json.dumps([{
    "level": "WARN", "symbol": "TEST", "date": "2026-09-13", "type": "close",
    "state": "异动", "current": 1.0, "last": 1.0, "change_pct": 0.0, "threshold": 20,
    "suggestion": "测试建议", "report": "reports/2026-09-13.md",
}], ensure_ascii=False)

# 两个滚动容器共用同一套断言（prefix 区分标签：A=资讯、B=告警）
CFG_NEWS = {
    "key": "news", "prefix": "A", "title": "最新资讯",
    "body_id": "news-body", "item_sel": ".news-item", "clone_sel": ".news-clone",
    "api": "api/news", "short_body": SHORT_NEWS,
}
CFG_ALERTS = {
    "key": "alerts", "prefix": "B", "title": "告警记录",
    "body_id": "alert-list", "item_sel": ".alert-card", "clone_sel": ".alert-clone",
    "api": "api/alerts", "short_body": SHORT_ALERTS,
}


def assert_autoscroll(page, base_url: str, cfg: dict) -> None:
    """自动循环滚动通用断言（双份内容 / 高度不变量 / 滚动 / 暂停 / 无缝回绕 / 亚像素回归 / 护栏）。"""
    p, bid = cfg["prefix"], cfg["body_id"]
    print(f"\n--- {p} {cfg['title']}（自动滚动）---")
    d = page.evaluate(autoscroll_js(cfg))
    if d.get("error"):
        check(False, f"{p}-0 找到 #{bid}", d["error"])
        return
    try:
        with urllib.request.urlopen(base_url + cfg["api"], timeout=10) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        payload = None
    if isinstance(payload, dict):
        api_n = len(payload.get("items") or [])
    elif isinstance(payload, list):
        api_n = len(payload)
    else:
        api_n = 0
    print(f"  api={api_n} dom={d['itemCount']} clone={d['cloneItemCount']} hidden={d['cloneAriaHidden']} "
          f"bodyH={d['offsetHeight']} client={d['clientHeight']} scroll={d['scrollHeight']}")

    check(api_n > 0 and d["itemCount"] == api_n * 2 and d["cloneItemCount"] == api_n,
          f"{p}-1 条目数 == 接口条数 × 2（双份内容）", (d["itemCount"], api_n, d["cloneItemCount"]))
    check(d["cloneAriaHidden"] == "true",
          f"{p}-2 克隆半 aria-hidden=true（屏幕阅读器不重复朗读）", d["cloneAriaHidden"])
    check(d["offsetHeight"] <= 132 and d["maxHeight"] == "132px",
          f"{p}-3 容器高 ≤132 且 max-height=132px（护栏不变）", (d["offsetHeight"], d["maxHeight"]))
    if d["scrollHeight"] > 132:      # 双份内容不得把容器撑高：超限时必须恰好钳在 132px
        check(d["offsetHeight"] == 132,
              f"{p}-3b 内容超限时恰好钳在 132px（双份内容不撑高容器）", d["offsetHeight"])
    else:
        check(d["offsetHeight"] <= 132, f"{p}-3b 内容不足时高度随内容（≤132）", d["offsetHeight"])
    check(d["newsH"] is not None and d["alertH"] is not None and abs(d["newsH"] - d["alertH"]) <= 2,
          f"{p}-3c #news 与 #alerts 两卡仍等高（并排等高原则未破）", (d["newsH"], d["alertH"]))

    page.mouse.move(10, 10)          # 保证不在 hover 暂停态
    page.wait_for_timeout(200)
    samples = page.evaluate(sample_js(cfg))
    moved = len(samples) >= 2 and samples[-1] > samples[0] + 0.5
    print(f"  滚动采样: {samples} moved={moved}")
    if d["scrollHeight"] > d["clientHeight"]:
        check(moved, f"{p}-4 内容超一屏 → scrollTop 递增（自动滚动生效）", samples)
    else:
        check(all(x == 0 for x in samples), f"{p}-4 内容不足一屏 → scrollTop 恒 0（不滚）", samples)

    # 必须「hover 前在动 + hover 时不动」两条同时成立（否则「不动」是恒真断言）
    page.hover(f"#{bid}")
    page.wait_for_timeout(200)
    t0 = page.evaluate(f"() => document.getElementById('{bid}').scrollTop")
    page.wait_for_timeout(600)
    t1 = page.evaluate(f"() => document.getElementById('{bid}').scrollTop")
    check(moved and abs(t1 - t0) <= 1,
          f"{p}-5 悬停暂停（滚动中 → 0.6s 内 scrollTop 不变）", (moved, t0, t1))
    page.mouse.move(10, 10)
    page.wait_for_timeout(150)
    r0 = page.evaluate(f"() => document.getElementById('{bid}').scrollTop")
    page.wait_for_timeout(500)
    r1 = page.evaluate(f"() => document.getElementById('{bid}').scrollTop")
    check(abs(r1 - r0) < 200,
          f"{p}-5b 移开恢复时不产生大跳（mouseleave 重置时间戳）", (r0, r1))

    # 顶到循环点前采样 → 应恰好回绕一次、幅度≈周期、回绕后继续前进、全程无负值
    page.mouse.move(10, 10)
    page.wait_for_timeout(150)
    w = page.evaluate(wrap_js(cfg))
    ss = w.get("samples") or []
    period = w.get("period") or 0
    wrap_idx = w.get("wrapIdx", -1)
    drops = [round(ss[i - 1] - ss[i], 2) for i in range(1, len(ss)) if ss[i] < ss[i - 1]]
    post = ss[wrap_idx:] if wrap_idx >= 0 else ss
    print(f"  回绕采样 period={period} first={ss[0] if ss else None} last={ss[-1] if ss else None} "
          f"drops={drops} armTries={w.get('armTries', 0)}")
    check(all(x >= 0 for x in ss), f"{p}-6a scrollTop 全程无负值", (min(ss) if ss else None))
    check(wrap_idx >= 0 and len(post) >= 3 and post[-1] > post[0] + 0.5,
          f"{p}-6b 回绕后继续前进（循环未停住）",
          (wrap_idx, post[0] if post else None, post[-1] if post else None))
    check(len(drops) <= 1 and (not drops or max(drops) <= period + 1),
          f"{p}-6c 只回绕一次且幅度 ≤ 周期", drops)
    check(not drops or max(drops) > period * 0.5,
          f"{p}-6d 回绕幅度 > 周期的一半（证明是 -period 而非随机跳变）", drops)

    halves = page.evaluate(halves_js(cfg))
    check(halves.get("n", 0) > 0 and not halves.get("mismatches"),
          f"{p}-7 克隆半与第一半逐条一致（文本+高度）→ 回绕无缝", halves)

    rate = page.evaluate(rate_js(cfg))
    print(f"  实测速率 {rate['px_per_sec']:.2f} px/s（常量 {rate['constant']}）")
    check(rate["px_per_sec"] >= 8, f"{p}-8 实测速率 ≥8px/s（按常量匀速滚动）", rate)

    # ★ 根因回归：亚像素速率下仍必须前进。
    # 旧实现 `el.scrollTop += 增量`：此处 scrollTop 读回是整数，增量 <1px/帧 时小数每帧被抹掉
    # → 位置永远停在原处（60fps 下 16px/s = 0.27px/帧 → 看起来「完全不动」）。
    page.mouse.move(10, 10)
    page.wait_for_timeout(200)
    page.evaluate(
        f"""() => {{ window.NEWS_SCROLL_PX_PER_SEC = 4;
                    const el = document.getElementById('{bid}');
                    const sc = window.__scroll && window.__scroll['{cfg["key"]}'];
                    if (sc) sc.state.pos = 0;
                    el.scrollTop = 0; }}"""
    )
    page.wait_for_timeout(2200)
    sub = page.evaluate(f"() => document.getElementById('{bid}').scrollTop")
    page.evaluate("() => { window.NEWS_SCROLL_PX_PER_SEC = 16; }")
    print(f"  亚像素速率(4px/s) 2.2s 后 scrollTop={sub}")
    check(sub >= 3,
          f"{p}-9 速率 4px/s（<1px/帧）仍前进（浮点累加器生效，防「看起来不动」）", sub)

    check(d["scrollH"] <= 1240, f"{p}-10a scrollHeight @1920 ≤1240", d["scrollH"])
    check(d["scrollW"] == d["innerW"], f"{p}-10b 无横向溢出", (d["scrollW"], d["innerW"]))


def assert_reduced_motion(browser, url: str, cfg: dict) -> None:
    """`prefers-reduced-motion: reduce` 下不启动自动滚动，但内容仍可手动滚动到（无障碍）。"""
    p = cfg["prefix"]
    print(f"\n--- {p} reduce-motion 退化（{cfg['title']}）---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080},
                              device_scale_factor=1, reduced_motion="reduce")
    try:
        page = ctx.new_page()
        page.goto(url, wait_until="load")
        page.wait_for_timeout(2500)          # 若误启动，16px/s × 2.5s ≈ 40px，足以区分
        d = page.evaluate(autoscroll_js(cfg))
        s = page.evaluate(sample_js(cfg))
        print(f"  overflowY={d['overflowY']} maxH={d['maxHeight']} scrollTop 采样={s}")
        check(d["overflowY"] == "auto",
              f"{p}-11a reduce-motion 下仍 overflow-y:auto（内容可达）", d["overflowY"])
        check(all(x == 0 for x in s),
              f"{p}-11b reduce-motion 下不启动自动滚动（scrollTop 恒 0）", s)
    finally:
        ctx.close()


FF_SCROLLBAR_JS = r"""
() => {
  const el = document.querySelector('#news-body');
  const cs = el ? getComputedStyle(el) : null;
  // CSSOM 里的 Firefox 门控块：conditionText 含 -moz-appearance，且内部含 scrollbar-width
  let gate = null;
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const r of rules) {
      if (r.conditionText && r.conditionText.includes('-moz-appearance')) {
        for (const inner of (r.cssRules || [])) {
          if (inner.style && inner.style.scrollbarWidth) gate = inner.style.scrollbarWidth;
        }
      }
    }
  }
  return {
    scrollbarWidth: cs ? cs.scrollbarWidth : null,
    scrollbarColor: cs ? cs.scrollbarColor : null,
    gateScrollbarWidth: gate,
    rootSbPx: window.innerWidth - document.documentElement.clientWidth,
    newsSbPx: el ? el.offsetWidth - el.clientWidth : null,
  };
}
"""


def assert_firefox_scrollbar(p, url: str) -> None:
    """N-12 Firefox 引擎专项：细滚动条的门控必须真的命中 Firefox。

    背景（2026-09-13 用户实测「就 firefox 这样」）：`@supports not selector(::-webkit-scrollbar)`
    在 **Firefox 里恒为假** —— Firefox 出于 web 兼容把 `::-webkit-scrollbar` 当作「合法但未实现」
    的选择器，`selector()` 同样返回 true；取反后 Firefox 被误判成 Chromium、标准属性块被跳过 →
    落到 **17px 原生滚动条**。门控必须改用 Firefox 专属属性（`-moz-appearance`，实测 FF=true / Chromium=false）。

    ⚠️ 判据为何不用宽度：**headless Firefox 根本不渲染滚动条**（实测 `scrollbar-width` 解析为 `none`、
    宽度 0，与 headless Chromium 的 overlay 同源）→ 宽度类断言在 headless 下恒真/恒假都没有意义。
    故 headless 下用「门控命中」判据（`scrollbar-color` 是否被主题色覆盖 = 块真的生效了 + CSSOM 门控形状），
    宽度证据来自 headed 实测：修复前 17px → 修复后 **8px**（Firefox thin 的下限）。
    未安装 Firefox 内核 → SKIP（打印原因、不计失败）。
    """
    print("\n--- N-12 Firefox 引擎滚动条 ---")
    try:
        fb = p.firefox.launch()
    except Exception as exc:  # noqa: BLE001
        # 2026-09-20：SKIP 从"只打一行日志"改为**进结构化记录**（否则汇总与 report.json 都看不到
        # 「这次有几条没验」，读者会误以为跑全了 —— plan §0 第 4 条）。
        # ⚠️ 但 **N-12a/12b 的判据保持原样**（`deps=()`，永不 SKIP）：它不是外部依赖，
        #    实测在当前 Firefox 1538 下**已通过**，继续作「门控命中」的回归护栏（plan §3.4）。
        why = "Firefox 内核不可用（需 `playwright install firefox`）: %s" % str(exc).splitlines()[0][:90]
        SKIPPED.append({"label": "N-12 Firefox 滚动条门控（a/b 两条未判定）", "reason": why, "detail": {}})
        print(f"  SKIP Firefox 内核不可用（需 `playwright install firefox`）: {str(exc).splitlines()[0][:90]}")
        return
    try:
        pg = fb.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto(url, wait_until="load")
        pg.wait_for_timeout(3000)
        d = pg.evaluate(FF_SCROLLBAR_JS)
    finally:
        fb.close()
    print(f"  {d}")
    check("auto" not in str(d["scrollbarColor"]) and "rgb" in str(d["scrollbarColor"]),
          "N-12a Firefox 下 scrollbar-color 被主题色覆盖（证明 -moz-appearance 门控在 FF 命中）",
          d["scrollbarColor"])
    check(d["gateScrollbarWidth"] == "thin",
          "N-12b CSSOM 内 Firefox 门控块含 scrollbar-width:thin", d["gateScrollbarWidth"])


def assert_short_content(browser, url: str, cfg: dict) -> None:
    """内容不足一屏（**周期 ≤ clientHeight**，与 makeAutoScroller 的启动判定同口径）时不启动
    自动滚动（否则原地抖动）。

    用 `page.route` 伪造「仅 1 条」的响应，独立 context 避免污染主页面状态。
    注意判据是**周期**而不是 scrollHeight：双份内容下 scrollHeight ≈ 2×周期，恒大于容器高。
    """
    p = cfg["prefix"]
    print(f"\n--- {p} 内容不足一屏（{cfg['title']}）---")
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    try:
        page = ctx.new_page()
        page.route(f"**/{cfg['api']}", lambda route: route.fulfill(
            status=200, content_type="application/json", body=cfg["short_body"]))
        page.goto(url, wait_until="load")
        page.wait_for_timeout(1500)
        d = page.evaluate(autoscroll_js(cfg))
        s = page.evaluate(sample_js(cfg))
        print(f"  items={d['itemCount']} period={d['period']} client={d['clientHeight']} 采样={s}")
        check(d["itemCount"] == 2 and 0 < d["period"] <= d["clientHeight"],
              f"{p}-12a 1 条内容 → 周期 ≤ clientHeight（不足一屏）",
              (d["itemCount"], d["period"], d["clientHeight"]))
        check(all(x == 0 for x in s), f"{p}-12b 内容不足一屏 → scrollTop 恒 0（不滚动/不抖动）", s)
    finally:
        ctx.close()


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


def assert_viewport(w: int, h: int, m: dict, expect_date: str = "") -> None:
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
    # ⚠️ 2026-09-14（macro-page-refine）：原为写死 `"2026-09-11" in topbarDate` → **数据日一变就必红**
    #    （违反 K-5「只断不变量、不断死数值」）。改为与 `/api/latest.date` **同源比对**；
    #    /api/latest 不可用时退化为"格式像数据日"（不因网络抖动误报）。
    td = (m["topbarDate"] or "").strip()
    ok = (expect_date in td) if expect_date else bool(re.match(r"^\d{4}-\d{2}-\d{2}", td))
    check(ok, f"{w} 顶栏显示数据日（期望值取自 /api/latest.date）", (td, expect_date))


def summarize_and_exit(strict: bool | None = None) -> int:
    """打印三态汇总并返回退出码（**抽成函数**：`--strict` 语义需要可被直接验证）。

    ⚠️ SKIP **不代表通过**：它只表示"该条无法判定，且原因是上游不可用（独立探测确认）"。
    所以汇总必须把三个数字都打出来，不能只打一个 `ALL PASSED` —— 否则读者会以为跑全了。
    退出码：有 FAIL ⇒ 1；`--strict` 时有 SKIP ⇒ 1；否则 0。
    """
    n_total = N_PASS + len(FAILURES) + len(SKIPPED)
    ups = " ".join("%s=%s" % (k, "OK" if UPSTREAM.get(k) else "DOWN") for k in ("macro", "econ"))
    print("\n===== 结果 =====")
    print(f"PASS:   {N_PASS}")
    print(f"FAIL:   {len(FAILURES)}")
    print(f"SKIP:   {len(SKIPPED)}")
    print(f"上游探测: {ups}")
    if SKIPPED:
        print("\n未判定（SKIP）明细：")
        for s in SKIPPED:
            print(f"  - {s['label']}  ← {s['reason']}")
        print("⚠️ 以上条目**未判定**（上游不可用），本次结果不代表它们通过；"
              "查上游状态，不要先查代码。")
        if n_total and len(SKIPPED) > n_total * 0.5:
            print("🔴 警告：SKIP 占比 > 50% —— 当前环境不可信，本次结果不应作为验收依据。")
    if FAILURES:
        print(f"\nFAILED: {len(FAILURES)} 条")
        for f in FAILURES:
            print("  - " + f)
        return 1
    if SKIPPED:
        print(f"ALL PASSED ({len(SKIPPED)} SKIPPED)" if not strict
              else f"STRICT: {len(SKIPPED)} 条 SKIP 视为失败")
        return 1 if strict else 0
    print("ALL PASSED")
    return 0


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"启动 uvicorn: {url}")
    if not PY.exists():
        print(f"找不到 venv python: {PY}")
        return 1
    # D-4a（2026-09-19）：鉴权上线后，验收脚本必须用 `MP_AUTH_DISABLED=1` 关掉鉴权起服。
    # 子进程**继承父进程 env**（Popen 未传 env）⇒ 这一行让既有 700+ 条断言**零改动、零新增失败**；
    # 鉴权行为本身由 `assert_auth()` 另起带鉴权实例独立覆盖（D-4b）。
    # ⚠️ 不要改成"给 28 个 new_context 都加 http_credentials"：改动面过大、把鉴权与既有信号耦合。
    os.environ["MP_AUTH_DISABLED"] = "1"

    # 上游探测（2026-09-20 signal-layering）：**跑断言之前**探一次快照，之后 `check()` 用它做归因。
    # 独立口径（不 import src.fetcher / web.app）+ 不确定即视为可用，见 probe_upstream。
    UPSTREAM.update(probe_upstream())
    print("上游探测: macro=%s econ=%s  %s" % (
        "OK" if UPSTREAM["macro"] else "DOWN", "OK" if UPSTREAM["econ"] else "DOWN",
        UPSTREAM.get("detail")))
    if STRICT:
        print("模式: --strict（有 SKIP 即判失败）")
    proc = subprocess.Popen(
        [str(PY), "-m", "uvicorn", "web.app:app", "--port", str(port)],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    report: dict = {"url": url, "viewports": {}}
    try:
        wait_ready(url)
        try:                        # 期望值一律取自数据（顶栏数据日等），不写死日期（见 assert_viewport 注释）
            data_date = api_latest(url).get("date") or ""
        except Exception as exc:  # noqa: BLE001
            data_date = ""
            print(f"  [warn] /api/latest 不可用 → 顶栏数据日退化为格式校验：{exc}")
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
                assert_viewport(w, h, m, data_date)
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
            # 2026-09-16（market-session-status）：原断言 `marketStatus in ("市场已开盘","休市")` 有两个病：
            #   ① 写死文案 → 下次改文案必红；② 旧实现"工作日恒为真"⇒ 工作日**恒真（假绿）**。
            #   改为与页面内**同一个函数**（window.__marketSession）产出比对的同源断言 —— 不写死任何具体词；
            #   真正的语义牙齿在 MS-3 覆盖表（含 DST 护栏）。
            _ms_now = page.evaluate(
                "() => (typeof window.__marketSession === 'function') ? window.__marketSession() : null")
            _ms_exp = _ms_now or {}
            check(bool(_ms_now)
                  and (m["marketCn"] or "").strip() == (_ms_exp.get("cn") or {}).get("label")
                  and (m["marketUs"] or "").strip() == (_ms_exp.get("us") or {}).get("label")
                  and "北京时间" in (m["marketTime"] or ""),
                  "侧栏市场状态两行 + 北京时间（期望同源 window.__marketSession，不写死词）",
                  (m["marketCn"], m["marketUs"], m["marketTime"]),
                  ((_ms_exp.get("cn") or {}).get("label"), (_ms_exp.get("us") or {}).get("label")))

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
            assert_us_table(page, browser, url)  # U-1~U-7 美股板块表格化（与 A股 同构）
            assert_sector_asof(page, url)        # V-1~V-6 板块「数据截至」标注（陈旧回填）
            try:                                 # 目视证据：美股 tab 的标注 + 真实回填数据
                page.evaluate("() => { const r = document.getElementById('sector-tab-us');"
                              " r.checked = true; r.dispatchEvent(new Event('change')); }")
                page.wait_for_timeout(250)
                page.locator("#us-sectors").screenshot(path=str(OUT_DIR / "shot-asof-us.png"))
                page.evaluate("() => { const r = document.getElementById('sector-tab-cn');"
                              " r.checked = true; r.dispatchEvent(new Event('change')); }")
                page.wait_for_timeout(250)
                page.locator("#us-sectors").screenshot(path=str(OUT_DIR / "shot-asof-cn.png"))
            except Exception as exc:  # noqa: BLE001
                print(f"  截图失败（不影响断言）: {exc}")
            assert_autoscroll(page, url, CFG_NEWS)      # A-* 最新资讯自动循环滚动
            assert_autoscroll(page, url, CFG_ALERTS)    # B-* 告警记录自动循环滚动
            for _cfg in (CFG_NEWS, CFG_ALERTS):
                assert_reduced_motion(browser, url, _cfg)   # reduce-motion 退化（独立 context）
                assert_short_content(browser, url, _cfg)    # 内容不足一屏不滚（独立 context）

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
            # 横悬线吸附到数据线（crosshair-snap 任务）：多宽度 + 目标选择 + 读数随日期变
            assert_crosshair_snap(page)

            # 375 档：抽屉 + 单列
            page.set_viewport_size({"width": 375, "height": 812})
            page.goto(url, wait_until="load")
            page.wait_for_timeout(3500)
            assert_asof_narrow(page)   # V-7 长文案在 375 档是否让 h2 换行（R1 护栏）
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
            assert_viewport(375, 812, mob_card, data_date)

            assert_macro_page(browser, url)   # MX-* 宏观数据独立页（2026-09-14 宏观页）
            assert_macro_cn_page(browser, url)  # CN-* 中国宏观独立页（2026-09-14 /macro/cn）
            assert_macro_refine(browser, url)  # M-* 宏观页 refinement（主题/关系口径/主图主次/留白/分层）
            assert_macro_crosshair(browser, url)  # XC-* 宏观页悬停参考线（读数按轴语义分派）
            assert_macro_cn_crosshair(browser, url)  # CNC-* /macro/cn 吸附（此前零覆盖，plan §6 Step 4）
            assert_crosshair_dpr2(browser, url)  # CS-D* DPR=2 取证（默认 DPR=1 测不出坐标系混用）
            assert_kpi_no_truncation(browser, url)   # KY-* KPI 无静默截断（kpi-responsive-fix）
            assert_market_session(browser, url)      # MS-* 侧栏市场状态两行两市场（market-session-status，2026-09-16）
            assert_macro_states(browser, url)        # NA-* 宏观页四态/chip/Score 语义色（macro-page-frontend-refactor，2026-09-16）
            assert_quadrant_matrix(browser, url)     # QM-* 四象限矩阵（macro-quadrant-matrix，2026-09-18）
            assert_timeline(browser, url)            # TL-* 市场日历（event-timeline-page，2026-09-18；09-19 改名）
            assert_timeline_values(browser, url)     # EV-* 结果值层 实际/预期/前值（timeline-event-values，2026-09-19）
            assert_auth(browser)                     # AUTH-* 访问控制 Basic Auth（web-basic-auth，2026-09-19；自带实例）
            assert_backtest(browser, url)            # BT-* 阈值回测页（backtest-ui，2026-09-20；本页不依赖上游）
            assert_settings(browser, url)            # ST-* 设置页（settings-page，2026-09-20；只读断言，不 POST）
            assert_portfolio(browser, url)            # PF-* 组合盈亏（portfolio-pnl，2026-09-20）
            assert_home_ux(browser, url)             # UX-* 首页体验走查整改（对比度/刷新反馈/主题初始化/抽屉，2026-09-17）
            assert_walkthrough(browser, url)         # PW-* 产线走查整改（告警锚点/相关性文案/表头语义/趋势三态，2026-09-17）
            check(not errors, "全流程 console error = 0", errors[:5])
            browser.close()

            # Firefox 专项（复用同一个 playwright 实例；未装 FF 内核则 SKIP）
            assert_firefox_scrollbar(p, url)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        report["failures"] = FAILURES
        report["skipped"] = SKIPPED
        report["upstream"] = UPSTREAM
        out = OUT_DIR / "verify-report.json"
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告: {out}")

    # ---- 三态汇总（2026-09-20 signal-layering）----
    return summarize_and_exit(STRICT)




# ============ BT 阈值回测页（/backtest，2026-09-20）============
# 任务档 tasks/2026-09-20-backtest-ui/。本页**不依赖上游**（只读本地 db）⇒ 断言一律 deps=()
# ⇒ **不该出现 SKIP**（出现即说明依赖标记或探测有问题）。

BT_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const txt = (s) => { const e = q(s); return e ? e.textContent.trim() : null; };
  const rows = Array.from(document.querySelectorAll('#bt-table-wrap .bt-table tbody tr'));
  const first = rows[0] ? Array.from(rows[0].children).map((td) => td.textContent.trim()) : null;
  return {
    h1: txt('.bt-head h1'),
    stats: {
      effdays: txt('#bt-effdays'), triggers: txt('#bt-triggers'),
      nsymbols: txt('#bt-nsymbols'), elapsed: txt('#bt-elapsed'),
    },
    cfgMode: txt('#bt-cfg-mode'), cfgLine: txt('#bt-cfg-line'),
    cfgChips: document.querySelectorAll('#bt-cfg-table .bt-cfg-chip').length,
    rowCount: rows.length, firstRow: first,
    detailsCount: document.querySelectorAll('#bt-details-body .bt-detail').length,
    methods: document.querySelectorAll('#bt-methods li').length,
    failHidden: !!q('#bt-fail') && q('#bt-fail').hidden,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    navCount: document.querySelectorAll('#sidebar .nav-item').length,
    navActive: (q('#sidebar .nav-item.active') || {}).textContent || null,
    theme: document.documentElement.getAttribute('data-theme'),
  };
}
"""


def assert_backtest(browser, url: str) -> None:
    """BT-1~BT-7 阈值回测页。

    BT-1 页面可开 + 概览条字段非空（含耗时）
    BT-2 **总览表行数 == API `symbols` 长度**（DOM↔API 对账，空集不算过）
    BT-3 值级对账：首页标的的「告警次数」DOM == API（**不由前端算**）
    BT-4 阈值口径明示（动态/回看/k 因子 + 回退阈值 chip 数 == 标的数）
    BT-5 口径 7 条**原文**在场（含「方向延续占比」这条，防被改成"预测准确率"）
    BT-6 375 档无横向溢出（表靠内层 `overflow-x` 滚动，不得撑破 document）
    BT-7 侧栏 12 项且本页 active =「阈值回测」
    """
    import urllib.request
    print("\n--- BT 阈值回测页（/backtest）---")
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    perrs: list[str] = []
    page.on("pageerror", lambda e: perrs.append(str(e)))
    try:
        resp = page.goto(url + "backtest", wait_until="load")
        page.wait_for_timeout(2500)
        d = page.evaluate(BT_JS)
        api = json.loads(urllib.request.urlopen(url + "api/backtest", timeout=30).read())

        check(resp is not None and resp.status == 200 and d["h1"] == "阈值回测",
              "BT-1 /backtest 可开且标题正确", (resp.status if resp else None, d["h1"]))
        check(all(d["stats"].values()) and d["stats"]["elapsed"].endswith("s"),
              "BT-1b 概览条四项均非空（含耗时）", d["stats"])
        check(len(api["symbols"]) > 0 and d["rowCount"] == len(api["symbols"]),
              "BT-2 总览表行数 == API symbols 长度", (d["rowCount"], len(api["symbols"])))
        # BT-3：首行=API 首个标的，且「告警次数」数值一致（DOM 只做展示，值来自 API）
        a0 = api["symbols"][0] if api["symbols"] else {}
        row_sym = (d["firstRow"] or ["", ""])[0]
        row_alerts = (d["firstRow"] or ["", "", "", ""])[2]
        check(row_sym == a0.get("symbol") and row_alerts == str(a0.get("alerts")),
              "BT-3 首页标的与告警次数 DOM == API（值级对账）",
              (row_sym, row_alerts, a0.get("symbol"), a0.get("alerts")))
        cfg = api.get("threshold_config") or {}
        check(bool(d["cfgMode"]) and bool(d["cfgLine"])
              and d["cfgChips"] == len(cfg.get("fallback") or []),
              "BT-4 阈值口径明示（模式 + 回看/k + 回退阈值 chip 数 == 标的数）",
              (d["cfgMode"], d["cfgChips"], len(cfg.get("fallback") or [])))
        check(d["methods"] == 7, "BT-5 口径说明 7 条在场", d["methods"])
        mtext = " ".join(api.get("methods") or [])
        check("方向延续" in mtext and "预测准确率" not in mtext,
              "BT-5b 「胜率 = 方向延续占比」原文在场，且未出现「预测准确率」误读", mtext[:60])
        check(d["detailsCount"] == len(api["symbols"]),
              "BT-5c 每标的详情块数 == 标的数", (d["detailsCount"], len(api["symbols"])))
        # BT-6：375 档
        page.set_viewport_size({"width": 375, "height": 812})
        page.wait_for_timeout(400)
        m375 = page.evaluate(BT_JS)
        check(m375["overflow"] == 0, "BT-6 375 档无横向溢出（表内层滚动，不撑破 document）",
              m375["overflow"])
        check(m375["stats"]["triggers"] == d["stats"]["triggers"],
              "BT-6b 375 档重排后关键数值不变（与桌面同源）",
              (m375["stats"]["triggers"], d["stats"]["triggers"]))
        check(d["navCount"] == 12 and (d["navActive"] or "").strip() == "阈值回测",
              "BT-7 侧栏 12 项且本页 active = 阈值回测", (d["navCount"], d["navActive"]))
        check(not perrs, "BT-8 /backtest console error = 0", perrs[:3])
    finally:
        page.close()




# ============ ST 设置页（/settings，2026-09-20）============
# 任务档 tasks/2026-09-20-settings-page/。**只读断言**：写路径（POST）由
# tests/test_web.py（4 条契约）+ tasks/2026-09-20-settings-page/journal.md 的人工闭环脚本覆盖；
# 验收脚本**绝不 POST 真实 config.json**。

ST_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const txt = (s) => { const e = q(s); return e ? e.textContent.trim() : null; };
  return {
    h1: txt('.st-head h1'),
    cfg: {
      dynamic: (q('#st-alert-dynamic') || {}).value || null,
      lookback: (q('#st-alert-lookback_days') || {}).value || null,
      k: (q('#st-alert-k_factor') || {}).value || null,
    },
    alertRows: document.querySelectorAll('#st-alert-grid .st-row').length,
    statusRows: document.querySelectorAll('#st-status-grid .st-row').length,
    envMarks: document.querySelectorAll('#st-alert-grid .st-envmark').length,
    saveDisabled: !!q('#st-save') && q('#st-save').disabled,
    saveText: txt('#st-save'),
    boundary: document.querySelectorAll('#st-boundary li').length,
    failHidden: !!q('#st-fail') && q('#st-fail').hidden,
    overflow: document.documentElement.scrollWidth - window.innerWidth,
    navCount: document.querySelectorAll('#sidebar .nav-item').length,
    navDisabled: document.querySelectorAll('#sidebar .nav-item.is-disabled').length,
    navActive: (q('#sidebar .nav-item.active') || {}).textContent || null,
  };
}
"""


def assert_settings(browser, url: str) -> None:
    """ST-1~ST-6 设置页（只读断言）。"""
    print("\n--- ST 设置页（/settings）---")
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    perrs: list[str] = []
    page.on("pageerror", lambda e: perrs.append(str(e)))
    try:
        resp = page.goto(url + "settings", wait_until="load")
        page.wait_for_timeout(2200)
        d = page.evaluate(ST_JS)
        check(resp is not None and resp.status == 200 and d["h1"] == "设置",
              "ST-1 /settings 可开且标题正确", (resp.status if resp else None, d["h1"]))
        check(d["cfg"]["dynamic"] in ("true", "false")
              and d["cfg"]["lookback"] not in (None, "")
              and d["cfg"]["k"] not in (None, ""),
              "ST-2 动态三参数在场且有值（开关/回看窗口/k 因子）", d["cfg"])
        check(d["alertRows"] == 8 and d["statusRows"] == 4,
              "ST-3 阈值 8 行 + 状态区间 4 行（白名单键数）", (d["alertRows"], d["statusRows"]))
        check(d["saveDisabled"] is False and "保存" in (d["saveText"] or ""),
              "ST-4 本地保存按钮可用（Railway 只读态由单测覆盖）", d["saveText"])
        check(d["boundary"] >= 5, "ST-5 口径与边界 ≥5 条（白名单拒绝/备份/env 优先/Railway 只读）",
              d["boundary"])
        check(d["navCount"] == 12 and d["navDisabled"] == 0
              and (d["navActive"] or "").strip() == "设置",
              "ST-6 侧栏 12 项、无占位项（navDisabled=0）且本页 active = 设置",
              (d["navCount"], d["navDisabled"], d["navActive"]))
        check(d["overflow"] == 0 and not perrs,
              "ST-7 1440 档无横向溢出且无 pageerror", (d["overflow"], perrs[:3]))
    finally:
        page.close()




# ============ PF 组合盈亏（自选列表，2026-09-20）============
# 任务档 tasks/2026-09-20-portfolio-pnl/。**只读断言**：不为验收伪造成本价
# （真实 config 里没录 cost 时，页面必须显示"未录成本价"的空态）。

PF_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const rows = Array.from(document.querySelectorAll('#watchlist-body tr'))
    .filter((tr) => !tr.classList.contains('sk-row'));
  const cells = Array.from(document.querySelectorAll('#watchlist-body td.pnl'));
  return {
    rowCount: rows.length,
    headerCount: document.querySelectorAll('.watchlist-table thead th').length,
    pnlCells: cells.map((td) => td.textContent.trim()),
    pnlClasses: cells.map((td) => {
      const s = td.querySelector('.chg-pill');
      return s ? s.className.replace('chg-pill', '').trim() : '(none)';
    }),
    overviewText: (q('#watchlist-pnl') || {}).textContent || '',
    overviewHidden: !!q('#watchlist-pnl') && q('#watchlist-pnl').hidden,
    overviewClass: (q('#watchlist-pnl') || {}).className || '',
    chgClasses: Array.from(document.querySelectorAll('#watchlist-body td.chg .chg-pill'))
      .map((s) => s.className.replace('chg-pill', '').trim()),
  };
}
"""


def assert_portfolio(browser, url: str) -> None:
    """PF-1~PF-5 组合盈亏（成本视角）。"""
    print("\n--- PF 组合盈亏（自选列表）---")
    api = {}
    try:
        with urllib.request.urlopen(url + "api/watchlist", timeout=30) as r:
            api = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"  /api/watchlist 读取失败: {exc}")
    ov = api.get("overview") or {}
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    try:
        page.goto(url, wait_until="load")
        page.wait_for_timeout(2600)
        d = page.evaluate(PF_JS)
        check(d["headerCount"] == 6, "PF-1 自选卡表头 6 列（含持仓盈亏）", d["headerCount"])
        check(len(d["pnlCells"]) == d["rowCount"] and d["rowCount"] > 0,
              "PF-2 每行都有盈亏单元格（列数一致，不错位）", (len(d["pnlCells"]), d["rowCount"]))
        # 无成本 ⇒ 「—」且不染色；**绝不允许出现 0.00%**
        bad_zero = [t for t in d["pnlCells"] if "0.00%" in t and t.strip() != "+0.00%"]
        check(len(bad_zero) == 0, "PF-3 无成本行不渲染成 0.00%（不显示假收益）", bad_zero)
        if ov.get("covered"):
            check(str(ov["covered"]) in d["overviewText"],
                  "PF-4 概览条数 == API covered（DOM↔API 对账）", (ov["covered"], d["overviewText"]))
            check("未含份额" in d["overviewText"],
                  "PF-4b 概览显式标注「未含份额」（防误读为组合总收益）", d["overviewText"])
        else:
            check("未录成本" in d["overviewText"] and not d["overviewHidden"],
                  "PF-4 无成本时空态文案在场（不是空白/不是隐藏）", d["overviewText"])
        same_ns = all((c == "(none)" or c in ("pos", "neg")) for c in d["pnlClasses"])
        check(same_ns, "PF-5 盈亏色沿用涨跌幅列的 pos/neg 命名空间（同色系）", d["pnlClasses"])
    finally:
        page.close()


if __name__ == "__main__":
    sys.exit(main())
