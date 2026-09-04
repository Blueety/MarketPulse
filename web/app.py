"""MarketPulse Web 看板：FastAPI 应用。

只读解析现有产物（data/history.json / context/*.json / alerts/*.md），提供单页看板
与 4 个 JSON API（含自选股实时取数 /api/watchlist，经 src.fetcher.fetch_watchlist，零写盘；响应含 hidden 键：无配置隐藏、有配置必显卡失败占位）。
零侵入日报 / 快照主流程：本进程绝不写 data / alerts / context。

路径常量从 analyzer 复用单一事实来源，但在此模块重新绑定为模块级名字，供解析函数
直接引用——测试按项目纪律 monkeypatch 这些名字（打在使用方模块 web.app，而非定义方
analyzer），因此解析函数**不调用** analyzer.load_history / alerter 等引用 analyzer 常量的函数。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.analyzer import ALERTS_DIR as _ALERTS_DIR
from src.analyzer import CONTEXT_DIR as _CONTEXT_DIR
from src.analyzer import HISTORY_FILE as _HISTORY_FILE
from src.config import load_config
from src.fetcher import SYMBOLS, fetch_watchlist

log = logging.getLogger("marketpulse")

# 模块级路径常量：解析函数一律引用本模块的这些名字（测试 monkeypatch 落点）。
HISTORY_FILE = _HISTORY_FILE
ALERTS_DIR = _ALERTS_DIR
CONTEXT_DIR = _CONTEXT_DIR

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

_TEMPLATES = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

app = FastAPI(title="MarketPulse Web 看板")

# 静态资源挂 /static（仅 style.css 等源码资源，不落盘生成物）。
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---- 历史解析（直接使用本模块 HISTORY_FILE 常量）----

def _load_history_raw() -> list[dict]:
    """读取 HISTORY_FILE；缺失 / 损坏 / 非列表 → []。记录须含 date 键。"""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("历史数据读取失败，按空历史处理: %s", exc)
        return []
    if not isinstance(data, list):
        log.warning("历史数据格式异常（非列表），按空历史处理")
        return []
    return [r for r in data if isinstance(r, dict) and r.get("date")]


def _last_records(n: int = 7) -> list[dict]:
    """返回最近 n 条历史记录（按文件顺序，末位为最新）。"""
    return _load_history_raw()[-n:]


def _normalize_series(raw: list[float | None]) -> tuple[list[float | None], float | None]:
    """单序列归一化为相对基准百分比（窗口首个非空值 = 100），返回 (values, change_7d)。

    - base 缺失或 0 → (全 None 列表, None)（防除零；列表同长以便前端安全遍历）。
    - 前导 null 位置原样保留；首个非空值作为基准。
    - 非空值 < 2 → change_7d 为 None（单点无 7D 变化可言，meta 显示「—」）。
    """
    base = next((v for v in raw if v is not None), None)
    if base in (None, 0):
        return [None] * len(raw), None
    values = [None if v is None else v / base * 100 for v in raw]
    last = next((v for v in reversed(raw) if v is not None), None)
    non_null = sum(1 for v in raw if v is not None)
    change_7d = (last - base) / base * 100 if (last is not None and non_null >= 2) else None
    return values, change_7d


def _resolve_symbols(symbols: str | None) -> list[str]:
    """解析 symbols 查询参数 → SYMBOLS 注册表序的大写键列表。

    - None / 空白 → 全部 SYMBOLS 键（保序）。
    - 逗号分隔 → strip + upper → 按 SYMBOLS 注册表序过滤（忽略参数传序、未知静默忽略）。
    - 解析结果为空（全未知 / 全空白）→ []。
    """
    if not symbols or not symbols.strip():
        return list(SYMBOLS.keys())
    wanted = {s.strip().upper() for s in symbols.split(",") if s.strip()}
    if not wanted:
        return []
    return [sym for sym in SYMBOLS if sym in wanted]


def _build_history_payload(days: int = 30, symbols: str | None = None) -> dict:
    """展开为 Chart.js 友好结构：dates + N 组 series（key=小写 symbol）。

    每个序列归一化为相对基准百分比（窗口首个非空值 = 100），另附 change_7d
    （窗口涨跌幅，键名保留向后兼容）与 raw（等长原始值，GLD 已 ×10，与图线一致）。
    按交易日条数过滤：读全量历史 → 过滤周末 → 取最近 days 条（记录数不足时全取）。
    """
    from datetime import datetime
    records = _load_history_raw()
    # 过滤周末（按交易日条数，而非自然日）
    weekdays = []
    for r in records:
        dt = datetime.strptime(r["date"], "%Y-%m-%d")
        if dt.weekday() < 5:
            weekdays.append(r)
    records = weekdays[-days:] if days > 0 else []

    dates = [r["date"] for r in records]
    series = []
    for sym in _resolve_symbols(symbols):  # SYMBOLS 注册表序
        key = sym.lower()
        raw = [r.get(key) for r in records]
        # GLD 价格乘以10，显示接近实际金价（美元/盎司）
        if key == "gld":
            raw = [v * 10 if v is not None else v for v in raw]
        values, change_7d = _normalize_series(raw)
        series.append({
            "key": key,
            "label": SYMBOLS[sym]["label"],
            "values": values,
            "change_7d": change_7d,
            "raw": raw,
        })
    return {"dates": dates, "series": series}


# ---- 最新日指数（value + change_pct 自算；status 复用最新 context）----

def _compute_latest(history: list[dict]):
    """从相邻历史记录计算最新日指数 value / change_pct。

    返回 (date, indices) 或历史为空时返回 None。
    - change_pct = (cur - prev) / prev * 100；prev 缺失 / 为 None / 为 0 → None。
    - 末行某符号为 None（该市场未开盘/已收盘）→ 值前向回填最近非空行该符号值，
      change_pct 强制 None（不虚构当日涨跌幅，前端显示数值 + "—"；决策 R5）。
    - status 字段在此置 None，由调用方从最新 context 合并。
    """
    if not history:
        return None
    last = history[-1]
    prev = history[-2] if len(history) >= 2 else None
    date = last["date"]
    indices = []
    for sym in SYMBOLS:
        key = sym.lower()
        raw = last.get(key)
        cur = raw
        if cur is None:
            for past in reversed(history[:-1]):
                if past.get(key) is not None:
                    cur = past[key]
                    break
        change_pct = None
        if raw is not None and prev is not None:
            base = prev.get(key)
            if base not in (None, 0):
                change_pct = (cur - base) / base * 100
        indices.append({
            "symbol": sym,
            "label": SYMBOLS[sym]["label"],
            "value": cur,
            "change_pct": change_pct,
            "status": None,
        })
    return date, indices


def _read_context_file(path: Path) -> dict | None:
    """单文件解析容错：坏 JSON / 非 dict / IO 错误 → None（不阻断回退遍历）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("context 读取失败，跳过该文件: %s (%s)", path.name, exc)
        return None
    if not isinstance(data, dict):
        log.warning("context 非 dict，跳过该文件: %s", path.name)
        return None
    return data


def _load_latest_context() -> dict | None:
    """最近有效 context：按文件名倒序返回第一个 sector_heat 有数据（gainers 非空）的
    context；全部无板块数据 → 返回最新的可解析 context；目录缺失/全坏 → None。"""
    if not CONTEXT_DIR.exists():
        return None
    files = sorted(CONTEXT_DIR.glob("*.json"), reverse=True)
    fallback = None
    for path in files:
        ctx = _read_context_file(path)
        if ctx is None:
            continue
        if fallback is None:
            fallback = ctx                     # 语义下限：最新的可解析文件
        sh = ctx.get("sector_heat")
        if isinstance(sh, dict) and sh.get("gainers"):
            return ctx                         # 最近一次板块取数成功的交易日
    return fallback

def _load_sector_heat() -> dict:
    """从最新 context 取 sector_heat（gainers/losers）；缺失 / 坏 → 空结构降级。"""
    ctx = _load_latest_context()
    if not isinstance(ctx, dict):
        return {"gainers": [], "losers": []}
    sh = ctx.get("sector_heat")
    if not isinstance(sh, dict):
        return {"gainers": [], "losers": []}
    return {
        "gainers": sh.get("gainers") or [],
        "losers": sh.get("losers") or [],
    }


# ---- 告警解析（直接使用本模块 ALERTS_DIR 常量）----

def _parse_alert_file(path: Path) -> dict | None:
    """解析告警 md（frontmatter + 字段块）。解析失败 → None（容错，不 500）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not fm_match:
        return None
    fm: dict[str, str] = {}
    for line in fm_match.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    body = text[fm_match.end():]

    def field(name: str) -> str | None:
        m = re.search(rf"{name}：([^\n]*)", body)
        return m.group(1).strip() if m else None

    def num(s: str | None) -> float | None:
        if s in (None, ""):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    chg_match = re.search(
        r"变化率：([+-]?\d+(?:\.\d+)?)%（阈值 ±([\d.]+)%）", body
    )
    return {
        "date": fm.get("date"),
        "type": fm.get("type"),
        "symbol": fm.get("symbol"),
        "level": fm.get("level"),
        "current": num(field("当前值")),
        "last": num(field("昨日收盘")),
        "change_pct": float(chg_match.group(1)) if chg_match else None,
        "threshold": float(chg_match.group(2)) if chg_match else None,
        "state": field("市场状态"),
        "suggestion": field("建议"),
        "report": field("相关报告"),
    }


def _load_alerts(limit: int = 10) -> list[dict]:
    """解析 alerts/ 下告警 md，按文件名（日期）倒序取最近 limit 条；目录缺失 / 空 → []。"""
    if not ALERTS_DIR.exists():
        return []
    files = sorted(ALERTS_DIR.glob("*.md"), reverse=True)
    out = []
    for f in files:
        parsed = _parse_alert_file(f)
        if parsed:
            out.append(parsed)
        if len(out) >= limit:
            break
    return out

# ---- 自选股（实时取数，config.json watchlist.stocks；零写盘）----

def _series_tail(points, n: int = 30) -> list:
    """截最近 n 点（保序）；空输入安全返回 []。"""
    if not points:
        return []
    return list(points[-n:])


def _build_watchlist_payload(stocks_cfg, values, series) -> dict:
    """构建自选股表格 + 趋势图双结构（同源一次返回）。

    stocks 行按配置序：symbol / label / value（当日收盘价，缺失为 None）/ change_pct
    （序列相邻日自算，与日报 _build_watchlist_view 同公式）。trend 与 /api/history
    同构（dates + 索引对齐的 values，归一化基准 100），供前端单图多标的复用。
    """
    stocks_out = []
    trend_items = []
    all_dates: set[str] = set()
    for it in stocks_cfg:
        sym = it["symbol"]
        label = it.get("label", sym)
        pts = _series_tail(series.get(sym) or [])
        # 涨跌幅：序列相邻日自算（与日报 _build_watchlist_view 同公式）
        change_pct = None
        if len(pts) >= 2 and pts[-2][1] not in (None, 0):
            change_pct = round((pts[-1][1] - pts[-2][1]) / pts[-2][1] * 100, 2)
        val = values.get(sym)
        # 失败行（value 缺失）按决策 1：change_pct 亦为 None（前端其余列「数据暂缺」）
        if val is None:
            change_pct = None
        stocks_out.append({
            "symbol": sym,
            "label": label,
            "value": val,
            "change_pct": change_pct,
        })
        # 趋势图：即便当日价缺失但历史在也入图（A 股盘中无收盘 ≠ 无历史）
        if pts:
            for d, _ in pts:
                all_dates.add(d)
            trend_items.append({"key": sym.lower(), "label": label, "pts": pts})
    # 对齐 dates 并集（字符串排序即时间序），按 dates 投影 raw 后归一化
    dates = sorted(all_dates)
    trend_series = []
    for item in trend_items:
        price_map = {d: c for d, c in item["pts"]}
        aligned_raw = [price_map.get(d) for d in dates]
        values_n, change_7d = _normalize_series(aligned_raw)
        trend_series.append({
            "key": item["key"],
            "label": item["label"],
            "values": values_n,
            "change_7d": change_7d,
            "raw": aligned_raw,
        })
    return {"stocks": stocks_out, "trend": {"dates": dates, "series": trend_series}}


def _load_watchlist() -> dict:
    """实时取数自选股。hidden=true 仅=无配置（前端隐藏）；有配置时取数失败
    仍返回 hidden=false + 空 stocks（前端占位可见，不静默隐藏，NF3）。
    优先读环境变量 WATCHLIST_STOCKS（JSON 格式），其次读 config.json。"""
    empty = {"stocks": [], "trend": {"dates": [], "series": []}}
    # 优先从环境变量读取（Railway 部署用）
    env_stocks = os.environ.get("WATCHLIST_STOCKS")
    if env_stocks:
        try:
            stocks = json.loads(env_stocks)
            if not stocks:
                return {"hidden": True, **empty}
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("WATCHLIST_STOCKS 环境变量解析失败: %s", exc)
            return {"hidden": True, **empty}
    else:
        try:
            cfg = load_config()
        except Exception as exc:
            log.warning("自选股配置读取失败，视为无配置: %s", exc)
            return {"hidden": True, **empty}
        stocks = (cfg.get("watchlist") or {}).get("stocks") or []
        if not stocks:
            return {"hidden": True, **empty}
    try:
        values, series, _errors = fetch_watchlist(stocks)
        return {"hidden": False, **_build_watchlist_payload(stocks, values, series)}
    except Exception as exc:
        log.warning("自选股取数失败，降级空结构: %s", exc)
        return {"hidden": False, **empty}


# ---- 端点 ----

@app.get("/api/history")
def api_history(days: int = Query(30, ge=1, le=90), symbols: str | None = Query(None)) -> dict:
    """最近 N 交易日趋势数据（Chart.js 友好）；days 默认 30，symbols 默认全量。"""
    return _build_history_payload(days=days, symbols=symbols)


@app.get("/api/latest")
def api_latest() -> dict:
    """最新日 10 指数概览 + 板块热度；status 复用最新 context。"""
    records = _last_records(7)
    result = _compute_latest(records)
    if result is None:
        return {"date": None, "indices": [], "sector_heat": {"gainers": [], "losers": []}}

    date, indices = result
    ctx = _load_latest_context()
    status_map: dict[str, str | None] = {}
    if isinstance(ctx, dict):
        ctx_indices = ctx.get("indices", {})
        for sym in SYMBOLS:
            entry = ctx_indices.get(sym) if isinstance(ctx_indices, dict) else None
            status_map[sym] = entry.get("status") if isinstance(entry, dict) else None
    for it in indices:
        it["status"] = status_map.get(it["symbol"])

    return {"date": date, "indices": indices, "sector_heat": _load_sector_heat()}


@app.get("/api/alerts")
def api_alerts() -> list[dict]:
    """最近 10 条告警记录（按日期倒序）。"""
    return _load_alerts(10)


@app.get("/api/watchlist")
def api_watchlist() -> dict:
    """自选股实时取数（config.json watchlist.stocks）；失败降级空结构（HTTP 200，不 500）。"""
    return _load_watchlist()


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """渲染单页看板。"""
    template = _TEMPLATES.get_template("index.html")
    resp = HTMLResponse(template.render())
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp
