"""经济事件日历（2026-09-18）：官方发布日程的两个抓取器 + 归一化 + 过滤去重。

任务档：`tasks/2026-09-18-event-timeline-page/`（plan v3 定稿 / research.md 调研依据）。

**分工（plan §2，实测确定）**：

- **Fed 官方 FOMC 日历**（HTML 直连，200）→ **FOMC 会议**（唯一负责方）。
  ⚠️ 镜像里也有 FOMC 家族的条目（`FOMC Meeting Day 1/Day 2` / `Rate Decision` / `Press Conference` /
  `FOMC Minutes Release`），但它们会把**同一次会议拆成 3~4 条**（Day1 与 Day2 还是不同日期）
  ⇒ 本模块把镜像里的 FOMC 家族**整族丢弃**，FOMC 一律以官方源为准（plan §2 的分工表：Fed 页 = FOMC）。
- **第三方镜像 .ics**（smartcalendars.ai，200，185 条）→ BLS（非农/CPI/PPI）+ BEA（GDP/PCE）+ Census（零售）
  + Fed 工业产出。**BLS 官方 `.ics` 本机 403**（直连与代理都 403，research §2）⇒ 走镜像并标注来源。

**两个实测坑（plan §3，必须按此实现）**：

1. Fed 页的年份**不能按区块顺序推断**：实测 `<h4>` 顺序是 2026/2025/2024/2023/2022/2021/**2027**
   ⇒ 年份必须**从标题文本解析**（`<h4>2027 FOMC Meetings</h4>`），不能取首/末区块。
2. 镜像 `STATUS:CANCELLED` 占 75/185（40%）⇒ 必须过滤；`TENTATIVE` 保留并标 `tentative`
   （它是有效信息）。过滤后同一 `(日期, 归一化类型)` 仍可能重复（同一天两条非农、两条 PPI）⇒ 必须去重。

单位/口径约定：日期一律 `YYYY-MM-DD`；`time_et` 为美东时间 `HH:MM`（镜像的 `DTSTART` 有 159 条带 UTC 时刻，
转美东后正好落在 08:30 / 09:15 / 14:00 这些**公开惯例**时刻上，可作为解析正确性的交叉验证）。
"""

from __future__ import annotations

import logging
import re
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger("marketpulse")

FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
# ⚠️ 镜像的订阅地址是「feed 页里嵌的 hash 路径」，不是可猜的语义路径
#    （`/cal/<slug>.ics` 会 404；真实地址在 `https://www.smartcalendars.ai/en/feeds/us-economic-calendar`
#      的 RSC 载荷里）。若将来失效：重新抓那页，取 `webcal://.../cal/<hash>.ics`。
MIRROR_ICS_URL = ("https://www.smartcalendars.ai/cal/"
                  "8d6bda5ff8dc5f1a31ef90c28740dfccac475a43517c812de5f62283fcd1152c.ics")
MIRROR_PAGE = "https://www.smartcalendars.ai/en/feeds/us-economic-calendar"
MIRROR_ORIGIN = ("镜像自述来源：bls.gov / bea.gov / federalreserve.gov / census.gov"
                 "（页面上须如实标注）")

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ET = ZoneInfo("America/New_York")

KIND_OTHER = "其他"

# 归一化表（plan §4.2）：顺序敏感 —— 先匹配到的赢。
#   `agency` 是该类型的**原始发布机构**（页面据此显示"经由第三方镜像"的口径，plan §7-2）。
KIND_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("FOMC", "Fed", (r"\bFOMC\b", r"\bFOMC\b")),
    ("非农", "BLS", (r"Employment Situation", r"\bNonfarm\b", r"\bNFP\b")),
    ("CPI", "BLS", (r"Consumer Price Index", r"\bCPI\b")),
    ("PPI", "BLS", (r"Producer Price Index", r"\bPPI\b")),
    ("GDP", "BEA", (r"\bGDP\b",)),
    ("PCE", "BEA", (r"Personal Income and Outlays", r"\bPCE\b")),
    ("零售", "Census", (r"\bRetail\b", r"\bMARTS\b")),
    ("工业产出", "Fed", (r"Industrial Production", r"\bG\.17\b", r"\bG\.1\b")),
)

#: 归一化后的**合法类型**枚举（验收断言 TL-3 锁这个集合，防 §4.2 漏配后把原始事件名漏到页面上）
KINDS: tuple[str, ...] = tuple(k for k, _, _ in KIND_RULES) + (KIND_OTHER,)

#: 镜像里属于 Fed/FOMC 家族的条目（整族丢弃，见模块 docstring 的"分工"）
_FOMC_FAMILY_RE = re.compile(r"FOMC|Fed Interest Rate Decision|FOMC Press Conference", re.I)

_MONTH_NAMES = ("January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December")
_MONTHS = {m: i for i, m in enumerate(_MONTH_NAMES, start=1)}
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _month_num(token: str) -> int | None:
    """`September` / `Sep` / `Sept` → 9；认不出返回 None。

    ⚠️ Fed 页**同页混用全名与缩写**：普通行是 `<strong>January</strong>`，而跨月会议写成
    `<strong>Jan/Feb</strong>`、`<strong>Oct/Nov</strong>`（2023 两场、2024 一场）
    ⇒ 只认全名会**静默漏掉整场会议**（初版实测漏 3 场，靠逐块 raw_anchor 对账才发现）。
    """
    t = (token or "").strip().title()
    if t in _MONTHS:
        return _MONTHS[t]
    if len(t) >= 3:
        for i, name in enumerate(_MONTH_NAMES, start=1):
            if name.startswith(t):
                return i
    return None


# ---------------------------------------------------------------- 归一化

def normalize_kind(title: str) -> tuple[str, str | None]:
    """事件名 → `(kind, agency)`；未命中 → `(KIND_OTHER, None)` 并记 warning（不静默丢弃）。

    各源写法不一（`US Employment Situation Release` / `Employment Situation (Nonfarm Payrolls)` /
    `US Employment Situation Report — August 2026 Data`）⇒ 必须归一化，否则同一个非农会出现三四次。
    """
    text = title or ""
    for kind, agency, patterns in KIND_RULES:
        for pat in patterns:
            if re.search(pat, text, re.I):
                return kind, agency
    log.warning("[econ_calendar] 未归一化的事件名（归入 %s）: %r", KIND_OTHER, text[:80])
    return KIND_OTHER, None


def clean_summary(summary: str) -> str:
    """iCal 文本 → 干净标题：还原转义、去 `[CANCELLED]` 后缀、压空白。"""
    s = (summary or "").replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
    s = re.sub(r"\s*\[CANCELLED\]\s*$", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- 中文事件名（2026-09-19）

#: 类型 → 中文**短名**（前缀「美国」由 `zh_title` 统一加；括号里是给不熟悉缩写的读者加的全称）
KIND_ZH: dict[str, str] = {
    "FOMC": "美联储议息会议",
    "非农": "非农就业报告",
    "CPI": "CPI（消费者物价指数）",
    "PPI": "PPI（生产者物价指数）",
    "GDP": "GDP",
    "PCE": "PCE（个人消费支出物价指数）",
    "零售": "零售销售",
    "工业产出": "工业产出与产能利用率",
}
#: 需要「美国」前缀的类型（FOMC 本身已说明是美联储）
_ZH_NO_US = {"FOMC"}
_MONTH_ZH = ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月", "9 月", "10 月", "11 月", "12 月")
#: 估计阶段（GDP 三阶段 / 零售初值）—— **只翻译结构，不翻译内容**
_STAGE_RULES: tuple[tuple[str, str], ...] = (
    (r"Advance|First Estimate|1st Estimate", "初值"),
    (r"Second Estimate|2nd Estimate", "第二次估计"),
    (r"Third Estimate|3rd Estimate|Final Estimate", "终值"),
)


def _month_en(token: str) -> int | None:
    """英文月份（全名或缩写 `Sep`/`Sept`）→ 月份数字；认不出返回 None。

    ⚠️ 必须同时认缩写：源站日期段写 `Sep 15-16`、`Jan 31-Feb 1`（**只有缩写**），
    初版只查全名表 ⇒ 57 场 FOMC 里只有 3 场解析出日期段（其余中文标题丢了会期）。
    """
    t = (token or "").strip().rstrip(".").lower()
    if not t:
        return None
    for i, name in enumerate(_MONTH_NAMES, start=1):
        if name.lower() == t or (len(t) >= 3 and name.lower().startswith(t)):
            return i
    return None


def zh_title(ev: dict) -> str:
    """事件 → **中文标题**（用户 2026-09-19：「英文看不懂」）。

    **只翻译"结构"，不翻译"内容"**：类型名（`KIND_ZH`）+ 数据期（月份 / 季度）+ 估计阶段
    （初值 / 第二次估计 / 终值）全部**从源站英文标题里解析**，不做机器翻译、不编造信息。
    解析不到的部分就不写（例如 `US Industrial Production and Capacity Utilization - G.1`
    只有报告名、没有数据期 ⇒ 中文标题也不带月份），**不用发布日期顶替数据期**（那是错的口径）。

    - `其他` 类（未归一化）**不猜中文名**，原样返回英文，避免误译。
    - 数据年份与本事件年份不同（跨年发布，如 2026-01 发布 2025-12 数据）时**带年份**，否则只写月份。
    - 语序：`美国 8 月 CPI（消费者物价指数）` / `美国 2026 年 Q2 GDP 终值` / `美联储议息会议（9 月 15-16 日）`。
    """
    raw = ev.get("title") or ""
    kind = ev.get("kind") or KIND_OTHER
    base = KIND_ZH.get(kind)
    if not base:
        return raw                     # `其他`：宁可不译，也不猜
    if kind == "FOMC":
        span = _fomc_span_zh(raw)
        return base + ("（%s）" % span if span else "")
    year = str(ev.get("date") or "")[:4]
    period = _period_zh(raw, year)
    stage = _stage_zh(raw)
    # ⚠️ 两个空格规则（中文排版，u"空格"只加在"下半截是拉丁/数字"的那一侧）：
    #    ① 「美国」后面接的若是拉丁名（CPI…）或数字（`8 月`）→ 加空格；接中文名（非农就业报告…）→ 不加；
    #    ② 数据期后接拉丁名（CPI/PPI/GDP/PCE）→ 加空格；接中文名 → 不加。
    #    否则会渲染成「美国 工业产出…」或「美国8 月非农就业报告」。
    sep_pd = " " if base[:1].isascii() else ""
    sep_us = " " if (period or base)[:1].isascii() else ""
    prefix = "" if kind in _ZH_NO_US else ("美国" + sep_us)
    # ⚠️ 只有名字以拉丁字母开头（CPI/PPI/GDP/PCE）才在数据期后加空格；
    #    中文名（非农就业报告/零售销售…）不加 —— 否则会渲染成「美国 9 月 非农就业报告」。
    sep = " " if base[:1].isascii() else ""
    head = "%s%s" % (prefix, period + sep if period else "")
    text = head + base
    if kind == "GDP" and stage:
        text += " " + stage
    if kind == "零售" and stage == "初值":
        text += "（初值）"
    return text


def _stage_zh(raw: str) -> str | None:
    for pat, zh in _STAGE_RULES:
        if re.search(pat, raw, re.I):
            return zh
    return None


def _period_zh(raw: str, event_year: str = "") -> str:
    """从英文标题解析**数据期** → `8 月` / `2025 年 12 月` / `2026 年 Q2`；解析不到返回 ""。

    本模块曾被「经 shell heredoc 打补丁」写入过一次，**B 边界的反斜杠转义在传递中退化成了不可见的退格符**，
    导致季度/月份解析**静默失效**（中文标题里数据期全丢，而表观上完全看不出来）。
    教训见 docs/pitfalls.md「补丁经 shell 传递会吃掉反斜杠转义」。
    """
    NS = "[ ]"
    m = re.search(r"(?:^|[^A-Za-z])Q([1-4])" + NS + r"*([0-9]{4})(?![0-9])", raw)
    if not m:
        m = re.search(r"(?:^|[^A-Za-z])([1-4])(?:st|nd|rd|th)" + NS + r"+Quarter" + NS + r"+([0-9]{4})(?![0-9])", raw, re.I)
    if m:
        return "%s 年 Q%s" % (m.group(2), m.group(1))
    m = re.search(r"(?:^|[^A-Za-z])([A-Za-z]{3,9})[.]?" + NS + r"+([0-9]{4})(?![0-9])", raw)
    if m:
        num = _month_en(m.group(1))
        if num:
            yr = m.group(2)
            return ("%s 年 %s" % (yr, _MONTH_ZH[num - 1])) if (event_year and yr != event_year) else _MONTH_ZH[num - 1]
    return ""


def _fomc_span_zh(raw: str) -> str:
    """`FOMC Meeting - Sep 15-16, 2026` / `Jan 31-Feb 1, 2023` / `Aug 22, 2025` → 会期中文。

    覆盖两种形态：**两日会议**（`Sep 15-16` / 跨月 `Jan 31-Feb 1`）与**单日会议**（`Aug 22`，实测 2021~2027 有 1 场）。
    """
    NS = "[ ]"
    m = re.search(r"([A-Za-z]{3,9})[.]?" + NS + r"*([0-9]{1,2})" + NS + r"*-" + NS + r"*(?:([A-Za-z]{3,9})[.]?" + NS + r"*)?([0-9]{1,2})", raw)
    if m:
        m1, m2 = _month_en(m.group(1)), _month_en(m.group(3) or m.group(1))
        d1, d2 = int(m.group(2)), int(m.group(4))
        if m1 and m2:
            if m1 == m2:
                return "%s %d-%d 日" % (_MONTH_ZH[m1 - 1], d1, d2)
            return "%s %d 日-%s %d 日" % (_MONTH_ZH[m1 - 1], d1, _MONTH_ZH[m2 - 1], d2)
    m = re.search(r"([A-Za-z]{3,9})[.]?" + NS + r"*([0-9]{1,2})" + NS + r"*,", raw)
    if m:
        mm, dd = _month_en(m.group(1)), int(m.group(2))
        if mm:
            return "%s %d 日" % (_MONTH_ZH[mm - 1], dd)
    return ""



# ---------------------------------------------------------------- 源 1：Fed FOMC（HTML）

def parse_fed_calendar(html: str) -> list[dict]:
    """解析 Fed FOMC 日历页 → 事件列表（每条 = 一次会议的**决议日**）。

    ⚠️ 年份从 `<h4>` 的**文本**解析（实测 h4 顺序：2026, 2025, 2024, 2023, 2022, 2021, **2027**）。
    实测锚点：`fomc-meeting__month` = 月份名；`fomc-meeting__date` = `27-28` / `17-18*`（`*` = 含 SEP）。
    决议日在**第二天**（两日会议），单日会议取该日。
    """
    out: list[dict] = []
    if not html:
        return out
    # 按 h4 切块 —— 年份取标题文本，不取顺序
    blocks = re.split(r"<h4[^>]*>", html)[1:]
    for blk in blocks:
        head = blk.split("</h4>", 1)[0]
        ym = re.search(r"(\d{4})\s+FOMC\s+Meetings", head, re.I)
        if not ym:
            continue
        year = int(ym.group(1))
        body = blk
        # 行内顺序固定：月份在前、日期紧随其后（实测）
        for mon, date_txt in re.findall(
                r"fomc-meeting__month[^>]*>\s*(?:<strong>)?\s*([A-Za-z]+(?:\s*/\s*[A-Za-z]+)?)"
                r".*?fomc-meeting__date[^>]*>(.*?)</div>", body, re.S):
            # ⚠️ 跨月会议实测写 `Jan/Feb`、`Oct/Nov`、`Apr/May`（2023 有两场、2024 一场）：
            #    必须取**后一个**月份作为决议所在月，否则整行被跳过（初版漏了 3 场会议）。
            parts = [p.strip() for p in mon.split("/") if p.strip()]
            month = _month_num(parts[-1]) if parts else None
            month_first = _month_num(parts[0]) if parts else None
            raw = re.sub(r"<[^>]+>", "", date_txt).strip()
            days = re.findall(r"\d{1,2}", raw)
            if not month or not days:
                continue
            sep = "*" in raw
            dec_day = int(days[-1])
            notes = []
            if len(days) >= 2:
                if month_first and month_first != month:
                    notes.append("两日会议（%s %s - %s %s）的决议日"
                                 % (_MONTH_ABBR[month_first - 1], days[0], _MONTH_ABBR[month - 1], days[-1]))
                else:
                    notes.append("两日会议（%d 月 %s）的决议日" % (month, "-".join(days)))
            else:
                notes.append("单日会议")
            if sep:
                notes.append("含 SEP 经济预测")
            # ⚠️ 决议日可能跨月（如 4 月 30 日 - 5 月 1 日）：Fed 页只给月内日期，实测范围内无跨月
            try:
                date = datetime(year, month, dec_day).strftime("%Y-%m-%d")
            except ValueError:      # pragma: no cover - 防御：脏数据不让整源崩
                log.warning("[econ_calendar] Fed 日期非法，跳过: %s %s", mon, raw)
                continue
            d1 = int(days[0])
            if len(days) >= 2:
                if month_first and month_first != month:
                    span = "%s %d-%s %d" % (_MONTH_ABBR[month_first - 1], d1,
                                            _MONTH_ABBR[month - 1], dec_day)
                else:
                    span = "%s %d-%d" % (_MONTH_ABBR[month - 1], d1, dec_day)
            else:
                span = "%s %d" % (_MONTH_ABBR[month - 1], dec_day)
            out.append({
                "date": date,
                "kind": "FOMC",
                "agency": "Fed",
                "title": "FOMC Meeting - %s, %d" % (span, year),
                "source": "fed",
                "time_et": None,          # Fed 页无时刻（plan §4.1）
                "status": "ok",
                "note": "；".join(notes),
            })
    return out


# ---------------------------------------------------------------- 源 2：镜像 .ics

def _ical_prop(block: str, name: str) -> str | None:
    """取 iCal 属性值，**容忍 `NAME;PARAM=x:` 形式**（镜像大量使用 `SUMMARY;LANGUAGE=en:`）。"""
    m = re.search(r"^%s(?:;[^:\n]*)?:(.*)$" % re.escape(name), block, re.M)
    return m.group(1).strip() if m else None


def _ical_unfold(text: str) -> str:
    """展开 RFC 5545 折行：续行以空格/制表开头。"""
    return re.sub(r"\n[ \t]", "", text.replace("\r\n", "\n").replace("\r", "\n"))


def parse_ics(text: str) -> list[dict]:
    """解析第三方镜像 .ics → 事件列表（已过滤 CANCELLED、丢弃 FOMC 家族，见模块 docstring）。"""
    out: list[dict] = []
    if not text:
        return out
    unfolded = _ical_unfold(text)
    for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", unfolded, re.S):
        summary = clean_summary(_ical_prop(block, "SUMMARY") or "")
        if not summary:
            continue
        status_raw = (_ical_prop(block, "STATUS") or "").upper()
        # 过滤取消：STATUS 为主，标题后缀为辅（实测 75 条 CANCELLED 中 64 条带后缀）
        if status_raw == "CANCELLED" or re.search(r"\[CANCELLED\]\s*$", _ical_prop(block, "SUMMARY") or "", re.I):
            continue
        if _FOMC_FAMILY_RE.search(summary):
            continue
        dtstart = _ical_prop(block, "DTSTART") or ""
        date, time_et = _parse_dtstart(dtstart)
        if not date:
            continue
        event_no_time = re.search(r"VALUE=DATE", block) is not None and "T" not in dtstart
        kind, agency = normalize_kind(summary)
        notes = []
        if re.search(r"\(SEP\)", summary, re.I):
            notes.append("含 SEP 经济预测")
        if status_raw == "TENTATIVE":
            notes.append("暂定（源标记 TENTATIVE）")
        out.append({
            "date": date,
            "kind": kind,
            "agency": agency,
            "title": summary,
            "source": "mirror",
            "time_et": None if event_no_time else time_et,
            "status": "tentative" if status_raw == "TENTATIVE" else "ok",
            "note": "；".join(notes),
        })
    return out


def _parse_dtstart(value: str) -> tuple[str | None, str | None]:
    """`20260616` / `20260617T180000Z` → `(日期, 美东 HH:MM)`；无法解析返回 `(None, None)`。

    ⚠️ 时区必须显式转 **America/New_York**：实测 `12:30Z → 08:30 ET`、`18:00Z → 14:00 ET`、
    `13:15Z → 09:15 ET`，与 BLS / FOMC / 工业产出的**公开惯例时刻**逐一吻合（解析正确性的交叉验证）。
    """
    v = (value or "").strip()
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})(Z)?)?$", v)
    if not m:
        return None, None
    y, mo, d, hh, mm, _, z = m.groups()
    try:
        if hh is None:
            return "%s-%s-%s" % (y, mo, d), None
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mm),
                      0, tzinfo=timezone.utc if z else ET)
        dt_et = dt.astimezone(ET)
        return dt_et.strftime("%Y-%m-%d"), dt_et.strftime("%H:%M")
    except ValueError:      # pragma: no cover
        return None, None


# ---------------------------------------------------------------- 合流 / 去重

def merge_events(events: list[dict]) -> list[dict]:
    """按 `(date, kind)` 去重（plan §4.1）并按日期升序返回。

    实测同一天同一类型会重复出现两次（`US Employment Situation Release` 与
    `... Report — August 2026 Data`；`PPI Release — July 2026 Data` 与 `July 2026 PPI Release`）
    ⇒ 必须去重。**保留哪条**：来源优先 `fed > mirror`，其次标题信息量（含 Rate Decision / 年份 / 月份），
    再取较短者 —— 让标题稳定可预期，避免每次抓取换一条。
    """
    best: dict[tuple[str, str], dict] = {}
    for ev in events:
        key = (ev["date"], ev["kind"])
        cur = best.get(key)
        if cur is None or _rank(ev) > _rank(cur):
            best[key] = ev
    return sorted(best.values(), key=lambda e: (e["date"], e["kind"]))


def _rank(ev: dict) -> tuple[int, int, int]:
    src = 2 if ev.get("source") == "fed" else 1
    title = ev.get("title") or ""
    score = 0
    if re.search(r"Rate Decision|\bDecision\b", title, re.I):
        score += 2
    if re.search(r"\b(19|20)\d{2}\b", title):
        score += 1
    if re.search(r"Data|Estimate|Release", title, re.I):
        score += 1
    # 同分时**标题短的赢**（更干净）⇒ 用负数参与比较
    return (src, score, -len(title))


def collect_events(fed_html: str | None = None, ics_text: str | None = None,
                   timeout: int = 30) -> tuple[list[dict], list[str]]:
    """抓两个源并合流。返回 `(events, failed_sources)`。

    **容错纪律（plan §6.3）**：单个源失败 → 该源为空 + 记入 `failed`，**不抛异常、不清空既有数据**
    （调用方负责"失败不覆盖"）。
    """
    failed: list[str] = []
    events: list[dict] = []
    if fed_html is None:
        try:
            fed_html = fetch_text(FED_URL, timeout=timeout)
        except Exception as exc:            # noqa: BLE001 —— 单源失败不拖垮整轮
            log.warning("[econ_calendar] Fed 源失败：%s", exc)
            failed.append("fed")
            fed_html = ""
    if ics_text is None:
        try:
            ics_text = fetch_text(MIRROR_ICS_URL, timeout=timeout)
        except Exception as exc:            # noqa: BLE001
            log.warning("[econ_calendar] 镜像源失败：%s", exc)
            failed.append("mirror")
            ics_text = ""
    events += parse_fed_calendar(fed_html)
    events += parse_ics(ics_text)
    return merge_events(events), failed


def fetch_text(url: str, timeout: int = 30) -> str:
    """取文本（带 UA；非 2xx / 网络错误直接抛，由调用方按源记账）。"""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT,
                                               "Accept": "text/calendar,text/html,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError("HTTP %s: %s" % (resp.status, url))
        return resp.read().decode("utf-8", errors="replace")
