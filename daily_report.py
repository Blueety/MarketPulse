"""MarketPulse — 每日波动率指数日报生成器（编排入口）。

流程：取数 → 读缓存/历史 → 算涨跌幅 → 渲染报告 + 趋势图 → 写报告 → 告警检查 → 追加历史 → 写缓存。
脚本不包含推送逻辑（由 Hermes 读取报告并推送）。

用法:
    python daily_report.py
"""

from __future__ import annotations

import logging

from src.alerter import run_alert_checks
from src.analyzer import (
    append_history,
    build_statuses,
    build_summary,
    compute_changes,
    compute_correlation,
    get_us_eastern_date,
    load_history,
    load_last_values,
    save_last_values,
)
from src.fetcher import SYMBOLS, fetch_all, fetch_sector_heat, fetch_us_sector_heat
from src.reporter import generate_context, render_market_trend_chart, render_report, render_trend_chart, save_report
from src.image_renderer import render_report_image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketpulse")


def main() -> int:
    """完整流程：取数 → 读缓存/历史 → 算涨跌幅 → 渲染报告 + 趋势图 → 写报告 → 告警检查 → 追加历史 → 写缓存。"""
    date = get_us_eastern_date()
    log.info("MarketPulse 开始生成 %s 日报", date)

    values, errors = fetch_all()
    sector_heat = fetch_sector_heat()  # 八期：板块热度，失败/超时返回 [] 不影响主流程
    us_sector_heat = fetch_us_sector_heat()  # 美股板块领涨/领跌，失败/超时返回 [] 不影响主流程
    last_values = load_last_values()
    has_history = bool(last_values)
    changes = compute_changes(values, last_values)
    history = load_history()
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

    report = render_report(date, values, changes, statuses, summary, has_history, trend_chart,
                           sector_heat=sector_heat, us_sector_heat=us_sector_heat,
                           us_trend_chart=us_trend_chart, cn_trend_chart=cn_trend_chart,
                           alts_trend_chart=alts_trend_chart, correlations=correlations)
    report_path = save_report(date, report)
    log.info("报告已生成: %s", report_path)

    try:  # 告警检查：save_last_values 前用旧缓存作基准（决策 G），失败仅记日志（决策 H）
        run_alert_checks(date, values, last_values, "close", report_path)
    except Exception as exc:
        log.warning("告警检查失败，不影响日报生成: %s", exc)

    record = {"date": date, **{k.lower(): values[k] for k in SYMBOLS}}
    append_history(record)
    log.info("历史已追加: %s", record)

    saved = {k: v for k, v in values.items() if v is not None}
    if saved:
        save_last_values(saved, date)
        log.info("缓存已更新")
    else:
        log.warning("所有数据源获取失败，本次不更新缓存")

    try:  # 上下文生成（决策 E）：供 Hermes 常规解读/异动归因，失败仅记日志不影响日报
        generate_context(date, values, changes, statuses, last_values, sector_heat=sector_heat, us_sector_heat=us_sector_heat, correlations=correlations)
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
