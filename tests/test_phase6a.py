"""六期A 美股大盘监控：SYMBOLS 扩展、大盘趋势/告警、日报两板块、context 扩展。"""

import json

import pytest

from src import analyzer as an
from src import config as cfg
from src import reporter as rep


@pytest.fixture
def clean_thresholds(monkeypatch):
    for sym in ("VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ"):
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)


class TestSymbolsAndConfig:
    def test_symbols_order_stock_first(self):
        assert list(an.SYMBOLS)[:4] == ["GSPC", "IXIC", "SH", "SZ"]
        assert list(an.SYMBOLS)[-3:] == ["VIX", "VXN", "MOVE"]
        assert an.STOCK_SYMBOLS == {"GSPC", "IXIC", "SH", "SZ"}
        assert an.A_SHARE_SYMBOLS == {"SH", "SZ"}
        assert set(an.SYMBOLS) == {"GSPC", "IXIC", "SH", "SZ", "VIX", "VXN", "MOVE"}
        assert an.SYMBOLS["SH"]["ticker"] == "000001.SS"
        assert an.SYMBOLS["SZ"]["ticker"] == "399001.SZ"

    def test_config_defaults_phase6a(self, clean_thresholds):
        assert an.alert_threshold("GSPC") == 4.0
        assert an.alert_threshold("IXIC") == 4.5
        assert an.alert_threshold("SH") == 4.0
        assert an.alert_threshold("SZ") == 4.0
        assert cfg.load_config()["trend"]["streak_days"] == 3


class TestStreakTrend:
    def _hist(self, closes):
        from datetime import date, timedelta

        start = date(2026, 1, 1)
        return [{"date": (start + timedelta(days=i)).isoformat(), "gspc": c} for i, c in enumerate(closes)]

    def test_accumulating_when_no_history(self):
        assert an.trend_label(0, False) == "数据积累中"

    def test_flat_short_streak(self):
        assert an.trend_label(2, True) == "连涨2日"
        assert an.trend_label(3, True) == "上升趋势"

    def test_rising_label(self):
        assert an.trend_label(4, True) == "上升趋势"
        assert an.trend_label(1, True) == "连涨1日"

    def test_uptrend_label(self):
        assert an.trend_label(5, True) == "上升趋势"

    def test_compute_streaks_uses_history(self):
        hist = self._hist([100, 101, 102, 103])
        st = an.compute_streaks({"GSPC": 104.0}, {"GSPC": 103.0}, hist)
        assert st["GSPC"] == 4
        assert an.trend_label(st["GSPC"], True) == "上升趋势"

    def test_compute_streaks_missing_history_accumulating(self):
        hist = self._hist([None, None, 100])
        st = an.compute_streaks({"GSPC": 101.0}, {"GSPC": 100.0}, hist)
        assert st["GSPC"] == 1


class TestBuildStatusesStock:
    def test_stock_uses_trend_label(self):
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        hist = [
            {"date": "2026-08-28", "gspc": 4390.0, "ixic": 16900.0},
            {"date": "2026-08-29", "gspc": 4400.0, "ixic": 17000.0},
        ]
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        st = an.build_statuses(values, {}, last, hist)
        assert st["GSPC"][0] == "连涨2日"
        assert st["IXIC"][0] == "连涨2日"
        assert st["VIX"][0] == "警惕"
        assert st["MOVE"][0] == "平静"

    def test_stock_missing_value_tolerated(self):
        values = {"GSPC": None, "IXIC": 17500.0, "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        st = an.build_statuses(values, {})
        assert st["GSPC"][0] == "获取失败"


class TestCheckBreachStockAlwaysWarn:
    def test_stock_breach_is_warn(self, clean_thresholds):
        alert = an.check_breach("GSPC", 4500.0, 4300.0)
        assert alert is not None
        assert alert["level"] == "WARN"
        assert alert["state"] == "异动"
        assert alert["change"] == pytest.approx(100 * (4500 - 4300) / 4300)

    def test_stock_breach_uses_threshold(self, clean_thresholds):
        assert an.check_breach("GSPC", 4450.0, 4400.0) is None


class TestReportSections:
    def test_daily_three_sections_stock_first(self):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3100.0, "SZ": 10000.0,
                  "VIX": 15.23, "VXN": 22.11, "MOVE": 95.40}
        changes = an.compute_changes(values, values)
        statuses = an.build_statuses(values, {})
        summary = an.build_summary(values, statuses, {})
        body = rep.render_report("2026-08-29", values, changes, statuses, summary, True)
        idx_stock = body.index("🌏 美股大盘")
        idx_ashare = body.index("🇨🇳 A 股大盘")
        idx_vol = body.index("📈 波动率指数")
        assert idx_stock < idx_ashare < idx_vol
        assert "标普500" in body and "纳斯达克" in body
        assert "上证指数" in body and "深证成指" in body
        assert "| VIX（恐慌指数） |" in body

    def test_snapshot_three_sections(self):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3100.0, "SZ": 10000.0,
                  "VIX": 15.23, "VXN": 22.11, "MOVE": 95.40}
        statuses = an.build_statuses(values, {})
        body = rep.render_snapshot("2026-08-29", values, statuses)
        idx_stock = body.index("🌏 美股大盘")
        idx_ashare = body.index("🇨🇳 A 股大盘")
        idx_vol = body.index("📈 波动率指数")
        assert idx_stock < idx_ashare < idx_vol


class TestContextExtension:
    def test_indices_and_history_include_gspc_ixic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path)
        monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
        an.append_history({"date": "2026-08-28", "vix": 20.0, "vxn": 18.0, "move": 75.0, "gspc": 4400.0, "ixic": 17000.0, "sh": 3100.0, "sz": 10000.0})
        an.append_history({"date": "2026-08-29", "vix": 21.0, "vxn": 19.0, "move": 78.0, "gspc": 4500.0, "ixic": 17500.0, "sh": 3120.0, "sz": 10100.0})
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        changes = an.compute_changes(values, last)
        statuses = an.build_statuses(values, {}, last, an.load_history())
        path = rep.generate_context("2026-08-29", values, changes, statuses, last)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "GSPC" in data["indices"] and "IXIC" in data["indices"]
        assert "SH" in data["indices"] and "SZ" in data["indices"]
        assert data["indices"]["GSPC"]["value"] == 4500.0
        assert data["indices"]["SH"]["value"] == 3120.0
        assert data["history_30d"]["gspc"] == [4400.0, 4500.0]
        assert data["history_30d"]["ixic"] == [17000.0, 17500.0]
        assert data["history_30d"]["sh"] == [3100.0, 3120.0]
        assert data["history_30d"]["sz"] == [10000.0, 10100.0]
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "GSPC" in data["indices"] and "IXIC" in data["indices"]
        assert data["indices"]["GSPC"]["value"] == 4500.0
        assert data["history_30d"]["gspc"] == [4400.0, 4500.0]
        assert data["history_30d"]["ixic"] == [17000.0, 17500.0]
