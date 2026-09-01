"""二十四期单元测试：自选股/持仓关联。

覆盖：fetch_watchlist（Yahoo/AkShare 分发、并行容错、超时隔离）、
render_report 自选股板块、generate_context watchlist 键、daily_report 编排接线、
新闻归因、故障隔离（失败 → 不阻断日报/退出码=0）。
"""

import json

import pytest

from src import analyzer as an
from src import config as cfg
from src import fetcher as ft
from src import reporter as rep
import daily_report as dr


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _sample_inputs():
    values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
              "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0, "GLD": 200.0, "BTC": 60000.0}
    last = {k: v * 0.99 for k, v in values.items()}
    changes = an.compute_changes(values, last)
    statuses = an.build_statuses(values, {}, last, an.load_history())
    summary = an.build_summary(values, statuses, {})
    return dict(date="2026-08-29", values=values, changes=changes, statuses=statuses,
                summary=summary, has_history=True)


# --------------------------------------------------------------------------- #
# fetch_watchlist
# --------------------------------------------------------------------------- #
class TestFetchWatchlist:
    def test_us_yahoo(self, monkeypatch):
        monkeypatch.setattr(ft, "_fetch_yahoo_watch",
                            lambda s: (210.0, [("2026-08-28", 200.0), ("2026-08-29", 210.0)]))
        monkeypatch.setattr(ft, "_fetch_a_share_watch",
                            lambda s: (10.0, [("2026-08-28", 9.0), ("2026-08-29", 10.0)]))
        values, series, errors = ft.fetch_watchlist([{"symbol": "AAPL"}, {"symbol": "600519.SS"}])
        assert values == {"AAPL": 210.0, "600519.SS": 10.0}
        assert series["AAPL"] == [("2026-08-28", 200.0), ("2026-08-29", 210.0)]
        assert series["600519.SS"] == [("2026-08-28", 9.0), ("2026-08-29", 10.0)]
        assert errors == {}

    def test_a_share_dispatch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ft, "_fetch_yahoo_watch", lambda s: (1.0, []))
        monkeypatch.setattr(ft, "_fetch_a_share_watch", lambda s: calls.append(s) or (2.0, []))
        values, series, errors = ft.fetch_watchlist([{"symbol": "000001.SZ"}])
        assert calls == ["000001.SZ"]
        assert values == {"000001.SZ": 2.0}

    def test_single_failure_isolated(self, monkeypatch):
        def ok(s):
            return (1.0, [("2026-08-28", 1.0), ("2026-08-29", 1.0)])

        def bad(s):
            raise ValueError("boom")

        monkeypatch.setattr(ft, "_fetch_yahoo_watch", lambda s: ok(s) if s == "AAPL" else bad(s))
        monkeypatch.setattr(ft, "_fetch_a_share_watch", bad)
        values, series, errors = ft.fetch_watchlist(
            [{"symbol": "AAPL"}, {"symbol": "TSLA"}, {"symbol": "600519.SS"}])
        assert values == {"AAPL": 1.0}
        assert set(errors.keys()) == {"TSLA", "600519.SS"}
        assert "AAPL" not in errors

    def test_empty(self, monkeypatch):
        monkeypatch.setattr(ft, "_fetch_yahoo_watch", lambda s: (1.0, []))
        values, series, errors = ft.fetch_watchlist([])
        assert values == {} and series == {} and errors == {}

    def test_timeout_isolated(self, monkeypatch):
        def bad(s):
            raise TimeoutError("timeout")

        monkeypatch.setattr(ft, "_fetch_yahoo_watch", bad)
        monkeypatch.setattr(ft, "_fetch_a_share_watch", bad)
        values, series, errors = ft.fetch_watchlist([{"symbol": "AAPL"}, {"symbol": "TSLA"}])
        assert values == {}
        assert set(errors.keys()) == {"AAPL", "TSLA"}


# --------------------------------------------------------------------------- #
# render_report 自选股板块
# --------------------------------------------------------------------------- #
class TestRenderReportWatchlist:
    def test_watchlist_section(self):
        wl = {"available": True, "stocks": [
            {"symbol": "AAPL", "label": "苹果", "value": 210.0, "change_pct": 5.0,
             "r": 0.83, "n": 20, "benchmark": "GSPC", "news": None}],
            "portfolio_risk": {"high": False, "avg_r": None}}
        body = rep.render_report(**_sample_inputs(), watchlist=wl)
        assert "📋 自选股/持仓" in body
        assert "苹果 (AAPL)" in body
        assert "🔴 0.83" in body
        assert "| 股票 | 收盘价 | 涨跌幅 | 相关性 |" in body

    def test_data_missing_row(self):
        wl = {"available": True, "stocks": [
            {"symbol": "AAPL", "label": "苹果", "value": None, "change_pct": None,
             "r": None, "n": 0, "benchmark": None, "news": None}],
            "portfolio_risk": {"high": False, "avg_r": None}}
        body = rep.render_report(**_sample_inputs(), watchlist=wl)
        assert "数据暂缺" in body
        assert "数据不足" in body

    def test_all_failed_placeholder(self):
        wl = {"available": False, "stocks": [
            {"symbol": "AAPL", "label": "苹果", "value": None, "change_pct": None,
             "r": None, "n": 0, "benchmark": None, "news": None}],
            "portfolio_risk": {"high": False, "avg_r": None}}
        body = rep.render_report(**_sample_inputs(), watchlist=wl)
        assert "自选股数据暂缺" in body

    def test_concentration_prompt(self):
        wl = {"available": True, "stocks": [
            {"symbol": "AAPL", "label": "苹果", "value": 210.0, "change_pct": 1.0,
             "r": 0.9, "n": 20, "benchmark": "GSPC", "news": None},
            {"symbol": "QQQ", "label": "纳指ETF", "value": 400.0, "change_pct": 1.0,
             "r": 0.9, "n": 20, "benchmark": "GSPC", "news": None}],
            "portfolio_risk": {"high": True, "avg_r": 0.95}}
        body = rep.render_report(**_sample_inputs(), watchlist=wl)
        assert "组合集中度高" in body
        assert "0.95" in body



    def test_news(self):
        wl = {"available": True, "stocks": [
            {"symbol": "AAPL", "label": "苹果", "value": 210.0, "change_pct": 5.0,
             "r": 0.83, "n": 20, "benchmark": "GSPC", "news": "Apple earnings beat"}],
            "portfolio_risk": {"high": False, "avg_r": None}}
        body = rep.render_report(**_sample_inputs(), watchlist=wl)
        assert "📰" in body
        assert "Apple earnings beat" in body

    def test_no_watchlist_no_section(self):
        body = rep.render_report(**_sample_inputs())
        assert "📋 自选股/持仓" not in body


# --------------------------------------------------------------------------- #
# daily_report 编排接线 + 故障隔离
# --------------------------------------------------------------------------- #
_BASE_CFG = {
    "analysis": {"vix": {"peaceful": 20, "panic": 30}, "move": {"normal": 100, "tight": 130}},
    "alert": {"vix": 20, "vxn": 20, "move": 12, "gspc": 2.5, "ixic": 3.5, "sh": 2.5, "sz": 3.5, "cyb": 5.0},
    "trend": {"chart_days": 30, "streak_days": 3},
    "history": {"retention_days": 90},
}


class TestDailyReportWiring:
    def _monkeypatch_net(self, monkeypatch, tmp_path, cfg_obj):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps(cfg_obj), encoding="utf-8")
        monkeypatch.setenv("CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
        monkeypatch.setattr(an, "LAST_VALUES_FILE", tmp_path / "last_values.json")
        monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
        monkeypatch.setattr(dr, "fetch_all", lambda *a, **k: (
            {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
             "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0, "GLD": 200.0, "BTC": 60000.0}, {}))
        monkeypatch.setattr(dr, "fetch_sector_heat", lambda *a, **k: ([], []))
        monkeypatch.setattr(dr, "fetch_us_sector_heat", lambda *a, **k: ([], []))
        monkeypatch.setattr(dr, "render_trend_chart", lambda *a, **k: None)
        monkeypatch.setattr(dr, "render_market_trend_chart", lambda *a, **k: None)
        monkeypatch.setattr(dr, "run_alert_checks", lambda *a, **k: None)
        monkeypatch.setattr(dr, "render_report_image", lambda *a, **k: None)
        monkeypatch.setattr(dr, "load_opening_refs", lambda d: [])

    def test_watchlist_in_report_and_context(self, tmp_path, monkeypatch):
        cfg_obj = dict(_BASE_CFG)
        cfg_obj["watchlist"] = {"stocks": [{"symbol": "AAPL", "label": "苹果"}],
                                "corr_high_threshold": 0.7}
        captured = {}
        self._monkeypatch_net(monkeypatch, tmp_path, cfg_obj)

        series = {"AAPL": [("2026-08-28", 200.0), ("2026-08-29", 210.0)]}
        values = {"AAPL": 210.0}
        monkeypatch.setattr(dr, "fetch_watchlist", lambda stocks: (values, series, {}))
        monkeypatch.setattr(dr, "compute_portfolio_correlation", lambda *a, **k: {
            "stocks": [{"symbol": "AAPL", "label": "苹果", "benchmark": "GSPC", "r": 0.83, "n": 2}],
            "portfolio_risk": {"high": False, "avg_r": None}})
        monkeypatch.setattr(dr, "search_news",
                            lambda q: [{"title": "Apple earnings beat", "snippet": "", "link": "", "date": ""}])
        monkeypatch.setattr(dr, "save_report",
                            lambda d, c: captured.setdefault("report", c) or (tmp_path / f"{d}.md"))

        rc = dr.main()
        assert rc == 0
        report = captured["report"]
        assert "📋 自选股/持仓" in report
        assert "苹果 (AAPL)" in report
        assert "📰" in report  # 涨幅 5% > 2% → 新闻归因
        assert "Apple earnings beat" in report
        ctx_path = tmp_path / "context" / f"{an.get_us_eastern_date()}.json"
        data = json.loads(ctx_path.read_text(encoding="utf-8"))
        assert data["watchlist"]["stocks"][0]["symbol"] == "AAPL"
        assert data["watchlist"]["stocks"][0]["value"] == 210.0
        assert data["watchlist"]["stocks"][0]["corr"]["r"] == 0.83

    def test_no_watchlist_config_clean(self, tmp_path, monkeypatch):
        captured = {}
        self._monkeypatch_net(monkeypatch, tmp_path, dict(_BASE_CFG))
        monkeypatch.setattr(dr, "save_report",
                            lambda d, c: captured.setdefault("report", c) or (tmp_path / f"{d}.md"))

        rc = dr.main()
        assert rc == 0
        assert "📋 自选股/持仓" not in captured["report"]
        ctx_path = tmp_path / "context" / f"{an.get_us_eastern_date()}.json"
        data = json.loads(ctx_path.read_text(encoding="utf-8"))
        assert data["watchlist"] == {"stocks": [], "portfolio_risk": {"high": False, "avg_r": None}}

    def test_watchlist_failure_isolated(self, tmp_path, monkeypatch):
        captured = {}
        cfg_obj = dict(_BASE_CFG)
        cfg_obj["watchlist"] = {"stocks": [{"symbol": "AAPL"}], "corr_high_threshold": 0.7}
        self._monkeypatch_net(monkeypatch, tmp_path, cfg_obj)
        # 抛错发生在 fetch_watchlist 之后，由 main 的 try/except 捕获
        monkeypatch.setattr(dr, "fetch_watchlist", lambda stocks: (_ for _ in ()).throw(RuntimeError("net down")))
        monkeypatch.setattr(dr, "save_report",
                            lambda d, c: captured.setdefault("report", c) or (tmp_path / f"{d}.md"))

        rc = dr.main()  # 必须恒为 0
        assert rc == 0
        assert "📋 自选股/持仓" not in captured["report"]  # 失败 → 不渲染板块
        ctx_path = tmp_path / "context" / f"{an.get_us_eastern_date()}.json"
        data = json.loads(ctx_path.read_text(encoding="utf-8"))
        assert data["watchlist"] == {"stocks": [], "portfolio_risk": {"high": False, "avg_r": None}}
