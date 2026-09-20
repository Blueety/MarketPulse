"""回测纯统计逻辑（2026-09-20 从 `scripts/backtest.py` 搬迁；**唯一实现**）。

任务档：`tasks/2026-09-20-backtest-ui/`

**为什么搬到 `src/`**：回测结果现在要在看板上呈现（`GET /api/backtest`），而 `scripts/` 的定位是
「独立入口脚本」（见 `AGENTS.md`）—— web 层不该 import 它。搬迁后 CLI（`scripts/backtest.py`）
与 web **共用同一份**计算，避免「同一算法两份实现」（本项目头号禁忌）。
先例：`src/timeline.py`（纯逻辑在 `src/`）+ `scripts/sync_econ_calendar.py`（入口）。

**留在 `scripts/backtest.py` 的**：`render_report`（md 渲染）/ `print_summary` / `main`（CLI 与退出码）、
`REPORTS_DIR` 与动态阈值常量（`ALERT_*`）—— 那是「入口 + 呈现」职责，不是纯统计。

⚠️ 本文件是**逐字搬迁**：函数体与 docstring 一字未改（改动即会让搬迁正确性无从证明）。
回归护栏是 `tests/test_backtest.py`（10 条，**未改动**）+ 报告 md 逐字节相同。
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.analyzer import (ALERT_DYNAMIC, ALERT_K_FACTOR, ALERT_LOOKBACK_DAYS,
                          alert_threshold, check_breach, load_history)

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
    """回放触发事件，复用生产 check_breach 语义（严格大于、实时阈值、缺口断开）。

    动态阈值：回放第 i 对 (rows[i-1], rows[i]) 时传 history[:i]（排除候选行 i，
    窗口含到 prev 行为止的收益，等价于生产「昨日收益是分布最新成员」）。"""
    triggers: list[dict] = []
    for i in range(1, len(history)):
        for sym in symbols:
            key = _sym_key(sym)
            cur = history[i].get(key)
            prev = history[i - 1].get(key)
            if cur is None or prev is None:
                continue
            breach = check_breach(sym, cur, prev, history[:i])
            if breach is None:
                continue
            triggers.append(
                {
                    "date": history[i]["date"],
                    "symbol": sym,
                    "change": breach["change"],
                    "threshold": breach["threshold"],
                    "threshold_mode": breach["threshold_mode"],
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


# ---- 口径说明与 payload 组装（2026-09-20，看板 `GET /api/backtest` 用）------------------------
# ⚠️ 下面这两个函数**不是**从 scripts/ 搬来的，是本次新增；上面搬迁部分保持逐字未改。

def method_notes() -> list[str]:
    """口径说明 **7 条原文**（md 报告「方法说明」节）。

    🔴 单一事实来源：CLI 的 `render_report`（`scripts/backtest.py`）与看板
    `GET /api/backtest` 的 `methods[]` **都从这里取** —— 避免同一段措辞两份副本漂移。
    **措辞不得改写**（plan R9）：「胜率」是**方向延续占比**，**不是**预测准确率 ——
    这是最容易被误读的一条。
    """
    return [
        f"- 触发检测：对历史相邻交易日 (prev, cur) 调用生产 `check_breach(sym, cur, prev, history[:i])`，严格大于阈值才触发；阈值经 `alert_threshold(sym)` 实时读取 config/env，动态模式激活时按历史波动率（history[:i] 排除候选当日）计算生效阈值，样本不足/关闭时回退固定阈值。",
        f"- 有效交易日：至少一个回测标的有相邻可计算变化的行；全局门槛 {MIN_EFFECTIVE_DAYS} 天，不足则跳过回测。",
        f"- 单标的有效点：该标的有相邻可计算变化的行；门槛 {MIN_SYMBOL_POINTS} 点，不足仅输出计数与告警次数。",
        "- 后效：触发日后第 h 个交易日点对点收益 (p[t+h]-p[t])/p[t]×100%，缺口不阻断；窗口不足的样本不计入该窗口（n 透明展示）。",
        "- 胜率：前向收益与告警当日变化率同号（方向延续）的触发占比。",
        f"- 有效触发率：触发后 5 个交易日内出现任意单日 |变化率| ≥ {MEANINGFUL_MOVE_PCT:.1f}% 的触发占比。",
        "- 年化频率：告警次数 / 有效数据跨度天数 × 365。",
    ]


def threshold_config() -> dict:
    """当前生效的阈值口径（动态开关 + 回看窗口 + k 因子 + 各标的回退阈值）。

    页面上必须明示它 —— 不写清口径，回测数字**无法解读**（plan 验收标准 2）。
    `alert_threshold()` 每次现读 config/env ⇒ 与「改阈值后立刻可见」配套。
    """
    return {
        "dynamic": bool(ALERT_DYNAMIC),
        "lookback_days": int(ALERT_LOOKBACK_DAYS),
        "k_factor": float(ALERT_K_FACTOR),
        "fallback": [{"symbol": s, "threshold": float(alert_threshold(s))} for s in BACKTEST_SYMBOLS],
    }


def build_backtest_payload(history: list[dict], elapsed_ms: float | None = None) -> dict:
    """组装回测 payload（看板 `GET /api/backtest` 的响应体）。**恒返回结构、不抛异常**。

    字段：`as_of` / `window` / `stats` / `threshold_config` / `symbols[]` / `methods[]`
    / `empty_reason`。数据不足（有效交易日 < `MIN_EFFECTIVE_DAYS`）⇒ `symbols: []` +
    `empty_reason` 文案（**降级为可读空态，而不是报错**，与项目「恒 200」纪律一致）。
    """
    empty: dict = {
        "as_of": None,
        "window": {"start": None, "end": None},
        "stats": {"rows": len(history), "effective_trading_days": 0, "triggers": 0},
        "threshold_config": threshold_config(),
        "symbols": [],
        "methods": method_notes(),
        "elapsed_ms": elapsed_ms,
        "empty_reason": None,
    }
    if not history:
        empty["empty_reason"] = "历史数据为空，无法回测。"
        return empty

    eff_days = _effective_trading_days(history, BACKTEST_SYMBOLS)
    empty["window"] = {"start": history[0].get("date"), "end": history[-1].get("date")}
    empty["as_of"] = history[-1].get("date")
    empty["stats"]["effective_trading_days"] = eff_days
    if eff_days < MIN_EFFECTIVE_DAYS:
        empty["empty_reason"] = (
            f"历史有效交易日不足 {MIN_EFFECTIVE_DAYS} 天（当前 {eff_days} 天），暂不产出回测统计。"
        )
        return empty

    triggers = collect_triggers(history, BACKTEST_SYMBOLS)
    fwd = forward_stats(triggers, history)
    symbols: list[dict] = []
    for sym in BACKTEST_SYMBOLS:
        sym_triggers = [t for t in triggers if t["symbol"] == sym]
        levels = Counter(t["level"] for t in sym_triggers)
        modes = Counter(t["threshold_mode"] for t in sym_triggers)
        n_points = _effective_points(history, sym)
        etr = effective_trigger_rate(sym_triggers, history)
        stats = fwd.get(sym, {})
        symbols.append({
            "symbol": sym,
            "threshold": float(alert_threshold(sym)),
            "effective_points": n_points,
            "alerts": len(sym_triggers),
            "annualized": annualized_frequency(sym_triggers, history, sym),
            "levels": {"WARN": levels.get("WARN", 0), "ALERT": levels.get("ALERT", 0)},
            "threshold_modes": {"dynamic": modes.get("dynamic", 0), "fixed": modes.get("fixed", 0)},
            "effective_trigger_rate": etr,
            "insufficient": n_points < MIN_SYMBOL_POINTS,
            # 后效按窗口字符串键（JSON 的键只能是字符串）；前端按 "1"/"3"/"5"/"10" 取
            "forward": {
                str(h): {
                    "avg": (stats.get(h) or {}).get("avg"),
                    "win": (stats.get(h) or {}).get("win"),
                    "n": (stats.get(h) or {}).get("n", 0),
                }
                for h in HORIZONS
            },
        })
    return {
        "as_of": history[-1].get("date"),
        "window": {"start": history[0].get("date"), "end": history[-1].get("date")},
        "stats": {"rows": len(history), "effective_trading_days": eff_days,
                  "triggers": len(triggers)},
        "threshold_config": threshold_config(),
        "symbols": symbols,
        "methods": method_notes(),
        "elapsed_ms": elapsed_ms,
        "empty_reason": None,
    }
