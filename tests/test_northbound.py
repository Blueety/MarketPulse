"""北向资金模块单元测试。

覆盖：fetch_northbound_flow 成功/失败/超时/空数据、
fmt_northbound / fmt_northbound_detail 格式化、
check_northbound_alert 触发/未触发/去重/None 数据。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import src.northbound as northbound
from src.analyzer import fmt_northbound, fmt_northbound_detail
from src.alerter import check_northbound_alert


# ---- fetch_northbound_flow 测试 ----

class TestFetchNorthboundFlow:
    """测试 fetch_northbound_flow 降级链。"""

    def test_fetch_success(self):
        """mock adata 返回有效数据，断言返回结构正确。"""
        df = pd.DataFrame({
            "trade_date": ["2026-09-01", "2026-08-31"],
            "net_hgt": [1820000000, 1500000000],
            "net_sgt": [1395000000, 1200000000],
            "net_tgt": [3215000000, 2700000000],
        })
        with patch.object(northbound, "_fetch_via_adata", return_value={
            "net_inflow": 32.15,
            "sh_net": 18.20,
            "sz_net": 13.95,
            "date": "2026-09-01",
        }):
            result = northbound.fetch_northbound_flow()
        assert result is not None
        assert result["net_inflow"] == 32.15
        assert result["sh_net"] == 18.20
        assert result["sz_net"] == 13.95
        assert result["date"] == "2026-09-01"

    def test_fetch_adata_returns_none(self):
        """adata 返回 None，断言 fetch_northbound_flow 返回 None。"""
        with patch.object(northbound, "_fetch_via_adata", return_value=None):
            result = northbound.fetch_northbound_flow()
        assert result is None

    def test_fetch_adata_error(self):
        """adata 抛异常，断言返回 None（不抛出）。"""
        with patch.object(northbound, "_fetch_via_adata", side_effect=RuntimeError("网络错误")):
            result = northbound.fetch_northbound_flow()
        assert result is None

    def test_fetch_adata_timeout(self):
        """adata 超时（_fetch_via_adata 返回 None），断言返回 None。"""
        with patch.object(northbound, "_fetch_via_adata", return_value=None):
            result = northbound.fetch_northbound_flow()
        assert result is None

    def test_fetch_negative_flow(self):
        """负值净流出，断言返回负数。"""
        with patch.object(northbound, "_fetch_via_adata", return_value={
            "net_inflow": -12.50,
            "sh_net": -8.30,
            "sz_net": -4.20,
            "date": "2026-09-01",
        }):
            result = northbound.fetch_northbound_flow()
        assert result is not None
        assert result["net_inflow"] == -12.50


class TestFetchViaAdata:
    """测试 _fetch_via_adata 内部逻辑。"""

    def test_empty_dataframe(self):
        """adata 返回空 DataFrame，断言返回 None。"""
        with patch("adata.sentiment") as mock_sentiment:
            mock_sentiment.north.north_flow.return_value = pd.DataFrame()
            result = northbound._fetch_via_adata()
        assert result is None

    def test_timeout(self):
        """adata 超时（join 返回但 result 仍 None），断言返回 None。"""
        with patch("adata.sentiment") as mock_sentiment:
            # north_flow 不返回任何东西（模拟超时）
            mock_sentiment.north.north_flow.side_effect = None
            mock_sentiment.north.north_flow.return_value = None
            result = northbound._fetch_via_adata()
        # None DataFrame → 返回 None
        assert result is None


# ---- fmt_northbound 测试 ----

class TestFmtNorthbound:
    """测试 fmt_northbound 格式化函数。"""

    def test_positive(self):
        """正值 → '净流入 X.XX 亿元'"""
        data = {"net_inflow": 32.15, "sh_net": 18.20, "sz_net": 13.95, "date": "2026-09-01"}
        assert fmt_northbound(data) == "净流入 32.15 亿元"

    def test_negative(self):
        """负值 → '净流出 X.XX 亿元'"""
        data = {"net_inflow": -12.50, "sh_net": -8.30, "sz_net": -4.20, "date": "2026-09-01"}
        assert fmt_northbound(data) == "净流出 12.50 亿元"

    def test_zero(self):
        """零值 → '净流入 0.00 亿元'"""
        data = {"net_inflow": 0.0, "sh_net": 0.0, "sz_net": 0.0, "date": "2026-09-01"}
        assert fmt_northbound(data) == "净流入 0.00 亿元"

    def test_none(self):
        """None → '数据暂缺'"""
        assert fmt_northbound(None) == "数据暂缺"


# ---- fmt_northbound_detail 测试 ----

class TestFmtNorthboundDetail:
    """测试 fmt_northbound_detail 格式化函数。"""

    def test_detail(self):
        """正常明细格式化。"""
        data = {"net_inflow": 32.15, "sh_net": 18.20, "sz_net": 13.95, "date": "2026-09-01"}
        assert fmt_northbound_detail(data) == "沪股通 +18.20 / 深股通 +13.95"

    def test_detail_negative(self):
        """负值明细格式化。"""
        data = {"net_inflow": -12.50, "sh_net": -8.30, "sz_net": -4.20, "date": "2026-09-01"}
        assert fmt_northbound_detail(data) == "沪股通 -8.30 / 深股通 -4.20"

    def test_detail_none(self):
        """None → '—'"""
        assert fmt_northbound_detail(None) == "—"


# ---- check_northbound_alert 测试 ----

class TestCheckNorthboundAlert:
    """测试 check_northbound_alert 告警逻辑。"""

    def test_triggered(self, tmp_path):
        """超过阈值 → 生成告警文件。"""
        alerts_dir = tmp_path / "alerts"
        alerts_log = tmp_path / "alerts.log"
        report_path = tmp_path / "reports" / "2026-09-01.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("test report", encoding="utf-8")

        data = {"net_inflow": 150.0, "sh_net": 80.0, "sz_net": 70.0, "date": "2026-09-01"}

        with patch("src.alerter.ALERTS_DIR", alerts_dir), \
             patch("src.alerter.ALERTS_LOG", alerts_log), \
             patch("src.alerter.load_config", return_value={"alert": {"northbound": 100.0}}):
            result = check_northbound_alert("2026-09-01", data, report_path)

        assert len(result) == 1
        assert result[0]["symbol"] == "NORTHBOUND"
        assert result[0]["level"] == "ALERT"
        assert result[0]["net_inflow"] == 150.0
        assert alerts_dir.exists()
        alert_file = alerts_dir / "2026-09-01-northbound.md"
        assert alert_file.exists()
        content = alert_file.read_text(encoding="utf-8")
        assert "净流入" in content
        assert "150.00" in content

    def test_not_triggered(self, tmp_path):
        """未超阈值 → 无告警。"""
        data = {"net_inflow": 50.0, "sh_net": 30.0, "sz_net": 20.0, "date": "2026-09-01"}
        report_path = tmp_path / "reports" / "2026-09-01.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("test", encoding="utf-8")

        with patch("src.alerter.load_config", return_value={"alert": {"northbound": 100.0}}):
            result = check_northbound_alert("2026-09-01", data, report_path)
        assert result == []

    def test_dedup(self, tmp_path):
        """同日重复调用 → 跳过。"""
        alerts_dir = tmp_path / "alerts"
        alerts_log = tmp_path / "alerts.log"
        alerts_log.write_text("2026-09-01 NORTHBOUND\n", encoding="utf-8")
        report_path = tmp_path / "reports" / "2026-09-01.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("test", encoding="utf-8")

        data = {"net_inflow": 150.0, "sh_net": 80.0, "sz_net": 70.0, "date": "2026-09-01"}

        with patch("src.alerter.ALERTS_DIR", alerts_dir), \
             patch("src.alerter.ALERTS_LOG", alerts_log), \
             patch("src.alerter.load_config", return_value={"alert": {"northbound": 100.0}}):
            result = check_northbound_alert("2026-09-01", data, report_path)
        assert result == []

    def test_none_data(self, tmp_path):
        """数据为 None → 跳过。"""
        report_path = tmp_path / "reports" / "2026-09-01.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("test", encoding="utf-8")

        result = check_northbound_alert("2026-09-01", None, report_path)
        assert result == []

    def test_negative_flow_triggered(self, tmp_path):
        """负值超阈值（净流出）→ 生成告警。"""
        alerts_dir = tmp_path / "alerts"
        alerts_log = tmp_path / "alerts.log"
        report_path = tmp_path / "reports" / "2026-09-01.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("test", encoding="utf-8")

        data = {"net_inflow": -120.0, "sh_net": -70.0, "sz_net": -50.0, "date": "2026-09-01"}

        with patch("src.alerter.ALERTS_DIR", alerts_dir), \
             patch("src.alerter.ALERTS_LOG", alerts_log), \
             patch("src.alerter.load_config", return_value={"alert": {"northbound": 100.0}}):
            result = check_northbound_alert("2026-09-01", data, report_path)

        assert len(result) == 1
        assert "净流出" in result[0]["message"]
