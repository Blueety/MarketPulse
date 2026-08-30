"""九期：分市场趋势图（美股 2×1 / A 股 3×1）单元测试。

不联网，真实 matplotlib 渲染到 tmp_path。复用 test_reporter 的 sample_data。
"""

from datetime import date, timedelta

import pytest

from src import reporter as rep
from test_reporter import sample_data


def make_market_history(n: int, start: date, keys: list[str]) -> list[dict]:
    """构造含市场键的历史记录（不含当日）。keys 为小写键，如 ["gspc", "ixic"]。"""
    return [
        {
            **{"date": (start + timedelta(days=i)).isoformat()},
            **{k: 100.0 + i + idx for idx, k in enumerate(keys)},
        }
        for i in range(n)
    ]


class TestMarketTrendChart:
    def test_us_png_generated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        path = rep.render_market_trend_chart(
            make_market_history(30, date(2026, 7, 1), ["gspc", "ixic"]), "2026-09-01", "us"
        )
        assert path is not None
        assert path == tmp_path / "2026-09-01-us-trend.png"
        assert path.exists()

    def test_cn_png_generated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        path = rep.render_market_trend_chart(
            make_market_history(30, date(2026, 7, 1), ["sh", "sz", "cyb"]), "2026-09-01", "cn"
        )
        assert path is not None
        assert path == tmp_path / "2026-09-01-cn-trend.png"
        assert path.exists()

    def test_insufficient_rows_skips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        assert rep.render_market_trend_chart(
            make_market_history(1, date(2026, 7, 1), ["gspc", "ixic"]), "2026-09-01", "us"
        ) is None

    def test_empty_history_skips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        assert rep.render_market_trend_chart([], "2026-09-01", "us") is None

    def test_only_today_and_yesterday_excluded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        history = [
            {"date": "2026-09-01", "gspc": 100.0, "ixic": 200.0},
            {"date": "2026-08-31", "gspc": 99.0, "ixic": 199.0},
        ]
        # 排除当日记录后仅剩 1 条 → 跳过（设计 C）
        assert rep.render_market_trend_chart(history, "2026-09-01", "us") is None

    def test_partial_null_series_still_generates(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        history = make_market_history(15, date(2026, 7, 1), ["gspc", "ixic"])
        for r in history:
            r["gspc"] = None  # gspc 全 null，ixic 正常 → 图仍生成（gspc 面板占位）
        path = rep.render_market_trend_chart(history, "2026-09-01", "us")
        assert path is not None
        assert path.exists()

    def test_single_finite_point_placeholder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        history = make_market_history(15, date(2026, 7, 1), ["gspc", "ixic"])
        for i, r in enumerate(history):
            r["gspc"] = 100.0 if i == 3 else None  # 仅 1 个有限点 → 该面板占位
        path = rep.render_market_trend_chart(history, "2026-09-01", "us")
        assert path is not None
        assert path.exists()

    def test_all_null_series_placeholder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        history = make_market_history(15, date(2026, 7, 1), ["gspc", "ixic"])
        for r in history:
            r["gspc"] = None
            r["ixic"] = None  # 两序列全 null → 全占位图，不抛
        path = rep.render_market_trend_chart(history, "2026-09-01", "us")
        assert path is not None
        assert path.exists()

    def test_invalid_market_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        assert rep.render_market_trend_chart(
            make_market_history(30, date(2026, 7, 1), ["gspc", "ixic"]), "2026-09-01", "eu"
        ) is None


class TestRenderReportMarketCharts:
    def test_both_charts_render_sections(self):
        data = sample_data()
        data["us_trend_chart"] = "./charts/2026-08-28-us-trend.png"
        data["cn_trend_chart"] = "./charts/2026-08-28-cn-trend.png"
        report = rep.render_report(**data)
        assert "## 📈 美股大盘近30日趋势" in report
        assert "![美股大盘近30日趋势](./charts/2026-08-28-us-trend.png)" in report
        assert "## 📈 A股大盘近30日趋势" in report
        assert "![A股大盘近30日趋势](./charts/2026-08-28-cn-trend.png)" in report

    def test_no_new_sections_without_charts(self):
        report = rep.render_report(**sample_data())
        assert "美股大盘近30日趋势" not in report
        assert "A股大盘近30日趋势" not in report

    def test_all_three_charts_coexist(self):
        data = sample_data()
        data["trend_chart"] = "./charts/2026-08-28-trend.png"
        data["us_trend_chart"] = "./charts/2026-08-28-us-trend.png"
        data["cn_trend_chart"] = "./charts/2026-08-28-cn-trend.png"
        report = rep.render_report(**data)
        assert "## 📉 近30日趋势" in report
        assert "## 📈 美股大盘近30日趋势" in report
        assert "## 📈 A股大盘近30日趋势" in report

    def test_section_order(self):
        data = sample_data()
        data["us_trend_chart"] = "./charts/2026-08-28-us-trend.png"
        data["cn_trend_chart"] = "./charts/2026-08-28-cn-trend.png"
        report = rep.render_report(**data)
        us_market_pos = report.index("## 🌏 美股大盘")
        us_pos = report.index("## 📈 美股大盘近30日趋势")
        a_share_pos = report.index("## 🇨🇳 A 股大盘")
        cn_pos = report.index("## 📈 A股大盘近30日趋势")
        hot_pos = report.index("## 🔥 A 股热点板块 Top 5")
        # us 图在美股大盘之后、A 股大盘之前；cn 图在 A 股大盘之后、热点板块之前
        assert us_market_pos < us_pos < a_share_pos < cn_pos < hot_pos
