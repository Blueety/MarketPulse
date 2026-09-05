"""任务 H.5：非交易日 gate 单元测试（is_market_holiday + 入口 gate 边界）。

覆盖：
- 周六 a-share 休市 / 周三 a-share 开市
- ET 周六（北京周日凌晨）us 休市 / ET 周五（北京周六）us 开市
- 入口 gate：a-share 周末三时段全跳；us open/noon 周末跳、close/daily 不跳（边界钉死）
- 工作日全不跳
"""
import os
import sys

# 顶层脚本 snapshot_report 在仓库根目录，需显式加入 sys.path（pytest 默认只加 tests/）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone

import src.analyzer as an
import snapshot_report as sr


class _FakeDateTime:
    """monkeypatch src.analyzer.datetime：now(tz) 返回固定 UTC 瞬时换算到 tz。"""

    fixed = None  # 由测试设置的 aware UTC datetime

    @staticmethod
    def now(tz=None):
        dt = _FakeDateTime.fixed
        if tz is None:
            return dt
        return dt.astimezone(tz)


def _patch(monkeypatch, utc_dt):
    _FakeDateTime.fixed = utc_dt
    monkeypatch.setattr(an, "datetime", _FakeDateTime)


def test_a_share_saturday_closed(monkeypatch):
    # 北京周六 00:00 = UTC 周五 16:00（a-share 周末）
    _patch(monkeypatch, datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc))
    assert an.is_market_holiday("a-share") is True


def test_a_share_wednesday_open(monkeypatch):
    # 北京周三 00:00 = UTC 周二 16:00（a-share 工作日）
    _patch(monkeypatch, datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc))
    assert an.is_market_holiday("a-share") is False


def test_us_et_saturday_closed(monkeypatch):
    # 北京周日 00:00 = ET 周六 12:00（us 周末）
    _patch(monkeypatch, datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc))
    assert an.is_market_holiday("us") is True


def test_us_et_friday_open(monkeypatch):
    # 北京周六 00:00 = ET 周五 12:00（us 工作日，不跳）
    _patch(monkeypatch, datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc))
    assert an.is_market_holiday("us") is False


def test_gate_a_share_weekend_skip(monkeypatch):
    # 北京周六 00:00 = UTC 周五 16:00
    _patch(monkeypatch, datetime(2026, 9, 4, 16, 0, tzinfo=timezone.utc))
    assert sr._is_market_closed("a-share", "midday") is True
    assert sr._is_market_closed("a-share", "open") is True
    assert sr._is_market_closed("a-share", "close") is True


def test_gate_us_open_noon_weekend_skip_close_valid(monkeypatch):
    # 北京周日 00:00 = ET 周六 12:00
    _patch(monkeypatch, datetime(2026, 9, 5, 16, 0, tzinfo=timezone.utc))
    assert sr._is_market_closed("us", "open") is True
    assert sr._is_market_closed("us", "noon") is True
    # 边界钉死：us close/daily 周末不跳（ET 周五收盘后数据有效）
    assert sr._is_market_closed("us", "close") is False
    assert sr._is_market_closed("us", "daily") is False


def test_gate_weekday_no_skip(monkeypatch):
    # 北京周三 00:00 = UTC 周二 16:00（两市场均工作日）
    _patch(monkeypatch, datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc))
    assert sr._is_market_closed("a-share", "midday") is False
    assert sr._is_market_closed("us", "noon") is False
