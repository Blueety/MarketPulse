"""中国宏观数据源：AkShare（国家统计局 / 央行 / 中债 官方数据转发）—— 免 Key / 月度或日频。

用途：`/macro/cn` 中国宏观页的「四象限 + 核心变量 + 经济数据明细」数据底座。

与 `src/econ_fetcher.py`（BLS / 美国）**平行且不共享取数**：数据源（AkShare vs BLS）、
序列数（13 vs 4）、TTL、失败语义都不同；塞进一个模块会让「只缓存成功」等纪律互相污染。
**共享的只有四象限常量** `QUADRANTS`（同一套语义，复制一份必然漂移）。

⚠️ 五条「改错就废」的约束（勿"优化"掉）：

1. **排序口径不统一 —— 必须按周期键排序后再取尾**（2026-09-14 实测）：
   `cpi`/`ppi`/`pmi`/`gdp`/`m2`/`credit`/`retail` 是**倒序**返回（`iloc[-1]` 是 2008 年），
   而 `social_financing`/`unemployment`/`house_price`/`lpr`/`shibor`/`bond_10y` 是**正序**。
   照 BLS 版那样"取第 N 个"或"取 `iloc[-1]`"会把最旧的行当最新值（cpi 实测误得 2008-01）。
2. **增长轴用 PMI 的「水平」与 50 比较**，**不是同比方向**：PMI 是扩散指数，
   49.8（< 50，收缩）与它的同比 +0.81%（方向 up）**结论相反**。照抄美国版
   `_growth_axis`（同比方向）会得到"扩张"的错误结论。详见 `_growth_axis_cn`。
3. **房价只有「北京 · 上海」2 城**（接口实际覆盖，**不是 70 城**），且 `新建商品住宅价格指数-同比`
   是**指数（上年同月 = 100）** → 同比% = 值 − 100（上海 103.0 = +3.0%）。
   文案与换算都不得按"70 城"或"原始值即百分比"处理。
4. **`bond_china_yield` 区间敏感**：6 个月窗口返回 411 行，**1 年窗口返回 0 行**（上游行为，
   非 bug）→ 固定用 6 个月窗口 + 空结果守卫。`scripts/probe_cn_macro.py` 已把该行为固化为已知。
5. **`as_of` 取「数据月份」**（不是抓取时间），且**优先取月度序列**：日频序列（SHIBOR / 10Y
   国债）会把 `as_of` 顶到今天，掩盖月度数据的发布滞后。

**列缺失守卫**（`_require_cols`）：AkShare 升级改列名是常态，缺列一律降级 `[]` 并记 warning，
绝不抛异常中断其余 12 个序列（复用 `fetcher.fetch_sector_heat` 的守纪律）。

本模块**零写盘**：全部内存计算，不落盘、不进 history、不改任何现有管线（Web 只读边界）。
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import date, datetime
from time import monotonic

from src.econ_fetcher import QUADRANTS, _direction, _infl_axis

log = logging.getLogger("marketpulse")

# ---- 序列注册表 ----
#
# kind：`yoy` = 主列**已经是同比%**；`level` = 主列是水平值（同比由 `_yoy_at` 现算）。
# freq：`month` / `quarter` / `day`（决定 history 深度、as_of 是否参与、同比基准怎么找）。
# index100：主列是「上年同月 = 100」的指数 → 同比% = 值 − 100（房价，见约束 3）。
CN_ECON_SERIES: dict[str, dict] = {
    "cpi": {"group": "price", "label": "CPI", "unit": "%", "fn": "macro_china_cpi",
            "time_col": "月份", "main_col": "全国-同比增长", "kind": "yoy", "freq": "month"},
    "ppi": {"group": "price", "label": "PPI", "unit": "%", "fn": "macro_china_ppi",
            "time_col": "月份", "main_col": "当月同比增长", "kind": "yoy", "freq": "month"},
    "pmi": {"group": "growth", "label": "制造业 PMI", "unit": "", "fn": "macro_china_pmi",
            "time_col": "月份", "main_col": "制造业-指数", "kind": "level", "freq": "month"},
    "gdp": {"group": "growth", "label": "GDP", "unit": "%", "fn": "macro_china_gdp",
            "time_col": "季度", "main_col": "国内生产总值-同比增长", "kind": "yoy", "freq": "quarter"},
    "m2": {"group": "money", "label": "M2", "unit": "%", "fn": "macro_china_money_supply",
           "time_col": "月份", "main_col": "货币和准货币(M2)-同比增长", "kind": "yoy", "freq": "month"},
    "social_financing": {"group": "money", "label": "社会融资规模增量", "unit": "亿元",
                         "fn": "macro_china_bank_financing", "time_col": "日期", "main_col": "最新值",
                         "kind": "level", "freq": "month"},
    # ⚠️ 主列用「累计-同比增长」：`当月` 存在异常负值（2026-07 = -5896），见约束与 basis.credit_note
    "credit": {"group": "money", "label": "新增信贷", "unit": "%", "fn": "macro_china_new_financial_credit",
               "time_col": "月份", "main_col": "累计-同比增长", "kind": "yoy", "freq": "month"},
    # 长表：date / item / value，item 有 4 种（含尾随空格），只取「全国城镇调查失业率」
    "unemployment": {"group": "labor", "label": "城镇调查失业率", "unit": "%",
                     "fn": "macro_china_urban_unemployment", "time_col": "date", "main_col": "value",
                     "kind": "level", "freq": "month", "filter_item": "全国城镇调查失业率"},
    "retail": {"group": "labor", "label": "社会消费品零售", "unit": "%",
               "fn": "macro_china_consumer_goods_retail", "time_col": "月份", "main_col": "同比增长",
               "kind": "yoy", "freq": "month"},
    # 仅 2 城（北京 / 上海），按城市拆两条序列；主列是指数（上年同月 = 100）
    "house_price": {"group": "estate", "label": "新建商品住宅价格", "unit": "%",
                    "fn": "macro_china_new_house_price", "time_col": "日期",
                    "main_col": "新建商品住宅价格指数-同比", "kind": "yoy", "freq": "month",
                    "split_col": "城市", "index100": True},
    "lpr": {"group": "rate", "label": "LPR 1Y", "unit": "%", "fn": "macro_china_lpr",
            "time_col": "TRADE_DATE", "main_col": "LPR1Y", "kind": "level", "freq": "day"},
    "shibor": {"group": "rate", "label": "SHIBOR 隔夜", "unit": "%", "fn": "macro_china_shibor_all",
               "time_col": "日期", "main_col": "O/N-定价", "kind": "level", "freq": "day"},
    # 区间敏感（约束 4）：固定 6 个月窗口；一次请求返回 3 条曲线，只取国债曲线
    "bond_10y": {"group": "rate", "label": "10 年期国债收益率", "unit": "%", "fn": "bond_china_yield",
                 "kwargs": "AUTO_6M", "time_col": "日期", "main_col": "10年", "kind": "level",
                 "freq": "day", "filter_col": "曲线名称", "filter_value": "中债国债收益率曲线"},
}

_CN_ECON_TIMEOUT = 25      # 整体限时（daemon 线程 + join；串行实测 ≈22s → 必须并发）
# ⚠️ 并发度 13 = **全部一起发**（2026-09-14 实测，勿凭直觉改小）：
#   串行 22.2s / workers=6 → 13.6s / workers=3 → 15.2s / workers=13 → **10.3s**。
#   并发越小越慢（13 个接口都是等网络，排队只会把总时长摊长）；墙钟由**最慢的单个接口**
#   `bond_china_yield`（7.5~8.4s）决定，不是由并发度决定。TTL 6h → 一天 ≤4 次，不会限频。
_CN_ECON_WORKERS = 13
_CN_HISTORY_MONTHS = 36    # 月/季序列输出给前端的 history 长度（3 年）
_CN_HISTORY_DAYS = 120     # 日频序列输出给前端的 history 长度（≈6 个月）

# 分组（R1 降级路径）：单端点全量实测 10.3s > 8s 判据 → 前端按组分两波懒加载。
# ⚠️ **同时**发 6 个分组请求不会有收益（13 个上游请求照样同时在飞，墙钟不变）——
#    必须**分批**（先 price+growth 出四象限，再其余），这是"逐组填充"的本意。
CN_ECON_GROUPS: dict[str, list[str]] = {
    "price": ["cpi", "ppi"],
    "growth": ["pmi", "gdp"],
    "money": ["m2", "social_financing", "credit"],
    "rate": ["lpr", "shibor", "bond_10y"],
    "labor": ["unemployment", "retail"],
    "estate": ["house_price"],
}
CN_ECON_GROUP_KEYS: tuple[str, ...] = tuple(CN_ECON_GROUPS)

_CITY_SLUG = {"北京": "bj", "上海": "sh"}   # house_price 拆分后的 key 后缀
_BOND_CURVES = {                            # bond_china_yield 一次返回的 3 条曲线
    "中债国债收益率曲线": "国债",
    "中债商业银行普通债收益率曲线(AAA)": "商金债AAA",
    "中债中短期票据收益率曲线(AAA)": "中票AAA",
}
_PMI_THRESHOLD = 50.0      # ★ 天然荣枯线（不是工程取值）：PMI ≥ 50 = 扩张
_PMI_WINDOW = 3            # 增长轴用 3 个月均值平滑单月噪声

_AXIS_DIR = {"expanding": "up", "contracting": "down"}
_DIR_AXIS = {"up": "expanding", "down": "contracting"}

Rows = list[tuple[str, float]]


# ---- 解析纯函数 ----

def _parse_ym(raw) -> str | None:
    """各种日期文本 → 统一周期键；非法 → `None`（绝不猜）。

    - `"2026年08月份"` → `"2026-08"`；`"202607"` → `"2026-07"`；`"2026-08-01"` → `"2026-08"`
      （`datetime.date` 会先被 `str()` 成 `2026-07-01`）
    - `"2026年第1-2季度"` → `"2026Q2"`（**取区间里的较大季度号** = 该累计期的末尾季度）
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if "季度" in s:
        m = re.search(r"(\d{4})\D*第?(\d{1,2})(?:\s*[—–\-~]\s*(\d{1,2}))?\s*季度", s)
        if not m:
            return None
        quarter = int(m.group(3) or m.group(2))
        return f"{m.group(1)}Q{quarter}" if 1 <= quarter <= 4 else None
    m = re.search(r"(\d{4})\D{0,3}(\d{1,2})", s)
    if not m:
        return None
    month = int(m.group(2))
    return f"{m.group(1)}-{month:02d}" if 1 <= month <= 12 else None


def _parse_date(raw) -> str | None:
    """日频序列的完整日期 `YYYY-MM-DD`（月/季序列用 `_parse_ym` 即可）。"""
    if raw is None:
        return None
    m = re.search(r"(\d{4})\D{1,2}(\d{1,2})\D{1,2}(\d{1,2})", str(raw))
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _to_float(raw) -> float | None:
    """`None` / `nan` / 空串 / 非数值 → `None`（AkShare 大量用 `nan` 表示缺失）。"""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    return None if val != val else val        # NaN 自检（NaN != NaN）


def _require_cols(df, cols: list[str]) -> bool:
    """缺列守卫：任一必需列缺失 → `False`（调用方降级 `[]`，**不抛**）。"""
    have = {str(c) for c in df.columns}
    missing = [c for c in cols if c not in have]
    if missing:
        log.warning("中国宏观：接口返回缺少必需列 %s（AkShare 版本变更？），降级为空", missing)
        return False
    return True


def _sort_rows(rows: Rows) -> Rows:
    """按周期键**升序**重排 + 同键去重（后者覆盖前者）。

    见模块约束 1：上游排序口径不统一，所有消费点都必须先过这里再"取尾"。
    """
    clean = [(k, v) for k, v in rows if k is not None and v is not None]
    clean.sort(key=lambda r: r[0])
    out: Rows = []
    for k, v in clean:
        if out and out[-1][0] == k:
            out[-1] = (k, v)
        else:
            out.append((k, v))
    return out


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _months_ago(end: date, n: int) -> date:
    idx = end.year * 12 + (end.month - 1) - n
    return date(idx // 12, idx % 12 + 1, 1)


def _resolve_kwargs(spec: dict) -> dict:
    """`kwargs` 支持哨兵 `AUTO_6M`（按调用当天算 6 个月窗口，见约束 4）。"""
    raw = spec.get("kwargs")
    if raw == "AUTO_6M":
        end = date.today()
        return {"start_date": _months_ago(end, 6).strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")}
    return dict(raw or {})


# ---- 单序列取数 ----

def _rows_from(df, spec: dict) -> Rows:
    """按 spec 的 time/main 列抽 `[(周期键, 值)]`（已排序）；`index100` 时值 − 100。"""
    key_fn = _parse_date if spec.get("freq") == "day" else _parse_ym
    offset = -100.0 if spec.get("index100") else 0.0
    rows: Rows = []
    for raw_t, raw_v in zip(df[spec["time_col"]], df[spec["main_col"]]):
        val = _to_float(raw_v)
        if val is None:
            continue
        rows.append((key_fn(raw_t), round(val + offset, 4)))
    return _sort_rows(rows)


def _fetch_one(key: str) -> Rows | dict[str, Rows]:
    """取单个序列；**任何失败返回空**（`[]` 或 `{}`），绝不抛。

    返回类型：`split_col` 的序列（房价）返回 `{城市: rows}`，其余返回 `rows`。
    """
    spec = CN_ECON_SERIES[key]
    try:
        import akshare as ak
    except Exception as exc:  # noqa: BLE001 —— akshare 缺失不应拖垮 Web 进程
        log.warning("中国宏观：akshare 导入失败，%s 降级为空: %s", key, exc)
        return {} if spec.get("split_col") else []

    fn = getattr(ak, spec["fn"], None)
    if fn is None:
        log.warning("中国宏观：akshare 无接口 %s（版本变更？），%s 降级为空", spec["fn"], key)
        return {} if spec.get("split_col") else []

    try:
        df = fn(**_resolve_kwargs(spec))
    except Exception as exc:  # noqa: BLE001
        log.warning("中国宏观：%s 取数失败，降级为空: %s", key, exc)
        return {} if spec.get("split_col") else []

    if df is None or len(df) == 0:
        log.warning("中国宏观：%s 返回空结果（上游无数据 / 区间敏感），降级为空", key)
        return {} if spec.get("split_col") else []

    need = [spec["time_col"], spec["main_col"]]
    if spec.get("filter_col"):
        need.append(spec["filter_col"])
    if spec.get("filter_item"):
        need.append("item")
    if spec.get("split_col"):
        need.append(spec["split_col"])
    if not _require_cols(df, need):
        return {} if spec.get("split_col") else []

    df = df.copy()

    # 国债曲线：一次请求返回 3 条曲线，只取「中债国债收益率曲线」
    if spec.get("filter_col"):
        df = df[df[spec["filter_col"]].astype(str).str.strip() == spec["filter_value"]]
    # 失业率：长表，item 有 4 种且**带尾随空格** → 先 strip 再精确匹配
    if spec.get("filter_item"):
        df = df[df["item"].astype(str).str.strip() == spec["filter_item"]]
    if len(df) == 0:
        log.warning("中国宏观：%s 过滤后为空，降级为空", key)
        return {} if spec.get("split_col") else []

    # 房价：按城市拆多条序列（**只有 2 城**，不是 70 城）
    if spec.get("split_col"):
        out: dict[str, Rows] = {}
        for city, grp in df.groupby(df[spec["split_col"]].astype(str).str.strip(), sort=False):
            rows = _rows_from(grp, spec)
            if rows:
                out[str(city)] = rows
        return out

    return _rows_from(df, spec)


# ---- 并发取数 ----

def group_keys(group: str | None) -> list[str]:
    """分组名 → 该组的 key 列表；`None` → 全部 13 个。未知组名 → `[]`（调用方降级，不抛）。"""
    if group is None:
        return list(CN_ECON_SERIES)
    return list(CN_ECON_GROUPS.get(group) or [])


def fetch_cn_econ_raw(keys: list[str] | None = None,
                      timeout: int = _CN_ECON_TIMEOUT) -> tuple[dict, list[str]]:
    """并发拉取序列（默认全部 13 个，`keys` 可指定分组子集）+ 整体限时。

    返回 `(raw, failed)`；**不抛异常**。单序列失败 → 该 key 为空并计入 `failed`，
    其余照常返回（调用方按 `failed` 逐模块降级）。超时 → 未完成的 key 记 `failed`。

    用 daemon 线程 + 全局 deadline（而非 `ThreadPoolExecutor`）：AkShare 内部
    `requests` 多无 timeout，若某个调用永久挂起，`ThreadPoolExecutor` 的 atexit
    会 **join 住非 daemon 工作线程导致进程退不出**；daemon 线程进程退出即终止。
    """
    keys = [k for k in (keys or list(CN_ECON_SERIES)) if k in CN_ECON_SERIES]
    out: dict = {}
    lock = threading.Lock()
    slots = threading.BoundedSemaphore(min(_CN_ECON_WORKERS, max(1, len(keys))))

    def worker(k: str) -> None:
        try:
            with slots:
                rows = _fetch_one(k)
        except Exception as exc:  # noqa: BLE001 —— 兜底：任何异常都只让这一个 key 空
            log.warning("中国宏观：%s 取数异常，降级为空: %s", k, exc)
            rows = [] if not CN_ECON_SERIES[k].get("split_col") else {}
        with lock:
            out[k] = rows

    threads = [threading.Thread(target=worker, args=(k,), daemon=True) for k in keys]
    for t in threads:
        t.start()
    deadline = monotonic() + timeout
    for t in threads:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        t.join(remaining)
    if any(t.is_alive() for t in threads):
        log.warning("中国宏观取数超时（>%ds），未完成序列降级为空", timeout)

    failed: list[str] = []
    for k in keys:
        rows = out.get(k)
        if rows is None:                       # 超时未完成
            out[k] = [] if not CN_ECON_SERIES[k].get("split_col") else {}
            failed.append(k)
        elif not rows:
            failed.append(k)
    return out, failed


# ---- 派生（纯函数）----

def _prior_value(rows: Rows, end: int) -> float | None:
    """找 `rows[end]` 的「去年同期」值（**按键查，不按位置**，真实数据会缺期）。

    - 月/季：精确匹配 `去年 + 同月/同季`；
    - 日频：匹配 `去年同月` 的**最后一个**交易日（从 end 往前找首个同前缀行）。
    """
    if end < 0 or end >= len(rows):
        return None
    key = rows[end][0]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key or ""):
        y, m = int(key[:4]), key[5:7]
        prefix = f"{y - 1}-{m}"
        for i in range(end - 1, -1, -1):
            if rows[i][0].startswith(prefix):
                return rows[i][1]
        return None
    m = re.fullmatch(r"(\d{4})(-\d{2}|Q\d)", key or "")
    if not m:
        return None
    want = f"{int(m.group(1)) - 1}{m.group(2)}"
    return next((v for k, v in rows if k == want), None)


def _yoy_at(rows: Rows, end: int) -> float | None:
    """`rows[end]` 的同比 %（水平序列用）；基数缺失 / 为 0 → `None`（不猜，防除零）。"""
    if end < 0 or end >= len(rows):
        return None
    base = _prior_value(rows, end)
    cur = rows[end][1]
    if not base or cur is None:
        return None
    return round((cur / base - 1) * 100, 2)


def _growth_axis_cn(pmi_rows: Rows, gdp_rows: Rows) -> dict:
    """中国版增长轴：**PMI 3 个月均值与 50 比较（水平口径）** + GDP 同比方向交叉校验。

    ⚠️ **必须用水平，不能用同比方向**（模块约束 2）：PMI 是扩散指数，49.8（< 50 → 收缩）
    与它的同比 +0.81%（方向 up → 扩张）**结论相反**。美国版 `_growth_axis` 用同比方向
    是因为它拿不到 PMI 才用就业替代；中国版有真 PMI，口径必须改。

    `conflict`：GDP 方向（归一化成 expanding/contracting）与 PMI 结论不一致时**如实上报**，
    不静默取一个 —— 前端据此提示"交叉校验不一致"。
    """
    pmi_vals = [v for _, v in pmi_rows]
    gdp_vals = [v for _, v in gdp_rows]
    pmi_3m = _mean(pmi_vals[-_PMI_WINDOW:])
    pmi_axis = None if pmi_3m is None else ("expanding" if pmi_3m >= _PMI_THRESHOLD else "contracting")

    gdp_dir = _direction(gdp_vals[-1] if gdp_vals else None,
                         gdp_vals[-2] if len(gdp_vals) >= 2 else None)
    gdp_axis = _DIR_AXIS.get(gdp_dir or "")          # flat / 无数据 → None（不构成交叉信号）
    conflict = bool(gdp_axis and pmi_axis and gdp_axis != pmi_axis)
    return {
        "pmi_3m": pmi_3m,
        "pmi_axis": pmi_axis,
        "gdp_yoy": gdp_vals[-1] if gdp_vals else None,
        "gdp_axis": gdp_axis,
        "conflict": conflict,
    }


def _series_item(key: str, spec: dict, rows: Rows, label: str | None = None) -> dict:
    """单序列 → 契约结构（`latest` / `date` / `yoy` / `prev_yoy` / `direction` / `history`）。"""
    rows = _sort_rows(rows)
    vals = [v for _, v in rows]
    latest = vals[-1] if vals else None
    prev = vals[-2] if len(vals) >= 2 else None
    if spec["kind"] == "yoy":
        yoy, prev_yoy = latest, prev                      # 主列已经是同比%
    else:
        yoy, prev_yoy = _yoy_at(rows, len(rows) - 1), _yoy_at(rows, len(rows) - 2)
    depth = _CN_HISTORY_DAYS if spec["freq"] == "day" else _CN_HISTORY_MONTHS
    return {
        "key": key,
        "group": spec["group"],
        "label": label or spec["label"],
        "unit": spec["unit"],
        "freq": spec["freq"],
        "latest": latest,
        "date": rows[-1][0] if rows else None,
        "yoy": yoy,
        "prev_yoy": prev_yoy,
        "direction": _direction(yoy, prev_yoy) or _direction(latest, prev),
        "history": [[k, v] for k, v in rows[-depth:]],
    }


def build_cn_econ_payload(raw: dict | None = None, failed: list[str] | None = None,
                          only: list[str] | None = None) -> dict:
    """清洗 + 派生 → 统一结构（四象限在这里算完，前端不重算）。

    `only`：只输出这些 key 的 `series`（分组端点用）；**四象限仍按整个 `raw` 计算** ——
    否则分组响应里永远拿不到 `quadrant`（四象限需要跨组的 cpi/ppi + pmi/gdp）。

    `raw` 为空 / 全失败 → `as_of` 与所有轴为 `None`（HTTP 仍 200，前端逐模块「数据暂缺」）。
    `as_of`：**优先取月度序列**的最大数据月份（模块约束 5）。
    """
    raw = raw or {}
    failed = list(failed or [])
    series: list[dict] = []
    for key, spec in CN_ECON_SERIES.items():
        if only is not None and key not in only:
            continue
        value = raw.get(key)
        if isinstance(value, dict):                       # 拆分序列（房价：北京 / 上海）
            for i, (city, rows) in enumerate(value.items()):
                slug = _CITY_SLUG.get(city, f"c{i}")
                series.append(_series_item(f"{key}_{slug}", spec, rows,
                                           label=f"{spec['label']}·{city}"))
        else:
            series.append(_series_item(key, spec, value or []))

    groups: dict[str, list[str]] = {}
    for s in series:
        groups.setdefault(s["group"], []).append(s["key"])

    # ⚠️ 轴与四象限按**整个 raw** 计算（不受 `only` 影响）：分组响应也要能带上 `quadrant`
    def _dir_of(key: str) -> str | None:
        rows = raw.get(key)
        if isinstance(rows, dict) or not rows:
            return None
        vals = [v for _, v in _sort_rows(rows)]
        return _direction(vals[-1] if vals else None, vals[-2] if len(vals) >= 2 else None)

    inflation_axis = _infl_axis(_dir_of("cpi"), _dir_of("ppi"))
    growth = _growth_axis_cn(
        _sort_rows(raw.get("pmi") or []),
        _sort_rows(raw.get("gdp") or []),
    )
    growth_axis = growth["pmi_axis"]
    quadrant = quadrant_label = None
    if inflation_axis and growth_axis:
        quadrant, quadrant_label = QUADRANTS[(inflation_axis, growth_axis)]

    # as_of：**只取月度序列**（日频的 SHIBOR / 10Y 国债会把 as_of 顶到今天，掩盖发布滞后）
    monthly = [s["date"] for s in series if s["freq"] == "month" and s["date"]]
    as_of = max(monthly) if monthly else max((s["date"] for s in series if s["date"]), default=None)

    return {
        "as_of": as_of,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "failed": failed,
        "series": series,
        "groups": groups,
        "inflation_axis": inflation_axis,
        "growth_axis": growth_axis,
        "quadrant": quadrant,
        "quadrant_label": quadrant_label,
        "growth_inputs": growth,
        # 口径标注（前端直接展示）：每一条都要能挡住"想当然的误读"
        # ⚠️ 文案里**不得出现** "70 城"（C1 纠正项）：verify_ui 的断言会检查房价模块文案
        #    不含该字面量；basis 若被前端渲染，写"非 70 城"同样会命中该断言 → 直接写成"仅覆盖 2 城"。
        "basis": {
            "inflation": "CPI 同比方向（PPI 同比二次确认）",
            "growth": f"制造业 PMI 与 {int(_PMI_THRESHOLD)} 荣枯线比较（{_PMI_WINDOW} 个月均值；"
                      f"水平口径，非同比方向）",
            "crosscheck": "季度 GDP 同比方向作交叉校验（与 PMI 结论不一致时如实标注）",
            "price_note": "房价指数仅覆盖北京·上海两城（接口实际覆盖范围），口径为上年同月=100",
            "credit_note": "新增信贷主用累计同比；当月口径存在异常值",
            "rate_note": "10Y 国债取自中债国债收益率曲线（固定 6 个月窗口；1 年窗口上游返回 0 行）",
            "asof_note": "as_of 为数据月份，宏观经济数据存在发布滞后",
        },
    }


# ---- 行情（/api/cn/quotes 用）----

def fetch_bond_yield_curves(tenor: str = "10年", timeout: int = 20) -> dict[str, Rows]:
    """中债收益率曲线 → `{曲线简称: [(日期, 收益率%)]}`，**失败返回 `{}`**。

    一次请求返回 3 条曲线（`国债` / `商金债AAA` / `中票AAA`）→ 信用利差（商金债 − 国债）
    **同一次取数免费获得**，正好补上美国版因 FRED 不通而被迫放弃的信用维度。
    """
    try:
        import akshare as ak
    except Exception as exc:  # noqa: BLE001
        log.warning("中债收益率：akshare 导入失败: %s", exc)
        return {}
    end = date.today()
    kwargs = {"start_date": _months_ago(end, 6).strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d")}

    box: dict = {}

    def worker() -> None:
        try:
            box["df"] = ak.bond_china_yield(**kwargs)
        except Exception as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    df = box.get("df")
    if df is None:
        log.warning("中债收益率取数失败: %s", box.get("err") or f"timeout>{timeout}s")
        return {}
    if not _require_cols(df, ["曲线名称", "日期", tenor]):
        return {}

    out: dict[str, Rows] = {}
    for curve, grp in df.groupby(df["曲线名称"].astype(str).str.strip(), sort=False):
        label = _BOND_CURVES.get(str(curve))
        if not label:
            continue
        rows = _sort_rows([(_parse_date(d), v) for d, v in
                           [(d, _to_float(v)) for d, v in zip(grp["日期"], grp[tenor])]
                           if d is not None and v is not None])
        if rows:
            out[label] = rows
    return out
