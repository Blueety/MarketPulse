"""MarketPulse — 每日波动率指数日报生成器（编排入口）。

流程：取数 → 读缓存/历史 → 算涨跌幅 → 渲染报告 + 趋势图 → 写报告 → 告警检查 → 追加历史 → 写缓存。
脚本不包含推送逻辑（由 Hermes 读取报告并推送）。

用法:
    python daily_report.py
"""

from __future__ import annotations

import logging

from src.alerter import run_alert_checks
from src.northbound import fetch_northbound_flow
from src.analyzer import (
    append_history,
    build_statuses,
    build_summary,
    compute_changes,
    compute_correlation,
    compute_portfolio_correlation,
    get_us_eastern_date,
    load_history,
    load_last_values,
    save_last_values,
)
from src.config import load_config
from src.fetcher import SYMBOLS, fetch_all, fetch_sector_heat, fetch_us_sector_heat, fetch_watchlist
from src.news_fetcher import search_news
from src.reporter import (generate_context, render_market_trend_chart, render_report,
                          render_trend_chart, save_report, load_opening_refs)
from src.image_renderer import render_report_image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketpulse")


def _build_watchlist_view(stocks_cfg, values, series, corr) -> dict:
    """合并配置 + 取数结果 + 相关性 → 渲染/context 统一视图（二十四期）。

    涨跌幅由序列相邻日自算（首日即有）；value 缺失 → available=False（整板块占位）。
    """
    corr_map = {c["symbol"]: c for c in (corr or {}).get("stocks", [])}
    stocks_view = []
    available = False
    for it in stocks_cfg:
        sym = it["symbol"]
        label = it.get("label", sym)
        s = series.get(sym) or []
        val = values.get(sym)
        change = None
        if len(s) >= 2 and s[-2][1] not in (None, 0):
            change = (s[-1][1] - s[-2][1]) / s[-2][1] * 100.0
        c = corr_map.get(sym, {})
        if val is not None:
            available = True
        stocks_view.append({
            "symbol": sym,
            "label": label,
            "value": val,
            "change_pct": round(change, 2) if change is not None else None,
            "r": c.get("r"),
            "n": c.get("n", 0),
            "benchmark": c.get("benchmark"),
            "news": None,
        })
    return {
        "available": available,
        "stocks": stocks_view,
        "portfolio_risk": (corr or {}).get("portfolio_risk", {"high": False, "avg_r": None}),
    }


def _attrib_watchlist_news(label: str, symbol: str, change_pct: float) -> str | None:
    """涨跌幅 >2% 的自选股搜索 Tavily 新闻，返回 1-2 句标题摘要；失败返回 None（不影响主流程）。"""
    try:
        direction = "大涨" if change_pct > 0 else "大跌"
        results = search_news(f"{label} {symbol} {direction} 新闻")
        if not results:
            return "暂无相关新闻"
        titles = [r["title"] for r in results[:2] if r.get("title")]
        if not titles:
            return "暂无相关新闻"
        return "；".join(titles)
    except Exception as exc:
        log.warning("自选股 %s 新闻归因失败: %s", symbol, exc)
        return None


_US_GATE = ("gspc", "ixic")   # D1：去重判定符号集（小写键），美股两大盘指数


def _is_us_duplicate_day(history: list[dict], record: dict) -> bool:
    """美股（GSPC/IXIC）与最近历史记录全同 → True（非交易日重复，跳过写历史）。

    排除 MOVE（浮点抖动 70.965→70.9655 会误判）；其余键（A 股/另类）变动不阻止
    跳过（D2：混合日整条跳过，PRD 字面）。history 为空（首跑）→ False。
    """
    if not history:
        return False
    prev = history[-1]
    return all(prev.get(k) == record.get(k) for k in _US_GATE)


def main() -> int:
    """完整流程：取数 → 读缓存/历史 → 算涨跌幅 → 渲染报告 + 趋势图 → 写报告 → 告警检查 → 追加历史 → 写缓存。"""
    date = get_us_eastern_date()
    log.info("MarketPulse 开始生成 %s 日报", date)

    values, errors = fetch_all()
    sector_heat = fetch_sector_heat()  # 八期：板块热度，失败/超时返回 [] 不影响主流程
    us_sector_heat = fetch_us_sector_heat()  # 美股板块领涨/领跌，失败/超时返回 [] 不影响主流程

    # 北向资金获取（独立容错，失败不影响日报）
    northbound_data = None
    try:
        northbound_data = fetch_northbound_flow()
        if northbound_data:
            log.info("北向资金: 净流入 %.2f 亿元", northbound_data["net_inflow"])
        else:
            log.info("北向资金数据暂缺（所有数据源失败）")
    except Exception as exc:
        log.warning("北向资金获取异常（不影响日报）: %s", exc)
        northbound_data = None

    last_values = load_last_values()
    has_history = bool(last_values)
    changes = compute_changes(values, last_values)
    history = load_history()

    # 二十四期：自选股/持仓关联（独立容错，失败不影响主流程/退出码）
    watchlist_view = None
    try:
        wl_cfg = load_config().get("watchlist", {"stocks": [], "corr_high_threshold": 0.7})
        stocks_cfg = wl_cfg.get("stocks") or []
        if stocks_cfg:
            wl_values, wl_series, wl_errors = fetch_watchlist(stocks_cfg)
            wl_data = [
                {"symbol": it["symbol"], "label": it.get("label", it["symbol"]),
                 "series": wl_series.get(it["symbol"])}
                for it in stocks_cfg
            ]
            wl_corr = compute_portfolio_correlation(
                wl_data, history, threshold=wl_cfg.get("corr_high_threshold")
            )
            watchlist_view = _build_watchlist_view(stocks_cfg, wl_values, wl_series, wl_corr)
            # 新闻归因：涨跌幅 > 2% 的标的搜索 Tavily
            for st in watchlist_view["stocks"]:
                if (st["change_pct"] is not None and abs(st["change_pct"]) > 2.0
                        and st["value"] is not None):
                    st["news"] = _attrib_watchlist_news(st["label"], st["symbol"], st["change_pct"])
    except Exception as exc:
        log.warning("自选股处理失败，跳过板块: %s", exc)
        watchlist_view = None
    correlations = compute_correlation(history)   # 十二期：相关性分析（报告/context 同一份数值）
    statuses = build_statuses(values, errors, last_values, history)
    summary = build_summary(values, statuses, errors)

    chart_path = render_trend_chart(history, date)
    trend_chart = f"./charts/{chart_path.name}" if chart_path else None

    # 九期：分市场趋势图（设计 F：各自独立失败，超时/异常 → None，不影响其他图与日报）
    us_trend_path = None
    cn_trend_path = None
    try:
        us_trend_path = render_market_trend_chart(history, date, "us")
    except Exception as exc:
        log.warning("美股趋势图渲染失败，跳过: %s", exc)
    try:
        cn_trend_path = render_market_trend_chart(history, date, "cn")
    except Exception as exc:
        log.warning("A股趋势图渲染失败，跳过: %s", exc)
    us_trend_chart = f"./charts/{us_trend_path.name}" if us_trend_path else None
    cn_trend_chart = f"./charts/{cn_trend_path.name}" if cn_trend_path else None
    alts_trend_path = None
    try:
        alts_trend_path = render_market_trend_chart(history, date, "alt")
    except Exception as exc:
        log.warning("另类资产趋势图渲染失败，跳过: %s", exc)

    alts_trend_chart = f"./charts/{alts_trend_path.name}" if alts_trend_path else None
    # 十五期：读当日开盘分析引用（美股/A 股按美东日期匹配），失败仅记日志不影响日报
    opening_refs = []
    try:
        opening_refs = load_opening_refs(date)
    except Exception as exc:
        log.warning("开盘分析引用加载失败，跳过: %s", exc)

    report = render_report(date, values, changes, statuses, summary, has_history, trend_chart,
                           sector_heat=sector_heat, us_sector_heat=us_sector_heat,
                           us_trend_chart=us_trend_chart, cn_trend_chart=cn_trend_chart,
                           alts_trend_chart=alts_trend_chart, correlations=correlations,
                           opening_refs=opening_refs, watchlist=watchlist_view,
                           northbound=northbound_data)
    report_path = save_report(date, report)
    log.info("报告已生成: %s", report_path)

    record = {"date": date, **{k.lower(): values[k] for k in SYMBOLS}}
    if _is_us_duplicate_day(history, record):
        log.info("美股数据与最近记录相同（非交易日），跳过历史追加: %s", date)
    else:
        append_history(record)
        log.info("历史已追加: %s", record)
    try:  # 告警检查：save_last_values 前用旧缓存作基准（决策 G），失败仅记日志（决策 H）
        run_alert_checks(date, values, last_values, "close", report_path)
    except Exception as exc:
        log.warning("告警检查失败，不影响日报生成: %s", exc)

    # 北向资金异动告警（独立于指数告警）
    try:
        from src.alerter import check_northbound_alert
        check_northbound_alert(date, northbound_data, report_path)
    except Exception as exc:
        log.warning("北向资金告警检查失败（不影响日报）: %s", exc)


    saved = {k: v for k, v in values.items() if v is not None}
    if saved:
        save_last_values(saved, date)
        log.info("缓存已更新")
    else:
        log.warning("所有数据源获取失败，本次不更新缓存")

    try:  # 上下文生成（决策 E）：供 Hermes 常规解读/异动归因，失败仅记日志不影响日报
        generate_context(date, values, changes, statuses, last_values, sector_heat=sector_heat, us_sector_heat=us_sector_heat, correlations=correlations, watchlist=watchlist_view, northbound=northbound_data)
        log.info("context 已生成: context/%s.json", date)
    except Exception as exc:
        log.warning("context 生成失败，不影响日报: %s", exc)

    try:  # 十四期：图片化推送（决策 E）：失败仅记日志，不影响日报主流程与退出码
        image_path = render_report_image(date)
        if image_path:
            log.info("日报图片已生成: %s", image_path)
    except Exception as exc:
        log.warning("日报图片渲染失败，不影响日报: %s", exc)

    return 0  # 全源失败也恒为 0，避免 Hermes 定时任务误报警


if __name__ == "__main__":
    raise SystemExit(main())
