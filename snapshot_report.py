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
from src.analyzer import build_statuses, get_market_date, is_market_holiday, load_history, load_last_values, merge_history
from src.fetcher import fetch_all, fetch_sector_heat
from src.reporter import render_snapshot, save_snapshot, generate_context
from src.git_ops import auto_commit_push

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketpulse")

def _is_market_closed(market: str, time: str) -> bool:
    """非交易日 gate（任务 H.5）：脚本级一处覆盖全 cron。

    a-share 任意时段周末休市；us 仅 open/noon 周末休市——us close/daily 按 ET 判定为
    有效（北京周六 08:00 = ET 周五收盘后，美股数据有效，不跳），测试钉死该边界。
    """
    if market == "a-share" and time in ("open", "midday", "close"):
        return is_market_holiday("a-share")
    if market == "us" and time in ("open", "noon"):
        return is_market_holiday("us")
    return False

def main(market: str = "us", time: str = "noon") -> int:
    """取数（仅本市场子集）→ 分类 → 渲染单板块快照 → 落盘 → 告警检查（只读缓存基准）。
    market: a-share | us | alt（默认 us）；time: open | midday | close | noon（默认 noon）。
    alt = 另类资产（GLD 黄金 / BTC 比特币），不参与告警。"""
    if _is_market_closed(market, time):
        log.info("休市，%s 时段=%s 无盘中数据，跳过生成（不取数/不渲染/不合并/不提交）", market, time)
        return 0
    date = get_market_date(market)
    log.info("MarketPulse 开始生成 %s 快照（市场=%s，时段=%s）", date, market, time)

    values, errors = fetch_all(market)
    sector_heat = fetch_sector_heat() if market == "a-share" else None
    last_values = load_last_values()  # 只读缓存作告警基准，不写 history/缓存
    history = load_history()
    # 读时剔除自身 date 行：本运行尚未 merge 写入，该行若存在（盘中其它入口已写）会污染
    # 动态阈值窗口/连涨串（决策 R4）；快照只在渲染/告警后把本次市场子集合并进当日行。
    history = [r for r in history if r.get("date") != date]
    statuses = build_statuses(values, errors, last_values, history)
    path = save_snapshot(
        date,
        render_snapshot(date, values, statuses, market, time, sector_heat=sector_heat),
        suffix=f"{market}-{time}",
    )
    try:  # 告警失败仅记日志，不影响快照生成（决策 H）
        run_alert_checks(date, values, last_values, f"{market}-{time}", path, history)
    except Exception as exc:
        log.warning("告警检查失败，不影响快照生成: %s", exc)
    # 读时剔除 + 渲染/告警之后，把本次市场子集（sh/sz/cyb 或 gspc/ixic 或 gld/btc）合并写回当日行；
    # 不整行覆盖，保留同日其它市场数据（决策 R1/R2）。取数全失败（values 空/全 None）→ 空操作。
    merge_history(date, values)
    # 更新 context（含 sector_heat），供 web 看板使用
    try:
        changes = {}
        for sym, val in values.items():
            prev = last_values.get(sym)
            if val is not None and prev is not None and prev != 0:
                changes[sym] = (val - prev) / prev * 100
        statuses = build_statuses(values, errors, last_values, history)
        generate_context(date, values, changes, statuses, last_values,
                         sector_heat=sector_heat if sector_heat else [])
        log.info("context 已更新: context/%s.json", date)
    except Exception as exc:
        log.warning("context 更新失败，不影响快照: %s", exc)
    # 二十六期：cron 执行后自动 commit + push；失败仅记日志、退出码恒 0
    auto_commit_push(date, f"{market} {time} snapshot")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析 CLI：--market（默认 us）/ --time（默认 noon）。"""
    parser = argparse.ArgumentParser(description="MarketPulse 盘中快照生成器")
    parser.add_argument("--market", choices=("a-share", "us", "alt"), default="us",
                        help="快照市场：a-share（上证/深证/创业板）、us（标普/纳斯达克）或 alt（黄金/比特币），默认 us")
    parser.add_argument("--time", choices=("open", "midday", "close", "noon"), default="noon",
                        help="快照时段：open/midday/close/noon，默认 noon")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(main(args.market, args.time))


