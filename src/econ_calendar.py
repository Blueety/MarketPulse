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
