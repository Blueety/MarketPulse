"""二十七期单元测试：动态告警阈值（基于历史波动率的 rolling 窗口）。

覆盖：config 新键 + bool 合并分支 / _trailing_returns + dynamic_alert_threshold 纯函数 /
check_breach 动态模式标注 / 消费点接线（alerter/reporter/daily/snapshot）/ 回测窗口化。

conftest 已强制 CONFIG_PATH 指向不存在文件 → 模块 import 时快照恒为内置默认
（ALERT_DYNAMIC=True、ALERT_LOOKBACK_DAYS=20、ALERT_K_FACTOR=2.0）。
"""
import statistics

import pytest

from src import analyzer as an
from src import reporter as rep
from src import config
from src import alerter as alerter
from src.config import DEFAULTS, load_config
import daily_report as dr
import snapshot_report as sr
from scripts import backtest as bt
# 隔离：清除宿主 ALERT_THRESHOLD_* env（与 test_alerter.clean_thresholds 同义）
# --------------------------------------------------------------------------- #
# 与 test_phase25 一致的 10 标的基准值（保证 build_statuses / generate_context 覆盖全部 SYMBOLS）
_VALUES = {
    "GSPC": 4500.0, "IXIC": 17500.0, "SH": 3120.0, "SZ": 10100.0, "CYB": 2210.0,
    "VIX": 21.0, "VXN": 19.0, "MOVE": 78.0, "GLD": 200.0, "BTC": 60000.0,
}
@pytest.fixture
def clean_thresholds(monkeypatch):
    for sym in an.SYMBOLS:
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)
    yield


def _write(tmp_path, obj):
    p = tmp_path / "config.json"
    p.write_text(__import__("json").dumps(obj), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# config：新键 + bool 合并分支
# --------------------------------------------------------------------------- #
class TestConfigDynamic:
    def test_defaults_have_dynamic_keys(self, tmp_path):
        cfg = load_config(path=tmp_path / "nope.json")
        assert cfg["alert"]["dynamic"] is True
        assert cfg["alert"]["lookback_days"] == 20
        assert cfg["alert"]["k_factor"] == 2.0

    def test_module_constants_default(self):
        assert an.ALERT_DYNAMIC is True
        assert an.ALERT_LOOKBACK_DAYS == 20
        assert an.ALERT_K_FACTOR == 2.0

    def test_dynamic_false_accepted(self, tmp_path):
        cfg = load_config(path=_write(tmp_path, {"alert": {"dynamic": False}}))
        assert cfg["alert"]["dynamic"] is False

    def test_dynamic_true_accepted(self, tmp_path):
        cfg = load_config(path=_write(tmp_path, {"alert": {"dynamic": True}}))
        assert cfg["alert"]["dynamic"] is True

    def test_dynamic_illegal_string_falls_back(self, tmp_path):
        cfg = load_config(path=_write(tmp_path, {"alert": {"dynamic": "yes"}}))
        assert cfg["alert"]["dynamic"] is True  # 回退默认 True

    def test_lookback_zero_falls_back(self, tmp_path):
        cfg = load_config(path=_write(tmp_path, {"alert": {"lookback_days": 0}}))
        assert cfg["alert"]["lookback_days"] == 20  # 须 >0

    def test_k_factor_override(self, tmp_path):
        cfg = load_config(path=_write(tmp_path, {"alert": {"k_factor": 3.5}}))
        assert cfg["alert"]["k_factor"] == 3.5


# --------------------------------------------------------------------------- #
# 纯函数：_trailing_returns + dynamic_alert_threshold
# --------------------------------------------------------------------------- #
def _hist_dates(values, sym="vix"):
    return [{"date": f"2026-01-{i:02d}", sym: v} for i, v in enumerate(values, 1)]


class TestTrailingReturns:
    def test_continuous_window(self):
        # closes 最新→最旧 = [110, 99, 110, 99, 110, 100]
        # 收益（旧→新）= [+10, -10, +11.11, -10, +11.11]
        hist = _hist_dates([100, 110, 99, 110, 99, 110])
        rets = an._trailing_returns("VIX", hist, 5)
        assert rets == pytest.approx([10.0, -10.0, 11.1111, -10.0, 11.1111], abs=1e-3)

    def test_gap_inside_window_interrupts(self):
        # d4=105, d3=None → 缺口中断，仅 1 个有效收盘 → 0 个收益
        hist = _hist_dates([100, 110, None, 105])
        assert an._trailing_returns("VIX", hist, 5) == []

    def test_gap_outside_window_ok(self):
        # 缺口在最旧行（窗口外），不影响最近 4 个收盘
        hist = _hist_dates([None, 100, 110, 99, 110, 99, 110])
        rets = an._trailing_returns("VIX", hist, 3)
        assert rets == pytest.approx([10.0, -10.0, 11.1111], abs=1e-3)


class TestDynamicThreshold:
    def test_formula_mean_plus_k_std(self):
        # 收益 [+5,-5,+5,-5,+5]：mean=1, 样本 std=sqrt(30)=5.47723
        hist = _hist_dates([100, 105, 99.75, 104.7375, 99.500625, 104.47565625])
        rets = an._trailing_returns("VIX", hist, 5)
        expected = statistics.mean(rets) + 2.0 * statistics.stdev(rets)
        val = an.dynamic_alert_threshold("VIX", hist, lookback_days=5, k_factor=2.0)
        assert val == pytest.approx(expected)

    def test_sample_insufficient_returns_none(self):
        hist = _hist_dates([100, 110, 99])  # 仅 2 个收益 < lookback 5
        assert an.dynamic_alert_threshold("VIX", hist, lookback_days=5) is None

    def test_lookback_one_none(self):
        hist = _hist_dates([100, 110])  # 1 个收益 → stdev 无定义
        assert an.dynamic_alert_threshold("VIX", hist, lookback_days=1) is None

    def test_zero_variance_none(self):
        # 恒定 +5%：std=0 → StatisticsError → None
        hist = _hist_dates([100, 100, 100, 100, 100, 100])  # 恒值 → 收益全 0 → std 无定义 → None
        assert an.dynamic_alert_threshold("VIX", hist, lookback_days=5) is None

    def test_negative_drift_le_zero_none(self):
        # 收益 [-2,-2,-2,-2,-1]：mean≈-1.8, std>0, 阈值<0 → None
        hist = _hist_dates([100, 98, 96.04, 94.1192, 92.1968, 91.2748])
        assert an.dynamic_alert_threshold("VIX", hist, lookback_days=5) is None

    def test_k_and_lookback_override(self):
        hist = _hist_dates([100, 105, 99.75, 104.7375, 99.500625, 104.47565625])
        base = an.dynamic_alert_threshold("VIX", hist, lookback_days=5, k_factor=2.0)
        bigger = an.dynamic_alert_threshold("VIX", hist, lookback_days=5, k_factor=4.0)
        assert bigger == pytest.approx(2.0 * base - statistics.mean(an._trailing_returns("VIX", hist, 5)))


# --------------------------------------------------------------------------- #
# check_breach 动态模式标注
# --------------------------------------------------------------------------- #
class TestCheckBreachMode:
    def _low_vol_history(self, n=25, sym="vix"):
        # 围绕 20 的微小波动（±0.05）→ 动态阈值远小于固定阈值
        vals = [20.0 + (0.01 if i % 2 else -0.01) for i in range(n)]
        return _hist_dates(vals, sym)

    def test_dynamic_mode_triggers_small_move(self, clean_thresholds):
        hist = self._low_vol_history()
        dyn = an.dynamic_alert_threshold("VIX", hist)
        assert dyn is not None and dyn < 20.0  # 动态 < 固定(20)
        breach = an.check_breach("VIX", 20.2, 20.0, hist)  # +1% > 动态
        assert breach is not None
        assert breach["threshold_mode"] == "dynamic"
        assert breach["dynamic_threshold"] == pytest.approx(breach["threshold"])
        assert breach["threshold"] == pytest.approx(dyn)

    def test_high_vol_mode_suppresses(self, clean_thresholds):
        # 大幅波动 → 动态阈值 > 固定；25% 变化被动态抑制
        vals = [20.0 + (3.0 if i % 2 else -3.0) for i in range(25)]
        hist = _hist_dates(vals)
        dyn = an.dynamic_alert_threshold("VIX", hist)
        assert dyn is not None and dyn > 20.0
        assert an.check_breach("VIX", 125, 100, hist) is None  # +25% < 动态

    def test_no_history_fixed(self, clean_thresholds):
        breach = an.check_breach("VIX", 25, 20, history=None)  # +25% > 固定 20
        assert breach is not None
        assert breach["threshold_mode"] == "fixed"
        assert breach["dynamic_threshold"] is None
        assert breach["threshold"] == pytest.approx(20.0)

    def test_empty_history_fixed(self, clean_thresholds):
        breach = an.check_breach("VIX", 25, 20, history=[])
        assert breach["threshold_mode"] == "fixed"
        assert breach["dynamic_threshold"] is None

    def test_dynamic_disabled_fixed(self, clean_thresholds, monkeypatch):
        monkeypatch.setattr(an, "ALERT_DYNAMIC", False)
        hist = self._low_vol_history()
        breach = an.check_breach("VIX", 100, 99, hist)  # +1% < 固定 20 → 不触发
        assert breach is None
        # 即便变化够大，模式也是 fixed
        breach2 = an.check_breach("VIX", 30, 20, hist)
        assert breach2["threshold_mode"] == "fixed"
        assert breach2["dynamic_threshold"] is None



# --------------------------------------------------------------------------- #
# 接线：alerter / reporter / daily / snapshot
# --------------------------------------------------------------------------- #
class TestWiring:

    def test_collect_breaches_passes_history(self, clean_thresholds, monkeypatch):
        calls = []
        monkeypatch.setattr(alerter, "check_breach",
                            lambda sym, cur, last, history=None: calls.append(history) or None)
        hist = _hist_dates([20, 20.1, 19.9])
        alerter.collect_breaches({"VIX": 20.0}, {"VIX": 20.0}, hist)
        assert calls and calls[0] is hist

    def test_run_alert_checks_passes_history(self, clean_thresholds, monkeypatch):
        captured = {}
        monkeypatch.setattr(alerter, "collect_breaches",
                            lambda v, lv, history=None: (captured.__setitem__("h", history) or []))
        hist = _hist_dates([20, 20.1, 19.9])
        alerter.run_alert_checks("2026-09-03", {"VIX": 20.0}, {"VIX": 20.0}, "close",
                                 __import__("pathlib").Path("x.md"), hist)
        assert captured["h"] is hist

    def test_generate_context_excludes_today(self, clean_thresholds, monkeypatch, tmp_path):
        monkeypatch.setattr(an, "CONTEXT_DIR", tmp_path / "context")
        captured = {}
        monkeypatch.setattr(rep, "collect_breaches",
                            lambda v, lv, history=None: (captured.__setitem__("h", history) or []))
        today_rows = [
            {"date": "2026-09-03", "vix": 999.0},
            {"date": "2026-09-02", "vix": 20.0},
        ]
        monkeypatch.setattr(an, "load_history", lambda: today_rows)
        rep.generate_context("2026-09-03", {"VIX": 20.0}, {"VIX": 0.0},
                             {sym: ("平静", "ok") for sym in an.SYMBOLS}, {"VIX": 20.0})
        assert captured["h"] is not None
        assert all(r["date"] != "2026-09-03" for r in captured["h"])

    def test_daily_passes_history_to_alert_checks(self, clean_thresholds, monkeypatch, tmp_path):
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
        monkeypatch.setattr(an, "LAST_VALUES_FILE", tmp_path / "last_values.json")
        monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")
        monkeypatch.setattr(dr, "get_us_eastern_date", lambda: "2026-09-03")
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
        monkeypatch.setattr(dr, "render_report_image", lambda *a, **k: None)
        monkeypatch.setattr(dr, "load_opening_refs", lambda d: [])
        captured = {}
        monkeypatch.setattr(dr, "run_alert_checks",
                            lambda *a, **k: captured.setdefault("args", a) or None)
        seed = {"date": "2026-09-02", "vix": 20.0}
        (tmp_path / "history.json").write_text(
            __import__("json").dumps([seed]), encoding="utf-8")
        dr.main()
        args = captured["args"]
        assert len(args) >= 6
        assert isinstance(args[5], list)
        # 内存 history 变量（L122 load_history 结果，天然不含当日）
        assert len(args[5]) == 1
        assert args[5][0]["date"] == "2026-09-02"
        assert "2026-09-03" not in {r["date"] for r in args[5]}
    def test_regression_no_history_dict_shape(self, clean_thresholds):
        # 不传 history → 与旧版逐位一致（固定阈值 + 新键显式标注）
        # VIX=25 落在 20~30「警惕」区间 → level=WARN（非 ALERT）
        breach = an.check_breach("VIX", 25, 20)
        assert breach == {
            "symbol": "VIX",
            "current": 25,
            "last": 20,
            "change": 25.0,
            "threshold": 20.0,
            "threshold_mode": "fixed",
            "dynamic_threshold": None,
            "level": "WARN",
            "state": "警惕",
            "suggestion": an.ALERT_SUGGESTIONS["警惕"],
        }

    def test_snapshot_passes_history(self, clean_thresholds, monkeypatch, tmp_path):
        monkeypatch.setattr(an, "HISTORY_FILE", tmp_path / "history.json")
        monkeypatch.setattr(an, "LAST_VALUES_FILE", tmp_path / "last_values.json")
        monkeypatch.setattr(dr, "get_us_eastern_date", lambda: "2026-09-03")  # 无关，snapshot 用市场日期
        monkeypatch.setattr(sr, "get_market_date", lambda market: "2026-09-03")
        monkeypatch.setattr(sr, "fetch_all", lambda *a, **k: ({"VIX": 21.0}, {}))
        monkeypatch.setattr(sr, "fetch_sector_heat", lambda *a, **k: ([], []))
        monkeypatch.setattr(sr, "build_statuses", lambda *a, **k: {"VIX": ("平静", "ok")})
        monkeypatch.setattr(sr, "render_snapshot", lambda *a, **k: "")
        monkeypatch.setattr(sr, "save_snapshot", lambda *a, **k: tmp_path / "snap.md")
        monkeypatch.setattr(sr, "auto_commit_push", lambda *a, **k: False)
        captured = {}
        monkeypatch.setattr(sr, "run_alert_checks",
                            lambda *a, **k: captured.setdefault("args", a) or None)
        seed = {"date": "2026-09-02", "vix": 20.0}
        (tmp_path / "history.json").write_text(
            __import__("json").dumps([seed]), encoding="utf-8")
        sr.main("a-share", "midday")
        args = captured["args"]
        assert len(args) >= 6
        assert isinstance(args[5], list)
        assert args[5] == an.load_history()  # 文件恒无当日 → 全部行原样传入


# --------------------------------------------------------------------------- #
# 回测：collect_triggers 窗口化 + 报告语义
# --------------------------------------------------------------------------- #
class TestBacktestDynamic:
    def _long_history(self, n=30):
        # 基准平稳（±0.01，收益 ~±0.05%）→ 动态阈值极小，不会误触发。
        # 早段跳变置于 rows[2]（候选 i=2/i=3，history[:i] 样本不足 → fixed）。
        # 末段跳变置于末行 rows[29]（候选 i=29，history[:29] 充足且窗口不含此跳变 → dynamic）。
        rows = []
        for i in range(1, n + 1):
            vix = 20.0 + (0.01 if i % 2 else -0.01)
            rows.append({"date": f"2026-02-{i:02d}", "vix": vix})
        rows[2]["vix"] = 26.0    # 早段触发（fixed）
        rows[29]["vix"] = 26.0   # 末段触发（dynamic，窗口 history[:29] 不含此跳变）
        return rows

    def test_collect_triggers_has_mode(self):
        hist = self._long_history()
        trigs = bt.collect_triggers(hist, ["VIX"])
        assert trigs
        assert all("threshold_mode" in t for t in trigs)
        modes = {t["threshold_mode"] for t in trigs}
        assert "fixed" in modes       # 早段（history[:i] 样本不足）回退
        assert "dynamic" in modes     # 晚段（样本充足）动态

    def test_report_contains_dynamic_section(self):
        hist = [{"date": "2026-09-01", "vix": 125.0}]
        triggers = [{"date": "2026-09-01", "symbol": "VIX", "change": 25.0,
                     "threshold": 30.0, "threshold_mode": "dynamic",
                     "level": "ALERT", "price": 125.0, "index": 1}]
        report = bt.render_report(hist, triggers, {}, "2026-09-03", 1)
        assert "动态阈值参数" in report
        assert "回退阈值" in report
        assert "dynamic 1 / fixed 0" in report
