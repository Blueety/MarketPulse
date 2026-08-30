"""一次性历史数据回填：大盘指数(AkShare+Yahoo)。

用法：venv/Scripts/python seed_history_market.py
"""
from __future__ import annotations
import sys, json, time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import requests
from src.fetcher import _SESSION, SYMBOLS
from src.analyzer import HISTORY_MAX, load_history, append_history

TIMEOUT = 15


def fetch_yahoo_history(ticker: str) -> list[dict]:
    """Yahoo Finance 6月历史。"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": "6mo"}
    resp = _SESSION.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    result = resp.json()["chart"].get("result")
    if not result:
        raise ValueError(f"{ticker}: Yahoo 返回空")
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


def fetch_akshare_history(symbol: str) -> list[dict]:
    """AkShare A股指数6月历史。"""
    import akshare as ak
    # 转换 ticker: 000001.SS → sh000001
    if symbol.endswith(".SS"):
        ak_sym = "sh" + symbol.replace(".SS", "")
    elif symbol.endswith(".SZ"):
        ak_sym = "sz" + symbol.replace(".SZ", "")
    else:
        raise ValueError(f"非A股 ticker: {symbol}")
    
    # 用 stock_zh_index_daily 获取历史
    df = ak.stock_zh_index_daily(symbol=ak_sym)
    if df is None or len(df) == 0:
        raise ValueError(f"AkShare 返回空: {symbol}")
    
    out = []
    for _, row in df.iterrows():
        date_str = str(row["date"])[:10]  # YYYY-MM-DD
        close = float(row["close"])
        out.append({"date": date_str, "close": close})
    return out[-180:]  # 取近6月


def main() -> int:
    print("=== MarketPulse 大盘指数历史回填 ===\n")
    
    # 已有的波动率数据
    existing = load_history()
    existing_dates = {r["date"] for r in existing}
    print(f"已有 {len(existing)} 条历史记录")
    
    # 分类：A股用AkShare，美股/波动率用Yahoo
    a_share_syms = ["SH", "SZ", "CYB"]  # 000001.SS, 399001.SZ, 399006.SZ
    yahoo_syms = ["GSPC", "IXIC"]  # ^GSPC, ^IXIC
    
    series = {}
    
    # A股用AkShare
    for sym in a_share_syms:
        meta = SYMBOLS[sym]
        ticker = meta["ticker"]
        print(f"拉取 {sym} ({ticker}) [AkShare] ...", flush=True)
        try:
            series[sym] = fetch_akshare_history(ticker)
            print(f"   -> {len(series[sym])} 条")
        except Exception as exc:
            print(f"   -> 失败: {exc}")
            series[sym] = []
        time.sleep(1)
    
    # 美股用Yahoo
    for sym in yahoo_syms:
        meta = SYMBOLS[sym]
        ticker = meta["ticker"]
        print(f"拉取 {sym} ({ticker}) [Yahoo] ...", flush=True)
        try:
            series[sym] = fetch_yahoo_history(ticker)
            print(f"   -> {len(series[sym])} 条")
        except Exception as exc:
            print(f"   -> 失败: {exc}")
            series[sym] = []
        time.sleep(2)
    
    # 合并到现有数据
    for sym, rows in series.items():
        key = sym.lower()  # GSPC → gspc
        for r in rows:
            day = r["date"]
            # 找到或创建该日期的记录
            found = False
            for rec in existing:
                if rec["date"] == day:
                    rec[key] = r["close"]
                    found = True
                    break
            if not found:
                new_rec = {"date": day, "gspc": None, "ixic": None, "sh": None, "sz": None, "cyb": None,
                           "vix": None, "vxn": None, "move": None}
                new_rec[key] = r["close"]
                existing.append(new_rec)
    
    # 按日期排序，裁剪到 HISTORY_MAX
    existing.sort(key=lambda x: x["date"])
    if len(existing) > HISTORY_MAX:
        existing = existing[-HISTORY_MAX:]
    
    # 写入
    history_path = BASE / "data" / "history.json"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = history_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(history_path)
    
    print(f"\n完成！写入 {len(existing)} 条记录")
    
    # 统计
    fields = ["gspc", "ixic", "sh", "sz", "cyb", "vix", "vxn", "move"]
    for f in fields:
        count = sum(1 for d in existing if d.get(f) is not None)
        print(f"  {f}: {count}/{len(existing)} 天有数据")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
