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
        assert cfg["alert"]["move"] == 15.0
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
        assert an.ALERT_THRESHOLDS["MOVE"] == 15.0

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
