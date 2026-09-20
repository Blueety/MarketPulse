"""src/settings_store.py 单测：白名单 / 校验 / 备份 / 原子写 / 深合并（不联网、不碰真实 config.json）。"""
import json

import pytest

from src import settings_store as ss


@pytest.fixture
def cfg_file(tmp_path):
    """临时 config.json（含一个用户自有键，验证"其它键原样保留"）。"""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({
        "alert": {"vix": 20.0, "k_factor": 2.0, "dynamic": True, "lookback_days": 20},
        "analysis": {"vix": {"peaceful": 20.0, "panic": 30.0},
                     "move": {"normal": 100.0, "tight": 130.0}},
        "watchlist": {"stocks": [{"symbol": "600519", "label": "贵州茅台"}],
                      "corr_high_threshold": 0.7},
        "user_own_key": {"keep": "me"},          # 用户自有键（白名单外，必须保留）
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---- 白名单 ----

def test_unknown_key_rejected(cfg_file):
    with pytest.raises(ss.SettingsError) as ei:
        ss.validate_updates({"trend.chart_days": 45}, cfg_file)
    assert "白名单" in str(ei.value)


def test_excluded_system_key_rejected(cfg_file):
    with pytest.raises(ss.SettingsError):
        ss.validate_updates({"history.retention_days": 30}, cfg_file)


def test_rejects_non_dict_body(cfg_file):
    with pytest.raises(ss.SettingsError):
        ss.validate_updates(["alert.vix", 25], cfg_file)


# ---- 单键校验 ----

def test_float_rules(cfg_file):
    with pytest.raises(ss.SettingsError) as ei:
        ss.validate_updates({"alert.vix": 0}, cfg_file)
    assert any("大于" in e for e in ei.value.errors)
    with pytest.raises(ss.SettingsError):
        ss.validate_updates({"alert.vix": "abc"}, cfg_file)


def test_int_rules(cfg_file):
    with pytest.raises(ss.SettingsError):
        ss.validate_updates({"alert.lookback_days": 3}, cfg_file)   # < min 5
    with pytest.raises(ss.SettingsError):
        ss.validate_updates({"alert.lookback_days": 20.5}, cfg_file)  # 不接受小数


def test_bool_rules(cfg_file):
    assert ss.validate_updates({"alert.dynamic": "true"}, cfg_file)["alert.dynamic"] is True
    assert ss.validate_updates({"alert.dynamic": 0}, cfg_file)["alert.dynamic"] is False
    with pytest.raises(ss.SettingsError):
        ss.validate_updates({"alert.dynamic": "yes"}, cfg_file)


# ---- 自选列表 ----

def test_stocks_dedupe_and_empty_label(cfg_file):
    with pytest.raises(ss.SettingsError) as ei:
        ss.validate_updates({"watchlist.stocks": [
            {"symbol": "600519", "label": "a"}, {"symbol": "600519", "label": "b"}]}, cfg_file)
    assert any("重复" in e for e in ei.value.errors)
    with pytest.raises(ss.SettingsError):
        ss.validate_updates({"watchlist.stocks": [{"symbol": "600519", "label": " "}]}, cfg_file)


def test_stocks_cap_matches_reader(cfg_file):
    """🔴 上限必须与 `src/config.py:_valid_watchlist` 的 20 一致 —— 不一致时写 25 条会被读侧静默截断。"""
    from src import config as cp
    assert ss.WATCHLIST_MAX == 20
    stocks = [{"symbol": "S%03d" % i, "label": "s%d" % i} for i in range(21)]
    with pytest.raises(ss.SettingsError):
        ss.validate_updates({"watchlist.stocks": stocks}, cfg_file)


# ---- 跨字段（合成结果上校验，部分更新也不许造出倒挂）----

def test_pair_rule_on_merged_result(cfg_file):
    # 单独把 peaceful 抬到 35（panic 保持 30）⇒ 倒挂，必须拒绝
    with pytest.raises(ss.SettingsError) as ei:
        ss.validate_updates({"analysis.vix.peaceful": 35}, cfg_file)
    assert any("低于" in e for e in ei.value.errors)
    # 两条一起改、保持正序 ⇒ 允许
    ok = ss.validate_updates({"analysis.vix.peaceful": 25, "analysis.vix.panic": 40}, cfg_file)
    assert ok["analysis.vix.peaceful"] == 25.0


# ---- 写入：备份 / 原子 / 深合并 ----

def test_apply_updates_writes_raw_and_keeps_user_keys(cfg_file):
    values = ss.apply_updates({"alert.vix": 25.0}, cfg_file)
    assert values["alert.vix"] == 25.0
    raw = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert raw["alert"]["vix"] == 25.0
    assert raw["user_own_key"] == {"keep": "me"}          # 用户自有键原样保留
    assert raw["alert"]["k_factor"] == 2.0                # 未动的键不丢
    assert "dynamic" not in raw["alert"] or raw["alert"]["dynamic"] is True
    # 🔴 内置默认**没有**被固化进用户文件（未在 patch 里、且原文件没有的键不出现）
    assert "gspc" not in raw["alert"]


def test_apply_creates_backup_and_prunes(cfg_file):
    for i in range(1, 8):
        ss.apply_updates({"alert.vix": 20.0 + i}, cfg_file)
    baks = sorted(cfg_file.parent.glob("config.json.bak-*"))
    assert 0 < len(baks) <= ss.BACKUP_KEEP


def test_no_backup_when_file_absent(tmp_path):
    p = tmp_path / "config.json"
    ss.apply_updates({"alert.vix": 22.0}, p)
    assert p.exists() and json.loads(p.read_text(encoding="utf-8"))["alert"]["vix"] == 22.0
    assert not list(p.parent.glob("config.json.bak-*"))


def test_corrupt_source_file_still_writable(tmp_path):
    """config.json 损坏 ⇒ 读侧容错为 {}，写侧只叠加本次改动（不固化默认）。"""
    p = tmp_path / "config.json"
    p.write_text("{ not json", encoding="utf-8")
    ss.apply_updates({"alert.vix": 23.0}, p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw == {"alert": {"vix": 23.0}}


def test_read_settings_reports_env_overrides(cfg_file, monkeypatch):
    monkeypatch.setenv("ALERT_THRESHOLD_VIX", "33")
    values, envs = ss.read_settings(cfg_file)
    assert values["alert.vix"] == 33.0          # 生效值 = env 覆盖后的结果
    assert envs.get("alert.vix") == "ALERT_THRESHOLD_VIX"
    assert "alert.gspc" not in envs             # 未被覆盖的键不标注


def test_readonly_only_when_railway(monkeypatch):
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    assert ss.is_readonly() is False
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    assert ss.is_readonly() is True
    assert "Railway" in (ss.readonly_reason() or "")
