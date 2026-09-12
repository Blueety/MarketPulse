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
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src import storage as st
from src.analyzer import ALERTS_DIR as _ALERTS_DIR
from src.analyzer import classify_move, classify_vix
from src.analyzer import CONTEXT_DIR as _CONTEXT_DIR
from src.analyzer import load_watchlist_snapshot
from src.config import load_config

# 三十三期：资讯快照（Hermes 侧 tavily 搜索后落盘，契约见 docs/architecture.md 决策行；
# 定义在使用方 web.app——monkeypatch 打这里，测试隔离不依赖真实 data/ 文件）
NEWS_FILE = Path(__file__).resolve().parent.parent / "data" / "news.json"
from src.fetcher import SYMBOLS, fetch_watchlist

log = logging.getLogger("marketpulse")

# 模块级路径常量：解析函数一律引用本模块的这些名字（测试 monkeypatch 落点）。
ALERTS_DIR = _ALERTS_DIR
CONTEXT_DIR = _CONTEXT_DIR

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# 自选股实时取数 TTL 缓存（uvicorn 单 worker 下语义一致；降低 Yahoo/AkShare 重复取数）
_WATCH_TTL = 90  # 秒
_watch_cache = {"ts": 0.0, "payload": None}
_watch_lock = threading.Lock()

_TEMPLATES = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

app = FastAPI(title="MarketPulse Web 看板")

# 三十一期（D2，P0）：Railway 临时文件系统 + DB 入 gitignore → 每次部署 DB 不存在，
# 启动恢复链（data/backup/*.json 按月合并 → 旧 history.json 兼容读 → 空库「数据暂缺」）
# 是 Railway 的主数据来源而非兜底。MP_SKIP_RESTORE=1 供 pytest 等场景跳过（防写真实 DB）。
# 恢复只对空库触发（幂等），是 web 对自身 DB 副本的一次性引导写入，不违反只读边界。
@app.on_event("startup")
def _restore_history_db() -> None:
    if os.environ.get("MP_SKIP_RESTORE") == "1":
        log.info("MP_SKIP_RESTORE=1，跳过 history DB 启动恢复")
        return
    try:
        outcome = st.restore_if_empty()
        if outcome == "backup":
            log.info("history DB 启动恢复完成（来源: data/backup/ 按月合并）")
        elif outcome == "json":
            log.info("history DB 启动恢复完成（来源: 旧 data/history.json 兼容导入）")
        elif outcome == "empty":
            log.warning("history DB 为空且无可用恢复源，页面将显示「数据暂缺」")
    except Exception as exc:
        log.warning("history DB 启动恢复失败，按空库运行: %s", exc)

# 静态资源挂 /static（仅 style.css 等源码资源，不落盘生成物）。
STATIC_DIR.mkdir(parents=True, exist_ok=True)


class _RevalidateStatic(StaticFiles):
    """静态资源一律加 `Cache-Control: no-cache`（= 每次协商，未变则 304，不浪费带宽）。

    StaticFiles 默认**不下发任何 Cache-Control** → 浏览器按「(Date − Last-Modified) 的 10%」
    启发式估算新鲜度，可长达数小时/天且**连协商请求都不发** → 出现「代码改了、页面没变」。
    HTML 路由已带 no-cache，反而更迷惑：页面是新的、CSS 是旧的（2026-09-13 用户把旧标签页
    里的旧 CSS 误判为「滚动条被改回去了」，实为启发式缓存命中）。
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/static", _RevalidateStatic(directory=str(STATIC_DIR)), name="static")


def _asset_version() -> str:
    """静态资源版本号 = style.css / app.js 的最大 mtime（秒），供模板拼 `?v=`。

    与 `Cache-Control: no-cache` 双保险：万一某层缓存（IDE 预览 webview / CDN / 代理）忽略
    缓存头，资源 URL 变化也会强制换新副本。取 mtime 而非手写版本号 = 不会忘记递增。
    """
    try:
        return str(int(max((STATIC_DIR / n).stat().st_mtime for n in ("style.css", "app.js"))))
    except OSError:
        return "0"


# ---- 历史解析（三十一期：SQLite storage；损坏 DB → []，纪律同旧 JSON 容错）----

def _load_history_raw() -> list[dict]:
    """读取历史宽记录（date 升序、None 语义保留、全键补 None）。"""
    return st.rows_to_records(st.query_history())


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


def _build_history_payload(days: int = 30, symbols: str | None = None,
                           start_date: str | None = None, end_date: str | None = None) -> dict:
    """展开为 Chart.js 友好结构：dates + N 组 series（key=小写 symbol）。

    每个序列归一化为相对基准百分比（窗口首个非空值 = 100），另附 change_7d
    （窗口涨跌幅，键名保留向后兼容）与 raw（等长原始值，GLD 已 ×10，与图线一致）。
    过滤：显式 start_date/end_date 优先（日期字符串比较）；否则按交易日条数取最近 days 条
    （记录数不足时全取）。
    """
    from datetime import datetime
    records = _load_history_raw()
    # 过滤周末（按交易日条数，而非自然日）
    weekdays = []
    for r in records:
        dt = datetime.strptime(r["date"], "%Y-%m-%d")
        if dt.weekday() < 5:
            weekdays.append(r)
    if start_date or end_date:
        weekdays = [r for r in weekdays
                    if (not start_date or r["date"] >= start_date)
                        and (not end_date or r["date"] <= end_date)]
    else:
        weekdays = weekdays[-days:] if days > 0 else []
    records = weekdays

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
        src_date = None
        if cur is None:
            for past in reversed(history[:-1]):
                if past.get(key) is not None:
                    cur = past[key]
                    src_date = past["date"]
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
            "source_date": src_date,
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

def _sector_payload(ctx: dict | None, key: str) -> dict:
    """从 context 抽取单个板块热度键（sector_heat / us_sector_heat）→ {gainers, losers}。

    ctx 非 dict / 键缺失 / 非 dict → 双空列表降级（前端安全遍历）。
    """
    sh = ctx.get(key) if isinstance(ctx, dict) else None
    if not isinstance(sh, dict):
        return {"gainers": [], "losers": []}
    return {
        "gainers": sh.get("gainers") or [],
        "losers": sh.get("losers") or [],
    }


def _load_sector_heat() -> dict:
    """从最近有效 context 取 A 股 sector_heat（gainers/losers）；缺失 / 坏 → 空结构降级。"""
    return _sector_payload(_load_latest_context(), "sector_heat")


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


def _watchlist_config() -> list[dict]:
    """自选股配置：env WATCHLIST_STOCKS（JSON，Railway 用）> config.json watchlist.stocks；
    无配置 / 解析失败 → []（语义与三十期前一致：空配置 = 前端隐藏）。"""
    env_stocks = os.environ.get("WATCHLIST_STOCKS")
    if env_stocks:
        try:
            stocks = json.loads(env_stocks)
            return stocks or []
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("WATCHLIST_STOCKS 环境变量解析失败: %s", exc)
            return []
    try:
        cfg = load_config()
    except Exception as exc:
        log.warning("自选股配置读取失败，视为无配置: %s", exc)
        return []
    return (cfg.get("watchlist") or {}).get("stocks") or []


# ---- 风险偏好（三十二期：纯函数合成，数据零新增取数）----

_RISK_VIX_5D_PCT = 5.0   # VIX 5 日变化打分阈值（%）；模块级常量，V1 不入 config（plan §5.5）


def _correlation_payload(ctx) -> list:
    """context correlation 显著对直通（list 原样返回，其余 → []；容错语义同 _sector_payload）。

    不做逐条字段校验：生产端 generate_context 的契约已保证 {a,b,pair,r,n}，web 侧过度防御反而藏错。
    """
    if isinstance(ctx, dict) and isinstance(ctx.get("correlation"), list):
        return ctx["correlation"]
    return []


def _compute_risk_appetite(indices: list[dict], records: list[dict]) -> dict:
    """风险偏好合成（纯函数）：VIX 状态 + MOVE 状态 + VIX 5 日变化三点打分。

    状态词表复用 analyzer.classify_vix/classify_move（阈值 env 调用时复核，单一事实来源，
    前端零阈值拷贝）。VIX value 缺失 → level=None（前端「数据暂缺」）；factors 尽列可得项。
    5 日变化 = 最近 6 个非 None vix 收盘首尾比（%），不足 6 个 → 因子缺省不计分。
    """
    vix = next((it.get("value") for it in indices if it.get("symbol") == "VIX"), None)
    move = next((it.get("value") for it in indices if it.get("symbol") == "MOVE"), None)
    factors: list[dict] = []
    score = 0
    if vix is not None:
        state = classify_vix(vix)[0]
        impact = 1 if state == "平静" else (-1 if state == "恐慌" else 0)
        score += impact
        factors.append({"name": "VIX", "value": vix, "state": state, "impact": impact})
    if move is not None:
        state = classify_move(move)[0]
        impact = -1 if state == "恐慌" else 0   # 债市波动只在剧烈时拉低偏好，平静不给正分
        score += impact
        factors.append({"name": "MOVE", "value": move, "state": state, "impact": impact})
    closes = [r.get("vix") for r in records if r.get("vix") is not None][-6:]
    if len(closes) >= 6 and closes[0]:
        change_pct = (closes[-1] - closes[0]) / closes[0] * 100
        impact = 1 if change_pct <= -_RISK_VIX_5D_PCT else (
            -1 if change_pct >= _RISK_VIX_5D_PCT else 0)
        score += impact
        factors.append({"name": "VIX 5日", "change_pct": round(change_pct, 1), "impact": impact})
    level = None
    if vix is not None:
        if score >= 1:
            level = "high"
        elif score <= -1:
            level = "low"
        else:
            level = "neutral"
    return {"level": level, "score": score, "factors": factors}


def _load_watchlist() -> dict:
    """自选股：快照文件优先（报告链路落盘，请求路径零联网），配置比对失败 / 无快照 /
    快照构建异常时回退既有实时取数路径（慢但正确，防改配置后展示旧标的）。
    hidden=true 仅=无配置（前端隐藏）；有配置时失败仍返回 hidden=false + 空 stocks
    （前端占位可见，不静默隐藏，NF3）。"""
    empty = {"stocks": [], "trend": {"dates": [], "series": []}}
    cfg = _watchlist_config()
    if not cfg:
        return {"hidden": True, **empty}
    snap = load_watchlist_snapshot()
    if snap and ([s.get("symbol") for s in snap["stocks"]] == [s.get("symbol") for s in cfg]):
        try:
            payload = _build_watchlist_payload(snap["stocks"], snap["values"], snap["series"])
            payload["as_of"] = snap.get("saved_at")   # 数据时点标注（新字段，向后兼容）
            return {"hidden": False, **payload}
        except Exception as exc:
            log.warning("自选股快照构建失败，回退实时取数: %s", exc)
    try:
        values, series, _errors = fetch_watchlist(cfg)
        return {"hidden": False, **_build_watchlist_payload(cfg, values, series)}
    except Exception as exc:
        log.warning("自选股取数失败，降级空结构: %s", exc)
        return {"hidden": False, **empty}


# ---- 宏观标的（美元指数 / 10Y 美债 / 原油；实时取数，零写盘）----

# 内置默认标的（宏观为只读行情，无「未配置即隐藏」语义）：env MACRO_STOCKS > config.json macro.stocks > 此默认
_MACRO_DEFAULT: list[dict] = [
    {"symbol": "DX-Y.NYB", "label": "美元指数"},
    {"symbol": "^TNX", "label": "10Y美债"},
    {"symbol": "CL=F", "label": "原油"},
]

_MACRO_TTL = 90  # 秒，与自选股 TTL 同量级
_macro_cache: dict = {"ts": 0.0, "payload": None}
_macro_lock = threading.Lock()


def _load_macro_stocks() -> list[dict]:
    """宏观标的配置：env MACRO_STOCKS（JSON）> config.json 的 macro.stocks > 内置默认。

    非法 JSON / 非列表 / 空列表 / 读取异常 → 内置默认（保证端点开箱可用）。
    仅保留含 symbol 的 dict 项。
    """
    def _normalize(items) -> list[dict]:
        if not isinstance(items, list):
            return []
        return [it for it in items if isinstance(it, dict) and it.get("symbol")]

    raw = os.environ.get("MACRO_STOCKS")
    if raw:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("MACRO_STOCKS 环境变量解析失败，回退内置默认: %s", exc)
            return list(_MACRO_DEFAULT)
        picked = _normalize(data)
        return picked or list(_MACRO_DEFAULT)
    try:
        cfg = load_config()
    except Exception as exc:
        log.warning("宏观配置读取失败，回退内置默认: %s", exc)
        return list(_MACRO_DEFAULT)
    picked = _normalize((cfg.get("macro") or {}).get("stocks"))
    return picked or list(_MACRO_DEFAULT)


def _load_macro() -> dict:
    """实时取宏观标的（复用自选股取数链路）；失败降级空结构（HTTP 200，不 500）。"""
    empty = {"stocks": [], "trend": {"dates": [], "series": []}}
    stocks = _load_macro_stocks()
    if not stocks:
        return empty
    try:
        values, series, _errors = fetch_watchlist(stocks)
        return _build_watchlist_payload(stocks, values, series)
    except Exception as exc:
        log.warning("宏观标的取数失败，降级空结构: %s", exc)
        return empty


# ---- 端点 ----

@app.get("/api/history")
def api_history(
    days: int = Query(30, ge=1, le=3650),   # D9：永久保留后放宽上限（原 365）
    symbols: str | None = Query(None),
    start_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    """趋势数据；days 默认 30，symbols 默认全量；显式 start_date/end_date 优先（忽略 days）。"""
    return _build_history_payload(days=days, symbols=symbols,
                                  start_date=start_date, end_date=end_date)


@app.get("/api/latest")
def api_latest() -> dict:
    """最新日 10 指数概览 + A 股/美股板块热度；status 与板块同源复用最新有效 context。"""
    ctx = _load_latest_context()
    empty_sectors = {"sector_heat": {"gainers": [], "losers": []},
                     "us_sector_heat": {"gainers": [], "losers": []}}
    records = _last_records(10)   # 三十二期：7→10，供风险偏好 5 日变化取数
    result = _compute_latest(records)
    if result is None:
        return {"date": None, "indices": [], **empty_sectors,
                "risk_appetite": {"level": None, "score": 0, "factors": []},
                "correlation": _correlation_payload(ctx)}

    date, indices = result
    status_map: dict[str, str | None] = {}
    if isinstance(ctx, dict):
        ctx_indices = ctx.get("indices", {})
        for sym in SYMBOLS:
            entry = ctx_indices.get(sym) if isinstance(ctx_indices, dict) else None
            status_map[sym] = entry.get("status") if isinstance(entry, dict) else None
    for it in indices:
        it["status"] = status_map.get(it["symbol"])

    return {
        "date": date,
        "indices": indices,
        "sector_heat": _sector_payload(ctx, "sector_heat"),
        "us_sector_heat": _sector_payload(ctx, "us_sector_heat"),
        "risk_appetite": _compute_risk_appetite(indices, records),
        "correlation": _correlation_payload(ctx),
    }


@app.get("/api/alerts")
def api_alerts() -> list[dict]:
    """最近 10 条告警记录（按日期倒序）。"""
    return _load_alerts(10)


# ---- 最新资讯（三十三期：Hermes 契约先行，web 只读消费）----

def _load_news() -> dict:
    """读取资讯快照 data/news.json（所有权归 Hermes，web 只读）。

    容错：文件缺失 / 坏 JSON / 非 dict / items 非列表 → 空结构（HTTP 200 恒定，不 500）。
    条目过滤：dict 且 title 非空 且 url 以 http(s):// 开头（防 javascript: 注入）；
    source/published/summary 缺省 ""；截前 8 条（cap 8，防超量撑破卡片）。
    """
    empty = {"date": None, "items": [], "count": 0}
    try:
        data = json.loads(NEWS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        if NEWS_FILE.exists():
            log.warning("资讯文件读取失败，按空结构处理: %s", exc)
        return empty
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        log.warning("资讯文件结构异常，按空结构处理")
        return empty
    items = []
    for it in data["items"]:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        url = str(it.get("url") or "").strip()
        if not title or not url.lower().startswith(("http://", "https://")):
            continue
        items.append({"title": title, "url": url,
                      "source": str(it.get("source") or ""),
                      "published": str(it.get("published") or ""),
                      "summary": str(it.get("summary") or "")})
    items = items[:8]
    date = data.get("date")
    return {"date": str(date) if date else None, "items": items, "count": len(items)}


@app.get("/api/news")
def api_news() -> dict:
    """最新资讯（data/news.json，Hermes 落盘；未接入/坏文件 → 空结构，200 恒定）。"""
    return _load_news()


def _watch_failed(payload: dict) -> bool:
    """fetch 视为失败：有配置(hidden=False) 但无 stocks 数据（取数失败降级）。"""
    return bool(payload) and not payload.get("hidden") and not payload.get("stocks")


@app.get("/api/watchlist")
def api_watchlist() -> dict:
    """自选股实时取数（TTL 缓存；取数失败且有旧缓存 → 回退旧缓存并标 stale）。"""
    now = time.time()
    with _watch_lock:
        cached = _watch_cache["payload"]
        if cached is not None and (now - _watch_cache["ts"]) < _WATCH_TTL:
            return cached
    fresh = _load_watchlist()
    if _watch_failed(fresh):
        with _watch_lock:
            if _watch_cache["payload"] is not None:
                stale = dict(_watch_cache["payload"])
                stale["stale"] = True
                return stale
        return fresh  # 无缓存：回退现状（降级空结构，HTTP 200，与原端点一致）
    with _watch_lock:
        _watch_cache["ts"] = time.time()
        _watch_cache["payload"] = fresh
    return fresh


@app.get("/api/macro")
def api_macro() -> dict:
    """宏观标的实时取数（TTL 缓存；失败降级空结构，只缓存成功结果）。"""
    now = time.time()
    with _macro_lock:
        cached = _macro_cache["payload"]
        if cached is not None and (now - _macro_cache["ts"]) < _MACRO_TTL:
            return cached
    fresh = _load_macro()
    if fresh.get("stocks"):
        with _macro_lock:
            _macro_cache["ts"] = time.time()
            _macro_cache["payload"] = fresh
    return fresh


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """渲染单页看板。"""
    template = _TEMPLATES.get_template("index.html")
    resp = HTMLResponse(template.render(asset_v=_asset_version()))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp
