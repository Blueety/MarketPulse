"""七期盘中快照扩展专项测试（不联网，tmp 目录 / 常量断言 / monkeypatch 编排）。

覆盖：SYMBOLS 8 键 + 创业板接线、市场日期、市场过滤取数、单板块渲染、
快照 suffix 落盘、创业板告警（阈值/严格大于/env）、告警文件复合名防碰撞、
跨市场去重、入口编排。
"""

import re

import pytest

from src import alerter as al
from src import analyzer as an
from src import fetcher as ft
from src import reporter as rep
import snapshot_report as snap


@pytest.fixture
def clean_thresholds(monkeypatch):
    for sym in ("VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ", "CYB"):
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)


@pytest.fixture
def tmp_paths(monkeypatch, tmp_path):
    """告警目录/日志重定向到 tmp，避开真实 data/alerts。"""
    monkeypatch.setattr(al, "ALERTS_DIR", tmp_path / "alerts")
    monkeypatch.setattr(al, "ALERTS_LOG", tmp_path / "alerts.log")
    return tmp_path


class TestSymbolsPhase7:
    def test_symbols_count_and_order(self):
        assert set(an.SYMBOLS) == {"GSPC", "IXIC", "SH", "SZ", "CYB", "VIX", "VXN", "MOVE", "GLD", "BTC"}
        # 前五顺序：美股大盘 → A 股大盘（含创业板）
        assert list(an.SYMBOLS)[:5] == ["GSPC", "IXIC", "SH", "SZ", "CYB"]
        assert list(an.SYMBOLS)[-5:] == ["VIX", "VXN", "MOVE", "GLD", "BTC"]

    def test_cyb_ticker(self):
        assert an.SYMBOLS["CYB"]["label"] == "创业板指"
        assert an.SYMBOLS["CYB"]["ticker"] == "399006.SZ"

    def test_groups(self):
        assert an.STOCK_SYMBOLS == {"GSPC", "IXIC", "SH", "SZ", "CYB"}
        assert an.A_SHARE_SYMBOLS == {"SH", "SZ", "CYB"}

    def test_markets(self):
        assert ft.MARKETS == {
            "a-share": {"SH", "SZ", "CYB"},
            "us": {"GSPC", "IXIC"},
            "alt": {"GLD", "BTC"},
        }


class TestMarketDate:
    def test_format(self):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", an.get_market_date("a-share"))
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", an.get_market_date("us"))


class TestFetchAllMarket:
    def test_subsets(self, monkeypatch):
        monkeypatch.setattr(ft, "sleep", lambda *a, **k: None)
        monkeypatch.setattr(ft, "fetch_with_retry", lambda name, fn, retries=1: 1.0)
        a_values, _ = ft.fetch_all("a-share")
        u_values, _ = ft.fetch_all("us")
        full_values, _ = ft.fetch_all()
        assert set(a_values) == {"SH", "SZ", "CYB"}
        assert set(u_values) == {"GSPC", "IXIC"}
        assert set(full_values) == set(ft.SYMBOLS)


class TestRenderMarketSnapshot:
    def test_a_share_midday(self):
        values = {"SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0}
        statuses = an.build_statuses(values, {})
        body = rep.render_snapshot("2026-08-29", values, statuses, market="a-share", time="midday")
        assert "🇨🇳 A 股大盘" in body
        assert "创业板指" in body
        assert "北京时间" in body
        assert "午盘" in body
        assert "美股大盘" not in body
        assert "波动率" not in body
        assert "VIX 当前值" not in body

    def test_us_open(self):
        values = {"GSPC": 4500.0, "IXIC": 17500.0}
        statuses = an.build_statuses(values, {})
        body = rep.render_snapshot("2026-08-29", values, statuses, market="us", time="open")
        assert "🌏 美股大盘" in body
        assert "标普500" in body and "纳斯达克" in body
        assert "美东时间" in body
        assert "开盘" in body
        assert "A 股大盘" not in body
        assert "波动率" not in body

    def test_a_share_none_is_休市(self):
        values = {"SH": None, "SZ": None, "CYB": None}
        statuses = an.build_statuses(values, {})
        body = rep.render_snapshot("2026-08-29", values, statuses, market="a-share", time="midday")
        assert "| 上证指数 | 休市 | 休市 |" in body
        assert "| 创业板指 | 休市 | 休市 |" in body

    def test_a_share_with_sector_heat(self):
        values = {"SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0}
        statuses = an.build_statuses(values, {})
        sector_heat = (
            [{"name": "创新药", "change": 5.2, "turnover": "10.0亿", "top_stock": "A制药"}],
            [{"name": "白酒", "change": -2.5, "turnover": "8.0亿", "top_stock": "B酒业"}],
        )
        body = rep.render_snapshot(
            "2026-08-29", values, statuses, market="a-share", time="close", sector_heat=sector_heat
        )
        assert "## 🔥 A 股热点板块 Top 5" in body
        assert "## 📉 A 股领跌板块 Top 5" in body
        assert "| 创新药 | +5.20% | 10.0亿 | A制药 |" in body
        assert "| 白酒 | -2.50% | 8.0亿 | B酒业 |" in body

    def test_a_share_empty_sector_heat_shows_placeholder(self):
        values = {"SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0}
        statuses = an.build_statuses(values, {})
        body = rep.render_snapshot(
            "2026-08-29", values, statuses, market="a-share", time="close", sector_heat=([], [])
        )
        assert body.count("| 数据暂缺 | — | — | — |") == 2

    def test_us_snapshot_ignores_sector_heat(self):
        values = {"GSPC": 4500.0, "IXIC": 17500.0}
        statuses = an.build_statuses(values, {})
        body = rep.render_snapshot("2026-08-29", values, statuses, market="us", time="open")
        assert "热点板块" not in body
        assert "领跌板块" not in body

    def test_none_branch_unchanged_three_sections(self):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                  "VIX": 15.23, "VXN": 22.11, "MOVE": 95.40}
        statuses = an.build_statuses(values, {})
        body = rep.render_snapshot("2026-08-29", values, statuses)
        assert "美股大盘" in body and "A 股大盘" in body and "波动率指数" in body
        assert "盘中快照（美东 12:30）" in body


class TestSaveSnapshotSuffix:
    def test_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "SNAPSHOTS_DIR", tmp_path)
        path = rep.save_snapshot("2026-08-29", "# 快照", suffix="a-share-close")
        assert path == tmp_path / "2026-08-29-a-share-close.md"
        assert path.exists()

    def test_default_noon(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "SNAPSHOTS_DIR", tmp_path)
        path = rep.save_snapshot("2026-08-29", "# 快照")
        assert path == tmp_path / "2026-08-29-noon.md"


class TestCYBBreach:
    def test_triggers(self, clean_thresholds):
        alert = an.check_breach("CYB", 105.1, 100.0)
        assert alert is not None
        assert alert["level"] == "WARN"
        assert alert["state"] == "异动"
        assert alert["threshold"] == pytest.approx(5.0)

    def test_exact_not_trigger(self, clean_thresholds):
        assert an.check_breach("CYB", 105.0, 100.0) is None

    def test_env_override(self, monkeypatch, clean_thresholds):
        monkeypatch.setenv("ALERT_THRESHOLD_CYB", "6")
        assert an.check_breach("CYB", 105.1, 100.0) is None  # +5.1% < 6

    def test_streak(self):
        from datetime import date, timedelta

        start = date(2026, 8, 1)
        hist = [{"date": (start + timedelta(days=i)).isoformat(), "cyb": 100.0 + i} for i in range(3)]
        st = an.compute_streaks({"CYB": 104.0}, {"CYB": 103.0}, hist)
        assert st["CYB"] > 0  # 创业板接入大盘 streak 计算


class TestAlertFileNoCollision:
    def test_composite_type_coexists(self, tmp_paths, clean_thresholds):
        date = "2026-08-29"
        # a-share-close 触发 SH；日报 close 触发 VIX；不同 symbol 互不 dedup 干扰
        v1 = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 104.1, "SZ": 10000.0, "CYB": 10000.0,
              "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        l1 = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 100.0, "SZ": 10000.0, "CYB": 10000.0,
              "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        al.run_alert_checks(date, v1, l1, "a-share-close", tmp_paths / "snap.md")
        v2 = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 100.0, "SZ": 10000.0, "CYB": 10000.0,
              "VIX": 24.4, "VXN": 19.0, "MOVE": 78.0}
        l2 = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 100.0, "SZ": 10000.0, "CYB": 10000.0,
              "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        al.run_alert_checks(date, v2, l2, "close", tmp_paths / "daily.md")
        f_ashare = tmp_paths / "alerts" / f"{date}-a-share-close.md"
        f_close = tmp_paths / "alerts" / f"{date}-close.md"
        assert f_ashare.exists() and f_close.exists()
        assert "SH" in f_ashare.read_text(encoding="utf-8")
        assert "VIX" in f_close.read_text(encoding="utf-8")


class TestDedupMarketScoped:
    def test_ashare_midday_then_close_skip(self, tmp_paths, clean_thresholds):
        date = "2026-08-29"
        al._mark_alerted(date, {"SH"})  # 模拟午盘已触发 SH
        v = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 104.1, "SZ": 10000.0, "CYB": 10000.0,
             "VIX": 24.4, "VXN": 19.0, "MOVE": 78.0}
        l = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 100.0, "SZ": 10000.0, "CYB": 10000.0,
             "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        al.run_alert_checks(date, v, l, "a-share-close", tmp_paths / "snap.md")
        content = (tmp_paths / "alerts" / f"{date}-a-share-close.md").read_text(encoding="utf-8")
        assert "SH" not in content
        assert "VIX" in content

    def test_us_open_then_noon_skip(self, tmp_paths, clean_thresholds):
        date = "2026-08-29"
        al._mark_alerted(date, {"GSPC"})  # 模拟美股开盘已触发 GSPC
        v = {"GSPC": 4600.0, "IXIC": 17500.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
             "VIX": 24.4, "VXN": 19.0, "MOVE": 78.0}
        l = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
             "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        al.run_alert_checks(date, v, l, "us-noon", tmp_paths / "snap.md")
        content = (tmp_paths / "alerts" / f"{date}-us-noon.md").read_text(encoding="utf-8")
        assert "GSPC" not in content
        assert "VIX" in content

    def test_cross_market_independent(self, tmp_paths, clean_thresholds):
        date = "2026-08-29"
        al._mark_alerted(date, {"SH"})  # A 股标记不影响美股
        v = {"GSPC": 4600.0, "IXIC": 17500.0, "SH": 104.1, "SZ": 10000.0, "CYB": 10000.0,
             "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        l = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 100.0, "SZ": 10000.0, "CYB": 10000.0,
             "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        al.run_alert_checks(date, v, l, "us-open", tmp_paths / "snap.md")
        content = (tmp_paths / "alerts" / f"{date}-us-open.md").read_text(encoding="utf-8")
        assert "GSPC" in content  # SH 标记不影响 GSPC


class TestSnapshotEntryOrchestration:
    def _patch(self, monkeypatch, tmp_path):
        calls = {}

        def fake_fetch_all(market=None):
            calls["market"] = market
            if market == "a-share":
                return ({"SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0}, {})
            return ({"GSPC": 4500.0, "IXIC": 17500.0}, {})

        def fake_fetch_sector_heat(top_n=5):
            calls["sector_heat_called"] = True
            return ([{"name": "x", "change": 1.0, "turnover": "1亿", "top_stock": "X"}], [])

        def fake_render(date, values, statuses, market=None, time="noon", sector_heat=None):
            calls["render_market"] = market
            calls["render_time"] = time
            calls["render_sector_heat"] = sector_heat
            return "# snap"

        def fake_save(date, content, suffix="noon"):
            calls["suffix"] = suffix
            return tmp_path / f"{date}-{suffix}.md"

        def fake_alert(date, values, last, alert_type, report_path):
            calls["alert_type"] = alert_type
            return []

        monkeypatch.setattr(snap, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(snap, "fetch_sector_heat", fake_fetch_sector_heat)
        monkeypatch.setattr(snap, "load_last_values", lambda: {})
        monkeypatch.setattr(snap, "load_history", lambda: [])
        monkeypatch.setattr(snap, "build_statuses", lambda *a, **k: {})
        monkeypatch.setattr(snap, "render_snapshot", fake_render)
        monkeypatch.setattr(snap, "save_snapshot", fake_save)
        monkeypatch.setattr(snap, "run_alert_checks", fake_alert)
        return calls

    def test_a_share_midday(self, monkeypatch, tmp_path):
        calls = self._patch(monkeypatch, tmp_path)
        rc = snap.main("a-share", "midday")
        assert rc == 0
        assert calls["sector_heat_called"] is True
        assert calls["render_sector_heat"] == ([{"name": "x", "change": 1.0, "turnover": "1亿", "top_stock": "X"}], [])
        assert calls["suffix"] == "a-share-midday"
        assert calls["alert_type"] == "a-share-midday"
        assert calls["render_market"] == "a-share"
        assert calls["render_time"] == "midday"

    def test_default_parse(self):
        args = snap.parse_args([])
        assert args.market == "us"
        assert args.time == "noon"

    def test_parse_market_time(self):
        args = snap.parse_args(["--market", "us", "--time", "open"])
        assert args.market == "us"
        assert args.time == "open"
