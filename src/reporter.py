"""报告渲染层：Markdown 日报、午盘快照、趋势图（matplotlib 懒加载 + 限时）、context 上下文 JSON。"""

from __future__ import annotations

import json
import logging
import os
import threading

from .alerter import collect_breaches
from .analyzer import (
    CHARTS_DIR,
    CONTEXT_DIR,
    REPORTS_DIR,
    SNAPSHOTS_DIR,
    build_search_keywords,
    fmt_change,
    fmt_value,
    load_history,
)
from .config import load_config
from .fetcher import SYMBOLS, STOCK_SYMBOLS, A_SHARE_SYMBOLS, ALT_SYMBOLS

log = logging.getLogger("marketpulse")

TREND_DAYS = int(load_config()["trend"]["chart_days"])   # 趋势图窗口（天），来自 config（import 时快照）
CHART_TIMEOUT = 15     # 绘图限时（秒），超时跳过绘图
MARKET_CHART_TIMEOUT = 5  # 分市场趋势图限时（秒），超时跳过该图（PRD ≤5s/图）

# 分市场趋势图注册表（设计 A）：market -> 面板（键/标签/配色）
MARKET_CHART_PANELS = {
    "us": [("gspc", "GSPC", "#2b6de8"), ("ixic", "IXIC", "#1a9e6c")],
    "cn": [("sh", "SH", "#d1495b"), ("sz", "SZ", "#e07600"), ("cyb", "CYB", "#7b5ce0")],
    "alt": [("gld", "GLD", "#d4a017"), ("btc", "BTC", "#f7931a")],
}
MARKET_CHART_TITLES = {
    "us": "US Major Indices — 30-Day Trend",
    "cn": "A-Share Major Indices — 30-Day Trend",
    "alt": "Gold & Bitcoin — 30-Day Trend",
}
def render_report(date, values, changes, statuses, summary, has_history, trend_chart=None, sector_heat=None, us_sector_heat=None, us_trend_chart=None, cn_trend_chart=None, alts_trend_chart=None) -> str:
    """按 PRD 模板渲染 Markdown 日报：美股大盘 + 波动率指数两板块（趋势图/总结不动）。

    trend_chart 为图表相对路径（如 "./charts/2026-08-29-trend.png"），
    提供时插入「近30日趋势」章节；None 则省略该章节。
    us_trend_chart / cn_trend_chart / alts_trend_chart 为分市场趋势图相对路径，提供时分别插入
    「美股大盘近30日趋势」/「A股大盘近30日趋势」/「另类资产近30日趋势」章节；None 则省略（设计 G）。
    """
    us_stock_syms = [s for s in SYMBOLS if s in STOCK_SYMBOLS and s not in A_SHARE_SYMBOLS]
    a_share_syms = [s for s in SYMBOLS if s in A_SHARE_SYMBOLS]
    vol_syms = [s for s in SYMBOLS if s not in STOCK_SYMBOLS and s not in ALT_SYMBOLS]
    alts_syms = [s for s in SYMBOLS if s in ALT_SYMBOLS]

    us_stock_rows = []
    for sym in us_stock_syms:
        meta = SYMBOLS[sym]
        trend, _ = statuses[sym]
        us_stock_rows.append(
            f"| {meta['label']} | {fmt_value(values[sym])} "
            f"| {fmt_change(changes[sym], has_history, values[sym])} | {trend} |"
        )
    us_stock_table = "\n".join(us_stock_rows)

    a_share_rows = []
    for sym in a_share_syms:
        meta = SYMBOLS[sym]
        trend, _ = statuses[sym]
        # A 股休市（取数失败/None）显示「休市」，与美股/波动率区分（六期 B 设计 B）
        close = "休市" if values[sym] is None else fmt_value(values[sym])
        a_share_rows.append(
            f"| {meta['label']} | {close} "
            f"| {fmt_change(changes[sym], has_history, values[sym])} | {trend} |"
        )
    a_share_table = "\n".join(a_share_rows)

    # 八期：A 股领涨 / 领跌板块 Top 5（按涨跌幅降序 / 升序，不设阈值；空数据显示「数据暂缺」）
    gainers, losers = sector_heat or ([], [])
    sector_table = _sector_table_md(gainers)
    loser_table = _sector_table_md(losers)

    # 美股板块领涨 / 领跌 Top 5（仅在有数据时渲染，避免无谓的「数据暂缺」占位）
    us_gainers, us_losers = us_sector_heat or ([], [])
    us_sector_block = ""
    if us_gainers or us_losers:
        us_sector_block = f"""
---

## 🔥 美股板块领涨 Top 5

| 板块 | 涨跌幅 | 成交额 | 领涨股 |
| :--- | :--- | :--- | :--- |
{_sector_table_md(us_gainers)}

---

## 📉 美股板块领跌 Top 5

| 板块 | 涨跌幅 | 成交额 | 领跌股 |
| :--- | :--- | :--- | :--- |
{_sector_table_md(us_losers)}
"""

    vol_rows = []
    for sym in vol_syms:
        meta = SYMBOLS[sym]
        status_label, _ = statuses[sym]
        vol_rows.append(
            f"| {meta['label']} | {fmt_value(values[sym])} "
            f"| {fmt_change(changes[sym], has_history, values[sym])} | {status_label} |"
        )
    vol_table = "\n".join(vol_rows)

    if values["VIX"] is not None:
        vix_label, vix_desc = statuses["VIX"]
        state_line = f"**VIX 当前值：{fmt_value(values['VIX'])} → 状态：{vix_label}**\n\n> {vix_desc}"
    else:
        state_line = "**VIX 当前值：获取失败 → 状态：无法判断**\n\n> VIX 数据获取失败，无法判断整体市场情绪。"

    # 九期：分市场趋势图章节（设计 G，默认 None → 省略）
    us_trend_block = ""
    if us_trend_chart:
        us_trend_block = f"""
---

## 📈 美股大盘近30日趋势

![美股大盘近30日趋势]({us_trend_chart})
"""
    cn_trend_block = ""
    if cn_trend_chart:
        cn_trend_block = f"""
---

## 📈 A股大盘近30日趋势

![A股大盘近30日趋势]({cn_trend_chart})
"""
    # 十期：另类资产板块（GLD/BTC）—— 不参与告警、复用大盘四档趋势标签；值缺失 → 获取失败
    alts_rows = []
    for sym in alts_syms:
        meta = SYMBOLS[sym]
        trend, _ = statuses[sym]
        alts_rows.append(
            f"| {meta['label']} | {fmt_value(values[sym])} "
            f"| {fmt_change(changes[sym], has_history, values[sym])} | {trend} |"
        )
    alts_table = "\n".join(alts_rows)

    # 十期：另类资产趋势图章节（设计 G，默认 None → 省略）
    alts_trend_block = ""
    if alts_trend_chart:
        alts_trend_block = f"""
---

## 📈 另类资产近30日趋势

![另类资产近30日趋势]({alts_trend_chart})
"""
    alts_block = f"""
---

## 💰 另类资产

| 资产 | 收盘价 | 涨跌幅 | 趋势 |
| :--- | :--- | :--- | :--- |
{alts_table}{alts_trend_block}
"""

    body = f"""# 📊 全市场情绪日报

**日期**：{date}（美东时间）

---

## 🌏 美股大盘

| 指数 | 收盘价 | 涨跌幅 | 趋势 |
| :--- | :--- | :--- | :--- |
{us_stock_table}{us_sector_block}{us_trend_block}

---

## 🇨🇳 A 股大盘

| 指数 | 收盘价 | 涨跌幅 | 趋势 |
| :--- | :--- | :--- | :--- |
{a_share_table}{cn_trend_block}{alts_block}

---

## 🔥 A 股热点板块 Top 5

| 板块 | 涨跌幅 | 成交额 | 领涨股 |
| :--- | :--- | :--- | :--- |
{sector_table}

---

## 📉 A 股领跌板块 Top 5

| 板块 | 涨跌幅 | 成交额 | 领跌股 |
|:--- | :--- | :--- | :--- |
{loser_table}

---

## 📈 波动率指数

| 指数 | 收盘价 | 涨跌幅 | 状态 |
| :--- | :--- | :--- | :--- |
{vol_table}
"""
    if trend_chart:
        body += f"""
---

## 📉 近30日趋势

![VIX/VXN/MOVE 近30日趋势]({trend_chart})
"""
    body += f"""
---

## 🏷️ 市场状态

{state_line}

---

## 📝 总结

{summary}

---
*本报告由 MarketPulse 自动生成 | 数据来源：Yahoo Finance*"""
    return body


def _sector_table_md(rows: list[dict]) -> str:
    """渲染领涨/领跌板块表格（A 股 / 美股板块共用）。rows 为空显示「数据暂缺」。"""
    lines = []
    for s in rows:
        sign = "+" if s["change"] >= 0 else ""
        lines.append(
            f"| {s['name']} | {sign}{s['change']:.2f}% | {s['turnover']} | {s['top_stock']} |"
        )
    if not lines:
        lines.append("| 数据暂缺 | — | — | — |")
    return "\n".join(lines)

def render_trend_chart(history: list[dict], date: str):
    """渲染近 30 日趋势图到 reports/charts/YYYY-MM-DD-trend.png，返回 Path 或 None。

    排除当日记录（同日重复运行不重绘当日点）；少于 2 个数据点跳过。
    matplotlib 懒加载（Agg 后端）；Windows 无 SIGALRM，用 daemon 线程 join(CHART_TIMEOUT)
    限时：超时记日志并返回 None，不中断整体流程。图表标签一律英文。
    """
    rows = [r for r in history if r.get("date") != date]
    rows = rows[-TREND_DAYS:]
    if len(rows) < 2:
        log.info("历史数据不足（%d 条），跳过趋势图", len(rows))
        return None

    result: dict = {}

    def _plot():
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime

        # 三面板配色（现代柔和，区分度高）
        panels = [
            ("move", "MOVE", "#e07600"),
            ("vxn", "VXN", "#ca3b7d"),
            ("vix", "VIX", "#2b6de8"),
        ]

        plt.rcParams["axes.edgecolor"] = "#d8d8d8"
        plt.rcParams["grid.color"] = "#ececec"

        # 用真实 datetime 作 x 轴（消除"分类轴字符串日期"警告）
        dt_dates = []
        for r in rows:
            try:
                dt_dates.append(datetime.strptime(r["date"], "%Y-%m-%d"))
            except (TypeError, ValueError):
                dt_dates.append(None)

        fig, axes = plt.subplots(3, 1, figsize=(10, 7.6), sharex=True,
                                 gridspec_kw={"hspace": 0.35})
        fig.suptitle("Volatility Outlook — 30-Day Trend", fontsize=13, y=0.975,
                     x=0.5, ha="center", fontweight="bold", color="#1b1b1b")

        for ax, (key, label, color) in zip(axes, panels):
            vals = [None if not isinstance(r.get(key), (int, float)) else r[key] for r in rows]
            finite = [(t, v) for t, v in zip(dt_dates, vals) if t is not None and v is not None]
            if not finite:
                continue
            xs = [t for t, _ in finite]
            ys = [v for _, v in finite]
            ax.plot(xs, ys, color=color, lw=2.3, solid_capstyle="round",
                    solid_joinstyle="round", zorder=3)
            ax.fill_between(xs, ys, min(ys) - 2, color=color, alpha=0.10, zorder=1)
            ax.grid(True, axis="y", alpha=0.6, lw=0.8)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            ax.spines["left"].set_visible(False)
            ax.tick_params(axis="y", labelsize=8, colors="#777777", length=0)
            ax.tick_params(axis="x", labelsize=8, colors="#777777")
            # 面板左上=指数名，右上=当前值；端点圆点
            ax.text(0.0, 1.02, label, transform=ax.transAxes, fontsize=12,
                    fontweight="bold", color=color, ha="left", va="bottom")
            ax.text(1.0, 1.02, f"{ys[-1]:.1f}", transform=ax.transAxes,
                    fontsize=11, color="#333333", ha="right", va="bottom",
                    fontweight="bold")
            ax.plot(xs[-1], ys[-1], "o", color=color, ms=5.5, zorder=4)
            ax.margins(x=0.02)

        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=7))

        fig.tight_layout()
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        out = CHARTS_DIR / f"{date}-trend.png"
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        result["path"] = out

    t = threading.Thread(target=_plot, daemon=True)
    t.start()
    t.join(CHART_TIMEOUT)
    if t.is_alive():
        log.warning("趋势图渲染超时（%ds），跳过", CHART_TIMEOUT)
        return None
    return result.get("path")



def render_market_trend_chart(history: list[dict], date: str, market: str):
    """渲染分市场近 30 日趋势图到 reports/charts/YYYY-MM-DD-{market}-trend.png，返回 Path 或 None。

    market ∈ {"us", "cn"}：us = 标普500/纳指 2×1，cn = 上证/深证/创业板 3×1。
    复用 render_trend_chart 的绘图范式（Agg 懒加载、线程限时、英文标签、datetime x 轴、面板样式）。
    排除当日记录；窗口内行数 <2 → 返回 None（整体跳过，报告省略该章节，设计 C）。
    某面板有限数据点 <2 → 中央显示灰色 "Insufficient Data" 占位，不画线（设计 B）；
    其余面板正常绘制，互不中断。非法 market → 返回 None（防御，不抛，设计 F）。
    """
    panels = MARKET_CHART_PANELS.get(market)
    if not panels:
        log.warning("未知市场 %r，跳过分市场趋势图", market)
        return None

    rows = [r for r in history if r.get("date") != date]
    rows = rows[-TREND_DAYS:]
    if len(rows) < 2:
        log.info("历史数据不足（%d 条），跳过 %s 趋势图", len(rows), market)
        return None

    result: dict = {}

    def _plot():
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime

        n = len(panels)
        figsize = (10, 5.4) if n == 2 else (10, 7.6)

        plt.rcParams["axes.edgecolor"] = "#d8d8d8"
        plt.rcParams["grid.color"] = "#ececec"

        dt_dates = []
        for r in rows:
            try:
                dt_dates.append(datetime.strptime(r["date"], "%Y-%m-%d"))
            except (TypeError, ValueError):
                dt_dates.append(None)

        fig, axes = plt.subplots(n, 1, figsize=figsize, sharex=True,
                                 gridspec_kw={"hspace": 0.35})
        fig.suptitle(MARKET_CHART_TITLES[market], fontsize=13, y=0.975,
                     x=0.5, ha="center", fontweight="bold", color="#1b1b1b")

        for ax, (key, label, color) in zip(axes, panels):
            vals = [None if not isinstance(r.get(key), (int, float)) else r[key] for r in rows]
            finite = [(t, v) for t, v in zip(dt_dates, vals) if t is not None and v is not None]
            ax.grid(True, axis="y", alpha=0.6, lw=0.8)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            ax.spines["left"].set_visible(False)
            ax.tick_params(axis="y", labelsize=8, colors="#777777", length=0)
            ax.tick_params(axis="x", labelsize=8, colors="#777777")
            # 面板左上=指数名（与既有面板对齐）
            ax.text(0.0, 1.02, label, transform=ax.transAxes, fontsize=12,
                    fontweight="bold", color=color, ha="left", va="bottom")
            if len(finite) < 2:
                # 有限数据点不足 2：中央占位文案（设计 B），不画线、不抛
                ax.text(0.5, 0.5, "Insufficient Data", transform=ax.transAxes,
                        fontsize=11, color="#999999", ha="center", va="center")
                continue
            xs = [t for t, _ in finite]
            ys = [v for _, v in finite]
            ax.plot(xs, ys, color=color, lw=2.3, solid_capstyle="round",
                    solid_joinstyle="round", zorder=3)
            ax.fill_between(xs, ys, min(ys) - 2, color=color, alpha=0.10, zorder=1)
            # 右上=当前值 + 端点圆点（与既有面板对齐）
            ax.text(1.0, 1.02, f"{ys[-1]:.1f}", transform=ax.transAxes,
                    fontsize=11, color="#333333", ha="right", va="bottom",
                    fontweight="bold")
            ax.plot(xs[-1], ys[-1], "o", color=color, ms=5.5, zorder=4)
            ax.margins(x=0.02)

        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        axes[-1].xaxis.set_major_locator(mdates.DayLocator(interval=7))

        fig.tight_layout()
        CHARTS_DIR.mkdir(parents=True, exist_ok=True)
        out = CHARTS_DIR / f"{date}-{market}-trend.png"
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        result["path"] = out

    t = threading.Thread(target=_plot, daemon=True)
    t.start()
    t.join(MARKET_CHART_TIMEOUT)
    if t.is_alive():
        log.warning("分市场趋势图渲染超时（%ds），跳过", MARKET_CHART_TIMEOUT)
        return None
    return result.get("path")

def render_snapshot(date, values, statuses, market=None, time="noon", sector_heat=None, us_sector_heat=None) -> str:
    """渲染盘中快照。market=None 保持原三板块午盘快照（美东 12:30）逐字不变；
    market="a-share"/"us" 走单板块渲染（仅大盘表 + 日期/类型行，无 VIX 状态行，设计 D）。"""
    if market is None:
        us_stock_syms = [s for s in SYMBOLS if s in STOCK_SYMBOLS and s not in A_SHARE_SYMBOLS]
        a_share_syms = [s for s in SYMBOLS if s in A_SHARE_SYMBOLS]
        vol_syms = [s for s in SYMBOLS if s not in STOCK_SYMBOLS and s not in ALT_SYMBOLS]
        us_stock_rows = [
            f"| {SYMBOLS[s]['label']} | {fmt_value(values[s])} | {statuses[s][0]} |"
            for s in us_stock_syms
        ]
        a_share_rows = [
            f"| {SYMBOLS[s]['label']} | {'休市' if values[s] is None else fmt_value(values[s])} | {statuses[s][0]} |"
            for s in a_share_syms
        ]
        vol_rows = [
            f"| {SYMBOLS[s]['label']} | {fmt_value(values[s])} | {statuses[s][0]} |"
            for s in vol_syms
        ]
        us_stock_table = "\n".join(us_stock_rows)
        a_share_table = "\n".join(a_share_rows)
        vol_table = "\n".join(vol_rows)
        if values["VIX"] is not None:
            vix_label, vix_desc = statuses["VIX"]
            state_line = f"**VIX 当前值：{fmt_value(values['VIX'])} → 状态：{vix_label}**\n\n> {vix_desc}"
        else:
            state_line = "**VIX 当前值：获取失败 → 状态：无法判断**\n\n> VIX 数据获取失败，无法判断整体市场情绪。"
        return f"""# 🕛 午盘快照

**日期**：{date}（美东时间）
**类型**：盘中快照（美东 12:30）

---

## 🌏 美股大盘

| 指数 | 当前值 | 趋势 |
| :--- | :--- | :--- |
{us_stock_table}

---

## 🇨🇳 A 股大盘

| 指数 | 当前值 | 趋势 |
| :--- | :--- | :--- |
{a_share_table}

---

## 📈 波动率指数

| 指数 | 当前值 | 状态 |
| :--- | :--- | :--- |
{vol_table}

---

## 🏷️ 市场状态

{state_line}

---
*本报告由 MarketPulse 自动生成 | 数据来源：Yahoo Finance*"""
    # 市场化单板块渲染（设计 A：us 仅大盘，不含波动率；设计 B：日期按市场时区）
    tz_label = "北京时间" if market == "a-share" else "美东时间"
    time_label = {"open": "开盘", "midday": "午盘", "close": "收盘", "noon": "午盘"}.get(time, "盘中")
    if market == "a-share":
        section_title = "🇨🇳 A 股大盘"
        syms = [s for s in SYMBOLS if s in A_SHARE_SYMBOLS]
    elif market == "alt":
        section_title = "💰 另类资产"
        syms = [s for s in SYMBOLS if s in ALT_SYMBOLS]
    else:
        section_title = "🌏 美股大盘"
        syms = [s for s in SYMBOLS if s in STOCK_SYMBOLS and s not in A_SHARE_SYMBOLS]
    rows = [
        f"| {SYMBOLS[s]['label']} | {'休市' if values[s] is None else fmt_value(values[s])} | {statuses[s][0]} |"
        for s in syms
    ]
    table = "\n".join(rows)
    body = f"""# 🕛 盘中快照

**日期**：{date}（{tz_label}）
**类型**：盘中快照（{time_label}）

---

## {section_title}

| 指数 | 当前值 | 趋势 |
| :--- | :--- | :--- |
{table}
"""
    if market == "a-share" and sector_heat is not None:
        gainers, losers = sector_heat
        sector_rows = []
        for s in gainers:
            sign = "+" if s["change"] >= 0 else ""
            sector_rows.append(
                f"| {s['name']} | {sign}{s['change']:.2f}% | {s['turnover']} | {s['top_stock']} |"
            )
        if not sector_rows:
            sector_rows.append("| 数据暂缺 | — | — | — |")
        loser_rows = []
        for s in losers:
            sign = "+" if s["change"] >= 0 else ""
            loser_rows.append(
                f"| {s['name']} | {sign}{s['change']:.2f}% | {s['turnover']} | {s['top_stock']} |"
            )
        if not loser_rows:
            loser_rows.append("| 数据暂缺 | — | — | — |")
        sector_table = "\n".join(sector_rows)
        loser_table = "\n".join(loser_rows)
        body += f"""
---

## 🔥 A 股热点板块 Top 5

| 板块 | 涨跌幅 | 成交额 | 领涨股 |
| :--- | :--- | :--- | :--- |
{sector_table}

---

## 📉 A 股领跌板块 Top 5

| 板块 | 涨跌幅 | 成交额 | 领跌股 |
|:--- | :--- | :--- | :--- |
{loser_table}
"""
    elif market == "us" and us_sector_heat is not None:
        us_g, us_l = us_sector_heat
        if us_g or us_l:
            body += f"""
---

## 🔥 美股板块领涨 Top 5

| 板块 | 涨跌幅 | 成交额 | 领涨股 |
| :--- | :--- | :--- | :--- |
{_sector_table_md(us_g)}

---

## 📉 美股板块领跌 Top 5

| 板块 | 涨跌幅 | 成交额 | 领跌股 |
| :--- | :--- | :--- | :--- |
{_sector_table_md(us_l)}
"""
    body += """
---

*本报告由 MarketPulse 自动生成 | 数据来源：Yahoo Finance*"""
    return body
def save_report(date: str, content: str) -> "Path":
    """写日报 reports/YYYY-MM-DD.md，返回路径。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{date}.md"
    path.write_text(content, encoding="utf-8")
    return path
def save_snapshot(date: str, content: str, suffix: str = "noon") -> "Path":
    """写盘中快照 reports/snapshots/YYYY-MM-DD-{suffix}.md，返回路径（设计 G：suffix 默认 noon，cron 传 {market}-{time}）。"""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"{date}-{suffix}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _breach_item(alert: dict) -> dict:
    """check_breach 原始 dict → context 契约字段（PRD 示例字段名；level 沿用 WARN/ALERT 大写）。"""
    return {
        "name": alert["symbol"],
        "current": alert["current"],
        "previous": alert["last"],
        "change_pct": round(alert["change"], 2),
        "threshold": alert["threshold"],
        "level": alert["level"],
    }
def generate_context(date: str, values: dict, changes: dict, statuses: dict,
                     last_values: dict, sector_heat=None, us_sector_heat=None) -> "Path":
    """生成 Hermes 上下文 context/YYYY-MM-DD.json（临时文件 + os.replace 原子写）。

    须在 append_history 之后调用（history_30d 才含当日）；不吞异常，由调用方 try/except
    兜底（决策 E）。返回写入路径。"""
    history = load_history()[-TREND_DAYS:]
    breaches = collect_breaches(values, last_values)
    payload = {
        "date": date,
        "indices": {
            sym: {
                "value": values.get(sym),
                "change_pct": changes.get(sym),
                "status": statuses[sym][0],
            }
            for sym in SYMBOLS
        },
        "history_30d": {
            "dates": [r["date"] for r in history],
            "vix": [r["vix"] for r in history],
            "vxn": [r["vxn"] for r in history],
            "move": [r["move"] for r in history],
            "gspc": [r["gspc"] for r in history],
            "ixic": [r["ixic"] for r in history],
            "sh": [r["sh"] for r in history],
            "sz": [r["sz"] for r in history],
            "cyb": [r["cyb"] for r in history],
            "gld": [r["gld"] for r in history],
            "btc": [r["btc"] for r in history],
        },
        "breach": {
            "triggered": bool(breaches),
            "indices": [_breach_item(a) for a in breaches],
        },
        "sector_heat": {
            "gainers": (sector_heat or ([], []))[0],
            "losers": (sector_heat or ([], []))[1],
        },
        "us_sector_heat": {
            "gainers": (us_sector_heat or ([], []))[0],
            "losers": (us_sector_heat or ([], []))[1],
        },
        "search_keywords": build_search_keywords(date, breaches, sector_heat),
    }
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    path = CONTEXT_DIR / f"{date}.json"
    tmp = CONTEXT_DIR / f"{date}.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path
