"""数据获取层：从 Yahoo Finance 拉取 VIX / VXN / MOVE 收盘价。

每个数据源独立容错，单源失败不影响其他源。
"""

from __future__ import annotations

import logging
from time import sleep
from urllib.parse import quote

import requests

log = logging.getLogger("marketpulse")

# ---- 常量 ----
# SYMBOLS 顺序：美股大盘（GSPC/IXIC）在前，波动率指数（VIX/VXN/MOVE）在后；
# 顺序决定 context indices、告警收集与报告板块的输出顺序（大盘板块在报告前部）。
SYMBOLS = {
    "GSPC": {"label": "标普500", "source": "yahoo", "ticker": "^GSPC"},
    "IXIC": {"label": "纳斯达克", "source": "yahoo", "ticker": "^IXIC"},
    "SH": {"label": "上证指数", "source": "yahoo", "ticker": "000001.SS"},
    "SZ": {"label": "深证成指", "source": "yahoo", "ticker": "399001.SZ"},
    "CYB": {"label": "创业板指", "source": "yahoo", "ticker": "399006.SZ"},
    "VIX": {"label": "VIX（恐慌指数）", "source": "yahoo", "ticker": "^VIX"},
    "VXN": {"label": "VXN（科技波动）", "source": "yahoo", "ticker": "^VXN"},
    "MOVE": {"label": "MOVE（债市波动）", "source": "yahoo", "ticker": "^MOVE"},
}
# 大盘指数分组（与 SYMBOLS 同处数据注册表）；波动率组 = SYMBOLS 中排除本集合。
# 顺序：美股大盘（GSPC/IXIC）在前、A 股大盘（SH/SZ/CYB）居中、波动率（VIX/VXN/MOVE）在后；
# 该顺序决定 context indices、告警收集与报告板块的输出顺序（六期 B 三板块同序）。
STOCK_SYMBOLS = frozenset({"GSPC", "IXIC", "SH", "SZ", "CYB"})
# A 股大盘分组：用于报告板块拆分（美股 / A 股 / 波动率）与休市判定（六期 B）。
A_SHARE_SYMBOLS = frozenset({"SH", "SZ", "CYB"})
# 七期：快照按市场取子集。PRD 定稿：us 仅大盘（GSPC/IXIC），不含波动率。
MARKETS = {
    "a-share": frozenset({"SH", "SZ", "CYB"}),
    "us": frozenset({"GSPC", "IXIC"}),
}

TIMEOUT = 15          # 单次请求超时（秒）
RETRIES = 1           # 失败重试次数（共尝试 2 次）

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def fetch_with_retry(name, fn, retries: int = RETRIES):
    """带重试地执行取数函数；全部失败返回 None 并记录日志（不抛给上层）。重试间退避 1s，避免突发限流。"""
    for attempt in range(1, retries + 2):
        try:
            value = fn()
            if value is None:
                raise ValueError("返回空数据")
            return value
        except Exception as exc:
            log.warning("%s 获取失败(第%d次): %s", name, attempt, exc)
            if attempt <= retries:
                sleep(1)
    return None


def fetch_from_akshare(symbol: str) -> float:
    """从 AkShare 获取 A 股指数最新收盘价（实时性优于 Yahoo）。"""
    import akshare as ak
    # 转换 ticker 格式：000001.SS → sh000001, 399001.SZ → sz399001
    if symbol.endswith(".SS"):
        ak_symbol = f"sh{symbol[:-3]}"
    elif symbol.endswith(".SZ"):
        ak_symbol = f"sz{symbol[:-3]}"
    else:
        raise ValueError(f"不支持的 AkShare ticker: {symbol}")
    df = ak.stock_zh_index_daily(symbol=ak_symbol)
    if df.empty:
        raise ValueError(f"AkShare 返回空数据: {symbol}")
    return float(df.iloc[-1]["close"])


def fetch_vix_vxn(symbol: str) -> float:
    """获取指数最近收盘价。A 股走 AkShare（实时性更好），美股/波动率走 Yahoo。"""
    # A 股走 AkShare
    if symbol.endswith(".SS") or symbol.endswith(".SZ"):
        return fetch_from_akshare(symbol)
    # 美股/波动率走 Yahoo
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    resp = _SESSION.get(url, params={"interval": "1d", "range": "5d"}, timeout=TIMEOUT)
    resp.raise_for_status()
    result = resp.json()["chart"].get("result")
    if not result:
        raise ValueError("Yahoo 返回空图表数据")
    meta = result[0].get("meta", {})
    close = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
    if close is not None:
        return float(close)
    # 兜底：meta 缺价时解析 close 序列最后一个非空收盘（应对 Yahoo 降级响应）
    quote_series = result[0].get("indicators", {}).get("quote", [{}])
    closes = quote_series[0].get("close", []) if quote_series else []
    for v in reversed(closes):
        if v is not None:
            return float(v)
    raise ValueError("Yahoo 返回数据无收盘价")


def fetch_all(market: str | None = None) -> tuple[dict, dict]:
    """依次获取指数；market 指定时仅取该市场子集（a-share/us），None 取全量。
    每个源独立容错，单源失败/跳过不影响其他源。源间节流 2s，降低 Yahoo 突发限流概率。"""
    subset = MARKETS.get(market) if market else None
    values, errors = {}, {}
    first = True
    for sym, meta in SYMBOLS.items():
        if subset is not None and sym not in subset:
            continue
        if not first:
            sleep(2)
        first = False
        ticker = meta["ticker"]
        fetch = lambda t=ticker: fetch_vix_vxn(t)  # noqa: E731
        values[sym] = fetch_with_retry(sym, fetch)
        if values[sym] is None:
            errors[sym] = "获取失败（已重试）"
            log.warning("%s 最终无数据", sym)
        else:
            log.info("%s 收盘价: %.2f", sym, values[sym])
    return values, errors
