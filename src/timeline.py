"""时间线组装（2026-09-18）：经济事件 × 行情影响 × 新闻叙事 → `/api/timeline` 的 payload。

任务档：`tasks/2026-09-18-event-timeline-page/`（plan v3 定稿）。

**三层口径（plan §4.3 / §7）**：

1. **事件层**：来自 `data/marketpulse.db` 的 `econ_events`（P1 落盘），按 `(date, kind)` 去重（官方源优先）。
2. **影响层**：当日 = 事件日各标的涨跌幅；事件后 = `+1/+3/+5/+10 交易日`**点对点收益**
   —— 与 `scripts/backtest.py:29 HORIZONS` **同一口径**（按 history 行序前推 h 行，非交易日历）。
   ⚠️ **"未走满"逐键判断**：实测同一天的 `gspc` 已有值而 `ixic` 还没值 ⇒ 必须 `row.get(key)`，
   不能按行判断（否则会把有数据的列一起标成"无数据"）。
   ⚠️ **点对点口径说明不了因果**：那几天大盘本来也在涨跌。页面必须并列展示、不生成"因 X 所以 Y"。
3. **叙事层（P3）**：Google News RSS（`after:` / `before:` 限定到事件日当天）→ 热度（篇数）+ 首条标题。
   热度受**每次 100 条上限**影响 ⇒ 只能读作"**至少**这么多篇"（plan §7-3）。

**诚实边界**：日历时间是"排定/估计"值（抄 OpenBB 文档口径），不是数据真正公开的时刻；
BLS/BEA/Census 事件经**第三方镜像**获得，原始来源为 bls.gov / bea.gov / census.gov。
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
import urllib.request
from datetime import date as _date, datetime, timedelta

from . import econ_calendar as ec
from . import econ_values as econv      # 别名避开 build_timeline 里的循环变量 `ev`

log = logging.getLogger("marketpulse")

#: 事件后窗口（交易日）—— 与 scripts/backtest.py 的 HORIZONS 同口径，改这里必须同步改那边
HORIZONS: tuple[int, ...] = (1, 3, 5, 10)
#: 当日涨跌展示的标的（A 股只取上证；深/创另有专题页）
DAY_KEYS: tuple[str, ...] = ("gspc", "ixic", "sh")
VIX_KEY = "vix"

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
GNEWS_URL = ("https://news.google.com/rss/search?q={q}+after%3A{d1}+before%3A{d2}"
             "&hl=en-US&gl=US&ceid=US:en")

#: 事件类型 → 检索词（英文；口径写死在表里，便于复核）
NEWS_QUERIES: dict[str, str] = {
    "FOMC": "FOMC rate decision Federal Reserve",
    "非农": "US jobs report nonfarm payrolls",
    "CPI": "US CPI inflation report",
    "PPI": "US PPI producer prices",
    "GDP": "US GDP report",
    "PCE": "US PCE inflation personal income",
    "零售": "US retail sales",
    "工业产出": "US industrial production",
    ec.KIND_OTHER: "US economic data release",
}

#: 源与口径说明（页面照此渲染；plan §7-2 要求标注镜像来源）
SOURCE_NOTES: tuple[dict, ...] = (
    {"source": "fed", "label": "美联储官网 FOMC 日历",
     "url": ec.FED_URL, "note": "官方直连；决议日取两日会议的第二天（含 SEP 标注）"},
    {"source": "mirror", "label": "第三方经济日历镜像",
     "url": ec.MIRROR_PAGE,
     "note": "BLS / BEA / Census / 工业产出经此镜像获得；原始来源 bls.gov / bea.gov / census.gov"},
    {"source": "values", "label": "TradingView 经济日历（结果值层）",
     "url": econv.TV_PAGE,
     "note": "事件行的「实际 / 预期 / 前值」数值来源（第三方源，非官方发布页）；"
             "美国 CPI 显示为指数水平（非同比）；源未提供单位的指标按原始数值显示"},
    {"source": "news", "label": "Google News 检索",
     "url": "https://news.google.com/",
     "note": "热度为检索口径，受每次 100 条上限影响，只能读作「至少这么多篇」"},
)


# ------------------------------------------------------------------ 行情侧

def _clean_history(history) -> list[dict]:
    """行情记录规范化：date 为 str、键小写、按日期升序（缺日期行丢弃）。"""
    out = []
    for rec in history or []:
        if not isinstance(rec, dict):
            continue
        d = rec.get("date")
        if not d:
            continue
        row = {"date": str(d)}
        for k, v in rec.items():
            if k == "date":
                continue
            try:
                row[str(k).lower()] = None if v is None else float(v)
            except (TypeError, ValueError):
                row[str(k).lower()] = None
        out.append(row)
    out.sort(key=lambda r: r["date"])
    return out


def _index_of(records: list[dict], day: str) -> int | None:
    for i, r in enumerate(records):
        if r["date"] == day:
            return i
    return None


def trading_axes(records: list[dict], keys=DAY_KEYS + (VIX_KEY,)) -> dict[str, list[tuple[int, float]]]:
    """每个标的的**交易日轴**：`[(records 下标, 值), ...]`，只保留"非空且与前一个保留值不同"的行。

    ⚠️ **为什么必须有这一步（实测证据，2026-09-18）**：`history` 表在**休市日带"沿用值"**——

    ```
    2026-09-04 Fri  gspc=7718.6    sh=3930.1164
    2026-09-05 Sat  gspc=None      sh=3930.1164   <- 沿用周五（A 股休市）
    2026-09-06 Sun  gspc=7718.6    sh=3930.1164   <- 沿用周五（美股休市）
    2026-09-07 Mon  gspc=7718.6    sh=3932.6992   <- 美国劳动节，gspc 继续沿用
    ```

    ⇒ 直接按**行序** +h（`scripts/backtest.py` 的既有口径）会把"沿用行"当成交易日，
    算出**假的 `0.00%`**（实测 09-04 的 `sh` 在 +1 行得到 `0.0`），并让此后每个窗口整体错位一天。
    剔除"与前值相同的行"即得到该标的**真实交易日序列**；同时它也天然处理了美股/A 股休市不同步
    （各标的各算各的轴，互不污染）。

    代价：**真正的"零变动日"会被并掉**（指数两位小数下几乎不可能出现）⇒ 影响可忽略。
    """
    axes: dict[str, list[tuple[int, float]]] = {}
    for key in keys:
        axis: list[tuple[int, float]] = []
        prev: float | None = None
        for i, row in enumerate(records):
            v = row.get(key)
            if v is None:
                continue
            if prev is None or v != prev:
                axis.append((i, v))
                prev = v
        axes[key] = axis
    return axes


def _axis_pos(axis: list[tuple[int, float]], day: str, records: list[dict]) -> int | None:
    """`day` 在该标的交易日轴上的位置（不在轴上 → None，即该标的当日休市/无数据）。"""
    i = _index_of(records, day)
    if i is None:
        return None
    for pos, (idx, _v) in enumerate(axis):
        if idx == i:
            return pos
    return None


def same_day_changes(records: list[dict], day: str,
                     axes: dict[str, list[tuple[int, float]]] | None = None) -> dict | None:
    """事件日各标的涨跌幅（%）+ VIX 变化 —— **在该标的的交易日轴上**取前一个真实交易日比。

    与页面其它处同一算法（相邻收盘比），但**跳过"沿用值"行**：否则周一/节后首日会拿到 `0.00%`
    （拿休市那天的沿用值当"前收"）。
    """
    axes = axes or trading_axes(records)
    out: dict[str, float | None] = {}
    for key in DAY_KEYS + (VIX_KEY,):
        pos = _axis_pos(axes.get(key, []), day, records)
        if pos is None or pos == 0:
            out[key] = None
            continue
        cur = axes[key][pos][1]
        prev = axes[key][pos - 1][1]
        out[key] = None if not prev else (cur - prev) / prev * 100.0
    if all(v is None for v in out.values()):
        return None
    return out


def forward_returns(records: list[dict], day: str, keys=DAY_KEYS,
                    horizons=HORIZONS, axes: dict[str, list[tuple[int, float]]] | None = None) -> dict:
    """事件后 +h **交易日**点对点收益（%）：`{h: {key: pct|None}}`。

    - 步长 = **该标的的交易日**（见 `trading_axes`；不是 history 行序，理由与证据见上）。
    - ⚠️ **逐键判空**：各标的休市与数据到位节奏不同（实测 09-17 的 `gspc` 有值而 `ixic` 未走满、
      同期 `sh` 已有值）⇒ 必须 `axis[pos + h]` 逐键判断，**不能按行判断**。
    - 走不满 / 事件日该标的休市 / 基准缺失 → 该键 `None`（页面渲染「待走满」，**绝不显示 0.00%**）。
    """
    axes = axes or trading_axes(records, keys)
    out: dict[str, dict[str, float | None]] = {}
    for h in horizons:
        per: dict[str, float | None] = {}
        for key in keys:
            axis = axes.get(key, [])
            pos = _axis_pos(axis, day, records)
            if pos is None:
                per[key] = None
                continue
            base = axis[pos][1]
            j = pos + h
            cur = axis[j][1] if j < len(axis) else None
            per[key] = None if (not base or cur is None) else (cur - base) / base * 100.0
        out[str(h)] = per
    return out


# ------------------------------------------------------------------ 叙事层（P3）

def parse_news_rss(xml: str) -> dict:
    """Google News RSS → `{count, title, link}`；`count` = 本次检索返回的条目数（上限 100）。"""
    items = re.findall(r"<item>(.*?)</item>", xml or "", re.S)
    first_title = first_link = None
    if items:
        m = re.search(r"<title[^>]*>(.*?)</title>", items[0], re.S)
        if m:
            first_title = _unescape_xml(m.group(1))
        m = re.search(r"<link[^>]*>(.*?)</link>", items[0], re.S)
        if m:
            first_link = _unescape_xml(m.group(1))
    return {"count": len(items), "title": first_title, "link": first_link}


def _unescape_xml(s: str) -> str:
    return (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")).strip()


def news_url(kind: str, day: str) -> str:
    """事件类型 + 事件日 → 检索 URL（当天的新闻窗口：`after:D before:D+1`）。"""
    q = NEWS_QUERIES.get(kind) or NEWS_QUERIES[ec.KIND_OTHER]
    d1 = _date.fromisoformat(day)
    return GNEWS_URL.format(q=urllib.parse.quote_plus(q), d1=d1.isoformat(),
                            d2=(d1 + timedelta(days=1)).isoformat())


def fetch_event_news(events: list[dict], today: str | None = None, timeout: int = 20,
                     max_requests: int = 40, pause: float = 0.4) -> tuple[list[tuple], list[str]]:
    """为**已发生**事件抓叙事层 → `([(date, kind, count, title, link)], failed)`。

    只抓 `date <= today` 的事件（未来事件没有新闻，抓了也是空 —— 省一半请求）。
    单条失败 → 记入 `failed` 继续（**不抛异常、不清空既有数据**，调用方负责"失败不覆盖"）。
    """
    today = today or _date.today().isoformat()
    rows: list[tuple] = []
    failed: list[str] = []
    seen: set[tuple[str, str]] = set()
    todo = []
    for ev in events:
        key = (ev["date"], ev["kind"])
        if key in seen or ev["date"] > today:
            continue
        seen.add(key)
        todo.append(key)
    todo.sort()
    for day, kind in todo[:max_requests]:
        url = news_url(kind, day)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                xml = resp.read().decode("utf-8", errors="replace")
            got = parse_news_rss(xml)
            rows.append((day, kind, got["count"], got["title"], got["link"]))
        except Exception as exc:            # noqa: BLE001
            log.warning("[timeline] 叙事层抓取失败 %s %s: %s", day, kind, exc)
            failed.append("%s/%s" % (day, kind))
        time.sleep(pause)                   # 礼貌节流：别把检索当爬虫
    return rows, failed


# ------------------------------------------------------------------ 组装

def build_timeline(events: list[dict], history, news: dict | None = None,
                   today: str | None = None, past_days: int = 90,
                   future_days: int = 30, failed: list[str] | None = None) -> dict:
    """事件 + 行情 + 叙事 → 页面 payload（**按日期分组**）。

    返回结构：

    ```
    {as_of, window, stats, sources, failed,
     past:     [{date, events:[...], market:{...}|None, forward:{h:{k:pct|None}}}, ...],  # 日期降序
     upcoming: [同上]}                                                                   # 日期升序
    ```

    - 事件先按 `(date, kind)` 去重（官方源优先；库里两源都留着做对账）—— 与 `TL-5` 对应。
    - `market` / `forward` 是**按日**的事实（同日多事件共用），故挂在 day 上而不是事件上
      （plan §4.1 的平铺模型在此收成 day 级，语义等价且不重复存）。
    - 新闻（叙事层）是**按 (date, kind)** 的，挂回各自事件。
    """
    today = today or _date.today().isoformat()
    recs = _clean_history(history)
    axes = trading_axes(recs)
    news_map = news or {}
    merged = ec.merge_events(events)
    past_from = (_date.fromisoformat(today) - timedelta(days=past_days)).isoformat()
    fut_to = (_date.fromisoformat(today) + timedelta(days=future_days)).isoformat()

    by_day: dict[str, list[dict]] = {}
    for ev in merged:
        d = ev["date"]
        if d < past_from or d > fut_to:
            continue
        item = {
            "kind": ev["kind"],
            "title": ev.get("title") or "",                 # 源站原文（英文）——**不丢**，页面挂在悬停里
            "title_zh": ec.zh_title(ev),                    # 中文事件名（模板生成，见 econ_calendar.zh_title）
            "agency": ev.get("agency"),
            "source": ev.get("source"),
            "time_et": ev.get("time_et"),
            "status": ev.get("status") or "ok",
            "note": ev.get("note") or "",
        }
        # ---- 结果值层（2026-09-19）：**必须逐键显式加**，否则表里加了列也不透传 ----
        # 值可能全为 None（骨架行没被 enrich 到 / 窗口外 / 值侧失败）=> 键必须在，值可为 null。
        # `importance` 只透传、不上色（plan D-3a）；`value_fetched_at` 供排查时点。
        for _k in ("actual", "forecast", "previous", "unit", "importance",
                   "value_source", "value_title", "value_fetched_at"):
            item[_k] = ev.get(_k)
        nw = news_map.get((d, ev["kind"]))
        item["news_count"] = (nw or {}).get("count")
        item["news_title"] = (nw or {}).get("title")
        item["news_link"] = (nw or {}).get("link")
        by_day.setdefault(d, []).append(item)

    def make_day(d: str) -> dict:
        return {
            "date": d,
            "events": sorted(by_day[d], key=lambda e: (e["time_et"] or "99:99", e["kind"])),
            "market": same_day_changes(recs, d, axes),
            "forward": forward_returns(recs, d, axes=axes),
        }

    past = [make_day(d) for d in sorted(by_day, reverse=True) if d < today]
    upcoming = [make_day(d) for d in sorted(by_day) if d >= today]
    db_min, db_max = timeline_db_range(merged)
    return {
        "as_of": today,
        "window": {"past_days": past_days, "future_days": future_days},
        # 库内**全部**事件的日期范围（不受本次窗口限制）：页面据此显示"可回溯到"并决定
        # 「加载更早」是否还有意义（避免点到底才发现没有更多）。
        "db_range": [db_min, db_max],
        "stats": {
            "past_days": len(past), "past_events": sum(len(x["events"]) for x in past),
            "upcoming_days": len(upcoming),
            "upcoming_events": sum(len(x["events"]) for x in upcoming),
            "db_events": len(events or []),
            "covered_days": len(recs),
        },
        "sources": list(SOURCE_NOTES),
        "failed": list(failed or []),
        "past": past,
        "upcoming": upcoming,
    }


def timeline_db_range(events: list[dict]) -> tuple[str | None, str | None]:
    """库里事件的日期范围（页面「可回溯到」文案用）。"""
    ds = [e["date"] for e in events or [] if e.get("date")]
    return (min(ds), max(ds)) if ds else (None, None)
