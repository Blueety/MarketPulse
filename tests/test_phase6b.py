"""六期B A 股大盘监控专项测试（不联网，tmp 目录 / 常量断言）。

覆盖：SYMBOLS 7 键分组、A 股 streak（含平坦日不打断）、A 股休市特判、
A 股告警阈值（恒 WARN / 严格大于 / 独立去重）、日报三板块渲染、
history 投影（旧记录缺 sh/sz）、context 七数组、search_keywords 上限 5。
"""

import json

import pytest

from src import alerter as al
from src import analyzer as an
from src import reporter as rep
from src.config import DEFAULTS


@pytest.fixture
def clean_thresholds(monkeypatch):
    for sym in ("VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ", "CYB"):
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)


@pytest.fixture
def tmp_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(al, "ALERTS_DIR", tmp_path / "alerts")
    monkeypatch.setattr(al, "ALERTS_LOG", tmp_path / "alerts.log")
    monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
    monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
    return tmp_path


class TestSymbolsPhase6b:
    def test_seven_symbols(self):
        assert set(an.SYMBOLS) == {"GSPC", "IXIC", "SH", "SZ", "VIX", "VXN", "MOVE", "CYB", "GLD", "BTC"}

    def test_order_stock_ashare_vol(self):
        assert list(an.SYMBOLS)[:4] == ["GSPC", "IXIC", "SH", "SZ"]
        assert list(an.SYMBOLS)[-5:] == ["VIX", "VXN", "MOVE", "GLD", "BTC"]

    def test_tickers(self):
        assert an.SYMBOLS["SH"]["ticker"] == "000001.SS"
        assert an.SYMBOLS["SZ"]["ticker"] == "399001.SZ"
        assert an.SYMBOLS["CYB"]["ticker"] == "399006.SZ"

    def test_stock_and_ashare_groups(self):
        assert an.STOCK_SYMBOLS == {"GSPC", "IXIC", "SH", "SZ", "CYB"}
        assert an.A_SHARE_SYMBOLS == {"SH", "SZ", "CYB"}


class TestA股Streak:
    def _hist(self, closes):
        from datetime import date, timedelta

        start = date(2026, 1, 1)
        return [{"date": (start + timedelta(days=i)).isoformat(), "sh": c} for i, c in enumerate(closes)]

    def test_rising_four_days(self, clean_thresholds):
        hist = self._hist([100, 101, 102, 103])
        st = an.compute_streaks({"SH": 104.0}, {"SH": 103.0}, hist)
        assert st["SH"] == 4
        assert an.trend_label(st["SH"], True) == "上升趋势"

    def test_flat_day_does_not_break_streak(self, clean_thresholds):
        # 休市日（今日涨跌 0，末尾平坦）去尾 0 不打断既有连涨：4 历史连涨 + 今日平 → 仍上升趋势
        hist = self._hist([100, 101, 102, 103])
        st = an.compute_streaks({"SH": 103.0}, {"SH": 103.0}, hist)
        assert st["SH"] == 3
        assert an.trend_label(st["SH"], True) == "上升趋势"

    def test_no_history_accumulating(self, clean_thresholds):
        st = an.build_statuses({"SH": 3100.0}, {})
        assert st["SH"][0] == "数据积累中"


class Test休市:

    def test_report_ashare_row_休市(self, clean_thresholds):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": None, "SZ": None, "CYB": None,
                  "VIX": 15.23, "VXN": 22.11, "MOVE": 95.40, "GLD": 252.30, "BTC": 65000.00}
        statuses = an.build_statuses(values, {})
        body = rep.render_report("2026-08-29", values,
                                 an.compute_changes(values, values), statuses,
                                 "summary", True)
        assert "| 上证指数 | 休市 | — | 休市 |" in body
        assert "| 深证成指 | 休市 | — | 休市 |" in body
        assert "| 创业板指 | 休市 | — | 休市 |" in body


class TestA股Breach:
    def test_sh_triggers(self, clean_thresholds):
        alert = an.check_breach("SH", 104.1, 100.0)
        assert alert is not None
        assert alert["level"] == "WARN"
        assert alert["state"] == "异动"
        assert alert["threshold"] == pytest.approx(DEFAULTS["alert"]["sh"])

    def test_sh_exact_not_trigger(self, clean_thresholds):
        assert an.check_breach("SH", 102.5, 100.0) is None

    def test_sz_independent_threshold(self, clean_thresholds):
        assert an.check_breach("SZ", 104.1, 100.0) is not None
        assert an.check_breach("SZ", 103.4, 100.0) is None

    def test_env_override_sh(self, monkeypatch, clean_thresholds):
        monkeypatch.setenv("ALERT_THRESHOLD_SH", "5")
        assert an.check_breach("SH", 104.1, 100.0) is None

    def test_collect_both_sh_and_vix(self, clean_thresholds):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 104.1, "SZ": 10000.0, "CYB": 10000.0,
                  "VIX": 24.4, "VXN": 22.0, "MOVE": 80.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 100.0, "SZ": 10000.0, "CYB": 10000.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        syms = [b["symbol"] for b in al.collect_breaches(values, last)]
        assert "SH" in syms and "VIX" in syms

    def test_ashare_dedup_independent_of_vol(self, tmp_paths, clean_thresholds):
        # 午盘已告警 SH → 收盘 SH 跳过，但 VIX 仍可触发（告警独立）
        date = "2026-08-29"
        al._mark_alerted(date, {"SH"})
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 104.1, "SZ": 10000.0, "CYB": 10000.0,
                  "VIX": 24.4, "VXN": 22.0, "MOVE": 80.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 100.0, "SZ": 10000.0, "CYB": 10000.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        pending = al.run_alert_checks(date, values, last, "close", tmp_paths / "report.md")
        pending_syms = [p["symbol"] for p in pending]
        assert "SH" not in pending_syms
        assert "VIX" in pending_syms
        content = (tmp_paths / "alerts" / f"{date}-close.md").read_text(encoding="utf-8")
        assert "SH" not in content
        assert "VIX" in content


class TestReportThreeSections:
    def _seven(self):
        return {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 15.23, "VXN": 22.11, "MOVE": 95.40, "GLD": 252.30, "BTC": 65000.00}

    def test_daily_three_sections_order(self, clean_thresholds):
        values = self._seven()
        statuses = an.build_statuses(values, {})
        body = rep.render_report("2026-08-29", values,
                                 an.compute_changes(values, values), statuses,
                                 "summary", True)
        idx_stock = body.index("🌏 美股大盘")
        idx_ashare = body.index("🇨🇳 A 股大盘")
        idx_vol = body.index("📈 波动率指数")
        assert idx_stock < idx_ashare < idx_vol
        # A 股表 4 列（收盘价/涨跌幅/趋势），波动率行格式与现版一致
        assert "| 上证指数 |" in body and "| 深证成指 |" in body and "| 创业板指 |" in body
        assert "| VIX（恐慌指数） |" in body

    def test_snapshot_three_sections(self, clean_thresholds):
        values = self._seven()
        statuses = an.build_statuses(values, {})
        body = rep.render_snapshot("2026-08-29", values, statuses)
        idx_stock = body.index("🌏 美股大盘")
        idx_ashare = body.index("🇨🇳 A 股大盘")
        idx_vol = body.index("📈 波动率指数")
        assert idx_stock < idx_ashare < idx_vol


class TestHistoryProjectionPhase6b:
    def test_old_record_missing_sh_sz(self, tmp_paths):
        an.append_history({"date": "2026-08-01", "vix": 20.0, "vxn": 18.0, "move": 75.0})
        data = an.load_history()
        assert data[0]["sh"] is None
        assert data[0]["sz"] is None

    def test_record_with_sh_sz_roundtrip(self, tmp_paths):
        an.append_history({"date": "2026-08-01", "vix": 20.0, "vxn": 18.0, "move": 75.0,
                            "sh": 3100.0, "sz": 10000.0})
        data = an.load_history()
        assert data[0]["sh"] == 3100.0
        assert data[0]["sz"] == 10000.0


class TestContextPhase6b:
    def test_indices_seven_and_history_arrays(self, tmp_paths):
        an.append_history({"date": "2026-08-28", "vix": 20.0, "vxn": 18.0, "move": 75.0,
                            "gspc": 4400.0, "ixic": 17000.0, "sh": 3100.0, "sz": 10000.0, "cyb": 2200.0})
        an.append_history({"date": "2026-08-29", "vix": 21.0, "vxn": 19.0, "move": 78.0,
                            "gspc": 4500.0, "ixic": 17500.0, "sh": 3120.0, "sz": 10100.0, "cyb": 2210.0})
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        path = rep.generate_context(
            "2026-08-29",
            values,
            an.compute_changes(values, last),
            an.build_statuses(values, {}, last, an.load_history()),
            last,
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert set(data["indices"]) == set(an.SYMBOLS)
        assert data["indices"]["SH"]["value"] == 3120.0
        assert data["indices"]["CYB"]["value"] == 2210.0
        h = data["history_30d"]
        assert len(h["sh"]) == len(h["sz"]) == len(h["cyb"]) == len(h["dates"]) == 2
        assert h["sh"] == [3100.0, 3120.0]
        assert h["sz"] == [10000.0, 10100.0]
        assert h["cyb"] == [2200.0, 2210.0]


class TestSearchKeywordsCap:
    def test_four_breaches_capped_at_five(self, clean_thresholds):
        breaches = [
            {"symbol": "GSPC", "change": 5.0},
            {"symbol": "SH", "change": 4.5},
            {"symbol": "SZ", "change": -4.2},
            {"symbol": "VIX", "change": 22.0},
        ]
        kw = an.build_search_keywords("2026-08-29", breaches)
        assert len(kw) == 5  # 4 异动词 + 2 定向词 → 截断到 5

    def test_three_breaches_unchanged(self, clean_thresholds):
        breaches = [
            {"symbol": "VIX", "change": 22.0},
            {"symbol": "VXN", "change": 21.0},
            {"symbol": "MOVE", "change": -16.0},
        ]
        kw = an.build_search_keywords("2026-08-29", breaches)
        assert len(kw) == 5
