"""A 股指数取数价格护栏（`src/fetcher.fetch_from_akshare`）。

回归背景（2026-11-02 事故）：收盘后重跑日报时新浪 spot 在**盘前**返回 0，`sz`/`cyb` 被写成
0.0 落进 `history` ⇒ -100% 假告警 + 趋势/相关性失真。0 必须按「缺失」处理：先降级日线，
仍无效就抛异常（`fetch_with_retry` → None，`merge_history` 的 None 不覆盖纪律兜底），
**任何路径都不得返回 0**。

全程不联网：函数内的 `import akshare as ak` 走 `sys.modules`，用假模块替换。
"""

import sys
import types

import pandas as pd
import pytest

import src.fetcher as ft


def _fake_akshare(monkeypatch, spot_price, daily_close, code="sz399001"):
    """装假 akshare：spot 表一行（给定最新价），日线一行（给定收盘价）。"""
    spot = pd.DataFrame({"代码": [code], "最新价": [spot_price]})
    daily = pd.DataFrame({"date": ["2026-11-02"], "close": [daily_close]})
    mod = types.SimpleNamespace(
        stock_zh_index_spot_sina=lambda: spot,
        stock_zh_index_daily=lambda symbol: daily,
    )
    monkeypatch.setitem(sys.modules, "akshare", mod)
    return mod


def test_zero_spot_price_falls_back_to_daily_close(monkeypatch):
    """盘前 spot 返回 0 → 走日线接口拿收盘价，而不是把 0 当价格返回。"""
    _fake_akshare(monkeypatch, spot_price=0.0, daily_close=11010.678)
    assert ft.fetch_from_akshare("399001.SZ") == pytest.approx(11010.678)


def test_zero_daily_close_raises_instead_of_returning_zero(monkeypatch):
    """两路都是 0 → 抛异常（等价「取数失败」），绝不返回 0.0。"""
    _fake_akshare(monkeypatch, spot_price=0.0, daily_close=0.0)
    with pytest.raises(ValueError):
        ft.fetch_from_akshare("399001.SZ")


def test_zero_price_becomes_none_through_retry_wrapper(monkeypatch):
    """生产包装链路上 0 价最终变成 None（×），不会被当成有效值写库。"""
    _fake_akshare(monkeypatch, spot_price=0.0, daily_close=0.0)
    monkeypatch.setattr(ft, "sleep", lambda *_: None)
    assert ft.fetch_with_retry("SZ", lambda: ft.fetch_from_akshare("399001.SZ"), retries=0) is None
