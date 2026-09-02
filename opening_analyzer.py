"""MarketPulse — 开盘分析生成器（独立入口）。

开盘后 15-30 分钟生成开盘分析：对比昨收价分析开盘跳空、板块轮动（开盘热点）、
市场情绪（VIX + 大盘方向）。仅读新浪实时行情 + 只写自己的报告文件，零持久化
（不写 history / last_values / context / alerts.log）。AI 解读由 Hermes 追加重渲染。

用法:
    python opening_analyzer.py                         # A 股开盘分析（默认 a-share）
    python opening_analyzer.py --market a-share
    python opening_analyzer.py --market us
"""

from __future__ import annotations

import argparse
import logging

from src.analyzer import classify_vix, get_market_date
from src.fetcher import fetch_realtime_quotes, fetch_sector_heat, fetch_us_sector_heat
from src.reporter import render_opening_report, save_opening

from src.git_ops import auto_commit_push
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketpulse")


def compute_gaps(quotes: dict) -> dict:
    """计算各指数开盘跳空与当前涨跌（%）。

    open_gap = (open - prev_close) / prev_close * 100；current_change = (current - prev_close) / prev_close * 100。
    VIX 不计算跳空；prev_close 缺失（None/0）→ 对应项 None（不除零）。
    """
    gaps: dict = {}
    for sym, q in quotes.items():
        if sym == "VIX":
            continue
        pc = q.get("prev_close")
        op = q.get("open")
        cur = q.get("current")
        gaps[sym] = {
            "open_gap": (op - pc) / pc * 100 if (op is not None and pc) else None,
            "current_change": (cur - pc) / pc * 100 if (cur is not None and pc) else None,
        }
    return gaps


def build_opening_sentiment(quotes: dict, errors: dict) -> dict:
    """确定性开盘情绪：VIX 状态 + 大盘整体方向（跳空均值符号）。

    VIX 有值 → classify_vix 状态 + 描述；缺失 → 「数据暂缺」。
    大盘方向 = 跳空均值符号（高开/低开/平开，|均值|<0.3% 记平开）；无跳空数据 → 平开。
    """
    vix = quotes.get("VIX")
    if vix and vix.get("current") is not None:
        label, desc = classify_vix(vix["current"])
        vix_state = {
            "value": vix["current"],
            "label": label,
            "desc": desc,
            "prev_close": vix.get("prev_close"),
        }
    else:
        vix_state = {
            "value": None,
            "label": "数据暂缺",
            "desc": "VIX 数据暂缺，无法判断开盘情绪",
            "prev_close": None,
        }

    gaps = compute_gaps(quotes)
    avg_gaps = [g["open_gap"] for g in gaps.values() if g["open_gap"] is not None]
    if avg_gaps:
        avg = sum(avg_gaps) / len(avg_gaps)
        if abs(avg) < 0.3:
            direction = "平开"
        elif avg > 0:
            direction = "高开"
        else:
            direction = "低开"
    else:
        avg = None
        direction = "平开"
    return {"vix": vix_state, "direction": direction, "avg_gap": avg}


def main(market: str = "a-share") -> int:
    """开盘分析编排：取实时行情 → 板块热度 → 跳空/情绪 → 渲染 → 落盘。

    不调用 run_alert_checks（开盘分析不告警），不写任何缓存/历史/context。
    全源失败也恒返回 0，避免 Hermes cron 误报警。
    """
    date = get_market_date(market)
    log.info("MarketPulse 开始生成 %s 开盘分析（市场=%s）", date, market)

    quotes, errors = fetch_realtime_quotes(market)
    # 开盘热点板块：A 股走概念板块、美股走 SPDR 行业 ETF；失败/超时返回 ([], []) 降级
    sector_heat = fetch_sector_heat() if market == "a-share" else fetch_us_sector_heat()
    gaps = compute_gaps(quotes)
    sentiment = build_opening_sentiment(quotes, errors)
    path = save_opening(
        date,
        market,
        render_opening_report(date, market, quotes, gaps, sentiment, sector_heat, errors),
    )
    log.info("开盘分析已生成: %s", path)
    # 二十六期：cron 执行后自动 commit + push；失败仅记日志、退出码恒 0
    auto_commit_push(date, f"{market} opening analysis")
    return 0  # 全源失败也恒 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI：--market（默认 a-share；裸跑 = A 股开盘分析）。"""
    parser = argparse.ArgumentParser(description="MarketPulse 开盘分析生成器")
    parser.add_argument("--market", choices=("a-share", "us"), default="a-share",
                        help="开盘分析市场：a-share（上证/深证/创业板）或 us（标普/纳斯达克），默认 a-share")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(args.market))
