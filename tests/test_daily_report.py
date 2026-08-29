"""daily_report.py 纯逻辑单元测试（不联网）。"""

import re

import pytest

import daily_report as dr


def sample_data() -> dict:
    """一份完整的渲染输入（三指数均取数成功）。"""
    return {
        "date": "2026-08-28",
        "values": {"VIX": 15.23, "VXN": 22.11, "MOVE": 95.40},
        "changes": {"VIX": 1.23, "VXN": -0.50, "MOVE": 2.00},
        "statuses": {
            "VIX": ("平静", "市场情绪平稳，波动率处于低位，风险偏好较高。"),
            "VXN": ("警惕", "市场情绪偏谨慎，波动率上升，注意短期回调风险。"),
            "MOVE": ("平静", "债市波动平稳，利率预期稳定。"),
        },
        "summary": "VIX 收于 15.23，市场状态：平静。",
        "has_history": True,
    }


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
        assert dr.classify_vix(value)[0] == label

    def test_vxn_reuses_vix(self):
        assert dr.classify_vix(25.0)[0] == dr.classify_vix(25.0)[0] == "警惕"


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
        assert dr.classify_move(value)[0] == label


class TestComputeChanges:
    def test_normal(self):
        assert dr.compute_changes({"VIX": 22.0}, {"VIX": 20.0})["VIX"] == pytest.approx(10.0)

    def test_negative(self):
        assert dr.compute_changes({"VIX": 19.0}, {"VIX": 20.0})["VIX"] == pytest.approx(-5.0)

    def test_first_run_returns_none(self):
        assert dr.compute_changes({"VIX": 22.0}, {})["VIX"] is None

    def test_symbol_missing_in_last_returns_none(self):
        assert dr.compute_changes({"VIX": 22.0, "MOVE": 95.0}, {"VIX": 20.0})["MOVE"] is None

    def test_div_zero_protected(self):
        assert dr.compute_changes({"VIX": 22.0}, {"VIX": 0.0})["VIX"] is None

    def test_failed_value_returns_none(self):
        assert dr.compute_changes({"VIX": None}, {"VIX": 20.0})["VIX"] is None


class TestBuildStatuses:
    def test_ok(self):
        statuses = dr.build_statuses(
            {"VIX": 15.0, "VXN": 25.0, "MOVE": 95.0}, {}
        )
        assert statuses["VIX"][0] == "平静"
        assert statuses["VXN"][0] == "警惕"
        assert statuses["MOVE"][0] == "平静"

    def test_fetch_failed(self):
        statuses = dr.build_statuses(
            {"VIX": 15.0, "VXN": None, "MOVE": 95.0},
            {"VXN": "获取失败（已重试）"},
        )
        assert statuses["VXN"][0] == "获取失败"
        assert statuses["MOVE"][0] == "平静"


class TestRenderReport:
    def test_template_complete(self):
        report = dr.render_report(**sample_data())
        assert "2026-08-28" in report
        for label in ("VIX（恐慌指数）", "VXN（科技波动）", "MOVE（债市波动）"):
            assert label in report
        for status in ("平静", "警惕"):
            assert status in report
        assert "| VIX（恐慌指数） |" in report  # 表格三行
        assert "首次运行，暂无历史对比" not in report

    def test_no_unreplaced_placeholder(self):
        report = dr.render_report(**sample_data())
        assert not re.search(r"\{[a-z_]+\}", report)

    def test_first_run_change_text(self):
        data = sample_data()
        data["has_history"] = False
        data["changes"] = {"VIX": None, "VXN": None, "MOVE": None}
        report = dr.render_report(**data)
        assert report.count("首次运行，暂无历史对比") == 3

    def test_failed_fetch_annotated(self):
        data = sample_data()
        data["values"]["VXN"] = None
        data["changes"]["VXN"] = None
        data["statuses"]["VXN"] = ("获取失败", "数据获取失败，无法判断状态。")
        report = dr.render_report(**data)
        assert "获取失败" in report
        assert "| VXN（科技波动） | 获取失败 | — | 获取失败 |" in report

    def test_vix_failed_state_section(self):
        data = sample_data()
        data["values"]["VIX"] = None
        data["changes"]["VIX"] = None
        data["statuses"]["VIX"] = ("获取失败", "数据获取失败，无法判断状态。")
        report = dr.render_report(**data)
        assert "无法判断" in report


class TestBuildSummary:
    def test_complete(self):
        values = {"VIX": 15.23, "VXN": 22.11, "MOVE": 95.40}
        statuses = dr.build_statuses(values, {})
        summary = dr.build_summary(values, statuses, {})
        assert "VIX 收于 15.23" in summary
        assert "获取完整" in summary

    def test_partial_failure(self):
        values = {"VIX": 15.23, "VXN": None, "MOVE": 95.40}
        statuses = dr.build_statuses(values, {"VXN": "获取失败（已重试）"})
        summary = dr.build_summary(values, statuses, {"VXN": "获取失败（已重试）"})
        assert "VXN" in summary and "获取失败" in summary

    def test_all_failed(self):
        values = {"VIX": None, "VXN": None, "MOVE": None}
        errors = {
            "VIX": "获取失败（已重试）",
            "VXN": "获取失败（已重试）",
            "MOVE": "获取失败（已重试）",
        }
        statuses = dr.build_statuses(values, errors)
        summary = dr.build_summary(values, statuses, errors)
        assert "无法判断整体市场情绪" in summary
        assert "MOVE" in summary


class TestGetUsEasternDate:
    def test_format(self):
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", dr.get_us_eastern_date())


class TestFormatters:
    def test_fmt_value(self):
        assert dr.fmt_value(15.234) == "15.23"
        assert dr.fmt_value(None) == "获取失败"

    def test_fmt_change(self):
        assert dr.fmt_change(1.23, True, 10.0) == "+1.23%"
        assert dr.fmt_change(-0.5, True, 10.0) == "-0.50%"
        assert dr.fmt_change(0.0, True, 10.0) == "0.00%"
        assert dr.fmt_change(None, True, 10.0) == "—"
        assert dr.fmt_change(1.23, False, 10.0) == "首次运行，暂无历史对比"
        assert dr.fmt_change(1.23, True, None) == "—"
