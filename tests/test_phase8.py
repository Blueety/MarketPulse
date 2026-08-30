"""八期 A 股板块热度专项测试（不联网，monkeypatch akshare / 编排函数）。

覆盖：fetch_sector_heat 取数（成功/异常/缺列/超时限）、render_report 板块表（正常/空/负值）、
generate_context 扩展 sector_heat 键 + search_keywords 注入板块词（不设阈值）、build_search_keywords
板块注入方向语义、daily_report 入口透传板块数据。既有 170 条测试零改动（默认参数）。
"""

import json

import pytest

from src import analyzer as an
from src import fetcher as ft
from src import reporter as rep
import daily_report as dr


def _spot_df(rows):
    import pandas as pd

    return pd.DataFrame(rows)


# 概念板块实测列名：板块 / 涨跌幅 / 总成交额 / 股票名称（另含其它列不影响）
ROWS = [
    {"板块": "生物育种", "涨跌幅": 5.20, "总成交额": 7_220_000_000, "股票名称": "敦煌种业", "其它": 1},
    {"板块": "水产品", "涨跌幅": 3.79, "总成交额": 1_370_489_337, "股票名称": "中水渔业", "其它": 2},
    {"板块": "生态农业", "涨跌幅": 2.68, "总成交额": 9_730_000_000, "股票名称": "敦煌种业", "其它": 3},
    {"板块": "中间板块", "涨跌幅": 1.00, "总成交额": 200_000_000, "股票名称": "Z公司", "其它": 4},
    {"板块": "领跌板块", "涨跌幅": -2.50, "总成交额": 100_000_000, "股票名称": "X公司", "其它": 5},
    {"板块": "暴跌板块", "涨跌幅": -5.00, "总成交额": 500_000_000, "股票名称": "Y公司", "其它": 6},
]


class TestFetchSectorHeat:
    def test_top5_sorted_desc_and_format(self, monkeypatch):
        import akshare as ak_mod

        monkeypatch.setattr(ak_mod, "stock_sector_spot", lambda indicator=None: _spot_df(ROWS))
        res = ft.fetch_sector_heat()
        assert len(res) == 5
        # 按涨跌幅降序：5.20, 3.79, 2.68, 1.00, -2.50
        assert [r["change"] for r in res] == [5.2, 3.79, 2.68, 1.0, -2.5]
        assert res[0] == {"name": "生物育种", "change": 5.2, "turnover": "72.2亿", "top_stock": "敦煌种业"}
        assert res[1] == {"name": "水产品", "change": 3.79, "turnover": "13.7亿", "top_stock": "中水渔业"}
        # 负值板块保留负号
        assert res[4] == {"name": "领跌板块", "change": -2.5, "turnover": "1.0亿", "top_stock": "X公司"}

    def test_top_n_param(self, monkeypatch):
        import akshare as ak_mod

        monkeypatch.setattr(ak_mod, "stock_sector_spot", lambda indicator=None: _spot_df(ROWS))
        res = ft.fetch_sector_heat(top_n=3)
        assert len(res) == 3
        assert [r["name"] for r in res] == ["生物育种", "水产品", "生态农业"]


class TestFetchSectorHeatFailure:
    def test_exception_returns_empty(self, monkeypatch):
        import akshare as ak_mod

        def boom(indicator=None):
            raise ValueError("boom")

        monkeypatch.setattr(ak_mod, "stock_sector_spot", boom)
        assert ft.fetch_sector_heat() == []

    def test_missing_required_column_returns_empty(self, monkeypatch):
        import akshare as ak_mod

        bad = [{"板块": "X", "涨跌幅": 1.0, "股票名称": "Y"}]  # 缺 总成交额
        monkeypatch.setattr(ak_mod, "stock_sector_spot", lambda indicator=None: _spot_df(bad))
        assert ft.fetch_sector_heat() == []

    def test_timeout_returns_empty(self, monkeypatch):
        import akshare as ak_mod
        import time

        def slow(indicator=None):
            time.sleep(0.5)
            return _spot_df(ROWS)

        monkeypatch.setattr(ak_mod, "stock_sector_spot", slow)
        monkeypatch.setattr(ft, "SECTOR_TIMEOUT", 0.05)
        assert ft.fetch_sector_heat() == []


def _report_inputs(sector_heat=None):
    syms = ["GSPC", "IXIC", "SH", "SZ", "CYB", "VIX", "VXN", "MOVE"]
    values = {s: 100.0 for s in syms}
    values["VIX"] = 15.0
    changes = {s: 0.5 for s in syms}
    statuses = {s: ("平静", "desc") for s in syms}
    return dict(
        date="2026-08-29",
        values=values,
        changes=changes,
        statuses=statuses,
        summary="x",
        has_history=True,
        sector_heat=sector_heat,
    )


class TestRenderReportSectorTable:
    SECTORS = [
        {"name": "水产品", "change": 3.79, "turnover": "13.7亿", "top_stock": "中水渔业"},
        {"name": "领跌", "change": -2.5, "turnover": "1.0亿", "top_stock": "X公司"},
        {"name": "生物育种", "change": 5.2, "turnover": "72.2亿", "top_stock": "敦煌种业"},
    ]

    def test_table_rendered_with_signs(self):
        report = rep.render_report(**_report_inputs(sector_heat=self.SECTORS))
        assert "## 🔥 A 股热点板块 Top 5" in report
        assert "| 水产品 | +3.79% | 13.7亿 | 中水渔业 |" in report
        assert "| 领跌 | -2.50% | 1.0亿 | X公司 |" in report
        assert "| 生物育种 | +5.20% | 72.2亿 | 敦煌种业 |" in report
        # 既有章节不破坏
        assert "## 🇨🇳 A 股大盘" in report
        assert "## 📈 波动率指数" in report

    def test_empty_list_shows_placeholder(self):
        report = rep.render_report(**_report_inputs(sector_heat=[]))
        assert "| 数据暂缺 | — | — | — |" in report

    def test_none_default_shows_placeholder(self):
        report = rep.render_report(**_report_inputs())
        assert "| 数据暂缺 | — | — | — |" in report


class TestGenerateContextSector:
    def _patch(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
        monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
        from src import alerter as al

        monkeypatch.setattr(al, "ALERTS_DIR", tmp_path / "alerts")
        monkeypatch.setattr(al, "ALERTS_LOG", tmp_path / "alerts.log")

    def _inputs(self, values, last_values):
        return dict(
            values=values,
            changes=an.compute_changes(values, last_values),
            statuses=an.build_statuses(values, {}),
            last_values=last_values,
        )

    def test_sector_heat_key_and_keywords(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        sector_heat = [{"name": "创新药", "change": 5.2, "turnover": "10.0亿", "top_stock": "A"}]
        rep.generate_context("2026-08-29", **self._inputs(values, last), sector_heat=sector_heat)
        data = json.loads((tmp_path / "context" / "2026-08-29.json").read_text(encoding="utf-8"))
        assert data["sector_heat"] == sector_heat
        assert "创新药 surge 2026-08-29" in data["search_keywords"]

    def test_none_falls_back(self, monkeypatch, tmp_path):
        self._patch(monkeypatch, tmp_path)
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0}
        rep.generate_context("2026-08-29", **self._inputs(values, last))
        data = json.loads((tmp_path / "context" / "2026-08-29.json").read_text(encoding="utf-8"))
        assert data["sector_heat"] == []
        assert data["search_keywords"] == ["market summary 2026-08-29"]


class TestBuildSearchKeywordsSector:
    def test_sectors_injected_no_threshold(self):
        # 八期：不设阈值，3.79% 也注入（与旧版阈值版行为不同）
        kw = an.build_search_keywords("2026-08-29", [], sector_heat=[{"name": "水产品", "change": 3.79}])
        assert kw == ["水产品 surge 2026-08-29"]

    def test_negative_change_drop(self):
        kw = an.build_search_keywords("2026-08-29", [], sector_heat=[{"name": "领跌", "change": -2.5}])
        assert kw == ["领跌 drop 2026-08-29"]

    def test_five_sectors_no_directional_words(self):
        sh = [{"name": f"s{i}", "change": float(i)} for i in range(5)]
        kw = an.build_search_keywords("2026-08-29", [], sector_heat=sh)
        assert len(kw) == 5
        assert "market volatility" not in " ".join(kw)

    def test_breach_priority(self):
        kw = an.build_search_keywords(
            "2026-08-29",
            [{"symbol": "VIX", "change": 22.0}],
            sector_heat=[{"name": "水产品", "change": 3.79}],
        )
        assert kw[0] == "VIX surge 2026-08-29"
        assert "水产品 surge 2026-08-29" in kw

    def test_none_fallback(self):
        assert an.build_search_keywords("2026-08-29", []) == ["market summary 2026-08-29"]


class TestDailyReportWiring:
    def test_sector_heat_passed_through(self, monkeypatch, tmp_path):
        calls = {}
        fixed = [{"name": "水产品", "change": 3.79, "turnover": "13.7亿", "top_stock": "中水渔业"}]

        def fake_fetch_all(market=None):
            return ({s: 100.0 for s in ["GSPC", "IXIC", "SH", "SZ", "CYB", "VIX", "VXN", "MOVE"]}, {})

        def fake_fetch_sector_heat():
            calls["sector"] = fixed
            return fixed

        def fake_render(*a, **k):
            calls["render_sector"] = k.get("sector_heat")
            return "# report"

        def fake_gen(*a, **k):
            calls["gen_sector"] = k.get("sector_heat")
            return tmp_path / "context" / "2026-08-29.json"

        def fake_trend(*a, **k):
            return None

        monkeypatch.setattr(dr, "fetch_all", fake_fetch_all)
        monkeypatch.setattr(dr, "fetch_sector_heat", fake_fetch_sector_heat)
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
        assert calls["render_sector"] == fixed
        assert calls["gen_sector"] == fixed
