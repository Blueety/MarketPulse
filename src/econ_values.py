"""事件结果值层（2026-09-19）：TradingView 经济日历 → `actual / forecast / previous`。

任务档：`tasks/2026-09-19-timeline-event-values/`（plan 定稿，方案 A「骨架不动 + 值层 join」）。

**为什么需要这个模块**：`econ_events` 的骨架源（Fed 官方页 / 第三方镜像 `.ics`）都是**纯日程源**，
源头就没有数值 ⇒ 取值只能引入带值的新源。本模块是**值侧**，骨架侧（`econ_calendar.py`）零改动。

**数据源与请求形态（2026-09-19 本机直连实测：HTTP 200 / 1.67s / 229 KB / 无 key / 无代理）**：

```
GET https://economic-calendar.tradingview.com/events
      ?from=<ISO8601 UTC>&to=<ISO8601 UTC>&countries=US
```

- **必须带 `Origin` / `Referer`**（不带会被拒），无需任何 API key。
- ⚠️ **单请求上限 2000 条**：实测 2019 / 2021 / 2023 / 2025 / 2026 **全年 US 都恰好 2000**（打满上限，
  静默截断），而单月约 170–350 条 ⇒ 抓取**一律按月分段**（见 `month_segments`），年度窗口不能一把梭。
- 🔻 **端点未公开、无 SLA、可能改结构或限频**。**若将来失效，这样重新定位**：
  打开 tradingview.com 的经济日历页 → DevTools → Network → 过滤 `economic-calendar` →
  抄新的 `/events` 请求 URL 与必需头；再跑一次「全年 vs 单季条数是否相等」确认新的分页上限。
  已实测的替代源与排除理由见 plan §2（TradingEconomics guest 已 410、FMP 需商用 key、
  FRED 无预期值、ForexFactory 403、jin10 502/404）；BLS 官方 API 可作**交叉校验**退路（只有实际值）。

**三条口径纪律（照 plan D2.1 / D3 / D4 写，都有实测依据）**：

1. **匹配键用美东日期，不用 UTC 日期**（D4）：TV 的 `date` 是 UTC ISO（`2026-09-16T18:00:00.000Z`），
   转 ET 后得到 `08:30` / `14:00` / `09:15`，与骨架 `time_et` **逐一吻合**。
   ⚠️ 直接用 UTC 日期，落在 00:00–04:00Z 的事件会**错一天**（当前 8 类都在 12:30Z–19:00Z 不触发，
   但规则必须写对，否则将来扩类型必错）。**零容差**：实测过去事件 100% 命中，加 ±1 天容差只会引入错配。
2. **`unit` 缺失不得猜单位**（D-1a 的直接推论）：实测美国 `CPI` / `Non Farm Payrolls` 的 `unit`
   **连键都没有**（4658 条里只有 2072 条带该键）⇒ 原样返回 `None`，**绝不**补 `%` / `点` / `千人`。
   仅 `%` 会出现在本模块 enrich 的 8 类上（实测），故单位一律**原样后缀**，不发明摆放规则。
3. **同日同 kind 多行必须择优**（D3）：实测 `2025-12-16` 有**两条** `Non Farm Payrolls`
   （一条 `fc=None`、一条 `fc=50`；政府停摆顺延的两个数据期）⇒ 按「forecast 非空 > actual 非空 >
   previous 非空，再取 date 较晚者」择优，且**两条候选的空值形态相同时记 warning**（暴露歧义，不静默）。

**分工边界**：本模块**只算值、不写库**（返回 `update_econ_event_values` 能吃的 dict 列表），
落库与 preserve 语义在 `src/storage.py`；失败时返回空 + `failed` 记 `tradingview`，
调用方负责"失败不覆盖"（既有值保留，页面退化成"只有事件名"）。
"""

from __future__ import annotations

import logging
import time
from datetime import date as _date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from . import econ_calendar as ec

log = logging.getLogger("marketpulse")

TV_URL = "https://economic-calendar.tradingview.com/events"
TV_PAGE = "https://www.tradingview.com/economic-calendar/"
#: 值侧来源名（`source` 字段缺失时用它兜底，页面照此标注）
TV_SOURCE = "TradingView 经济日历"

#: 必带请求头（实测：不带 `Origin`/`Referer` 会被拒）
TV_HEADERS = {
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
}

ET = ZoneInfo("America/New_York")

#: 值的重算窗口（天）。**刻意与页面默认窗口 `/api/timeline?days=90&future_days=30` 取齐**：
#: 于是「库里有 `actual` 的行」== 「页面默认窗口里有 `actual` 的事件」，
#: `EV-2` 的三方对账（sqlite 直查 vs API vs DOM）才能**字面成立**。
#: ⚠️ 将来若加宽本窗口，必须同步把 `EV-2` 的 sqlite 侧也限制到同一 range（否则三方计数必然不等）。
#: ⚠️ 每次同步都**重算整个窗口**（幂等 upsert）：`actual` 只在公布之后才出现，
#: 「公布当天那次没抓到」是常态 ⇒ 不能只在事件当天抓一次（plan D5）。
VALUE_PAST_DAYS = 90
VALUE_FUTURE_DAYS = 30

#: 单段请求的礼貌间隔（秒）
SEGMENT_PAUSE = 0.3

#: `kind` → TV headline **精确标题**（已用 2025-08 ~ 2026-09 的真实标题枚举核实，见 plan D2）。
#: ⚠️ 必须精确匹配，不能用子串：同族还有 `PPI YoY` / `Core PPI MoM` / `Non Farm Payrolls Annual Revision`
#: 等一堆**不属本类**的行，子串匹配会混进来。
HEADLINE: dict[str, str] = {
    "FOMC": "Fed Interest Rate Decision",
    "非农": "Non Farm Payrolls",
    "CPI": "CPI",
    "PPI": "PPI MoM",
    "PCE": "Core PCE Price Index MoM",
    "零售": "Retail Sales MoM",
    "工业产出": "Industrial Production MoM",
}

#: 首选标题缺失时的备选（实测 `Core PCE Price Index MoM` 是 headline；`PCE Price Index MoM` 更宽，
#: 仅在首选抓不到时兜底 —— 顺序即优先级）。
FALLBACK: dict[str, tuple[str, ...]] = {
    "PCE": ("PCE Price Index MoM",),
}

#: GDP 的**期次**标题（plan D2：TV 同期有 Adv / 2nd Est / Final 三行，**必须按期次选，
#: 不能按顺序取第一条**）。骨架侧的中文期次由既有的 `econ_calendar._stage_zh` 解析（零重复实现）。
GDP_PREFIX = "GDP Growth Rate QoQ"
GDP_STAGE = {"初值": "Adv", "第二次估计": "2nd Est", "终值": "Final"}


# ------------------------------------------------------------------ 纯函数：时间与分段

def et_parts(iso_utc: str | None) -> tuple[str | None, str | None]:
    """TV 的 UTC ISO 时刻 → `(美东日期, 美东 HH:MM)`；解析不了返回 `(None, None)`。

    `2026-09-16T18:00:00.000Z` → `("2026-09-16", "14:00")`（实测与骨架 `time_et` 吻合）。
    """
    v = (iso_utc or "").strip()
    if not v:
        return None, None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local = dt.astimezone(ET)
    return local.strftime("%Y-%m-%d"), local.strftime("%H:%M")


def month_segments(d1: str, d2: str) -> list[tuple[str, str]]:
    """`[d1, d2]` → 按自然月切段 `[(from, to), ...]`（`to` 为**闭区间次日**，即不含）。

    单请求上限 2000 条（实测常年打满）⇒ 必须分段；单月约 170–350 条，安全。
    """
    segs: list[tuple[str, str]] = []
    cur = _date.fromisoformat(d1)
    end = _date.fromisoformat(d2)
    while cur <= end:
        nxt = _date(cur.year + 1, 1, 1) if cur.month == 12 else _date(cur.year, cur.month + 1, 1)
        stop = min(nxt, end + timedelta(days=1))
        segs.append((cur.isoformat(), stop.isoformat()))
        cur = nxt
    return segs


# ------------------------------------------------------------------ 纯函数：映射与择优

def headlines_for(kind: str, skel_title: str = "") -> tuple[str, ...]:
    """`(kind, 骨架英文标题)` → 可接受的 TV 标题（**顺序即优先级**，首项为首选）。

    GDP 走**期次**路径：骨架标题里的 `Advance / Second / Third Estimate` 由既有的
    `econ_calendar._stage_zh` 解析成 `初值 / 第二次估计 / 终值`，再映射到 TV 的 `Adv / 2nd Est / Final`。
    解析不出期次时（防御路径，实测骨架里都能解析出）退回**全部三行 + 无后缀行**，并记 warning ——
    宁可让择优规则去挑，也不静默丢弃。
    """
    if kind == "GDP":
        stage = ec._stage_zh(skel_title or "")
        suffix = GDP_STAGE.get(stage or "")
        if suffix:
            return ("%s %s" % (GDP_PREFIX, suffix),)
        log.warning("[econ_values] GDP 骨架标题未解析出期次，退回全期次候选: %r", (skel_title or "")[:80])
        return tuple("%s %s" % (GDP_PREFIX, s) for s in GDP_STAGE.values()) + (GDP_PREFIX,)
    if kind in HEADLINE:
        return (HEADLINE[kind],) + FALLBACK.get(kind, ())
    return ()


def _title_to_kind() -> dict[str, str]:
    """TV 标题 → kind 的反查表（GDP 三行用前缀归并，其余精确匹配）。"""
    out: dict[str, str] = {}
    for kind, title in HEADLINE.items():
        out[title] = kind
        for alt in FALLBACK.get(kind, ()):
            out.setdefault(alt, kind)
    return out


_TITLE_KIND = _title_to_kind()


def kind_of_tv_row(row: dict) -> str | None:
    """TV 行 → kind；不属于本模块 enrich 的 8 类 → `None`（**其余 TV 指标一律不入库**）。"""
    title = row.get("title") or ""
    if title == GDP_PREFIX or title.startswith(GDP_PREFIX + " "):
        return "GDP"
    return _TITLE_KIND.get(title)


def rank_row(row: dict) -> tuple:
    """择优排序键（D3）：`forecast` 非空 > `actual` 非空 > `previous` 非空，再取 `date` 较晚者。

    沿用既有 `econ_calendar._rank` 的模式。`None` 与 `0.0` 必须区分：TV 的 `forecast: 0` 是
    **真实预期值 0**（实测 `2026-07-15 PPI MoM` 的 fc=0），不能被当成"没有预期"。
    """
    return (1 if row.get("forecast") is not None else 0,
            1 if row.get("actual") is not None else 0,
            1 if row.get("previous") is not None else 0,
            str(row.get("date") or ""))


def build_value_map(tv_rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """TV 行 → `{(美东日期, kind): [候选行, ...]}`（**只分组，不择优** —— 择优要拿到骨架标题）。"""
    out: dict[tuple[str, str], list[dict]] = {}
    for row in tv_rows or []:
        kind = kind_of_tv_row(row)
        if not kind:
            continue
        day, _hm = et_parts(row.get("date"))
        if not day:
            continue
        out.setdefault((day, kind), []).append(row)
    return out


def pick_for(skel: dict, candidates: list[dict]) -> tuple[dict | None, bool]:
    """骨架行 → `(选中的 TV 行 | None, 是否有歧义)`。

    三步：
    ① 按 `headlines_for(kind, 骨架标题)` 过滤（GDP 靠这一步锁定期次）；
    ② **首选标题优先**：`headlines_for` 是**有序**表，只要首选标题当天存在，就**只在首选里选**
       （备选仅在首选缺失时启用）。⚠️ 这一步不能省：PCE 的同一天**同时**存在
       `Core PCE Price Index MoM`（首选）与 `PCE Price Index MoM`（备选），两者的
       `rank_row` 键完全并列 ⇒ 只靠 `rank_row` 会由**上游返回顺序**决定取哪条（实测取到了备选，
       即非 Core 的那条）。
    ③ 再按 `rank_row` 降序取首；前两名**空值形态完全相同**时记 warning（择优规则无法区分，不静默取第一条）。
    """
    wanted = list(headlines_for(skel.get("kind") or "", skel.get("title") or ""))
    pref = {t: i for i, t in enumerate(wanted)}
    rows = [r for r in candidates if (r.get("title") or "") in pref]
    if not rows:
        return None, False
    top = min(pref[r["title"]] for r in rows)
    rows = [r for r in rows if pref[r["title"]] == top]      # 首选标题存在则不看备选
    rows.sort(key=rank_row, reverse=True)
    ambiguous = len(rows) > 1 and rank_row(rows[0])[:3] == rank_row(rows[1])[:3]
    return rows[0], ambiguous


def value_entry(skel: dict, row: dict) -> dict:
    """骨架行 + 选中的 TV 行 → 落库用的值层 dict（形状与 `storage.update_econ_event_values` 对齐）。"""
    return {
        "date": skel["date"],
        "kind": skel["kind"],
        "actual": row.get("actual"),
        "forecast": row.get("forecast"),
        "previous": row.get("previous"),
        "unit": row.get("unit"),                       # ⚠️ 可能是**键缺失** ⇒ 用 .get，不许补默认单位
        "importance": row.get("importance"),           # 只落库、不上色（D-3a）
        "value_source": row.get("source") or TV_SOURCE,
        "value_title": row.get("title") or "",
    }


def join_skeleton(skeleton: list[dict], value_map: dict[tuple[str, str], list[dict]]) -> list[dict]:
    """骨架行 × 值表 → 待落库的值层列表（**只保留真有命中的**，未命中不产生条目）。"""
    out: list[dict] = []
    for skel in skeleton or []:
        key = (skel.get("date"), skel.get("kind"))
        cands = value_map.get(key)
        if not cands:
            continue
        row, ambiguous = pick_for(skel, cands)
        if row is None:
            continue
        if ambiguous:
            log.warning("[econ_values] %s %s 有并列候选，择优规则无法区分（取 %r）",
                        skel.get("date"), skel.get("kind"), row.get("title"))
        out.append(value_entry(skel, row))
    return out


# ------------------------------------------------------------------ 抓取

def fetch_events(d1: str, d2: str, timeout: int = 40) -> tuple[list[dict], list[str]]:
    """抓 `[d1, d2]` 的美股相关事件（按月分段）。返回 `(rows, failed)`。

    单段失败 → 记入 `failed` 并继续（**不抛异常**）；调用方据此把 `tradingview` 汇总进 `failed`
    且**保留既有值**（失败不覆盖）。
    """
    rows: list[dict] = []
    failed: list[str] = []
    segs = month_segments(d1, d2)
    for i, (a, b) in enumerate(segs):
        params = {"from": "%sT00:00:00.000Z" % a, "to": "%sT00:00:00.000Z" % b, "countries": "US"}
        try:
            resp = requests.get(TV_URL, params=params, headers=TV_HEADERS, timeout=timeout)
            resp.raise_for_status()
            got = (resp.json() or {}).get("result") or []
            rows += got
            log.info("[econ_values] 段 %s 取回 %d 条", a[:7], len(got))
        except Exception as exc:                    # noqa: BLE001 —— 单段失败不拖垮整轮
            log.warning("[econ_values] 段 %s 抓取失败：%s", a[:7], exc)
            failed.append("tradingview:%s" % a[:7])
        if i < len(segs) - 1:
            time.sleep(SEGMENT_PAUSE)               # 礼貌节流
    return rows, failed


def value_window(today: str | None = None, past_days: int = VALUE_PAST_DAYS,
                 future_days: int = VALUE_FUTURE_DAYS) -> tuple[str, str]:
    """值的重算窗口 `(起, 止)`（闭区间）。

    单独成函数是为了让**调用方（sync 脚本的日志）**与 `collect_values` 用**同一份**窗口规则 ——
    各写一份必然漂移（"命中 N/M" 的 M 口径就会与真实窗口不一致）。
    """
    d = _date.fromisoformat(today) if today else _date.today()
    return ((d - timedelta(days=past_days)).isoformat(),
            (d + timedelta(days=future_days)).isoformat())


def in_window(skeleton: list[dict], today: str | None = None, past_days: int = VALUE_PAST_DAYS,
              future_days: int = VALUE_FUTURE_DAYS) -> list[dict]:
    """筛出**窗口内**的骨架行（`value_window` 的闭区间）。

    ⚠️ 窗口必须**两侧都卡**：只卡抓取范围不够 —— 若上游返回了窗口外的行（`from`/`to` 边界语义
    不保证严格），窗口外的骨架行就会被 join 上，出现"窗口外也带值"的越界 enrich。
    单独成函数是为了让 sync 脚本日志里的分母（"命中 N/M"的 M）与这里**同源**。
    """
    d1, d2 = value_window(today, past_days, future_days)
    return [s for s in (skeleton or []) if s.get("date") and d1 <= str(s["date"]) <= d2]


def collect_values(skeleton: list[dict], today: str | None = None,
                   past_days: int = VALUE_PAST_DAYS, future_days: int = VALUE_FUTURE_DAYS,
                   timeout: int = 40, fetch=None) -> tuple[list[dict], list[str]]:
    """骨架行 → `(待落库值层, failed)`。

    - 窗口 = `[today - past_days, today + future_days]`（`value_window`），与页面默认窗口取齐
      （见 `VALUE_PAST_DAYS` 注释）；窗口外的骨架行一律不 enrich。
    - **只 enrich 骨架已有行**（plan D-5a）：值侧有、骨架没有的事件不会进结果
      （`join_skeleton` 以骨架为驱动遍历）。
    - 值侧整段失败 → 返回已拿到的部分 + `failed`；**全失败返回空列表**（调用方不写库 ⇒ 既有值保留）。
    - `fetch` 可注入（单测用固定 fixture，**不联网**）。
    """
    today = today or _date.today().isoformat()
    fetch = fetch or fetch_events
    d1, d2 = value_window(today, past_days, future_days)
    win = in_window(skeleton, today, past_days, future_days)
    skipped = len(skeleton or []) - len(win)
    tv_rows, failed = fetch(d1, d2, timeout=timeout)
    if not tv_rows:
        log.warning("[econ_values] 值侧无数据（failed=%s），不覆盖既有值", failed)
        return [], failed
    value_map = build_value_map(tv_rows)
    values = join_skeleton(win, value_map)
    log.info("[econ_values] 窗口 %s ~ %s：TV %d 条 → 骨架 %d 条（窗口外跳过 %d）→ 命中 %d 条",
             d1, d2, len(tv_rows), len(win), skipped, len(values))
    return values, failed
