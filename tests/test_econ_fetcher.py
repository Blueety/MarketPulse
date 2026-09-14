"""经济数据源（BLS）单测：纯函数（同比 / 方向 / 四象限）+ 降级路径。

**全程不联网**：一律 monkeypatch `econ_fetcher._SESSION.post` 返回夹具
（与 tests/test_us_sector.py 的 stub 风格一致）。真实 BLS 只由验收命令单独跑一次
（BLS 无 Key 限额 25 次/日，别把网络调用放进测试）。
"""
from datetime import date

import pytest

from src import econ_fetcher as ef


# ---- 夹具 ----

class _Resp:
    """requests.Response 的最小替身（只用到 raise_for_status / json）。"""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _months(end_year=2026, end_month=8, n=24):
    """n 个连续月份键（升序），末尾为 `end_year-end_month`。"""
    out, y, m = [], end_year, end_month
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def _series(values, end_year=2026, end_month=8):
    """[值] → [(YYYY-MM, 值)]（月份连续，末尾为 end_month）。"""
    return list(zip(_months(end_year, end_month, len(values)), values))


def _level_ramp(n=24, r0=0.001, dr=0.0001, base=100.0):
    """构造水平序列：月度增速从 r0 起每月叠加 dr → dr>0 同比单调上行，dr<0 同比下行。"""
    out, val = [], base
    for k in range(1, n + 1):
        val *= 1 + r0 + dr * k
        out.append(round(val, 4))
    return out


def _econ_raw(infl="up", growth="up"):
    """造一份 raw：infl ∈ {up,down} 控 CPI/PPI 同比方向；growth 控就业方向。"""
    cpi = _level_ramp(dr=0.0001) if infl == "up" else _level_ramp(r0=0.006, dr=-0.0004)
    payrolls = [150000 + 200 * i for i in range(24)] if growth == "up" \
        else [155000 - 200 * i for i in range(24)]
    unemp = [4.6 - 0.03 * i for i in range(24)] if growth == "up" \
        else [3.8 + 0.03 * i for i in range(24)]
    return {"cpi": _series(cpi), "ppi": _series(cpi),
            "payrolls": _series(payrolls), "unemployment": _series(unemp)}


def _bls_ok(series_map):
    """BLS 成功响应夹具：`{sid: [(year, period, value), ...]}`。"""
    return {
        "status": "REQUEST_SUCCEEDED",
        "Results": {"series": [
            {"seriesID": sid,
             "data": [{"year": str(y), "period": p, "value": v} for (y, p, v) in rows]}
            for sid, rows in series_map.items()
        ]},
    }


def _patch_post(monkeypatch, payload=None, exc=None):
    """把 `_SESSION.post` 换成替身，返回调用记录；`exc` 非空则抛它（模拟超时/网络错）。"""
    calls = []

    def _post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if exc:
            raise exc
        return _Resp(payload)

    monkeypatch.setattr(ef._SESSION, "post", _post)
    return calls


# ---- 同比 ----

class TestYoy:
    def test_normal(self):
        # 去年同月 324.24 → 今月 334.98 ≈ +3.31%
        assert ef._yoy(324.24, 334.98) == pytest.approx(3.31, abs=0.01)

    def test_zero_base_no_zero_division(self):
        assert ef._yoy(0.0, 100.0) is None

    def test_missing_base(self):
        assert ef._yoy(None, 100.0) is None


class TestYoyAt:
    """`_yoy_at`：**按月份键**找去年同月（BLS 有真实缺月，按位置取会静默算错基准）。"""

    def test_insufficient_months(self):
        rows = _series(_level_ramp(12))
        assert ef._yoy_at(rows, len(rows) - 1) is None

    def test_middle_gap_still_computes(self):
        """实测场景：CPI-U / 失业率都缺 `2025-10` → 中间缺月**不影响**同比。"""
        rows = [r for r in _series(_level_ramp(25)) if r[0] != "2025-10"]
        by_ym = dict(rows)
        yoy = ef._yoy_at(rows, len(rows) - 1)
        assert yoy is not None
        assert yoy == round((by_ym["2026-08"] / by_ym["2025-08"] - 1) * 100, 2)

    def test_base_month_absent_returns_none(self):
        rows = [r for r in _series(_level_ramp(25)) if r[0] != "2025-08"]
        assert ef._yoy_at(rows, len(rows) - 1) is None

    def test_end_out_of_range(self):
        rows = _series(_level_ramp(14))
        assert ef._yoy_at(rows, 99) is None


# ---- 方向 ----

class TestDirection:
    def test_up(self):
        assert ef._direction(1.10, 1.00) == "up"

    def test_down(self):
        assert ef._direction(0.90, 1.00) == "down"

    def test_flat_within_eps(self):
        assert ef._direction(1.02, 1.00) == "flat"

    def test_none_input(self):
        assert ef._direction(None, 1.00) is None


# ---- 轴与四象限 ----

class TestAxis:
    def test_inflation_flat_falls_back_to_ppi(self):
        assert ef._infl_axis("flat", "down") == "down"

    def test_inflation_both_flat_defaults_up(self):
        assert ef._infl_axis("flat", "flat") == "up"

    def test_inflation_no_data(self):
        assert ef._infl_axis(None, None) is None

    def test_growth_payroll_flat_uses_unemployment(self):
        g = ef._growth_axis([100.0] * 8, [4.0, 4.1, 4.2, 4.3])
        assert g["payroll_dir"] == "flat" and g["unemployment_dir"] == "up"
        assert g["axis"] == "contracting"

    def test_growth_no_data(self):
        assert ef._growth_axis([], [])["axis"] is None


class TestQuadrants:
    @pytest.mark.parametrize("infl,growth,expect", [
        ("up", "up", ("reflation", "再通胀")),
        ("down", "up", ("goldilocks", "复苏")),
        ("up", "down", ("stagflation", "滞胀")),
        ("down", "down", ("deflation", "通缩衰退")),
    ])
    def test_four_combinations(self, infl, growth, expect):
        p = ef.build_econ_payload(_econ_raw(infl, growth))
        assert p["inflation_axis"] == infl
        assert p["growth_axis"] == ("expanding" if growth == "up" else "contracting")
        assert (p["quadrant"], p["quadrant_label"]) == expect
        # 自洽：象限必须能由两个轴查表反推
        assert ef._QUADRANTS[(p["inflation_axis"], p["growth_axis"])] == expect


# ---- 拉取降级 ----

class TestFetchEconSeries:
    def test_success_maps_cleans_and_sorts(self, monkeypatch):
        calls = _patch_post(monkeypatch, _bls_ok({
            "CUUR0000SA0": [("2026", "M08", "334.980"), ("2026", "M07", "334.100"),
                            ("2026", "M13", "330.000"), ("2026", "M06", "-")],
        }))
        out = ef.fetch_econ_series()
        assert list(out) == ["cpi"]
        # M13（年度均值）与 value="-"（不可用）都被过滤，且输出升序
        assert out["cpi"] == [("2026-07", 334.1), ("2026-08", 334.98)]
        # 一次 POST 带齐 4 个序列 ID；年份窗口拉到 3 年前（算同比需 ≥13 个月）
        assert len(calls) == 1 and calls[0]["url"] == ef.BLS_URL
        assert sorted(calls[0]["json"]["seriesid"]) == sorted(ef._SID_TO_KEY)
        assert calls[0]["json"]["startyear"] == str(date.today().year - ef._LOOKBACK_YEARS)

    def test_status_not_succeeded_returns_empty(self, monkeypatch):
        _patch_post(monkeypatch, {"status": "REQUEST_NOT_PROCESSED", "message": "daily limit"})
        assert ef.fetch_econ_series() == {}

    def test_timeout_returns_empty(self, monkeypatch):
        _patch_post(monkeypatch, exc=TimeoutError("timed out"))
        assert ef.fetch_econ_series() == {}

    def test_http_error_returns_empty(self, monkeypatch):
        monkeypatch.setattr(ef._SESSION, "post", lambda *a, **k: _Resp({}, status_code=503))
        assert ef.fetch_econ_series() == {}

    def test_non_json_returns_empty(self, monkeypatch):
        class _Bad:
            def raise_for_status(self):
                return None

            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(ef._SESSION, "post", lambda *a, **k: _Bad())
        assert ef.fetch_econ_series() == {}


# ---- 统一结构 ----

class TestBuildEconPayload:
    def test_empty_raw_no_crash(self):
        p = ef.build_econ_payload({})
        assert p["as_of"] is None
        assert p["inflation_axis"] is None and p["growth_axis"] is None
        assert p["quadrant"] is None and p["quadrant_label"] is None
        assert len(p["series"]) == 4
        for s in p["series"]:
            assert s["latest"] is None and s["yoy"] is None
            assert s["direction"] is None and s["history"] == []

    def test_none_raw_no_crash(self):
        assert ef.build_econ_payload(None)["as_of"] is None

    def test_as_of_is_data_month(self):
        p = ef.build_econ_payload(_econ_raw())
        assert p["as_of"] == "2026-08"          # 数据月份（fixture 的末尾月），非抓取时间
        assert p["fetched_at"] > "2026-08"      # 抓取时间是 ISO 时间戳

    def test_four_series_derived_fields(self):
        p = ef.build_econ_payload(_econ_raw())
        assert [s["key"] for s in p["series"]] == ["cpi", "ppi", "unemployment", "payrolls"]
        for s in p["series"]:
            assert s["latest"] is not None and s["yoy"] is not None
            assert s["prev_yoy"] is not None and s["direction"] is not None
            assert s["date"] == "2026-08" and len(s["history"]) == 24
        assert p["basis"]["growth"] and "非 PMI" in p["basis"]["growth"]

    def test_series_date_is_data_month(self):
        p = ef.build_econ_payload({"cpi": _series(_level_ramp(14))})
        cpi = next(s for s in p["series"] if s["key"] == "cpi")
        assert cpi["date"] == "2026-08" and cpi["yoy"] is not None

    def test_middle_gap_keeps_yoy(self):
        """实测缺口（BLS 缺 `2025-10`）不再让同比变 None —— 基准按月份键取。"""
        rows = [r for r in _series(_level_ramp(25)) if r[0] != "2025-10"]
        p = ef.build_econ_payload({"cpi": rows})
        cpi = next(s for s in p["series"] if s["key"] == "cpi")
        assert cpi["yoy"] is not None and cpi["direction"] is not None

    def test_missing_base_month_yields_none(self):
        rows = [r for r in _series(_level_ramp(25)) if r[0] != "2025-08"]
        p = ef.build_econ_payload({"cpi": rows})
        assert next(s for s in p["series"] if s["key"] == "cpi")["yoy"] is None

    def test_twelve_months_not_enough(self):
        p = ef.build_econ_payload({"cpi": _series(_level_ramp(12))})
        assert next(s for s in p["series"] if s["key"] == "cpi")["yoy"] is None

    def test_history_capped_at_24(self):
        p = ef.build_econ_payload({"cpi": _series(_level_ramp(36))})
        cpi = next(s for s in p["series"] if s["key"] == "cpi")
        assert len(cpi["history"]) == ef._HISTORY_MONTHS == 24


class TestEndToEndOffline:
    def test_fetch_then_build(self, monkeypatch):
        """fetch → build 全链路（离线替身）：4 序列 + as_of + 四象限自洽。"""
        raw = _econ_raw("up", "up")
        _patch_post(monkeypatch, _bls_ok({
            ef.ECON_SERIES[k]["sid"]:
                [(int(ym[:4]), f"M{ym[5:]}", str(v)) for ym, v in rows]
            for k, rows in raw.items()
        }))
        p = ef.build_econ_payload(ef.fetch_econ_series())
        assert p["as_of"] == "2026-08"
        assert len(p["series"]) == 4
        assert all(s["latest"] is not None and s["yoy"] is not None and s["direction"]
                   for s in p["series"])
        assert (p["quadrant"], p["quadrant_label"]) == ("reflation", "再通胀")
