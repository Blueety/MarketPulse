#!/usr/bin/env python
"""独立回测脚本（CLI 入口）：验证告警阈值有效性。只读 history，仅写 reports/backtest_report.md。

复用生产同一套告警语义（src.analyzer.check_breach：严格大于阈值、env/config 实时阈值、
缺口断开），回放历史触发事件并统计后效与有效触发率。无任何写回副作用。

2026-09-20（`tasks/2026-09-20-backtest-ui/`）：**纯统计逻辑已搬到 `src/backtest.py`**，
本文件只留「入口 + 呈现」——`render_report`（md）/ `print_summary`（终端）/ `main`（CLI）。
搬迁理由：看板要呈现同一份回测结果（`GET /api/backtest`），而 web 层不该 import `scripts/`；
这样 CLI 与 web **共用唯一实现**（避免同一算法两份实现）。
本文件 re-export 被搬迁的名字 ⇒ `tests/test_backtest.py` / `tests/test_phase27.py`
的 `bt.<name>` 用法**保持不变**。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from time import perf_counter

# 项目根入 path（支持 `python scripts/backtest.py` 与 `from scripts.backtest import ...`）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyzer import (REPORTS_DIR, alert_threshold,
                          ALERT_DYNAMIC, ALERT_LOOKBACK_DAYS, ALERT_K_FACTOR)
# 纯统计逻辑（唯一实现）在 src/backtest.py —— 此处 re-export，保持 `scripts.backtest` 既有用法。
from src.backtest import (  # noqa: F401  re-export：测试与外部按 bt.<name> 使用
    BACKTEST_SYMBOLS,
    HORIZONS,
    MEANINGFUL_MOVE_PCT,
    MIN_EFFECTIVE_DAYS,
    MIN_SYMBOL_POINTS,
    _effective_points,
    _effective_trading_days,
    annualized_frequency,
    collect_triggers,
    effective_trigger_rate,
    forward_stats,
    load_backtest_history,
    method_notes,
)


def render_report(history, triggers, fwd, run_date, eff_days) -> str:
    """渲染回测 Markdown 报告（纯事实数字，不输出任何结论性评语）。"""
    lines: list[str] = []
    first = history[0]["date"]
    last = history[-1]["date"]
    lines += [
        "# 告警阈值回测报告",
        "",
        f"- 运行日期：{run_date}",
        f"- 数据窗口：{first} ~ {last}",
        f"- 有效交易日：{eff_days}",
        "- 阈值来源：config/env 实时配置（下表为回退/固定阈值，动态模式激活时实际生效阈值由历史波动率计算）",
        "",
        "## 动态阈值参数（二十七期）",
        "",
        f"- 动态阈值启用：{'是' if ALERT_DYNAMIC else '否'}",
        f"- 回看窗口：{ALERT_LOOKBACK_DAYS} 个交易日",
        f"- k 因子：{ALERT_K_FACTOR}",
        f"- 回退阈值：下表 config/env 固定阈值（样本不足 / 关闭动态 / 零方差 / 计算值≤0 时生效）",
        "",
        "## 各标的当前（回退）阈值",
        "",
        "| 标的 | 阈值(%) |",
        "|---|---|",
    ]
    for sym in BACKTEST_SYMBOLS:
        lines.append(f"| {sym} | {alert_threshold(sym):.2f} |")
    lines.append("")

    for sym in BACKTEST_SYMBOLS:
        sym_triggers = [t for t in triggers if t["symbol"] == sym]
        n_alerts = len(sym_triggers)
        n_points = _effective_points(history, sym)
        thr = alert_threshold(sym)
        ann = annualized_frequency(sym_triggers, history, sym)
        levels = Counter(t["level"] for t in sym_triggers)
        modes = Counter(t["threshold_mode"] for t in sym_triggers)
        etr = effective_trigger_rate(sym_triggers, history)
        small = n_points < MIN_SYMBOL_POINTS
        lines += [
            f"## {sym}",
            "",
            f"- 回退阈值：{thr:.2f}%",
            f"- 阈值模式分布：dynamic {modes.get('dynamic', 0)} / fixed {modes.get('fixed', 0)}",
            f"- 有效点：{n_points}",
            f"- 告警次数：{n_alerts}",
            f"- 年化频率：{ann:.2f} 次/年",
            f"- WARN/ALERT 分布：WARN {levels.get('WARN', 0)} / ALERT {levels.get('ALERT', 0)}",
        ]
        if small:
            lines += [
                f"- 样本不足（有效点 < {MIN_SYMBOL_POINTS}），后效/胜率/有效触发率暂不统计，避免小样本误导。",
                "",
            ]
            continue
        etr_s = f"{etr * 100:.1f}%" if etr is not None else "—"
        lines += [
            f"- 有效触发率：{etr_s}",
            "",
            "### 后效（前向平均收益 / 胜率 / 样本数）",
            "",
            "| 窗口(日) | 平均收益(%) | 胜率 | 样本数 n |",
            "|---|---|---|---|",
        ]
        stats = fwd.get(sym, {})
        for h in HORIZONS:
            s = stats.get(h, {"avg": None, "win": None, "n": 0})
            avg = f"{s['avg']:.2f}" if s["avg"] is not None else "—"
            win = f"{s['win'] * 100:.1f}%" if s["win"] is not None else "—"
            lines.append(f"| {h} | {avg} | {win} | {s['n']} |")
        lines.append("")

    lines += [
        "## 总览对比",
        "",
        "| 标的 | 告警次数 | 年化(次/年) | 有效触发率 | 1日平均后效(%) | 3日平均后效(%) | 5日平均后效(%) | 10日平均后效(%) |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def _avg(sym, h):
        s = fwd.get(sym, {}).get(h)
        return f"{s['avg']:.2f}" if s and s["avg"] is not None else "—"

    for sym in BACKTEST_SYMBOLS:
        sym_triggers = [t for t in triggers if t["symbol"] == sym]
        n_alerts = len(sym_triggers)
        ann = annualized_frequency(sym_triggers, history, sym)
        etr = effective_trigger_rate(sym_triggers, history)
        etr_s = f"{etr * 100:.1f}%" if etr is not None else "—"
        lines.append(
            f"| {sym} | {n_alerts} | {ann:.2f} | {etr_s} | {_avg(sym, 1)} | {_avg(sym, 3)} | {_avg(sym, 5)} | {_avg(sym, 10)} |"
        )
    lines += [
        "",
        "## 方法说明",
        "",
        # 7 条口径原文取自 src/backtest.method_notes() —— 与看板 /api/backtest 的 methods[] **同一来源**，
        # 避免同一段措辞两份副本漂移（plan R9：措辞不得改写）。
        *method_notes(),
        "- 本脚本只读历史、仅写本报告文件，不写任何 data/alerts/context，不联网。",
        "",
    ]
    return "\n".join(lines)


def print_summary(history, triggers, fwd, eff_days, report_path, elapsed) -> None:
    """终端摘要：每标的一行 + 总耗时 + 报告路径。"""
    print("=" * 62)
    print(f"回测完成 | 有效交易日 {eff_days} | 触发事件 {len(triggers)} | 耗时 {elapsed:.3f}s")
    print("-" * 62)
    print(f"{'标的':<6}{'告警':>6}{'年化':>10}{'胜率@1d':>10}{'有效触发率':>12}")
    for sym in BACKTEST_SYMBOLS:
        sym_triggers = [t for t in triggers if t["symbol"] == sym]
        n_alerts = len(sym_triggers)
        ann = annualized_frequency(sym_triggers, history, sym)
        etr = effective_trigger_rate(sym_triggers, history)
        etr_s = f"{etr * 100:.1f}%" if etr is not None else "—"
        s1 = fwd.get(sym, {}).get(1)
        win1 = f"{s1['win'] * 100:.1f}%" if s1 and s1["win"] is not None else "—"
        print(f"{sym:<6}{n_alerts:>6}{ann:>10.2f}{win1:>10}{etr_s:>12}")
    print("-" * 62)
    print(f"报告：{report_path}")
    print("=" * 62)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="MarketPulse 告警阈值回测（只读历史，仅写 reports/backtest_report.md）"
    )
    parser.add_argument(
        "--history", default=None, help="可选：指定只读历史 JSON 路径（默认 data/history.json）"
    )
    args = parser.parse_args(argv)

    start = perf_counter()
    history = load_backtest_history(args.history)
    eff_days = _effective_trading_days(history, BACKTEST_SYMBOLS)
    if eff_days < MIN_EFFECTIVE_DAYS:
        print(f"历史有效交易日不足 {MIN_EFFECTIVE_DAYS} 天（{eff_days}），跳过回测。")
        return 0

    triggers = collect_triggers(history, BACKTEST_SYMBOLS)
    fwd = forward_stats(triggers, history)
    run_date = date.today().isoformat()
    report = render_report(history, triggers, fwd, run_date, eff_days)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / "backtest_report.md"
    report_path.write_text(report, encoding="utf-8")

    elapsed = perf_counter() - start
    print_summary(history, triggers, fwd, eff_days, report_path, elapsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
