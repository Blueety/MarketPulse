"""二十六期（2026-09-05）Yahoo 双主机轮换 + 快照 None 单元格真值化。

覆盖：
- D1 Yahoo chart 主机轮换（query1 403 → query2 200，顺序与次数）
- D2 双主机全 403 → 经 fetch_with_retry 返回 None、不抛异常
- D3 404 确定失败 → 不切主机立即失败（调用次数不放大）
- D4 get_market_date 时区锁（a-share=北京 / us=美东，防回归 PRD「美股快照用美东时间」）
- D5 render_snapshot 单市场分支 None 单元格真值化（us/alt→数据暂缺，a-share→休市）

命名注：tests/test_phase26.py 已被 git_ops 26 期占用，本文件按任务名取，避免冲突。
"""

import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from src import fetcher as ft
from src import analyzer as an
from src import reporter as rep


class _FakeYahooResp:
    """最小 Yahoo chart 响应 stub：带 status_code 与 json()。"""

    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("无 payload")
        return self._payload


def _ok_payload(price: float) -> dict:
    return {
        "chart": {
            "result": [{"meta": {"regularMarketPrice": price}}],
            "error": None,
        }
    }

def test_yahoo_host_rotation(monkeypatch):
    """D1：query1 返回 403、query2 返回 200 → 取数成功，调用 2 次且顺序 query1→query2。"""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        if "query1" in url:
            return _FakeYahooResp(403)
        return _FakeYahooResp(200, _ok_payload(7719.02))

    monkeypatch.setattr(ft._SESSION, "get", fake_get)
    monkeypatch.setattr(ft, "sleep", lambda *a, **k: None)

    val = ft.fetch_vix_vxn("^GSPC")
    assert val == 7719.02
    assert len(calls) == 2
    assert "query1" in calls[0] and "query2" in calls[1]


def test_yahoo_both_403_returns_none(monkeypatch):
    """D2：双主机全 403 → 经 fetch_with_retry 容错返回 None，不抛异常。"""

    def fake_get(url, params=None, timeout=None):
        return _FakeYahooResp(403)

    monkeypatch.setattr(ft._SESSION, "get", fake_get)
    monkeypatch.setattr(ft, "sleep", lambda *a, **k: None)

    val = ft.fetch_with_retry("GSPC", lambda: ft.fetch_vix_vxn("^GSPC"))
    assert val is None


def test_yahoo_404_no_rotation(monkeypatch):
    """D3：404 确定失败 → 不切主机立即失败，调用次数不放大（仅 query1）。"""

    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        return _FakeYahooResp(404)

    monkeypatch.setattr(ft._SESSION, "get", fake_get)
    monkeypatch.setattr(ft, "sleep", lambda *a, **k: None)

    try:
        ft.fetch_vix_vxn("^GSPC")
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("404 应触发 HTTPError")
    assert len(calls) == 1
    assert "query1" in calls[0]


def test_market_date_tz_lock(monkeypatch):
    """D4：get_market_date 时区锁 —— 北京 2026-09-05 00:00 → a-share 当日、us 前一日（美东）。"""
    sh = ZoneInfo("Asia/Shanghai")
    eastern = ZoneInfo("America/New_York")
    fixed = datetime(2026, 9, 5, 0, 0, tzinfo=sh)

    class _FixedDateTime:
        @staticmethod
        def now(tz=None):
            return fixed.astimezone(tz) if tz else fixed

    monkeypatch.setattr(an, "datetime", _FixedDateTime)
    assert an.get_market_date("a-share") == "2026-09-05"
    assert an.get_market_date("us") == "2026-09-04"


def test_render_snapshot_none_label(monkeypatch):
    """D5：render_snapshot 单市场分支 None 单元格真值化。

    us/alt → 「数据暂缺」；a-share → 保留「休市」（回归保护，六期 B 既定行为）。
    """
    # us：None → 数据暂缺
    us_syms = ["GSPC", "IXIC"]
    out_us = rep.render_snapshot(
        date="2026-09-04",
        values={s: None for s in us_syms},
        statuses={s: ("—",) for s in us_syms},
        market="us",
        time="noon",
    )
    assert "数据暂缺" in out_us
    assert "休市" not in out_us

    # alt：None → 数据暂缺
    alt_syms = ["GLD", "BTC"]
    out_alt = rep.render_snapshot(
        date="2026-09-04",
        values={s: None for s in alt_syms},
        statuses={s: ("—",) for s in alt_syms},
        market="alt",
        time="noon",
    )
    assert "数据暂缺" in out_alt

    # a-share：None → 休市（保留）
    a_syms = ["SH", "SZ", "CYB"]
    out_a = rep.render_snapshot(
        date="2026-09-05",
        values={s: None for s in a_syms},
        statuses={s: ("—",) for s in a_syms},
        market="a-share",
        time="midday",
    )
    assert "休市" in out_a
    assert "数据暂缺" not in out_a
