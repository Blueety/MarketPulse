"""纯逻辑层 + 持久化：状态分类、涨跌幅、日期、格式化、缓存与历史读写。

不含网络请求与报告渲染，全部可单测。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import env_float, load_config
from .fetcher import SYMBOLS, STOCK_SYMBOLS, A_SHARE_SYMBOLS, ALT_SYMBOLS

log = logging.getLogger("marketpulse")

# ---- 路径常量 ----
BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
CHARTS_DIR = REPORTS_DIR / "charts"
SNAPSHOTS_DIR = REPORTS_DIR / "snapshots"
DATA_DIR = BASE_DIR / "data"
LAST_VALUES_FILE = DATA_DIR / "last_values.json"
HISTORY_FILE = DATA_DIR / "history.json"
ALERTS_DIR = BASE_DIR / "alerts"
ALERTS_LOG = DATA_DIR / "alerts.log"
CONTEXT_DIR = BASE_DIR / "context"   # 四期：Hermes 上下文 JSON（generate_context 产出）

# 五期：阈值来自 load_config()（import 时快照；env > config.json > 内置默认，设计 A）。
_CFG = load_config()

# 状态阈值：VIX/VXN 共用 20/30；MOVE 量级不同，用 100/130。调用时经 STATUS_THRESHOLD_* env 复核。
VIX_CALM = float(_CFG["analysis"]["vix"]["peaceful"])
VIX_WARN = float(_CFG["analysis"]["vix"]["panic"])
MOVE_CALM = float(_CFG["analysis"]["move"]["normal"])
MOVE_WARN = float(_CFG["analysis"]["move"]["tight"])

ALERT_THRESHOLDS = {sym: float(_CFG["alert"][sym.lower()]) for sym in SYMBOLS if sym not in ALT_SYMBOLS}  # 变化率百分比，调用时 env 复核；另类资产不设阈值
ALERT_SUGGESTIONS = {  # 告警建议按当前状态分档（确定性，可单测断言）
    "平静": "波动率仍处低位，建议保持现有策略，关注后续变化。",
    "警惕": "波动率明显抬升，建议控制仓位，留意短期回调风险。",
    "恐慌": "波动率处于高位，建议以避险为主，防范系统性风险。",
}

# 六期A：大盘趋势连续涨跌天数阈值（N）；trend_label 调用时经 TREND_STREAK_DAYS env 复核。
STREAK_DAYS = int(_CFG["trend"]["streak_days"])
# 大盘告警（恒 WARN）建议文案：大盘无恐慌区间定义，不臆造分级。
STOCK_SUGGESTION = "大盘指数当日波动显著，注意仓位与风险管理。"

HISTORY_MAX = int(_CFG["history"]["retention_days"])   # 历史数据滚动窗口（天）
# 十二期：相关性分析（PRD 定稿 5 组关键对；窗口/最少样本/显著阈值均为 PRD 固定值，不配置化）
CORRELATION_PAIRS = [   # (指数A, 指数B) —— 顺序即报告与 context 输出顺序
    ("VIX", "GSPC"),    # 恐慌 ↔ 标普500（负相关越强，美股对恐慌越敏感）
    ("VIX", "SH"),      # 恐慌 ↔ 上证（VIX 对 A 股传导强度）
    ("GSPC", "SH"),     # 标普500 ↔ 上证（中美股市联动）
    ("IXIC", "CYB"),    # 纳指 ↔ 创业板（中美科技股同步性）
    ("MOVE", "VIX"),    # 债市恐慌 ↔ 股市恐慌
]
CORRELATION_DAYS = int(_CFG["trend"]["chart_days"])   # 窗口 30 交易日，与趋势图同一配置源
CORRELATION_MIN_POINTS = 10                            # 至少 10 个有效数据点
CORRELATION_SIGNIFICANT = 0.5                          # |r| 显著阈值（颜色编码与 context 写入共用）

EASTERN_TZ = ZoneInfo("America/New_York")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")  # 七期：A 股快照按北京时间归档


# ---- 纯逻辑层 ----
def get_market_date(market: str) -> str:
    """返回市场自身交易日 YYYY-MM-DD（设计 B）：a-share 用北京时间、us 用美东时间。"""
    tz = SHANGHAI_TZ if market == "a-share" else EASTERN_TZ
    return datetime.now(tz).strftime("%Y-%m-%d")

def get_us_eastern_date() -> str:
    """返回美东当前日期 YYYY-MM-DD（内部 UTC，显示用美东）。"""
    return datetime.now(EASTERN_TZ).strftime("%Y-%m-%d")

def classify_vix(value: float) -> tuple[str, str]:
    """按 VIX 阈值分类：<20 平静 / 20-30 警惕 / >=30 恐慌（默认值，可配置）。VXN 复用。

    阈值 import 时快照，调用时经 STATUS_THRESHOLD_VIX_* env 复核（设计 A）。"""
    calm = env_float("STATUS_THRESHOLD_VIX_CALM", VIX_CALM)
    warn = env_float("STATUS_THRESHOLD_VIX_PANIC", VIX_WARN)
    if value < calm:
        return "平静", "市场情绪平稳，波动率处于低位，风险偏好较高。"
    if value < warn:
        return "警惕", "市场情绪偏谨慎，波动率上升，注意短期回调风险。"
    return "恐慌", "市场情绪恐慌，波动率处于高位，警惕大幅波动与系统性风险。"


def classify_move(value: float) -> tuple[str, str]:
    """按 MOVE 阈值分类：<100 平静 / 100-130 警惕 / >=130 恐慌（默认值，可配置）。

    阈值 import 时快照，调用时经 STATUS_THRESHOLD_MOVE_* env 复核（设计 A）。"""
    calm = env_float("STATUS_THRESHOLD_MOVE_CALM", MOVE_CALM)
    warn = env_float("STATUS_THRESHOLD_MOVE_WARN", MOVE_WARN)
    if value < calm:
        return "平静", "债市波动平稳，利率预期稳定。"
    if value < warn:
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


def alert_threshold(symbol: str) -> float:
    """返回指数告警阈值（变化率 %）；env ALERT_THRESHOLD_<SYM> 覆盖默认，非法/非正回退默认。"""
    return env_float(f"ALERT_THRESHOLD_{symbol}", ALERT_THRESHOLDS[symbol])


def check_breach(symbol: str, current: float | None, last: float | None) -> dict | None:
    """判断当日变化率是否超过告警阈值（严格大于，等于不触发）。返回告警 dict 或 None；level：恐慌区间为 ALERT。"""
    if current is None or last is None or last == 0:
        return None
    change = (current - last) / last * 100.0
    threshold = alert_threshold(symbol)
    if abs(change) <= threshold:
        return None
    if symbol in STOCK_SYMBOLS:  # 大盘无恐慌区间定义，恒 WARN、state=异动
        return {
            "symbol": symbol,
            "current": current,
            "last": last,
            "change": change,
            "threshold": threshold,
            "level": "WARN",
            "state": "异动",
            "suggestion": STOCK_SUGGESTION,
        }
    state, _ = (classify_move if symbol == "MOVE" else classify_vix)(current)
    level = "ALERT" if state == "恐慌" else "WARN"
    return {
        "symbol": symbol,
        "current": current,
        "last": last,
        "change": change,
        "threshold": threshold,
        "level": level,
        "state": state,
        "suggestion": ALERT_SUGGESTIONS[state],
    }


def build_search_keywords(date: str, breaches: list[dict], sector_heat=None) -> list[str]:
    """按异动状态生成 tavily 搜索关键词（方向感知）。

    八期：板块热度（Top5，按涨跌幅排序，不设阈值）全量注入方向词，与指数异动词同构
    （变化率 >=0 用 surge / <0 用 drop）；异动日额外补两个定向词。
    无任何异动且板块缺失时仅 1 个 "market summary {date}"。"""
    breach_words = [
        f"{b['symbol']} {'surge' if b['change'] >= 0 else 'drop'} {date}"
        for b in breaches
    ]
    sector_heat = sector_heat or ([], [])
    sectors = sector_heat[0] + sector_heat[1]
    sector_words = [
        f"{s['name']} {'surge' if s['change'] >= 0 else 'drop'} {date}"
        for s in sectors
    ]
    words = breach_words + sector_words
    if not words:
        return [f"market summary {date}"]
    if breaches:
        words += [f"market volatility {date}", f"economic data {date}"]
    return words[:5]


def _sign(x: float) -> int:
    """数值符号：正 1 / 负 -1 / 零 0。"""
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def compute_streaks(values: dict, last_values: dict | None = None,
                    history: list[dict] | None = None, date: str = "",
                    symbols: set = STOCK_SYMBOLS) -> dict:
    """计算大盘指数连续同向涨跌天数（streak）。返回 {sym: signed_int}（正=连涨、负=连跌、0=无方向）。

    纯计算、可单测：方向序列 = 历史相邻记录（排除 date==今日 行）逐日涨跌 + 今日 current vs last_values；
    序列去尾 0（横盘不打断既有趋势）后，从最后非零方向往前数连续同号天数。
    symbols 默认 STOCK_SYMBOLS（存量行为不变）；十期传入 STOCK_SYMBOLS | ALT_SYMBOLS 使另类资产复用趋势机制。
    """
    streaks = {}
    history = history or []
    last_values = last_values or {}
    for sym in symbols:
        lower = sym.lower()
        closes = [
            r[lower]
            for r in sorted(
                (r for r in history if r.get("date") != date),
                key=lambda r: r.get("date", ""),
            )
            if isinstance(r.get(lower), (int, float))
        ]
        dirs = []
        prev = None
        for v in closes:
            if prev is not None:
                dirs.append(_sign(v - prev))
            prev = v
        cur = values.get(sym)
        if isinstance(cur, (int, float)):
            last = last_values.get(sym)
            if isinstance(last, (int, float)):
                dirs.append(_sign(cur - last))
        while dirs and dirs[-1] == 0:
            dirs.pop()
        if not dirs:
            streaks[sym] = 0
            continue
        last_sign = 1 if dirs[-1] > 0 else -1
        count = 0
        for d in reversed(dirs):
            if d == last_sign:
                count += 1
            else:
                break
        streaks[sym] = count if last_sign > 0 else -count
    return streaks


def compute_correlation(history, pairs=None, window=None) -> list[dict]:
    """计算指定指数对的 Pearson 相关系数（纯 Python，零依赖）。

    输入为每日涨跌幅（收益率%），非原始价格：由 history 原始收盘价逐对推导相邻日收益率，
    再按日期对齐取两序列均有效的点。窗口 = 最后 window 行（默认 CORRELATION_DAYS=30）。
    每对有效点数 >= CORRELATION_MIN_POINTS(10) 才计算，否则 r=None。
    常量序列（零方差）→ r=None；浮点误差钳制到 [-1,1]，保留两位小数。
    返回 [{a, b, pair, r, n}]，顺序 = pairs 顺序。纯计算、可单测。
    """
    pairs = pairs if pairs is not None else CORRELATION_PAIRS
    window = window if window is not None else CORRELATION_DAYS
    rows = _corr_window(history, window)
    results = []
    for a, b in pairs:
        ra = _returns(rows, a.lower())
        rb = _returns(rows, b.lower())
        common = sorted(set(ra) & set(rb))
        xs = [ra[d] for d in common]
        ys = [rb[d] for d in common]
        n = len(xs)
        r = _pearson(xs, ys) if n >= CORRELATION_MIN_POINTS else None
        results.append({
            "a": a,
            "b": b,
            "pair": f"{SYMBOLS[a]['label']} ↔ {SYMBOLS[b]['label']}",
            "r": r,
            "n": n,
        })
    return results


def _corr_window(history, window):
    """取最后 window 行（按 date 升序），与趋势图 rows[-TREND_DAYS:] 同一语义。"""
    rows = [r for r in (history or []) if isinstance(r, dict) and r.get("date")]
    rows.sort(key=lambda r: r.get("date", ""))
    return rows[-window:]


def _returns(rows, key):
    """由原始收盘价推导逐日收益率（涨跌幅），按 date 索引。

    仅当相邻两行（前一日、当日）该键均为有效数值时计算；
    遇缺口（None）断开链，避免多日累计收益混入。返回 {date: return}。
    """
    rets = {}
    prev = None
    for r in rows:
        v = r.get(key)
        if isinstance(v, (int, float)):
            if prev is not None and prev != 0:
                rets[r["date"]] = (v - prev) / prev
            prev = v
        else:
            prev = None
    return rets


def _pearson(xs, ys):
    """Pearson 相关系数（零依赖）。样本 <2 或任一序列零方差 → None。"""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    r = cov / (vx ** 0.5 * vy ** 0.5)
    r = max(-1.0, min(1.0, r))
    return round(r, 2)


def trend_label(streak: int, has_data: bool) -> str:
    """大盘趋势四档标签。N=STREAK_DAYS（调用时经 TREND_STREAK_DAYS env 复核）。

    无数据→数据积累中；streak==0→横盘；1≤|streak|<N→连涨/跌X日；|streak|≥N→上升/下跌趋势。
    """
    n = int(env_float("TREND_STREAK_DAYS", STREAK_DAYS))
    if not has_data:
        return "数据积累中"
    if streak == 0:
        return "横盘"
    if abs(streak) < n:
        return f"连{'涨' if streak > 0 else '跌'}{abs(streak)}日"
    return f"{'上升' if streak > 0 else '下跌'}趋势"


def _stock_has_data(sym: str, last_values: dict | None = None,
                    history: list[dict] | None = None) -> bool:
    """是否有足够数据判断大盘趋势（≥1 个对比基准）。首次运行无基准 → 数据积累中。"""
    if isinstance(last_values, dict) and isinstance(last_values.get(sym), (int, float)):
        return True
    history = history or []
    cnt = 0
    for r in history:
        if isinstance(r.get(sym.lower()), (int, float)):
            cnt += 1
            if cnt >= 2:
                return True
    return False


def _trend_desc(streak: int, has_data: bool, sym: str) -> str:
    """大盘趋势描述（辅助文案，配合趋势标签）。"""
    if not has_data:
        return "大盘历史数据不足，趋势待积累。"
    if streak == 0:
        return "大盘窄幅震荡，方向暂不明。"
    direction = "上涨" if streak > 0 else "下跌"
    return f"大盘连续{direction}{abs(streak)}日。"


def build_statuses(values: dict, errors: dict, last_values: dict | None = None,
                   history: list[dict] | None = None) -> dict:
    """为每个指数生成 (状态标签, 描述)。取数失败/跳过时给出明确标注。

    大盘指数走趋势标签（compute_streaks + trend_label），波动率走 classify_*；
    values 用 .get 容忍缺失（与 collect_breaches 一致）；不传 last_values/history（旧调用）
    """
    statuses = {}
    streaks = compute_streaks(values, last_values, history, symbols=STOCK_SYMBOLS | ALT_SYMBOLS)
    for sym in SYMBOLS:
        val = values.get(sym)
        if val is None:
            if sym in A_SHARE_SYMBOLS:
                statuses[sym] = ("休市", "A 股休市或数据缺失。")
            else:
                statuses[sym] = ("获取失败", "数据获取失败，无法判断状态。")
        elif sym in STOCK_SYMBOLS or sym in ALT_SYMBOLS:
            streak = streaks.get(sym, 0)
            has = _stock_has_data(sym, last_values, history)
            statuses[sym] = (trend_label(streak, has), _trend_desc(streak, has, sym))
        elif sym == "MOVE":
            statuses[sym] = classify_move(val)
        else:
            statuses[sym] = classify_vix(val)
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
        parts.append("全部市场指数数据获取完整，无异常。")
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


# ---- 历史数据层 ----
def load_history() -> list[dict]:
    """读取历史记录 [{date, vix, vxn, move}]；文件缺失、损坏或格式异常时按空历史处理。"""
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
    return [
        {
            "date": str(rec.get("date", "")),
            "vix": rec.get("vix"),
            "vxn": rec.get("vxn"),
            "move": rec.get("move"),
            "gspc": rec.get("gspc"),
            "ixic": rec.get("ixic"),
            "sh": rec.get("sh"),
            "sz": rec.get("sz"),
            "cyb": rec.get("cyb"),
            "gld": rec.get("gld"),
            "btc": rec.get("btc"),
            }
        for rec in data
        if isinstance(rec, dict) and rec.get("date")
    ]


def append_history(record: dict) -> None:
    """追加当日记录（同日重复按 date 键覆盖），裁剪至最近 90 条；临时文件 + os.replace 原子写。"""
    records = load_history()
    records = [r for r in records if r.get("date") != record.get("date")]
    records.append(record)
    records = records[-HISTORY_MAX:]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_name(HISTORY_FILE.name + ".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, HISTORY_FILE)
