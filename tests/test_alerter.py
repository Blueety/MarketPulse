"""三期告警单元测试：check_breach 边界/级别/env、alerter 去重/渲染/编排（不联网，tmp 目录）。"""

import pytest

from src import alerter as al
from src import analyzer as an


@pytest.fixture
def clean_thresholds(monkeypatch):
    for sym in ("VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ"):
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)


@pytest.fixture
def tmp_paths(monkeypatch, tmp_path):
    """告警目录/日志重定向到 tmp，避开真实 data/alerts。"""
    monkeypatch.setattr(al, "ALERTS_DIR", tmp_path / "alerts")
    monkeypatch.setattr(al, "ALERTS_LOG", tmp_path / "alerts.log")
    return tmp_path


class TestAlertThreshold:
    def test_defaults(self, clean_thresholds):
        assert an.alert_threshold("VIX") == 20.0
        assert an.alert_threshold("VXN") == 20.0
        assert an.alert_threshold("MOVE") == 15.0

    def test_env_override(self, monkeypatch, clean_thresholds):
        monkeypatch.setenv("ALERT_THRESHOLD_VIX", "30")
        assert an.alert_threshold("VIX") == 30.0

    def test_invalid_env_falls_back(self, monkeypatch, clean_thresholds):
        monkeypatch.setenv("ALERT_THRESHOLD_VIX", "abc")
        assert an.alert_threshold("VIX") == 20.0

    def test_nonpositive_env_falls_back(self, monkeypatch, clean_thresholds):
        monkeypatch.setenv("ALERT_THRESHOLD_MOVE", "0")
        assert an.alert_threshold("MOVE") == 15.0


class TestCheckBreach:
    def test_missing_data_returns_none(self, clean_thresholds):
        assert an.check_breach("VIX", None, 20.0) is None
        assert an.check_breach("VIX", 24.0, None) is None
        assert an.check_breach("VIX", 24.0, 0.0) is None

    def test_equal_threshold_not_trigger(self, clean_thresholds):
        # +20.0% 恰好等于阈值：严格大于才触发（设计 A）
        assert an.check_breach("VIX", 24.0, 20.0) is None

    def test_above_threshold_trigger_warn(self, clean_thresholds):
        alert = an.check_breach("VIX", 24.4, 20.0)  # +22%
        assert alert is not None
        assert alert["symbol"] == "VIX"
        assert alert["level"] == "WARN"
        assert alert["change"] == pytest.approx(22.0)
        assert alert["threshold"] == 20.0
        assert alert["state"] == "警惕"
        assert alert["suggestion"]

    def test_below_negative_threshold_trigger(self, clean_thresholds):
        # -21% 同样触发（绝对值超过阈值，双向告警）
        alert = an.check_breach("VIX", 15.8, 20.0)
        assert alert is not None
        assert alert["level"] == "WARN"

    def test_panic_level_alert_vix(self, clean_thresholds):
        # VIX 35（>=30 恐慌）从 28 涨 +25%：升级 ALERT（设计 B）
        alert = an.check_breach("VIX", 35.0, 28.0)
        assert alert is not None
        assert alert["level"] == "ALERT"
        assert alert["state"] == "恐慌"

    def test_panic_level_alert_move(self, clean_thresholds):
        # MOVE 135（>=130 恐慌）从 110 涨 +22.7%：ALERT
        alert = an.check_breach("MOVE", 135.0, 110.0)
        assert alert is not None
        assert alert["level"] == "ALERT"

    def test_env_threshold_applied(self, monkeypatch, clean_thresholds):
        monkeypatch.setenv("ALERT_THRESHOLD_VIX", "30")
        assert an.check_breach("VIX", 24.4, 20.0) is None  # +22% < 30
        assert an.check_breach("VIX", 26.0, 20.0) is None  # +30% 恰好等于，不触发
        assert an.check_breach("VIX", 26.2, 20.0) is not None  # +31% > 30


class TestAlertedLog:
    def test_mark_and_load_same_day(self, tmp_paths):
        al._mark_alerted("2026-09-01", {"VIX"})
        assert al._load_alerted("2026-09-01") == {"VIX"}

    def test_log_keeps_today_only(self, tmp_paths):
        al._mark_alerted("2026-09-01", {"VIX", "VXN"})
        al._mark_alerted("2026-09-02", {"MOVE"})
        assert al._load_alerted("2026-09-02") == {"MOVE"}  # 旧日行已清除（设计 C）
        assert al._load_alerted("2026-09-01") == set()

    def test_missing_log_is_empty(self, tmp_paths):
        assert al._load_alerted("2026-09-01") == set()

    def test_ignores_malformed_lines(self, tmp_paths):
        (tmp_paths / "alerts.log").write_text("garbage line\n2026-09-01 VIX\n", encoding="utf-8")
        assert al._load_alerted("2026-09-01") == {"VIX"}


class TestRenderAlert:
    def test_format(self, tmp_paths, clean_thresholds):
        alert = an.check_breach("VIX", 24.4, 20.0)
        assert alert is not None
        content = al.render_alert(alert, "2026-09-01", "close", tmp_paths / "2026-09-01.md")
        assert content.startswith("---\ntype: close\n")
        assert "date: 2026-09-01" in content
        assert "symbol: VIX" in content
        assert "level: WARN" in content
        assert "VIX（恐慌指数）告警" in content
        assert "- 当前值：24.40" in content
        assert "- 昨日收盘：20.00" in content
        assert "+22.00%（阈值 ±20.0%）" in content
        assert "- 市场状态：警惕" in content
        assert "- 相关报告：2026-09-01.md" in content


class TestRunAlertChecks:
    def _breaching_values(self):
        # VIX +22%、VXN +22.2% 触发；MOVE +6.7% 不触发
        return {"GSPC": 4500.0, "IXIC": 17500.0, "VIX": 24.4, "VXN": 22.0, "MOVE": 80.0}, {"GSPC": 4400.0, "IXIC": 17000.0, "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}

    def test_generates_alert_file(self, tmp_paths, clean_thresholds):
        values, last = self._breaching_values()
        alerts = al.run_alert_checks("2026-09-01", values, last, "close", tmp_paths / "2026-09-01.md")
        assert [a["symbol"] for a in alerts] == ["VIX", "VXN"]
        path = tmp_paths / "alerts" / "2026-09-01-close.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert content.count("---\ntype: close") == 2  # 两指数各一个附录块
        assert "## ⚠️ VIX（恐慌指数）告警" in content
        assert "## ⚠️ VXN（科技波动）告警" in content

    def test_dedup_same_day(self, tmp_paths, clean_thresholds):
        values, last = self._breaching_values()
        al.run_alert_checks("2026-09-01", values, last, "close", tmp_paths / "daily.md")
        assert al.run_alert_checks("2026-09-01", values, last, "close", tmp_paths / "daily.md") == []

    def test_noon_then_close_dedup(self, tmp_paths, clean_thresholds):
        # 午盘触发则收盘跳过同一指数（决策 2）
        values, last = self._breaching_values()
        al.run_alert_checks("2026-09-01", values, last, "noon", tmp_paths / "snap.md")
        assert (tmp_paths / "alerts" / "2026-09-01-noon.md").exists()
        assert al.run_alert_checks("2026-09-01", values, last, "close", tmp_paths / "daily.md") == []
        assert not (tmp_paths / "alerts" / "2026-09-01-close.md").exists()

    def test_cross_day_retriggers(self, tmp_paths, clean_thresholds):
        values, last = self._breaching_values()
        al.run_alert_checks("2026-09-01", values, last, "close", tmp_paths / "a.md")
        alerts = al.run_alert_checks("2026-09-02", values, last, "close", tmp_paths / "b.md")
        assert [a["symbol"] for a in alerts] == ["VIX", "VXN"]

    def test_no_breach_no_file(self, tmp_paths, clean_thresholds):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        assert al.run_alert_checks("2026-09-01", values, last, "close", tmp_paths / "daily.md") == []
        assert not (tmp_paths / "alerts" / "2026-09-01-close.md").exists()

    def test_missing_data_skipped(self, tmp_paths, clean_thresholds):
        values = {"GSPC": None, "IXIC": None, "VIX": None, "VXN": 22.0, "MOVE": None}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        alerts = al.run_alert_checks("2026-09-01", values, last, "close", tmp_paths / "daily.md")
        assert [a["symbol"] for a in alerts] == ["VXN"]

    def test_single_index_failure_isolated(self, tmp_paths, clean_thresholds, monkeypatch):
        # 单指数 check_breach 异常不影响其他指数（决策 H）
        real = an.check_breach

        def flaky(sym, current, last):
            if sym == "VIX":
                raise RuntimeError("boom")
            return real(sym, current, last)

        monkeypatch.setattr(al, "check_breach", flaky)
        values, last = self._breaching_values()
        alerts = al.run_alert_checks("2026-09-01", values, last, "close", tmp_paths / "daily.md")
        assert [a["symbol"] for a in alerts] == ["VXN"]
