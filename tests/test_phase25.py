"""二十五期单元测试：美股去重（GSPC/IXIC）+ 浅色主题（纯逻辑/接线）。

覆盖：
- _is_us_duplicate_day 纯逻辑（同值/异值/空历史/混合日）
- daily_report.main() 接线（重复日跳过写历史 / 变动日追加），验证 history 行数
浅色主题为纯前端（CSS + HTML + localStorage），无后端逻辑，浏览器实测覆盖。
"""

import json

from src import analyzer as an
from src import reporter as rep
import daily_report as dr

# 与 daily_report.main() 取数一致的 10 标的基准值（GSPC/IXIC 为判定符号集）
_VALUES = {
    "GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
    "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0, "GLD": 200.0, "BTC": 60000.0,
}


# --------------------------------------------------------------------------- #
# 纯逻辑：_is_us_duplicate_day
# --------------------------------------------------------------------------- #
class TestIsUsDuplicateDay:
    def test_same_us_duplicate(self):
        history = [{"date": "2026-08-31", "gspc": 4500.0, "ixic": 17500.0, "btc": 60000.0}]
        record = {"date": "2026-09-01", "gspc": 4500.0, "ixic": 17500.0, "btc": 60000.0}
        assert dr._is_us_duplicate_day(history, record) is True

    def test_gspc_diff_not_duplicate(self):
        history = [{"date": "2026-08-31", "gspc": 4500.0, "ixic": 17500.0}]
        record = {"date": "2026-09-01", "gspc": 4600.0, "ixic": 17500.0}
        assert dr._is_us_duplicate_day(history, record) is False

    def test_empty_history_not_duplicate(self):
        assert dr._is_us_duplicate_day([], {"gspc": 4500.0, "ixic": 17500.0}) is False

    def test_only_btc_diff_mixed_day_duplicate(self):
        # D2：混合日（美股未动、另类/A 股变动）整条跳过
        history = [{"date": "2026-08-31", "gspc": 4500.0, "ixic": 17500.0, "btc": 59000.0}]
        record = {"date": "2026-09-01", "gspc": 4500.0, "ixic": 17500.0, "btc": 60000.0}
        assert dr._is_us_duplicate_day(history, record) is True


# --------------------------------------------------------------------------- #
# 接线：daily_report.main() 去重门
# --------------------------------------------------------------------------- #
class TestDailyReportDedupWiring:
    def _monkeypatch_net(self, monkeypatch, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps({}), encoding="utf-8")
        monkeypatch.setenv("CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
        monkeypatch.setattr(an, "LAST_VALUES_FILE", tmp_path / "last_values.json")
        monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
        monkeypatch.setattr(dr, "get_us_eastern_date", lambda: "2026-09-01")
        monkeypatch.setattr(dr, "fetch_all", lambda *a, **k: (dict(_VALUES), {}))
        monkeypatch.setattr(dr, "fetch_sector_heat", lambda *a, **k: ([], []))
        monkeypatch.setattr(dr, "fetch_us_sector_heat", lambda *a, **k: ([], []))
        monkeypatch.setattr(dr, "fetch_watchlist", lambda stocks: ({}, {}, {}))
        monkeypatch.setattr(dr, "compute_portfolio_correlation",
                            lambda *a, **k: {"stocks": [], "portfolio_risk": {"high": False, "avg_r": None}})
        monkeypatch.setattr(dr, "search_news", lambda q: [])
        monkeypatch.setattr(dr, "render_report", lambda *a, **k: "")
        monkeypatch.setattr(dr, "save_report", lambda d, c: tmp_path / f"{d}.md")
        monkeypatch.setattr(dr, "render_trend_chart", lambda *a, **k: None)
        monkeypatch.setattr(dr, "render_market_trend_chart", lambda *a, **k: None)
        monkeypatch.setattr(dr, "run_alert_checks", lambda *a, **k: None)
        monkeypatch.setattr(dr, "render_report_image", lambda *a, **k: None)
        monkeypatch.setattr(dr, "load_opening_refs", lambda d: [])

    def _seed_history(self, tmp_path, record):
        p = tmp_path / "history.json"
        p.write_text(json.dumps([record]), encoding="utf-8")

    def test_dup_day_skips_append(self, tmp_path, monkeypatch):
        self._monkeypatch_net(monkeypatch, tmp_path)
        seed = {"date": "2026-08-31", **{k.lower(): v for k, v in _VALUES.items()}}
        seed["btc"] = 59000.0  # 混合日：美股同值、btc 异值
        self._seed_history(tmp_path, seed)

        rc = dr.main()
        assert rc == 0
        assert len(an.load_history()) == 1  # 重复日不新增

    def test_changed_us_appends(self, tmp_path, monkeypatch):
        self._monkeypatch_net(monkeypatch, tmp_path)
        seed = {"date": "2026-08-31", **{k.lower(): v for k, v in _VALUES.items()}}
        seed["gspc"] = 4400.0  # 美股变动
        self._seed_history(tmp_path, seed)

        rc = dr.main()
        assert rc == 0
        assert len(an.load_history()) == 2  # 变动日追加
