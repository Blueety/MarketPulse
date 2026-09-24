"""MarketPulse Web 看板：FastAPI 应用。

只读解析现有产物（data/history.json / context/*.json / alerts/*.md），提供单页看板
与 4 个 JSON API（含自选股实时取数 /api/watchlist，经 src.fetcher.fetch_watchlist，零写盘；响应含 hidden 键：无配置隐藏、有配置必显卡失败占位）。
零侵入日报 / 快照主流程：本进程绝不写 data / alerts / context。

路径常量从 analyzer 复用单一事实来源，但在此模块重新绑定为模块级名字，供解析函数
直接引用——测试按项目纪律 monkeypatch 这些名字（打在使用方模块 web.app，而非定义方
analyzer），因此解析函数**不调用** analyzer.load_history / alerter 等引用 analyzer 常量的函数。
"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from src import storage as st
from src.analyzer import ALERTS_DIR as _ALERTS_DIR
from src.analyzer import _pearson, _returns      # 宏观相关性复用（2026-09-14）
from src.analyzer import classify_move, classify_vix
from src.analyzer import CONTEXT_DIR as _CONTEXT_DIR
from src.analyzer import load_watchlist_snapshot
from src.analyzer import reload_config_snapshots as _reload_config
from src.config import load_config

# 三十三期：资讯快照（Hermes 侧 tavily 搜索后落盘，契约见 docs/architecture.md 决策行；
# 定义在使用方 web.app——monkeypatch 打这里，测试隔离不依赖真实 data/ 文件）
NEWS_FILE = Path(__file__).resolve().parent.parent / "data" / "news.json"
from src.fetcher import SYMBOLS, _fetch_yahoo_watch, fetch_watchlist
from src import settings_store as _settings
# 经济数据（BLS）：模块级导入，测试 monkeypatch 打使用方 web.app（与既有纪律一致）
from src.econ_fetcher import build_econ_payload, fetch_econ_series
# 中国宏观（AkShare）：与 BLS 版**平行**的独立模块（数据源/序列数/失败语义都不同）
from src.cn_econ_fetcher import (
    CN_ECON_SERIES,
    build_cn_econ_payload,
    fetch_bond_yield_curves,
    fetch_cn_econ_raw,
    group_keys,
)
# 事件时间线（2026-09-18）：日历（db）× 行情影响 × 新闻叙事 → 组装成页面 payload
from src import timeline as _timeline
# 回测（2026-09-20）：纯统计在 src/backtest.py（与 CLI **同一份实现**），web 只负责组装响应
from src import backtest as _backtest

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

# ------------------------------------------------------------------ 访问控制（HTTP Basic Auth，2026-09-19）
# 任务档 tasks/2026-09-19-web-basic-auth/（方案 A）。零新依赖（stdlib `base64` + `hmac`）、
# 零前端改动：Basic Auth 是**唯一**浏览器原生支持、且能一次性覆盖「页面导航 + 静态资源 + XHR」
# 三类请求的方案 —— header 型 Token 在 `<a href="/macro">` 跳转时会直接失败。
#
# ⚠️ R9：**env 一律现读，绝不求值成模块级常量**。常量在 import 时定型 ⇒ 单测 monkeypatch env 不生效。
#    `os.environ.get` 的开销相对一次 HTTP 请求可忽略，换来的是可测性。
#
# ⚠️ D-1（已裁定）：未配置凭据时**fail-open**（放行 + 启动 WARNING），不是 fail-closed。
#    理由：与项目既有纪律一致（失败降级不中断，git_ops 失败仅记日志）；且 fail-closed 会锁死
#    本地开发与验收。**代价**：忘了配 env = 回到未鉴权状态 ⇒ 靠启动 WARNING + 部署清单兜住。
def _auth_user() -> str:
    return (os.environ.get("MP_AUTH_USER") or "").strip()


def _auth_pass() -> str:
    # ⚠️ 密码不做 strip：空格可能是合法字符（随机口令一般不含，但改了会让"配了却登不上"）
    return os.environ.get("MP_AUTH_PASS") or ""


def _auth_disabled() -> bool:
    return os.environ.get("MP_AUTH_DISABLED") == "1"


def auth_enabled() -> bool:
    """鉴权是否启用（现读 env；见上面 R9 注释）。"""
    return bool(_auth_user()) and bool(_auth_pass()) and not _auth_disabled()


def _authorized(header: str) -> bool:
    """`Authorization` 头校验：**任何异常形态都返回 False（401），绝不抛给 FastAPI 变成 500**。

    - `Basic ` 前缀按 RFC 大小写不敏感 ⇒ 统一小写比较（plan §5 Step 2 要点①）。
    - `hmac.compare_digest` **用户名与密码都要**（防时序侧信道；只比一个等于没防）。
    - ⚠️ 2026-09-24（BUG-004）：比较**统一走 bytes**。`compare_digest` 对含非 ASCII 的 `str`
      直接抛 `TypeError: comparing strings with non-ASCII characters is not supported`
      （CPython 语义，防的是 `str` 的 Unicode 归一化恒时假象）⇒ 中文口令/用户名**永远 500**
      —— 而中文口令是本产品用户最可能的选择，且**未认证的任何人都能触发**（刷日志 + 报错页）。
    """
    try:
        if len(header) < 6 or header[:6].lower() != "basic ":
            return False
        try:
            raw = base64.b64decode(header[6:], validate=True).decode("utf-8")
        except Exception:               # noqa: BLE001 —— 非 base64 / 坏填充 / 非 UTF-8 一律 401
            return False
        if ":" not in raw:
            return False
        u, p = raw.split(":", 1)
        # 契约（见 docstring）：**整个函数体**都在 try 内 —— 任何路径都不许把异常漏给 FastAPI。
        return (hmac.compare_digest(u.encode("utf-8"), _auth_user().encode("utf-8"))
                and hmac.compare_digest(p.encode("utf-8"), _auth_pass().encode("utf-8")))
    except Exception:                   # noqa: BLE001 —— 含 `encode` 遇孤立代理字符的 UnicodeEncodeError
        return False


def _unauthorized() -> JSONResponse:
    """401。⚠️ **必须带 `WWW-Authenticate`**（D-7）：缺该头浏览器**不弹窗**，
    表现为"反复失败且没有任何提示"，极难自查。"""
    return JSONResponse({"detail": "Unauthorized"}, status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="MarketPulse"'})


@app.middleware("http")
async def _basic_auth(request: Request, call_next):
    """全站 Basic Auth（页面 + 10 个 API + `/static/*`）。

    - **不豁免静态资源**（D-3）：Basic Auth 下浏览器会自动带上凭据；而豁免会制造
      "页面能开、数据全 401"的半开状态，反而更难排查。
    - `/healthz` 用**精确相等**放行（不做前缀匹配，防 `/healthz/../` 类绕过）。
    """
    if not auth_enabled():
        return await call_next(request)
    if request.url.path == "/healthz":
        return await call_next(request)
    if not _authorized(request.headers.get("authorization", "")):
        return _unauthorized()
    return await call_next(request)


@app.get("/healthz")
def healthz() -> dict:
    """Railway healthcheck（**无鉴权、不查 DB**）。

    🔴 R1：`railway.toml` 的 `healthcheckPath` 已从 `/` 改到本端点 —— 若给 `/` 返 401，
    配合 `restartPolicyType=ON_FAILURE` + `MaxRetries=10` 会让部署**陷入重启循环直到失败**。
    ⚠️ 刻意**不查 DB**：DB 挂了重启也修不好，不该让健康检查背锅（D-2）。
    """
    return {"status": "ok"}


@app.on_event("startup")
def _log_auth_state() -> None:
    """启动即告知鉴权状态（R3：忘了配 env 等同没做 ⇒ 必须醒目）。"""
    if auth_enabled():
        log.info("web 鉴权已启用（HTTP Basic Auth，用户 %s）", _auth_user())
    elif _auth_disabled():
        log.warning("web 鉴权已由 MP_AUTH_DISABLED=1 关闭 —— **仅限本地开发与自动化验收，勿用于公网**")
    else:
        log.warning("web 鉴权未启用（MP_AUTH_USER / MP_AUTH_PASS 未配置）⇒ 全站裸奔；"
                    "公网部署前请在 Railway Variables 设置这两个 env")

# 参与 `?v=` 版本号计算的静态资源（新增前端文件记得加进来）
# ⚠️ 2026-09-14（macro-chart-crosshair）：新增 `chart-crosshair.js` 必须在此登记 ——
#    否则"改它不换 URL"，验证时会吃到旧副本（正是本行注释所警告的坑）。
_ASSET_FILES = ("style.css", "app.js", "macro.js", "chart-crosshair.js", "macro_cn.js", "timeline.js",
                "backtest.js", "settings.js",
                # 液态玻璃皮肤（2026-09-23）：目录名可写进元组 —— `_asset_version()` 按**文件**逐个
                # 取 mtime（`STATIC_DIR / n`），故这里的每一项都必须是**文件**路径，不能只写目录。
                "skin.js", "skin/tokens.css", "skin/liquid-skin.css", "skin/motion.css", "skin/mp-skin.css",
                "vendor/liquid-glass/liquid-glass.css", "vendor/liquid-glass/liquid-glass.esm.js")


def _asset_version() -> str:
    """静态资源版本号 = 前端静态资源的最大 mtime（秒），供模板拼 `?v=`。

    与 `Cache-Control: no-cache` 双保险：万一某层缓存（IDE 预览 webview / CDN / 代理）忽略
    缓存头，资源 URL 变化也会强制换新副本。取 mtime 而非手写版本号 = 不会忘记递增。
    ⚠️ 新增静态资源（如 macro.js）必须加进 `_ASSET_FILES`，否则改它不会换 URL → 验证时吃旧副本。
    """
    try:
        mtimes = [(STATIC_DIR / n).stat().st_mtime for n in _ASSET_FILES if (STATIC_DIR / n).exists()]
        return str(int(max(mtimes))) if mtimes else "0"
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


def _read_text(path: Path) -> str | None:
    """容错读取 UTF-8 文本：非 UTF-8 字节按**替换符解码**（不抛 `UnicodeDecodeError`）；IO 失败 → None。

    BUG-007（2026-09-24）：此前各读盘点直接用 `path.read_text(encoding="utf-8")`，半写 / 坏字节文件会抛
    `UnicodeDecodeError`（`ValueError` 子类，不在 `except (json.JSONDecodeError, OSError)` 内）⇒ 出口 500，
    违反本模块「坏 JSON → 空结构、HTTP 200 恒定、不 500」的契约。本模块所有「读文本 + `json.loads`」
    的读盘点统一走这里 ⇒ 坏字节退化为「解码出替换符 → `json.loads` 判坏 JSON」的既有降级口径。
    """
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def _read_context_file(path: Path) -> dict | None:
    """单文件解析容错：坏 JSON / 坏字节 / 非 dict / IO 错误 → None（不阻断回退遍历）。"""
    text = _read_text(path)
    if text is None:
        log.warning("context 读取失败，跳过该文件: %s", path.name)
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("context 解析失败，跳过该文件: %s (%s)", path.name, exc)
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

SECTOR_LOOKBACK_MAX = 5          # 板块回看上限（个 context 文件 ≈ 5 个交易日）


def _find_context_with_key(key: str, max_lookback: int = SECTOR_LOOKBACK_MAX):
    """按文件名倒序找第一个 `key.gainers` 非空的 context → `(ctx, 日期 stem)`；找不到 → `(None, None)`。

    **逐键独立回看**：`sector_heat`（A股，1 个新浪请求）与 `us_sector_heat`（美股，11 个 Yahoo
    请求）是同一天**独立取数、独立失败**的，所以不能拿"A股 有数据"当作整份 context 有效的判据
    —— 否则 A股 成功、美股失败的日子会把美股的空值一起带回来（2026-09-14 实测）。
    超过 `max_lookback` 个文件仍无数据 → 返回空：宁可空白，也不展示过旧快照（盘面误导）。
    坏 JSON 复用 `_read_context_file` 的容错（跳过该文件继续回看）。
    """
    if not CONTEXT_DIR.exists():
        return None, None
    for i, path in enumerate(sorted(CONTEXT_DIR.glob("*.json"), reverse=True)):
        if i >= max_lookback:
            break
        ctx = _read_context_file(path)
        if ctx is None:
            continue                      # 坏文件 / 非 dict：跳过，继续回看
        val = ctx.get(key)
        if not isinstance(val, dict) or not val.get("gainers"):
            continue
        return ctx, path.stem             # 文件名 stem 即日期（YYYY-MM-DD）
    return None, None


def _sector_payload(key: str) -> dict:
    """单键独立回看 → `{gainers, losers, as_of}`；`as_of=None` 表示无可用数据（前端显示空态）。

    `as_of` 只在本函数的返回值里生成，**不落盘** —— `context.json` 必须保持"当天真实快照"
    语义（写入端回填会污染它，且对已写下的历史文件无效）。
    """
    ctx, as_of = _find_context_with_key(key)
    sh = ctx.get(key) if isinstance(ctx, dict) else None
    if not isinstance(sh, dict):
        return {"gainers": [], "losers": [], "as_of": None}
    return {
        "gainers": sh.get("gainers") or [],
        "losers": sh.get("losers") or [],
        "as_of": as_of,
    }


def _load_sector_heat() -> dict:
    """A 股 sector_heat：单键独立回看（含 as_of）；缺失 / 坏 / 超回溯上限 → 空结构降级。"""
    return _sector_payload("sector_heat")


# ---- 告警解析（直接使用本模块 ALERTS_DIR 常量）----

def _parse_alert_file(path: Path) -> dict | None:
    """解析告警 md（frontmatter + 字段块）。解析失败（含坏字节 / IO 错误）→ None（容错，不 500）。"""
    text = _read_text(path)
    if text is None:
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


def _build_watchlist_payload(stocks_cfg, values, series, tail: int = 30) -> dict:
    """构建自选股表格 + 趋势图双结构（同源一次返回）。

    tail：趋势序列截取深度（默认 30；三十四期 /api/macro 传 400 补全黄金 1Y 视图）。

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
        pts = _series_tail(series.get(sym) or [], tail)
        # 涨跌幅：序列相邻日自算（与日报 _build_watchlist_view 同公式）
        change_pct = None
        if len(pts) >= 2 and pts[-2][1] not in (None, 0):
            change_pct = round((pts[-1][1] - pts[-2][1]) / pts[-2][1] * 100, 2)
        val = values.get(sym)
        # 失败行（value 缺失）按决策 1：change_pct 亦为 None（前端其余列「数据暂缺」）
        if val is None:
            change_pct = None
        # 持仓盈亏（2026-09-20 portfolio-pnl）：cost 可选；value/cost 任一缺失 ⇒ None（**不算 0**，
        #   "没录成本"与"没亏没赚"是两回事，同 TL-6「不显示假 0.00%」纪律）。前端只渲染，不做除法。
        cost = it.get("cost")
        try:
            cost_f = float(cost) if cost not in (None, "", 0) else None
        except (TypeError, ValueError):
            cost_f = None
        pnl_pct = round((val - cost_f) / cost_f * 100, 2) if (val is not None and cost_f) else None
        stocks_out.append({
            "symbol": sym,
            "label": label,
            "value": val,
            "change_pct": change_pct,
            "cost": cost_f,
            "pnl_pct": pnl_pct,
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
    # 组合概览：**有成本标的的等权平均**（无 shares ⇒ 算不出金额/市值/加权收益，
    #   plan §0-3：显式标注"未含份额"，不得让用户误读为组合总收益）。
    pnls = [s["pnl_pct"] for s in stocks_out if s["pnl_pct"] is not None]
    overview = {"covered": len(pnls), "total": len(stocks_out),
                "avg_pnl_pct": (round(sum(pnls) / len(pnls), 2) if pnls else None)}
    return {"stocks": stocks_out, "overview": overview,
            "trend": {"dates": dates, "series": trend_series}}


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
    {"symbol": "GC=F", "label": "黄金COMEX"},   # 三十四期：黄金报价位 GLD×10 → COMEX 期货
]

# 宏观 TTL：2026-09-14 由 90s 提到 **300s**。理由：本端点数据量扩了 3 倍（range 2y→5y，
# 实测 trend.dates 400 → 1258），90s TTL 下用户隔 90 秒刷新就吃一次 ~2.2s 冷启动；
# 而宏观页的 5Y 序列是给 1M~5Y 时间范围用的，秒级刷新对它没有价值。
# ⚠️ 为什么不是 10 分钟：本端点**同时供首页 4 张宏观卡**（美元/10Y/原油/黄金，都是**盘中交易**品种），
#    首页「刷新数据」按钮也走它 → TTL 过长会让手动刷新拿不到新价。5 分钟是折中。
#    若将来宏观页改为独立端点取数（不复用首页链路），可再放宽。
_MACRO_TTL = 300  # 秒
_macro_cache: dict = {"ts": 0.0, "payload": None}
_macro_lock = threading.Lock()

# 经济数据（BLS）TTL 缓存。
# ⚠️ **必须**是小时级，不能"对齐 /api/macro 的 90s"：BLS 无 Key 限额 **25 次查询 / 日 / IP**，
#   90s TTL → 一天最多 960 次 → 必然超限（返回 REQUEST_NOT_PROCESSED）。6h → 一天 ≤4 次。
#   经济数据是**月度**的，6 小时完全不影响新鲜度。改小之前先读 docs/pitfalls.md。
_ECON_TTL = 6 * 3600  # 秒
_econ_cache: dict = {"ts": 0.0, "payload": None}
_econ_lock = threading.Lock()


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
    """实时取宏观标的 + 派生宏观环境 / 相关性 / 历史三态分布（复用自选股取数链路）。

    取数失败降级空结构（HTTP 200，不 500）。派生三键（`regime` / `correlation` /
    `history_regime`）全部是**内存纯计算**，零落盘 —— 与 trend 合并成一份响应，
    避免前端多次取数与口径漂移。
    """
    empty = {"stocks": [], "trend": {"dates": [], "series": []}}
    stocks = _load_macro_stocks()
    if not stocks:
        return empty
    try:
        # 2026-09-14：宏观页需要 5Y（trend.dates ≈ 1260 点）。range 必须传参 ——
        # 改 _fetch_yahoo_watch 的默认值会连带把 /api/watchlist 也拉成 5y（它只要 30 天）。
        values, series, _errors = fetch_watchlist(stocks, range_="5y")
        payload = _build_watchlist_payload(stocks, values, series, tail=1260)  # 5Y 全量，下游各自截取
    except Exception as exc:
        log.warning("宏观标的取数失败，降级空结构: %s", exc)
        return empty
    records = _last_records(_MACRO_RECORDS)
    indices = (_compute_latest(records) or (None, []))[1]
    payload["regime"] = _compute_macro_regime(indices, records, payload.get("trend") or {})
    payload["correlation"] = compute_macro_correlation(payload.get("trend") or {})
    payload["history_regime"] = _macro_history_regime(records)
    return payload


# ---- 宏观环境（2026-09-14 宏观页 /macro 专用）----
#
# ⚠️ 三条边界（勿越界）：
# 1. **四象限（reflation / goldilocks / stagflation / deflation）不在这里算** —— 它由
#    `src/econ_fetcher.py`（/api/econ）产出，宏观页只消费 `quadrant` / `inflation_axis` /
#    `growth_axis`。在本层重算 → 与后端漂移（plan §4.4）。
# 2. 本层只负责**风险偏好轴的三态**（Risk-On / Neutral / Risk-Off）及其 30 天分布，
#    复用 analyzer 的阈值与首页 `_compute_risk_appetite` 口径（单一事实来源）。
# 3. 以下阈值**全是工程取值**（形态参考 Equicurious《Using Risk-On/Risk-Off Dashboards》
#    的四指标法：每项 -2~+2 → 总分 -8~+8 → ÷8 归一化 → ±0.25 分档）。原文用 IG/HY 信用利差
#    （需 FRED，本机不通），这里用本库可得数据填满四维度。**不是行业标准**，前端须标「评分口径」。
_MACRO_SCORE_MAX = 8              # 4 维度 × ±2
_MACRO_NEUTRAL_BAND = 0.25        # 归一化后 ±0.25 内 = Neutral（与出处一致）
_MACRO_MA_WINDOW = 50             # 美元相对均线窗口（交易日）
_MACRO_CHG_DAYS = 5               # 利率 / 商品 5 日变化
_MACRO_DXY_BANDS = (1.0, 2.0)     # 美元偏离均线分档（%）
_MACRO_RATE_BANDS = (0.10, 0.25)  # 10Y 5 日变化分档（百分点）
_MACRO_CMDTY_BANDS = (2.0, 5.0)   # 原油 5 日变化分档（%）
_MACRO_RECORDS = 40               # 派生指标回看的记录条数（30 天回放 + 5 日变化余量）
_MACRO_CORR_WINDOW = 252          # 相关性滚动窗口 = 1 年（业界惯例，见 docs/architecture.md）
_MACRO_CORR_MIN_POINTS = 30       # 有效点下限；不足 → r=None（前端「样本不足」，不显示 0）
_MACRO_HISTORY_DAYS = 30          # 历史环境分布窗口

# 宏观两两相关（4 变量 → 6 对；不做热力图、不引通胀序列 —— 库内无通胀历史序列）
MACRO_CORR_PAIRS = [
    ("DX-Y.NYB", "GC=F", "美元 ↔ 黄金"),
    ("DX-Y.NYB", "CL=F", "美元 ↔ 原油"),
    ("DX-Y.NYB", "^TNX", "美元 ↔ 10Y 美债"),
    ("GC=F", "CL=F", "黄金 ↔ 原油"),
    ("GC=F", "^TNX", "黄金 ↔ 10Y 美债"),
    ("CL=F", "^TNX", "原油 ↔ 10Y 美债"),
]


def _band_score(delta: float, bands: tuple[float, float], inverse: bool = False) -> int:
    """按 `|delta|` 落档打分：< b0 → 0；b0~b1 → ±1；≥ b1 → ±2。

    `inverse=True`：数值上行 = 风险偏好下行（美元走强 / 利率上行），符号取反。
    """
    b0, b1 = bands
    mag = abs(delta)
    if mag < b0:
        return 0
    sign = 1 if delta > 0 else -1
    return (-sign if inverse else sign) * (1 if mag < b1 else 2)


def _valid_points(raw) -> list[float]:
    """trend.raw 里的有效数值点（None/非数一律剔除；缺口不补齐）。"""
    return [v for v in (raw or []) if isinstance(v, (int, float))]


def _chg_pct(points: list[float], days: int) -> float | None:
    """最近 `days` 日变化（%）：末点 vs 倒数第 `days+1` 个有效点；点数不足 / 基准为 0 → None。"""
    if len(points) < days + 1:
        return None
    prev = points[-(days + 1)]
    if not prev:
        return None
    return round((points[-1] - prev) / prev * 100, 2)


def _chg_abs(points: list[float], days: int) -> float | None:
    """最近 `days` 日的**绝对变化**（如国债收益率的百分点）；点数不足 → None。

    ⚠️ 利率维度必须用绝对变化而不是百分比变化：4.00% → 4.30% 的"百分比变化"是 7.5%，
    和分档阈值 `_MACRO_RATE_BANDS`（0.10 / 0.25 **百分点**）量纲不符 → 任何变动都会顶格。
    """
    if len(points) < days + 1:
        return None
    return round(points[-1] - points[-(days + 1)], 3)


def _dev_from_ma_pct(points: list[float], window: int) -> float | None:
    """最新值相对最近 `window` 个有效点均值的偏离（%）；点数不足 / 均值为 0 → None。"""
    if len(points) < window:
        return None
    ma = sum(points[-window:]) / window
    if not ma:
        return None
    return round((points[-1] - ma) / ma * 100, 2)


def _compute_macro_regime(indices: list[dict], records: list[dict], trend: dict) -> dict:
    """宏观环境四维度打分 → `{level, score, score100, normalized, factors, basis}`。

    维度 / 来源（阈值见上方常量，**均为工程取值**）：

    | 维度 | 输入 | 打分 |
    |---|---|---|
    | 风险偏好 | VIX 状态 + MOVE 状态（`analyzer.classify_*`，与首页同口径） | VIX 平静 +2 / 警惕 0 / 恐慌 -2；MOVE 恐慌再 -1；合计 clamp ±2 |
    | 美元 | DX-Y.NYB 相对 50 日均线偏离 % | ±1% 内 0；1~2% → ∓1；≥2% → ∓2（**美元走强 = 负分**）|
    | 利率 | ^TNX 5 日变化（百分点） | 0.10 内 0；0.10~0.25 → ∓1；≥0.25 → ∓2（**利率上行 = 负分**）|
    | 商品 | CL=F 5 日变化 % | 2% 内 0；2~5% → ±1；≥5% → ±2（商品上行 = 再通胀 = 正分）|

    缺数据的维度**不计分**（分母仍为 8 → 结果偏 Neutral，是刻意的保守默认，不猜）。
    """
    series = {s.get("key"): (s.get("raw") or []) for s in ((trend or {}).get("series") or [])}
    factors: list[dict] = []
    total = 0

    # 维度 1：风险偏好（VIX + MOVE）
    vix = next((it.get("value") for it in (indices or []) if it.get("symbol") == "VIX"), None)
    move = next((it.get("value") for it in (indices or []) if it.get("symbol") == "MOVE"), None)
    risk = 0
    vix_state = move_state = None
    if vix is not None:
        vix_state = classify_vix(vix)[0]
        risk += {"平静": 2, "警惕": 0, "恐慌": -2}.get(vix_state, 0)
    if move is not None:
        move_state = classify_move(move)[0]
        risk += -1 if move_state == "恐慌" else 0   # 债市只在剧烈时扣分（与首页 _compute_risk_appetite 一致）
    if vix is not None or move is not None:
        risk = max(-2, min(2, risk))
        total += risk
        factors.append({"name": "风险偏好", "value": vix, "unit": "",
                        "impact": risk,
                        "note": "VIX %s / MOVE %s" % (vix_state or "—", move_state or "—")})

    # 维度 2：美元（相对均线偏离，反向）
    dxy = _valid_points(series.get("dx-y.nyb"))
    dev = _dev_from_ma_pct(dxy, _MACRO_MA_WINDOW) if dxy else None
    if dev is not None:
        score = _band_score(dev, _MACRO_DXY_BANDS, inverse=True)
        total += score
        factors.append({"name": "美元", "value": dev, "unit": "%", "impact": score,
                        "note": "相对 %d 日均线偏离" % _MACRO_MA_WINDOW})

    # 维度 3：利率（10Y 5 日变化，**百分点**，反向）
    tnx = _valid_points(series.get("^tnx"))
    rate_chg = _chg_abs(tnx, _MACRO_CHG_DAYS) if tnx else None
    if rate_chg is not None:
        score = _band_score(rate_chg, _MACRO_RATE_BANDS, inverse=True)
        total += score
        factors.append({"name": "利率", "value": rate_chg, "unit": "pp", "impact": score,
                        "note": "10Y %d 日变化（百分点）" % _MACRO_CHG_DAYS})

    # 维度 4：商品（原油 5 日变化）
    oil = _valid_points(series.get("cl=f"))
    oil_chg = _chg_pct(oil, _MACRO_CHG_DAYS) if oil else None
    if oil_chg is not None:
        score = _band_score(oil_chg, _MACRO_CMDTY_BANDS)
        total += score
        factors.append({"name": "商品", "value": oil_chg, "unit": "%", "impact": score,
                        "note": "原油 %d 日变化" % _MACRO_CHG_DAYS})

    normalized = round(total / _MACRO_SCORE_MAX, 3)
    if normalized > _MACRO_NEUTRAL_BAND:
        level = "risk_on"
    elif normalized < -_MACRO_NEUTRAL_BAND:
        level = "risk_off"
    else:
        level = "neutral"
    return {
        "level": level,
        "score": total,
        "score100": round((normalized + 1) / 2 * 100, 1),
        "normalized": normalized,
        "factors": factors,
        "max_score": _MACRO_SCORE_MAX,
        # 口径标注（前端直接展示，勿让它看起来像权威指标）
        "basis": "四指标法（每项 -2~+2，总分 ÷8，±0.25 分档）；"
                 "信用利差维度改用 波动率/美元/利率/商品，阈值为工程取值",
    }


def compute_macro_correlation(trend: dict, window: int = _MACRO_CORR_WINDOW) -> list[dict]:
    """宏观品种两两相关（**1 年滚动窗口**）→ `[{a, b, pair, r, n}]`（固定 6 对，顺序稳定）。

    ⚠️ **不复用** `analyzer.compute_correlation`（它绑定 `history` 的 10 个指数键与
    `CORRELATION_PAIRS`）；只复用 `analyzer._returns` / `_pearson`。数据源是 `/api/macro`
    的 `trend.raw`（5Y，同一批取数 → 日期天然对齐，无需跨源对齐）。

    `r=None` 表示样本不足或零方差 —— 前端显示「样本不足」，**绝不显示错误的 0**。
    """
    dates = list((trend or {}).get("dates") or [])
    series = {s.get("key"): (s.get("raw") or []) for s in ((trend or {}).get("series") or [])}
    if not dates or not series:
        return [{"a": a, "b": b, "pair": pair, "r": None, "n": 0} for a, b, pair in MACRO_CORR_PAIRS]
    rows = []
    for i, day in enumerate(dates):
        row = {"date": day}
        for key, raw in series.items():
            row[key] = raw[i] if i < len(raw) else None
        rows.append(row)
    rows = rows[-window:]                     # 1 年滚动窗口
    out = []
    for a, b, pair in MACRO_CORR_PAIRS:
        # ⚠️ trend.series[].key 是 **sym.lower()**（见 _build_watchlist_payload），
        # 而 MACRO_CORR_PAIRS 写的是展示用原始符号（含 ^TNX / DX-Y.NYB）→ 必须先转小写再查，
        # 否则每对都取不到值，6 对全部静默变成 r=None（页面看起来"样本永远不足"）。
        ret_a, ret_b = _returns(rows, a.lower()), _returns(rows, b.lower())
        common = sorted(set(ret_a) & set(ret_b))
        xs = [ret_a[d] for d in common]
        ys = [ret_b[d] for d in common]
        n = len(xs)
        out.append({"a": a, "b": b, "pair": pair,
                    "r": _pearson(xs, ys) if n >= _MACRO_CORR_MIN_POINTS else None,
                    "n": n})
    return out


def _macro_history_regime(records: list[dict], days: int = _MACRO_HISTORY_DAYS) -> dict:
    """最近 `days` 个交易日的风险偏好三态分布（逐日回放）→ `{risk_on, neutral, risk_off, days}`。

    复用 `_compute_risk_appetite`（单一事实来源）：每一天都**只用当天及之前**的记录回放，
    绝不用未来信息；末尾多取 5 天仅为 VIX 5 日变化提供上下文（不足则自动少算该因子）。
    """
    rows = [r for r in (records or []) if isinstance(r, dict) and r.get("date")]
    rows.sort(key=lambda r: r.get("date", ""))
    window = rows[-(days + 5):]
    counts = {"risk_on": 0, "neutral": 0, "risk_off": 0, "days": 0}
    for i in range(max(0, len(window) - days), len(window)):
        upto = window[:i + 1]
        rec = upto[-1]
        indices = [{"symbol": "VIX", "value": rec.get("vix")},
                   {"symbol": "MOVE", "value": rec.get("move")}]
        level = _compute_risk_appetite(indices, upto)["level"]
        if level == "high":
            counts["risk_on"] += 1
        elif level == "low":
            counts["risk_off"] += 1
        elif level == "neutral":
            counts["neutral"] += 1
        counts["days"] += 1
    return counts


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
    empty_sectors = {"sector_heat": {"gainers": [], "losers": [], "as_of": None},
                     "us_sector_heat": {"gainers": [], "losers": [], "as_of": None}}
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
        "sector_heat": _sector_payload("sector_heat"),
        "us_sector_heat": _sector_payload("us_sector_heat"),
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

    容错：文件缺失 / 坏 JSON / **坏字节** / 非 dict / items 非列表 → 空结构
    （HTTP 200 恒定，不 500 —— 坏字节经 `_read_text` 按替换符解码后退化为坏 JSON，同一口径）。
    条目过滤：dict 且 title 非空 且 url 以 http(s):// 开头（防 javascript: 注入）；
    source/published/summary 缺省 ""；截前 8 条（cap 8，防超量撑破卡片）。
    """
    empty = {"date": None, "items": [], "count": 0}
    text = _read_text(NEWS_FILE)
    if text is None:
        if NEWS_FILE.exists():
            log.warning("资讯文件读取失败，按空结构处理: %s", NEWS_FILE)
        return empty
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        if NEWS_FILE.exists():
            log.warning("资讯文件解析失败，按空结构处理: %s", exc)
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


# ---- 事件时间线（2026-09-18，任务档 tasks/2026-09-18-event-timeline-page）----
#
# 数据来自 **db**（`econ_events` / `econ_event_news`，由 `scripts/sync_econ_calendar.py` 落盘）
# + 既有 history 表 —— 本端点**不联网**，因此不会像 `/api/econ` 那样受上游抖动影响。
# 缓存按 `(days, future_days)` 分键：TTL 6h 与 `/api/econ` 同纪律（日历变动是月度/年度级别），
# 且**只缓存有事件的结果**（全空不写缓存，否则一次空库会锁死 6 小时 —— 同 `/api/econ` 的"失败不缓存"）。
_TIMELINE_TTL = 6 * 3600
_timeline_lock = threading.Lock()
_timeline_cache: dict = {"ts": {}, "payload": {}}


@app.get("/api/timeline")
def api_timeline(
    days: int = Query(90, ge=1, le=3650),
    future_days: int = Query(30, ge=0, le=730),
) -> dict:
    """事件时间线：`{as_of, window, stats, sources, past[], upcoming[]}`（HTTP 恒 200）。

    每个 day 携带 `events[]` + `market`（当日涨跌，按**该标的的交易日**取前收）
    + `forward`（+1/3/5/10 交易日点对点，**逐键判空**）；事件自带叙事层字段（可空）。
    """
    key = (days, future_days)
    now = time.time()
    with _timeline_lock:
        cached = _timeline_cache["payload"].get(key)
        if cached is not None and now - _timeline_cache["ts"].get(key, 0.0) < _TIMELINE_TTL:
            return cached

    events = st.query_econ_events()
    history = st.rows_to_records(st.query_history())
    news = st.query_event_news()
    payload = _timeline.build_timeline(events, history, news,
                                       past_days=days, future_days=future_days)
    stats = payload.get("stats") or {}
    if stats.get("past_events") or stats.get("upcoming_events"):
        with _timeline_lock:
            _timeline_cache["payload"][key] = payload
            _timeline_cache["ts"][key] = time.time()
    return payload


@app.get("/timeline", response_class=HTMLResponse)
def timeline_page() -> HTMLResponse:
    """事件时间线独立页（官方日历 = 骨架，行情 = 影响，新闻 = 叙事）。

    `active_page="timeline"` → 侧栏高亮「事件时间线」。
    """
    template = _TEMPLATES.get_template("timeline.html")
    resp = HTMLResponse(template.render(asset_v=_asset_version(),
                                        base_prefix="/", active_page="timeline"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/api/backtest")
def api_backtest() -> dict:
    """阈值回测：`{as_of, window, stats, threshold_config, symbols[], methods[], empty_reason}`。

    🔴 **刻意不缓存**（2026-09-20，与 `/api/econ` 等端点**相反**）：本功能的**核心价值**就是
    「改 `config.json` 阈值 → 立刻看历史表现」。加 TTL 会让用户改完却看到旧结果 ⇒ **价值归零**。
    若将来性能成为问题，要加的是「按 `config.json` mtime 失效」，**不是**定时 TTL。
    实测 266 交易日 / 309 触发 / 7 标的 ≈ 0.5~0.9s，可接受（前端有 loading 态）。

    统计走 `src/backtest.py`（与 `scripts/backtest.py` CLI **同一份实现**）；
    历史与 CLI 同源（SQLite history，经 `st.query_history`）。
    **恒定 HTTP 200**：数据不足 ⇒ `symbols: []` + `empty_reason` 文案（可读空态，不报错）。
    """
    history = st.rows_to_records(st.query_history())
    started = time.perf_counter()
    payload = _backtest.build_backtest_payload(history)
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return payload


@app.get("/backtest", response_class=HTMLResponse)
def backtest_page() -> HTMLResponse:
    """阈值回测独立页（呈现现有回测结果）。

    `active_page="backtest"` → 侧栏高亮「阈值回测」（用户可见名；内部命名一律 backtest）。
    """
    template = _TEMPLATES.get_template("backtest.html")
    resp = HTMLResponse(template.render(asset_v=_asset_version(),
                                        base_prefix="/", active_page="backtest"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/api/settings")
def api_settings() -> dict:
    """设置页数据：当前生效值（三级链合并后）+ env 覆盖标注 + 白名单 schema。**恒 200**。"""
    values, env_over = _settings.read_settings()
    return {"readonly": _settings.is_readonly(),
            "readonly_reason": _settings.readonly_reason(),
            "values": values, "env_overrides": env_over, "schema": _settings.SCHEMA}


@app.post("/api/settings")
def api_settings_save(patch: dict = Body(default=None)) -> dict:
    """保存白名单内的设置（部分更新）。

    顺序（缺一不可）：校验（白名单+规则）→ 备份 → 原子写 → **`reload_config_snapshots()`**。
    🔴 最后一步是本功能的价值所在：不 reload 的话告警/回测的 import 时快照纹丝不动（plan R1）。
    Railway 上 403（只读是默认安全侧）；校验失败 400（逐键错误）；写盘失败 500（**不 reload**）。
    """
    if _settings.is_readonly():
        raise HTTPException(status_code=403, detail=_settings.readonly_reason())
    try:
        values = _settings.apply_updates(patch or {})
    except _settings.SettingsError as exc:
        raise HTTPException(status_code=400, detail={"errors": exc.errors}) from None
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写盘失败（未重载快照）: {exc}") from None
    _reload_config()
    return {"saved": True, "values": values}


@app.get("/settings", response_class=HTMLResponse)
def settings_page() -> HTMLResponse:
    """设置页（用户可见名「设置」，内部命名 settings；本地可写 / Railway 只读）。"""
    template = _TEMPLATES.get_template("settings.html")
    resp = HTMLResponse(template.render(asset_v=_asset_version(),
                                        base_prefix="/", active_page="settings"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


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


@app.get("/api/econ")
def api_econ() -> dict:
    """经济数据（BLS：CPI-U / PPI / 失业率 / 非农）+ 四象限（长 TTL 缓存）。

    **只缓存成功结果**：`as_of` 为空的降级结构不写缓存 —— 否则一次网络抖动会锁死 6 小时。
    失败降级返回空结构，HTTP 200 恒定（不 500），前端显示「数据暂缺」。
    """
    now = time.time()
    with _econ_lock:
        cached = _econ_cache["payload"]
        if cached is not None and (now - _econ_cache["ts"]) < _ECON_TTL:
            return cached
    fresh = build_econ_payload(fetch_econ_series())
    if fresh.get("as_of"):
        with _econ_lock:
            _econ_cache["ts"] = time.time()
            _econ_cache["payload"] = fresh
    return fresh


@app.get("/macro", response_class=HTMLResponse)
def macro_page() -> HTMLResponse:
    """宏观数据独立页（research terminal 风格：7 模块，大图为主视觉）。

    与首页共用顶栏/侧栏（`_topbar.html` / `_sidebar.html`）：
    `base_prefix="/"` → 侧栏锚点变成 `/#overview`（回首页）；`active_page="macro"` → 高亮「宏观数据」。
    """
    template = _TEMPLATES.get_template("macro.html")
    resp = HTMLResponse(template.render(asset_v=_asset_version(),
                                        base_prefix="/", active_page="macro"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


# ---- 中国宏观（2026-09-14 新增 /macro/cn）----
#
# ⚠️ 与 BLS `/api/econ` 的**有意差异**（勿"统一"成同一套）：
#   BLS 版：1 个上游请求 → **失败即全失败** → `as_of` 为空才不缓存。
#   中国版：13 个**相互独立**的 AkShare 接口 → 只缓存"13 个全部失败（as_of 为空）"不缓存；
#   **部分成功照常缓存**，失败明细走 `failed` 交给前端逐模块降级。
#   否则一次单接口抖动就会让每次请求都重打 13 个接口（用户等 10s+）。
_CN_ECON_TTL = 6 * 3600          # 月/季数据为主，与 _ECON_TTL 同纪律（日调用 ≤4 次）
_CN_QUOTES_TTL = 90              # 行情类（汇率/国债收益率），与 _MACRO_TTL 同口径
# BUG-012（2026-09-24）：`/api/cn/quotes` 冷缓存时**同步直连取数、无上限**（实测冷启动 13.50s，
# 上游挂起会占住单 worker）⇒ 复用项目既有 daemon 线程限时范式（`src/fetcher.fetch_sector_heat`），
# 超时返回空态（HTTP 200，前端按既有「数据暂缺」降级）。上限 15s 覆盖实测冷启动并有富余。
_CN_QUOTES_TIMEOUT = 15          # 取数限时（秒）
_cn_econ_raw: dict = {}          # key -> rows：**跨组累积**，供四象限算轴
_cn_econ_raw_ts: dict = {}       # key -> 写入时间
_cn_econ_cache: dict = {"ts": {}, "payload": {}}     # 按 group（"all" 或组名）分桶
_cn_econ_lock = threading.Lock()
_cn_quotes_cache: dict = {"ts": 0.0, "payload": None}
_cn_quotes_lock = threading.Lock()


@app.get("/api/econ/cn")
def api_econ_cn(group: str | None = Query(
        default=None, pattern="^(price|growth|money|rate|labor|estate)$")) -> dict:
    """中国宏观数据（AkShare 13 序列）+ 中国版四象限。

    `?group=` 走 **R1 分组降级路径**（2026-09-14 实测：全量并发 10.3s > 8s 判据）：
    前端**分批**请求（先 `price`+`growth` 出四象限 ≈3.6s，再其余组逐组填充）——
    ⚠️ 6 个组**同时**发是没有收益的：13 个上游请求照样同时在飞，墙钟不变。

    失败语义：单序列失败 → `failed` 列该 key，HTTP 恒 200（前端逐模块「数据暂缺」）。
    """
    now = time.time()
    only, cache_key = (None, "all") if group is None else (group_keys(group), group)
    with _cn_econ_lock:
        cached = _cn_econ_cache["payload"].get(cache_key)
        if cached is not None and now - _cn_econ_cache["ts"].get(cache_key, 0.0) < _CN_ECON_TTL:
            return cached
        scope = list(CN_ECON_SERIES) if only is None else list(only)
        stale = [k for k in scope if now - _cn_econ_raw_ts.get(k, 0.0) >= _CN_ECON_TTL]

    if stale:
        raw, _failed = fetch_cn_econ_raw(stale)
        with _cn_econ_lock:
            for k in stale:
                _cn_econ_raw[k] = raw.get(k)
                # ⚠️ **失败的 key 不写 ts**（下次请求会重试它）：若连失败也记 ts，
                #    一次网络抖动会把空数据锁死 6 小时；而"部分成功"靠**上层 payload 缓存**
                #    短路（6h 内不再走到这里），不会因此反复重打成功的接口。
                if _cn_econ_raw[k]:
                    _cn_econ_raw_ts[k] = time.time()
                else:
                    _cn_econ_raw_ts.pop(k, None)

    with _cn_econ_lock:
        raw_all = dict(_cn_econ_raw)
    # 四象限按**累积 raw** 算（跨组）：先到的组可能还没有另一条轴 → quadrant 为 None，
    # 后到的组自然补上；前端取"任一响应里 quadrant 非空"的那份。
    fresh = build_cn_econ_payload(raw_all, [k for k in scope if not raw_all.get(k)], only=only)
    if fresh.get("as_of"):
        with _cn_econ_lock:
            _cn_econ_cache["ts"][cache_key] = now
            _cn_econ_cache["payload"][cache_key] = fresh
    return fresh


def _cn_quotes_empty() -> dict:
    """中国宏观行情空态：无数据 + `failed` 如实列出三项（与「取数全失败」分支同形）。"""
    return {"as_of": None, "cny": None, "bond10y": None, "credit_spread": None,
            "failed": ["cny", "bond10y", "credit_spread"]}


def _load_cn_quotes_limited() -> dict:
    """`_load_cn_quotes()` 的**限时**包装：daemon 线程 + `join(_CN_QUOTES_TIMEOUT)`（BUG-012）。

    范式与 `src/fetcher.fetch_sector_heat` 一致（本项目既有写法）。超时 / 取数抛异常 → 空态，
    HTTP 仍 200、`as_of` 语义与既有失败分支一致（None，前端沿用「数据暂缺」文案）。
    被放弃的线程是 daemon 且 `_load_cn_quotes` 只读不写缓存 ⇒ 超时后不会回写污染后续请求。
    """
    box: dict = {}

    def _worker() -> None:
        try:
            box["out"] = _load_cn_quotes()
        except Exception as exc:  # noqa: BLE001 —— 与既有降级语义一致（不 500）
            log.warning("中国宏观行情取数异常，降级空态: %s", exc)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(_CN_QUOTES_TIMEOUT)
    if t.is_alive():
        log.warning("中国宏观行情取数超时（>%ss），返回空态", _CN_QUOTES_TIMEOUT)
        return _cn_quotes_empty()
    return box.get("out") or _cn_quotes_empty()


def _load_cn_quotes() -> dict:
    """人民币汇率（Yahoo `CNY=X`）+ 中债 10Y 国债 + 信用利差（商金债AAA − 国债，bp）。

    ⚠️ `CNH=X` 只返回 **1 个数据点**（离岸水深浅），**不能作趋势** → 用 `CNY=X`。
    ⚠️ 信用利差是**同一次请求的副产品**（`bond_china_yield` 一次返回 3 条曲线），
       正好补上美国版因 FRED 不通而被迫放弃的信用维度。
    """
    out: dict = _cn_quotes_empty()
    out["failed"] = []          # 逐项失败时再 append（默认「三项全失败」留给限时/异常路径）
    try:
        value, series = _fetch_yahoo_watch("CNY=X", "3mo")
        out["cny"] = {"symbol": "CNY=X", "label": "美元/人民币", "value": round(float(value), 4),
                      "series": [[d, round(float(v), 4)] for d, v in series[-120:]]}
    except Exception as exc:  # noqa: BLE001 —— 汇率失败不影响国债/利差
        log.warning("人民币汇率取数失败，降级: %s", exc)
        out["failed"].append("cny")

    curves = fetch_bond_yield_curves("10年")
    gov = curves.get("国债") or []
    aaa = curves.get("商金债AAA") or []
    if gov:
        out["bond10y"] = {"label": "10 年期国债收益率", "unit": "%", "value": gov[-1][1],
                          "date": gov[-1][0], "series": [[d, v] for d, v in gov[-120:]]}
    else:
        out["failed"].append("bond10y")

    if gov and aaa:
        gov_map = dict(gov)
        spread = [[d, round((v - g) * 100, 2)]                 # 百分点 → bp
                  for d, v in aaa if (g := gov_map.get(d)) is not None]
        if spread:
            out["credit_spread"] = {"label": "信用利差（商金债AAA − 国债）", "unit": "bp",
                                    "value": spread[-1][1], "date": spread[-1][0],
                                    "series": spread[-120:]}
    if out["credit_spread"] is None:
        out["failed"].append("credit_spread")

    candidates = []
    if out["bond10y"]:
        candidates.append(out["bond10y"]["date"])
    if out["cny"] and out["cny"]["series"]:
        candidates.append(out["cny"]["series"][-1][0])
    out["as_of"] = max(candidates) if candidates else None
    return out


@app.get("/api/cn/quotes")
def api_cn_quotes() -> dict:
    """中国宏观行情（汇率 / 10Y 国债 / 信用利差）；TTL 缓存，失败降级、HTTP 恒 200。"""
    now = time.time()
    with _cn_quotes_lock:
        cached = _cn_quotes_cache["payload"]
        if cached is not None and now - _cn_quotes_cache["ts"] < _CN_QUOTES_TTL:
            return cached
    fresh = _load_cn_quotes_limited()
    if fresh.get("as_of"):
        with _cn_quotes_lock:
            _cn_quotes_cache["ts"] = now
            _cn_quotes_cache["payload"] = fresh
    return fresh


@app.get("/macro/cn", response_class=HTMLResponse)
def macro_cn_page() -> HTMLResponse:
    """中国宏观独立页（与 `/macro` 平行：同为 `.mac-*` research terminal 风格）。

    `active_page="macro-cn"` → 侧栏高亮「中国宏观」（**不是**「宏观数据」）。
    """
    template = _TEMPLATES.get_template("macro_cn.html")
    resp = HTMLResponse(template.render(asset_v=_asset_version(),
                                        base_prefix="/", active_page="macro-cn"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """渲染单页看板。

    2026-09-14：顶栏/侧栏抽成 `_topbar.html` / `_sidebar.html`（宏观页共用），
    由 `base_prefix`（首页 "" → 页内锚点 `#x`）与 `active_page`（高亮哪一项）参数化。
    """
    template = _TEMPLATES.get_template("index.html")
    resp = HTMLResponse(template.render(asset_v=_asset_version(),
                                        base_prefix="", active_page="dashboard"))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp
