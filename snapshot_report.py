"""MarketPulse — 盘中快照生成器（独立入口）。

仅取数（按市场子集）→ 分类 → 渲染单板块快照 → 落盘；只读缓存作告警基准
（不写任何缓存）、不算涨跌幅、不写历史、不推送。

由 Hermes cron 在 A 股午盘/收盘、美股开盘/午盘（北京时间）触发，输出供用户按需查看。

用法:
    python snapshot_report.py                              # 美股午盘快照（us/noon）
    python snapshot_report.py --market a-share --time midday
    python snapshot_report.py --market us --time open
"""

from __future__ import annotations

import argparse
import logging

from src.alerter import run_alert_checks
from src.analyzer import build_statuses, get_market_date, load_history, load_last_values
from src.fetcher import fetch_all, fetch_sector_heat
from src.reporter import render_snapshot, save_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketpulse")


def main(market: str = "us", time: str = "noon") -> int:
    """取数（仅本市场子集）→ 分类 → 渲染单板块快照 → 落盘 → 告警检查（只读缓存基准）。
    market: a-share | us（默认 us）；time: open | midday | close | noon（默认 noon，设计 G）。"""
    date = get_market_date(market)
    log.info("MarketPulse 开始生成 %s 快照（市场=%s，时段=%s）", date, market, time)

    values, errors = fetch_all(market)
    sector_heat = fetch_sector_heat() if market == "a-share" else None
    last_values = load_last_values()  # 只读缓存作告警基准，不写 history/缓存
    statuses = build_statuses(values, errors, last_values, load_history())
    path = save_snapshot(
        date,
        render_snapshot(date, values, statuses, market, time, sector_heat=sector_heat),
        suffix=f"{market}-{time}",
    )
    try:  # 告警失败仅记日志，不影响快照生成（决策 H）
        run_alert_checks(date, values, last_values, f"{market}-{time}", path)
    except Exception as exc:
        log.warning("告警检查失败，不影响快照生成: %s", exc)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI：--market（默认 us）/ --time（默认 noon）。"""
    parser = argparse.ArgumentParser(description="MarketPulse 盘中快照生成器")
    parser.add_argument("--market", choices=("a-share", "us"), default="us",
                        help="快照市场：a-share（上证/深证/创业板）或 us（标普/纳斯达克），默认 us")
    parser.add_argument("--time", choices=("open", "midday", "close", "noon"), default="noon",
                        help="快照时段：open/midday/close/noon，默认 noon")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(args.market, args.time))


