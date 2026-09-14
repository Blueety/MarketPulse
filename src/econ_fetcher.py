"""经济数据源：BLS（美国劳工统计局）官方 API —— 免 Key / 权威 / 月度更新。

用途：宏观页「历史宏观环境」（四象限）与「经济数据」模块的数据底座。

⚠️ 三条「改错就废」的约束（勿"优化"掉）：

1. **抓取 TTL 必须是小时级**（调用方 `web.app` 定 `_ECON_TTL = 6*3600`）：BLS **无 Key 限额
   25 次查询 / 日 / IP**，若沿用 `/api/macro` 的 90s TTL → 一天最多 960 次 → **必然超限**
   （超限时 BLS 返回 `REQUEST_NOT_PROCESSED`）。经济数据是**月度**的，6 小时 TTL
   完全不影响新鲜度。
2. **CPI-U / PPI 返回的是"指数"不是百分比**（CPI-U 2026-M08 = 334.980）。同比要自己算：
   `(今月 / 去年同月 - 1) × 100`。因此 `startyear` 至少拉 3 年（算同比至少要 13 个月）。
3. **`as_of` 取"数据月份"（如 `2026-08`），不是抓取时间**。经济数据有发布滞后
   （8 月 CPI 在 9 月中才公布），用抓取时间会让前端显示成"最新/实时"，误导用户。

增长轴口径（**如实标注，不要宣称是 PMI**）：GDP 在 BEA（需 Key）、PMI 是 ISM 专有
（无免费源）→ 用**就业**替代：非农就业 3 个月均值（主）+ 失业率 3 个月变化（辅）。
就业是增长轴的核心月度指标，且比季度 GDP 更及时。四象限阈值（`_DIRECTION_EPS` /
`_PAYROLL_WINDOW`）是**工程取值**，不是理论值。

本模块**零写盘**：全部内存计算，不落盘、不进 history、不改任何现有管线
（符合 Web 只读约束）。
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

import requests

log = logging.getLogger("marketpulse")

BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# 一次 POST 拿 4 个序列（BLS 支持 seriesid 数组）→ 通胀轴 + 增长轴全覆盖
ECON_SERIES: dict[str, dict] = {
    "cpi":          {"label": "CPI-U",      "sid": "CUUR0000SA0",    "unit": "index"},
    "ppi":          {"label": "PPI 终需求",  "sid": "WPSFD4",         "unit": "index"},
    "unemployment": {"label": "失业率",       "sid": "LNS14000000",   "unit": "percent"},
    "payrolls":     {"label": "非农就业",     "sid": "CES0000000001", "unit": "thousands"},
}
_SID_TO_KEY = {meta["sid"]: key for key, meta in ECON_SERIES.items()}

_LOOKBACK_YEARS = 3      # 算同比需 ≥13 个月；拉 3 年兼顾同比 + 趋势（BLS 单次上限 20 年）
_HISTORY_MONTHS = 24     # 输出给前端的 history 长度
_DIRECTION_EPS = 0.05    # 方向判定的"持平"带宽（工程取值）：|Δ| < EPS → flat
_PAYROLL_WINDOW = 3      # 非农用 3 个月均值判方向（单月噪声大）

_SESSION = requests.Session()


# ---- 拉取 ----

def _clean_series(items: list[dict]) -> list[tuple[str, float]]:
    """BLS 原始 `data` → `[(YYYY-MM, value)]` 升序。

    过滤规则：
    - `period` 必须是 `M01`~`M12`；**`M13` 是年度均值，混进来会污染"最新值"**；
    - `year` 必须是 4 位数字；
    - `value` 非数值（BLS 用 `"-"` 表示不可用）丢弃。
    """
    rows: list[tuple[str, float]] = []
    for it in items:
        year = str(it.get("year") or "")
        period = str(it.get("period") or "")
        if not re.fullmatch(r"\d{4}", year) or not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
            continue
        try:
            val = float(it.get("value"))
        except (TypeError, ValueError):
            continue
        rows.append((f"{year}-{period[1:]}", val))
    rows.sort(key=lambda r: r[0])          # BLS 返回是倒序；统一升序，后续一律按时间取尾
    return rows


def fetch_econ_series(startyear: int | None = None, timeout: int = 20) -> dict[str, list[tuple[str, float]]]:
    """POST BLS 拿全部 4 个序列（**一次请求**）；**任何失败 → `{}`**（调用方降级，不抛）。

    失败面：网络异常 / 超时 / HTTP 非 2xx / `status != REQUEST_SUCCEEDED`
    （无 Key 超过 25 次/日时是 `REQUEST_NOT_PROCESSED`）/ 响应结构缺失 / 非 JSON。
    """
    year = startyear or (date.today().year - _LOOKBACK_YEARS)
    body = {
        "seriesid": [meta["sid"] for meta in ECON_SERIES.values()],
        "startyear": str(year),
        "endyear": str(date.today().year),
    }
    try:
        resp = _SESSION.post(BLS_URL, json=body, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 —— 网络/解析层任何异常都走降级，不上抛
        log.warning("BLS 经济数据请求失败: %s", exc)
        return {}
    status = data.get("status")
    if status != "REQUEST_SUCCEEDED":
        log.warning("BLS 经济数据返回非成功状态: %s %s", status, data.get("message"))
        return {}
    out: dict[str, list[tuple[str, float]]] = {}
    for item in (data.get("Results") or {}).get("series") or []:
        key = _SID_TO_KEY.get(item.get("seriesID"))
        if key:
            out[key] = _clean_series(item.get("data") or [])
    return out


# ---- 派生（纯函数）----

def _yoy(values: list[float]) -> float | None:
    """同比 %：`(今月 / 去年同月 - 1) × 100`；不足 13 个月 / 去年同月为 0 → `None`（不猜）。"""
    if len(values) < 13:
        return None
    base = values[-13]
    if not base:
        return None
    return round((values[-1] / base - 1) * 100, 2)


def _is_consecutive_months(yms: list[str]) -> bool:
    """月份键是否连续（`"2026-08"` 的前一个月必须是 `"2026-07"`，跨年 OK）。"""
    for prev, cur in zip(yms, yms[1:]):
        y, m = int(prev[:4]), int(prev[5:])
        nxt = f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"
        if cur != nxt:
            return False
    return True


def _yoy_at(yms: list[str], values: list[float], end: int) -> float | None:
    """以 `values[end]` 为"今月"算同比；窗口不足 / 月份不连续 → `None`。

    ⚠️ 只取"第 13 个"在**数据缺口（缺月）时会静默算错基准**（拿到的不是去年同月），
    所以先校验这 13 个月是否连续 —— 不连续一律 `None`，绝不猜。
    """
    if end < 12 or end >= len(values):
        return None
    if not _is_consecutive_months(yms[end - 12:end + 1]):
        return None
    return _yoy(values[end - 12:end + 1])


def _direction(cur: float | None, prev: float | None, eps: float = _DIRECTION_EPS) -> str | None:
    """`up` / `down` / `flat`（`|Δ| < eps` 视为持平）；任一入参为 `None` → `None`。"""
    if cur is None or prev is None:
        return None
    diff = cur - prev
    if diff > eps:
        return "up"
    if diff < -eps:
        return "down"
    return "flat"


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _infl_axis(cpi_dir: str | None, ppi_dir: str | None) -> str | None:
    """通胀轴：CPI 同比方向为主，PPI 同比方向二次确认。

    ⚠️ 两者都"持平"时返回 `"up"`（**工程约定**）：四象限需要二值轴，月度数据下
    "持平"多是阈值内抖动，取"通胀未回落"为默认；无任何数据 → `None`。
    """
    for direction in (cpi_dir, ppi_dir):
        if direction in ("up", "down"):
            return direction
    return "up" if (cpi_dir or ppi_dir) else None


def _growth_axis(payroll_vals: list[float], unemp_vals: list[float]) -> dict:
    """增长轴：非农 3 个月均值方向（主）+ 失业率 3 个月变化（辅）。

    - 非农非持平 → 以非农为准（就业是增长轴核心指标）；
    - 非农持平 → 看失业率（**上行 = 恶化 → 收缩**）；
    - 两者都无数据 → `axis=None`（不猜）。
    口径如实标注：**这是就业替代 GDP/PMI，不是 PMI**。
    """
    if not payroll_vals and not unemp_vals:
        return {"axis": None, "payroll_3m": None, "payroll_dir": None, "unemployment_dir": None}
    p_now = _mean(payroll_vals[-_PAYROLL_WINDOW:])
    p_prev = _mean(payroll_vals[-2 * _PAYROLL_WINDOW:-_PAYROLL_WINDOW])
    p_dir = _direction(p_now, p_prev)
    u_dir = _direction(unemp_vals[-1] if unemp_vals else None,
                       unemp_vals[-4] if len(unemp_vals) >= 4 else None)
    if p_dir in ("up", "down"):
        axis = "expanding" if p_dir == "up" else "contracting"
    elif u_dir == "up":
        axis = "contracting"
    else:
        axis = "expanding"
    return {"axis": axis, "payroll_3m": p_now, "payroll_dir": p_dir, "unemployment_dir": u_dir}


_QUADRANTS: dict[tuple[str, str], tuple[str, str]] = {
    ("up", "expanding"):   ("reflation",   "再通胀"),
    ("down", "expanding"): ("goldilocks",  "复苏"),
    ("up", "contracting"): ("stagflation", "滞胀"),
    ("down", "contracting"): ("deflation", "通缩衰退"),
}


def build_econ_payload(raw: dict | None) -> dict:
    """清洗 + 派生 → 统一结构（四象限在这里算完，前端不重算）。

    数据不足的字段一律 `None`，**不猜**。`raw` 为空（BLS 失败 / 降级）→ 空结构且
    `as_of` / `inflation_axis` / `growth_axis` / `quadrant` 全为 `None`（HTTP 仍 200）。

    `as_of` = 各序列中**最新的数据月份**（单序列月份见 `series[].date`）。
    """
    raw = raw or {}
    series: list[dict] = []
    latest_month: str | None = None
    for key, meta in ECON_SERIES.items():
        rows = raw.get(key) or []
        yms = [r[0] for r in rows]
        vals = [r[1] for r in rows]
        yoy = _yoy_at(yms, vals, len(vals) - 1)
        prev_yoy = _yoy_at(yms, vals, len(vals) - 2)
        if yms and (latest_month is None or yms[-1] > latest_month):
            latest_month = yms[-1]
        series.append({
            "key": key,
            "label": meta["label"],
            "unit": meta["unit"],
            "latest": round(vals[-1], 4) if vals else None,
            "date": yms[-1] if yms else None,
            "yoy": yoy,
            "prev_yoy": prev_yoy,
            "direction": _direction(yoy, prev_yoy),
            "history": [[ym, round(val, 4)] for ym, val in rows[-_HISTORY_MONTHS:]],
        })

    by_key = {s["key"]: s for s in series}
    inflation_axis = _infl_axis(by_key["cpi"]["direction"], by_key["ppi"]["direction"])
    growth = _growth_axis([r[1] for r in (raw.get("payrolls") or [])],
                          [r[1] for r in (raw.get("unemployment") or [])])
    growth_axis = growth["axis"]
    quadrant = quadrant_label = None
    if inflation_axis and growth_axis:
        quadrant, quadrant_label = _QUADRANTS[(inflation_axis, growth_axis)]

    return {
        "as_of": latest_month,                 # ★ 数据月份，不是抓取时间
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "series": series,
        "inflation_axis": inflation_axis,
        "growth_axis": growth_axis,
        "quadrant": quadrant,
        "quadrant_label": quadrant_label,
        # 口径标注（前端直接展示，避免把增长轴误读成 PMI）
        "basis": {
            "inflation": "CPI-U 同比（PPI 终需求二次确认）",
            "growth": "非农就业 3 个月均值 + 失业率 3 个月变化（就业替代 GDP/PMI，非 PMI）",
            "note": "四象限阈值为工程取值；as_of 为数据月份，存在发布滞后",
        },
        "growth_inputs": {
            "payroll_3m": growth["payroll_3m"],
            "payroll_dir": growth["payroll_dir"],
            "unemployment_dir": growth["unemployment_dir"],
        },
    }
