"""scripts/backtest.py 单元测试：触发检测 / 前向收益 / 胜率 / 有效触发率 / 门槛退出。"""
import json

import pytest

from scripts import backtest as bt


@pytest.fixture(autouse=True)
def _isolate_thresholds(monkeypatch):
    # 隔离宿主 ALERT_THRESHOLD_* env，确保使用内置默认阈值（与 conftest 默认配置一致）。
    for sym in bt.BACKTEST_SYMBOLS:
        monkeypatch.delenv(f"ALERT_THRESHOLD_{sym}", raising=False)


def _hist(rows):
    """rows: list of (date, {小写符号键: value})。"""
    return [{"date": d, **vals} for d, vals in rows]

def test_collect_triggers_strict_greater():
    # VIX 默认阈值 20%：等于不触发、严格大于触发（相邻日比较，复用生产 check_breach 语义）。
    hist = _hist([
        ("2026-01-01", {"vix": 100}),
        ("2026-01-02", {"vix": 120}),  # i=1: vs 100 = +20% == 阈值 -> 不触发
        ("2026-01-03", {"vix": 145.2}),  # i=2: vs 120 = +21% > 阈值 -> 触发
    ])
    trig = bt.collect_triggers(hist, ["VIX"])
    assert len(trig) == 1
    assert trig[0]["date"] == "2026-01-03"
    assert trig[0]["change"] == pytest.approx(21.0)

def test_equal_not_triggered():
    hist = _hist([("2026-01-01", {"vix": 100}), ("2026-01-02", {"vix": 120})])
    assert bt.collect_triggers(hist, ["VIX"]) == []


def test_gap_breaks_chain():
    # 缺口（None）断开：缺口两侧不产生跨缺口触发。
    hist = _hist([
        ("d1", {"vix": 100}),
        ("d2", {"vix": 200}),  # +100% 触发
        ("d3", {"vix": None}),  # 缺口
        ("d4", {"vix": 100}),  # prev 缺口 -> 不触发
    ])
    trig = bt.collect_triggers(hist, ["VIX"])
    assert len(trig) == 1
    assert trig[0]["date"] == "d2"


def test_trigger_fields():
    hist = _hist([("d1", {"vix": 100}), ("d2", {"vix": 130})])
    trig = bt.collect_triggers(hist, ["VIX"])
    assert set(trig[0].keys()) >= {"date", "symbol", "change", "threshold", "level", "price", "index"}


def test_forward_stats():
    # 单触发（i=1, price 130），后效窗口全部可算；变化为正、前向收益均为正 -> 胜率 1.0。
    prices = [100, 130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 260, 280]
    hist = _hist([(f"2026-01-{i + 1:02d}", {"vix": p}) for i, p in enumerate(prices)])
    trig = bt.collect_triggers(hist, ["VIX"])
    assert len(trig) == 1
    fwd = bt.forward_stats(trig, hist)
    s = fwd["VIX"]
    assert s[1]["avg"] == pytest.approx(100 * (140 - 130) / 130)
    assert s[1]["win"] == 1.0
    assert s[1]["n"] == 1
    assert s[3]["avg"] == pytest.approx(100 * (160 - 130) / 130)
    assert s[5]["avg"] == pytest.approx(100 * (180 - 130) / 130)
    assert s[10]["avg"] == pytest.approx(100 * (260 - 130) / 130)
    assert s[10]["win"] == 1.0
    assert s[10]["n"] == 1


def test_forward_window_insufficient():
    # 序列过短：h=10 超出范围 -> n=0、avg/win 为 None；h=1/3/5 仍可算。
    prices = [100, 130, 140, 150, 160, 170, 180]
    hist = _hist([(f"2026-02-{i + 1:02d}", {"vix": p}) for i, p in enumerate(prices)])
    trig = bt.collect_triggers(hist, ["VIX"])
    fwd = bt.forward_stats(trig, hist)
    s = fwd["VIX"]
    assert s[10]["n"] == 0
    assert s[10]["avg"] is None
    assert s[10]["win"] is None
    assert s[1]["n"] == 1


def test_win_rate():
    # 两个触发：i=1 后向反转（负收益）、i=5 后向延续（正收益）-> 胜率 0.5。
    prices = [100, 200, 190, 180, 170, 340, 350, 360, 370, 380, 390, 400, 410, 420, 430, 440]
    hist = _hist([(f"2026-03-{i + 1:02d}", {"vix": p}) for i, p in enumerate(prices)])
    trig = bt.collect_triggers(hist, ["VIX"])
    assert len(trig) == 2
    fwd = bt.forward_stats(trig, hist)
    assert fwd["VIX"][1]["n"] == 2
    assert fwd["VIX"][1]["win"] == pytest.approx(0.5)


def test_effective_trigger_rate():
    # i=1 后 5 日全平（无 >=1% 日）-> 非有效；i=10 后第 1 日 +1% -> 有效；rate=0.5。
    prices = [100, 200] + [200] * 8 + [400, 404, 404, 404, 404, 404]
    hist = _hist([(f"2026-04-{i + 1:02d}", {"vix": p}) for i, p in enumerate(prices)])
    trig = bt.collect_triggers(hist, ["VIX"])
    assert len(trig) == 2
    rate = bt.effective_trigger_rate(trig, hist)
    assert rate == pytest.approx(0.5)
    assert bt.effective_trigger_rate([], hist) is None


def test_annualized_frequency():
    # 11 天（Jan01~Jan11）；首个有效点（相邻可算行）在 Jan02、末个在 Jan11 -> 跨度 9 天。
    # SH 仅 1 次触发（i=5, +4.63% > 4% 阈值）-> 1/9*365。
    dates = [f"2026-01-{d:02d}" for d in range(1, 12)]
    sh = [100, 102, 104, 106, 108, 113, 115, 117, 119, 121, 123]
    hist = _hist([(d, {"sh": v}) for d, v in zip(dates, sh)])
    trig = bt.collect_triggers(hist, ["SH"])
    assert len(trig) == 1
    assert bt.annualized_frequency(trig, hist, "SH") == pytest.approx(1 / 9 * 365)


def test_insufficient_data_exit(tmp_path, monkeypatch):
    # 有效交易日 < 30 -> 优雅退出（退出码 0、无报告、不写任何数据文件）。
    monkeypatch.setattr(bt, "REPORTS_DIR", tmp_path)
    data = [{"date": f"2026-05-{d:02d}", "vix": 100.0 + d} for d in range(1, 11)]
    hist_file = tmp_path / "small_history.json"
    hist_file.write_text(json.dumps(data), encoding="utf-8")
    rc = bt.main(["--history", str(hist_file)])
    assert rc == 0
    assert not (tmp_path / "backtest_report.md").exists()
