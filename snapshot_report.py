"""MarketPulse — 午盘快照生成器（独立入口）。

仅取数 → 分类 → 渲染午盘快照 → 落盘；不读缓存、不算涨跌幅、不写历史、不推送。
由 Hermes cron 在美东 12:30（北京时间次日 00:30）触发，输出供用户按需查看。

用法:
    python snapshot_report.py
"""

from __future__ import annotations

import logging

from src.analyzer import build_statuses, get_us_eastern_date
from src.fetcher import fetch_all
from src.reporter import render_snapshot, save_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketpulse")


def main() -> int:
    """取数 → 分类 → 渲染午盘快照 → 落盘（reports/snapshots/YYYY-MM-DD-noon.md）。"""
    date = get_us_eastern_date()
    log.info("MarketPulse 开始生成 %s 午盘快照", date)

    values, errors = fetch_all()
    statuses = build_statuses(values, errors)
    path = save_snapshot(date, render_snapshot(date, values, statuses))
    log.info("快照已生成: %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
