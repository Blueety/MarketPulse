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
    const c = q('.card');
    if (!c) return null;
    const s = cs(c);
    return { boxSizing: s.boxSizing, borderRadius: s.borderRadius, background: s.backgroundColor,
             border: s.borderTopWidth, shadow: s.boxShadow !== 'none' };
  })();
  const sidebar = q('#sidebar');
  const sbRect = sidebar ? sidebar.getBoundingClientRect() : null;
  return {
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


def measure(page, url: str, w: int, h: int) -> dict:
    page.set_viewport_size({"width": w, "height": h})
    page.goto(url, wait_until="load")
    page.wait_for_timeout(4500)   # 等 watchlist(≤12s) / macro 与本机取数
    data = page.evaluate(MEASURE_JS)
    dark = os.path.join(OUT_DIR, f"shot-{w}x{h}.png")
    page.screenshot(path=dark, full_page=True)
    return data


def assert_viewport(w: int, h: int, m: dict) -> None:
    print(f"\n--- {w}x{h} ---")
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
            errors: list[str] = []
            page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: errors.append(f"pageerror: {err}"))

            for (w, h) in VIEWPORTS:
                m = measure(page, url, w, h)
                assert_viewport(w, h, m)
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
            check(int(m["zSidebar"] or 0) > 55 and int(m["zTopbar"] or 0) > int(m["zSidebar"] or 0),
                  "层级 topbar > sidebar > backdrop", (m["zTopbar"], m["zSidebar"], m["zBackdrop"]))
            check(m["marketStatus"] in ("市场已开盘", "休市") and "北京时间" in (m["marketTime"] or ""),
                  "侧栏市场状态 + 北京时间", (m["marketStatus"], m["marketTime"]))

            # 主题切换（深浅双套 token）
            bg_before = m["card"]["background"]
            theme_after = page.evaluate(
                """() => {
                    document.getElementById('sidebar-theme').click();
                    const c = document.querySelector('.card');
                    return { theme: document.documentElement.getAttribute('data-theme'),
                             ls: localStorage.getItem('mp-theme'),
                             bg: getComputedStyle(c).backgroundColor,
                             chartAlive: !!(window.Chart && window.Chart.getChart(document.getElementById('chart-main'))) };
                }"""
            )
            page.wait_for_timeout(600)
            check(theme_after["theme"] != m["htmlTheme"], "切换后 data-theme 变化",
                  (m["htmlTheme"], theme_after["theme"]))
            check(theme_after["ls"] == theme_after["theme"], "localStorage 与主题一致", theme_after["ls"])
            check(bg_before != theme_after["bg"], "切换后卡片底色变化", (bg_before, theme_after["bg"]))
            check(theme_after["chartAlive"], "切主题后图表实例存活")

            # 4 个类别 tab 切换（无「Canvas is already in use」）
            errors.clear()
            tab_result = page.evaluate(
                """async () => {
                    const out = [];
                    const btns = [...document.querySelectorAll('#trend-tabs button')];
                    for (const b of btns) {
                      b.click();
                      await new Promise(r => setTimeout(r, 350));
                      out.push({ name: b.textContent,
                                 active: b.classList.contains('active'),
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

            # 375 档：抽屉 + 单列
            page.set_viewport_size({"width": 375, "height": 812})
            page.goto(url, wait_until="load")
            page.wait_for_timeout(3500)
            mob = page.evaluate(
                """() => {
                    const sb = document.getElementById('sidebar');
                    const before = getComputedStyle(sb).transform;
                    document.getElementById('menu-toggle').click();
                    return { pos: getComputedStyle(sb).position,
                             open: document.body.classList.contains('nav-open'),
                             transform: getComputedStyle(sb).transform,
                             before: before,
                             chartWrapH: Math.round(document.getElementById('chart-main-wrap').getBoundingClientRect().height),
                             scrollW: document.scrollingElement.scrollWidth,
                             innerW: window.innerWidth };
                }"""
            )
            page.wait_for_timeout(400)
            check(mob["pos"] == "fixed", "375 侧栏为 fixed 抽屉", mob["pos"])
            check(mob["open"] and mob["transform"] != mob["before"], "点击菜单后抽屉展开", mob)
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
