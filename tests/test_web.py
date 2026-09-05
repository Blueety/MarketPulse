"""Web 看板测试：解析纯函数 + 4 端点（TestClient + monkeypatch 路径常量到 tmp_path）。

monkeypatch 落点严格打在使用方模块 web.app（与项目既有纪律一致：路径常量在导入时已
绑定，打在定义方 analyzer 不生效）。web 为独立模块，不触碰 src/* 与既有测试。
"""
import json
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
    _load_sector_heat,
    _load_watchlist,
    _normalize_series,
    _parse_alert_file,
    _resolve_symbols,
)
from src.fetcher import SYMBOLS


@pytest.fixture(autouse=True)
def _reset_watch_cache():
    """TTL 缓存为模块级状态，跨测试会泄漏；每个测试前清空以保证断言隔离。"""
    web.app._watch_cache["ts"] = 0.0
    web.app._watch_cache["payload"] = None
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
    p = tmp_path / "history.json"
    p.write_text(json.dumps(hist), encoding="utf-8")
    monkeypatch.setattr(web.app, "HISTORY_FILE", p)
    last = _last_records(7)
    assert len(last) == 7
    assert last[-1]["date"] == "2026-08-11"


def test_last_records_empty_file(tmp_path, monkeypatch):
    p = tmp_path / "history.json"
    p.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(web.app, "HISTORY_FILE", p)
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


def test_load_alerts_desc_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(web.app, "ALERTS_DIR", tmp_path)
    for d in ["2026-08-25", "2026-08-26", "2026-08-27",
              "2026-08-28", "2026-08-29", "2026-08-30"]:
        (tmp_path / f"{d}-close.md").write_text(ALERT_MD, encoding="utf-8")
    alerts = _load_alerts(10)
    assert len(alerts) == 6
    assert [a["date"] for a in alerts] == [
        "2026-08-30", "2026-08-29", "2026-08-28",
        "2026-08-27", "2026-08-26", "2026-08-25",
    ]


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
    assert _load_sector_heat() == {"gainers": [], "losers": []}


def test_load_sector_heat_no_context_dir(monkeypatch):
    monkeypatch.setattr(web.app, "CONTEXT_DIR", Path("/nonexistent/context/dir"))
    assert _load_sector_heat() == {"gainers": [], "losers": []}


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
    assert _load_sector_heat() == {"gainers": [], "losers": []}


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
    assert _load_sector_heat() == {"gainers": [], "losers": []}



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
    hist_p = tmp_path / "history.json"
    hist_p.write_text(json.dumps(hist), encoding="utf-8")
    monkeypatch.setattr(web.app, "HISTORY_FILE", hist_p)

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
    monkeypatch.setattr(web.app, "HISTORY_FILE", tmp_path / "history.json")
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
    assert lat["sector_heat"] == {"gainers": [], "losers": []}
    assert c.get("/api/alerts").json() == []


def _seed_history(tmp_path, monkeypatch, hist):
    """写入测试历史并 monkeypatch HISTORY_FILE（落在使用方模块 web.app）。"""
    p = tmp_path / "history.json"
    p.write_text(json.dumps(hist), encoding="utf-8")
    monkeypatch.setattr(web.app, "HISTORY_FILE", p)


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
    assert client.get("/api/history?days=91").status_code == 422


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
