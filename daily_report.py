"""MarketPulse — 每日波动率指数日报生成器。

每天获取 VIX、VXN、MOVE 三个波动率指数数据，生成 Markdown 日报
（reports/YYYY-MM-DD.md），并把当日收盘值缓存到 data/last_values.json
作为次日涨跌幅基准。脚本不包含推送逻辑（由 Hermes 读取报告并推送）。

用法:
    python daily_report.py
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from urllib.parse import quote
from time import sleep

import requests

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0"})

# ---- 常量 ----
SYMBOLS = {
    "VIX": {"label": "VIX（恐慌指数）", "source": "yahoo", "ticker": "^VIX"},
    "VXN": {"label": "VXN（科技波动）", "source": "yahoo", "ticker": "^VXN"},
    "MOVE": {"label": "MOVE（债市波动）", "source": "yahoo", "ticker": "^MOVE"},
}

# 状态阈值：VIX/VXN 共用 20/30；MOVE 量级不同，用 100/130（已确认）。
VIX_CALM = 20.0
VIX_WARN = 30.0
MOVE_CALM = 100.0
MOVE_WARN = 130.0

TIMEOUT = 15          # 单次请求超时（秒）
RETRIES = 1           # 失败重试次数（共尝试 2 次）

BASE_DIR = Path(__file__).resolve().parent
REPORTS_DIR = BASE_DIR / "reports"
DATA_DIR = BASE_DIR / "data"
LAST_VALUES_FILE = DATA_DIR / "last_values.json"

EASTERN_TZ = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("marketpulse")


# ---- 纯逻辑层 ----
def get_us_eastern_date() -> str:
    """返回美东当前日期 YYYY-MM-DD（内部 UTC，显示用美东）。"""
    return datetime.now(EASTERN_TZ).strftime("%Y-%m-%d")


def classify_vix(value: float) -> tuple[str, str]:
    """按 VIX 阈值分类：<20 平静 / 20-30 警惕 / >=30 恐慌。VXN 复用。"""
    if value < VIX_CALM:
        return "平静", "市场情绪平稳，波动率处于低位，风险偏好较高。"
    if value < VIX_WARN:
        return "警惕", "市场情绪偏谨慎，波动率上升，注意短期回调风险。"
    return "恐慌", "市场情绪恐慌，波动率处于高位，警惕大幅波动与系统性风险。"


def classify_move(value: float) -> tuple[str, str]:
    """按 MOVE 阈值分类：<100 平静 / 100-130 警惕 / >=130 恐慌。"""
    if value < MOVE_CALM:
        return "平静", "债市波动平稳，利率预期稳定。"
    if value < MOVE_WARN:
        return "警惕", "债市波动上升，利率预期分歧加大，注意久期风险。"
    return "恐慌", "债市波动剧烈，利率预期高度不确定，警惕债券抛售与流动性风险。"


def compute_changes(current: dict, last_values: dict) -> dict:
    """计算各指数相对缓存值的涨跌幅（%）。无历史或基准为 0 时返回 None。"""
    changes = {}
    for sym, value in current.items():
        if value is None:
            changes[sym] = None
        elif sym not in last_values or last_values[sym] is None or last_values[sym] == 0:
            changes[sym] = None  # 首跑或无有效基准
        else:
            changes[sym] = (value - last_values[sym]) / last_values[sym] * 100.0
    return changes


def build_statuses(values: dict, errors: dict) -> dict:
    """为每个指数生成 (状态标签, 描述)。取数失败/跳过时给出明确标注。"""
    statuses = {}
    for sym in SYMBOLS:
        if values[sym] is None:
            statuses[sym] = ("获取失败", "数据获取失败，无法判断状态。")
        elif sym == "MOVE":
            statuses[sym] = classify_move(values[sym])
        else:
            statuses[sym] = classify_vix(values[sym])
    return statuses


def build_summary(values: dict, statuses: dict, errors: dict) -> str:
    """基于 VIX 状态与数据完整性拼确定性总结。"""
    parts = []
    vix = values.get("VIX")
    if vix is not None:
        label, desc = statuses["VIX"]
        parts.append(f"VIX 收于 {fmt_value(vix)}，市场状态：{label}。{desc}")
    else:
        parts.append("VIX 数据获取失败，无法判断整体市场情绪。")
    if errors:
        failed = "、".join(f"{k}（{errors[k]}）" for k in SYMBOLS if k in errors)
        parts.append(f"注意：{failed}，相关指标缺失，请留意数据源可用性。")
    else:
        parts.append("三个波动率指数数据获取完整，无异常。")
    return "\n".join(parts)


# ---- 格式化 ----
def fmt_value(value: float | None) -> str:
    """收盘价显示：保留两位小数；None 显示获取失败。"""
    return "获取失败" if value is None else f"{value:.2f}"


def fmt_change(change: float | None, has_history: bool, value: float | None) -> str:
    """涨跌幅显示：首跑提示 / 正负号百分比 / 无数据时 —。"""
    if value is None:
        return "—"
    if not has_history:
        return "首次运行，暂无历史对比"
    if change is None:
        return "—"
    sign = "+" if change > 0 else ""
    return f"{sign}{change:.2f}%"


# ---- 数据获取层 ----
def fetch_with_retry(name, fn, retries: int = RETRIES):
    """带重试地执行取数函数；全部失败返回 None 并记录日志（不抛给上层）。重试间退避 1s，避免突发限流。"""
    for attempt in range(1, retries + 2):
        try:
            value = fn()
            if value is None:
                raise ValueError("返回空数据")
            return value
        except Exception as exc:
            log.warning("%s 获取失败(第%d次): %s", name, attempt, exc)
            if attempt <= retries:
                sleep(1)
    return None


def fetch_vix_vxn(symbol: str) -> float:
    """从 Yahoo Finance chart REST 接口获取指数最近收盘价（复用 Session，规避 history() 多请求限流）。"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
    resp = _SESSION.get(url, params={"interval": "1d", "range": "5d"}, timeout=TIMEOUT)
    resp.raise_for_status()
    result = resp.json()["chart"].get("result")
    if not result:
        raise ValueError("Yahoo 返回空图表数据")
    meta = result[0].get("meta", {})
    close = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
    if close is not None:
        return float(close)
    # 兜底：meta 缺价时解析 close 序列最后一个非空收盘（应对 Yahoo 降级响应）
    quote_series = result[0].get("indicators", {}).get("quote", [{}])
    closes = quote_series[0].get("close", []) if quote_series else []
    for v in reversed(closes):
        if v is not None:
            return float(v)
    raise ValueError("Yahoo 返回数据无收盘价")


def fetch_all() -> tuple[dict, dict]:
    """依次获取三个指数；每个源独立容错，单源失败/跳过不影响其他源。源间节流 2s，降低 Yahoo 突发限流概率。"""
    values, errors = {}, {}
    first = True
    for sym, meta in SYMBOLS.items():
        if not first:
            sleep(2)
        first = False
        ticker = meta["ticker"]
        fetch = lambda t=ticker: fetch_vix_vxn(t)  # noqa: E731
        values[sym] = fetch_with_retry(sym, fetch)
        if values[sym] is None:
            errors[sym] = "获取失败（已重试）"
            log.warning("%s 最终无数据", sym)
        else:
            log.info("%s 收盘价: %.2f", sym, values[sym])
    return values, errors


# ---- 缓存层 ----
def load_last_values() -> dict:
    """读取缓存 {symbol: value}；文件不存在或损坏时按首跑处理（空 dict）。"""
    if not LAST_VALUES_FILE.exists():
        return {}
    try:
        data = json.loads(LAST_VALUES_FILE.read_text(encoding="utf-8"))
        values = data.get("values", {})
        return {k: v for k, v in values.items() if isinstance(v, (int, float))}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("缓存读取失败，按首次运行处理: %s", exc)
        return {}


def save_last_values(values: dict, date: str) -> None:
    """写入当日缓存（值 + 美东日期），供次日涨跌幅对比。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"date": date, "values": values}
    LAST_VALUES_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---- 报告渲染 ----
def render_report(date, values, changes, statuses, summary, has_history) -> str:
    """按 PRD 模板渲染 Markdown 日报，占位符全部替换。"""
    rows = []
    for sym, meta in SYMBOLS.items():
        status_label, _ = statuses[sym]
        rows.append(
            f"| {meta['label']} | {fmt_value(values[sym])} "
            f"| {fmt_change(changes[sym], has_history, values[sym])} | {status_label} |"
        )
    table = "\n".join(rows)

    if values["VIX"] is not None:
        vix_label, vix_desc = statuses["VIX"]
        state_line = f"**VIX 当前值：{fmt_value(values['VIX'])} → 状态：{vix_label}**\n\n> {vix_desc}"
    else:
        state_line = "**VIX 当前值：获取失败 → 状态：无法判断**\n\n> VIX 数据获取失败，无法判断整体市场情绪。"

    return f"""# 📊 市场情绪日报

**日期**：{date}（美东时间）

---

## 📈 核心指数

| 指数 | 收盘价 | 涨跌幅 | 状态 |
| :--- | :--- | :--- | :--- |
{table}

---

## 🏷️ 市场状态

{state_line}

---

## 📝 总结

{summary}

---
*本报告由 MarketPulse 自动生成 | 数据来源：Yahoo Finance*"""


# ---- 编排 ----
def main() -> int:
    """完整流程：取数 → 读缓存 → 算涨跌幅 → 渲染 → 写报告 → 写缓存。"""
    date = get_us_eastern_date()
    log.info("MarketPulse 开始生成 %s 日报", date)

    values, errors = fetch_all()
    last_values = load_last_values()
    has_history = bool(last_values)
    changes = compute_changes(values, last_values)
    statuses = build_statuses(values, errors)
    summary = build_summary(values, statuses, errors)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{date}.md"
    report_path.write_text(
        render_report(date, values, changes, statuses, summary, has_history),
        encoding="utf-8",
    )
    log.info("报告已生成: %s", report_path)

    saved = {k: v for k, v in values.items() if v is not None}
    if saved:
        save_last_values(saved, date)
        log.info("缓存已更新: %s", LAST_VALUES_FILE)
    else:
        log.warning("所有数据源获取失败，本次不更新缓存")

    return 0  # 全源失败也恒为 0，避免 Hermes 定时任务误报警


if __name__ == "__main__":
    raise SystemExit(main())
