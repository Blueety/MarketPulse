"""经济事件日历与时间线组装单测（P1/P2/P3，不联网）。

覆盖（每条对应 plan 里一个已实测的坑，防回归）：

- `normalize_kind`：多源写法归一化（§4.2），未命中归 `其他` 而不是静默丢弃
- `parse_ics`：CANCELLED 过滤（STATUS 与标题后缀两条路径）、TENTATIVE 保留、FOMC 家族丢弃、
  UTC→美东时刻、纯日期条目无时刻、转义逗号还原
- `parse_fed_calendar`：**年份从 h4 文本解析**（2027 排在最后）、跨月会议缩写月份（`Jan/Feb` + `31-1`）、
  决议日取第二天、`*` = 含 SEP
- `merge_events`：`(date, kind)` 去重 + 官方源优先
- `timeline`：**休市日"沿用值"不得算成 0.00%**（本轮修的真实缺陷）、`+h` 逐键判空、
  past/upcoming 窗口切分、叙事层挂载
"""

from __future__ import annotations

import pytest

from src import econ_calendar as ec
from src import storage as st
from src import timeline as tl

# ------------------------------------------------------------------ 夹具

ICS = """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:US Economic Calendar
X-WR-CALDESC:Release dates from bls.gov\\, bea.gov\\, federalreserve.gov\\, and census.gov
BEGIN:VEVENT
UID:a@x
DTSTART:20260911T123000Z
SUMMARY;LANGUAGE=en:CPI Release — August 2026 Data
STATUS:CONFIRMED
END:VEVENT
BEGIN:VEVENT
UID:b@x
DTSTART:20260904T123000Z
SUMMARY;LANGUAGE=en:US Employment Situation Release
END:VEVENT
BEGIN:VEVENT
UID:c@x
DTSTART:20260904T123000Z
SUMMARY;LANGUAGE=en:US Employment Situation Report — August 2026 Data
END:VEVENT
BEGIN:VEVENT
UID:d@x
DTSTART:20260916T180000Z
SUMMARY;LANGUAGE=en:FOMC Rate Decision (SEP)
END:VEVENT
BEGIN:VEVENT
UID:e@x
DTSTART;VALUE=DATE:20261015
SUMMARY;LANGUAGE=en:US Retail Sales (Advance) [CANCELLED]
STATUS:CANCELLED
END:VEVENT
BEGIN:VEVENT
UID:f@x
DTSTART;VALUE=DATE:20261120
SUMMARY;LANGUAGE=en:Advance Monthly Retail Trade Report
STATUS:CANCELLED
END:VEVENT
BEGIN:VEVENT
UID:g@x
DTSTART;VALUE=DATE:20261211
SUMMARY;LANGUAGE=en:GDP Third Estimate
STATUS:TENTATIVE
END:VEVENT
END:VCALENDAR
"""

FED_HTML = """
<h4><a id="1">2026 FOMC Meetings</a></h4>
<div class="row fomc-meeting">
  <div class="fomc-meeting__month col-xs-5"><strong>September</strong></div>
  <div class="fomc-meeting__date col-xs-4">15-16*</div>
</div>
<div class="row fomc-meeting">
  <div class="fomc-meeting__month col-xs-5"><strong>December</strong></div>
  <div class="fomc-meeting__date col-xs-4">8-9</div>
</div>
<h4><a id="2">2023 FOMC Meetings</a></h4>
<div class="row fomc-meeting">
  <div class="fomc-meeting__month col-xs-5"><strong>Jan/Feb</strong></div>
  <div class="fomc-meeting__date col-xs-4">31-1</div>
</div>
<h4><a id="3">2027 FOMC Meetings</a></h4>
<div class="row fomc-meeting">
  <div class="fomc-meeting__month col-xs-5"><strong>January</strong></div>
  <div class="fomc-meeting__date col-xs-4">26-27</div>
</div>
"""


# ------------------------------------------------------------------ 归一化

def test_normalize_kind_variants():
    """同一事件的多源写法必须归一到同一枚举（§4.2）。"""
    cases = [
        ("US Employment Situation Release", "非农", "BLS"),
        ("US Employment Situation Report — August 2026 Data", "非农", "BLS"),
        ("NFP Jobs Report — September 2026 Data", "非农", "BLS"),
        ("US CPI Release", "CPI", "BLS"),
        ("Consumer Price Index Release", "CPI", "BLS"),
        ("PPI Release — July 2026 Data", "PPI", "BLS"),
        ("July 2026 PPI Release", "PPI", "BLS"),
        ("GDP (Third Estimate), Industries, Corporate Profits,", "GDP", "BEA"),
        ("GDP Third Estimate — Q2 2026", "GDP", "BEA"),
        ("Personal Income and Outlays, April 2026", "PCE", "BEA"),
        ("Advance Monthly Retail Trade Report: August 2026 Data", "零售", "Census"),
        ("US Retail Sales (Advance) — July 2026 Data", "零售", "Census"),
        ("US Industrial Production and Capacity Utilization - G.1", "工业产出", "Fed"),
        ("FOMC Minutes Release", "FOMC", "Fed"),
    ]
    for title, kind, agency in cases:
        assert ec.normalize_kind(title) == (kind, agency), title


def test_normalize_kind_unknown_goes_to_other():
    """未命中 → `其他`（不静默丢弃：plan §11 明确要求记 warning 并归入 其他）。"""
    assert ec.normalize_kind("Some Unmapped Event 2026") == (ec.KIND_OTHER, None)
    assert ec.KIND_OTHER in ec.KINDS


def test_pce_not_matched_as_gdp():
    """顺序敏感：`Personal Income and Outlays` 只含 PCE 关键词，不能被 GDP 抢走。"""
    assert ec.normalize_kind("Personal Income and Outlays - August 2026 Data")[0] == "PCE"


# ------------------------------------------------------------------ ics 解析

def test_parse_ics_filters_cancelled_two_paths():
    """取消过滤：STATUS:CANCELLED（含标题无后缀的情形）与标题 `[CANCELLED]` 都要滤掉。"""
    events = ec.parse_ics(ICS)
    titles = [e["title"] for e in events]
    assert all("CANCELLED" not in t for t in titles)
    assert not any(e["date"] in ("2026-10-15", "2026-11-20") for e in events)


def test_parse_ics_drops_fomc_family():
    """FOMC 家族由官方源负责 ⇒ 镜像条目整族丢弃（否则同一次会议会出现 3~4 条）。"""
    assert not any(e["kind"] == "FOMC" for e in ec.parse_ics(ICS))


def test_parse_ics_datetime_to_et_and_date_only():
    """`12:30Z` → 08:30 美东；`VALUE=DATE` 条目不带时刻。"""
    events = {e["title"]: e for e in ec.parse_ics(ICS)}
    cpi = events["CPI Release — August 2026 Data"]
    assert (cpi["date"], cpi["time_et"]) == ("2026-09-11", "08:30")
    gdp = events["GDP Third Estimate"]
    assert (gdp["date"], gdp["time_et"]) == ("2026-12-11", None)
    assert gdp["status"] == "tentative"          # TENTATIVE 保留并标注


def test_parse_ics_unescapes_summary():
    """iCal 转义（`\\,`）必须还原，否则标题里会出现反斜杠。"""
    text = ICS.replace("CPI Release — August 2026 Data",
                       "Personal Income and Outlays\\, July 2026")
    got = [e["title"] for e in ec.parse_ics(text)]
    assert "Personal Income and Outlays, July 2026" in got


def test_parse_ics_empty_input():
    assert ec.parse_ics("") == []
    assert ec.parse_ics("BEGIN:VCALENDAR\nEND:VCALENDAR") == []


# ------------------------------------------------------------------ Fed 解析

def test_parse_fed_year_from_h4_text_not_order():
    """年份从 `<h4>` **文本**解析：2027 在页面上排在最后，取"最后一个区块"会拿错年份。"""
    events = ec.parse_fed_calendar(FED_HTML)
    years = sorted({e["date"][:4] for e in events})
    assert years == ["2023", "2026", "2027"]
    last_block = [e for e in events if e["date"].startswith("2027")]
    assert last_block and last_block[0]["date"] == "2027-01-27"


def test_parse_fed_cross_month_abbrev():
    """跨月会议写 `Jan/Feb` + `31-1` ⇒ 决议日 = 2 月 1 日（取后一个月份）。"""
    events = [e for e in ec.parse_fed_calendar(FED_HTML) if e["date"].startswith("2023")]
    assert [e["date"] for e in events] == ["2023-02-01"]
    assert "Jan 31-Feb 1" in events[0]["title"]


def test_parse_fed_decision_day_and_sep():
    """`15-16*` → 决议日 09-16（第二天）且标注含 SEP；无 `*` 的会议不标注。"""
    events = {e["date"]: e for e in ec.parse_fed_calendar(FED_HTML)}
    assert "含 SEP 经济预测" in events["2026-09-16"]["note"]
    assert "含 SEP 经济预测" not in events["2026-12-09"]["note"]
    assert events["2026-12-09"]["title"] == "FOMC Meeting - Dec 8-9, 2026"


# ------------------------------------------------------------------ 合流去重

def test_merge_events_dedupes_same_day_same_kind():
    """同一天两条非农（实测形态）→ 只留一条；fomc 家族不会与官方源冲突。"""
    merged = ec.merge_events(ec.parse_ics(ICS) + ec.parse_fed_calendar(FED_HTML))
    keys = [(e["date"], e["kind"]) for e in merged]
    assert len(keys) == len(set(keys))
    payrolls = [e for e in merged if e["date"] == "2026-09-04"]
    assert len(payrolls) == 1 and payrolls[0]["kind"] == "非农"


def test_merge_events_prefers_official_source():
    """同 `(date, kind)` 时官方源优先（fed > mirror）。"""
    evs = [{"date": "2026-09-16", "kind": "FOMC", "title": "mirror title", "source": "mirror"},
           {"date": "2026-09-16", "kind": "FOMC", "title": "FOMC Meeting - Sep 15-16, 2026", "source": "fed"}]
    assert ec.merge_events(evs)[0]["source"] == "fed"


# ------------------------------------------------------------------ 时间线组装

def _history_with_carried_rows() -> list[dict]:
    """构造含"休市日沿用值"的行情：周五收盘后周六/周日沿用，周一（美股休市）也沿用。"""
    return [
        {"date": "2026-09-03", "gspc": 100.0, "ixic": 200.0, "sh": 300.0, "vix": 10.0},
        {"date": "2026-09-04", "gspc": 110.0, "ixic": 220.0, "sh": 330.0, "vix": 11.0},
        {"date": "2026-09-05", "gspc": None, "ixic": None, "sh": 330.0, "vix": None},   # 周六
        {"date": "2026-09-06", "gspc": 110.0, "ixic": 220.0, "sh": 330.0, "vix": 11.0},  # 周日（沿用）
        {"date": "2026-09-07", "gspc": 110.0, "ixic": 220.0, "sh": 333.0, "vix": 11.0},  # 周一美股休市
        {"date": "2026-09-08", "gspc": 121.0, "ixic": 242.0, "sh": 336.0, "vix": 12.0},
    ]


def test_carried_rows_not_treated_as_zero_return():
    """**休市日沿用值不能算成 0.00%**（本轮修的真实缺陷）：09-04 的 +1 交易日 = 09-08 的真实涨幅。"""
    recs = _history_with_carried_rows()
    fwd = tl.forward_returns(recs, "2026-09-04")
    assert fwd["1"]["gspc"] == pytest.approx(10.0)   # 110 → 121（按行序会拿到 09-06 的 110 → 假的 0.0）
    # 美股 09-07 是劳动节（沿用行，跳过）⇒ +1 交易日 = 09-08
    assert fwd["1"]["ixic"] == pytest.approx((242.0 - 220.0) / 220.0 * 100.0)
    # A 股 09-05 是周六（沿用行，跳过）⇒ +1 交易日 = 09-07 的 333
    assert fwd["1"]["sh"] == pytest.approx((333.0 - 330.0) / 330.0 * 100.0)
    # 两个交易日后再看一次（显式给 horizons，HORIZONS 里没有 2）
    two = tl.forward_returns(recs, "2026-09-04", horizons=(2,))
    assert two["2"]["sh"] == pytest.approx((336.0 - 330.0) / 330.0 * 100.0)


def test_same_day_change_skips_carried_row():
    """周一（美股休市）的当日涨跌必须与**上一个真实交易日**比，而不是沿用行。"""
    recs = _history_with_carried_rows()
    d = tl.same_day_changes(recs, "2026-09-07")
    assert d is not None
    assert d["sh"] == (333.0 - 330.0) / 330.0 * 100.0
    assert d["gspc"] is None                 # 该标的当日无成交（沿用行不算交易日）


def test_forward_returns_per_key_when_window_not_complete():
    """`+h` 逐键判空：走不满的键为 None，走满的键有值（不得整行判空）。"""
    recs = _history_with_carried_rows()
    fwd = tl.forward_returns(recs, "2026-09-04")
    assert fwd["1"]["gspc"] is not None
    assert fwd["5"]["gspc"] is None          # 只有 3 个交易日后就没有数据了
    assert fwd["10"]["sh"] is None


def test_build_timeline_window_split_and_stats():
    """past/upcoming 切分 + stats 计数（TL-2 的口径）。"""
    events = [
        {"date": "2026-09-04", "kind": "非农", "title": "NFP", "source": "mirror",
         "agency": "BLS", "status": "ok", "note": "", "time_et": "08:30"},
        {"date": "2026-10-02", "kind": "非农", "title": "NFP next", "source": "mirror",
         "agency": "BLS", "status": "ok", "note": "", "time_et": "08:30"},
        {"date": "2025-01-01", "kind": "CPI", "title": "too old", "source": "mirror",
         "agency": "BLS", "status": "ok", "note": "", "time_et": "08:30"},
    ]
    p = tl.build_timeline(events, _history_with_carried_rows(), today="2026-09-18")
    assert [d["date"] for d in p["past"]] == ["2026-09-04"]
    assert [d["date"] for d in p["upcoming"]] == ["2026-10-02"]
    assert p["stats"]["past_events"] == 1 and p["stats"]["upcoming_events"] == 1
    assert p["past"][0]["market"]["gspc"] == (110.0 - 100.0) / 100.0 * 100.0
    assert p["upcoming"][0]["market"] is None       # 未来事件没有行情


def test_build_timeline_attaches_news_and_dedupes():
    """叙事层按 (date, kind) 挂回事件；库里两源同一事件 → 页面只出一条（TL-5）。"""
    events = [
        {"date": "2026-09-04", "kind": "非农", "title": "A", "source": "mirror",
         "agency": "BLS", "status": "ok", "note": "", "time_et": "08:30"},
        {"date": "2026-09-04", "kind": "非农", "title": "B", "source": "fed",
         "agency": "BLS", "status": "ok", "note": "", "time_et": None},
    ]
    news = {("2026-09-04", "非农"): {"count": 42, "title": "Jobs report", "link": "https://x"}}
    p = tl.build_timeline(events, _history_with_carried_rows(), news, today="2026-09-18")
    day = p["past"][0]
    assert len(day["events"]) == 1
    assert day["events"][0]["news_count"] == 42
    assert day["events"][0]["news_title"] == "Jobs report"


def test_parse_news_rss():
    xml = ("<rss><channel>"
           "<item><title>Headline &amp; more - CNBC</title><link>https://n/1</link></item>"
           "<item><title>Second</title><link>https://n/2</link></item>"
           "</channel></rss>")
    got = tl.parse_news_rss(xml)
    assert got == {"count": 2, "title": "Headline & more - CNBC", "link": "https://n/1"}
    assert tl.parse_news_rss("") == {"count": 0, "title": None, "link": None}


def test_news_url_uses_day_window():
    url = tl.news_url("CPI", "2026-09-11")
    assert "after%3A2026-09-11" in url and "before%3A2026-09-12" in url
    assert "CPI" in url or "cpi" in url


# ------------------------------------------------------------------ storage 往返

def test_storage_econ_events_roundtrip(tmp_db):
    """事件与叙事层的落盘/读取（含同键覆盖）。"""
    rows = [
        {"date": "2026-09-11", "kind": "CPI", "title": "t1", "agency": "BLS",
         "source": "mirror", "time_et": "08:30", "status": "ok", "note": ""},
        {"date": "2026-09-11", "kind": "CPI", "title": "t2", "agency": "BLS",
         "source": "mirror", "time_et": "08:30", "status": "ok", "note": "改期后"},
        {"date": "bad-date", "kind": "CPI", "title": "dropped", "source": "mirror"},
    ]
    assert st.upsert_econ_events(rows) == 2
    got = st.query_econ_events()
    assert len(got) == 1 and got[0]["title"] == "t2" and got[0]["note"] == "改期后"
    assert st.count_econ_events() == 1
    assert st.query_econ_events(start_date="2027-01-01") == []

    assert st.upsert_event_news([("2026-09-11", "CPI", 34, "标题", "https://x")]) == 1
    news = st.query_event_news()
    assert news[("2026-09-11", "CPI")]["count"] == 34
    assert st.query_event_news(dates=["2026-01-01"]) == {}
