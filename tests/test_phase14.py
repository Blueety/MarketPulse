"""十四期日报图片化专项测试（全 mock playwright，不依赖 wkhtmltoimage 二进制）。

覆盖：md 解析（日期/卡片/图表/解读）/ 告警解析 / 模板渲染 / 编排接线（成功/导入失败/超时/尺寸守卫）/
daily_report 容错退出码 / 重渲染脚本入口。
"""

import sys
import time
import types
import zlib
import struct as _struct

import pytest

from src import image_renderer as ir

SAMPLE_MD = """# 📊 全市场情绪日报

**日期**：2026-08-29（美东时间）

---

## 🌏 美股大盘

| 指数 | 收盘价 | 涨跌幅 | 趋势 |
| :--- | :--- | :--- | :--- |
| 标普500 | 5000.00 | +1.23% | 上升 |
| 纳斯达克 | 16000.00 | -0.50% | 下降 |

---

## 🇨🇳 A 股大盘

| 指数 | 收盘价 | 涨跌幅 | 趋势 |
| :--- | :--- | :--- | :--- |
| 上证指数 | 3000.00 | +0.10% | 震荡 |
| 深证成指 | 9500.00 | — | 休市 |
| 创业板指 | 1900.00 | +2.00% | 上升 |

---

## 💰 另类资产

| 资产 | 收盘价 | 涨跌幅 | 趋势 |
| :--- | :--- | :--- | :--- |
| 黄金ETF | 180.00 | +0.80% | 上升 |
| 比特币 | 60000.00 | -3.00% | 下降 |

---

## 📈 波动率指数

| 指数 | 收盘价 | 涨跌幅 | 状态 |
| :--- | :--- | :--- | :--- |
| VIX | 15.00 | +5.00% | 平静 |
| VXN | 18.00 | -1.00% | 警惕 |
| MOVE | 100.00 | +0.00% | 正常 |
"""
ALERT_MD = """---
type: close
date: 2026-08-29
symbol: VIX
level: ALERT
---

## ⚠️ VIX 告警

- 级别：**ALERT**
- 当前值：25.00
- 昨日收盘：20.50
- 变化率：+22.00%（阈值 ±20.0%）
- 市场状态：异动
- 建议：波动率突破阈值，注意仓位与风险管理。
- 相关报告：2026-08-29.md

---
type: close
date: 2026-08-29
symbol: SH
level: WARN
---

## ⚠️ SH 告警

- 级别：**WARN**
- 当前值：3050.00
- 昨日收盘：3000.00
- 变化率：+1.67%（阈值 ±4.0%）
- 市场状态：异动
- 建议：大盘波动显著，注意风险。
- 相关报告：2026-08-29.md
"""
def _make_png(w=600, h=800):
    """构造最小合法 PNG（验证 _png_dimensions / 尺寸守卫用）。"""

    def chunk(typ, data):
        return (
            _struct.pack(">I", len(data))
            + typ
            + data
            + _struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" for _ in range(h))
    idat = zlib.compress(raw)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _fake_playwright(monkeypatch, png_factory):
    """把 `import imgkit` 解析到假模块；from_string 写入 png_factory() 字节。"""
    fake = types.ModuleType("playwright")
    calls = []

    def from_string(html, path, options=None):
        calls.append(options)
        import os

        os.makedirs(str(__import__("pathlib").Path(path).parent), exist_ok=True)
        __import__("pathlib").Path(path).write_bytes(png_factory())

    # playwright mock already set up
    monkeypatch.setitem(sys.modules, "imgkit", fake)
    return calls


# --------------------------------------------------------------------------- #
# 1-4,10：解析纯函数
# --------------------------------------------------------------------------- #
def test_parse_report_basic(tmp_path):
    md_path = tmp_path / "2026-08-29.md"
    md_path.write_text(SAMPLE_MD, encoding="utf-8")
    data = ir.parse_report(SAMPLE_MD, md_path)
    assert data["date"] == "2026-08-29"
    assert len(data["cards"]) == 10
    for c in data["cards"]:
        assert set(c) >= {"label", "value", "change", "trend_or_status", "sign", "kind"}
    # 涨跌幅符号判定
    assert data["cards"][0]["sign"] == "up"      # +1.23%
    assert data["cards"][1]["sign"] == "down"    # -0.50%
    assert data["cards"][3]["sign"] == "flat"    # —
    # 类别顺序（美股 → A股 → 另类 → 波动率）
    assert data["cards"][0]["kind"] == "us"
    assert data["cards"][9]["kind"] == "vol"
    assert data["interpretation"] is None
    assert data["charts"] == []


def test_parse_report_charts(tmp_path):
    md = (
        SAMPLE_MD
        + "\n---\n\n## 📉 近30日趋势\n\n"
        + "![VIX/VXN/MOVE 近30日趋势](./charts/2026-08-29-trend.png)\n\n"
        + "![missing](./charts/nope.png)\n"
    )
    md_path = tmp_path / "2026-08-29.md"
    md_path.write_text(md, encoding="utf-8")
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "2026-08-29-trend.png").write_bytes(b"fake")
    data = ir.parse_report(md, md_path)
    assert len(data["charts"]) == 2
    present = [c for c in data["charts"] if not c["missing"]]
    missing = [c for c in data["charts"] if c["missing"]]
    assert len(present) == 1 and len(missing) == 1
    assert str(tmp_path / "charts" / "2026-08-29-trend.png") in present[0]["src"]
    assert present[0]["uri"].startswith("file:///")


def test_parse_report_interpretation(tmp_path):
    md = SAMPLE_MD + "\n---\n\n## 🤖 AI 解读\n\n市场情绪偏谨慎，波动率低位。\n"
    data = ir.parse_report(md, tmp_path / "x.md")
    assert data["interpretation"] == "市场情绪偏谨慎，波动率低位。"


def test_parse_report_no_interpretation():
    data = ir.parse_report(SAMPLE_MD, None)
    assert data["interpretation"] is None


def test_parse_report_bad_md_no_raise():
    # 坏 md 降级，绝不抛异常
    assert ir.parse_report("", None)["date"] is None
    assert ir.parse_report("乱码 无结构", None)["cards"] == []


def test_parse_alerts_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ir, "ALERTS_DIR", tmp_path)
    assert ir.parse_alerts("2099-01-01") == []


def test_parse_alerts_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(ir, "ALERTS_DIR", tmp_path)
    (tmp_path / "2026-08-29-close.md").write_text(ALERT_MD, encoding="utf-8")
    alerts = ir.parse_alerts("2026-08-29")
    assert len(alerts) == 2
    vix = alerts[0]
    assert vix["symbol"] == "VIX"
    assert vix["level"] == "ALERT"
    assert vix["change"] == "+22.00"
    assert vix["threshold"] == "20.0"
    assert vix["state"] == "异动"
    assert "波动率突破阈值" in (vix["suggestion"] or "")


def test_parse_alerts_bad_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ir, "ALERTS_DIR", tmp_path)
    (tmp_path / "2026-08-29-close.md").write_text("not a valid alert 💥", encoding="utf-8")
    assert ir.parse_alerts("2026-08-29") == []  # 不崩


def test_png_dimensions(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(_make_png(600, 900))
    assert ir._png_dimensions(p) == (600, 900)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not png")
    with pytest.raises(ValueError):
        ir._png_dimensions(bad)


# --------------------------------------------------------------------------- #
# 5：模板渲染
# --------------------------------------------------------------------------- #
def _sample_render_data():
    return {
        "date": "2026-08-29",
        "cards": [
            {"label": "标普500", "value": "5000.00", "change": "+1.23%", "trend_or_status": "上升", "sign": "up", "kind": "us"},
            {"label": "纳斯达克", "value": "16000.00", "change": "-0.50%", "trend_or_status": "下降", "sign": "down", "kind": "us"},
            {"label": "上证", "value": "3000.00", "change": "—", "trend_or_status": "休市", "sign": "flat", "kind": "a_share"},
        ],
        "charts": [
            {"alt": "t", "src": "x", "uri": "file:///x.png", "missing": True},
            {"alt": "t2", "src": "y", "uri": "file:///y.png", "missing": False},
        ],
        "interpretation": None,
        "alerts": [],
    }


def test_render_html_sections():
    data = _sample_render_data()
    html = ir.render_html(data)
    assert html.count('class="index-card') == 3
    assert "ic-change up" in html
    assert "ic-change down" in html
    assert "趋势图暂缺" in html          # 缺失图表占位
    assert "file:///y.png" in html
    assert '<div class="alert-card' not in html   # 无告警 → 省全区（CSS 中也含 .alert-card，需排除）
    assert "市场告警" not in html
    assert "AI 解读" not in html         # 无解读 → 省全区

    data2 = dict(
        data,
        interpretation="解读内容",
        alerts=[{"symbol": "VIX", "level": "ALERT", "change": "+22.00", "threshold": "20.0", "state": "异动", "suggestion": "注意风险"}],
    )
    html2 = ir.render_html(data2)
    assert "AI 解读" in html2 and "解读内容" in html2
    assert '<div class="alert-card' in html2 and "市场告警" in html2 and "VIX" in html2


# --------------------------------------------------------------------------- #
# 6-9：编排接线（mock imgkit）
# --------------------------------------------------------------------------- #
def test_render_report_image_success(tmp_path, monkeypatch):
    md_path = tmp_path / "2026-08-29.md"
    md_path.write_text(SAMPLE_MD, encoding="utf-8")
    monkeypatch.setattr(ir, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "IMAGES_DIR", tmp_path / "images")
    _fake_playwright(monkeypatch, lambda: _make_png(600, 800))
    out = ir.render_report_image("2026-08-29")
    assert out is not None
    assert out.exists()
    assert out.name == "2026-08-29.png"


def test_render_report_image_no_playwright(tmp_path, monkeypatch):
    md_path = tmp_path / "2026-08-29.md"
    md_path.write_text(SAMPLE_MD, encoding="utf-8")
    monkeypatch.setattr(ir, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setitem(sys.modules, "playwright", None)  # import imgkit → ImportError
    assert ir.render_report_image("2026-08-29") is None


def test_render_report_image_timeout(tmp_path, monkeypatch):
    md_path = tmp_path / "2026-08-29.md"
    md_path.write_text(SAMPLE_MD, encoding="utf-8")
    monkeypatch.setattr(ir, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(ir, "RENDER_TIMEOUT", 0.2)
    fake = types.ModuleType("playwright")

    def from_string(html, path, options=None):
        time.sleep(5)  # 阻塞超过限时

    # playwright mock already set up
    monkeypatch.setitem(sys.modules, "imgkit", fake)
    assert ir.render_report_image("2026-08-29") is None


def test_render_report_image_size_guard(tmp_path, monkeypatch):
    md_path = tmp_path / "2026-08-29.md"
    md_path.write_text(SAMPLE_MD, encoding="utf-8")
    monkeypatch.setattr(ir, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "IMAGES_DIR", tmp_path / "images")
    calls = []

    def factory():
        calls.append(1)
        if len(calls) == 1:
            return b"\x00" * (900 * 1024)  # 首次 >800KB
        return _make_png(600, 800)         # 重试后小图

    _fake_playwright(monkeypatch, factory)
    out = ir.render_report_image("2026-08-29")
    assert out is not None
    assert len(calls) == 2                  # 触发 zoom 重试
    assert out.stat().st_size <= ir.MAX_IMAGE_BYTES


# --------------------------------------------------------------------------- #
# 11-12：入口容错
# --------------------------------------------------------------------------- #
def test_daily_report_image_failure_exit_zero(monkeypatch, tmp_path):
    import daily_report as dr

    monkeypatch.setattr(dr, "fetch_all", lambda *a, **k: (
        {s: 100.0 for s in ["GSPC", "IXIC", "SH", "SZ", "CYB", "VIX", "VXN", "MOVE", "GLD", "BTC"]}, {}))
    monkeypatch.setattr(dr, "fetch_sector_heat", lambda: ([], []))
    monkeypatch.setattr(dr, "fetch_us_sector_heat", lambda: ([], []))
    monkeypatch.setattr(dr, "load_last_values", lambda: {})
    monkeypatch.setattr(dr, "compute_changes", lambda *a, **k: {})
    monkeypatch.setattr(dr, "load_history", lambda: [])
    monkeypatch.setattr(dr, "compute_correlation", lambda *a, **k: [])
    monkeypatch.setattr(dr, "build_statuses", lambda *a, **k: {})
    monkeypatch.setattr(dr, "build_summary", lambda *a, **k: "summary")
    monkeypatch.setattr(dr, "render_trend_chart", lambda *a, **k: None)
    monkeypatch.setattr(dr, "render_market_trend_chart", lambda *a, **k: None)
    monkeypatch.setattr(dr, "render_report", lambda *a, **k: "# report")
    monkeypatch.setattr(dr, "save_report", lambda *a, **k: tmp_path / "r.md")
    monkeypatch.setattr(dr, "run_alert_checks", lambda *a, **k: [])
    monkeypatch.setattr(dr, "append_history", lambda *a, **k: None)
    monkeypatch.setattr(dr, "save_last_values", lambda *a, **k: None)
    monkeypatch.setattr(dr, "generate_context", lambda *a, **k: tmp_path / "c.json")

    def boom(date):
        raise RuntimeError("boom")

    monkeypatch.setattr(dr, "render_report_image", boom)
    assert dr.main() == 0


def test_render_script_missing_md_exit_zero(monkeypatch, tmp_path):
    from scripts import render_report_image as rri

    monkeypatch.setattr(ir, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "IMAGES_DIR", tmp_path / "images")
    assert rri.main(["--date", "2099-01-01"]) == 0


def test_render_script_present_md_success(tmp_path, monkeypatch):
    from scripts import render_report_image as rri

    (tmp_path / "2026-08-29.md").write_text(SAMPLE_MD, encoding="utf-8")
    monkeypatch.setattr(ir, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "ALERTS_DIR", tmp_path)
    monkeypatch.setattr(ir, "IMAGES_DIR", tmp_path / "images")
    _fake_playwright(monkeypatch, lambda: _make_png(600, 800))
    assert rri.main(["--date", "2026-08-29"]) == 0
    assert (tmp_path / "images" / "2026-08-29.png").exists()
