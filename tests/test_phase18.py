"""十八期 板块聚合专项测试（不联网，全部 mock / 手工构造）。

覆盖：SECTOR_MAPPING 完整性、aggregate_sectors 纯函数（加权公式 / 零成交额简单平均 /
未匹配归其他 / 单成员 / 全未匹配 / 空输入 / 排序与 TopN / top_stock 取法 /
turnover 合计格式 / 类别数 ≤15）、fetch_sector_heat 集成（mock akshare）、
render_snapshot 聚合行渲染、build_search_keywords 大类方向词注入、
generate_context 聚合落盘。
"""

import json

import pytest

from src import analyzer as an
from src import fetcher as ft
from src import reporter as rep

# 与 src/fetcher.SECTOR_MAPPING 保持一致（PRD 表原文 + 新浪实际板块别名）。
EXPECTED_MAPPING = {
    "通信/电子": [
        "5G概念", "华为概念", "消费电子", "物联网",
        "华为海思", "华为鸿蒙", "苹果概念", "小米概念", "无线耳机", "智能穿戴",
    ],
    "光伏/新能源": [
        "光伏", "光伏概念", "新能源", "锂矿", "锂电池", "盐湖提锂",
        "氢能源", "氢燃料", "充电桩", "固态电池", "钠电池", "钒电池",
        "风电", "风能", "风能概念", "HIT电池", "TOPCon", "BC电池", "钙钛矿", "电解液",
    ],
    "半导体/芯片": ["芯片", "半导体", "集成电路"],
    "军工": ["国防军工", "军工航天", "军民融合", "卫星导航", "大飞机", "海工装备"],
    "医药": [
        "创新药", "仿制药", "免疫治疗", "CRO概念",
        "CXO概念", "基因概念", "基因测序", "生物疫苗", "抗癌", "民营医院", "超级细菌", "甲型流感",
    ],
    "消费": ["白酒", "食品饮料", "新零售", "白酒概念", "电商概念"],
    "金融": ["券商", "银行", "保险", "券商重仓", "民营银行", "保险重仓", "互联金融", "参股金融", "金融改革"],
    "地产/基建": ["房地产", "基建", "水泥", "土地流转"],
    "资源/有色": ["黄金概念", "有色金属", "稀土", "煤炭", "稀缺资源"],
    "农业": [
        "农业", "养殖", "猪肉",
        "生态农业", "乡村振兴", "鸡肉", "水产品", "生物育种",
    ],
}


class TestSectorMapping:
    def test_mapping_complete(self):
        assert ft.SECTOR_MAPPING == EXPECTED_MAPPING
        assert len(ft.SECTOR_MAPPING) == 10
        assert total == 82
        # 概念名不跨类重复
        seen = []
        for names in ft.SECTOR_MAPPING.values():
        for names in ft.SECTOR_MAPPING.values():
            seen.extend(names)
        assert len(seen) == len(set(seen))


class TestParseTurnover:
    def test_yi(self):
        assert ft._parse_turnover("13.7亿") == pytest.approx(1.37e9)

    def test_wan(self):
        assert ft._parse_turnover("500万") == pytest.approx(5e6)

    def test_plain(self):
        assert ft._parse_turnover("12345") == 12345.0

    def test_empty_and_invalid(self):
        assert ft._parse_turnover("") == 0.0
        assert ft._parse_turnover(None) == 0.0
        assert ft._parse_turnover("abc") == 0.0


def _row(name, change, turnover, top_stock="X"):
    return {"name": name, "change": change, "turnover": turnover, "top_stock": top_stock}


class TestAggregateSectors:
    def test_weighted_formula(self):
        # 光伏/新能源：锂电池(3,10亿) + 光伏(5,30亿) → (3*10+5*30)/40 = 4.5
        rows = [
            _row("锂电池", 3.0, "10.0亿"),
            _row("光伏", 5.0, "30.0亿"),
        ]
        gainers, losers = ft.aggregate_sectors(rows)
        assert len(gainers) == 1
        cat = gainers[0]
        assert cat["name"] == "光伏/新能源"
        assert cat["change"] == 4.5
        assert cat["turnover"] == "40.0亿"
        # top_stock = 成交额最大子板块（光伏 30e9，默认 top_stock 均为 "X"）
        assert cat["top_stock"] == "X"

    def test_zero_turnover_simple_average(self):
        # 半导体/芯片：两行成交额均为 0 → 简单平均 (2+4)/2 = 3.0
        rows = [
            _row("芯片", 2.0, "0.0亿"),
            _row("半导体", 4.0, "0.0亿"),
        ]
        gainers, losers = ft.aggregate_sectors(rows)
        assert gainers[0]["name"] == "半导体/芯片"
        assert gainers[0]["change"] == 3.0
        assert gainers[0]["turnover"] == "0.0亿"

    def test_unmatched_goes_to_other(self):
        rows = [
            _row("生物育种", 5.2, "7.2亿"),
            _row("不存在板块", -1.0, "3.0亿"),
        ]
        gainers, losers = ft.aggregate_sectors(rows)
        assert [r["name"] for r in gainers] == ["其他"]
        assert gainers[0]["change"] == pytest.approx((5.2 * 7.2 + (-1.0) * 3.0) / 10.2, abs=0.01)

    def test_single_member_category(self):
        rows = [_row("白酒", 2.5, "12.0亿", top_stock="茅台")]
        gainers, losers = ft.aggregate_sectors(rows)
        assert gainers[0]["name"] == "消费"
        assert gainers[0]["change"] == 2.5
        assert gainers[0]["turnover"] == "12.0亿"
        assert gainers[0]["top_stock"] == "茅台"

    def test_all_unmatched_single_other(self):
        rows = [
            _row("a", 1.0, "1.0亿"),
            _row("b", -2.0, "2.0亿"),
        ]
        gainers, losers = ft.aggregate_sectors(rows)
        # 仅「其他」一类，同时出现在 gainers 与 losers
        assert [r["name"] for r in gainers] == ["其他"]
        assert [r["name"] for r in losers] == ["其他"]

    def test_empty_input(self):
        assert ft.aggregate_sectors([]) == ([], [])

    def test_sorting_and_topn(self):
        # 构造 6 个大类（5 映射 + 其他），验证降序/升序 Top3 截断
        rows = [
            _row("锂电池", 1.0, "10.0亿"),   # 光伏/新能源
            _row("创新药", 2.0, "10.0亿"),   # 医药
            _row("白酒", 3.0, "10.0亿"),     # 消费
            _row("券商", 4.0, "10.0亿"),     # 金融
            _row("猪肉", 5.0, "10.0亿"),     # 农业
            _row("未知", 0.5, "10.0亿"),     # 其他
        ]
        gainers, losers = ft.aggregate_sectors(rows, top_n=3)
        assert [r["name"] for r in gainers] == ["农业", "金融", "消费"]
        assert [r["name"] for r in losers] == ["其他", "光伏/新能源", "医药"]

    def test_top_stock_by_max_turnover(self):
        # 同一类内 top_stock 取成交额最大子板块
        rows = [
            _row("锂电池", 3.0, "10.0亿", top_stock="小锂"),
            _row("光伏", 4.0, "50.0亿", top_stock="大光"),
        ]
        gainers, _ = ft.aggregate_sectors(rows)
        assert gainers[0]["top_stock"] == "大光"

    def test_turnover_total_format(self):
        rows = [
            _row("芯片", 1.0, "12.34亿"),
            _row("半导体", 2.0, "7.66亿"),
        ]
        gainers, _ = ft.aggregate_sectors(rows)
        # 合计 20.0亿 → "20.0亿"
        assert gainers[0]["turnover"] == "20.0亿"

    def test_category_count_le_15(self):
        # 覆盖全部 10 映射类 + 其他 = 11 类，断言 ≤ 15
        rows = []
        sample = [
            ("5G概念", 1.0), ("光伏", 2.0), ("芯片", 3.0), ("国防军工", 4.0),
            ("创新药", 5.0), ("白酒", 6.0), ("券商", 7.0), ("房地产", 8.0),
            ("黄金概念", 9.0), ("猪肉", 10.0), ("未知概念", 0.1),
        ]
        for name, ch in sample:
            rows.append(_row(name, ch, "1.0亿"))
        gainers, losers = ft.aggregate_sectors(rows)
        distinct = {r["name"] for r in gainers} | {r["name"] for r in losers}
        assert distinct <= set(ft.SECTOR_MAPPING.keys()) | {"其他"}
        assert len(distinct) <= 15


class TestFetchSectorHeatIntegration:
    def _spot_df(self, rows):
        import pandas as pd

        return pd.DataFrame(rows)

    def test_returns_aggregated(self, monkeypatch):
        import akshare as ak_mod

        rows = [
            {"板块": "锂电池", "涨跌幅": 3.0, "总成交额": 40_000_000_000, "股票名称": "宁德时代"},
            {"板块": "光伏", "涨跌幅": 6.0, "总成交额": 20_000_000_000, "股票名称": "隆基绿能"},
            {"板块": "创新药", "涨跌幅": 4.0, "总成交额": 10_000_000_000, "股票名称": "恒瑞医药"},
            {"板块": "生物育种", "涨跌幅": 5.2, "总成交额": 7_220_000_000, "股票名称": "敦煌种业"},
        ]
        monkeypatch.setattr(ak_mod, "stock_sector_spot", lambda indicator=None: self._spot_df(rows))
        gainers, losers = ft.fetch_sector_heat()
        # 聚合后不再出现概念名「锂电池」「创新药」，而是大类名
        names = {r["name"] for r in gainers} | {r["name"] for r in losers}
        assert "锂电池" not in names
        assert "创新药" not in names
        assert "光伏/新能源" in names
        assert "医药" in names
        assert "其他" in names


class TestRenderSnapshotAggregated:
    def test_snapshot_renders_category_names(self):
        values = {"SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0}
        statuses = an.build_statuses(values, {})
        sector_heat = (
            [{"name": "光伏/新能源", "change": 4.0, "turnover": "600.0亿", "top_stock": "宁德时代"}],
            [{"name": "农业", "change": -3.0, "turnover": "50.0亿", "top_stock": "牧原股份"}],
        )
        body = rep.render_snapshot(
            "2026-08-31", values, statuses, market="a-share", time="midday",
            sector_heat=sector_heat,
        )
        assert "## 🔥 A 股热点板块 Top 5" in body
        assert "| 光伏/新能源 | +4.00% | 600.0亿 | 宁德时代 |" in body
        assert "| 农业 | -3.00% | 50.0亿 | 牧原股份 |" in body


class TestSearchKeywordsAggregated:
    def test_category_direction_injected(self):
        sh = ([{"name": "半导体/芯片", "change": 5.0}], [{"name": "农业", "change": -2.0}])
        kw = an.build_search_keywords("2026-08-31", [], sector_heat=sh)
        assert "半导体/芯片 surge 2026-08-31" in kw
        assert "农业 drop 2026-08-31" in kw


class TestGenerateContextAggregated:
    def test_context_stores_categories(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
        monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
        from src import alerter as al

        monkeypatch.setattr(al, "ALERTS_DIR", tmp_path / "alerts")
        monkeypatch.setattr(al, "ALERTS_LOG", tmp_path / "alerts.log")

        values = {"GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
                  "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0, "GLD": 252.30, "BTC": 65000.00}
        last = {"GSPC": 4400.0, "IXIC": 17000.0, "SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0,
                "VIX": 20.0, "VXN": 18.0, "MOVE": 75.0, "GLD": 250.10, "BTC": 64000.00}
        sector_heat = (
            [{"name": "光伏/新能源", "change": 4.0, "turnover": "600.0亿", "top_stock": "宁德时代"}],
            [{"name": "农业", "change": -3.0, "turnover": "50.0亿", "top_stock": "牧原股份"}],
        )
        rep.generate_context(
            "2026-08-31",
            values=values,
            changes=an.compute_changes(values, last),
            statuses=an.build_statuses(values, {}),
            last_values=last,
            sector_heat=sector_heat,
        )
        data = json.loads((tmp_path / "context" / "2026-08-31.json").read_text(encoding="utf-8"))
        assert data["sector_heat"]["gainers"][0]["name"] == "光伏/新能源"
        assert data["sector_heat"]["losers"][0]["name"] == "农业"
        assert "光伏/新能源 surge 2026-08-31" in data["search_keywords"]
