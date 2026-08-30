"""src/reporter.py 渲染与趋势图单元测试（趋势图用真实 matplotlib 渲染到 tmp）。"""

import re
from datetime import date, timedelta

import pytest

from src import reporter as rep
from src.analyzer import build_statuses


def sample_data() -> dict:
    """一份完整的渲染输入（七指数均取数成功：GSPC/IXIC 美股 + SH/SZ A 股 + VIX/VXN/MOVE 波动率）。"""
    return {
        "date": "2026-08-28",
        "values": {
            "GSPC": 4500.0, "IXIC": 17500.0, "SH": 3100.0, "SZ": 10000.0,
            "VIX": 15.23, "VXN": 22.11, "MOVE": 95.40,
        },
        "changes": {
            "GSPC": 0.50, "IXIC": -0.30, "SH": 0.60, "SZ": -0.40,
            "VIX": 1.23, "VXN": -0.50, "MOVE": 2.00,
        },
        "statuses": {
            "GSPC": ("连涨1日", "大盘连续上涨1日。"),
            "IXIC": ("连跌1日", "大盘连续下跌1日。"),
            "SH": ("连涨1日", "大盘连续上涨1日。"),
            "SZ": ("连跌1日", "大盘连续下跌1日。"),
            "VIX": ("平静", "市场情绪平稳，波动率处于低位，风险偏好较高。"),
            "VXN": ("警惕", "市场情绪偏谨慎，波动率上升，注意短期回调风险。"),
            "MOVE": ("平静", "债市波动平稳，利率预期稳定。"),
        },
        "summary": "VIX 收于 15.23，市场状态：平静。",
        "has_history": True,
    }


class TestRenderReport:
    def test_template_complete(self):
        report = rep.render_report(**sample_data())
        assert "2026-08-28" in report
        for label in ("VIX（恐慌指数）", "VXN（科技波动）", "MOVE（债市波动）"):
            assert label in report
        for status in ("平静", "警惕"):
            assert status in report
        assert "| VIX（恐慌指数） |" in report  # 表格三行
        assert "首次运行，暂无历史对比" not in report

    def test_no_unreplaced_placeholder(self):
        report = rep.render_report(**sample_data())
        data = sample_data()
        data["has_history"] = False
        data["changes"] = {"GSPC": None, "IXIC": None, "SH": None, "SZ": None,
                            "VIX": None, "VXN": None, "MOVE": None}
        report = rep.render_report(**data)
        assert report.count("首次运行，暂无历史对比") == 7

    def test_failed_fetch_annotated(self):
        data = sample_data()
        data["values"]["VXN"] = None
        data["changes"]["VXN"] = None
        data["statuses"]["VXN"] = ("获取失败", "数据获取失败，无法判断状态。")
        data["values"]["SH"] = None
        data["changes"]["SH"] = None
        data["statuses"]["SH"] = ("休市", "A 股休市或数据缺失。")
        report = rep.render_report(**data)
        assert "获取失败" in report
        assert "| VXN（科技波动） | 获取失败 | — | 获取失败 |" in report
        assert "| 上证指数 | 休市 | — | 休市 |" in report


    def test_vix_failed_state_section(self):
        data = sample_data()
        data["values"]["VIX"] = None
        data["changes"]["VIX"] = None
        data["statuses"]["VIX"] = ("获取失败", "数据获取失败，无法判断状态。")
        report = rep.render_report(**data)
        assert "无法判断" in report

    def test_trend_section_with_chart(self):
        data = sample_data()
        data["trend_chart"] = "./charts/2026-08-28-trend.png"
        report = rep.render_report(**data)
        assert "## 📉 近30日趋势" in report
        assert "![VIX/VXN/MOVE 近30日趋势](./charts/2026-08-28-trend.png)" in report

    def test_no_trend_section_without_chart(self):
        report = rep.render_report(**sample_data())
        assert "近30日趋势" not in report


def make_history(n: int, start: date) -> list[dict]:
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "vix": 20.0 + i,
            "vxn": 25.0 + i,
            "move": 70.0 - i,
        }
        for i in range(n)
    ]


class TestTrendChart:
    def test_png_generated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        path = rep.render_trend_chart(make_history(30, date(2026, 7, 1)), "2026-09-01")
        assert path is not None
        assert path == tmp_path / "2026-09-01-trend.png"
        assert path.exists()

    def test_insufficient_history_skips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        assert rep.render_trend_chart(make_history(1, date(2026, 7, 1)), "2026-09-01") is None

    def test_empty_history_skips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        assert rep.render_trend_chart([], "2026-09-01") is None

    def test_today_row_excluded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        history = [
            {"date": "2026-09-01", "vix": 20.0, "vxn": 25.0, "move": 70.0},
            {"date": "2026-08-31", "vix": 19.5, "vxn": 24.5, "move": 71.0},
        ]
        # 排除当日记录后仅剩 1 条 → 跳过绘图
        assert rep.render_trend_chart(history, "2026-09-01") is None

    def test_null_value_breaks_line_but_renders(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "CHARTS_DIR", tmp_path)
        history = make_history(15, date(2026, 7, 1))
        history[3]["vix"] = None  # 单源缺失 → 断点绘制，不中断
        path = rep.render_trend_chart(history, "2026-09-01")
        assert path is not None
        assert path.exists()
class TestSnapshot:
    def test_render_complete(self):
        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3100.0, "SZ": 10000.0,
                  "VIX": 15.23, "VXN": 22.11, "MOVE": 95.40}
        statuses = build_statuses(values, {})
        content = rep.render_snapshot("2026-08-28", values, statuses)
        assert "午盘快照" in content
        assert "2026-08-28" in content
        assert "盘中快照（美东 12:30）" in content
        for label in ("标普500", "纳斯达克", "上证指数", "深证成指",
                      "VIX（恐慌指数）", "VXN（科技波动）", "MOVE（债市波动）"):
            assert label in content
        assert not re.search(r"\{[a-z_]+\}", content)

    def test_render_failed_fetch(self):
        values = {"GSPC": None, "IXIC": None, "SH": None, "SZ": None,
                  "VIX": None, "VXN": 22.11, "MOVE": None}
        statuses = build_statuses(
            values,
            {"VIX": "获取失败（已重试）", "MOVE": "获取失败（已重试）"},
        )
        content = rep.render_snapshot("2026-08-28", values, statuses)
        assert content.count("获取失败") >= 3
        assert "休市" in content
        assert "| 上证指数 | 休市 | 休市 |" in content
        assert "无法判断" in content

    def test_save_snapshot_writes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "SNAPSHOTS_DIR", tmp_path)
        path = rep.save_snapshot("2026-08-28", "# 快照")
        assert path == tmp_path / "2026-08-28-noon.md"
        assert path.exists()
