"""二十四期单元测试：自选股/持仓关联。

覆盖：fetch_watchlist（Yahoo/AkShare 分发、并行容错、超时隔离）、
render_report 自选股板块、generate_context watchlist 键、daily_report 编排接线、
新闻归因、故障隔离（失败 → 不阻断日报/退出码=0）。
"""

import json

import pytest

from src import analyzer as an
from src import storage as st
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
                            lambda s, *a: (210.0, [("2026-08-28", 200.0), ("2026-08-29", 210.0)]))
        monkeypatch.setattr(ft, "_fetch_a_share_watch",
                            lambda s: (10.0, [("2026-08-28", 9.0), ("2026-08-29", 10.0)]))
        values, series, errors = ft.fetch_watchlist([{"symbol": "AAPL"}, {"symbol": "600519.SS"}])
        assert values == {"AAPL": 210.0, "600519.SS": 10.0}
        assert series["AAPL"] == [("2026-08-28", 200.0), ("2026-08-29", 210.0)]
        assert series["600519.SS"] == [("2026-08-28", 9.0), ("2026-08-29", 10.0)]
        assert errors == {}

    def test_a_share_dispatch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ft, "_fetch_yahoo_watch", lambda s, *a: (1.0, []))
        monkeypatch.setattr(ft, "_fetch_a_share_watch", lambda s: calls.append(s) or (2.0, []))
        values, series, errors = ft.fetch_watchlist([{"symbol": "000001.SZ"}])
        assert calls == ["000001.SZ"]
        assert values == {"000001.SZ": 2.0}

    def test_single_failure_isolated(self, monkeypatch):
        def ok(s):
            return (1.0, [("2026-08-28", 1.0), ("2026-08-29", 1.0)])

        def bad(s, *a):
            raise ValueError("boom")

        monkeypatch.setattr(ft, "_fetch_yahoo_watch", lambda s, *a: ok(s) if s == "AAPL" else bad(s))
        monkeypatch.setattr(ft, "_fetch_a_share_watch", bad)
        values, series, errors = ft.fetch_watchlist(
            [{"symbol": "AAPL"}, {"symbol": "TSLA"}, {"symbol": "600519.SS"}])
        assert values == {"AAPL": 1.0}
        assert set(errors.keys()) == {"TSLA", "600519.SS"}
        assert "AAPL" not in errors

    def test_range_passthrough(self, monkeypatch):
        """M-1 契约：range_ 透传到 Yahoo 取数层（默认 "2y" 不变；宏观端点传 "5y"）。

        ⚠️ 这里同时是 R2 的护栏：range 是自选股与宏观**共用**的取数函数，
        若有人把默认值直接改成 5y，本用例的 `seen == ["2y", "5y"]` 会失败。
        """
        seen = []
        monkeypatch.setattr(ft, "_fetch_yahoo_watch",
                            lambda s, r="2y": seen.append(r) or (1.0, []))
        ft.fetch_watchlist([{"symbol": "AAPL"}])
        ft.fetch_watchlist([{"symbol": "AAPL"}], range_="5y")
        assert seen == ["2y", "5y"]

    def test_empty(self, monkeypatch):
        monkeypatch.setattr(ft, "_fetch_yahoo_watch", lambda s, *a: (1.0, []))
        values, series, errors = ft.fetch_watchlist([])
        assert values == {} and series == {} and errors == {}

    def test_timeout_isolated(self, monkeypatch):
        def bad(s, *a):
            raise TimeoutError("timeout")

        monkeypatch.setattr(ft, "_fetch_yahoo_watch", bad)
        monkeypatch.setattr(ft, "_fetch_a_share_watch", bad)
        values, series, errors = ft.fetch_watchlist([{"symbol": "AAPL"}, {"symbol": "TSLA"}])
        assert values == {}
        assert set(errors.keys()) == {"AAPL", "TSLA"}


# --------------------------------------------------------------------------- #
# ETF 数据源链（2026-10-12）
# --------------------------------------------------------------------------- #
def _etf_df(rows):
    import pandas as pd

    return pd.DataFrame(rows)


class TestAShareWatchSourceChain:
    """ETF 源链 东财 → 新浪 → 腾讯 → Yahoo 兜底（不联网，akshare 打桩）。

    背景：东财 `push2his.eastmoney.com` 自 2026-09-30 起每次失败，Yahoo 在本机又必须走
    Clash 代理 —— 两者任一抖动即「自选股 10 行数据暂缺」（2026-10-12 15:16 快照只剩 1 只）。
    新浪/腾讯为国内直连源，本组测试锁死「主路挂掉仍能出数」。
    """

    # 实测列名：新浪/腾讯 = date/close，东财 = 日期/收盘
    SINA_ROWS = [{"date": "2026-10-09", "close": 1.338},
                 {"date": "2026-10-12", "close": 1.357}]
    TX_ROWS = [{"date": "2026-10-09", "close": 1.34},
               {"date": "2026-10-12", "close": 1.36}]

    @staticmethod
    def _eastmoney_down(monkeypatch):
        import akshare as ak_mock

        def boom(**kw):
            raise ConnectionError("('Connection aborted.', RemoteDisconnected(...))")

        monkeypatch.setattr(ak_mock, "fund_etf_hist_em", boom)
        # 实时行情覆盖不在本组测（见 TestEtfQuoteOverlay），这里固定为 None 以免联网
        monkeypatch.setattr(ft, "_etf_quote", lambda s: None)

    def test_eastmoney_down_falls_to_sina(self, monkeypatch):
        import akshare as ak_mod

        self._eastmoney_down(monkeypatch)
        monkeypatch.setattr(ak_mod, "fund_etf_hist_sina",
                            lambda symbol: _etf_df(self.SINA_ROWS))
        monkeypatch.setattr(ft, "_fetch_yahoo_watch",
                            lambda s, *a: pytest.fail("新浪已成功，不应回退 Yahoo"))

        value, series = ft._fetch_a_share_watch("515300.SS")
        assert series == [("2026-10-09", 1.338), ("2026-10-12", 1.357)]
        assert value == 1.357  # 末点即当日收盘

    def test_date_objects_normalized(self, monkeypatch):
        """新浪/腾讯返回 datetime.date（实测 dtype=object），统一成 %Y-%m-%d 字符串。"""
        import akshare as ak_mod
        from datetime import date

        self._eastmoney_down(monkeypatch)
        monkeypatch.setattr(ak_mod, "fund_etf_hist_sina", lambda symbol: _etf_df(
            [{"date": date(2026, 10, 9), "close": 1.338},
             {"date": date(2026, 10, 12), "close": 1.357}]))

        _, series = ft._fetch_a_share_watch("515300.SS")
        assert [d for d, _ in series] == ["2026-10-09", "2026-10-12"]

    def test_sina_empty_or_down_falls_to_tencent(self, monkeypatch):
        import akshare as ak_mod

        self._eastmoney_down(monkeypatch)
        monkeypatch.setattr(ak_mod, "fund_etf_hist_sina", lambda symbol: _etf_df([]))
        monkeypatch.setattr(ak_mod, "stock_zh_a_hist_tx",
                            lambda **kw: _etf_df(self.TX_ROWS))
        monkeypatch.setattr(ft, "_fetch_yahoo_watch",
                            lambda s, *a: pytest.fail("腾讯已成功，不应回退 Yahoo"))

        value, series = ft._fetch_a_share_watch("159813.SZ")
        assert series == [("2026-10-09", 1.34), ("2026-10-12", 1.36)]
        assert value == 1.36

    def test_all_sources_down_falls_back_to_yahoo(self, monkeypatch):
        import akshare as ak_mod

        def boom(**kw):
            raise ConnectionError("down")

        monkeypatch.setattr(ak_mod, "fund_etf_hist_em", boom)
        monkeypatch.setattr(ak_mod, "fund_etf_hist_sina", boom)
        monkeypatch.setattr(ak_mod, "stock_zh_a_hist_tx", boom)
        monkeypatch.setattr(ft, "_fetch_yahoo_watch",
                            lambda s, *a: (9.9, [("2026-10-11", 9.9)]))

        value, series = ft._fetch_a_share_watch("515300.SS")
        assert value == 9.9 and series == [("2026-10-11", 9.9)]

    def test_watchlist_survives_yahoo_outage(self, monkeypatch):
        """症状级：Yahoo/代理挂掉时自选股仍出数（不再 10 行「数据暂缺」）。"""
        import akshare as ak_mod

        def yahoo_dead(s, *a):
            raise RuntimeError("HTTP 403 for query2.finance.yahoo.com")

        self._eastmoney_down(monkeypatch)
        monkeypatch.setattr(ak_mod, "fund_etf_hist_sina",
                            lambda symbol: _etf_df(self.SINA_ROWS))
        monkeypatch.setattr(ft, "_fetch_yahoo_watch", yahoo_dead)

        values, series, errors = ft.fetch_watchlist(
            [{"symbol": "515300.SS"}, {"symbol": "159813.SZ"}])
        assert values == {"515300.SS": 1.357, "159813.SZ": 1.357}
        assert errors == {}
        assert series["515300.SS"][-1] == ("2026-10-12", 1.357)


# --------------------------------------------------------------------------- #
# ETF 实时行情覆盖（2026-10-12）
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.encoding = "utf-8"

    def raise_for_status(self):
        pass


class _FakeSession:
    """只实现 `_etf_quote` 用到的 `get(url, timeout=)`。"""

    def __init__(self, text):
        self.text = text
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return _FakeResp(self.text)


def _tx_payload(code="sh515300", price="1.357", ts="20261012161456"):
    """腾讯 `qt.gtimg.cn` 实测报文（`~` 分隔，[3] 当前价 / [30] 时间戳）。"""
    fields = ["1", "300红利低波ETF嘉实", code, price, "1.338", "1.337", "808447", "419332",
              "389115", "1.356", "737", "1.355", "1162", "1.354", "2079", "1.353", "6425",
              "1.352", "7916", "1.357", "1147", "1.358", "3005", "1.359", "6190", "1.360",
              "10123", "1.361", "10790", "", ts, "0.019", "1.42"]
    return f'v_{code}="' + "~".join(fields) + '";'


class TestEtfQuoteOverlay:
    """实时行情补当日 bar：历史文件（`klc_kl.js`）盘后才更新，不补则午盘「最新价」退化成昨收。"""

    def test_parses_tencent_payload(self, monkeypatch):
        monkeypatch.setattr(ft, "_SESSION", _FakeSession(_tx_payload()))
        assert ft._etf_quote("515300.SS") == ("2026-10-12", 1.357)

    def test_bad_payload_returns_none(self, monkeypatch):
        monkeypatch.setattr(ft, "_SESSION", _FakeSession('v_sh999999="";'))
        assert ft._etf_quote("999999.SS") is None

    def test_intraday_quote_appended(self, monkeypatch):
        monkeypatch.setattr(ft, "_etf_series", lambda code, symbol, start, end: [
            ("2026-10-08", 1.338), ("2026-10-09", 1.34)])
        monkeypatch.setattr(ft, "_etf_quote", lambda s: ("2026-10-12", 1.357))

        value, series = ft._fetch_a_share_watch("515300.SS")
        assert series[-1] == ("2026-10-12", 1.357)
        assert value == 1.357  # 盘中即最新价（而非上一交易日收盘）

    def test_same_day_overridden_and_stale_ignored(self, monkeypatch):
        monkeypatch.setattr(ft, "_etf_quote", lambda s: ("2026-10-12", 1.357))
        monkeypatch.setattr(ft, "_etf_series", lambda code, symbol, start, end: [
            ("2026-10-09", 1.338), ("2026-10-12", 1.30)])
        _, series = ft._fetch_a_share_watch("515300.SS")
        assert series == [("2026-10-09", 1.338), ("2026-10-12", 1.357)]

        monkeypatch.setattr(ft, "_etf_quote", lambda s: ("2026-10-09", 1.20))  # 行情落后于历史
        monkeypatch.setattr(ft, "_etf_series", lambda code, symbol, start, end: [
            ("2026-10-09", 1.338), ("2026-10-12", 1.357)])
        _, series = ft._fetch_a_share_watch("515300.SS")
        assert series == [("2026-10-09", 1.338), ("2026-10-12", 1.357)]


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
        monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
        st.init_db()
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
