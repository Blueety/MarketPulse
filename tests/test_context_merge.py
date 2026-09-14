"""同日 context 合并语义专项（2026-09-14）：generate_context(merge=True)。

背景：`generate_context` 是全量覆盖写，而盘中快照只取本市场子集 → 每次快照都把当天
其它市场的数据抹掉。合并语义 = **合并「输入」，重算「派生」**：

- `indices`：`sym in values` → 覆盖（取数失败写 null 也覆盖）；否则保留旧条目
- `sector_heat`/`us_sector_heat`：`is None` 保留旧值；非 None（含 `[]`/`([], [])`）覆盖
- `correlation`/`watchlist`：`is None` 保留旧 payload 值
- `breach`/`search_keywords`：用合并后的 `values` 重算（否则板块词退化成 market summary）
- `merge` 默认 `False`：daily_report 不传 → 行为逐字节不变（M-6 回归护栏）

全部用例 monkeypatch CONTEXT_DIR 到 tmp_path（不写真实 context/）。
"""

import json
import logging

import pytest

import snapshot_report as snap
from src import alerter as al
from src import analyzer as an
from src import reporter as rep
from src import storage as st

DATE = "2026-09-14"
CN_SYMS = ("SH", "SZ", "CYB")

# 10 标的基准值（保证 build_statuses / generate_context 覆盖全部 SYMBOLS）
FULL_VALUES = {
    "GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
    "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0, "GLD": 252.30, "BTC": 65000.00,
}
US_VALUES = {"GSPC": 4510.0, "IXIC": 17600.0}
US_LAST = {"GSPC": 4500.0, "IXIC": 17500.0}
CN_VALUES = {"SH": 3130.0, "SZ": 10120.0, "CYB": 2220.0}
CN_LAST = {"SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0}

CN_SECTOR = (
    [{"name": "医药", "change": 3.23, "turnover": "13.7亿", "top_stock": "恒瑞医药"}],
    [{"name": "地产", "change": -2.3, "turnover": "10.0亿", "top_stock": "保利发展"}],
)
US_SECTOR = (
    [{"name": "能源", "change": 1.5, "turnover": "5.0亿", "top_stock": "XOM"}],
    [],
)


@pytest.fixture
def ctx_env(monkeypatch, tmp_path):
    """context / DB / alerts 全部重定向到 tmp；清宿主 ALERT_THRESHOLD_* env。"""
    monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    monkeypatch.setattr(al, "ALERTS_DIR", tmp_path / "alerts")
    monkeypatch.setattr(al, "ALERTS_LOG", tmp_path / "alerts.log")
    for sym in ("VIX", "VXN", "MOVE", "GSPC", "IXIC", "SH", "SZ", "CYB"):
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)
    return tmp_path


def _inputs(values, last_values):
    return dict(
        values=values,
        changes=an.compute_changes(values, last_values),
        statuses=an.build_statuses(values, {}, last_values, an.load_history()),
        last_values=last_values,
    )


def _read(ctx_env):
    path = ctx_env / "context" / f"{DATE}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_full(ctx_env, sector_heat=CN_SECTOR, us_sector_heat=None):
    """先写一份「全量」context（模拟 A 股快照/daily：本市场数据齐全）。"""
    rep.generate_context(
        DATE, **_inputs(dict(FULL_VALUES), dict(FULL_VALUES)),
        sector_heat=sector_heat, us_sector_heat=us_sector_heat,
    )
    return _read(ctx_env)


def _merge_us(ctx_env, values=None, sector_heat=None):
    """再写一份「美股子集」context（模拟 `--market us` 快照）。"""
    rep.generate_context(
        DATE, **_inputs(values or dict(US_VALUES), dict(US_LAST)),
        sector_heat=sector_heat, merge=True,
    )
    return _read(ctx_env)


class TestMergeIndices:
    def test_m1_keeps_absent_keys(self, ctx_env):
        """M-1：不在本次 values 里的 sym 保留旧 value/change_pct/status（不再是"休市"）。"""
        first = _write_full(ctx_env)
        data = _merge_us(ctx_env)
        for sym in CN_SYMS:
            assert data["indices"][sym] == first["indices"][sym]
        assert data["indices"]["SH"]["value"] == FULL_VALUES["SH"]
        assert data["indices"]["SH"]["change_pct"] == 0.0
        assert data["indices"]["SH"]["status"] != "休市"
        assert data["indices"]["SH"]["status"] == first["indices"]["SH"]["status"]

    def test_m5_key_present_none_overwrites(self, ctx_env):
        """M-5：键存在即覆盖 —— values["GSPC"]=None 写 null（诚实反映本次失败）。"""
        _write_full(ctx_env)
        data = _merge_us(ctx_env, values={"GSPC": None, "IXIC": 17600.0})
        assert data["indices"]["GSPC"]["value"] is None
        assert data["indices"]["SH"]["value"] == FULL_VALUES["SH"]

    def test_m10_cn_subset_keeps_us_indices(self, ctx_env):
        """M-10：反向验证 —— a-share 子集覆盖时，美股/波动率/另类资产保留旧值。"""
        first = _write_full(ctx_env)
        rep.generate_context(
            DATE, **_inputs(dict(CN_VALUES), dict(CN_LAST)),
            sector_heat=CN_SECTOR, merge=True,
        )
        data = _read(ctx_env)
        for sym in ("GSPC", "IXIC", "VIX", "VXN", "MOVE", "GLD", "BTC"):
            assert data["indices"][sym] == first["indices"][sym]
        assert data["indices"]["SH"]["value"] == CN_VALUES["SH"]


class TestMergeDerived:
    def test_m2_keywords_recomputed_from_merged_values(self, ctx_env):
        """M-2（核心）：派生字段用合并后 values 重算 → 板块词存活，不退化 market summary。"""
        _write_full(ctx_env)
        data = _merge_us(ctx_env)
        assert f"医药 surge {DATE}" in data["search_keywords"]
        assert data["search_keywords"] != [f"market summary {DATE}"]
        assert data["sector_heat"]["gainers"][0]["name"] == "医药"


class TestMergeSectorHeat:
    def test_m3_none_keeps_prev(self, ctx_env):
        """M-3：sector_heat=None（本次未取数）→ 保留旧 gainers/losers。"""
        _write_full(ctx_env)
        data = _merge_us(ctx_env, sector_heat=None)
        assert data["sector_heat"]["gainers"] == CN_SECTOR[0]
        assert data["sector_heat"]["losers"] == CN_SECTOR[1]

    def test_m4_empty_overwrites(self, ctx_env):
        """M-4：`([], [])`（取了但为空）必须能覆盖（R3：`[]` ≠ None）。"""
        _write_full(ctx_env)
        data = _merge_us(ctx_env, sector_heat=([], []))
        assert data["sector_heat"] == {"gainers": [], "losers": []}

    def test_m4b_us_sector_heat_kept_when_none(self, ctx_env):
        _write_full(ctx_env, us_sector_heat=US_SECTOR)
        data = _merge_us(ctx_env, sector_heat=None)
        assert data["us_sector_heat"]["gainers"] == US_SECTOR[0]


class TestMergeCorrelationWatchlist:
    def test_m9_none_keeps_prev_payload(self, ctx_env):
        """M-9：correlations/watchlist 为 None → 保留旧 payload 值（不二次加工）。"""
        corr = [{"a": "GSPC", "b": "SH", "pair": "标普500 ↔ 上证指数", "r": 0.81, "n": 30}]
        wl = {
            "stocks": [{"symbol": "AAPL", "label": "苹果", "value": 210.0, "change_pct": 5.0,
                        "r": 0.83, "n": 20, "benchmark": "GSPC"}],
            "portfolio_risk": {"high": True, "avg_r": 0.9},
        }
        rep.generate_context(
            DATE, **_inputs(dict(FULL_VALUES), dict(FULL_VALUES)),
            sector_heat=CN_SECTOR, correlations=corr, watchlist=wl,
        )
        data = _merge_us(ctx_env)
        assert data["correlation"] == [{"a": "GSPC", "b": "SH",
                                        "pair": "标普500 ↔ 上证指数", "r": 0.81, "n": 30}]
        assert data["watchlist"]["stocks"][0]["symbol"] == "AAPL"
        assert data["watchlist"]["portfolio_risk"]["high"] is True

    def test_m9b_correlation_rebuilt_when_given(self, ctx_env):
        """非 None 时仍走重建（显著过滤保留）。"""
        _write_full(ctx_env)
        rep.generate_context(
            DATE, **_inputs(dict(US_VALUES), dict(US_LAST)), sector_heat=None,
            correlations=[{"a": "GSPC", "b": "SH", "pair": "p", "r": 0.9, "n": 30},
                          {"a": "VIX", "b": "MOVE", "pair": "q", "r": 0.1, "n": 30}],
            merge=True,
        )
        data = _read(ctx_env)
        assert data["correlation"] == [{"a": "GSPC", "b": "SH", "pair": "p", "r": 0.9, "n": 30}]


class TestSnapshotCallerWiring:
    """R3 接线护栏：漏改 snapshot_report.py 的调用点 → 修复整体失效（`[]` 被判为"要覆盖"）。"""

    def _stub(self, monkeypatch, tmp_path, captured):
        monkeypatch.setattr(snap, "is_market_holiday", lambda market: False)  # 脱离运行日/周末影响
        monkeypatch.setattr(snap, "load_last_values", lambda: dict(US_LAST))
        monkeypatch.setattr(snap, "load_history", lambda: [])
        monkeypatch.setattr(snap, "build_statuses",
                            lambda *a, **k: {s: ("平静", "ok") for s in an.SYMBOLS})
        monkeypatch.setattr(snap, "save_snapshot", lambda *a, **k: tmp_path / "s.md")
        monkeypatch.setattr(snap, "run_alert_checks", lambda *a, **k: None)
        monkeypatch.setattr(snap, "merge_history", lambda *a, **k: None)
        monkeypatch.setattr(snap, "auto_commit_push", lambda *a, **k: None)
        monkeypatch.setattr(snap, "load_config", lambda: {"watchlist": {"stocks": []}})
        monkeypatch.setattr(snap, "generate_context",
                            lambda *a, **k: captured.update(k) or tmp_path / "c.json")
        return snap

    def test_us_snapshot_passes_merge_and_keeps_none(self, monkeypatch, tmp_path):
        captured = {}
        snap = self._stub(monkeypatch, tmp_path, captured)
        monkeypatch.setattr(snap, "fetch_all", lambda market: (dict(US_VALUES), {}))
        assert snap.main("us", "open") == 0
        assert captured.get("merge") is True
        assert captured.get("sector_heat") is None  # 不得被转成 []

    def test_a_share_empty_sector_heat_passthrough(self, monkeypatch, tmp_path):
        captured = {}
        snap = self._stub(monkeypatch, tmp_path, captured)
        monkeypatch.setattr(snap, "fetch_all", lambda market: (dict(CN_VALUES), {}))
        monkeypatch.setattr(snap, "fetch_sector_heat", lambda: ([], []))
        assert snap.main("a-share", "midday") == 0
        assert captured.get("merge") is True
        assert captured.get("sector_heat") == ([], [])  # "取了但为空"必须原样透传


class TestMergeFallbacks:
    def test_m6_default_merge_false_overwrites(self, ctx_env):
        """M-6 回归护栏：默认 merge=False → 全量覆盖，与改动前逐字节一致。"""
        _write_full(ctx_env)
        rep.generate_context(
            DATE, **_inputs(dict(US_VALUES), dict(US_LAST)), sector_heat=None,
        )
        data = _read(ctx_env)
        assert data["indices"]["SH"]["value"] is None
        assert data["indices"]["SH"]["status"] == "休市"
        assert data["sector_heat"] == {"gainers": [], "losers": []}
        assert data["search_keywords"] == [f"market summary {DATE}"]

    def test_m7_no_prev_file(self, ctx_env):
        """M-7：merge=True 但旧文件不存在 → 不抛异常，等价全量写。"""
        path = rep.generate_context(
            DATE, **_inputs(dict(US_VALUES), dict(US_LAST)), sector_heat=None, merge=True,
        )
        assert path == ctx_env / "context" / f"{DATE}.json"
        data = _read(ctx_env)
        assert data["indices"]["SH"]["value"] is None
        assert data["date"] == DATE

    def test_m8_corrupt_prev_file(self, ctx_env, caplog):
        """M-8：旧文件坏 JSON → 记 warning、退化为全量写，不抛异常。"""
        ctx_dir = ctx_env / "context"
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / f"{DATE}.json").write_text("{not json", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="marketpulse"):
            rep.generate_context(
                DATE, **_inputs(dict(US_VALUES), dict(US_LAST)), sector_heat=None, merge=True,
            )
        assert "读取旧 context 失败" in caplog.text
        data = _read(ctx_env)
        assert data["indices"]["SH"]["value"] is None
