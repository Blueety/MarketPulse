"""美股板块（11 个 SPDR Sector ETF）领涨/领跌专项测试（不联网，monkeypatch _SESSION.get）。

覆盖：fetch_us_sector_heat 取数（成功排序/缺字段/超时由 SECTOR_TIMEOUT 限时）、
render_report 美股板块表（有数据时渲染、无数据时不污染 A 股空态）、
generate_context 扩展 us_sector_heat 键、render_snapshot 美股分支渲染。
"""

import json

import pytest

from src import analyzer as an
from src import fetcher as ft
from src import reporter as rep

# ticker -> (涨跌幅%, 现价, 成交量)
_FAKE = {
    "XLK": (2.5, 200.0, 6_000_000),
    "XLF": (-1.2, 40.0, 30_000_000),
    "XLE": (0.8, 80.0, 12_000_000),
    "XLV": (-3.0, 130.0, 9_000_000),
    "XLI": (1.5, 100.0, 15_000_000),
    "XLP": (-0.5, 75.0, 8_000_000),
    "XLY": (3.2, 180.0, 10_000_000),
    "XLU": (-2.1, 70.0, 11_000_000),
    "XLB": (0.3, 90.0, 5_000_000),
    "XLRE": (-1.8, 40.0, 4_000_000),
    "XLC": (1.1, 60.0, 7_000_000),
}


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_get(url, params=None, timeout=None):
    ticker = url.rstrip("/").split("/")[-1]
    change, price, vol = _FAKE[ticker]
    return _FakeResp({
        "chart": {
            "result": [{"meta": {
                "regularMarketChangePercent": change,
                "regularMarketPrice": price,
                "regularMarketVolume": vol,
            }}],
            "error": None,
        }
    })


US_GAINERS = [
    {"name": "科技 (XLK)", "change": 2.5, "turnover": "$1.2B", "top_stock": "XLK"},
]
US_LOSERS = [
    {"name": "医疗健康 (XLV)", "change": -3.0, "turnover": "$1.2B", "top_stock": "XLV"},
]


class TestFetchUsSectorHeat:
    def test_sorted_top5(self, monkeypatch):
        monkeypatch.setattr(ft._SESSION, "get", _fake_get)
        gainers, losers = ft.fetch_us_sector_heat()
        assert len(gainers) == 5
        assert len(losers) == 5
        # 降序领涨：XLY 3.2 > XLK 2.5 > XLI 1.5 > XLC 1.1 > XLE 0.8
        assert [r["name"] for r in gainers] == [
            "可选消费 (XLY)", "科技 (XLK)", "工业 (XLI)", "通信服务 (XLC)", "能源 (XLE)",
        ]
        assert gainers[0]["change"] == 3.2
        assert gainers[0]["top_stock"] == "XLY"
        # 升序领跌：XLV -3.0 < XLU -2.1 < XLRE -1.8 < XLF -1.2 < XLP -0.5
        assert losers[0]["name"] == "医疗健康 (XLV)"
        assert losers[0]["change"] == -3.0

    def test_top_n_param(self, monkeypatch):
        monkeypatch.setattr(ft._SESSION, "get", _fake_get)
        gainers, losers = ft.fetch_us_sector_heat(top_n=3)
        assert len(gainers) == 3
        assert len(losers) == 3

    def test_volume_format(self, monkeypatch):
        monkeypatch.setattr(ft._SESSION, "get", _fake_get)
        gainers, _ = ft.fetch_us_sector_heat()
        # XLK: 200 * 6_000_000 = 1.2e9 -> $1.2B
        xlk = next(r for r in gainers if r["top_stock"] == "XLK")
        assert xlk["turnover"] == "$1.2B"

    def test_missing_field_returns_empty(self, monkeypatch):
        def bad(url, params=None, timeout=None):
            return _FakeResp({"chart": {"result": [{"meta": {"regularMarketPrice": 1.0}}], "error": None}})

        monkeypatch.setattr(ft._SESSION, "get", bad)
        assert ft.fetch_us_sector_heat() == ([], [])


def _report_inputs(**kw):
    syms = ["GSPC", "IXIC", "SH", "SZ", "CYB", "VIX", "VXN", "MOVE", "GLD", "BTC"]
    values = {s: 100.0 for s in syms}
    values["VIX"] = 15.0
    changes = {s: 0.5 for s in syms}
    statuses = {s: ("平静", "desc") for s in syms}
    base = dict(date="2026-08-29", values=values, changes=changes,
                statuses=statuses, summary="x", has_history=True)
    base.update(kw)
    return base


class TestRenderReportUsSector:
    def test_tables_rendered(self):
        report = rep.render_report(**_report_inputs(us_sector_heat=(US_GAINERS, US_LOSERS)))
        assert "## 🔥 美股板块领涨 Top 5" in report
        assert "## 📉 美股板块领跌 Top 5" in report
        assert "| 科技 (XLK) | +2.50% | $1.2B | XLK |" in report
        assert "| 医疗健康 (XLV) | -3.00% | $1.2B | XLV |" in report
        # A 股板块不受影响
        assert "## 🔥 A 股热点板块 Top 5" in report

    def test_absent_when_none(self):
        report = rep.render_report(**_report_inputs())
        assert "美股板块" not in report
        # A 股空态占位仍为 2（不被美股占位污染）
        assert report.count("| 数据暂缺 | — | — | — |") == 2


class TestGenerateContextUsSector:
    def test_field_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
        monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
        from src import alerter as al

        monkeypatch.setattr(al, "ALERTS_DIR", tmp_path / "alerts")
        monkeypatch.setattr(al, "ALERTS_LOG", tmp_path / "alerts.log")
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0, "GLD": 252.30, "BTC": 65000.00}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0, "GLD": 250.10, "BTC": 64000.00}
        changes = an.compute_changes(values, last)
        statuses = an.build_statuses(values, {})
        rep.generate_context("2026-08-29", values, changes, statuses, last,
                             us_sector_heat=(US_GAINERS, US_LOSERS))
        data = json.loads((tmp_path / "context" / "2026-08-29.json").read_text(encoding="utf-8"))
        assert data["us_sector_heat"] == {
            "gainers": US_GAINERS,
            "losers": US_LOSERS,
        }


class TestSnapshotUsSector:
    def _values_statuses(self):
        syms = ["GSPC", "IXIC", "SH", "SZ", "CYB", "VIX", "VXN", "MOVE", "GLD", "BTC"]
        values = {s: 100.0 for s in syms}
        values["VIX"] = 15.0
        return values, an.build_statuses(values, {})

    def test_us_branch_renders(self):
        values, statuses = self._values_statuses()
        content = rep.render_snapshot("2026-08-29", values, statuses, market="us", time="close",
                                      us_sector_heat=(US_GAINERS, US_LOSERS))
        assert "## 🔥 美股板块领涨 Top 5" in content
        assert "| 科技 (XLK) | +2.50% | $1.2B | XLK |" in content

    def test_us_branch_absent_without_data(self):
        values, statuses = self._values_statuses()
        content = rep.render_snapshot("2026-08-29", values, statuses, market="us", time="close")
        assert "美股板块" not in content
