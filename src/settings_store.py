"""设置页的配置读写：白名单 schema / 校验 / 备份 / 原子写（2026-09-20，settings-page）。

**为什么单独一个模块**：web 层首次获得「有限写」权限（写 `config.json`），写路径必须
**收敛成一个入口**并走与读取侧同构的白名单 —— 否则任何键都能被前端写进配置文件。

三条铁律（plan §3.3 / R7）：
1. 🔴 **写的是用户原文件（raw），不是 `load_config()` 的返回值** —— 那是三级合并后的结果，
   写回会把内置默认固化进用户文件。
2. **写前备份 + 原子写**（tmp + `os.replace`）；备份滚动保留 5 份（`config.json.bak-<时间戳>`）。
3. **校验复用项目自己的三级链**：把「原文件 + 本次改动」写进临时文件，调 `load_config(tmp)`
   走真实白名单/env 链路，再对合成结果做跨字段校验（如 peaceful < panic）—— 不自己重写解析。
"""

from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

from src.config import DEFAULTS, ENV_MAP, load_config

#: 备份保留份数（滚动；D-2）
BACKUP_KEEP = 5
#: 自选条目上限（**与 `src/config.py:_valid_watchlist` 的 20 一致** —— 写 25 条会被读侧静默截断，
#: 那比报错更骗人。plan 写的 30 是笔误，journal 已记录）。
WATCHLIST_MAX = 20

# ⚠️ 备份名按 **config 文件自己的名字**派生（不硬编码 "config.json"）——
#   否则多环境/测试用不同文件名时备份会写错名、甚至互相覆盖（人工闭环实测抓到）。
def _backup_prefix(path: Path) -> str:
    return path.name + ".bak-"



class SettingsError(Exception):
    """校验失败（携带逐条错误信息）。"""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


# ---------------------------------------------------------------- schema（白名单与规则）
# 顺序即 UI 呈现顺序：动态三参数置顶（plan §0-4：固定阈值在动态模式下只是回退基准）。
SCHEMA: dict[str, dict] = {
    "alert.dynamic":        {"kind": "bool",  "label": "动态阈值开关"},
    "alert.lookback_days":  {"kind": "int",   "label": "动态阈值回看窗口（交易日）", "min": 5, "max": 250},
    "alert.k_factor":       {"kind": "float", "label": "动态阈值 k 因子", "gt": 0.0},
    "alert.vix":  {"kind": "float", "label": "VIX 告警阈值（%）—— 动态模式的回退基准", "gt": 0.0},
    "alert.vxn":  {"kind": "float", "label": "VXN 告警阈值（%）—— 动态模式的回退基准", "gt": 0.0},
    "alert.move": {"kind": "float", "label": "MOVE 告警阈值（%）—— 动态模式的回退基准", "gt": 0.0},
    "alert.gspc": {"kind": "float", "label": "标普500 告警阈值（%）—— 动态模式的回退基准", "gt": 0.0},
    "alert.ixic": {"kind": "float", "label": "纳斯达克 告警阈值（%）—— 动态模式的回退基准", "gt": 0.0},
    "alert.sh":   {"kind": "float", "label": "上证 告警阈值（%）—— 动态模式的回退基准", "gt": 0.0},
    "alert.sz":   {"kind": "float", "label": "深证 告警阈值（%）—— 动态模式的回退基准", "gt": 0.0},
    "alert.cyb":  {"kind": "float", "label": "创业板 告警阈值（%）—— 动态模式的回退基准", "gt": 0.0},
    "analysis.vix.peaceful":  {"kind": "float", "label": "VIX 平静线", "gt": 0.0},
    "analysis.vix.panic":     {"kind": "float", "label": "VIX 恐慌线", "gt": 0.0},
    "analysis.move.normal":   {"kind": "float", "label": "MOVE 正常线", "gt": 0.0},
    "analysis.move.tight":    {"kind": "float", "label": "MOVE 紧张线", "gt": 0.0},
    "watchlist.corr_high_threshold": {"kind": "float", "label": "自选相关性高阈值（0~1）", "min": 0.0, "max": 1.0},
    "watchlist.stocks": {"kind": "stocks", "label": "自选列表（symbol/label）"},
}

#: 跨字段规则（在「原文件 + 本次改动」的**合成结果**上校验，部分更新也不允许造出倒挂）
PAIR_RULES = (
    ("analysis.vix.peaceful", "analysis.vix.panic", "VIX 平静线必须低于恐慌线"),
    ("analysis.move.normal", "analysis.move.tight", "MOVE 正常线必须低于紧张线"),
)

#: 不给 UI 的系统键（写进来直接拒，防止误改数据链）
EXCLUDED = ("trend.chart_days", "trend.streak_days", "history.retention_days")


def _config_file(config_path: Path | str | None = None) -> Path:
    """config.json 位置（默认走 `CONFIG_PATH` env → 项目根；与 `src/config.py` 同口径）。"""
    if config_path is not None:
        return Path(config_path)
    env = os.environ.get("CONFIG_PATH")
    if env:
        return Path(env)
    base = Path(__file__).resolve().parent.parent
    return base / "config.json"


def is_readonly() -> bool:
    """Railway 等临时文件系统上只读（**默认安全侧**：只在明确检测到 Railway 才只读）。"""
    return bool(os.environ.get("RAILWAY_ENVIRONMENT"))


def readonly_reason() -> str | None:
    return ("线上环境（Railway 临时文件系统）为只读展示；本地修改 config.json 重启即丢，"
            "线上持久化需迁移到数据库（独立任务）。") if is_readonly() else None


def _env_for_path(dotted: str) -> str | None:
    """dotted path → 覆盖它的 env 变量名（从 config.ENV_MAP 反查）。"""
    parts = tuple(dotted.split("."))
    for name, keys in ENV_MAP.items():
        if keys == parts:
            return name
    return None


def read_settings(config_path: Path | str | None = None) -> tuple[dict, dict]:
    """当前生效值（三级链合并后的结果，只取白名单键）+ 被.env 覆盖的键标注。"""
    cfg = load_config(None if config_path is None else Path(config_path))
    values: dict[str, object] = {}
    for dotted in SCHEMA:
        node: object = cfg
        ok = True
        for k in dotted.split("."):
            if not isinstance(node, dict) or k not in node:
                ok = False
                break
            node = node[k]
        values[dotted] = node if ok else _default_for(dotted)
    env_overrides = {d: name for d, name in ((d, _env_for_path(d)) for d in SCHEMA)
                     if name and os.environ.get(name)}
    return values, env_overrides


def _default_for(dotted: str):
    node: object = DEFAULTS
    for k in dotted.split("."):
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def _read_raw(path: Path) -> dict:
    """读用户原文件（**只读不改**）；缺失/损坏 → `{}`（写侧只叠加本次改动，不固化默认）。"""
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _validate_one(dotted: str, value) -> object:
    """单键校验，返回规范化后的值；非法 raise ValueError（文案进 errors）。"""
    spec = SCHEMA.get(dotted)
    if spec is None:
        raise ValueError("%s 不在可写白名单内" % dotted)
    kind = spec["kind"]
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
        raise ValueError("%s 需为布尔值（true/false）" % dotted)
    if kind == "int":
        try:
            iv = int(value)
        except (TypeError, ValueError):
            raise ValueError("%s 需为整数" % dotted) from None
        if str(iv) != str(value).strip() and not isinstance(value, int):
            raise ValueError("%s 需为整数（不接受小数）" % dotted)
        lo, hi = spec.get("min"), spec.get("max")
        if (lo is not None and iv < lo) or (hi is not None and iv > hi):
            raise ValueError("%s 需在 %s ~ %s 之间" % (dotted, lo, hi))
        return iv
    if kind == "stocks":
        return _validate_stocks(value, dotted)
    # float
    try:
        fv = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s 需为数字" % dotted) from None
    if "gt" in spec and not fv > spec["gt"]:
        raise ValueError("%s 需大于 %s" % (dotted, spec["gt"]))
    if "min" in spec and fv < spec["min"]:
        raise ValueError("%s 不能小于 %s" % (dotted, spec["min"]))
    if "max" in spec and fv > spec["max"]:
        raise ValueError("%s 不能大于 %s" % (dotted, spec["max"]))
    return fv


def _validate_stocks(value, dotted: str) -> list[dict]:
    """自选列表：两项均非空、按 symbol 去重（大小写不敏感）、≤ WATCHLIST_MAX。"""
    if not isinstance(value, list):
        raise ValueError("%s 需为数组" % dotted)
    if len(value) > WATCHLIST_MAX:
        raise ValueError("%s 最多 %d 条（收到 %d）" % (dotted, WATCHLIST_MAX, len(value)))
    out: list[dict] = []
    seen: set[str] = set()
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("%s 第 %d 项需为对象（symbol/label）" % (dotted, i + 1))
        sym = str(item.get("symbol", "") or "").strip()
        label = str(item.get("label", "") or "").strip()
        if not sym or not label:
            raise ValueError("%s 第 %d 项的 symbol 与 label 均不能为空" % (dotted, i + 1))
        key = sym.upper()
        if key in seen:
            raise ValueError("%s 第 %d 项 symbol 重复（%s）" % (dotted, i + 1, sym))
        seen.add(key)
        out.append({"symbol": sym, "label": label})
    return out


def validate_updates(patch: dict, config_path: Path | str | None = None) -> dict:
    """校验一次部分更新：白名单 + 单键规则 + **合成结果上的跨字段规则**。

    返回「规范化后的 clean patch」（dotted → value）。非法 raise `SettingsError`（逐键错误）。
    跨字段在「原文件 + 本次改动」的合成结果上校验（走项目自己的 `load_config` 三级链），
    因此部分更新也不允许造出 peaceful ≥ panic 这类倒挂。
    """
    if not isinstance(patch, dict):
        raise SettingsError(["请求体需为对象（{\"路径\": 值}）"])
    errors: list[str] = []
    clean: dict[str, object] = {}
    for dotted, value in patch.items():
        try:
            clean[dotted] = _validate_one(dotted, value)
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        raise SettingsError(errors)

    # 合成结果（原文件 + 本次改动）→ 临时文件 → 走项目真实的三级链 → 跨字段校验
    path = _config_file(config_path)
    new_raw = copy.deepcopy(_read_raw(path))
    for dotted, value in clean.items():
        node = new_raw
        parts = dotted.split(".")
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    tmp = path.parent / (path.name + ".validate-tmp")
    try:
        tmp.write_text(json.dumps(new_raw, ensure_ascii=False, indent=2), encoding="utf-8")
        merged = load_config(tmp)
    finally:
        if tmp.exists():
            tmp.unlink()
    for a, b, msg in PAIR_RULES:
        va, vb = _get_merged(merged, a), _get_merged(merged, b)
        if va is not None and vb is not None and va >= vb:
            errors.append("%s（%s ≥ %s）" % (msg, va, vb))
    if errors:
        raise SettingsError(errors)
    return clean


def _get_merged(cfg: dict, dotted: str):
    node: object = cfg
    for k in dotted.split("."):
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def _backup(path: Path) -> Path | None:
    """写前备份（文件存在才有得备）。"""
    if not path.exists():
        return None
    dst = path.parent / (_backup_prefix(path) + time.strftime("%Y%m%d-%H%M%S"))
    dst.write_bytes(path.read_bytes())
    return dst


def _prune_backups(path: Path, keep: int = BACKUP_KEEP) -> int:
    """滚动清理更旧的备份（**只在写入成功后调用**）。"""
    backups = sorted(path.parent.glob(_backup_prefix(path) + "*"))
    removed = 0
    for old in backups[:-keep] if len(backups) > keep else []:
        try:
            old.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.parent / (path.name + ".settings-tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)                       # 同盘原子替换（analyzer 既有范式）


def apply_updates(patch: dict, config_path: Path | str | None = None,
                  backup: bool = True) -> dict:
    """校验 → 读原文件深合并 → 备份 → 原子写 → 滚动清备份 → 返回**生效值**。

    🔴 写的是**用户原文件**：只 set 本次白名单内的路径，用户文件里的其它键**原样保留**
    （`load_config()` 的返回值是合并结果，**严禁**写回 —— 会把内置默认固化进用户文件，plan R7）。
    """
    clean = validate_updates(patch, config_path)
    path = _config_file(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_raw = copy.deepcopy(_read_raw(path))
    for dotted, value in clean.items():
        node = new_raw
        parts = dotted.split(".")
        for k in parts[:-1]:
            node = node.setdefault(k, {})
        node[parts[-1]] = value
    bak = _backup(path) if backup else None
    _atomic_write(path, new_raw)
    if bak is not None:
        _prune_backups(path)
    values, _ = read_settings(config_path)
    return values
