"""src/analyzer.py 纯逻辑单元测试（不联网）。"""

import json
import re
from datetime import date, timedelta

import pytest

from src import analyzer as an


class TestClassifyVix:
    @pytest.mark.parametrize(
        ("value", "label"),
        [
            (15.00, "平静"),
            (19.99, "平静"),
            (20.00, "警惕"),   # 下界含
            (29.99, "警惕"),
            (30.00, "恐慌"),   # 上界含
            (45.00, "恐慌"),
        ],
    )
    def test_boundaries(self, value, label):
        assert an.classify_vix(value)[0] == label

    def test_vxn_reuses_vix(self):
        assert an.classify_vix(25.0)[0] == an.classify_vix(25.0)[0] == "警惕"


class TestClassifyMove:
    @pytest.mark.parametrize(
        ("value", "label"),
        [
            (80.00, "平静"),
            (99.99, "平静"),
            (100.00, "警惕"),  # 下界含
            (129.99, "警惕"),
            (130.00, "恐慌"),  # 上界含
            (150.00, "恐慌"),
        ],
    )
    def test_boundaries(self, value, label):
        assert an.classify_move(value)[0] == label


class TestComputeChanges:
    def test_normal(self):
        assert an.compute_changes({"VIX": 22.0}, {"VIX": 20.0})["VIX"] == pytest.approx(10.0)

    def test_negative(self):
        assert an.compute_changes({"VIX": 19.0}, {"VIX": 20.0})["VIX"] == pytest.approx(-5.0)

    def test_first_run_returns_none(self):
        assert an.compute_changes({"VIX": 22.0}, {})["VIX"] is None

    def test_symbol_missing_in_last_returns_none(self):
        assert an.compute_changes({"VIX": 22.0, "MOVE": 95.0}, {"VIX": 20.0})["MOVE"] is None

    def test_div_zero_protected(self):
        assert an.compute_changes({"VIX": 22.0}, {"VIX": 0.0})["VIX"] is None

    def test_failed_value_returns_none(self):
        assert an.compute_changes({"VIX": None}, {"VIX": 20.0})["VIX"] is None


class TestBuildStatuses:
    def test_ok(self):
        statuses = an.build_statuses(
            {"GSPC": 4500.0, "IXIC": 17500.0, "VIX": 15.0, "VXN": 25.0, "MOVE": 95.0}, {}
        )
        assert statuses["VIX"][0] == "平静"
        assert statuses["VXN"][0] == "警惕"
        assert statuses["MOVE"][0] == "平静"

    def test_fetch_failed(self):
        statuses = an.build_statuses(
            {"GSPC": 4500.0, "IXIC": 17500.0, "VIX": 15.0, "VXN": None, "MOVE": 95.0},
            {"VXN": "获取失败（已重试）"},
        )
        assert statuses["VXN"][0] == "未开盘"
        assert statuses["MOVE"][0] == "平静"


class TestBuildSummary:
    def test_complete(self):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "VIX": 15.23, "VXN": 22.11, "MOVE": 95.40}
        statuses = an.build_statuses(values, {})
        summary = an.build_summary(values, statuses, {})
        assert "VIX 收于 15.23" in summary
        assert "获取完整" in summary

    def test_partial_failure(self):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "VIX": 15.23, "VXN": None, "MOVE": 95.40}
        statuses = an.build_statuses(values, {"VXN": "获取失败（已重试）"})
        summary = an.build_summary(values, statuses, {"VXN": "获取失败（已重试）"})
        assert "VXN" in summary and "获取失败" in summary

    def test_all_failed(self):
        values = {"GSPC": None, "IXIC": None, "VIX": None, "VXN": None, "MOVE": None}
        errors = {
            "VIX": "获取失败（已重试）",
            "VXN": "获取失败（已重试）",
            "MOVE": "获取失败（已重试）",
        }
        statuses = an.build_statuses(values, errors)
        summary = an.build_summary(values, statuses, errors)
        assert "无法判断整体市场情绪" in summary
        assert "MOVE" in summary


class TestGetUsEasternDate:
    def test_format(self):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", an.get_us_eastern_date())


class TestFormatters:
    def test_fmt_value(self):
        assert an.fmt_value(15.234) == "15.23"
        assert an.fmt_value(None) == "未开盘"

    def test_fmt_change(self):
        assert an.fmt_change(1.23, True, 10.0) == "+1.23%"
        assert an.fmt_change(-0.5, True, 10.0) == "-0.50%"
        assert an.fmt_change(0.0, True, 10.0) == "0.00%"
        assert an.fmt_change(None, True, 10.0) == "—"
        assert an.fmt_change(1.23, False, 10.0) == "首次运行，暂无历史对比"
        assert an.fmt_change(1.23, True, None) == "—"


class TestHistory:
    def _set_file(self, tmp_path, monkeypatch) -> "Path":
        history_file = tmp_path / "history.json"
        monkeypatch.setattr(an, "HISTORY_FILE", history_file)
        return history_file

    def test_append_and_load(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.append_history({"date": "2026-08-01", "vix": 22.3, "vxn": 26.1, "move": 72.5})
        data = an.load_history()
        assert data[0] == {"date": "2026-08-01", "vix": 22.3, "vxn": 26.1, "move": 72.5, "gspc": None, "ixic": None, "sh": None, "sz": None, "cyb": None, "gld": None, "btc": None}

    def test_same_date_overrides(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.append_history({"date": "2026-08-01", "vix": 22.3, "vxn": 26.1, "move": 72.5})
        an.append_history({"date": "2026-08-01", "vix": 23.0, "vxn": 26.1, "move": 72.5})
        data = an.load_history()
        assert len(data) == 1
        assert data[0]["vix"] == pytest.approx(23.0)

    def test_rolling_90(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        start = date(2026, 1, 1)
        for i in range(95):
            an.append_history(
                {"date": (start + timedelta(days=i)).isoformat(), "vix": 20.0, "vxn": 25.0, "move": 70.0}
            )
        data = an.load_history()
        assert len(data) == 90
        assert data[0]["date"] == (start + timedelta(days=5)).isoformat()  # 最早 5 条被滚动掉
        assert data[-1]["date"] == (start + timedelta(days=94)).isoformat()

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        assert an.load_history() == []

    def test_corrupt_file_returns_empty(self, tmp_path, monkeypatch):
        history_file = self._set_file(tmp_path, monkeypatch)
        history_file.write_text("{broken json", encoding="utf-8")
        assert an.load_history() == []

    def test_non_list_returns_empty(self, tmp_path, monkeypatch):
        history_file = self._set_file(tmp_path, monkeypatch)
        history_file.write_text(json.dumps({"date": "2026-08-01"}), encoding="utf-8")
        assert an.load_history() == []

    def test_append_after_corrupt_recovers(self, tmp_path, monkeypatch):
        history_file = self._set_file(tmp_path, monkeypatch)
        history_file.write_text("{broken", encoding="utf-8")
        an.append_history({"date": "2026-08-01", "vix": 22.3, "vxn": 26.1, "move": 72.5})
        data = an.load_history()
        assert len(data) == 1
        assert data[0]["date"] == "2026-08-01"
        assert not history_file.with_name("history.json.tmp").exists()  # 临时文件已清理


def _wl_hist(dates, gspc):
    return [{"date": d, "vix": 20.0, "vxn": 18.0, "move": 75.0,
             "gspc": g, "ixic": g * 4, "sh": 3000.0, "sz": 10000.0, "cyb": 2200.0,
             "gld": 200.0, "btc": 60000.0} for d, g in zip(dates, gspc)]


def _wl_series(dates, fn):
    return [(d, fn(i)) for i, d in enumerate(dates)]


class TestComputePortfolioCorrelation:
    def _dates(self, n=12):
        return [f"2026-08-{i:02d}" for i in range(1, n + 1)]

    def test_positive_benchmark_corr(self):
        dates = self._dates()
        hist = _wl_hist(dates, [100 + i for i in range(12)])
        data = [{"symbol": "STK", "label": "Stock", "series": _wl_series(dates, lambda i: 50 + i)}]
        out = an.compute_portfolio_correlation(data, hist)
        st = out["stocks"][0]
        assert st["benchmark"] == "GSPC"
        assert st["r"] == pytest.approx(1.0, abs=0.01)
        assert st["n"] >= 10
        assert out["portfolio_risk"]["avg_r"] is None
    def test_negative_benchmark_corr(self):
        dates = self._dates()
        # bench 按 rets 累积、series 按 -rets 累积 → 反向 → 负相关
        rets = [0.05, -0.03, 0.04, -0.02, 0.06, -0.01, 0.03, -0.04, 0.02, -0.05, 0.03, -0.02]
        b = 100.0
        s = 50.0
        bvals, svals = [], []
        for r in rets:
            bvals.append(b)
            svals.append(s)
            b *= (1 + r)
            s *= (1 - r)
        hist = _wl_hist(dates, bvals)
        series = list(zip(dates, svals))
        data = [{"symbol": "STK", "label": "Stock", "series": series}]
        out = an.compute_portfolio_correlation(data, hist)
        assert out["stocks"][0]["r"] == pytest.approx(-1.0, abs=0.01)

    def test_a_share_benchmark(self):
        dates = self._dates()
        hist = _wl_hist(dates, [100 + i for i in range(12)])
        data = [{"symbol": "600519.SS", "label": "茅台", "series": _wl_series(dates, lambda i: 1800 + i)}]
        out = an.compute_portfolio_correlation(data, hist)
        assert out["stocks"][0]["benchmark"] == "SH"

    def test_insufficient_data(self):
        dates = self._dates()
        hist = _wl_hist(dates, [100 + i for i in range(12)])
        data = [{"symbol": "STK", "label": "Stock", "series": [("2026-08-01", 50.0)]}]
        out = an.compute_portfolio_correlation(data, hist)
        assert out["stocks"][0]["r"] is None
        assert out["stocks"][0]["n"] == 0

    def test_gap_disconnect_insufficient(self):
        dates = self._dates()
        hist = _wl_hist(dates, [100 + i for i in range(12)])
        # 去掉两个连续日期 → 两段各 <10 回报 → n<10 → r None
        series = [(d, 50 + i) for i, d in enumerate(dates) if d not in ("2026-08-06", "2026-08-07")]
        data = [{"symbol": "STK", "label": "Stock", "series": series}]
        out = an.compute_portfolio_correlation(data, hist)
        assert out["stocks"][0]["r"] is None

    def test_concentration_high(self):
        dates = self._dates()
        hist = _wl_hist(dates, [100 + i for i in range(12)])
        s = _wl_series(dates, lambda i: 50 + i)
        data = [
            {"symbol": "A", "label": "A", "series": s},
            {"symbol": "B", "label": "B", "series": s},
        ]
        out = an.compute_portfolio_correlation(data, hist)
        assert out["portfolio_risk"]["high"] is True
        assert out["portfolio_risk"]["avg_r"] == pytest.approx(1.0, abs=0.01)

    def test_concentration_not_high(self):
        dates = self._dates()
        hist = _wl_hist(dates, [100 + i for i in range(12)])
        s1 = _wl_series(dates, lambda i: 50 + i)
        s2 = _wl_series(dates, lambda i: 50 + (1 if i % 2 == 0 else -1))
        data = [
            {"symbol": "A", "label": "A", "series": s1},
            {"symbol": "B", "label": "B", "series": s2},
        ]
        out = an.compute_portfolio_correlation(data, hist)
        assert out["portfolio_risk"]["avg_r"] == pytest.approx(0.0, abs=0.05)
        assert out["portfolio_risk"]["high"] is False

    def test_threshold_param(self):
        dates = self._dates()
        hist = _wl_hist(dates, [100 + i for i in range(12)])
        s = _wl_series(dates, lambda i: 50 + i)
        data = [
            {"symbol": "A", "label": "A", "series": s},
            {"symbol": "B", "label": "B", "series": s},
        ]
        out = an.compute_portfolio_correlation(data, hist, threshold=1.5)
        assert out["portfolio_risk"]["high"] is False

    def test_empty(self):
        dates = self._dates()
        hist = _wl_hist(dates, [100 + i for i in range(12)])
        out = an.compute_portfolio_correlation([], hist)
        assert out == {"stocks": [], "portfolio_risk": {"high": False, "avg_r": None}}
