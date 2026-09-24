"""五期阈值配置化测试：load_config / env 覆盖 / 接线（import 快照 + 调用时 env 复核）。

conftest.py 已强制 CONFIG_PATH 指向不存在文件，因此模块 import 时快照恒为内置默认；
本文件通过 load_config(path=tmp) 显式指定配置文件，避免依赖宿主环境。
"""
import importlib
import json
from pathlib import Path

import pytest

from src import analyzer as an
from src import config
from src import reporter as rep
from src.config import DEFAULTS, load_config

# 与 conftest 隔离路径保持一致，用于 reload 测试的 finally 恢复。
ISOLATED_CONFIG = str(Path(__file__).parent / "_nonexistent_config.json")


def _write(tmp_path: Path, obj: dict) -> Path:
    p = tmp_path / "config.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


class TestDefaults:
    """无配置文件时返回值与五期前硬编码逐位一致。"""
    def test_defaults_match_hardcoded(self, tmp_path):
        cfg = load_config(path=tmp_path / "nope.json")
        assert cfg["analysis"]["vix"]["peaceful"] == 20.0
        assert cfg["analysis"]["vix"]["panic"] == 30.0
        assert cfg["analysis"]["move"]["normal"] == 100.0
        assert cfg["analysis"]["move"]["tight"] == 130.0
        assert cfg["alert"]["vix"] == 20.0
        assert cfg["alert"]["vxn"] == 20.0
        assert cfg["alert"]["move"] == 12.0
        assert cfg["alert"]["vix"] == 20.0
        assert cfg["alert"]["cyb"] == 5.0
        assert cfg["history"]["retention_days"] == 90

    def test_defaults_is_deepcopy(self, tmp_path):
        cfg = load_config(path=tmp_path / "nope.json")
        cfg["alert"]["vix"] = 999
        # 不应污染模块级 DEFAULTS
        assert DEFAULTS["alert"]["vix"] == 20.0


class TestLoadFile:
    """合法配置文件生效；部分键深合并补默认。"""
    def test_full_override(self, tmp_path):
        cfg = {
            "analysis": {"vix": {"peaceful": 22, "panic": 35}},
            "alert": {"vix": 25},
            "trend": {"chart_days": 45},
            "history": {"retention_days": 120},
        }
        p = _write(tmp_path, cfg)
        loaded = load_config(path=p)
        assert loaded["analysis"]["vix"]["peaceful"] == 22.0
        assert loaded["analysis"]["vix"]["panic"] == 35.0
        assert loaded["alert"]["vix"] == 25.0
        assert loaded["trend"]["chart_days"] == 45
        assert loaded["history"]["retention_days"] == 120
        # 未提供的键保持默认
        assert loaded["analysis"]["move"]["normal"] == 100.0
        assert loaded["alert"]["vxn"] == 20.0

    def test_partial_keys_deep_merge(self, tmp_path):
        cfg = {"alert": {"vix": 22}}  # 仅 alert 段
        p = _write(tmp_path, cfg)
        loaded = load_config(path=p)
        assert loaded["alert"]["vix"] == 22.0
        assert loaded["analysis"]["vix"]["peaceful"] == 20.0  # 默认
        assert loaded["trend"]["chart_days"] == 30


class TestInvalidFile:
    """损坏/非 dict 根/不可读 → 默认 + 不抛异常。"""
    def test_corrupted_json(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text("{not json", encoding="utf-8")
        assert load_config(path=p)["alert"]["vix"] == 20.0

    def test_non_dict_root(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        assert load_config(path=p)["alert"]["vix"] == 20.0

    def test_unreadable_path_is_dir(self, tmp_path):
        # 指向目录：read_text 抛 OSError → None → 默认
        assert load_config(path=tmp_path)["alert"]["vix"] == 20.0


class TestTypeValidation:
    """叶值须为非 bool 的数字且 >0，否则回退默认。"""
    def test_string_rejected(self, tmp_path):
        p = _write(tmp_path, {"alert": {"vix": "high"}})
        assert load_config(path=p)["alert"]["vix"] == 20.0

    def test_bool_rejected(self, tmp_path):
        p = _write(tmp_path, {"alert": {"vix": True}})
        # bool 是 int 子类，必须排除（JSON true 不可被当 1）
        assert load_config(path=p)["alert"]["vix"] == 20.0

    def test_zero_rejected(self, tmp_path):
        p = _write(tmp_path, {"alert": {"vix": 0}})
        assert load_config(path=p)["alert"]["vix"] == 20.0

    def test_negative_rejected(self, tmp_path):
        p = _write(tmp_path, {"alert": {"vix": -5}})
        assert load_config(path=p)["alert"]["vix"] == 20.0

    def test_int_accepted(self, tmp_path):
        p = _write(tmp_path, {"alert": {"vix": 15}})
        assert load_config(path=p)["alert"]["vix"] == 15.0

    def test_unknown_keys_ignored(self, tmp_path):
        p = _write(tmp_path, {"future": {"unknown": 7}})
        loaded = load_config(path=p)
        assert "future" not in loaded
        assert loaded["alert"]["vix"] == 20.0


class TestEnvOverride:
    """优先级链：env > config.json > 内置默认。"""
    def test_env_over_file(self, tmp_path, monkeypatch):
        p = _write(tmp_path, {"alert": {"vix": 22}})
        monkeypatch.setenv("ALERT_THRESHOLD_VIX", "25")
        assert load_config(path=p)["alert"]["vix"] == 25.0  # env(25) > file(22) > default(20)

    def test_file_over_default(self, tmp_path):
        p = _write(tmp_path, {"alert": {"vix": 22}})
        assert load_config(path=p)["alert"]["vix"] == 22.0  # file > default

    def test_default_when_no_file_or_env(self, tmp_path):
        assert load_config(path=tmp_path / "missing.json")["alert"]["vix"] == 20.0

    def test_env_invalid_keeps_file(self, tmp_path, monkeypatch):
        p = _write(tmp_path, {"alert": {"vix": 22}})
        monkeypatch.setenv("ALERT_THRESHOLD_VIX", "abc")
        assert load_config(path=p)["alert"]["vix"] == 22.0  # 非法 env → 保留文件值

    def test_env_white_list_only(self, tmp_path, monkeypatch):
        p = _write(tmp_path, {"alert": {"vix": 22}})
        monkeypatch.setenv("ALERT_THRESHOLD_RANDOM", "99")  # 未知 env 忽略
        assert load_config(path=p)["alert"]["vix"] == 22.0


class TestConfigPath:
    """路径解析：显式 path= > CONFIG_PATH env > 项目根默认。"""
    def test_explicit_path_over_env(self, tmp_path, monkeypatch):
        env_p = _write(tmp_path, {"alert": {"vix": 1}})
        monkeypatch.setenv("CONFIG_PATH", str(env_p))
        exp_p = _write(tmp_path, {"alert": {"vix": 2}})
        assert load_config(path=exp_p)["alert"]["vix"] == 2.0  # 显式优先

    def test_env_over_root_default(self, tmp_path, monkeypatch):
        env_p = _write(tmp_path, {"alert": {"vix": 3}})
        monkeypatch.setenv("CONFIG_PATH", str(env_p))
        assert load_config()["alert"]["vix"] == 3.0  # 无 path 参数 → 用 CONFIG_PATH


class TestWiring:
    """配置 → 模块常量接线（设计 A/G）。"""
    def test_hermetic_defaults(self):
        # 隔离下 import 快照必须等于内置默认
        assert an.VIX_CALM == 20.0
        assert an.VIX_WARN == 30.0
        assert an.MOVE_CALM == 100.0
        assert an.MOVE_WARN == 130.0
        assert an.HISTORY_MAX == 90
        assert rep.TREND_DAYS == 30
        assert an.ALERT_THRESHOLDS["VIX"] == 20.0
        assert an.ALERT_THRESHOLDS["VXN"] == 20.0
        assert an.ALERT_THRESHOLDS["MOVE"] == 12.0

    def test_reload_updates_constants(self, monkeypatch, tmp_path):
        cfg = {
            "analysis": {"vix": {"peaceful": 22, "panic": 35}, "move": {"normal": 105, "tight": 135}},
            "alert": {"vix": 25, "vxn": 25, "move": 18},
            "trend": {"chart_days": 45},
            "history": {"retention_days": 120},
        }
        p = _write(tmp_path, cfg)
        monkeypatch.setenv("CONFIG_PATH", str(p))
        importlib.reload(an)
        importlib.reload(rep)
        try:
            assert an.VIX_CALM == 22.0
            assert an.VIX_WARN == 35.0
            assert an.MOVE_CALM == 105.0
            assert an.MOVE_WARN == 135.0
            assert an.HISTORY_MAX == 120
            assert rep.TREND_DAYS == 45
            assert an.ALERT_THRESHOLDS["VIX"] == 25.0
            assert an.ALERT_THRESHOLDS["VXN"] == 25.0
            assert an.ALERT_THRESHOLDS["MOVE"] == 18.0
        finally:
            # 恢复 import 快照为内置默认，避免污染后续用例
            monkeypatch.setenv("CONFIG_PATH", ISOLATED_CONFIG)
            importlib.reload(an)
            importlib.reload(rep)


class TestStatusEnv:
    """classify 调用时经 STATUS_THRESHOLD_* env 复核（设计 A）。"""
    def test_vix_calm_env(self, monkeypatch):
        monkeypatch.setenv("STATUS_THRESHOLD_VIX_CALM", "22")
        assert an.classify_vix(21.0)[0] == "平静"   # 21 < 22
        assert an.classify_vix(23.0)[0] == "警惕"   # 22 < 23 < 30

    def test_vix_calm_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("STATUS_THRESHOLD_VIX_CALM", "not_a_number")
        # 非法 → 回退默认 20 → 21 判警惕
        assert an.classify_vix(21.0)[0] == "警惕"

    def test_move_warn_env(self, monkeypatch):
        monkeypatch.setenv("STATUS_THRESHOLD_MOVE_WARN", "135")
        assert an.classify_move(134.0)[0] == "警惕"
        assert an.classify_move(136.0)[0] == "恐慌"


class TestTrendHistoryEnv:
    """TREND_DAYS / HISTORY_MAX 为 import 快照，env 覆盖需 reload（设计 A/F）。"""
    def test_trend_days_env(self, monkeypatch):
        monkeypatch.setenv("TREND_CHART_DAYS", "45")
        importlib.reload(rep)
        try:
            assert rep.TREND_DAYS == 45
        finally:
            monkeypatch.delenv("TREND_CHART_DAYS", raising=False)
            importlib.reload(rep)

    def test_history_max_env(self, monkeypatch):
        monkeypatch.setenv("HISTORY_RETENTION_DAYS", "120")
        importlib.reload(an)
        try:
            assert an.HISTORY_MAX == 120
        finally:
            monkeypatch.delenv("HISTORY_RETENTION_DAYS", raising=False)
            importlib.reload(an)


class TestWatchlistValidation:
    def test_default_when_no_file(self, tmp_path):
        cfg = load_config(path=tmp_path / "nope.json")
        assert cfg["watchlist"] == {"stocks": [], "corr_high_threshold": 0.7}

    def test_valid_file(self, tmp_path):
        p = _write(tmp_path, {"watchlist": {"stocks": [
            {"symbol": "AAPL", "label": "苹果"}, {"symbol": "600519.SS"}],
            "corr_high_threshold": 0.8}})
        cfg = load_config(path=p)
        assert cfg["watchlist"]["corr_high_threshold"] == 0.8
        assert cfg["watchlist"]["stocks"][0] == {"symbol": "AAPL", "label": "苹果"}
        assert cfg["watchlist"]["stocks"][1] == {"symbol": "600519.SS", "label": "600519.SS"}

    def test_truncate_to_20(self, tmp_path):
        p = _write(tmp_path, {"watchlist": {"stocks": [{"symbol": f"S{i}"} for i in range(25)]}})
        cfg = load_config(path=p)
        assert len(cfg["watchlist"]["stocks"]) == 20

    def test_dedup_symbols(self, tmp_path):
        p = _write(tmp_path, {"watchlist": {"stocks": [
            {"symbol": "AAPL"}, {"symbol": "AAPL"}, {"symbol": "AAPL"}]}})
        cfg = load_config(path=p)
        assert len(cfg["watchlist"]["stocks"]) == 1

    def test_drop_illegal_entry(self, tmp_path):
        p = _write(tmp_path, {"watchlist": {"stocks": [
            {"symbol": "AAPL"}, "notadict", {"symbol": ""}, {"label": "nolabel"}]}})
        cfg = load_config(path=p)
        assert cfg["watchlist"]["stocks"] == [{"symbol": "AAPL", "label": "AAPL"}]

    def test_threshold_invalid_fallback(self, tmp_path):
        p = _write(tmp_path, {"watchlist": {"stocks": [{"symbol": "AAPL"}],
                                            "corr_high_threshold": -1}})
        cfg = load_config(path=p)
        assert cfg["watchlist"]["corr_high_threshold"] == 0.7

    def test_threshold_valid(self, tmp_path):
        p = _write(tmp_path, {"watchlist": {"stocks": [{"symbol": "AAPL"}],
                                            "corr_high_threshold": 0.5}})
        cfg = load_config(path=p)
        assert cfg["watchlist"]["corr_high_threshold"] == 0.5

    def test_watchlist_non_dict(self, tmp_path):
        p = _write(tmp_path, {"watchlist": "bad"})
        cfg = load_config(path=p)
        assert cfg["watchlist"] == {"stocks": [], "corr_high_threshold": 0.7}

    # ---- BUG-002（2026-09-24）：读侧必须透传 cost（旧实现重建条目时只留 symbol/label）----

    def test_valid_cost_passed_through(self, tmp_path):
        p = _write(tmp_path, {"watchlist": {"stocks": [
            {"symbol": "600519", "label": "茅台", "cost": 1500.0},
            {"symbol": "AAPL", "label": "苹果"}]}})
        cfg = load_config(path=p)
        assert cfg["watchlist"]["stocks"][0] == {"symbol": "600519", "label": "茅台", "cost": 1500.0}
        assert "cost" not in cfg["watchlist"]["stocks"][1]      # 没给就不造键（不是 None）

    def test_illegal_cost_dropped_not_crashed(self, tmp_path):
        """非法 cost（≤0 / 非有限 / 非数字）⇒ **丢该键**、条目保留（读侧宽容，写侧才报错）。"""
        p = _write(tmp_path, {"watchlist": {"stocks": [
            {"symbol": "A", "cost": 0},
            {"symbol": "B", "cost": -1},
            {"symbol": "C", "cost": float("inf")},
            {"symbol": "D", "cost": "abc"},
            {"symbol": "E", "cost": None},
            {"symbol": "F", "cost": ""}]}})
        stocks = load_config(path=p)["watchlist"]["stocks"]
        assert [s["symbol"] for s in stocks] == ["A", "B", "C", "D", "E", "F"]
        assert all("cost" not in s for s in stocks)

    def test_cost_string_number_accepted(self, tmp_path):
        p = _write(tmp_path, {"watchlist": {"stocks": [{"symbol": "A", "cost": "12.5"}]}})
        assert load_config(path=p)["watchlist"]["stocks"][0]["cost"] == 12.5


class TestNonFiniteReadSide:
    """BUG-003 读侧（2026-09-24）：历史遗留的 `Infinity` 阈值必须回退内置默认，不能进报警链。

    `json.loads` 默认接受 `Infinity/NaN`（Python 扩展），旧写侧会把它落盘 ⇒ 读侧必须挡。
    """

    def test_infinite_threshold_falls_back_to_default(self, tmp_path):
        p = _write(tmp_path, {"alert": {"vix": float("inf"), "sh": float("nan"), "gspc": 3.0}})
        cfg = load_config(path=p)
        assert cfg["alert"]["vix"] == DEFAULTS["alert"]["vix"]     # ∞ → 默认 20
        assert cfg["alert"]["sh"] == DEFAULTS["alert"]["sh"]       # NaN → 默认 2.5
        assert cfg["alert"]["gspc"] == 3.0                         # 正常值不受影响

    def test_infinite_analysis_and_k_factor_fall_back(self, tmp_path):
        p = _write(tmp_path, {"analysis": {"vix": {"peaceful": float("inf"), "panic": 30.0}},
                              "alert": {"k_factor": 1e999}})
        cfg = load_config(path=p)
        assert cfg["analysis"]["vix"]["peaceful"] == 20.0
        assert cfg["alert"]["k_factor"] == 2.0

    def test_env_float_rejects_non_finite(self, monkeypatch):
        """env 侧同一道闸：`ALERT_THRESHOLD_VIX=inf` 不得进报警链（否则告警静默关闭）。"""
        monkeypatch.setenv("ALERT_THRESHOLD_VIX", "inf")
        assert config.env_float("ALERT_THRESHOLD_VIX", 20.0) == 20.0
        monkeypatch.setenv("ALERT_THRESHOLD_VIX", "nan")
        assert config.env_float("ALERT_THRESHOLD_VIX", 20.0) == 20.0
        monkeypatch.setenv("ALERT_THRESHOLD_VIX", "25")
        assert config.env_float("ALERT_THRESHOLD_VIX", 20.0) == 25.0

    def test_bad_bytes_config_falls_back_to_defaults(self, tmp_path):
        """BUG-007 同类（读侧）：非 UTF-8 字节 ⇒ 内置默认，**绝不抛异常**（否则四 API + 三入口同挂）。"""
        p = tmp_path / "config.json"
        p.write_bytes(b'{"alert": {"vix": 25.0}}\xff\xfe')
        cfg = load_config(path=p)
        assert cfg["alert"]["vix"] == DEFAULTS["alert"]["vix"]


class TestAlertThresholdEnvCoverage:
    """BUG-010（2026-09-24）：`settings_store.SCHEMA` 的**8 个标的阈值**都要有 env 覆盖。

    旧实现漏了 `ALERT_THRESHOLD_SZ`（SCHEMA 能改、env 改不动，文档却宣称 `ALERT_THRESHOLD_*`
    通用覆盖）⇒ 用**参数化**把 `DEFAULTS.alert` / `SCHEMA` / `ENV_MAP` 三处钉在一起，防再漏项。
    ⚠️ `alert.k_factor` / `lookback_days` / `dynamic` **有意不给 env**（设置页专属；本用例断言
    的集合刻意不含它们——若将来补 env，请连同这张清单一起改）。
    """

    SYMBOL_KEYS = ["vix", "vxn", "move", "gspc", "ixic", "sh", "sz", "cyb"]

    @staticmethod
    def _float_alert_keys():
        from src import settings_store as ss

        return sorted(k[len("alert."):] for k, spec in ss.SCHEMA.items()
                      if k.startswith("alert.") and spec["kind"] == "float")

    def test_all_symbol_thresholds_have_defaults_schema_and_env(self):
        from src import settings_store as ss

        keys = self._float_alert_keys()
        assert set(keys) == set(self.SYMBOL_KEYS) | {"k_factor"}
        env_paths = set(config.ENV_MAP.values())
        missing = [k for k in self.SYMBOL_KEYS if ("alert", k) not in env_paths]
        assert not missing, "缺 env 映射: %s" % missing
        # 三个来源必须同源（默认值 / 设置页白名单 / env 映射）
        for k in self.SYMBOL_KEYS:
            assert k in DEFAULTS["alert"] and ("alert." + k) in ss.SCHEMA

    def test_sz_env_takes_effect(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ALERT_THRESHOLD_SZ", "9")
        assert load_config(path=tmp_path / "nope.json")["alert"]["sz"] == 9.0

    @pytest.mark.parametrize("key", ["vix", "vxn", "move", "gspc", "ixic", "sh", "sz", "cyb"])
    def test_each_threshold_env_overrides(self, key, monkeypatch, tmp_path):
        by_path = {path: name for name, path in config.ENV_MAP.items()}
        monkeypatch.setenv(by_path[("alert", key)], "7.5")
        assert load_config(path=tmp_path / "nope.json")["alert"][key] == 7.5
