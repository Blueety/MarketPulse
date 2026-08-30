#!/usr/bin/env python
"""独立回测脚本：验证告警阈值有效性。只读 history，仅写 reports/backtest_report.md。

复用生产同一套告警语义（src.analyzer.check_breach：严格大于阈值、env/config 实时阈值、
缺口断开），回放历史触发事件并统计后效与有效触发率。无任何写回副作用。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from time import perf_counter

# 项目根入 path（支持 `python scripts/backtest.py` 与 `from scripts.backtest import ...`）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyzer import REPORTS_DIR, alert_threshold, check_breach, load_history

# 回测标的：PRD 表 7 个（CYB 有阈值但 PRD 表未列，默认不纳入，决策 A）。
BACKTEST_SYMBOLS = ["VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ"]

# 有效触发率判定：触发后 5 个交易日内出现任意单日 |变化率| ≥ 该百分比（决策 C）。
MEANINGFUL_MOVE_PCT = 1.0
# 后效窗口（交易日）。
HORIZONS = (1, 3, 5, 10)
# 样本门槛（决策 E）：全局有效交易日不足则优雅退出；单标的有效点不足仅输出计数。
MIN_EFFECTIVE_DAYS = 30
MIN_SYMBOL_POINTS = 30


def _sign(x: float) -> int:
    """数值符号：正 1 / 负 -1 / 零 0。"""
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _sym_key(symbol: str) -> str:
    """history 小写键（六期B 纪律：history 存 gspc/sh 等小写键）。"""
    return symbol.lower()


def load_backtest_history(history_path: str | None = None) -> list[dict]:
    """加载历史并按 date 升序排序。history_path 提供则只读该文件，否则用 analyzer.HISTORY_FILE。"""
    hist = _load_history_from_path(Path(history_path)) if history_path else load_history()
    hist = [r for r in hist if r.get("date")]
    hist.sort(key=lambda r: r["date"])
    return hist


def _load_history_from_path(path: Path) -> list[dict]:
    """从指定路径读取 history（与 load_history 同 schema，仅换只读输入源）。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    keys = ("vix", "vxn", "move", "gspc", "ixic", "sh", "sz", "cyb", "gld", "btc")
    return [
        {"date": str(rec.get("date", "")), **{k: rec.get(k) for k in keys}}
        for rec in data
        if isinstance(rec, dict) and rec.get("date")
    ]


def collect_triggers(history: list[dict], symbols=BACKTEST_SYMBOLS) -> list[dict]:
    """回放触发事件，复用生产 check_breach 语义（严格大于、实时阈值、缺口断开）。"""
    triggers: list[dict] = []
    for i in range(1, len(history)):
        for sym in symbols:
            key = _sym_key(sym)
            cur = history[i].get(key)
            prev = history[i - 1].get(key)
            if cur is None or prev is None:
                continue
            breach = check_breach(sym, cur, prev)
            if breach is None:
                continue
            triggers.append(
                {
                    "date": history[i]["date"],
                    "symbol": sym,
                    "change": breach["change"],
                    "threshold": breach["threshold"],
                    "level": breach["level"],
                    "price": cur,
                    "index": i,
                }
            )
    return triggers


def _effective_trading_days(history: list[dict], symbols=BACKTEST_SYMBOLS) -> int:
    """至少一个回测标的有相邻可计算变化的行数。"""
    cnt = 0
    for i in range(1, len(history)):
        for sym in symbols:
            key = _sym_key(sym)
            if history[i].get(key) is not None and history[i - 1].get(key) is not None:
                cnt += 1
                break
    return cnt


def _effective_points(history: list[dict], symbol: str) -> int:
    """该标的有相邻可计算变化的行数。"""
    key = _sym_key(symbol)
    return sum(
        1
        for i in range(1, len(history))
        if history[i].get(key) is not None and history[i - 1].get(key) is not None
    )


def forward_stats(triggers: list[dict], history: list[dict], horizons=HORIZONS) -> dict:
    """每标的每窗口：平均前向收益 / 胜率（方向延续占比）/ 样本数 n。"""
    by_sym: dict[str, list[dict]] = {}
    for t in triggers:
        by_sym.setdefault(t["symbol"], []).append(t)
    out: dict[str, dict[int, dict]] = {}
    for sym, ts in by_sym.items():
        key = _sym_key(sym)
        stats: dict[int, dict] = {}
        for h in horizons:
            rets: list[float] = []
            wins = 0
            for t in ts:
                i = t["index"]
                j = i + h
                if j >= len(history):
                    continue
                base = history[i].get(key)
                cur = history[j].get(key)
                if base is None or cur is None:
                    continue
                fr = (cur - base) / base * 100.0
                rets.append(fr)
                if _sign(fr) == _sign(t["change"]):
                    wins += 1
            n = len(rets)
            stats[h] = {
                "avg": (sum(rets) / n) if n else None,
                "win": (wins / n) if n else None,
                "n": n,
            }
        out[sym] = stats
    return out


def effective_trigger_rate(
    triggers: list[dict], history: list[dict], meaningful: float = MEANINGFUL_MOVE_PCT
) -> float | None:
    """触发后 5 个交易日内出现任意单日 |变化率| ≥ meaningful% 的触发占比。"""
    if not triggers:
        return None
    eff = 0
    for t in triggers:
        sym = t["symbol"]
        key = _sym_key(sym)
        i = t["index"]
        found = False
        for j in range(i + 1, min(i + 6, len(history))):
            cur = history[j].get(key)
            prev = history[j - 1].get(key)
            if cur is None or prev in (None, 0):
                continue
            if abs((cur - prev) / prev * 100.0) >= meaningful:
                found = True
                break
        if found:
            eff += 1
    return eff / len(triggers)


def annualized_frequency(triggers: list[dict], history: list[dict], symbol: str) -> float:
    """年化触发频率 = 触发次数 / 有效数据跨度天数 × 365（跨度 = 首个到末个有效点日期）。"""
    if not triggers:
        return 0.0
    key = _sym_key(symbol)
    dates = [
        history[i]["date"]
        for i in range(1, len(history))
        if history[i].get(key) is not None and history[i - 1].get(key) is not None
    ]
    if len(dates) < 2:
        return 0.0
    try:
        d0 = datetime.strptime(dates[0], "%Y-%m-%d")
        d1 = datetime.strptime(dates[-1], "%Y-%m-%d")
    except ValueError:
        return 0.0
    span = (d1 - d0).days
    if span < 1:
        return 0.0
    return len(triggers) / span * 365.0


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
        "- 数据源：`data/history.json`（只读）",
        "- 触发语义：生产 `check_breach`（严格大于阈值、缺口断开）",
        "- 阈值来源：config/env 实时配置（见下表，回测目的即验证当前阈值）",
        "",
        "## 各标的当前阈值",
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
        etr = effective_trigger_rate(sym_triggers, history)
        small = n_points < MIN_SYMBOL_POINTS
        lines += [
            f"## {sym}",
            "",
            f"- 阈值：{thr:.2f}%",
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
        f"- 触发检测：对历史相邻交易日 (prev, cur) 调用生产 `check_breach(sym, cur, prev)`，严格大于阈值才触发；阈值经 `alert_threshold(sym)` 实时读取 config/env。",
        f"- 有效交易日：至少一个回测标的有相邻可计算变化的行；全局门槛 {MIN_EFFECTIVE_DAYS} 天，不足则跳过回测。",
        f"- 单标的有效点：该标的有相邻可计算变化的行；门槛 {MIN_SYMBOL_POINTS} 点，不足仅输出计数与告警次数。",
        "- 后效：触发日后第 h 个交易日点对点收益 (p[t+h]-p[t])/p[t]×100%，缺口不阻断；窗口不足的样本不计入该窗口（n 透明展示）。",
        "- 胜率：前向收益与告警当日变化率同号（方向延续）的触发占比。",
        f"- 有效触发率：触发后 5 个交易日内出现任意单日 |变化率| ≥ {MEANINGFUL_MOVE_PCT:.1f}% 的触发占比。",
        "- 年化频率：告警次数 / 有效数据跨度天数 × 365。",
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
