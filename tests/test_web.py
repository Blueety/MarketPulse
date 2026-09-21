"""Web 看板测试：解析纯函数 + 4 端点（TestClient + monkeypatch 路径常量到 tmp_path）。

monkeypatch 落点严格打在使用方模块 web.app（与项目既有纪律一致：路径常量在导入时已
绑定，打在定义方 analyzer 不生效）。web 为独立模块，不触碰 src/* 与既有测试。
"""
import json
import logging
from pathlib import Path

import pytest
import web.app
from web.app import (
    _build_history_payload,
    _build_watchlist_payload,
    _compute_latest,
    _last_records,
    _load_alerts,
    _load_latest_context,
    _load_macro,
    _load_macro_stocks,
    _load_sector_heat,
    _load_watchlist,
    _normalize_series,
    _parse_alert_file,
    _resolve_symbols,
    _sector_payload,
)
from src import storage as st
from src.fetcher import SYMBOLS


@pytest.fixture(autouse=True)
def _reset_watch_cache(monkeypatch):
    """TTL 缓存为模块级状态，跨测试会泄漏；每个测试前清空以保证断言隔离。
    同时默认把自选股快照读取隔离为 None（本机可能存在真实 data/watchlist.json，
    文件优先逻辑不得劫持未打补丁的既有用例）；快照路径用例自行覆盖该补丁。"""
    web.app._watch_cache["ts"] = 0.0
    web.app._watch_cache["payload"] = None
    web.app._macro_cache["ts"] = 0.0
    web.app._macro_cache["payload"] = None
    web.app._econ_cache["ts"] = 0.0
    web.app._econ_cache["payload"] = None
    # 中国宏观（2026-09-14）：同样是模块级 TTL 状态，且多一份**跨组累积**的 raw 缓存
    web.app._cn_econ_cache["ts"].clear()
    web.app._cn_econ_cache["payload"].clear()
    web.app._cn_econ_raw.clear()
    web.app._cn_econ_raw_ts.clear()
    web.app._cn_quotes_cache["ts"] = 0.0
    web.app._cn_quotes_cache["payload"] = None
    monkeypatch.setattr(web.app, "load_watchlist_snapshot", lambda: None)
    yield

def make_alert(date: str) -> str:
    """生成指定日期的告警 md（frontmatter date 与文件名日期一致）。"""
    return (
        "---\n"
        f"type: close\n"
        f"date: {date}\n"
        "symbol: VIX\n"
        "level: WARN\n"
        "---\n\n"
        "## ⚠️ VIX（恐慌指数）告警\n\n"
        "- 级别：**WARN**\n"
        "- 当前值：26.10\n"
        "- 昨日收盘：21.40\n"
        "- 变化率：+22.00%（阈值 ±20.0%）\n"
        "- 市场状态：警惕\n"
        "- 建议：市场情绪警惕，波动率处于高位，警惕大幅波动。\n"
        f"- 相关报告：{date}.md\n"
    )


ALERT_MD = """---
type: close
date: 2026-08-30
symbol: VIX
level: WARN
---

## ⚠️ VIX（恐慌指数）告警

- 级别：**WARN**
- 当前值：26.10
- 昨日收盘：21.40
- 变化率：+22.00%（阈值 ±20.0%）
- 市场状态：警惕
- 建议：市场情绪警惕，波动率处于高位，警惕大幅波动。
- 相关报告：2026-08-30.md
"""


# ---- 历史解析纯函数 ----

def test_last_records_truncates(tmp_path, monkeypatch):
    hist = [{"date": f"2026-08-{i:02d}"} for i in range(1, 12)]  # 11 条
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    st.upsert_history_rows(st.records_to_rows(hist))
    last = _last_records(7)
    assert len(last) == 7
    assert last[-1]["date"] == "2026-08-11"


def test_last_records_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    assert _last_records(7) == []


def test_compute_latest_change_and_null_base(tmp_path, monkeypatch):
    # 仅在测试纯函数语义，不依赖文件
    hist = [
        {"date": "2026-08-29", "gspc": 100.0, "vix": None},
        {"date": "2026-08-30", "gspc": 105.0, "vix": 15.0},
    ]
    date, indices = _compute_latest(hist)
    assert date == "2026-08-30"
    gspc = next(i for i in indices if i["symbol"] == "GSPC")
    assert gspc["value"] == 105.0
    assert gspc["change_pct"] == pytest.approx(5.0)
    vix = next(i for i in indices if i["symbol"] == "VIX")
    # 前一条 vix=None → change_pct None
    assert vix["change_pct"] is None


def test_compute_latest_base_zero(tmp_path, monkeypatch):
    hist = [{"date": "d1", "gspc": 0.0}, {"date": "d2", "gspc": 10.0}]
    _, idx = _compute_latest(hist)
    g = next(i for i in idx if i["symbol"] == "GSPC")
    assert g["change_pct"] is None


def test_compute_latest_single_record(tmp_path, monkeypatch):
    hist = [{"date": "d1", "gspc": 100.0}]
    _, idx = _compute_latest(hist)
    g = next(i for i in idx if i["symbol"] == "GSPC")
    assert g["change_pct"] is None


def test_compute_latest_empty(tmp_path, monkeypatch):
    assert _compute_latest([]) is None

def test_compute_latest_backfills_sparse(tmp_path):
    """末行仅含部分市场（盘中 snapshot 合并）→ 缺失符号前向回填，涨跌幅置 None（R5）。"""
    hist = [
        {"date": "d1", "sh": 3000.0, "sz": 10000.0, "cyb": 2200.0,
         "gspc": 100.0, "ixic": 200.0, "vix": 15.0, "vxn": 18.0, "move": 100.0},
        {"date": "d2", "sh": 3030.0, "sz": 10100.0, "cyb": 2210.0},  # 仅 A 股已合并
    ]
    _, idx = _compute_latest(hist)
    by = {i["symbol"]: i for i in idx}
    # A 股：原始有值 → 计算涨跌幅
    assert by["SH"]["value"] == 3030.0
    assert by["SH"]["change_pct"] == pytest.approx(1.0)
    assert by["SH"]["source_date"] is None  # 末行本身有值，无回填
    # 美股/波动率：末行 None → 前向回填 d1 值，change_pct 强制 None
    assert by["GSPC"]["value"] == 100.0
    assert by["GSPC"]["change_pct"] is None
    assert by["GSPC"]["source_date"] == "d1"  # 回填来源日期
    assert by["MOVE"]["value"] == 100.0
    assert by["MOVE"]["change_pct"] is None
    assert by["MOVE"]["source_date"] == "d1"


def test_compute_latest_source_date_none_when_last_has_value(tmp_path):
    """末行所有符号均有值 → source_date 为 None，不标"回填"。"""
    hist = [
        {"date": "d1", "gspc": 100.0},
        {"date": "d2", "gspc": 105.0},
    ]
    _, idx = _compute_latest(hist)
    g = next(i for i in idx if i["symbol"] == "GSPC")
    assert g["source_date"] is None


def test_compute_latest_source_date_multi_day_chain(tmp_path):
    """多日 None 链 → source_date 取最近非空行日期（d1 而非更早的 d0）。"""
    hist = [
        {"date": "d0", "gspc": 90.0},
        {"date": "d1", "gspc": 100.0},  # 最近非空
        {"date": "d2", "gspc": None},   # 末行 None
        {"date": "d3", "gspc": None},   # 连续 None
    ]
    _, idx = _compute_latest(hist)
    g = next(i for i in idx if i["symbol"] == "GSPC")
    assert g["value"] == 100.0
    assert g["source_date"] == "d1"




# ---- 告警解析纯函数 ----

def test_parse_alert_file_full(tmp_path):
    p = tmp_path / "2026-08-30-close.md"
    p.write_text(ALERT_MD, encoding="utf-8")
    a = _parse_alert_file(p)
    assert a["date"] == "2026-08-30"
    assert a["type"] == "close"
    assert a["symbol"] == "VIX"
    assert a["level"] == "WARN"
    assert a["current"] == pytest.approx(26.10)
    assert a["last"] == pytest.approx(21.40)
    assert a["change_pct"] == pytest.approx(22.0)
    assert a["threshold"] == pytest.approx(20.0)
    assert a["state"] == "警惕"
    assert a["report"] == "2026-08-30.md"


def test_parse_alert_file_missing_change(tmp_path):
    p = tmp_path / "x.md"
    p.write_text(
        "---\ntype: close\ndate: 2026-08-30\nsymbol: VIX\nlevel: WARN\n---\n\n"
        "## ⚠️ VIX\n\n- 当前值：26.10\n",
        encoding="utf-8",
    )
    a = _parse_alert_file(p)
    assert a["current"] == pytest.approx(26.10)
    assert a["change_pct"] is None
    assert a["threshold"] is None


def test_parse_alert_file_no_frontmatter(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("not an alert", encoding="utf-8")
    assert _parse_alert_file(p) is None



def test_load_alerts_missing_dir(monkeypatch):
    monkeypatch.setattr(web.app, "ALERTS_DIR", Path("/nonexistent/alerts/dir"))
    assert _load_alerts(10) == []


def test_load_alerts_skips_unparseable(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "ALERTS_DIR", tmp_path)
    (tmp_path / "bad.md").write_text("not an alert", encoding="utf-8")
    (tmp_path / "2026-08-30-close.md").write_text(ALERT_MD, encoding="utf-8")
    assert len(_load_alerts(10)) == 1


def test_load_alerts_desc_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "ALERTS_DIR", tmp_path)
    for d in ["2026-08-25", "2026-08-26", "2026-08-27",
              "2026-08-28", "2026-08-29", "2026-08-30"]:
        (tmp_path / f"{d}-close.md").write_text(make_alert(d), encoding="utf-8")
    alerts = _load_alerts(10)
    assert len(alerts) == 6
    assert [a["date"] for a in alerts] == [
        "2026-08-30", "2026-08-29", "2026-08-28",
        "2026-08-27", "2026-08-26", "2026-08-25",
    ]


def _assert_sector_empty(sh: dict) -> None:
    """板块 payload 的**空值**断言（子集口径）。

    2026-09-14 起 `_sector_payload` 的返回值多了读取端生成的 `as_of` 键（陈旧数据回填用），
    不能再整体相等比对。**用子集断言，而不是删掉断言** —— 后者会把真红改成假绿。
    """
    assert sh["gainers"] == [] and sh["losers"] == [] and sh["as_of"] is None


def test_load_sector_heat_present(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    ctx = {
        "date": "2026-08-30",
        "indices": {},
        "sector_heat": {
            "gainers": [{"name": "水产品", "change": 3.79, "turnover": "13.7亿", "top_stock": "中水渔业"}],
            "losers": [],
        },
    }
    (tmp_path / "2026-08-30.json").write_text(json.dumps(ctx), encoding="utf-8")
    sh = _load_sector_heat()
    assert sh["gainers"][0]["name"] == "水产品"
    assert sh["losers"] == []


def test_load_sector_heat_missing_key(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    (tmp_path / "2026-08-30.json").write_text(
        json.dumps({"date": "x", "indices": {}}), encoding="utf-8"
    )
    _assert_sector_empty(_load_sector_heat())


def test_load_sector_heat_no_context_dir(monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", Path("/nonexistent/context/dir"))
    _assert_sector_empty(_load_sector_heat())


def test_load_latest_context_falls_back_from_empty_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    # 09-03 全源失败空壳：indices 全 null、sector_heat 空
    empty_shell = {
        "date": "2026-09-03",
        "indices": {k: None for k in ["gspc", "ixic", "sh", "sz", "cyb", "vix", "vxn", "move"]},
        "sector_heat": {"gainers": [], "losers": []},
    }
    (tmp_path / "2026-09-03.json").write_text(json.dumps(empty_shell), encoding="utf-8")
    # 09-02 真实有板块数据
    real = {
        "date": "2026-09-02",
        "indices": {"gspc": 5500.0},
        "sector_heat": {
            "gainers": [{"name": "军工", "change": -0.28, "turnover": "1.2亿", "top_stock": "中航飞机"}],
            "losers": [],
        },
    }
    (tmp_path / "2026-09-02.json").write_text(json.dumps(real), encoding="utf-8")
    assert _load_latest_context()["date"] == "2026-09-02"
    gainers = _load_sector_heat()["gainers"]
    assert [g["name"] for g in gainers] == ["军工"]


def test_load_latest_context_prefers_newest_with_sector(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    old = {
        "date": "2026-09-02",
        "indices": {},
        "sector_heat": {"gainers": [{"name": "军工", "change": 1.0}], "losers": []},
    }
    (tmp_path / "2026-09-02.json").write_text(json.dumps(old), encoding="utf-8")
    new = {
        "date": "2026-09-03",
        "indices": {},
        "sector_heat": {"gainers": [{"name": "消费", "change": 2.0}], "losers": []},
    }
    (tmp_path / "2026-09-03.json").write_text(json.dumps(new), encoding="utf-8")
    # 最新文件本身有板块数据 → 不误回退
    assert _load_latest_context()["date"] == "2026-09-03"
    assert _load_sector_heat()["gainers"][0]["name"] == "消费"


def test_load_latest_context_no_sector_anywhere(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    # 旧格式：全部无 sector_heat 键
    old = {"date": "2026-09-02", "indices": {"gspc": 5400.0}}
    (tmp_path / "2026-09-02.json").write_text(json.dumps(old), encoding="utf-8")
    new = {"date": "2026-09-03", "indices": {"gspc": 5500.0}}
    (tmp_path / "2026-09-03.json").write_text(json.dumps(new), encoding="utf-8")
    # 语义下限：返回最新的可解析 context（状态列不落空）
    assert _load_latest_context()["date"] == "2026-09-03"
    _assert_sector_empty(_load_sector_heat())


def test_load_latest_context_skips_corrupt_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    # 最新文件坏 JSON
    (tmp_path / "2026-09-03.json").write_text("{bad json", encoding="utf-8")
    real = {
        "date": "2026-09-02",
        "indices": {},
        "sector_heat": {"gainers": [{"name": "军工", "change": 1.0}], "losers": []},
    }
    (tmp_path / "2026-09-02.json").write_text(json.dumps(real), encoding="utf-8")
    assert _load_latest_context()["date"] == "2026-09-02"
    assert _load_sector_heat()["gainers"][0]["name"] == "军工"


def test_load_latest_context_all_corrupt(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    (tmp_path / "2026-09-02.json").write_text("{bad", encoding="utf-8")
    (tmp_path / "2026-09-03.json").write_text("not json", encoding="utf-8")
    assert _load_latest_context() is None
    _assert_sector_empty(_load_sector_heat())



# ---- 端点（TestClient，夹具打齐三路径常量）----

@pytest.fixture
def client(tmp_path, monkeypatch):
    hist = [
        {"date": "2026-08-03", "gspc": 100.0, "ixic": 200.0, "sh": 3000.0, "sz": 12000.0, "cyb": 3500.0, "vix": 17.0, "vxn": 23.0, "move": 70.0, "gld": 420.0, "btc": 76000.0},
        {"date": "2026-08-04", "gspc": 101.0, "ixic": 202.0, "sh": 3010.0, "sz": 12050.0, "cyb": 3520.0, "vix": 18.0, "vxn": 23.5, "move": 71.0, "gld": 421.0, "btc": 76200.0},
        {"date": "2026-08-05", "gspc": 102.0, "ixic": 205.0, "sh": 3020.0, "sz": 12100.0, "cyb": 3540.0, "vix": None, "vxn": 24.0, "move": 72.0, "gld": 423.0, "btc": 76300.0},
        {"date": "2026-08-06", "gspc": 103.0, "ixic": 208.0, "sh": 3030.0, "sz": 12150.0, "cyb": 3560.0, "vix": 19.0, "vxn": 24.5, "move": 73.0, "gld": 424.0, "btc": 76400.0},
        {"date": "2026-08-07", "gspc": 104.0, "ixic": 210.0, "sh": 3040.0, "sz": 12200.0, "cyb": 3580.0, "vix": 20.0, "vxn": 25.0, "move": 74.0, "gld": 425.0, "btc": 76500.0},
        {"date": "2026-08-10", "gspc": 105.0, "ixic": 212.0, "sh": 3050.0, "sz": 12250.0, "cyb": 3600.0, "vix": 21.0, "vxn": 25.5, "move": 75.0, "gld": 426.0, "btc": 76600.0},
        {"date": "2026-08-11", "gspc": 106.0, "ixic": 214.0, "sh": 3060.0, "sz": 12300.0, "cyb": 3620.0, "vix": 22.0, "vxn": 26.0, "move": 76.0, "gld": 427.0, "btc": 76700.0},
        {"date": "2026-08-12", "gspc": 107.0, "ixic": 216.0, "sh": 3070.0, "sz": 12350.0, "cyb": 3640.0, "vix": 23.0, "vxn": 26.5, "move": 77.0, "gld": 428.0, "btc": 76800.0},
    ]
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    st.upsert_history_rows(st.records_to_rows(hist))

    alerts_dir = tmp_path / "alerts"
    alerts_dir.mkdir()
    (alerts_dir / "2026-08-30-close.md").write_text(ALERT_MD, encoding="utf-8")
    monkeypatch.setattr(web.app, "ALERTS_DIR", alerts_dir)

    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    ctx = {
        "date": "2026-08-31",
        "indices": {"GSPC": {"value": 107.0, "change_pct": 0.0, "status": "连涨1日"}},
        "sector_heat": {
            "gainers": [{"name": "水产品", "change": 3.79, "turnover": "13.7亿", "top_stock": "中水渔业"}],
            "losers": [],
        },
    }
    (ctx_dir / "2026-08-31.json").write_text(json.dumps(ctx), encoding="utf-8")
    monkeypatch.setattr(web.app, "CONTEXT_DIR", ctx_dir)

    from fastapi.testclient import TestClient

    return TestClient(web.app.app)


def test_index_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_api_history(client):
    r = client.get("/api/history")
    assert r.status_code == 200
    data = r.json()
    # 默认值 30 天；夹具 8 条全为周内交易日，全量返回
    assert len(data["dates"]) == 8
    assert len(data["series"]) == 10
    vix = next(s for s in data["series"] if s["key"] == "vix")
    # 全量 8 条中 08-05 的 vix 为 null，index 2
    assert vix["values"][2] is None


def test_api_latest(client):
    r = client.get("/api/latest")
    assert r.status_code == 200
    data = r.json()
    assert len(data["indices"]) == 10
    gspc = next(i for i in data["indices"] if i["symbol"] == "GSPC")
    assert gspc["value"] == 107.0
    # 相邻 08-30(106)→08-31(107)：+0.943…
    assert gspc["change_pct"] == pytest.approx((107.0 - 106.0) / 106.0 * 100)
    # status 来自最新 context
    assert gspc["status"] == "连涨1日"
    assert data["sector_heat"]["gainers"][0]["name"] == "水产品"


def test_api_alerts(client):
    r = client.get("/api/alerts")
    assert r.status_code == 200
    data = r.json()
    assert len(data) <= 10
    assert data[0]["symbol"] == "VIX"


def test_endpoints_empty_data(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    monkeypatch.setattr(web.app, "ALERTS_DIR", tmp_path / "alerts")
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path / "context")
    from fastapi.testclient import TestClient

    c = TestClient(web.app.app)
    assert c.get("/").status_code == 200
    h = c.get("/api/history").json()
    assert h["dates"] == [] and len(h["series"]) == 10
    lat = c.get("/api/latest").json()
    assert lat["date"] is None
    assert lat["indices"] == []
    _assert_sector_empty(lat["sector_heat"])
    _assert_sector_empty(lat["us_sector_heat"])
    assert c.get("/api/alerts").json() == []


def _seed_history(tmp_path, monkeypatch, hist):
    """seed 测试历史进 tmp DB（三十一期：DB_PATH 调用时查找，单点 patch 生效）。"""
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    st.upsert_history_rows(st.records_to_rows(hist))


def test_build_history_payload_normalized_base100(tmp_path, monkeypatch):
    dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]
    hist = [{"date": d, "gspc": float(100 + i * 10 / 6)} for i, d in enumerate(dates)]
    _seed_history(tmp_path, monkeypatch, hist)
    gspc = next(s for s in _build_history_payload()["series"] if s["key"] == "gspc")
    assert gspc["values"][0] == 100.0
    assert gspc["values"][-1] == pytest.approx(110.0)
    assert gspc["change_7d"] == pytest.approx(10.0)


    hist = [
        {"date": "2026-08-03", "gspc": None},
        {"date": "2026-08-04", "gspc": 200.0},
        {"date": "2026-08-05", "gspc": None},
        {"date": "2026-08-06", "gspc": 220.0},
        {"date": "2026-08-07", "gspc": 210.0},
        {"date": "2026-08-10", "gspc": 230.0},
        {"date": "2026-08-11", "gspc": 240.0},
    ]
    _seed_history(tmp_path, monkeypatch, hist)
    gspc = next(s for s in _build_history_payload()["series"] if s["key"] == "gspc")
    assert gspc["values"][0] is None          # 前导 null 保留
    assert gspc["values"][1] == 100.0          # 基准 = 200
    assert gspc["values"][2] is None           # 中间 null 保留
    assert gspc["values"][-1] == pytest.approx(120.0)
    assert gspc["change_7d"] == pytest.approx(20.0)


    dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]
    hist = [{"date": d, "gspc": 0.0 if i == 0 else 5.0} for i, d in enumerate(dates)]
    _seed_history(tmp_path, monkeypatch, hist)
    gspc = next(s for s in _build_history_payload()["series"] if s["key"] == "gspc")
    assert gspc["values"] == [None] * 7        # 防除零，全 None 列表
    assert gspc["change_7d"] is None


def test_build_history_payload_single_value(tmp_path, monkeypatch):
    dates = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]
    hist = [{"date": d, "gspc": 100.0 if i == 3 else None} for i, d in enumerate(dates)]
    _seed_history(tmp_path, monkeypatch, hist)
    gspc = next(s for s in _build_history_payload()["series"] if s["key"] == "gspc")
    assert gspc["values"][3] == 100.0
    assert gspc["change_7d"] is None           # 仅 1 个非空值，无 7D 变化


def test_build_history_payload_change_7d_last_non_null(tmp_path, monkeypatch):
    hist = [
        {"date": "2026-08-03", "gspc": 100.0},
        {"date": "2026-08-04", "gspc": 110.0},
        {"date": "2026-08-05", "gspc": 120.0},
        {"date": "2026-08-06", "gspc": 130.0},
        {"date": "2026-08-07", "gspc": 140.0},
        {"date": "2026-08-10", "gspc": 150.0},
        {"date": "2026-08-11", "gspc": None},
    ]
    _seed_history(tmp_path, monkeypatch, hist)
    gspc = next(s for s in _build_history_payload()["series"] if s["key"] == "gspc")
    assert gspc["change_7d"] == pytest.approx(50.0)   # 末位 null，用最后非空 150 计
    assert gspc["values"][-1] is None


def test_api_history_series_shape(client):
    data = client.get("/api/history").json()
    for s in data["series"]:
        assert set(s.keys()) == {"key", "label", "values", "change_7d", "raw"}


# ---- /api/history 新参数：days / symbols / raw / 组合 / 容错 ----

def test_api_history_days_param(client):
    r = client.get("/api/history?days=3")
    assert r.status_code == 200
    data = r.json()
    assert len(data["dates"]) == 3
    assert data["dates"][-1] == "2026-08-12"  # 最近 3 条末位最新
    assert len(data["series"]) == 10


def test_api_history_days_caps(client):
    r = client.get("/api/history?days=90")
    assert r.status_code == 200
    data = r.json()
    # 夹具 8 条全为周内交易日，全量返回
    assert len(data["dates"]) == 8


def test_api_history_days_invalid(client):
    assert client.get("/api/history?days=0").status_code == 422
    # 三十一期 D9：上限放宽到 3650（永久保留）；91 / 365 / 3650 合法，3651 越界
    assert client.get("/api/history?days=91").status_code == 200
    assert client.get("/api/history?days=365").status_code == 200
    assert client.get("/api/history?days=3650").status_code == 200
    assert client.get("/api/history?days=3651").status_code == 422


def test_api_history_symbols_param(client):
    r = client.get("/api/history?symbols=VIX,GSPC")
    assert r.status_code == 200
    data = r.json()
    keys = [s["key"] for s in data["series"]]
    # 注册表序：GSPC 在 VIX 之前
    assert keys == ["gspc", "vix"]
    # 大小写混合
    r = client.get("/api/history?symbols=vix,gspc")
    assert [s["key"] for s in r.json()["series"]] == ["gspc", "vix"]
    # 未知符号静默忽略
    r = client.get("/api/history?symbols=VIX,FOO")
    assert [s["key"] for s in r.json()["series"]] == ["vix"]
    # 全未知 → series 为空，dates 仍返回
    r = client.get("/api/history?symbols=FOO,BAR")
    d = r.json()
    assert d["series"] == []
    assert len(d["dates"]) == 8
    # 空串 → 全部 10
    r = client.get("/api/history?symbols=")
    assert len(r.json()["series"]) == 10


def test_api_history_combined(client):
    r = client.get("/api/history?days=3&symbols=VIX,GSPC")
    assert r.status_code == 200
    data = r.json()
    assert len(data["dates"]) == 3
    assert [s["key"] for s in data["series"]] == ["gspc", "vix"]


def test_api_history_raw_values(client):
    data = client.get("/api/history").json()
    gld = next(s for s in data["series"] if s["key"] == "gld")
    # 08-03 gld 历史 420.0 → raw 已 ×10 = 4200.0；与 dates 等长
    assert gld["raw"][0] == 4200.0
    assert len(gld["raw"]) == len(data["dates"])


# ---- _resolve_symbols 纯函数 ----

def test_resolve_symbols():
    assert _resolve_symbols(None) == list(SYMBOLS.keys())
    assert _resolve_symbols("") == list(SYMBOLS.keys())
    assert _resolve_symbols("   ") == list(SYMBOLS.keys())
    assert _resolve_symbols("VIX,GSPC") == ["GSPC", "VIX"]    # 注册表序
    assert _resolve_symbols("vix,gspc") == ["GSPC", "VIX"]    # 大小写不敏感
    assert _resolve_symbols("GSPC,VIX,GSPC") == ["GSPC", "VIX"]  # 去重
    assert _resolve_symbols("FOO") == []                      # 未知 → 空
    assert _resolve_symbols("FOO,BAR") == []

# ---- 自选股 /api/watchlist：纯函数 + 端点（monkeypatch 打使用方 web.app）----

def test_build_watchlist_payload_contract():
    """表格行契约 + trend 契约（dates 并集升序 / 对齐含 null / 基准100 / key小写 / raw保留）。"""
    stocks_cfg = [
        {"symbol": "515300.SS", "label": "沪深300ETF"},
        {"symbol": "AAPL"},  # label 缺省回退 symbol
    ]
    series = {
        "515300.SS": [("2026-09-01", 4.00), ("2026-09-02", 4.10), ("2026-09-03", 4.123)],
        "AAPL": [("2026-09-01", 200.0), ("2026-09-02", 202.0), ("2026-09-03", 205.0)],
    }
    values = {"515300.SS": 4.123, "AAPL": 205.0}
    payload = _build_watchlist_payload(stocks_cfg, values, series)
    # 表格行契约
    rows = {r["symbol"]: r for r in payload["stocks"]}
    assert rows["515300.SS"]["label"] == "沪深300ETF"
    assert rows["515300.SS"]["value"] == 4.123
    assert rows["515300.SS"]["change_pct"] == round((4.123 - 4.10) / 4.10 * 100, 2)
    assert rows["AAPL"]["label"] == "AAPL"  # 缺省回退 symbol
    assert rows["AAPL"]["change_pct"] == round((205.0 - 202.0) / 202.0 * 100, 2)
    # trend 契约
    trend = payload["trend"]
    assert trend["dates"] == ["2026-09-01", "2026-09-02", "2026-09-03"]  # 升序并集
    by_key = {s["key"]: s for s in trend["series"]}
    assert "515300.ss" in by_key  # 小写 key
    s = by_key["515300.ss"]
    assert s["values"][0] == 100.0  # 归一化基准 100
    assert s["raw"] == [4.0, 4.10, 4.123]  # 对齐 dates
    assert s["change_7d"] == pytest.approx((4.123 - 4.0) / 4.0 * 100)
    # 所有 series 对齐到同一 dates 长度
    for ser in trend["series"]:
        assert len(ser["values"]) == len(trend["dates"])
        assert len(ser["raw"]) == len(trend["dates"])


def test_build_watchlist_change_pct_edge():
    """单点 / 空序列 / 昨收 None / 昨收 0 → change_pct 为 None（与日报同口径）。"""
    # 单点
    payload = _build_watchlist_payload([{"symbol": "X"}], {"X": 4.0}, {"X": [("d2", 4.0)]})
    assert payload["stocks"][0]["change_pct"] is None
    # 空序列（同时 value 缺失）
    payload = _build_watchlist_payload([{"symbol": "X"}], {}, {})
    assert payload["stocks"][0]["value"] is None
    assert payload["stocks"][0]["change_pct"] is None
    # 昨收 None
    payload = _build_watchlist_payload([{"symbol": "X"}], {"X": 4.0}, {"X": [("d1", None), ("d2", 4.0)]})
    assert payload["stocks"][0]["change_pct"] is None
    # 昨收 0
    payload = _build_watchlist_payload([{"symbol": "X"}], {"X": 4.0}, {"X": [("d1", 0.0), ("d2", 4.0)]})
    assert payload["stocks"][0]["change_pct"] is None


def test_build_watchlist_tail_30():
    """41 点输入 → trend 仅保留最近 30 点（dates 与 series 同裁）。"""
    pts = [(f"2026-08-{i:02d}", float(i)) for i in range(1, 42)]  # 41 点
    payload = _build_watchlist_payload([{"symbol": "X"}], {"X": 41.0}, {"X": pts})
    assert len(payload["trend"]["dates"]) == 30
    assert len(payload["trend"]["series"][0]["values"]) == 30
    assert payload["trend"]["dates"][0] == "2026-08-12"  # 最近 30 的起点


def test_load_watchlist_empty_config(monkeypatch):
    """config watchlist.stocks 为空 → 返回双空结构（F4 前端据此隐藏）。"""
    monkeypatch.setattr(web.app, "load_config", lambda: {"watchlist": {"stocks": []}})
    out = _load_watchlist()
    assert out == {"hidden": True, "stocks": [], "trend": {"dates": [], "series": []}}


def test_load_watchlist_partial_failure(monkeypatch):
    """失败行 value/change_pct 为 None、成功行正常；历史 series 仍入图（NF3）。"""

    stocks = [{"symbol": "OK", "label": "好"}, {"symbol": "BAD", "label": "坏"}]
    values = {"OK": 10.0}
    series = {"OK": [("d1", 9.0), ("d2", 10.0)], "BAD": [("d1", 5.0), ("d2", 6.0)]}
    errors = {"BAD": "获取失败"}
    monkeypatch.setattr(web.app, "load_config", lambda: {"watchlist": {"stocks": stocks}})
    monkeypatch.setattr(web.app, "fetch_watchlist", lambda s: (values, series, errors))
    out = _load_watchlist()
    rows = {r["symbol"]: r for r in out["stocks"]}
    assert rows["OK"]["value"] == 10.0
    assert rows["OK"]["change_pct"] == round((10.0 - 9.0) / 9.0 * 100, 2)
    assert rows["BAD"]["value"] is None
    assert rows["BAD"]["change_pct"] is None
    by_key = {s["key"]: s for s in out["trend"]["series"]}
    assert "ok" in by_key and "bad" in by_key  # 两标的均入图
    assert out["hidden"] is False


def test_load_watchlist_fetch_raises(monkeypatch):
    """fetch_watchlist 抛异常 → _load_watchlist 不抛、返回空结构（NF3，不 500）。"""
    def boom(stocks):
        raise RuntimeError("network down")
    monkeypatch.setattr(web.app, "fetch_watchlist", boom)
    monkeypatch.setattr(web.app, "load_config",
                        lambda: {"watchlist": {"stocks": [{"symbol": "X"}]}})
    out = _load_watchlist()
    assert out["hidden"] is False
    assert out["stocks"] == []
    assert out["trend"] == {"dates": [], "series": []}


def test_load_watchlist_file_hit_no_network(monkeypatch):
    """快照命中（标的与配置一致）→ 数据来自文件且零联网：fetch_watchlist 被调用即 fail。"""
    snap = {"saved_at": "2026-09-12T10:30+08:00",
            "stocks": [{"symbol": "X", "label": "测试"}],
            "values": {"X": 4.01},
            "series": {"X": [["d1", 3.9], ["d2", 4.01]]}}   # JSON 往返后 list-of-list
    monkeypatch.setattr(web.app, "load_watchlist_snapshot", lambda: snap)
    monkeypatch.setattr(web.app, "load_config",
                        lambda: {"watchlist": {"stocks": [{"symbol": "X", "label": "测试"}]}})

    def boom(stocks):
        raise AssertionError("快照命中时不得联网取数")

    monkeypatch.setattr(web.app, "fetch_watchlist", boom)
    out = _load_watchlist()
    assert out["hidden"] is False
    assert out["stocks"][0]["symbol"] == "X"
    assert out["stocks"][0]["value"] == 4.01
    assert out["as_of"] == "2026-09-12T10:30+08:00"
    assert out["trend"]["dates"][-1] == "d2"   # list 兼容解包与索引访问


def test_load_watchlist_config_mismatch_falls_back(monkeypatch):
    """快照标的 ≠ 配置标的 → 回退实时取数（防改配置后展示旧标的），无 as_of。"""
    snap = {"saved_at": "2026-09-12T10:30+08:00",
            "stocks": [{"symbol": "OLD"}], "values": {"OLD": 1.0},
            "series": {"OLD": [["d1", 1.0]]}}
    monkeypatch.setattr(web.app, "load_watchlist_snapshot", lambda: snap)
    monkeypatch.setattr(web.app, "load_config",
                        lambda: {"watchlist": {"stocks": [{"symbol": "NEW"}]}})
    values, series, errors = {"NEW": 9.0}, {"NEW": [("d1", 8.0), ("d2", 9.0)]}, []
    monkeypatch.setattr(web.app, "fetch_watchlist", lambda s: (values, series, errors))
    out = _load_watchlist()
    assert out["hidden"] is False
    assert out["stocks"][0]["symbol"] == "NEW"
    assert out["stocks"][0]["value"] == 9.0
    assert "as_of" not in out


def test_load_watchlist_no_snapshot_falls_back(monkeypatch):
    """无快照文件 → 回退实时取数（既有实时路径回归锚；文件优先逻辑不得越界）。"""
    monkeypatch.setattr(web.app, "load_watchlist_snapshot", lambda: None)
    monkeypatch.setattr(web.app, "load_config",
                        lambda: {"watchlist": {"stocks": [{"symbol": "X"}]}})
    values, series, errors = {"X": 4.0}, {"X": [("d1", None), ("d2", 4.0)]}, []
    monkeypatch.setattr(web.app, "fetch_watchlist", lambda s: (values, series, errors))
    out = _load_watchlist()
    assert out["hidden"] is False
    assert out["stocks"][0]["value"] == 4.0
    assert "as_of" not in out


def test_api_watchlist_endpoint(client, monkeypatch):
    """端点返回 200 + JSON 形状（stocks / trend.dates / trend.series）。"""
    payload = {
        "stocks": [{"symbol": "X", "label": "X", "value": 1.0, "change_pct": 2.0}],
        "trend": {"dates": ["d1"],
                  "series": [{"key": "x", "label": "X", "values": [100.0],
                              "change_7d": 0.0, "raw": [1.0]}]},
    }
    monkeypatch.setattr(web.app, "_load_watchlist", lambda: payload)
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    data = r.json()
    assert data["stocks"][0]["symbol"] == "X"
    assert data["trend"]["dates"] == ["d1"]
    assert data["trend"]["series"][0]["key"] == "x"


def test_api_watchlist_no_config_hidden_semantics(client, monkeypatch):
    """默认配置 stocks 恒空 → 端点返回 stocks=[]（F4 前端据此隐藏）。"""
    monkeypatch.setattr(web.app, "load_config", lambda: {"watchlist": {"stocks": []}})
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json()["stocks"] == []
    assert r.json()["hidden"] is True


def test_load_watchlist_config_raises(monkeypatch):
    """load_config 抛异常 → 视为无配置：hidden=true + 双空结构（不误报有配置）。"""
    def boom():
        raise RuntimeError("config unreadable")
    monkeypatch.setattr(web.app, "load_config", boom)
    out = _load_watchlist()
    assert out["hidden"] is True
    assert out == {"hidden": True, "stocks": [], "trend": {"dates": [], "series": []}}


def test_api_watchlist_fetch_raises_endpoint(client, monkeypatch):
    """有配置 + fetch_watchlist 抛 → 端点 200 + hidden=false + 空 stocks（NF3：不 500、不隐藏）。"""
    monkeypatch.setattr(
        web.app, "load_config",
        lambda: {"watchlist": {"stocks": [{"symbol": "X", "label": "X"}]}},
    )
    def boom(stocks):
        raise RuntimeError("network down")
    monkeypatch.setattr(web.app, "fetch_watchlist", boom)
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    data = r.json()
    assert data["hidden"] is False
    assert data["stocks"] == []
    assert data["trend"] == {"dates": [], "series": []}


# ---- 板块热度双键（sector_heat / us_sector_heat）：纯函数 + 端点 ----

# ---- 逐键独立回看（2026-09-14 陈旧回填）：_sector_payload(key) 取代 (ctx, key) ----

def _write_ctx(dirpath, date: str, **sectors) -> None:
    """写一份 context 夹具：`_write_ctx(tmp, "2026-09-14", sector_heat={...})`。"""
    (dirpath / f"{date}.json").write_text(
        json.dumps({"date": date, "indices": {}, **sectors}), encoding="utf-8")


def test_sector_payload_independent_lookback(tmp_path, monkeypatch):
    """核心效果：两个键**各自**回看 —— 今天美股空、昨天有 → 美股回看到昨天，A股 用今天。"""
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    _write_ctx(tmp_path, "2026-09-13",
               sector_heat={"gainers": [{"name": "军工"}], "losers": []},
               us_sector_heat={"gainers": [{"name": "能源 (XLE)"}], "losers": []})
    _write_ctx(tmp_path, "2026-09-14",
               sector_heat={"gainers": [{"name": "消费"}], "losers": []},
               us_sector_heat={"gainers": [], "losers": []})      # 今天美股取数失败

    cn, us = _sector_payload("sector_heat"), _sector_payload("us_sector_heat")
    assert cn["gainers"][0]["name"] == "消费" and cn["as_of"] == "2026-09-14"
    assert us["gainers"][0]["name"] == "能源 (XLE)" and us["as_of"] == "2026-09-13"
    assert cn["as_of"] != us["as_of"]                              # ← 本任务要达成的效果


def test_sector_payload_lookback_limit(tmp_path, monkeypatch):
    """超过 SECTOR_LOOKBACK_MAX 仍无数据 → 空 + as_of None（宁可空白，不展示过旧快照）。"""
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    for i in range(1, web.app.SECTOR_LOOKBACK_MAX + 1):            # 最新的 5 份都没有板块数据
        _write_ctx(tmp_path, f"2026-09-{10 + i:02d}")
    _write_ctx(tmp_path, "2026-09-10",                             # 第 6 份有数据 → 超上限，不该取到
               sector_heat={"gainers": [{"name": "太旧"}], "losers": []})
    assert _sector_payload("sector_heat") == {"gainers": [], "losers": [], "as_of": None}


def test_sector_payload_skips_corrupt_newest(tmp_path, monkeypatch):
    """最新文件坏 JSON → 跳过它继续回看（复用 _read_context_file 容错，不另写解析）。"""
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    (tmp_path / "2026-09-14.json").write_text("{bad json", encoding="utf-8")
    _write_ctx(tmp_path, "2026-09-13",
               us_sector_heat={"gainers": [{"name": "能源 (XLE)"}], "losers": []})
    p = _sector_payload("us_sector_heat")
    assert p["gainers"][0]["name"] == "能源 (XLE)" and p["as_of"] == "2026-09-13"


def test_sector_payload_degrade_variants(tmp_path, monkeypatch):
    """容错：目录不存在 / 键缺失 / 键非 dict → 空 + as_of None（不抛）。"""
    monkeypatch.setattr(web.app, "CONTEXT_DIR", Path("/nonexistent/context/dir"))
    assert _sector_payload("sector_heat") == {"gainers": [], "losers": [], "as_of": None}

    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    _write_ctx(tmp_path, "2026-09-14")                             # 无板块键
    assert _sector_payload("sector_heat") == {"gainers": [], "losers": [], "as_of": None}
    (tmp_path / "2026-09-14.json").write_text(
        json.dumps({"date": "2026-09-14", "indices": {}, "sector_heat": "bad"}),
        encoding="utf-8")                                          # 键存在但不是 dict
    assert _sector_payload("sector_heat") == {"gainers": [], "losers": [], "as_of": None}


def test_sector_payload_gainers_empty_means_no_data(tmp_path, monkeypatch):
    """键在但 gainers 为空/None → 视为「该键当天无数据」→ 整键降级（不再单独保留 losers）。

    ⚠️ 语义变化点（2026-09-14）：回看的有效性判据是 `key.gainers`（与 `_load_latest_context`
    同口径），所以 gainers 为空时 losers 不再被单独保留。实测 `fetch_*_heat` 成功时两者必然
    同时非空（都出自同一批结果），该组合只会出现在手写/异常数据里。
    """
    monkeypatch.setattr(web.app, "CONTEXT_DIR", tmp_path)
    _write_ctx(tmp_path, "2026-09-14",
               us_sector_heat={"gainers": None, "losers": [{"name": "能源"}]})
    assert _sector_payload("us_sector_heat") == {"gainers": [], "losers": [], "as_of": None}


def test_api_latest_includes_us_sector_heat(tmp_path, monkeypatch):
    """同一 context 同源暴露 A 股与美股两个板块键（Step 1：context 已有键但端点未暴露）。"""
    hist = [{"date": "2026-09-10", "gspc": 100.0}, {"date": "2026-09-11", "gspc": 101.0}]
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    st.upsert_history_rows(st.records_to_rows(hist))
    monkeypatch.setattr(web.app, "ALERTS_DIR", tmp_path / "alerts")

    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    ctx = {
        "date": "2026-09-11",
        "indices": {},
        "sector_heat": {"gainers": [{"name": "军工", "change": 1.0}], "losers": []},
        "us_sector_heat": {
            "gainers": [
                {"name": "能源 (XLE)", "change": 1.11, "turnover": "$1.8B", "top_stock": "XLE"},
                {"name": "公用事业 (XLU)", "change": 0.86, "turnover": "$855.7M", "top_stock": "XLU"},
            ],
            "losers": [],
        },
    }
    (ctx_dir / "2026-09-11.json").write_text(json.dumps(ctx), encoding="utf-8")
    monkeypatch.setattr(web.app, "CONTEXT_DIR", ctx_dir)

    from fastapi.testclient import TestClient

    data = TestClient(web.app.app).get("/api/latest").json()
    assert data["sector_heat"]["gainers"][0]["name"] == "军工"
    assert [g["name"] for g in data["us_sector_heat"]["gainers"]] == ["能源 (XLE)", "公用事业 (XLU)"]


def test_api_latest_sector_as_of_independent(tmp_path, monkeypatch):
    """端点层：两个板块各自回看到**不同**日期 → 各自带 as_of（前端据此显示「数据截至」）。"""
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    st.upsert_history_rows(st.records_to_rows([{"date": "2026-09-14", "gspc": 100.0}]))
    monkeypatch.setattr(web.app, "ALERTS_DIR", tmp_path / "alerts")
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    _write_ctx(ctx_dir, "2026-09-13",                     # 美股只在这天成功
               us_sector_heat={"gainers": [{"name": "能源 (XLE)"}], "losers": []})
    _write_ctx(ctx_dir, "2026-09-14",                     # A股 今天成功、美股今天失败
               sector_heat={"gainers": [{"name": "军工"}], "losers": []})
    monkeypatch.setattr(web.app, "CONTEXT_DIR", ctx_dir)

    from fastapi.testclient import TestClient

    data = TestClient(web.app.app).get("/api/latest").json()
    assert data["sector_heat"]["as_of"] == "2026-09-14"
    assert data["us_sector_heat"]["as_of"] == "2026-09-13"
    assert data["us_sector_heat"]["gainers"] == [{"name": "能源 (XLE)"}]
    # as_of 只在响应里生成 → context 文件本身不被改写（不落盘）
    written = json.loads((ctx_dir / "2026-09-14.json").read_text(encoding="utf-8"))
    assert "as_of" not in written["sector_heat"]


def test_api_latest_us_sector_heat_degrades(tmp_path, monkeypatch):
    """context 无 us_sector_heat 键（旧格式）→ 该键降级双空，不影响 sector_heat。"""
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    st.upsert_history_rows(st.records_to_rows([{"date": "2026-09-10", "gspc": 100.0}]))
    monkeypatch.setattr(web.app, "ALERTS_DIR", tmp_path / "alerts")
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    (ctx_dir / "2026-09-10.json").write_text(
        json.dumps({"date": "2026-09-10", "indices": {},
                    "sector_heat": {"gainers": [{"name": "军工"}], "losers": []}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(web.app, "CONTEXT_DIR", ctx_dir)

    from fastapi.testclient import TestClient

    data = TestClient(web.app.app).get("/api/latest").json()
    assert data["sector_heat"]["gainers"] == [{"name": "军工"}]
    _assert_sector_empty(data["us_sector_heat"])


# ---- /api/macro：配置三级回退 + 容错 ----

def test_load_macro_stocks_builtin_default(monkeypatch):
    """env 未设 / config 无 macro.stocks → 内置 4 标的（三十四期 +黄金 COMEX）。"""
    monkeypatch.delenv("MACRO_STOCKS", raising=False)
    monkeypatch.setattr(web.app, "load_config", lambda: {})
    assert [s["symbol"] for s in _load_macro_stocks()] == ["DX-Y.NYB", "^TNX", "CL=F", "GC=F"]


def test_load_macro_stocks_env_precedence(monkeypatch):
    """env MACRO_STOCKS 优先于 config.json。"""
    monkeypatch.setenv("MACRO_STOCKS", json.dumps([{"symbol": "GC=F", "label": "黄金期货"}]))
    monkeypatch.setattr(web.app, "load_config", lambda: {"macro": {"stocks": [{"symbol": "ZZZ"}]}})
    assert _load_macro_stocks() == [{"symbol": "GC=F", "label": "黄金期货"}]


def test_load_macro_stocks_env_invalid_falls_back(monkeypatch):
    """env 非法 JSON / 非列表 / 全无效项 → 内置默认（不抛、不空）。"""
    monkeypatch.setattr(web.app, "load_config", lambda: {})
    monkeypatch.setenv("MACRO_STOCKS", "{bad json")
    assert len(_load_macro_stocks()) == 4
    monkeypatch.setenv("MACRO_STOCKS", json.dumps("not-a-list"))
    assert len(_load_macro_stocks()) == 4
    monkeypatch.setenv("MACRO_STOCKS", json.dumps([{"label": "无symbol"}]))
    assert len(_load_macro_stocks()) == 4


def test_load_macro_stocks_config_raises(monkeypatch):
    """load_config 抛异常 → 内置默认。"""
    monkeypatch.delenv("MACRO_STOCKS", raising=False)

    def boom():
        raise RuntimeError("config unreadable")
    monkeypatch.setattr(web.app, "load_config", boom)
    assert len(_load_macro_stocks()) == 4


def test_load_macro_fetch_raises(monkeypatch):
    """fetch_watchlist 抛 → 空结构降级（不 500）。"""
    def boom(*a, **k):                      # 宏观链路会传 range_，桩必须接得住
        raise RuntimeError("network down")
    monkeypatch.setattr(web.app, "fetch_watchlist", boom)
    assert _load_macro() == {"stocks": [], "trend": {"dates": [], "series": []}}


def test_api_macro_endpoint(monkeypatch):
    """端点 200 + 形状（stocks[].symbol / value / change_pct）。"""
    payload = {
        "stocks": [{"symbol": "DX-Y.NYB", "label": "美元指数", "value": 97.5, "change_pct": -0.21}],
        "trend": {"dates": ["d1"], "series": []},
    }
    monkeypatch.setattr(web.app, "_load_macro", lambda: payload)
    from fastapi.testclient import TestClient

    r = TestClient(web.app.app).get("/api/macro")
    assert r.status_code == 200
    assert r.json()["stocks"][0]["symbol"] == "DX-Y.NYB"


def test_api_macro_endpoint_degrades(monkeypatch):
    """取数失败 → 200 + 空 stocks（前端据此显示「数据未接入」占位）。"""
    monkeypatch.setattr(web.app, "_load_macro", lambda: {"stocks": [], "trend": {"dates": [], "series": []}})
    from fastapi.testclient import TestClient

    r = TestClient(web.app.app).get("/api/macro")
    assert r.status_code == 200
    assert r.json()["stocks"] == []


# ---- 风险偏好（三十二期：/api/latest 新增 risk_appetite，纯函数合成零新增取数）----

def _ra_indices(vix=None, move=None):
    return [{"symbol": "VIX", "value": vix}, {"symbol": "MOVE", "value": move}]


def _ra_records(closes):
    """vix 收盘序列 → 宽 records（None 语义保留）。"""
    return [{"date": f"2026-09-{i:02d}", "vix": v} for i, v in enumerate(closes, start=1)]


def _ra_clean_env(monkeypatch):
    for k in ("STATUS_THRESHOLD_VIX_CALM", "STATUS_THRESHOLD_VIX_PANIC",
              "STATUS_THRESHOLD_MOVE_CALM", "STATUS_THRESHOLD_MOVE_PANIC"):
        monkeypatch.delenv(k, raising=False)


def test_risk_appetite_high_when_vix_calm_and_falling(monkeypatch):
    """VIX 平静(+1) + 5 日回落超 5%(+1)、MOVE 平静(0) → score 2 → high。"""
    _ra_clean_env(monkeypatch)
    records = _ra_records([15.5, 15.2, 15.0, 14.8, 14.5, 14.2])   # (14.2-15.5)/15.5 ≈ -8.4%
    out = web.app._compute_risk_appetite(_ra_indices(14.2, 98.1), records)
    assert out["level"] == "high" and out["score"] == 2
    by_name = {f["name"]: f for f in out["factors"]}
    assert by_name["VIX"] == {"name": "VIX", "value": 14.2, "state": "平静", "impact": 1}
    assert by_name["MOVE"]["state"] == "平静" and by_name["MOVE"]["impact"] == 0
    assert by_name["VIX 5日"]["change_pct"] == pytest.approx(-8.4, abs=0.1)
    assert by_name["VIX 5日"]["impact"] == 1


def test_risk_appetite_low_when_panic(monkeypatch):
    """VIX 恐慌(-1) + MOVE 恐慌(-1) + 5 日持平(0) → score -2 → low。"""
    _ra_clean_env(monkeypatch)
    out = web.app._compute_risk_appetite(_ra_indices(32.0, 140.0), _ra_records([20.0] * 6))
    assert out["level"] == "low" and out["score"] == -2


def test_risk_appetite_neutral_when_mixed(monkeypatch):
    """VIX 平静(+1) 与 MOVE 恐慌(-1) 对冲、5 日温和(+0.9%) → score 0 → neutral。"""
    _ra_clean_env(monkeypatch)
    records = _ra_records([15.0, 15.05, 15.1, 15.12, 15.14, 15.13])   # ≈ +0.9%
    out = web.app._compute_risk_appetite(_ra_indices(15.0, 140.0), records)
    assert out["level"] == "neutral" and out["score"] == 0


def test_risk_appetite_vix_missing_level_null(monkeypatch):
    """VIX 值缺失（取数失败/前向回填不可得）→ level=None，factors 尽列可得项。"""
    _ra_clean_env(monkeypatch)
    out = web.app._compute_risk_appetite(_ra_indices(None, 98.1), _ra_records([20.0] * 6))
    assert out["level"] is None
    # 5 日因子由 records 独立计算（与 indices 的 VIX 缺失无关）→ 尽列可得项
    assert [f["name"] for f in out["factors"]] == ["MOVE", "VIX 5日"]


def test_risk_appetite_5d_insufficient(monkeypatch):
    """非空收盘不足 6 个 → VIX 5日 因子缺省（不入 factors、不计分）。"""
    _ra_clean_env(monkeypatch)
    out = web.app._compute_risk_appetite(_ra_indices(22.0, 98.1), _ra_records([22.0] * 3))
    assert out["level"] == "neutral" and out["score"] == 0
    assert "VIX 5日" not in {f["name"] for f in out["factors"]}


def test_risk_appetite_5d_none_gaps_use_last_six_non_null(monkeypatch):
    """5 日窗口取最近 6 个非 None 收盘（None 间隙跳过，保持时间序）。"""
    _ra_clean_env(monkeypatch)
    records = _ra_records([16.0, None, 15.5, 15.2, None, 15.0, None, 14.9, 14.2])
    out = web.app._compute_risk_appetite(_ra_indices(14.2, 98.1), records)
    by_name = {f["name"]: f for f in out["factors"]}
    assert by_name["VIX 5日"]["change_pct"] == pytest.approx(-11.25, abs=0.1)   # (14.2-16)/16


def test_api_latest_includes_risk_appetite(client):
    """/api/latest 恒含 risk_appetite 键（client 夹具数据：VIX 警惕 0 + MOVE 平静 0
    + 5 日 (23-18)/18≈+27.8% → -1 → low）。"""
    r = client.get("/api/latest")
    assert r.status_code == 200
    ra = r.json()["risk_appetite"]
    assert ra["level"] == "low" and ra["score"] == -1
    assert [f["name"] for f in ra["factors"]] == ["VIX", "MOVE", "VIX 5日"]


# ---- 市场关系（三十三期：/api/latest 新增 correlation，context 显著对直通）----

def test_correlation_payload_passthrough():
    """ctx 带 correlation 列表 → 原样直通（不做逐条字段校验，契约由生产端保证）。"""
    corr = [{"a": "VIX", "b": "GSPC", "pair": "恐慌指数(VIX) ↔ 标普500", "r": -0.62, "n": 28}]
    assert web.app._correlation_payload({"correlation": corr}) == corr


def test_correlation_payload_none_and_bad_type():
    """ctx None / correlation 缺失 / 非列表 → []（容错语义同 _sector_payload）。"""
    assert web.app._correlation_payload(None) == []
    assert web.app._correlation_payload({}) == []
    assert web.app._correlation_payload({"correlation": {"a": 1}}) == []
    assert web.app._correlation_payload({"correlation": "x"}) == []


def test_api_latest_correlation_key_empty_ctx(client):
    """client 夹具 ctx 无 correlation 键 → 恒有键且为 []（前端空态兜底）。"""
    r = client.get("/api/latest")
    assert r.status_code == 200
    assert r.json()["correlation"] == []


def test_api_latest_correlation_from_context(tmp_path, monkeypatch):
    """ctx 带显著对 → 原样透出（与 context/最新.json 逐条一致）。"""
    monkeypatch.setattr(st, "DB_PATH", tmp_path / "test-history.db")
    st.init_db()
    st.upsert_history_rows(st.records_to_rows([{"date": "2026-09-10", "gspc": 100.0}]))
    monkeypatch.setattr(web.app, "ALERTS_DIR", tmp_path / "alerts")
    ctx_dir = tmp_path / "context"
    ctx_dir.mkdir()
    corr = [{"a": "VIX", "b": "GSPC", "pair": "恐慌指数(VIX) ↔ 标普500", "r": -0.62, "n": 28}]
    (ctx_dir / "2026-09-11.json").write_text(json.dumps(
        {"date": "2026-09-11", "indices": {}, "sector_heat": {"gainers": [], "losers": []},
         "correlation": corr}), encoding="utf-8")
    monkeypatch.setattr(web.app, "CONTEXT_DIR", ctx_dir)

    from fastapi.testclient import TestClient

    data = TestClient(web.app.app).get("/api/latest").json()
    assert data["correlation"] == corr


# ---- 最新资讯（三十三期：Hermes 落盘 data/news.json，web 只读 /api/news）----

def _write_news(tmp_path, monkeypatch, payload, name="news.json"):
    """写资讯样例并 patch web.app.NEWS_FILE（定义在使用方 web.app，monkeypatch 纪律）。"""
    f = tmp_path / name
    f.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(web.app, "NEWS_FILE", f)
    return f


def test_build_watchlist_payload_tail_param(tmp_path, monkeypatch):
    """三十四期：tail 参数控制趋势深度（/api/macro 用 400 补全黄金 1Y 视图）；默认 30 语义不变。"""
    monkeypatch.delenv("STATUS_THRESHOLD_VIX_CALM", raising=False)
    closes = [("2026-06-%02d" % i, 100.0 + i) for i in range(1, 29)]   # 28 点
    stocks = [{"symbol": "GC=F", "label": "黄金COMEX"}]
    series = {"GC=F": closes}
    out30 = web.app._build_watchlist_payload(stocks, {"GC=F": 127.0}, series)
    assert len(out30["trend"]["dates"]) == 28
    out5 = web.app._build_watchlist_payload(stocks, {"GC=F": 127.0}, series, tail=5)
    assert len(out5["trend"]["dates"]) == 5
    assert out5["trend"]["series"][0]["raw"][-1] == 128.0


def test_api_news_missing_file(client, tmp_path, monkeypatch):
    """文件缺失 → 200 空结构（Hermes 未接入前为常驻空态，HTTP 200 恒定）。"""
    monkeypatch.setattr(web.app, "NEWS_FILE", tmp_path / "nonexistent" / "news.json")
    r = client.get("/api/news")
    assert r.status_code == 200
    assert r.json() == {"date": None, "items": [], "count": 0}


def test_api_news_valid_filtered_capped(client, tmp_path, monkeypatch):
    """合法文件 → 过滤（title 空 / url 非 http(s) 剔除）+ cap 8 + 缺省字段补 ""。"""
    items = [{"title": f"新闻{i}", "url": f"https://e.com/{i}", "source": "Reuters",
              "published": "2026-09-12", "summary": f"摘要{i}"} for i in range(10)]
    items.insert(2, {"title": "", "url": "https://e.com/x"})               # 空 title → 滤
    items.insert(5, {"title": "JS 注入", "url": "javascript:alert(1)"})    # 非 http(s) → 滤
    items.append({"url": "https://e.com/9"})                               # 缺 title → 滤
    _write_news(tmp_path, monkeypatch, {"date": "2026-09-12", "items": items})
    r = client.get("/api/news")
    assert r.status_code == 200
    data = r.json()
    assert data["date"] == "2026-09-12" and data["count"] == 8
    assert all(it["title"] and it["url"].startswith("https://") for it in data["items"])
    assert all(set(it.keys()) == {"title", "url", "source", "published", "summary"}
               for it in data["items"])


def test_api_news_bad_json(client, tmp_path, monkeypatch):
    """坏 JSON → 空结构（不 500）。"""
    _write_news(tmp_path, monkeypatch, "{broken", name="news-bad.json")
    r = client.get("/api/news")
    assert r.status_code == 200
    assert r.json() == {"date": None, "items": [], "count": 0}


def test_api_news_non_dict_payload(client, tmp_path, monkeypatch):
    """payload 非 dict（如列表）→ 空结构。"""
    _write_news(tmp_path, monkeypatch, "[]", name="news-list.json")
    r = client.get("/api/news")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_api_news_missing_items_key(client, tmp_path, monkeypatch):
    """缺 items 键 → 空结构（date 也不透出）。"""
    _write_news(tmp_path, monkeypatch, {"date": "2026-09-12"})
    r = client.get("/api/news")
    assert r.status_code == 200
    assert r.json() == {"date": None, "items": [], "count": 0}


# ---- /api/econ（经济数据 BLS，2026-09-14）----

def _econ_months(n, end_year=2026, end_month=8):
    """n 个连续月份键（升序），末尾为 end_year-end_month。"""
    out, y, m = [], end_year, end_month
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _econ_raw_14():
    """最小可用 raw：4 序列各 14 个月（够算同比），水平温和上行 → 同比非空。"""
    yms = _econ_months(14)
    cpi = [(ym, 300.0 + i) for i, ym in enumerate(yms)]
    return {
        "cpi": cpi,
        "ppi": list(cpi),
        "payrolls": [(ym, 150000.0 + 100 * i) for i, ym in enumerate(yms)],
        "unemployment": [(ym, 4.5 - 0.02 * i) for i, ym in enumerate(yms)],
    }


def test_api_econ_structure(monkeypatch):
    """端点：200 + 4 序列（latest/yoy/direction 非空）+ as_of 为数据月份 + 四象限自洽。"""
    monkeypatch.setattr(web.app, "fetch_econ_series", lambda *a, **k: _econ_raw_14())
    from fastapi.testclient import TestClient

    r = TestClient(web.app.app).get("/api/econ")
    assert r.status_code == 200
    data = r.json()
    assert data["as_of"] == "2026-08"                      # ★ 数据月份，不是抓取时间
    assert [s["key"] for s in data["series"]] == ["cpi", "ppi", "unemployment", "payrolls"]
    for s in data["series"]:
        assert s["latest"] is not None and s["yoy"] is not None and s["direction"]
    assert data["quadrant"] in ("reflation", "goldilocks", "stagflation", "deflation")
    assert data["quadrant_label"]
    # 象限与两轴自洽（查表反推）
    assert (data["inflation_axis"], data["growth_axis"]) in {
        ("up", "expanding"), ("down", "expanding"), ("up", "contracting"), ("down", "contracting")}
    assert data["basis"]["growth"]                       # 口径标注（勿被误读成 PMI）


def test_api_econ_degrade_and_failure_not_cached(monkeypatch):
    """BLS 失败 → 200 + 空结构（不 500）；且**失败不写缓存**（否则会锁死 6 小时）。"""
    state = {"raw": {}}
    monkeypatch.setattr(web.app, "fetch_econ_series", lambda *a, **k: state["raw"])
    from fastapi.testclient import TestClient

    c = TestClient(web.app.app)
    bad = c.get("/api/econ").json()
    assert bad["as_of"] is None and bad["quadrant"] is None and len(bad["series"]) == 4
    # 恢复后立刻拿到数据（若失败被缓存，这里仍是空 → 断言失败）
    state["raw"] = _econ_raw_14()
    assert c.get("/api/econ").json()["as_of"] == "2026-08"


# ---- 宏观环境纯函数（2026-09-14 宏观页 /macro）----
#
# ⚠️ 这里只测 web 层的「风险偏好轴」；四象限（reflation/…）由 src/econ_fetcher.py 产出，
#    其单测在 tests/test_econ_fetcher.py（职责边界见 plan §4.4）。

def _mk_trend(days, **series):
    """构造 /api/macro 形状的 trend（dates + series[].raw）；键沿用 sym.lower()（含 ^tnx / cl=f）。"""
    return {"dates": ["d%04d" % i for i in range(days)],
            "series": [{"key": k, "raw": list(v)} for k, v in series.items()]}


def _flat_then(value, days, last, tail):
    """`days` 个 `value` 后接 `tail` 个 `last`（制造末点突变，便于落档）。"""
    return [value] * (days - tail) + [last] * tail


def _price_from_returns(rets, start=100.0):
    """由逐日收益率构造价格序列（长度 = len(rets) + 1 → 恰好产生 len(rets) 个收益率）。"""
    out, price = [start], start
    for r in rets:
        price *= (1 + r)
        out.append(price)
    return out


class TestBandScore:
    def test_bands(self):
        got = [web.app._band_score(x, (1.0, 2.0)) for x in (0.5, 1.5, 3.0, -0.5, -1.5, -3.0)]
        assert got == [0, 1, 2, 0, -1, -2]

    def test_inverse_flips_sign(self):
        assert [web.app._band_score(x, (1.0, 2.0), inverse=True) for x in (1.5, -1.5)] == [-1, 1]


class TestMacroHelpers:
    def test_chg_pct_normal(self):
        assert web.app._chg_pct([100.0, 110.0], 1) == 10.0

    def test_chg_pct_insufficient(self):
        assert web.app._chg_pct([100.0], 5) is None

    def test_chg_pct_zero_base(self):
        assert web.app._chg_pct([0.0, 5.0], 1) is None

    def test_chg_abs_is_absolute_not_percent(self):
        """利率用绝对变化：4.00% → 4.30% 应得 0.3（百分点），不是 7.5（%）。"""
        assert web.app._chg_abs([4.0, 4.3], 1) == 0.3

    def test_chg_abs_insufficient(self):
        assert web.app._chg_abs([4.0], 5) is None

    def test_dev_from_ma(self):
        # 最近 10 点 = 9×100 + 110 → 均值 101 → 偏离 (110-101)/101 = 8.91%
        assert web.app._dev_from_ma_pct([100.0] * 10 + [110.0], 10) == 8.91

    def test_dev_insufficient(self):
        assert web.app._dev_from_ma_pct([100.0] * 5, 10) is None


class TestMacroRegime:
    def test_empty_is_neutral(self):
        r = web.app._compute_macro_regime([], [], {})
        assert r["level"] == "neutral" and r["score"] == 0
        assert r["score100"] == 50.0 and r["factors"] == []

    def test_all_risk_on_scores_max(self):
        trend = _mk_trend(60, **{"dx-y.nyb": _flat_then(100.0, 60, 97.0, 3),
                                 "^tnx": _flat_then(4.0, 60, 3.7, 3),
                                 "cl=f": _flat_then(70.0, 60, 75.0, 3)})
        r = web.app._compute_macro_regime(
            [{"symbol": "VIX", "value": 15.0}, {"symbol": "MOVE", "value": 90.0}], [], trend)
        assert r["score"] == 8 and r["normalized"] == 1.0
        assert r["level"] == "risk_on" and r["score100"] == 100.0

    def test_all_risk_off_scores_min(self):
        trend = _mk_trend(60, **{"dx-y.nyb": _flat_then(100.0, 60, 103.0, 3),
                                 "^tnx": _flat_then(4.0, 60, 4.3, 3),
                                 "cl=f": _flat_then(70.0, 60, 65.0, 3)})
        r = web.app._compute_macro_regime(
            [{"symbol": "VIX", "value": 40.0}, {"symbol": "MOVE", "value": 150.0}], [], trend)
        assert r["score"] == -8 and r["level"] == "risk_off" and r["score100"] == 0.0

    def test_risk_pref_clamped(self):
        """VIX 恐慌(-2) + MOVE 恐慌(-1) → clamp 到 -2（单维度不越界）。"""
        r = web.app._compute_macro_regime(
            [{"symbol": "VIX", "value": 40.0}, {"symbol": "MOVE", "value": 150.0}], [], {})
        assert r["factors"][0]["impact"] == -2

    def test_score100_formula(self):
        r = web.app._compute_macro_regime(
            [{"symbol": "VIX", "value": 25.0}, {"symbol": "MOVE", "value": 110.0}], [], {})
        assert r["score100"] == round((r["normalized"] + 1) / 2 * 100, 1)

    def test_missing_dims_keep_denominator(self):
        """缺数据的维度不计分，但分母仍是 8 → 结果偏 Neutral（保守默认，不猜）。"""
        trend = _mk_trend(60, **{"dx-y.nyb": _flat_then(100.0, 60, 97.0, 3)})
        r = web.app._compute_macro_regime([], [], trend)
        assert len(r["factors"]) == 1 and r["normalized"] == 0.25
        assert r["level"] == "neutral"          # 恰在 ±0.25 边界上 → 不上调

    def test_no_trend_factors_only_risk(self):
        """trend 为空但 VIX 可得 → 只有风险偏好一个维度。"""
        r = web.app._compute_macro_regime([{"symbol": "VIX", "value": 15.0}], [], {})
        assert [f["name"] for f in r["factors"]] == ["风险偏好"]


class TestMacroCorrelation:
    def test_six_pairs_and_signs(self):
        # ⚠️ 必须用**有波动**的收益率：恒定收益率的序列方差≈0（浮点噪声），
        # Pearson 会退化成 0/0 噪声（实测 -0.01）而不是 ±1 —— 那是"零方差"不是"完全相关"。
        days = 320
        rets = [0.01 if i % 20 < 10 else -0.008 for i in range(days)]
        up = _price_from_returns(rets)
        down = _price_from_returns([-r for r in rets])
        n = len(up)
        trend = _mk_trend(n, **{"dx-y.nyb": up, "cl=f": up, "gc=f": down,
                                "^tnx": [4.0] * n})            # ^tnx 常量 → 真零方差
        corr = {c["pair"]: c for c in web.app.compute_macro_correlation(trend)}
        assert len(corr) == 6
        assert corr["美元 ↔ 黄金"]["r"] == -1.0
        assert corr["美元 ↔ 原油"]["r"] == 1.0
        assert corr["黄金 ↔ 原油"]["r"] == -1.0
        # 常量序列（零方差）→ r=None，绝不显示错误的 0
        assert corr["美元 ↔ 10Y 美债"]["r"] is None
        assert corr["美元 ↔ 10Y 美债"]["n"] > 0     # 样本是够的，是零方差导致 None

    def test_insufficient_points_returns_none(self):
        trend = _mk_trend(10, **{"dx-y.nyb": [100.0 + i for i in range(10)],
                                 "gc=f": [100.0 + 2 * i for i in range(10)]})
        first = web.app.compute_macro_correlation(trend)[0]
        assert first["r"] is None and first["n"] == 9

    def test_empty_trend(self):
        out = web.app.compute_macro_correlation({})
        assert len(out) == 6 and all(c["r"] is None and c["n"] == 0 for c in out)


class TestMacroHistoryRegime:
    @staticmethod
    def _records(n, vix, move):
        return [{"date": "d%04d" % i, "vix": vix, "move": move} for i in range(n)]

    def test_all_calm_is_risk_on(self):
        out = web.app._macro_history_regime(self._records(35, 15.0, 90.0), days=30)
        assert out == {"risk_on": 30, "neutral": 0, "risk_off": 0, "days": 30}

    def test_all_panic_is_risk_off(self):
        out = web.app._macro_history_regime(self._records(35, 40.0, 150.0), days=30)
        assert out == {"risk_on": 0, "neutral": 0, "risk_off": 30, "days": 30}

    def test_middle_is_neutral(self):
        out = web.app._macro_history_regime(self._records(35, 25.0, 110.0), days=30)
        assert out == {"risk_on": 0, "neutral": 30, "risk_off": 0, "days": 30}

    def test_empty_records(self):
        assert web.app._macro_history_regime([]) == {"risk_on": 0, "neutral": 0,
                                                     "risk_off": 0, "days": 0}

    def test_days_capped(self):
        out = web.app._macro_history_regime(self._records(40, 15.0, 90.0), days=30)
        assert out["days"] == 30 and out["risk_on"] == 30


def test_load_macro_derived_keys(tmp_path, monkeypatch):
    """_load_macro 除 stocks/trend 外还带 regime / correlation / history_regime（内存派生，零落盘）。"""
    hist = [{"date": "2026-08-%02d" % (i + 1), "vix": 15.0, "move": 90.0} for i in range(28)]
    _seed_history(tmp_path, monkeypatch, hist)
    syms = ["DX-Y.NYB", "^TNX", "CL=F", "GC=F"]
    values = {s: 100.0 for s in syms}
    series = {s: [("d1", 100.0), ("d2", 101.0)] for s in syms}
    monkeypatch.setattr(web.app, "fetch_watchlist", lambda s, **k: (values, series, {}))

    payload = web.app._load_macro()
    assert set(payload) >= {"stocks", "trend", "regime", "correlation", "history_regime"}
    assert payload["regime"]["level"] in ("risk_on", "neutral", "risk_off")
    assert payload["regime"]["score100"] is not None
    assert len(payload["correlation"]) == 6
    assert payload["history_regime"]["days"] == 28


def test_macro_page_renders(client):
    """GET /macro → 200 + 7 个模块骨架 + 共用 shell（顶栏/侧栏）+ macro.js（2026-09-14 宏观页）。"""
    r = client.get("/macro")
    assert r.status_code == 200
    html = r.text
    assert 'id="macro-chart"' in html
    for mid in ("mac-regime", "mac-market", "mac-vars", "mac-factors",
                "mac-relation", "mac-history", "mac-econ"):
        assert 'id="%s"' % mid in html, mid
    # 共用 shell（_topbar.html / _sidebar.html）
    assert 'class="topbar"' in html and 'id="sidebar"' in html
    assert 'href="/macro"' in html                        # 侧栏「宏观数据」
    assert 'class="nav-item active" href="/macro"' in html   # active_page="macro" 高亮
    assert 'href="/#overview"' in html                    # base_prefix="/" → 回首页锚点
    assert '/static/macro.js?v=' in html
    assert 'id="macro-asof"' in html and 'id="econ-asof"' in html


def test_index_nav_macro_link_enabled(client):
    """首页侧栏「宏观数据」已由占位改为可点链接（href=/macro），且首页锚点仍是无前缀形式。"""
    html = client.get("/").text
    assert '<a class="nav-item" href="/macro">' in html
    assert '<a class="nav-item active" href="#overview"' in html
    assert 'href="/#overview"' not in html                # 首页 base_prefix="" → 不带 / 前缀


def test_api_econ_ttl_cache(monkeypatch):
    """连续调 3 次只触发 1 次 BLS 请求（6h TTL 生效）。"""
    calls = []
    monkeypatch.setattr(web.app, "fetch_econ_series",
                        lambda *a, **k: calls.append(1) or _econ_raw_14())
    from fastapi.testclient import TestClient

    c = TestClient(web.app.app)
    for _ in range(3):
        assert c.get("/api/econ").json()["as_of"] == "2026-08"
    assert len(calls) == 1
    # 防回退：BLS 无 Key 限额 25 次/日，TTL 绝不能"对齐"成 90s（那是 960 次/日）
    assert web.app._ECON_TTL == 6 * 3600

# ---- 中国宏观页 /macro/cn（2026-09-14）----

def test_macro_cn_page_renders(client):
    """GET /macro/cn → 200 + 5 层模块骨架 + 侧栏「中国宏观」active + macro_cn.js。"""
    r = client.get("/macro/cn")
    assert r.status_code == 200
    html = r.text
    assert 'id="cn-chart"' in html
    for mid in ("cn-regime", "cn-market", "cn-vars", "cn-factors", "cn-rate-list",
                "cn-estate", "cn-econ"):
        assert 'id="%s"' % mid in html, mid
    # 侧栏：本页 highight「中国宏观」，且「宏观数据」**不再** active
    assert 'class="nav-item active" href="/macro/cn"' in html
    assert 'class="nav-item active" href="/macro"' not in html
    assert '/static/macro_cn.js?v=' in html
    # 主题预应用脚本必须与 macro.html 同源（含 dark 分支），否则深色用户进本页会变白
    assert 'if (t === "light" || t === "dark")' in html


def test_sidebar_has_both_macro_links(client):
    """侧栏同时存在「宏观数据」与「中国宏观」两个跨页链接（navCount 10 → 11）。"""
    html = client.get("/").text
    assert '<a class="nav-item" href="/macro">' in html
    assert '<a class="nav-item" href="/macro/cn">' in html
    # ⚠️ 新项必须是真链接：data-target 会被页内锚点处理器判成坏项，href="#" 会跳页顶
    assert 'data-target="macro' not in html


def test_api_econ_cn_degrades(monkeypatch):
    """AkShare 全失败 → 200 + 空结构（不 500）；失败明细进 failed 供前端逐模块降级。"""
    monkeypatch.setattr(web.app, "fetch_cn_econ_raw",
                        lambda keys=None, timeout=None: ({k: [] for k in (keys or [])}, list(keys or [])))
    from fastapi.testclient import TestClient

    data = TestClient(web.app.app).get("/api/econ/cn").json()
    assert data["as_of"] is None and data["quadrant"] is None
    assert data["failed"]                        # 13 个 key 全失败 → 如实列出
    assert data["basis"]["growth"]               # 口径标注仍在（前端要显示"为什么没有"）


def test_api_cn_quotes_degrades(monkeypatch):
    """汇率 + 中债双双失败 → 200 + 三项 failed（不 500），且**失败不写缓存**。"""
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(web.app, "_fetch_yahoo_watch", boom)
    monkeypatch.setattr(web.app, "fetch_bond_yield_curves", lambda *a, **k: {})
    from fastapi.testclient import TestClient

    c = TestClient(web.app.app)
    data = c.get("/api/cn/quotes").json()
    assert data["as_of"] is None
    assert sorted(data["failed"]) == ["bond10y", "cny", "credit_spread"]
    assert data["cny"] is None and data["bond10y"] is None and data["credit_spread"] is None


def test_api_cn_quotes_shape(monkeypatch):
    """汇率 + 国债曲线成功 → 三项齐全；信用利差 = 商金债AAA − 国债（bp，按日期对齐）。"""
    monkeypatch.setattr(web.app, "_fetch_yahoo_watch",
                        lambda *a, **k: (6.7, [("2026-09-13", 6.71), ("2026-09-14", 6.70)]))
    monkeypatch.setattr(web.app, "fetch_bond_yield_curves", lambda *a, **k: {
        "国债": [("2026-09-14", 1.6888)],
        "商金债AAA": [("2026-09-14", 1.9516)],
    })
    from fastapi.testclient import TestClient

    data = TestClient(web.app.app).get("/api/cn/quotes").json()
    assert data["as_of"] == "2026-09-14"
    assert data["failed"] == []
    assert data["cny"]["value"] == 6.7
    assert data["bond10y"]["value"] == 1.6888
    # (1.9516 - 1.6888) * 100 = 26.28 bp
    assert data["credit_spread"]["value"] == 26.28
    assert data["credit_spread"]["unit"] == "bp"


def test_cn_econ_ttl_is_hourly():
    """防回退：13 个 AkShare 接口，TTL 绝不能"对齐"成 90s（那是每日近千次）。"""
    assert web.app._CN_ECON_TTL == 6 * 3600


# ---- 访问控制（HTTP Basic Auth，2026-09-19）----
# 任务档 tasks/2026-09-19-web-basic-auth/（方案 A；D-1「未配置 → fail-open」已裁定）。
#
# ⚠️ R9：鉴权是**现读 env**（`web.app.auth_enabled()`），不是 import 时定型的模块级常量
#    ⇒ monkeypatch env 直接生效，**不需要** `importlib.reload`（reload 会污染其它用例）。
# ⚠️ 401 用例一律用**裸 TestClient** 且不套 `client` 夹具：中间件在路由处理器**之前**短路，
#    既不需要数据夹具，也不会被本机真实 `data/` 影响（更快也更稳）。
AUTH_USER, AUTH_PASS = "mpdemo", "s3cret-pass-16"

# 覆盖口径：**4 页 + 10 API + 静态资源**全部要 401（plan §2 取证；`/healthz` 除外，单独验）
AUTH_PROTECTED = ("/", "/macro", "/macro/cn", "/timeline",
                  "/api/history", "/api/latest", "/api/alerts", "/api/news", "/api/timeline",
                  "/api/watchlist", "/api/macro", "/api/econ", "/api/econ/cn", "/api/cn/quotes",
                  "/static/app.js")


def _auth_env(monkeypatch, user=AUTH_USER, pwd=AUTH_PASS, disabled=None):
    """设好 env 后返回 TestClient；`disabled="1"` 时额外开 `MP_AUTH_DISABLED`。"""
    monkeypatch.setenv("MP_AUTH_USER", user)
    monkeypatch.setenv("MP_AUTH_PASS", pwd)
    if disabled:
        monkeypatch.setenv("MP_AUTH_DISABLED", disabled)
    else:
        monkeypatch.delenv("MP_AUTH_DISABLED", raising=False)
    from fastapi.testclient import TestClient
    return TestClient(web.app.app)


def test_auth_requires_credentials_with_www_authenticate(monkeypatch):
    """无凭据 → 401 **且**带 `WWW-Authenticate`（D-7：缺该头浏览器不弹窗，表现为反复失败无提示）。"""
    c = _auth_env(monkeypatch)
    r = c.get("/")
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == 'Basic realm="MarketPulse"'


def test_auth_covers_every_page_api_and_static(monkeypatch):
    """P0 缺口的覆盖口径：4 页 + 10 API + 静态资源**全部** 401，不允许有漏网的端点。"""
    c = _auth_env(monkeypatch)
    bad = [p for p in AUTH_PROTECTED if c.get(p).status_code != 401]
    assert not bad, bad


def test_auth_wrong_password_is_401(monkeypatch):
    c = _auth_env(monkeypatch)
    assert c.get("/", auth=(AUTH_USER, "wrong-pass")).status_code == 401
    assert c.get("/", auth=("wrong-user", AUTH_PASS)).status_code == 401


def test_auth_correct_credentials_is_200(monkeypatch):
    c = _auth_env(monkeypatch)
    r = c.get("/", auth=(AUTH_USER, AUTH_PASS))
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_auth_healthz_is_public(monkeypatch):
    """🔴 R1：`/healthz` 无凭据必须 200（Railway healthcheck；给 `/` 返 401 会重启循环）。"""
    c = _auth_env(monkeypatch)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    # 带凭据同样 200（白名单不是"只允许匿名"）
    assert c.get("/healthz", auth=(AUTH_USER, AUTH_PASS)).status_code == 200


def test_auth_disabled_env_opens_everything(monkeypatch):
    """`MP_AUTH_DISABLED=1`（本地开发 / 自动化验收用）→ 全站放行。"""
    c = _auth_env(monkeypatch, disabled="1")
    assert web.app.auth_enabled() is False
    assert c.get("/").status_code == 200
    assert c.get("/healthz").status_code == 200


def test_auth_not_configured_fails_open_and_warns(monkeypatch, caplog):
    """D-1（已裁定）：**未配置**凭据 → 放行 + 启动 WARNING（fail-open，不是 fail-closed）。

    ⚠️ 忘了配 env 就等同没鉴权 ⇒ 这条 WARNING 是唯一兜底信号（R3），必须锁住。
    """
    monkeypatch.delenv("MP_AUTH_USER", raising=False)
    monkeypatch.delenv("MP_AUTH_PASS", raising=False)
    monkeypatch.delenv("MP_AUTH_DISABLED", raising=False)
    assert web.app.auth_enabled() is False
    from fastapi.testclient import TestClient
    c = TestClient(web.app.app)
    assert c.get("/").status_code == 200
    with caplog.at_level(logging.WARNING, logger="marketpulse"):
        web.app._log_auth_state()
    assert "鉴权未启用" in caplog.text and "裸奔" in caplog.text


def test_auth_malformed_headers_are_401_not_500(monkeypatch):
    """畸形 `Authorization` 一律 401，**绝不 500**（坏输入不得变成服务端错误）。"""
    import base64
    c = _auth_env(monkeypatch)
    cases = {
        "无 Basic 前缀": "xyz",
        "非 base64": "Basic @@@@",
        "base64 但无冒号": "Basic " + base64.b64encode(AUTH_USER.encode()).decode(),
        "空凭据串": "Basic ",
    }
    for label, hdr in cases.items():
        r = c.get("/", headers={"Authorization": hdr})
        assert r.status_code == 401, (label, r.status_code)


def test_auth_basic_prefix_is_case_insensitive(monkeypatch):
    """RFC 7235：`Basic ` 方案名大小写不敏感 ⇒ 小写前缀也必须认。"""
    import base64
    c = _auth_env(monkeypatch)
    raw = base64.b64encode(("%s:%s" % (AUTH_USER, AUTH_PASS)).encode()).decode()
    assert c.get("/", headers={"Authorization": "basic " + raw}).status_code == 200


# ---- 阈值回测（2026-09-20，tasks/2026-09-20-backtest-ui/）-----------------------------------
# 统计逻辑在 src/backtest.py（与 CLI **同一份实现**）；web 只组装响应。故这里的断言只覆盖
# **契约与降级**，算法正确性由 tests/test_backtest.py 负责。






# ---- 阈值回测（2026-09-20，tasks/2026-09-20-backtest-ui/）-----------------------------------
# 统计逻辑在 src/backtest.py（与 CLI **同一份实现**）；web 只组装响应。故这里的断言只覆盖
# **契约与降级**，算法正确性由 tests/test_backtest.py 负责。

def _fake_rows(days: int, jump_at: int = 20, symbol: str = "vix"):
    """造 days 天单标的长行（第 jump_at 天 +25% ⇒ 必触发一次）。"""
    rows, price = [], 100.0
    for i in range(1, days + 1):
        price = price * (1.25 if i == jump_at else 1.0)
        date = "2026-01-%02d" % i if i <= 31 else "2026-02-%02d" % (i - 31)
        rows.append((date, symbol, price, 0.0))
    return rows


def test_api_backtest_payload_contract(monkeypatch):
    """`/api/backtest` 字段齐全，且标的与常量同源（`src.backtest.BACKTEST_SYMBOLS`）。"""
    from fastapi.testclient import TestClient

    from src import backtest as sb
    monkeypatch.setattr(web.app.st, "query_history", lambda *a, **k: _fake_rows(40))
    r = TestClient(web.app.app).get("/api/backtest")
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"as_of", "window", "stats", "threshold_config", "symbols",
                      "methods", "elapsed_ms", "empty_reason"}
    assert len(d["methods"]) == 7                    # 口径 7 条**原文**（与 md 报告同源）
    assert len(d["threshold_config"]["fallback"]) == len(sb.BACKTEST_SYMBOLS)
    assert [s["symbol"] for s in d["symbols"]] == sb.BACKTEST_SYMBOLS
    assert d["stats"]["triggers"] >= 1               # 夹具里那一次跳变
    assert d["empty_reason"] is None


def test_api_backtest_does_not_cache(monkeypatch):
    """🔴 **故意不缓存**（plan §3.4 / 硬约束 4）：改配置后必须立刻可见。

    判据：连续两次调用各算一次（用调用计数证明没有走缓存）—— 若后人"顺手"加了 TTL，
    本用例立刻红（这正是 plan R7 要防的）。
    """
    from fastapi.testclient import TestClient

    calls = {"n": 0}

    def _counted(*a, **k):
        calls["n"] += 1
        return _fake_rows(40)

    monkeypatch.setattr(web.app.st, "query_history", _counted)
    c = TestClient(web.app.app)
    c.get("/api/backtest")
    c.get("/api/backtest")
    assert calls["n"] == 2, "第二次调用走了缓存 ⇒ 「改阈值立刻可见」的价值被破坏"


def test_api_backtest_degrades_to_empty_state(monkeypatch):
    """数据不足（有效交易日 < 30）⇒ **恒 200** + 空 symbols + empty_reason（不报错）。"""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(web.app.st, "query_history", lambda *a, **k: _fake_rows(5))
    r = TestClient(web.app.app).get("/api/backtest")
    assert r.status_code == 200
    d = r.json()
    assert d["symbols"] == []
    assert "不足" in (d["empty_reason"] or "")
    assert len(d["methods"]) == 7                    # 空态仍给口径，便于解读


def test_backtest_page_renders():
    """`/backtest` 页面可开且带页标题（模板渲染不为空）。"""
    from fastapi.testclient import TestClient

    r = TestClient(web.app.app).get("/backtest")
    assert r.status_code == 200
    assert "阈值回测" in r.text
    assert "backtest.js" in r.text


# ---- 设置页（2026-09-20，tasks/2026-09-20-settings-page/）-----------------------------------
# web 首次获得「有限写」（config.json 白名单键）。契约：恒 200 读 / 400 白名单外 / 403 Railway /
# 保存成功必须 reload（否则告警与回测的 import 快照不动 = 功能骗人，plan R1）。

@pytest.fixture
def _settings_cfg(tmp_path, monkeypatch):
    """临时 config.json（隔离真实文件）。"""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"alert": {"vix": 20.0, "k_factor": 2.0, "dynamic": True,
                                       "lookback_days": 20}}), encoding="utf-8")
    monkeypatch.setenv("CONFIG_PATH", str(p))
    return p


def test_api_settings_get_contract(_settings_cfg):
    from fastapi.testclient import TestClient

    d = TestClient(web.app.app).get("/api/settings").json()
    assert set(d) >= {"readonly", "readonly_reason", "values", "env_overrides", "schema"}
    assert d["readonly"] is False
    assert d["values"]["alert.vix"] == 20.0
    assert len(d["methods"] if "methods" in d else d["schema"]) >= 1


def test_api_settings_post_saves_and_reloads(_settings_cfg, monkeypatch):
    """保存 → 文件变化 + **reload 被调用**（R1：不 reload = 功能骗人）。"""
    from fastapi.testclient import TestClient

    calls = {"n": 0}
    real = web.app._reload_config

    def _counted():
        calls["n"] += 1
        real()

    monkeypatch.setattr(web.app, "_reload_config", _counted)
    r = TestClient(web.app.app).post("/api/settings", json={"alert.k_factor": 2.5})
    assert r.status_code == 200 and r.json()["saved"] is True
    assert r.json()["values"]["alert.k_factor"] == 2.5
    assert calls["n"] == 1, "保存成功后必须重载快照"
    assert json.loads(_settings_cfg.read_text(encoding="utf-8"))["alert"]["k_factor"] == 2.5


def test_api_settings_post_rejects_unknown_key(_settings_cfg):
    """白名单外 ⇒ 400 且**文件未变**。"""
    from fastapi.testclient import TestClient

    before = _settings_cfg.read_text(encoding="utf-8")
    r = TestClient(web.app.app).post("/api/settings", json={"trend.chart_days": 45})
    assert r.status_code == 400
    assert _settings_cfg.read_text(encoding="utf-8") == before


def test_api_settings_post_403_on_railway(_settings_cfg, monkeypatch):
    """Railway 检测 ⇒ POST 403（只读是默认安全侧）。"""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    r = TestClient(web.app.app).post("/api/settings", json={"alert.vix": 25})
    assert r.status_code == 403


def test_settings_page_renders():
    from fastapi.testclient import TestClient

    r = TestClient(web.app.app).get("/settings")
    assert r.status_code == 200
    assert "设置" in r.text and "settings.js" in r.text


# ---- 组合盈亏（2026-09-20，tasks/2026-09-20-portfolio-pnl/）---------------------------------
# 判据：有 cost ⇒ pnl_pct；(value 或 cost) 缺失 ⇒ **None**（绝不算 0）；概览 = 有成本标的等权平均。

def _wl_payload(monkeypatch, stocks, values):
    """组装 _build_watchlist_payload 的结果（不联网、不依赖快照）。"""
    monkeypatch.setattr(web.app, "_watchlist_config", lambda: stocks)
    return web.app._build_watchlist_payload(stocks, values, {})


def test_watchlist_pnl_with_cost(monkeypatch):
    stocks = [{"symbol": "600519", "label": "茅台", "cost": 100.0}]
    d = _wl_payload(monkeypatch, stocks, {"600519": 112.5})
    row = d["stocks"][0]
    assert row["cost"] == 100.0 and row["pnl_pct"] == 12.5
    assert d["overview"] == {"covered": 1, "total": 1, "avg_pnl_pct": 12.5}


def test_watchlist_pnl_without_cost_is_none(monkeypatch):
    """🔴 无 cost ⇒ None，**不是 0.00%**（同 TL-6「不显示假 0.00%」）。"""
    d = _wl_payload(monkeypatch, [{"symbol": "600519", "label": "茅台"}], {"600519": 112.5})
    assert d["stocks"][0]["pnl_pct"] is None
    assert d["overview"]["covered"] == 0 and d["overview"]["avg_pnl_pct"] is None


def test_watchlist_pnl_when_value_missing(monkeypatch):
    """取数失败（value=None）⇒ 盈亏 None（不是用 cost 硬算）。"""
    d = _wl_payload(monkeypatch, [{"symbol": "600519", "label": "茅台", "cost": 100.0}], {})
    assert d["stocks"][0]["value"] is None and d["stocks"][0]["pnl_pct"] is None


def test_watchlist_overview_is_equal_weight(monkeypatch):
    """等权平均（无 shares ⇒ 不是加权/不是组合总收益）。"""
    stocks = [{"symbol": "A", "label": "a", "cost": 100.0},
              {"symbol": "B", "label": "b", "cost": 200.0},
              {"symbol": "C", "label": "c"}]
    d = _wl_payload(monkeypatch, stocks, {"A": 110.0, "B": 180.0, "C": 50.0})
    assert d["overview"] == {"covered": 2, "total": 3, "avg_pnl_pct": 0.0}   # +10% 与 -10% 等权 = 0


def test_load_watchlist_not_broken_by_cost(monkeypatch):
    """R3 回归：config 增加 cost 字段不应让 `_load_watchlist` 判为 mismatch（比对键是 symbol 集合）。"""
    stocks = [{"symbol": "600519", "label": "茅台", "cost": 1500.0}]
    # ⚠️ 快照的时点键是 `saved_at`（后端 `payload["as_of"] = snap.get("saved_at")`），不是 as_of
    snap = {"saved_at": "2026-09-20T15:00:00", "stocks": stocks, "values": {"600519": 1600.0}, "series": {}}
    # ⚠️ 打在**使用方模块**：web/app.py 用的是 `from src.analyzer import load_watchlist_snapshot`，
    #    patch src.analyzer 里的名字对 web.app 无效（本项目既定纪律：改谁用的那个名字）。
    monkeypatch.setattr(web.app, "load_watchlist_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr(web.app, "_watchlist_config", lambda: stocks)
    out = web.app._load_watchlist()
    # 快照被接受 ⇒ `as_of` 来自快照（mismatch 会走实时回退、没有 as_of）
    assert out.get("as_of") == snap["saved_at"], "加了 cost 后快照应仍被接受（不静默回退实时取数）"
    # 顺带验「存储层零改动」：cost 经快照原样透传，且据此算出盈亏
    assert out["stocks"][0]["cost"] == 1500.0
    assert out["stocks"][0]["pnl_pct"] == 6.67
