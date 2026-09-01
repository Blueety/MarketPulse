"""配置加载层：config.json + 环境变量覆盖 + 内置默认。

优先级链：env > config.json > 内置默认。零新增依赖（标准库 json/os/logging/pathlib）。
config.json 缺失/损坏/类型非法 → 对应键回退默认，仅记日志，不崩溃（向后兼容）。
每次调用重新读文件；cron 每进程全新启动且只调几次，性能无虞（设计 F）。
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path

log = logging.getLogger("marketpulse")

# 内置默认值：与五期前的硬编码逐位一致（20/30/100/130、20/20/15、30、90）。
DEFAULTS = {
    "analysis": {
        "vix": {"peaceful": 20.0, "panic": 30.0},
        "move": {"normal": 100.0, "tight": 130.0},
    },
    "alert": {"vix": 20.0, "vxn": 20.0, "move": 12.0, "gspc": 2.5, "ixic": 3.5, "sh": 2.5, "sz": 3.5, "cyb": 5.0},
    "trend": {"chart_days": 30, "streak_days": 3},
    "history": {"retention_days": 90},
    # 二十四期：自选股/持仓（值为 list[dict]，白名单合并无法处理，由 _valid_watchlist 单独校验）
    "watchlist": {"stocks": [], "corr_high_threshold": 0.7},
}

# 环境变量名 → 配置路径（白名单；未知 env 忽略，不做动态键）。
ENV_MAP = {
    "ALERT_THRESHOLD_VIX": ("alert", "vix"),
    "ALERT_THRESHOLD_VXN": ("alert", "vxn"),
    "ALERT_THRESHOLD_MOVE": ("alert", "move"),
    "ALERT_THRESHOLD_GSPC": ("alert", "gspc"),
    "ALERT_THRESHOLD_IXIC": ("alert", "ixic"),
    "ALERT_THRESHOLD_SH": ("alert", "sh"),
    "ALERT_THRESHOLD_CYB": ("alert", "cyb"),
    "STATUS_THRESHOLD_VIX_CALM": ("analysis", "vix", "peaceful"),
    "STATUS_THRESHOLD_VIX_PANIC": ("analysis", "vix", "panic"),
    "STATUS_THRESHOLD_MOVE_CALM": ("analysis", "move", "normal"),
    "STATUS_THRESHOLD_MOVE_WARN": ("analysis", "move", "tight"),
    "TREND_CHART_DAYS": ("trend", "chart_days"),
    "TREND_STREAK_DAYS": ("trend", "streak_days"),
    "HISTORY_RETENTION_DAYS": ("history", "retention_days"),

}

# 项目根 config.json 默认位置（可用 CONFIG_PATH env 或 load_config(path=...) 覆盖）。
DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"


def env_float(name: str, default: float) -> float:
    """读取环境变量并解析为 float；缺失/非法/非正回退 default（仅记日志，不抛异常）。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if value <= 0:
        log.warning("环境变量 %s 非法或非正（%r），回退默认 %.1f", name, raw, default)
        return default
    return value


def _valid_number(value) -> bool:
    """叶值校验：非 bool 的数字且 >0（bool 是 int 子类，须显式排除，否则 JSON true 被当 1）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _resolve_path(path) -> Path:
    """路径解析：显式 path 参数 > CONFIG_PATH env > 项目根 config.json。"""
    if path is not None:
        return Path(path)
    env_path = os.environ.get("CONFIG_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_FILE


def _read_json(path: Path) -> dict | None:
    """读配置文件；缺失/损坏/根非 dict → None（调用方用默认值）。"""
    if not path.exists():
        log.warning("配置文件不存在 %s，使用内置默认值", path)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("配置文件读取失败 %s: %s，使用内置默认值", path, exc)
        return None
    if not isinstance(data, dict):
        log.warning("配置文件根不是对象 %s，使用内置默认值", path)
        return None
    log.info("配置文件已加载: %s", path)
    return data


def _merge_valid(base: dict, raw: dict, prefix: tuple = ()) -> dict:
    """白名单深合并：raw 未知键忽略；叶值须为非 bool 数字且 >0，否则回退 base（记日志）。"""
    out = dict(base)
    for key, base_val in base.items():
        # list 值（如 watchlist.stocks）白名单不合并，由专用校验器处理；跳过避免误报
        if isinstance(base_val, list):
            continue
        raw_val = raw.get(key)
        if isinstance(base_val, dict):
            if isinstance(raw_val, dict):
                out[key] = _merge_valid(base_val, raw_val, prefix + (key,))
            # 非 dict → 保持默认
        elif _valid_number(raw_val):
            out[key] = raw_val
        elif key in raw:
            log.warning("配置 %s 非法（%r），回退默认 %s",
                        ".".join(prefix + (key,)), raw_val, base_val)
    return out


def _valid_watchlist(raw) -> dict:
    """校验 watchlist 配置（值为 list[dict]，_merge_valid 无法处理，单独校验）。

    stocks ≤20 只；symbol 非空字符串、去重（重复丢弃记日志）；label 缺省回退 symbol；
    非法条目丢弃记日志；corr_high_threshold 走 _valid_number（须为正数字）。
    返回 {"stocks": [...], "corr_high_threshold": float}。
    """
    default = {"stocks": [], "corr_high_threshold": 0.7}
    if not isinstance(raw, dict):
        if raw is not None:
            log.warning("配置 watchlist 非法（%r），回退默认", raw)
        return dict(default)
    stocks = []
    seen = set()
    raw_stocks = raw.get("stocks")
    if isinstance(raw_stocks, list):
        for item in raw_stocks:
            if not isinstance(item, dict):
                log.warning("watchlist 条目非法（%r），丢弃", item)
                continue
            sym = item.get("symbol")
            if not isinstance(sym, str) or not sym.strip():
                log.warning("watchlist symbol 非法（%r），丢弃", item)
                continue
            sym = sym.strip()
            if sym in seen:
                log.warning("watchlist symbol 重复（%s），丢弃", sym)
                continue
            seen.add(sym)
            label = item.get("label")
            if not isinstance(label, str) or not label.strip():
                label = sym
            stocks.append({"symbol": sym, "label": label})
    if len(stocks) > 20:
        log.warning("watchlist 数量 %d 超过上限 20，截断至 20", len(stocks))
        stocks = stocks[:20]
    threshold = raw.get("corr_high_threshold")
    if _valid_number(threshold):
        corr_high_threshold = threshold
    else:
        if "corr_high_threshold" in raw:
            log.warning("watchlist.corr_high_threshold 非法（%r），回退默认 0.7", threshold)
        corr_high_threshold = 0.7
    return {"stocks": stocks, "corr_high_threshold": corr_high_threshold}
def load_config(path=None) -> dict:
    """加载完整配置：读文件（缺失/损坏/非 dict 降级默认）→ 白名单校验合并 → env 覆盖。"""
    cfg = copy.deepcopy(DEFAULTS)
    file_path = _resolve_path(path)
    raw = _read_json(file_path)
    if raw is not None:
        cfg = _merge_valid(cfg, raw)
    # watchlist 含 list[dict]，_merge_valid 无法校验，单独处理（不受白名单合并影响）
    cfg["watchlist"] = _valid_watchlist(raw.get("watchlist") if raw is not None else None)
    for env_name, keys in ENV_MAP.items():
        node = cfg
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = env_float(env_name, node[keys[-1]])
    return cfg
