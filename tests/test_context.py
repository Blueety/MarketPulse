"""四期上下文单元测试：build_search_keywords 边界 + generate_context 端到端（不联网，tmp 目录）。

覆盖：关键词方向/计数 3-5、breach 字段映射、常规/异动/全源失败、幂等（不产告警文件、
alerts.log 不动）、history_30d 窗口、原子写。
"""

import json

import pytest

from src import alerter as al
from src import analyzer as an
from src import reporter as rep


@pytest.fixture
def clean_thresholds(monkeypatch):
    for sym in ("VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ"):
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)


@pytest.fixture
def tmp_context(monkeypatch, tmp_path, clean_thresholds):
    """context/history/alerts 全部重定向到 tmp；alerts 断言幂等性。"""
    monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
    monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
    monkeypatch.setattr(al, "ALERTS_DIR", tmp_path / "alerts")
    monkeypatch.setattr(al, "ALERTS_LOG", tmp_path / "alerts.log")
    return tmp_path


class TestBuildSearchKeywords:
    def test_no_breach_single_keyword(self):
        assert an.build_search_keywords("2026-08-29", []) == ["market summary 2026-08-29"]

    def test_positive_change_uses_surge(self):
        kw = an.build_search_keywords("2026-08-29", [{"symbol": "VIX", "change": 22.0}])
        assert kw[0] == "VIX surge 2026-08-29"

    def test_negative_change_uses_drop(self):
        kw = an.build_search_keywords("2026-08-29", [{"symbol": "VIX", "change": -18.5}])
        assert kw[0] == "VIX drop 2026-08-29"

    def test_zero_change_uses_surge(self):
        # 方向边界：变化率 >=0 归入 surge（设计 C）
        kw = an.build_search_keywords("2026-08-29", [{"symbol": "VIX", "change": 0.0}])
        assert kw[0] == "VIX surge 2026-08-29"

    def test_one_breach_three_keywords(self):
        kw = an.build_search_keywords("2026-08-29", [{"symbol": "VIX", "change": 22.0}])
        assert kw == [
            "VIX surge 2026-08-29",
            "market volatility 2026-08-29",
            "economic data 2026-08-29",
        ]

    def test_two_breaches_four_keywords(self):
        breaches = [
            {"symbol": "VIX", "change": 22.0},
            {"symbol": "VXN", "change": -21.0},
        ]
        kw = an.build_search_keywords("2026-08-29", breaches)
        assert kw == [
            "VIX surge 2026-08-29",
            "VXN drop 2026-08-29",
            "market volatility 2026-08-29",
            "economic data 2026-08-29",
        ]

    def test_three_breaches_five_keywords(self):
        breaches = [
            {"symbol": "VIX", "change": 22.0},
            {"symbol": "VXN", "change": 21.0},
            {"symbol": "MOVE", "change": -16.0},
        ]
        kw = an.build_search_keywords("2026-08-29", breaches)
        assert len(kw) == 5  # 3 异动词 + 2 定向词 = 5（计数上限）


class TestBreachItem:
    def test_field_mapping(self, clean_thresholds):
        alert = an.check_breach("VIX", 24.4, 20.0)  # +22% WARN
        assert alert is not None
        item = rep._breach_item(alert)
        assert item == {
            "name": "VIX",
            "current": 24.4,
            "previous": 20.0,
            "change_pct": 22.0,
            "threshold": 20.0,
            "level": "WARN",
        }

    def test_change_pct_rounded_2(self, clean_thresholds):
        # (24.456-20)/20*100 = 22.2800... → 保留 2 位
        alert = an.check_breach("VIX", 24.456, 20.0)
        assert alert is not None
        assert rep._breach_item(alert)["change_pct"] == 22.28


class TestGenerateContext:
    def _inputs(self, values, last_values):
        return {
            "values": values,
            "changes": an.compute_changes(values, last_values),
            "statuses": an.build_statuses(values, {}),
            "last_values": last_values,
        }

    def _seed_history(self, date):
        an.append_history({"date": "2026-08-28", "vix": 20.0, "vxn": 18.0, "move": 75.0})
        an.append_history({"date": date, "vix": 21.0, "vxn": 19.0, "move": 78.0})

    def test_non_breach_day(self, tmp_context):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        self._seed_history("2026-08-29")
        path = rep.generate_context("2026-08-29", **self._inputs(values, last))
        assert path == tmp_context / "context" / "2026-08-29.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["date"] == "2026-08-29"
        assert data["indices"]["VIX"] == {"value": 21.0, "change_pct": 5.0, "status": "警惕"}
        assert data["indices"]["MOVE"]["status"] == "平静"
        assert data["history_30d"]["dates"] == ["2026-08-28", "2026-08-29"]  # append 后调用，含当日
        assert data["history_30d"]["vix"] == [20.0, 21.0]
        assert len(data["history_30d"]["dates"]) == len(data["history_30d"]["vix"]) == \
            len(data["history_30d"]["vxn"]) == len(data["history_30d"]["move"]) == \
            len(data["history_30d"]["gspc"]) == len(data["history_30d"]["ixic"]) == \
            len(data["history_30d"]["sh"]) == len(data["history_30d"]["sz"])
        assert data["breach"] == {"triggered": False, "indices": []}
        assert data["search_keywords"] == ["market summary 2026-08-29"]

        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0,
                  "VIX": 24.4, "VXN": 22.0, "MOVE": 80.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        path = rep.generate_context("2026-08-29", **self._inputs(values, last))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["breach"]["triggered"] is True
        assert data["breach"]["indices"][0] == {
            "name": "VIX",
            "current": 24.4,
            "previous": 20.0,
            "change_pct": 22.0,
            "threshold": 20.0,
            "level": "WARN",
        }
        assert [i["name"] for i in data["breach"]["indices"]] == ["VIX", "VXN"]  # SYMBOLS 顺序
        kw = data["search_keywords"]
        assert kw[0] == "VIX surge 2026-08-29"
        assert kw[1] == "VXN surge 2026-08-29"
        assert 3 <= len(kw) <= 5
        assert kw[-2:] == ["market volatility 2026-08-29", "economic data 2026-08-29"]

    def test_all_sources_failed(self, tmp_context):
        values = {"GSPC": None, "IXIC": None, "SH": None, "SZ": None,
                  "VIX": None, "VXN": None, "MOVE": None}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        path = rep.generate_context("2026-08-29", **self._inputs(values, last))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["indices"]["VIX"]["value"] is None
        assert data["indices"]["VIX"]["change_pct"] is None
        assert data["indices"]["VIX"]["status"] == "获取失败"
        assert data["breach"] == {"triggered": False, "indices": []}
        assert data["search_keywords"] == ["market summary 2026-08-29"]

    def test_idempotent_no_alert_side_effects(self, tmp_context):
        # 连续两次运行：context 覆盖、JSON 有效；collect_breaches 纯计算不产告警文件/alerts.log
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0,
                  "VIX": 24.4, "VXN": 22.0, "MOVE": 80.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        rep.generate_context("2026-08-29", **self._inputs(values, last))
        rep.generate_context("2026-08-29", **self._inputs(values, last))
        data = json.loads((tmp_context / "context" / "2026-08-29.json").read_text(encoding="utf-8"))
        assert data["breach"]["triggered"] is True
        assert not (tmp_context / "alerts").exists()          # 未创建告警目录
        assert not (tmp_context / "alerts.log").exists()       # alerts.log 未被触碰
        assert not (tmp_context / "context" / "2026-08-29.json.tmp").exists()  # 原子写已清理

    def test_history_window_30(self, tmp_context):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        from datetime import date, timedelta

        start = date(2026, 7, 1)
        for i in range(35):
            d = (start + timedelta(days=i)).isoformat()
            an.append_history({"date": d, "vix": 20.0, "vxn": 18.0, "move": 75.0})
        data = json.loads(
            rep.generate_context("2026-08-29", **self._inputs(values, last))
            .read_text(encoding="utf-8")
        )
        assert len(data["history_30d"]["dates"]) == 30  # 窗口截断 35 → 30
        assert data["history_30d"]["dates"][0] == (start + timedelta(days=5)).isoformat()
        for key in ("vix", "vxn", "move", "gspc", "ixic", "sh", "sz"):
            assert len(data["history_30d"][key]) == 30
