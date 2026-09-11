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
6. **A 股覆盖补齐走 AkShare**：Yahoo 对 `399006.SZ`（创业板指）近 1y **只返回 1 天**，而同日的
   `000001.SS`/`399001.SZ` 各 243 天。故 A 股标的 Yahoo 返回 < `AKSHARE_FALLBACK_MIN`(30) 天时
   改用 `ak.stock_zh_index_daily`（daemon 线程 + `join(AKSHARE_TIMEOUT=15s)` 限时，新浪源无
   timeout），窗口按所有 Yahoo 序列的最早日期裁剪；对「已存在但该键为 `None`」的 A 股交易日行
   **只补 `None` 位置**（非空值一律不覆盖，`--no-patch-existing` 可关闭该行为）。
7. **收尾按 date 升序重排 + 断言**：`merge_history` 对不存在的 date 只 `append`、不排序
   （依赖"每个入口只写今天"），回填历史日期必须整体重排，否则 `/api/latest` 会把最旧日期当"最新日"。

前置条件：`config.json` 的 `history.retention_days`（或 env `HISTORY_RETENTION_DAYS`）
已放宽到 365 —— 否则 `merge_history` 的新增行会被立即裁回 90 行（脚本会提示）。

用法（项目根执行；**执行前请先备份 `data/history.json`**）：

    venv/Scripts/python scripts/backfill_history.py --dry-run    # 只打印计划，不写盘
    venv/Scripts/python scripts/backfill_history.py              # 执行回填（含 A 股 AkShare 补齐）
    venv/Scripts/python scripts/backfill_history.py --symbols SH,SZ   # 只回填指定标的
    venv/Scripts/python scripts/backfill_history.py --no-patch-existing   # 不补既有行空缺
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
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
AKSHARE_TIMEOUT = 15             # 秒；AkShare 走新浪源无 timeout，须 daemon 线程 + join 限时
AKSHARE_FALLBACK_MIN = 30        # A 股标的 Yahoo 返回少于该天数 → 改用 AkShare（实测 399006.SZ 仅 1 天）

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


def _akshare_symbol(ticker: str) -> str:
    """Yahoo 风格 A 股 ticker（`000001.SS` / `399006.SZ`）→ AkShare 指数代码（`sh000001` / `sz399006`）。"""
    code, _, suffix = ticker.partition(".")
    if not code or not suffix:
        raise ValueError(f"非 A 股指数 ticker: {ticker}")
    return ("sh" if suffix.upper() == "SS" else "sz") + code


def fetch_akshare_index(sym: str, window_start: str) -> list[tuple[str, float]]:
    """经 AkShare 取 A 股指数日线 → [(YYYY-MM-DD, close)]（升序，仅保留 >= window_start）。

    新浪源在 akshare 内部无 timeout，故用 daemon 线程 + `join(AKSHARE_TIMEOUT)` 限时
    （与 `src/fetcher.fetch_sector_heat` 同一范式）；超时/异常抛出，由调用方容错。
    AkShare 返回的是**北京交易日**日期，与 history 的 A 股行口径一致。
    """
    ak_sym = _akshare_symbol(SYMBOLS[sym]["ticker"])
    holder: dict = {}

    def _worker() -> None:
        try:
            import akshare as ak
            df = ak.stock_zh_index_daily(symbol=ak_sym)
            if df is None or len(df) == 0:
                raise ValueError(f"AkShare {ak_sym} 返回空数据")
            for col in ("date", "close"):
                if col not in df.columns:
                    raise KeyError(f"AkShare {ak_sym} 缺少必需列: {col}")
            rows = [(str(d)[:10], float(c)) for d, c in zip(df["date"], df["close"]) if c is not None]
            holder["rows"] = sorted(rows)
        except Exception as exc:  # noqa: BLE001 —— 交给调用方统一容错
            holder["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(AKSHARE_TIMEOUT)
    if t.is_alive():
        raise TimeoutError(f"AkShare {ak_sym} 取数超时（>{AKSHARE_TIMEOUT}s）")
    if "error" in holder:
        raise holder["error"]
    return [(d, c) for d, c in holder.get("rows", []) if d >= window_start]


def fill_akshare_gaps(series: dict[str, dict[str, float]], syms: list[str]) -> tuple[list[str], str | None]:
    """A 股标的 Yahoo 覆盖不足时改用 AkShare 补齐（窗口与 Yahoo 各标的对齐）。

    实测 `399006.SZ`（创业板指）Yahoo 近 1y **只返回 1 天**，而 `000001.SS`/`399001.SZ` 各 243 天。
    AkShare 返回全历史（2010 起），故按 Yahoo 序列的**最早日期**裁剪，避免回填远超 1Y。
    窗口基准**排除 7×24 标的**（BTC）——否则窗口会被 BTC 的自然日提前一天，造出
    「SH/SZ 为空但 CYB 有值」的错位首行。
    返回 (已补齐的符号列表, 窗口起始日)。
    """
    all_days = [
        d for sym, vals in series.items()
        if sym not in NON_TRADING_CALENDAR_SYMBOLS
        for d in vals
    ]
    if not all_days:
        return [], None
    window_start = min(all_days)
    filled: list[str] = []
    for sym in syms:
        if sym not in A_SHARE_SYMBOLS:
            continue
        have = len(series.get(sym) or {})
        if have >= AKSHARE_FALLBACK_MIN:
            continue
        try:
            rows = fetch_akshare_index(sym, window_start)
        except Exception as exc:  # noqa: BLE001 —— 单标的容错
            print(f"    {sym:5s} AkShare 补齐失败: {exc}")
            continue
        if len(rows) <= have:
            print(f"    {sym:5s} Yahoo {have} 天，AkShare 仅 {len(rows)} 天 → 保留 Yahoo 结果")
            continue
        print(f"    {sym:5s} Yahoo 仅 {have} 天 → 改用 AkShare: {len(rows)} 天")
        series[sym] = dict(rows)
        filled.append(sym)
    return filled, window_start


def patch_targets(series: dict[str, dict[str, float]],
                  syms_to_patch: list[str]) -> list[tuple[str, str, float]]:
    """列出「既有行中该键为 None」的待补写项 [(date, sym, close)]（只读，绝不覆盖非空值）。

    仅用于 AkShare 权威补数：既有行的 `None` 在**A 股交易日行**上属于 Yahoo 覆盖缺口的产物，
    不是休市语义（该行同时有 `sh`/`sz` 等值即为证）。仍只写 `None` 位置，非空值一律不动。
    """
    rows = {r["date"]: r for r in load_history()}
    out: list[tuple[str, str, float]] = []
    for sym in syms_to_patch:
        key = sym.lower()
        for day, close in sorted((series.get(sym) or {}).items()):
            row = rows.get(day)
            if row is not None and row.get(key) is None:
                out.append((day, sym, close))
    return out


def apply_patch_targets(targets: list[tuple[str, str, float]]) -> int:
    """执行补写：逐项走 `merge_history`（只更新非 None 键、不整行覆盖、不新增日期行）。"""
    for day, sym, close in targets:
        merge_history(day, {sym: close})
    return len(targets)


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


def count_skipped_blanks(series: dict[str, dict[str, float]], history: list[dict],
                         exclude: frozenset[str] = frozenset()) -> int:
    """统计既有行中「有值但该行原为空」的键数（报告"刻意不补"的量）。

    `exclude` 为已由 AkShare 权威补写的符号（它们在补写清单里，不该计入"刻意跳过"）。
    """
    rows = {r["date"]: r for r in history}
    n = 0
    for sym, vals in series.items():
        if sym in exclude:
            continue
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
    ap.add_argument("--no-patch-existing", action="store_true",
                    help="禁止把 AkShare 补的数写进既有行的空缺键（默认允许，仅写 None 位置）")
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

    # A 股覆盖补齐：Yahoo 对部分 A 股指数历史覆盖不足（实测 399006.SZ 仅 1 天）→ 改用 AkShare
    print("\nA 股覆盖补齐（Yahoo 覆盖不足时改走 AkShare）：")
    ak_filled, window_start = fill_akshare_gaps(series, syms)
    if ak_filled:
        print(f"    窗口起始日（各标的统一）: {window_start}")
    else:
        print("    无需补齐")

    patch_syms = [] if args.no_patch_existing else list(ak_filled)
    targets = patch_targets(series, patch_syms) if patch_syms else []

    raw_days = {d for vals in series.values() for d in vals if d not in existing}
    by_date = plan_fills(series, existing)
    days = sorted(by_date)
    dropped = len(raw_days) - len(days)

    if not days:
        print("\n无新增日期（既有历史已覆盖取数区间）")
    else:
        print(f"\n待新增 {len(days)} 行（{days[0]} ~ {days[-1]}）；既有 {len(existing)} 行不改动")
        if dropped:
            print(f"    已丢弃 {dropped} 个「仅 BTC 有值」的非交易日（周末 bar），保持 history 交易日口径")
        for sym in syms:
            if series.get(sym):
                print(f"    {sym:5s} 覆盖 {sum(1 for d in days if sym in by_date[d]):3d}/{len(days)} 天")
    skipped = count_skipped_blanks(series, history, exclude=frozenset(patch_syms))
    if skipped:
        print(f"    （另有 {skipped} 个「既有行中为空、有值」的键被刻意跳过："
              f"休市/未收盘的空值有真实语义，不用通用历史 bar 回填）")
    if failed:
        print(f"    取数失败标的: {failed}")

    if targets:
        print(f"\nAkShare 空缺补写: {len(targets)} 个键 / {len({d for d, _, _ in targets})} 行"
              f"（仅写既有行中该键为 None 的位置，绝不覆盖非空值；--no-patch-existing 可关闭）")

    if args.dry_run:
        print("\n[dry-run] 未写盘")
        return 0

    for day in days:
        merge_history(day, by_date[day])
    if targets:
        print(f"AkShare 空缺补写完成: {apply_patch_targets(targets)} 个键")
    code = finalize_and_report()
    if code == 0 and len(load_history()) >= HISTORY_MAX:
        print(f"注意：已达 HISTORY_MAX={HISTORY_MAX} 上限，更早的行会被裁剪。")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
