"""十二期相关性分析专项测试（纯 Python Pearson，零依赖；输入为日收益率，非原始价格）。

覆盖：compute_correlation 纯逻辑（收益率/对齐/缺口/最小样本/窗口/零方差/顺序）/ 报告章节与颜色 /
context 显著对键 / 入口透传。不联网，monkeypatch 取数与渲染。
"""

import json
from datetime import date, timedelta

import pytest

from src import analyzer as an
from src import reporter as rep
import daily_report as dr


# ---- 测试夹具：由收益率反推价格序列，构造 history（含 date + 小写键）--- ---


def _prices(rets, start=100.0):
    """由逐日收益率反推收盘价序列（长度 len(rets)+1）。"""
    out = [start]
    for r in rets:
        out.append(out[-1] * (1 + r))
    return out


def _hist(prices, start="2026-01-01"):
    """prices: {小写键: 价格列表}（等长）；返回 history rows（含 date）。"""
    keys = list(prices)
    n = len(prices[keys[0]])
    base = date.fromisoformat(start)
    rows = []
    for i in range(n):
        d = (base + timedelta(days=i)).isoformat()
        row = {"date": d}
        for k in keys:
            row[k] = prices[k][i]
        rows.append(row)
    return rows


@pytest.fixture
def clean_thresholds(monkeypatch):
    for sym in ("VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ", "CYB"):
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)


@pytest.fixture
def tmp_context(monkeypatch, tmp_path, clean_thresholds):
    """context/history/alerts 全部重定向到 tmp。"""
    monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
    monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
    return tmp_path


class TestComputeCorrelation:
    def test_perfect_positive(self):
        a = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
        hist = _hist({"gspc": _prices(a), "vix": _prices([x * 2 for x in a])})
        res = an.compute_correlation(hist, pairs=[("GSPC", "VIX")])
        assert res[0]["r"] == 1.0
        assert res[0]["n"] == 10

    def test_perfect_negative(self):
        a = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
        hist = _hist({"gspc": _prices(a), "vix": _prices([-x for x in a])})
        res = an.compute_correlation(hist, pairs=[("GSPC", "VIX")])
        assert res[0]["r"] == -1.0
        assert res[0]["n"] == 10

    def test_weak_correlation(self):
        a = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
        b = [0.01, -0.05, 0.02, -0.04, 0.03, -0.03, 0.04, -0.02, 0.05, -0.01]
        hist = _hist({"gspc": _prices(a), "vix": _prices(b)})
        res = an.compute_correlation(hist, pairs=[("GSPC", "VIX")])
        assert res[0]["r"] is not None
        assert abs(res[0]["r"]) < 0.5

    def test_insufficient_points(self):
        a = [0.01, 0.02, 0.03, 0.04, 0.05]
        hist = _hist({"gspc": _prices(a), "vix": _prices([x * 2 for x in a])})
        res = an.compute_correlation(hist, pairs=[("GSPC", "VIX")])
        assert res[0]["r"] is None
        assert res[0]["n"] == 5

    def test_null_rows_dropped(self):
        a = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]
        g = _prices(a)
        v = _prices([x * 2 for x in a])
        v[5] = None  # 单侧缺口行
        hist = _hist({"gspc": g, "vix": v})
        res = an.compute_correlation(hist, pairs=[("GSPC", "VIX")])
        assert res[0]["n"] == 12
        assert res[0]["r"] == 1.0

    def test_constant_series(self):
        # 恒定价格 → 收益率为 0（零方差）→ r None
        hist = _hist({"gspc": [100.0] * 11, "vix": [200.0] * 11})
        res = an.compute_correlation(hist, pairs=[("GSPC", "VIX")])
        assert res[0]["r"] is None
        assert res[0]["n"] == 10

    def test_window_truncation(self):
        a = [0.01 * i for i in range(1, 41)]  # 40 个收益率
        hist = _hist({"gspc": _prices(a), "vix": _prices([x * 2 for x in a])})
        res = an.compute_correlation(hist, pairs=[("GSPC", "VIX")])
        assert res[0]["n"] == 29  # 最后 30 行 → 29 个收益率
        assert res[0]["r"] == 1.0

    def test_default_pairs_order_keys(self):
        syms = ["gspc", "vix", "sh", "ixic", "cyb", "move"]
        prices = {k: _prices([0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]) for k in syms}
        hist = _hist(prices)
        res = an.compute_correlation(hist)
        assert len(res) == 5
        assert [(c["a"], c["b"]) for c in res] == an.CORRELATION_PAIRS
        for c in res:
            assert set(c.keys()) == {"a", "b", "pair", "r", "n"}
            assert c["pair"] == f"{an.SYMBOLS[c['a']]['label']} ↔ {an.SYMBOLS[c['b']]['label']}"

    def test_two_decimal_rounding(self):
        a = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10]
        b = [0.05, -0.05, 0.04, -0.04, 0.03, -0.03, 0.02, -0.02, 0.01, -0.01]
        hist = _hist({"gspc": _prices(a), "vix": _prices(b)})
        res = an.compute_correlation(hist, pairs=[("GSPC", "VIX")])
        r = res[0]["r"]
        assert r is not None
        assert round(r, 2) == r  # 保留两位小数（如 0.666… → 0.67）


class TestRenderReportCorrelation:
    CORR = [
        {"a": "VIX", "b": "GSPC", "pair": "VIX（恐慌指数） ↔ 标普500", "r": -0.72, "n": 30},
        {"a": "VIX", "b": "SH", "pair": "VIX（恐慌指数） ↔ 上证指数", "r": 0.62, "n": 28},
        {"a": "GSPC", "b": "SH", "pair": "标普500 ↔ 上证指数", "r": 0.12, "n": 30},
        {"a": "IXIC", "b": "CYB", "pair": "纳斯达克 ↔ 创业板指", "r": None, "n": 4},
        {"a": "MOVE", "b": "VIX", "pair": "MOVE（债市波动） ↔ VIX（恐慌指数）", "r": 0.81, "n": 30},
    ]

    def _report(self):
        from test_reporter import sample_data
        data = sample_data()
        data["correlations"] = self.CORR
        return rep.render_report(**data)

    def test_section_present(self):
        report = self._report()
        assert "## 📊 相关性分析" in report
        assert "| 指数对 | 相关系数 | 有效样本 |" in report
        assert report.count("| VIX（恐慌指数） ↔") == 2
        assert "窗口：近 30 个交易日" in report

    def test_colors(self):
        report = self._report()
        assert '<span style="color:#1a9e6c">**-0.72**</span>' in report   # r<-0.5 绿
        assert '<span style="color:#d1495b">**+0.62**</span>' in report   # r>0.5 红
        assert '<span style="color:#d1495b">**+0.81**</span>' in report   # r>0.5 红
        assert '<span style="color:#999999">**+0.12**</span>' in report   # 中间灰

    def test_none_means_insufficient(self):
        report = self._report()
        assert "数据不足" in report

    def test_absent_when_none(self):
        from test_reporter import sample_data
        report = rep.render_report(**sample_data())
        assert "📊 相关性分析" not in report


class TestGenerateContextCorrelation:
    def _inputs(self, values, last_values):
        return {
            "values": values,
            "changes": an.compute_changes(values, last_values),
            "statuses": an.build_statuses(values, {}),
            "last_values": last_values,
        }

    def test_significant_written(self, tmp_context):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        corr = [
            {"a": "VIX", "b": "GSPC", "pair": "VIX（恐慌指数） ↔ 标普500", "r": -0.72, "n": 30},
            {"a": "GSPC", "b": "SH", "pair": "标普500 ↔ 上证指数", "r": 0.12, "n": 30},
            {"a": "MOVE", "b": "VIX", "pair": "MOVE（债市波动） ↔ VIX（恐慌指数）", "r": 0.81, "n": 30},
        ]
        path = rep.generate_context("2026-08-29", **self._inputs(values, last), correlations=corr)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "correlation" in data
        sig = data["correlation"]
        assert len(sig) == 2  # 仅 |r|>0.5 写入
        assert {(c["a"], c["b"]) for c in sig} == {("VIX", "GSPC"), ("MOVE", "VIX")}
        for c in sig:
            assert set(c.keys()) == {"a", "b", "pair", "r", "n"}
        assert not (tmp_context / "context" / "2026-08-29.json.tmp").exists()

    def test_no_significant_empty(self, tmp_context):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        corr = [{"a": "GSPC", "b": "SH", "pair": "标普500 ↔ 上证指数", "r": 0.12, "n": 30}]
        data = json.loads(
            rep.generate_context("2026-08-29", **self._inputs(values, last), correlations=corr)
            .read_text(encoding="utf-8")
        )
        assert data["correlation"] == []

    def test_none_empty(self, tmp_context):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        data = json.loads(
            rep.generate_context("2026-08-29", **self._inputs(values, last))
            .read_text(encoding="utf-8")
        )
        assert data["correlation"] == []


class TestDailyReportWiring:
    def test_correlation_passed_through(self, monkeypatch, tmp_path):
        calls = {}
        sentinel = [{"a": "VIX", "b": "GSPC", "pair": "x", "r": -0.5, "n": 10}]

        def fake_fetch_all(market=None):
            return ({s: 100.0 for s in ["GSPC", "IXIC", "SH", "SZ", "CYB", "VIX", "VXN", "MOVE", "GLD", "BTC"]}, {})

        def fake_compute(history, pairs=None, window=None):
            return sentinel

        def fake_render(*a, **k):
            calls["render_corr"] = k.get("correlations")
            return "# report"

        def fake_gen(*a, **k):
            calls["gen_corr"] = k.get("correlations")
            return tmp_path / "context" / "d.json"

        def fake_trend(*a, **k):
            return None

        monkeypatch.setattr(dr, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(dr, "fetch_sector_heat", lambda: ([], []))
        monkeypatch.setattr(dr, "fetch_us_sector_heat", lambda: ([], []))
        monkeypatch.setattr(dr, "compute_correlation", fake_compute)
        monkeypatch.setattr(dr, "render_report", fake_render)
        monkeypatch.setattr(dr, "generate_context", fake_gen)
        monkeypatch.setattr(dr, "render_trend_chart", fake_trend)
        monkeypatch.setattr(dr, "save_report", lambda *a, **k: tmp_path / "r.md")
        monkeypatch.setattr(dr, "run_alert_checks", lambda *a, **k: None)
        monkeypatch.setattr(dr, "load_last_values", lambda: {})
        monkeypatch.setattr(dr, "load_history", lambda: [])
        monkeypatch.setattr(dr, "append_history", lambda *a, **k: None)
        monkeypatch.setattr(dr, "save_last_values", lambda *a, **k: None)

        rc = dr.main()
        assert rc == 0
        assert calls["render_corr"] is sentinel
        assert calls["gen_corr"] is sentinel
