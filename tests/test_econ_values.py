"""事件结果值层单测（2026-09-19，任务档 tasks/2026-09-19-timeline-event-values）。

**全程不联网**：值侧用固定 JSON fixture（形状抄自 2026-09-19 本机实测的真实响应）。

覆盖（每条都对应 plan 里一条已实测的坑 / 一条决策）：

- `et_parts`：UTC→美东（D4）含 **跨日反例** 与 **夏令时两侧** —— UTC 日期直接当匹配键会错一天
- `month_segments`：单请求 2000 上限 ⇒ 必须按月分段（D1）
- `headlines_for` / `kind_of_tv_row`：**精确匹配**，同族的 `PPI YoY` / `Non Farm Payrolls Annual Revision`
  等不得被收编；GDP 走**期次**路径（D2）
- `rank_row`：`forecast: 0` 是**真值**，不能与 `None` 混为一谈（实测 2026-07-15 PPI fc=0）
- `pick_for`：同日同 kind 多行择优（D3），用 **2025-12-16 真实双非农** 锁死
- `join_skeleton`：只 enrich 骨架已有行（D-5a）
- `collect_values`：失败降级（整源失败返回空 + `failed` 记 tradingview，D7）
- `update_econ_event_values`：**preserve 语义**（D5）—— 空值不得抹掉已落库的值；
  且**只 UPDATE 不 INSERT**（不建行 = 不做历史回填）
"""

from __future__ import annotations

from src import econ_values as ev
from src import storage as st

# ------------------------------------------------------------------ 夹具

#: 值侧固定 fixture（标题 / 字段形状照抄实测响应；`CPI` 与 `Non Farm Payrolls` **连 `unit` 键都没有**）
TV_ROWS: list[dict] = [
    {"title": "Fed Interest Rate Decision", "date": "2026-09-16T18:00:00.000Z",
     "actual": 4, "previous": 3.75, "forecast": 4, "unit": "%", "importance": 1,
     "source": "Federal Reserve"},
    {"title": "CPI", "date": "2026-09-11T12:30:00.000Z",
     "actual": 334.98, "previous": 333.92, "forecast": 334.85, "importance": 0,
     "source": "Bureau of Labor Statistics"},
    {"title": "Non Farm Payrolls", "date": "2026-09-04T12:30:00.000Z",
     "actual": 162, "previous": 21, "forecast": 56, "importance": 1,
     "source": "Bureau of Labor Statistics"},
    {"title": "PPI MoM", "date": "2026-09-10T12:30:00.000Z",
     "actual": 0.4, "previous": 0.1, "forecast": 0.4, "unit": "%", "importance": 1},
    # GDP 同期两条不同期次（Adv / 2nd Est）—— 期次必须靠骨架标题锁定，不能取第一条
    {"title": "GDP Growth Rate QoQ Adv", "date": "2026-07-30T12:30:00.000Z",
     "actual": 1.5, "previous": 2.1, "forecast": 2.1, "unit": "%", "importance": 1},
    {"title": "GDP Growth Rate QoQ 2nd Est", "date": "2026-08-26T12:30:00.000Z",
     "actual": 1.5, "previous": 2.1, "forecast": 1.5, "unit": "%", "importance": 1},
    # 未来事件：有预期无实际（D-2a 的「预期 X（待公布）」场景）
    {"title": "Core PCE Price Index MoM", "date": "2026-09-30T12:30:00.000Z",
     "actual": None, "previous": 0.2, "forecast": None, "unit": "%", "importance": 1},
    # 2025-12-16 真实双非农（政府停摆顺延两个数据期）：fc=None 的那条必须被淘汰（D3）
    {"title": "Non Farm Payrolls", "date": "2025-12-16T13:30:00.000Z",
     "actual": -105, "previous": None, "forecast": None, "importance": 1},
    {"title": "Non Farm Payrolls", "date": "2025-12-16T13:30:00.000Z",
     "actual": 64, "previous": None, "forecast": 50, "importance": 1},
    {"title": "PPI MoM", "date": "2026-01-14T13:30:00.000Z",
     "actual": 0.5, "previous": 0.2, "forecast": 0.3, "unit": "%", "importance": 1},
    # 以下 4 条**不得被收编**（同族兄弟 / 更宽的指标）
    {"title": "PPI YoY", "date": "2026-09-10T12:30:00.000Z",
     "actual": 2.6, "previous": 2.2, "forecast": 2.4, "unit": "%", "importance": -1},
    {"title": "Core PPI MoM", "date": "2026-09-10T12:30:00.000Z",
     "actual": 0.2, "previous": 0.1, "forecast": 0.2, "unit": "%", "importance": 0},
    {"title": "Non Farm Payrolls Annual Revision", "date": "2026-09-04T12:30:00.000Z",
     "actual": -911, "previous": None, "forecast": None, "importance": 1},
    {"title": "CPI s.a", "date": "2026-09-11T12:30:00.000Z",
     "actual": 335.1, "previous": 334.0, "forecast": 335.0, "importance": 0},
]


def _skel(date: str, kind: str, title: str = "", source: str = "mirror") -> dict:
    return {"date": date, "kind": kind, "title": title or ("%s release" % kind), "source": source}


SKELETONS: list[dict] = [
    _skel("2026-09-16", "FOMC", "FOMC Meeting - Sep 15-16, 2026", "fed"),
    _skel("2026-09-11", "CPI", "CPI Release - August 2026 Data"),
    _skel("2026-09-04", "非农", "US Employment Situation Report - August 2026 Data"),
    _skel("2026-09-10", "PPI", "September 2026 PPI Release"),
    _skel("2026-07-30", "GDP", "GDP Advance Estimate - Q2 2026"),
    _skel("2026-08-26", "GDP", "GDP Second Estimate - Q2 2026"),
    _skel("2026-09-30", "PCE", "Personal Income and Outlays - September 2026 Data"),
    _skel("2025-12-16", "非农", "US Employment Situation Report - November 2025 Data"),
    _skel("2026-03-05", "零售", "Advance Monthly Retail Trade Report"),   # 值侧没有 => 未命中
]


def _fake_fetch(rows):
    """构造可注入的 fetch（签名同 `ev.fetch_events`，**零联网**）。"""
    def _f(d1, d2, timeout=40):
        return list(rows), []
    return _f


# ------------------------------------------------------------------ ET 日期归一（D4）

def test_et_parts_converts_utc_to_eastern():
    assert ev.et_parts("2026-09-16T18:00:00.000Z") == ("2026-09-16", "14:00")
    assert ev.et_parts("2026-09-11T12:30:00.000Z") == ("2026-09-11", "08:30")


def test_et_parts_est_and_edt_both_0830():
    """夏令时两侧：EDT（7 月）与 EST（1 月）的 08:30 ET 分别对应 12:30Z / 13:30Z。"""
    assert ev.et_parts("2026-07-15T12:30:00.000Z") == ("2026-07-15", "08:30")
    assert ev.et_parts("2026-01-14T13:30:00.000Z") == ("2026-01-14", "08:30")


def test_et_parts_crosses_midnight_backwards():
    """⚠️ 跨日反例：UTC 日期直接当匹配键会**错一天**（D4 的规则依据）。"""
    assert ev.et_parts("2026-01-01T00:30:00.000Z") == ("2025-12-31", "19:30")


def test_et_parts_rejects_garbage():
    assert ev.et_parts("") == (None, None)
    assert ev.et_parts(None) == (None, None)
    assert ev.et_parts("not-a-date") == (None, None)


# ------------------------------------------------------------------ 分段抓取（D1）

def test_month_segments_splits_by_calendar_month():
    segs = ev.month_segments("2026-06-21", "2026-10-19")
    assert segs == [("2026-06-21", "2026-07-01"), ("2026-07-01", "2026-08-01"),
                    ("2026-08-01", "2026-09-01"), ("2026-09-01", "2026-10-01"),
                    ("2026-10-01", "2026-10-20")]


def test_month_segments_handles_december_rollover():
    segs = ev.month_segments("2026-12-05", "2027-01-03")
    assert segs == [("2026-12-05", "2027-01-01"), ("2027-01-01", "2027-01-04")]


# ------------------------------------------------------------------ 映射表（D2）

def test_headlines_for_plain_kinds():
    assert ev.headlines_for("FOMC") == ("Fed Interest Rate Decision",)
    assert ev.headlines_for("PPI") == ("PPI MoM",)
    assert ev.headlines_for("PCE") == ("Core PCE Price Index MoM", "PCE Price Index MoM")
    assert ev.headlines_for("不存在的类型") == ()


def test_headlines_for_gdp_picks_stage_from_skeleton_title():
    """GDP 必须按期次选（D2）：骨架标题里的期次决定取哪一行 TV。"""
    assert ev.headlines_for("GDP", "GDP Advance Estimate - Q2 2026") == ("GDP Growth Rate QoQ Adv",)
    assert ev.headlines_for("GDP", "GDP Second Estimate - Q2 2026") == ("GDP Growth Rate QoQ 2nd Est",)
    assert ev.headlines_for("GDP", "GDP Third Estimate - Q2 2026") == ("GDP Growth Rate QoQ Final",)


def test_headlines_for_gdp_falls_back_to_all_stages():
    cands = ev.headlines_for("GDP", "GDP Release - Q2 2026")
    assert "GDP Growth Rate QoQ Adv" in cands and "GDP Growth Rate QoQ Final" in cands


def test_kind_of_tv_row_is_exact_match_only():
    """精确匹配：同族兄弟与更宽指标一律不得被收编（否则页面会被小指标淹没）。"""
    assert ev.kind_of_tv_row({"title": "PPI MoM"}) == "PPI"
    assert ev.kind_of_tv_row({"title": "PPI YoY"}) is None
    assert ev.kind_of_tv_row({"title": "Core PPI MoM"}) is None
    assert ev.kind_of_tv_row({"title": "Non Farm Payrolls Annual Revision"}) is None
    assert ev.kind_of_tv_row({"title": "CPI s.a"}) is None
    assert ev.kind_of_tv_row({"title": "Retail Sales Ex Autos MoM"}) is None
    assert ev.kind_of_tv_row({"title": "GDP Growth Rate QoQ 2nd Est"}) == "GDP"
    assert ev.kind_of_tv_row({"title": "GDP Growth Rate QoQ"}) == "GDP"


# ------------------------------------------------------------------ 择优（D3）

def test_rank_row_treats_zero_forecast_as_present():
    """`forecast: 0` 是**真实预期值 0**（实测 2026-07-15 PPI MoM fc=0），不得当成"没有预期"。"""
    assert ev.rank_row({"forecast": 0, "actual": None, "previous": 1}) > \
           ev.rank_row({"forecast": None, "actual": 1, "previous": 1})


def test_pick_for_prefers_row_with_forecast_on_duplicate_date():
    """2025-12-16 真实双非农 ⇒ 取 `fc=50` 那条，不是 `fc=None` 那条（D3 / EV-5）。"""
    vmap = ev.build_value_map(TV_ROWS)
    cands = vmap[("2025-12-16", "非农")]
    assert len(cands) == 2
    picked, ambiguous = ev.pick_for(_skel("2025-12-16", "非农"), cands)
    assert picked["actual"] == 64 and picked["forecast"] == 50
    assert ambiguous is False          # 空值形态不同 => 择优规则能区分，不算歧义


def test_pick_for_flags_ambiguous_duplicates():
    """前两名空值形态完全相同 => 择优规则无法区分 => 必须记歧义（不静默取第一条）。"""
    a = {"title": "CPI", "date": "2026-09-11T12:30:00.000Z", "actual": 1, "forecast": 1, "previous": 1}
    b = {"title": "CPI", "date": "2026-09-11T11:00:00.000Z", "actual": 2, "forecast": 2, "previous": 2}
    _picked, ambiguous = ev.pick_for(_skel("2026-09-11", "CPI"), [a, b])
    assert ambiguous is True


def test_pick_for_prefers_primary_headline_over_fallback():
    """首选标题存在时**绝不能**落到备选（PCE：Core 与整体同日并存，两者 rank 键完全并列）。

    实测缺陷：只靠 `rank_row` 排序时并列项的先后由**上游返回顺序**决定 ⇒ 会取到 `PCE Price Index MoM`
    （非 Core）。
    """
    core = {"title": "Core PCE Price Index MoM", "date": "2026-09-30T12:30:00.000Z",
            "actual": None, "previous": 0.2, "forecast": None, "unit": "%", "importance": 1}
    broad = {"title": "PCE Price Index MoM", "date": "2026-09-30T12:30:00.000Z",
             "actual": None, "previous": 0.9, "forecast": None, "unit": "%", "importance": 0}
    # 两条顺序刻意把备选放前面：实现若依赖上游顺序就会取错
    picked, ambiguous = ev.pick_for(_skel("2026-09-30", "PCE"), [broad, core])
    assert picked["title"] == "Core PCE Price Index MoM"
    assert picked["previous"] == 0.2
    assert ambiguous is False


def test_pick_for_falls_back_when_primary_missing():
    """首选标题缺失时才启用备选（否则 PCE 在只有整体口径的日子会整条丢失）。"""
    broad = {"title": "PCE Price Index MoM", "date": "2026-09-30T12:30:00.000Z",
             "actual": None, "previous": 0.9, "forecast": None, "unit": "%", "importance": 0}
    picked, _ambiguous = ev.pick_for(_skel("2026-09-30", "PCE"), [broad])
    assert picked["title"] == "PCE Price Index MoM"


def test_pick_for_gdp_locks_stage_not_first_row():
    """GDP 期次锁定：骨架写 Second Estimate 就绝不能取到 Adv 那行。"""
    vmap = ev.build_value_map(TV_ROWS)
    adv, _ = ev.pick_for(_skel("2026-07-30", "GDP", "GDP Advance Estimate - Q2 2026"),
                         vmap[("2026-07-30", "GDP")])
    two, _ = ev.pick_for(_skel("2026-08-26", "GDP", "GDP Second Estimate - Q2 2026"),
                         vmap[("2026-08-26", "GDP")])
    assert adv["title"] == "GDP Growth Rate QoQ Adv"
    assert two["title"] == "GDP Growth Rate QoQ 2nd Est"


# ------------------------------------------------------------------ join（D-5a / unit 口径）

def test_value_entry_does_not_invent_unit_when_key_missing():
    """`unit` 键缺失（CPI / 非农）⇒ 必须原样 None，**不得**补 `%` / `点` / `千人`（D-1a 推论）。"""
    vmap = ev.build_value_map(TV_ROWS)
    cpi, _ = ev.pick_for(_skel("2026-09-11", "CPI"), vmap[("2026-09-11", "CPI")])
    entry = ev.value_entry(_skel("2026-09-11", "CPI"), cpi)
    assert entry["unit"] is None
    assert entry["actual"] == 334.98 and entry["forecast"] == 334.85 and entry["previous"] == 333.92
    fomc, _ = ev.pick_for(_skel("2026-09-16", "FOMC"), vmap[("2026-09-16", "FOMC")])
    assert ev.value_entry(_skel("2026-09-16", "FOMC"), fomc)["unit"] == "%"


def test_join_skeleton_only_enriches_existing_rows():
    """只 enrich 骨架已有行（D-5a）：值侧多余的行不得产生条目；骨架未命中的也不产生。"""
    values = ev.join_skeleton(SKELETONS, ev.build_value_map(TV_ROWS))
    keys = {(v["date"], v["kind"]) for v in values}
    assert ("2026-01-14", "PPI") not in keys          # 值侧有、骨架没有 => 不建条目
    assert ("2026-03-05", "零售") not in keys          # 骨架有、值侧没有 => 不产生条目
    assert keys == {("2026-09-16", "FOMC"), ("2026-09-11", "CPI"), ("2026-09-04", "非农"),
                    ("2026-09-10", "PPI"), ("2026-07-30", "GDP"), ("2026-08-26", "GDP"),
                    ("2026-09-30", "PCE"), ("2025-12-16", "非农")}


def test_join_skeleton_carries_source_and_title():
    values = {(v["date"], v["kind"]): v for v in ev.join_skeleton(SKELETONS, ev.build_value_map(TV_ROWS))}
    fomc = values[("2026-09-16", "FOMC")]
    assert fomc["value_source"] == "Federal Reserve"       # 源自带原始机构（plan §2.1）
    assert fomc["value_title"] == "Fed Interest Rate Decision"
    assert fomc["importance"] == 1                          # 只落库、不上色（D-3a）
    assert values[("2026-09-30", "PCE")]["actual"] is None  # 未来事件：有 previous 无 actual


# ------------------------------------------------------------------ 编排与失败降级（D7）

def test_collect_values_happy_path():
    """窗口 90/30（2026-06-21 ~ 2026-10-19）内的骨架行全命中；窗口外的 2025-12-16 被挡掉。"""
    values, failed = ev.collect_values(SKELETONS, today="2026-09-19",
                                       fetch=_fake_fetch(TV_ROWS))
    assert failed == []
    assert {(v["date"], v["kind"]) for v in values} == {
        ("2026-09-16", "FOMC"), ("2026-09-11", "CPI"), ("2026-09-04", "非农"),
        ("2026-09-10", "PPI"), ("2026-07-30", "GDP"), ("2026-08-26", "GDP"),
        ("2026-09-30", "PCE"),
    }
    fomc = [v for v in values if v["kind"] == "FOMC"][0]
    assert (fomc["actual"], fomc["previous"]) == (4.0, 3.75)


def test_collect_values_whole_source_failure_returns_empty():
    """整源失败 => 返回空 + `failed` 记 tradingview（调用方不写库 => 既有值保留，D7）。"""
    def _boom(d1, d2, timeout=40):
        return [], ["tradingview:2026-09"]
    values, failed = ev.collect_values(SKELETONS, today="2026-09-19", fetch=_boom)
    assert values == []
    assert failed and failed[0].startswith("tradingview")


def test_collect_values_window_excludes_out_of_range_skeleton():
    """窗口与页面默认窗口取齐（90/30）：窗口外的骨架行不参与 enrich。"""
    old = _skel("2025-12-16", "非农")            # 距 2026-09-19 已 277 天
    values, _failed = ev.collect_values([old], today="2026-09-19", fetch=_fake_fetch(TV_ROWS))
    assert values == []


# ------------------------------------------------------------------ 落库 preserve 语义（D5）

def _seed(tmp_db, rows):
    st.upsert_econ_events(rows)


def test_update_econ_event_values_writes_and_preserves(tmp_db):
    """preserve 语义：后一次抓取该列为空时**不得**抹掉已落库的值（与定稿保护同一纪律）。"""
    _seed(tmp_db, [{"date": "2026-09-11", "kind": "CPI", "title": "CPI Release", "agency": "BLS",
                    "source": "mirror", "time_et": "08:30", "status": "ok", "note": ""}])
    first = [{"date": "2026-09-11", "kind": "CPI", "actual": 334.98, "forecast": 334.85,
              "previous": 333.92, "unit": None, "importance": 0,
              "value_source": "Bureau of Labor Statistics", "value_title": "CPI"}]
    assert st.update_econ_event_values(first) == 1
    row = st.query_econ_events()[0]
    assert (row["actual"], row["forecast"], row["previous"]) == (334.98, 334.85, 333.92)

    # 第二次抓取：TV 对老事件的 actual 偶发为 null ⇒ 只有 previous 非空
    second = [{"date": "2026-09-11", "kind": "CPI", "actual": None, "forecast": None,
               "previous": 333.92, "unit": None, "importance": 0,
               "value_source": "Bureau of Labor Statistics", "value_title": "CPI"}]
    assert st.update_econ_event_values(second) == 1
    row = st.query_econ_events()[0]
    assert row["actual"] == 334.98 and row["forecast"] == 334.85   # 未被 null 抹掉


def test_update_econ_event_values_never_inserts_rows(tmp_db):
    """只 UPDATE 不 INSERT：值侧有、骨架没有的事件不得凭空进库（= 不做历史回填，D-5a）。"""
    _seed(tmp_db, [{"date": "2026-09-11", "kind": "CPI", "title": "CPI Release", "agency": "BLS",
                    "source": "mirror", "time_et": "08:30", "status": "ok", "note": ""}])
    assert st.update_econ_event_values([
        {"date": "2026-09-11", "kind": "CPI", "actual": 1.0, "importance": 0,
         "unit": None, "value_source": "x", "value_title": "CPI"},
        {"date": "2020-01-01", "kind": "CPI", "actual": 9.9, "importance": 0,
         "unit": None, "value_source": "x", "value_title": "CPI"},
    ]) == 1
    assert st.count_econ_events() == 1
    assert st.query_econ_events()[0]["actual"] == 1.0


def test_update_econ_event_values_skips_all_null(tmp_db):
    """全空值不写：否则只会把 `value_fetched_at` 刷成"有值层"，误导后续排查。"""
    _seed(tmp_db, [{"date": "2026-10-02", "kind": "非农", "title": "NFP", "agency": "BLS",
                    "source": "mirror", "time_et": "08:30", "status": "ok", "note": ""}])
    assert st.update_econ_event_values([{"date": "2026-10-02", "kind": "非农"}]) == 0
    assert st.query_econ_events()[0]["value_fetched_at"] is None


def test_update_econ_event_values_writes_all_source_rows_of_same_key(tmp_db):
    """`(date, kind)` 下有多源行时**全部**写入 —— 无论页面按哪种源优先去重，胜出那行都带值。"""
    _seed(tmp_db, [
        {"date": "2026-09-16", "kind": "FOMC", "title": "FOMC Meeting", "agency": "Fed",
         "source": "fed", "time_et": None, "status": "ok", "note": ""},
        {"date": "2026-09-16", "kind": "FOMC", "title": "FOMC Rate Decision", "agency": "Fed",
         "source": "mirror", "time_et": "14:00", "status": "ok", "note": ""},
    ])
    assert st.update_econ_event_values([
        {"date": "2026-09-16", "kind": "FOMC", "actual": 4.0, "forecast": 4.0, "previous": 3.75,
         "unit": "%", "importance": 1, "value_source": "Federal Reserve",
         "value_title": "Fed Interest Rate Decision"}]) == 1
    rows = st.query_econ_events()
    assert {r["source"] for r in rows} == {"fed", "mirror"}
    assert all(r["actual"] == 4.0 and r["unit"] == "%" for r in rows)


def test_econ_events_migration_adds_value_columns(tmp_db):
    """既有库迁移：`CREATE TABLE IF NOT EXISTS` 不加列 ⇒ 靠幂等 ALTER 补上 8 列（D6）。"""
    import sqlite3
    cols = {r[1] for r in sqlite3.connect(str(tmp_db.path)).execute("PRAGMA table_info(econ_events)")}
    assert {c for c, _ in st.ECON_VALUE_COLS} <= cols
    assert set(st._ECON_COLS) == cols          # 投影与建表同源（列清单分叉会让值"进了库读不出来"）
