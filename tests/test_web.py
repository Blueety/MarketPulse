"""Web 看板测试：解析纯函数 + 4 端点（TestClient + monkeypatch 路径常量到 tmp_path）。

monkeypatch 落点严格打在使用方模块 web.app（与项目既有纪律一致：路径常量在导入时已
绑定，打在定义方 analyzer 不生效）。web 为独立模块，不触碰 src/* 与既有测试。
"""
import json
from pathlib import Path

import pytest
import web.app
from web.app import (
    _compute_latest,
    _last_records,
    _load_alerts,
    _load_sector_heat,
    _parse_alert_file,
)

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


# ---- 端点（TestClient，夹具打齐三路径常量）----

@pytest.fixture
def client(tmp_path, monkeypatch):
    hist = [
        {"date": "2026-08-24", "gspc": 100.0, "ixic": 200.0, "sh": 3000.0, "sz": 12000.0, "cyb": 3500.0, "vix": 17.0, "vxn": 23.0, "move": 70.0, "gld": 420.0, "btc": 76000.0},
        {"date": "2026-08-25", "gspc": 101.0, "ixic": 202.0, "sh": 3010.0, "sz": 12050.0, "cyb": 3520.0, "vix": 18.0, "vxn": 23.5, "move": 71.0, "gld": 421.0, "btc": 76200.0},
        {"date": "2026-08-26", "gspc": 102.0, "ixic": 205.0, "sh": 3020.0, "sz": 12100.0, "cyb": 3540.0, "vix": None, "vxn": 24.0, "move": 72.0, "gld": 423.0, "btc": 76300.0},
        {"date": "2026-08-27", "gspc": 103.0, "ixic": 208.0, "sh": 3030.0, "sz": 12150.0, "cyb": 3560.0, "vix": 19.0, "vxn": 24.5, "move": 73.0, "gld": 424.0, "btc": 76400.0},
        {"date": "2026-08-28", "gspc": 104.0, "ixic": 210.0, "sh": 3040.0, "sz": 12200.0, "cyb": 3580.0, "vix": 20.0, "vxn": 25.0, "move": 74.0, "gld": 425.0, "btc": 76500.0},
        {"date": "2026-08-29", "gspc": 105.0, "ixic": 212.0, "sh": 3050.0, "sz": 12250.0, "cyb": 3600.0, "vix": None, "vxn": 25.5, "move": 75.0, "gld": 426.0, "btc": 76600.0},
        {"date": "2026-08-30", "gspc": 106.0, "ixic": 214.0, "sh": 3060.0, "sz": 12300.0, "cyb": 3620.0, "vix": 21.0, "vxn": 26.0, "move": 76.0, "gld": 427.0, "btc": 76700.0},
        {"date": "2026-08-31", "gspc": 107.0, "ixic": 216.0, "sh": 3070.0, "sz": 12350.0, "cyb": 3640.0, "vix": 22.0, "vxn": 26.5, "move": 77.0, "gld": 428.0, "btc": 76800.0},
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
    assert len(data["dates"]) <= 7
    assert len(data["series"]) == 10
    vix = next(s for s in data["series"] if s["key"] == "vix")
    # 最后 7 条 = 08-25..08-31；08-26 的 vix 为 null，index 1
    assert vix["values"][1] is None


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
