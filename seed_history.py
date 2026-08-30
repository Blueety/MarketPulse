"""一次性的历史数据回填脚本：从 Yahoo 拉取 VIX/VXN/MOVE 过去半年的日收盘，灌入 data/history.json。

- 复用 src.fetcher 的 Yahoo chart REST 接口（range=6mo），解析 timestamp + close 序列。
- 按日期对齐三个指数，合并成 history 记录；个别指数缺失记 None。
- 写入复用 src.analyzer 的 90 天滚动 + 原子写策略。
- 用法：venv/Scripts/python seed_history.py

注意：脚本会尊重项目既定的 90 天滚动上限（HISTORY_MAX），拉半年数据后裁到最近 90 条。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# 确保能将项目根入 sys.path（脚本留在项目根时直接可用）
BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import requests  # noqa: E402

from src.fetcher import SYMBOLS, _SESSION  # noqa: E402
from src.analyzer import (  # noqa: E402
    HISTORY_MAX,
    append_history,
    load_history,
    save_last_values,
)

TIMEOUT = 15


def fetch_history_series(ticker: str) -> list[dict]:
    """拉取单个 ticker 近 6 月日收盘，返回 [{date:'YYYY-MM-DD', close:float}]（按时间升序）。"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": "6mo"}
    resp = _SESSION.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    result = resp.json()["chart"].get("result")
    if not result:
        raise ValueError(f"{ticker}: Yahoo 返回空图表数据")
    timestamps = result[0].get("timestamp") or []
    quote = (result[0].get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    out = []
    for ts, close in zip(timestamps, closes):
        if ts is None or close is None:
            continue
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone().strftime("%Y-%m-%d")
        out.append({"date": day, "close": float(close)})
    return out


def main() -> int:
    print("=== MarketPulse 历史数据回填（近半年）===")
    # 1) 分别拉三个指数
    series = {}
    for sym, meta in SYMBOLS.items():
        ticker = meta["ticker"]
        print(f"拉取 {sym} ({ticker}) ...", flush=True)
        try:
            series[sym] = fetch_history_series(ticker)
            print(f"   -> {len(series[sym])} 条")
        except Exception as exc:  # noqa: BLE001
            print(f"   -> 失败: {exc}")
            series[sym] = []
        # 节流，降低 Yahoo 限流概率
        import time
        time.sleep(2)

    # 2) 按日期对齐合并
    date_map: dict[str, dict] = {}
    for sym, rows in series.items():
        for r in rows:
            day = r["date"]
            date_map.setdefault(day, {"date": day, "vix": None, "vxn": None, "move": None})[sym.lower()] = r["close"]

    records = sorted(date_map.values(), key=lambda x: x["date"])
    print(f"\n合并出 {len(records)} 个交易日")

    # 3) 尊重 90 天滚动上限
    if len(records) > HISTORY_MAX:
        records = records[-HISTORY_MAX:]
        print(f"裁剪到最近 {HISTORY_MAX} 条（项目滚动上限）")

    # 4) 去重：移除与现有历史同日期已有记录叠加（append_history 会按 date 覆盖，直接逐条追加）
    existing = {r.get("date") for r in load_history()}
    added = 0
    for rec in records:
        if rec["date"] not in existing:
            append_history(rec)
            added += 1
        else:
            # 覆盖已有记录（日期相同）
            append_history(rec)
            added += 1
    final = load_history()
    print(f"\n写入完成: 新增/刷新 {added} 条, history.json 现有 {len(final)} 条")
    print(f"最早日期: {final[0]['date'] if final else 'N/A'} | 最晚日期: {final[-1]['date'] if final else 'N/A'}")

    # 5) 同步 last_values.json 为最新收盘（保持涨跌幅基准一致，避免未来涨跌幅错乱）
    if final:
        latest = final[-1]
        save_last_values(
            {k: latest[k] for k in [s.lower() for s in SYMBOLS] if latest.get(k) is not None},
            latest["date"],
        )
        print(f"last_values.json 已同步为 {latest['date']} 收盘值")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())