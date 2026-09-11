"""历史数据回填（Step 10）：把 `data/history.json` 补齐到近 1 年，供看板 1Y 视图使用。

与早期一次性脚本 `seed_history.py` 的差异（后者保留不动）：

1. **走 `fetcher._yahoo_chart_get`**：query1/query2 双主机轮换，规避主机级 403/429
   （`docs/pitfalls.md`「Yahoo chart 需 query1/query2 双主机轮换」）。
2. **按符号所属市场时区归档日期**：A 股（SH/SZ/CYB）→ 上海时区、其余 → 美东时区，
   与 `analyzer.get_market_date` 的 history 日期口径一致。统一转美东会让 A 股整体
   早一天（上证 09:30 北京 = 前一日 21:30 ET），与既有行错位/重复。
3. **只新增、不改既有行**：既有行的 `None` 是真实语义（休市 / 未收盘，如美股假日整行
   美股键为空），用历史 bar 回填会造出"休市日却有值"的假数据。
4. **用 `analyzer.merge_history` 按 date 合并**：不整行覆盖、不抹他市场子集、
   自动按 `HISTORY_MAX` 裁剪、临时文件 + `os.replace` 原子写。
5. **不调用 `save_last_values`**：`data/last_values.json` 是次日涨跌幅与告警的基准，
   键名必须保持大写（`seed_history.py` 用小写键整文件覆盖会让次日涨跌幅与告警全部失效）。

前置条件：`config.json` 的 `history.retention_days`（或 env `HISTORY_RETENTION_DAYS`）
已放宽到 365 —— 否则 `merge_history` 的新增行会被立即裁回 90 行（脚本会提示）。

用法（项目根执行；**执行前请先备份 `data/history.json`**）：

    venv/Scripts/python scripts/backfill_history.py --dry-run    # 只打印计划，不写盘
    venv/Scripts/python scripts/backfill_history.py              # 执行回填
    venv/Scripts/python scripts/backfill_history.py --symbols SH,SZ   # 只回填指定标的
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from src.analyzer import (  # noqa: E402
    EASTERN_TZ,
    HISTORY_FILE,
    HISTORY_MAX,
    SHANGHAI_TZ,
    load_history,
    merge_history,
)
from src.fetcher import A_SHARE_SYMBOLS, SYMBOLS, _yahoo_chart_get  # noqa: E402

DEFAULT_RANGE = "1y"
RETENTION_WARN_THRESHOLD = 300   # 低于此值说明 retention 未放宽，回填会被立刻裁剪
SOURCE_THROTTLE = 0.5            # 源间节流（秒），降低 10 标的连续取数的 429 概率

# 7×24 交易、Yahoo 日线**含周末**的标的。其日期不可作为「交易日」依据，否则会写出
# 只有 btc 有值的纯周末行（既不符合 history 的交易日口径，也会切断相关性收益链、
# 夸大回测样本计数）。判定规则：某天若除它之外无任何标的有值 → 判为非交易日，整行丢弃。
NON_TRADING_CALENDAR_SYMBOLS = frozenset({"BTC"})


def fetch_series(sym: str, rng: str) -> list[tuple[str, float]]:
    """拉取单标的近 N 期日收盘 → [(YYYY-MM-DD, close)]（按所属市场时区归档，升序）。

    缺失 bar（None）跳过；日期时区：A 股用上海、其余用美东（与 history 口径一致）。
    """
    ticker = SYMBOLS[sym]["ticker"]
    tz = SHANGHAI_TZ if sym in A_SHARE_SYMBOLS else EASTERN_TZ
    resp = _yahoo_chart_get(ticker, {"interval": "1d", "range": rng})
    resp.raise_for_status()
    result = resp.json()["chart"].get("result")
    if not result:
        raise ValueError(f"{sym}({ticker}): Yahoo 返回空图表数据")
    res = result[0]
    timestamps = res.get("timestamp") or []
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    out: list[tuple[str, float]] = []
    for ts, close in zip(timestamps, closes):
        if ts is None or close is None:
            continue
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(tz).strftime("%Y-%m-%d")
        out.append((day, float(close)))
    return out


def collect_series(syms: list[str], rng: str) -> tuple[dict[str, dict[str, float]], list[str]]:
    """逐标的取数（单标的失败不影响其余），返回 ({sym: {date: close}}, 失败标的列表)。"""
    series: dict[str, dict[str, float]] = {}
    failed: list[str] = []
    for sym in syms:
        ticker = SYMBOLS[sym]["ticker"]
        try:
            rows = fetch_series(sym, rng)
        except Exception as exc:  # noqa: BLE001 —— 单标的容错，不中断整体回填
            print(f"  {sym:5s} {ticker:10s} -> 失败: {exc}")
            series[sym] = {}
            failed.append(sym)
            continue
        series[sym] = dict(rows)
        span = f"{rows[0][0]} ~ {rows[-1][0]}" if rows else "—"
        print(f"  {sym:5s} {ticker:10s} -> {len(rows):3d} 天 ({span})")
        time.sleep(SOURCE_THROTTLE)
    return series, failed


def plan_fills(series: dict[str, dict[str, float]], existing: set[str]) -> dict[str, dict[str, float]]:
    """按天聚合「待新增」值。

    两道过滤：
    1. date 已存在于既有历史 → 整行跳过（既有 None 有真实语义，如休市/未收盘，不覆盖）。
    2. 某天若只有 `NON_TRADING_CALENDAR_SYMBOLS` 有值（BTC 的周末 bar）→ 判为非交易日，
       整行丢弃，保持 history 的「交易日行」口径（与既有 90 行一致）。
    """
    raw: dict[str, dict[str, float]] = {}
    for sym, vals in series.items():
        for day, close in vals.items():
            if day in existing:
                continue
            raw.setdefault(day, {})[sym] = close
    return {
        day: vals
        for day, vals in raw.items()
        if any(sym not in NON_TRADING_CALENDAR_SYMBOLS for sym in vals)
    }


def count_skipped_blanks(series: dict[str, dict[str, float]], history: list[dict]) -> int:
    """统计既有行中「Yahoo 有值但该行原为空」的键数（仅用于报告"刻意不补"的量）。"""
    rows = {r["date"]: r for r in history}
    n = 0
    for sym, vals in series.items():
        key = sym.lower()
        for day, _close in vals.items():
            row = rows.get(day)
            if row is not None and row.get(key) is None:
                n += 1
    return n


def ensure_sorted() -> int:
    """按 date 升序重排 `data/history.json`（保留原始键序，临时文件 + os.replace 原子写）。

    **必需步骤**：    `analyzer.merge_history` 只做 `records.append(...)`，依赖「每个入口只写『今天』」
    使末尾天然有序；回填历史日期会 append 出乱序数组，而 `/api/latest`、
    `_last_records`、趋势窗口、`compute_correlation` 都按**数组顺序**消费 → 会把最旧的
    回填日期当成「最新日」。故回填后必须整体重排。
    """
    if not HISTORY_FILE.exists():
        return 0
    data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return 0
    data.sort(key=lambda r: str(r.get("date", "")))
    tmp = HISTORY_FILE.with_name(HISTORY_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, HISTORY_FILE)
    return len(data)


def finalize_and_report() -> int:
    """重排 + 校验（严格升序 / 无重复）+ 打印，返回退出码（0 正常 / 1 校验失败）。"""
    ensure_sorted()
    rows = load_history()
    dates = [r["date"] for r in rows]
    if not dates:
        print("\nhistory.json 为空")
        return 0
    ok_order = dates == sorted(dates)
    ok_unique = len(dates) == len(set(dates))
    print(f"\nhistory.json 现有 {len(rows)} 行（{dates[0]} ~ {dates[-1]}）")
    print(f"  日期严格升序: {ok_order} | 无重复: {ok_unique}")
    if not (ok_order and ok_unique):
        print("!! 校验失败：history 顺序/唯一性异常，请用备份回滚")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="MarketPulse 历史数据回填（近 1 年）")
    ap.add_argument("--symbols", default="", help="逗号分隔的大写符号，默认全部 SYMBOLS（10 个）")
    ap.add_argument("--range", default=DEFAULT_RANGE, help=f"Yahoo chart range，默认 {DEFAULT_RANGE}")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写盘")
    args = ap.parse_args()

    syms = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or list(SYMBOLS)
    unknown = [s for s in syms if s not in SYMBOLS]
    if unknown:
        print(f"未知符号: {unknown}（可用: {list(SYMBOLS)}）")
        return 2

    print(f"=== MarketPulse 历史回填（range={args.range}，符号 {len(syms)} 个）===")
    print(f"HISTORY_MAX（当前生效）= {HISTORY_MAX}")
    if HISTORY_MAX < RETENTION_WARN_THRESHOLD:
        print("!! 警告：HISTORY_MAX < 300，新增行会被 merge_history 立即裁剪。")
        print("   请先把 config.json 的 history.retention_days 或 env HISTORY_RETENTION_DAYS 放宽到 365。")

    history = load_history()
    existing = {r["date"] for r in history}
    print(f"既有历史 {len(history)} 行（{history[0]['date']} ~ {history[-1]['date']}）\n")
    print("取数：")
    series, failed = collect_series(syms, args.range)

    raw_days = {d for vals in series.values() for d in vals if d not in existing}
    by_date = plan_fills(series, existing)
    if not by_date:
        print("\n无新增日期（既有历史已覆盖 Yahoo 返回区间）")
        print("[dry-run] 未写盘" if args.dry_run else "（仅执行排序校验）")
        if args.dry_run:
            return 0
        return finalize_and_report()

    days = sorted(by_date)
    dropped = len(raw_days) - len(days)
    print(f"\n待新增 {len(days)} 行（{days[0]} ~ {days[-1]}）；既有 {len(existing)} 行不改动")
    if dropped:
        print(f"    已丢弃 {dropped} 个「仅 BTC 有值」的非交易日（周末 bar），保持 history 交易日口径")
    for sym in syms:
        if series.get(sym):
            print(f"    {sym:5s} 覆盖 {sum(1 for d in days if sym in by_date[d]):3d}/{len(days)} 天")
    skipped = count_skipped_blanks(series, history)
    if skipped:
        print(f"    （另有 {skipped} 个「既有行中为空、Yahoo 有值」的键被刻意跳过："
              f"休市/未收盘的空值有真实语义，不用历史 bar 回填）")
    if failed:
        print(f"    失败标的（本次未回填）: {failed}")

    if args.dry_run:
        print("\n[dry-run] 未写盘")
        return 0

    for day in days:
        merge_history(day, by_date[day])
    code = finalize_and_report()
    if code == 0 and len(load_history()) >= HISTORY_MAX:
        print(f"注意：已达 HISTORY_MAX={HISTORY_MAX} 上限，更早的行会被裁剪。")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
