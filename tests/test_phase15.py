"""十五期开盘分析专项测试（不联网，全程 mock 网络 IO）。

覆盖：新浪解析 / 跳空计算 / 情绪 / 报告渲染 / 降级 / 日报引用 / 入口编排 / 零持久化。
"""

import importlib

import pytest

import src.fetcher as ft
import src.reporter as rep
import opening_analyzer as oa
import json

import src.analyzer as an
from src.reporter import render_report


# ---- 1-3: parse_sina_realtime ----
class TestParseSinaRealtime:
    def test_a_share_normal(self):
        text = 'var hq_str_sh000001="上证指数,3000.50,2950.00,2980.00,2990.00,2940.00,2935.00";'
        r = ft.parse_sina_realtime(text, "a-share")
        assert r == {"open": 3000.50, "prev_close": 2950.00, "current": 2980.00}

    def test_us_normal(self):
        text = 'var hq_str_gb_inx="标普500,4500.00,1.2%,2026-08-31 09:30:00,53.0,4480.00,4490.00";'
        r = ft.parse_sina_realtime(text, "us")
        assert r == {"current": 4500.00, "prev_close": 4480.00, "open": 4490.00}

    def test_empty_and_short_and_nonnum(self):
        assert ft.parse_sina_realtime("", "a-share") is None
        assert ft.parse_sina_realtime('var hq_str_sh000001="上证指数";', "a-share") is None
        assert ft.parse_sina_realtime('var hq_str_sh000001="上证指数,abc,def,ghi";', "a-share") is None
        # 0 视为缺失（避免跳空除零）
        text = 'var hq_str_sh000001="上证指数,0,0,0";'
        assert ft.parse_sina_realtime(text, "a-share") == {"open": None, "prev_close": None, "current": None}


# ---- 4-6: fetch_realtime_quotes ----
SINA_A_SHARE = (
    'var hq_str_sh000001="上证指数,3000.50,2950.00,2980.00";'
    'var hq_str_sz399001="深证成指,12000.50,11900.00,11950.00";'
    'var hq_str_sz399006="创业板指,2500.50,2480.00,2490.00";'
)


class TestFetchRealtimeQuotes:
    def test_a_share_ok(self, monkeypatch):
        monkeypatch.setattr(ft, "_sina_realtime_get", lambda url: SINA_A_SHARE)
        monkeypatch.setattr(ft, "fetch_vix_realtime", lambda: (14.5, 15.0))
        quotes, errors = ft.fetch_realtime_quotes("a-share")
        assert set(quotes) == {"SH", "SZ", "CYB", "VIX"}
        assert quotes["SH"]["open"] == 3000.50
        assert quotes["SH"]["prev_close"] == 2950.00
        assert quotes["VIX"]["current"] == 14.5
        assert quotes["VIX"]["prev_close"] == 15.0
        assert not errors

    def test_request_exception_empty(self, monkeypatch):
        monkeypatch.setattr(ft, "fetch_with_retry", lambda name, fn, retries=1: None)
        monkeypatch.setattr(ft, "fetch_vix_realtime", lambda: (None, None))
        quotes, errors = ft.fetch_realtime_quotes("a-share")
        assert quotes == {}
        assert "sina" in errors and "VIX" in errors

    def test_vix_yahoo_fail_others_ok(self, monkeypatch):
        monkeypatch.setattr(ft, "_sina_realtime_get", lambda url: SINA_A_SHARE)
        monkeypatch.setattr(ft, "fetch_vix_realtime", lambda: (None, None))
        quotes, errors = ft.fetch_realtime_quotes("a-share")
        assert set(quotes) == {"SH", "SZ", "CYB"}
        assert "VIX" not in quotes
        assert "VIX" in errors


# ---- 7-8: 分析层纯函数 ----
class TestComputeGaps:
    def test_gaps(self):
        quotes = {
            "SH": {"open": 3030.0, "prev_close": 3000.0, "current": 3015.0},
            "SZ": {"open": 11900.0, "prev_close": 12000.0, "current": 11950.0},
            "VIX": {"current": 14.5, "prev_close": 15.0, "open": None},
        }
        gaps = oa.compute_gaps(quotes)
        assert gaps["SH"]["open_gap"] == 1.0
        assert gaps["SH"]["current_change"] == 0.5
        assert gaps["SZ"]["open_gap"] == -0.8333333333333334
        assert "VIX" not in gaps

    def test_missing_prev_close_none(self):
        quotes = {"SH": {"open": 10.0, "prev_close": None, "current": 10.5}}
        gaps = oa.compute_gaps(quotes)
        assert gaps["SH"]["open_gap"] is None
        assert gaps["SH"]["current_change"] is None


class TestBuildOpeningSentiment:
    def test_vix_present(self):
        quotes = {
            "SH": {"open": 3030.0, "prev_close": 3000.0, "current": 3015.0},
            "VIX": {"current": 14.5, "prev_close": 15.0, "open": None},
        }
        s = oa.build_opening_sentiment(quotes, {})
        assert s["vix"]["label"] == "平静"
        assert s["direction"] == "高开"

    def test_vix_missing(self):
        quotes = {"SH": {"open": 3000.0, "prev_close": 3000.0, "current": 3000.0}}
        s = oa.build_opening_sentiment(quotes, {"VIX": "fail"})
        assert s["vix"]["label"] == "数据暂缺"
        assert s["direction"] == "平开"


# ---- 9-11: 报告层 ----
class TestRenderOpeningReport:
    def _sample(self, market="a-share"):
        quotes = {
            "SH": {"open": 3030.0, "prev_close": 3000.0, "current": 3015.0},
            "SZ": {"open": 11900.0, "prev_close": 12000.0, "current": 11950.0},
            "CYB": {"open": 2500.0, "prev_close": 2480.0, "current": 2490.0},
            "VIX": {"current": 14.5, "prev_close": 15.0, "open": None},
        }
        gaps = oa.compute_gaps(quotes)
        sentiment = oa.build_opening_sentiment(quotes, {})
        return quotes, gaps, sentiment

    def test_sections_present(self):
        quotes, gaps, sentiment = self._sample()
        body = rep.render_opening_report("2026-08-31", "a-share", quotes, gaps, sentiment,
                                         sector_heat=([], []))
        for sec in ("🌅 开盘分析", "📊 开盘跳空", "🔥 热点板块 Top 5",
                    "📉 领跌板块 Top 5", "🏷️ 开盘情绪", "📝 开盘速览", "🤖 AI 解读"):
            assert sec in body
        assert "数据来源：新浪实时行情（VIX 来自 Yahoo Finance）" in body

    def test_degrade_missing_prev_close_and_sector(self):
        quotes = {"SH": {"open": None, "prev_close": None, "current": None}}
        gaps = oa.compute_gaps(quotes)
        sentiment = oa.build_opening_sentiment(quotes, {"SH": "fail"})
        body = rep.render_opening_report("2026-08-31", "a-share", quotes, gaps, sentiment,
                                         sector_heat=None, errors={"SH": "fail"})
        assert "获取失败" in body
        assert "数据暂缺" in body
        assert "注：部分数据源获取异常" in body


class TestSaveOpening:
    def test_path_and_content(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "OPENING_DIR", tmp_path)
        path = rep.save_opening("2026-08-31", "a-share", "# 开盘分析\n内容")
        assert path == tmp_path / "2026-08-31-a-share.md"
        assert path.exists()
        assert "内容" in path.read_text(encoding="utf-8")


# ---- 12-13: 日报引用 ----
class TestLoadOpeningRefs:
    def _write(self, opening_dir, market, name, gap):
        content = f"""# 🌅 开盘分析

## 📊 开盘跳空

| 指数 | 开盘价 | 昨收 | 跳空 | 当前价 | 当前涨跌 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| {name} | 3000 | 2950 | {gap} | 2980 | +1.0% |

## 🏷️ 开盘情绪

**VIX 当前值：14.50 → 状态：平静**（数据来源：Yahoo Finance）
"""
        (opening_dir / f"2026-08-31-{market}.md").write_text(content, encoding="utf-8")

    def test_both_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "OPENING_DIR", tmp_path)
        monkeypatch.setattr(rep, "get_market_date", lambda market: "2026-08-31")
        self._write(tmp_path, "us", "标普500", "+1.20%")
        self._write(tmp_path, "a-share", "上证指数", "+0.50%")
        refs = rep.load_opening_refs("2026-08-31")
        assert len(refs) == 2
        us = next(r for r in refs if r["market"] == "us")
        assert "标普500 跳空 +1.20%" in us["summary"]
        assert "VIX 14.50" in us["summary"]
        cn = next(r for r in refs if r["market"] == "a-share")
        assert "上证指数 跳空 +0.50%" in cn["summary"]

    def test_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "OPENING_DIR", tmp_path)
        assert rep.load_opening_refs("2026-08-31") == []


class TestRenderReportOpeningRefs:
    def _minimal(self):
        from src.fetcher import SYMBOLS
        values = {s: 100.0 for s in SYMBOLS}
        changes = {s: 1.0 for s in SYMBOLS}
        statuses = {s: ("平稳", "desc") for s in SYMBOLS}
        return values, changes, statuses

    def test_default_no_section(self):
        values, changes, statuses = self._minimal()
        body = render_report("2026-08-31", values, changes, statuses, "总结", True)
        assert "🔔 开盘分析" not in body

    def test_with_refs_section(self):
        values, changes, statuses = self._minimal()
        refs = [
            {"market": "us", "date": "2026-08-31", "summary": "标普500 跳空 +1.20%"},
            {"market": "a-share", "date": "2026-08-31", "summary": "上证指数 跳空 +0.50%"},
        ]
        body = render_report("2026-08-31", values, changes, statuses, "总结", True,
                             opening_refs=refs)
        assert "🔔 开盘分析" in body
        assert "opening/2026-08-31-us.md" in body
        assert "opening/2026-08-31-a-share.md" in body


# ---- 14-15: 入口编排 + 零持久化 ----
class TestOpeningEntry:
    def test_main_orchestration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rep, "OPENING_DIR", tmp_path)
        captured = {}

        def fake_fetch(market):
            return (
                {"SH": {"open": 3030.0, "prev_close": 3000.0, "current": 3015.0},
                 "VIX": {"current": 14.5, "prev_close": 15.0, "open": None}},
                {},
            )

        monkeypatch.setattr(oa, "fetch_realtime_quotes", fake_fetch)
        monkeypatch.setattr(oa, "fetch_sector_heat", lambda: ([], []))
        monkeypatch.setattr(oa, "fetch_us_sector_heat", lambda: ([], []))
        monkeypatch.setattr(oa, "render_opening_report", lambda *a, **k: "RENDERED")
        monkeypatch.setattr(oa, "save_opening",
                            lambda d, m, c: captured.setdefault("path", tmp_path / f"{d}-{m}.md"))
        monkeypatch.setattr(oa, "merge_history",
                            lambda d, v: captured.setdefault("merge", (d, v)))

        rc = oa.main("a-share")
        assert rc == 0
        assert "merge" in captured
        assert captured["merge"][1] == {"SH": 3015.0}

    def test_zero_persistence(self, tmp_path, monkeypatch):
        # 反转：开盘分析现合并写 history（决策 R1/R3）；仍不写 context
        data_dir = tmp_path / "data"
        ctx_dir = tmp_path / "context"
        history_file = tmp_path / "history.json"  # 父目录已存在，merge_history 写入不会 FileNotFoundError
        monkeypatch.setattr(rep, "OPENING_DIR", tmp_path / "opening")
        # 重定向 analyzer 持久化目标到 tmp，防止触碰真实 data/history.json
        monkeypatch.setattr(an, "HISTORY_FILE", history_file)
        monkeypatch.setattr(oa, "fetch_realtime_quotes",
                            lambda m: ({"SH": {"open": 1.0, "prev_close": 1.0, "current": 1.0}}, {}))
        monkeypatch.setattr(oa, "fetch_sector_heat", lambda: ([], []))
        monkeypatch.setattr(oa, "fetch_us_sector_heat", lambda: ([], []))
        monkeypatch.setattr(oa, "render_opening_report", lambda *a, **k: "RENDERED")
        monkeypatch.setattr(oa, "save_opening", lambda d, m, c: tmp_path / "opening" / f"{d}-{m}.md")

        rc = oa.main("a-share")
        assert rc == 0
        # history 被合并写入当日行（仅 SH，本市场子集；VIX 不写）
        hist = json.loads(history_file.read_text(encoding="utf-8"))
        today = [r for r in hist if r["date"] == oa.get_market_date("a-share")]
        assert len(today) == 1
        assert today[0]["sh"] == 1.0
        # context 仍零写入（保留原零持久化约束中 context 部分）
        assert not list(ctx_dir.rglob("*"))
