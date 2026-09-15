"""中国宏观（src/cn_econ_fetcher.py）单测 —— **不联网**，全部用 mock DataFrame / mock akshare。

对照 `tasks/2026-09-14-cn-macro-page/plan.md` §Step 10 的 12 条用例。重点钉住三个纠正性
结论（C1 房价仅 2 城 / C2 增长轴取 PMI 水平 / 排序口径不统一）与「部分失败仍缓存」的
端点语义 —— 这些是最容易被后人"顺手改坏"且**改坏后不报错**的地方。
"""
import sys

import pandas as pd
import pytest

from src import cn_econ_fetcher as cn

# ---- mock AkShare ----


class FakeAk:
    """按函数名返回固定 DataFrame 的假 akshare；未登记的函数抛 AttributeError（走降级）。"""

    def __init__(self, mapping):
        self._m = mapping

    def __getattr__(self, name):
        if name in self._m:
            return self._m[name]
        raise AttributeError(f"no such ak function: {name}")


@pytest.fixture
def fake_ak(monkeypatch):
    """安装假 akshare（`_fetch_one` 内部 `import akshare as ak` 会命中 sys.modules）。"""

    def _install(mapping):
        monkeypatch.setitem(sys.modules, "akshare", FakeAk(mapping))
        return mapping

    return _install


def df_of(rows, cols):
    return pd.DataFrame(rows, columns=cols)


# Step 10-1：_parse_ym 三种格式
def test_parse_ym_formats():
    assert cn._parse_ym("2026年08月份") == "2026-08"
    assert cn._parse_ym("202607") == "2026-07"
    assert cn._parse_ym("2026-08-01") == "2026-08"
    assert cn._parse_ym("2026年第1-2季度") == "2026Q2"       # ★ 取区间较大季度号
    assert cn._parse_ym("2026年第1季度") == "2026Q1"
    assert cn._parse_ym("abc") is None
    assert cn._parse_ym(None) is None
    assert cn._parse_ym("2026年13月份") is None


# Step 10-2：缺列守卫（AkShare 升级改列名 → 降级为空，不抛）
def test_require_cols_missing_returns_empty(fake_ak):
    fake_ak({"macro_china_cpi": lambda: df_of([["2026年08月份", 0.8]], ["月份", "全国-同比（改过名）"])})
    assert cn._fetch_one("cpi") == []
    assert cn._require_cols(df_of([[1]], ["a"]), ["a", "b"]) is False
    assert cn._require_cols(df_of([[1]], ["a"]), ["a"]) is True


# Step 10-3：unemployment 长表过滤（4 个 item 里只取 1 个，且 item 带尾随空格）
def test_unemployment_long_table_filter(fake_ak):
    rows = [
        ["202607", "全国城镇调查失业率 ", 5.2],
        ["202607", "全国城镇本地户籍劳动力失业率 ", 5.2],
        ["202607", "全国城镇外来户籍劳动力失业率 ", 5.2],
        ["202606", "全国城镇调查失业率 ", 5.0],
    ]
    fake_ak({"macro_china_urban_unemployment": lambda: df_of(rows, ["date", "item", "value"])})
    out = cn._fetch_one("unemployment")
    assert [r[0] for r in out] == ["2026-06", "2026-07"]      # 已按周期升序重排
    assert [r[1] for r in out] == [5.0, 5.2]


# Step 10-4：house_price 双城拆分（**2 城，不是 70 城**；主列是「上年同月=100」指数）
def test_house_price_split_two_cities(fake_ak):
    rows = [
        ["2026-07-01", "北京", 97.7, 95.5],
        ["2026-07-01", "上海", 103.0, 98.0],
        ["2026-06-01", "北京", 98.0, 96.0],
        ["2026-06-01", "上海", 102.5, 98.5],
    ]
    fake_ak({"macro_china_new_house_price": lambda: df_of(
        rows, ["日期", "城市", "新建商品住宅价格指数-同比", "二手住宅价格指数-同比"])})
    out = cn._fetch_one("house_price")
    assert isinstance(out, dict)
    # 注意排序：中文按码点，「上海」<「北京」→ 这里用集合比较，避免写成字面顺序
    assert set(out.keys()) == {"北京", "上海"}                    # ★ 只有 2 城
    assert out["北京"][-1] == ("2026-07", pytest.approx(-2.3))    # 97.7 → -2.3%
    assert out["上海"][-1] == ("2026-07", pytest.approx(3.0))     # 103.0 → +3.0%


# Step 10-5：credit 主用「累计-同比增长」（`当月` 存在异常负值）
def test_credit_uses_cumulative_yoy(fake_ak):
    rows = [["2026年08月份", -5896.0, -91.2, -20.9241], ["2026年07月份", 500.0, 3.0, -18.5]]
    fake_ak({"macro_china_new_financial_credit": lambda: df_of(
        rows, ["月份", "当月", "当月-同比增长", "累计-同比增长"])})
    out = cn._fetch_one("credit")
    assert out[-1] == ("2026-08", pytest.approx(-20.9241))        # 累计同比，不是 -91.2 / -5896


# Step 10-6：增长轴取 PMI **水平**（与 50 比较），不是同比方向
def test_growth_axis_uses_pmi_level_not_direction():
    # 水平 49.4 < 50 → contracting；但"同比方向"是 up（49.0 → 49.8）——若按方向会得出 expanding
    rows = [("2026-06", 49.4), ("2026-07", 49.0), ("2026-08", 49.8)]
    g = cn._growth_axis_cn(rows, [])
    assert g["pmi_axis"] == "contracting"
    assert g["pmi_3m"] == pytest.approx(49.4)
    assert cn._direction(rows[-1][1], rows[-2][1]) == "up"        # 反证：方向口径会给出相反结论

    up = cn._growth_axis_cn([("2026-08", 50.1)], [])
    assert up["pmi_axis"] == "expanding"

    empty = cn._growth_axis_cn([], [])
    assert empty["pmi_axis"] is None and empty["conflict"] is False


# Step 10-7：gdp 交叉校验（与 PMI 结论冲突时**如实上报**，不静默取一个）
def test_growth_axis_conflict_reported():
    pmi = [("2026-08", 50.5)]                     # 扩张
    gdp_up = [("2026Q1", 4.5), ("2026Q2", 5.0)]   # 同比上行 → expanding
    gdp_dn = [("2026Q1", 5.4), ("2026Q2", 4.7)]   # 同比下行 → contracting
    assert cn._growth_axis_cn(pmi, gdp_up)["conflict"] is False
    conflict = cn._growth_axis_cn(pmi, gdp_dn)
    assert conflict["conflict"] is True
    assert conflict["gdp_axis"] == "contracting" and conflict["pmi_axis"] == "expanding"
    # 增长轴本身仍以 PMI 水平为准（交叉校验只上报，不改写结论）
    assert conflict["pmi_axis"] == "expanding"


# Step 10-8：同比**按键找去年同月**（真实数据会缺期，禁止"取第 13 个"）
def test_yoy_looks_up_same_month_last_year():
    rows = [("2025-08", 100.0), ("2026-07", 110.0), ("2026-08", 121.0)]
    assert cn._yoy_at(rows, 2) == pytest.approx(21.0)      # 基准 = 2025-08（按键找到）
    # 去掉 2025-08 后，第 13 个位置正好是 2026-07 → 按位置取会静默算错；按键取应为 None
    assert cn._yoy_at(rows[1:], 1) is None
    # 日频：匹配去年同月的**最后一个**交易日
    daily = [("2025-09-30", 2.0), ("2026-09-13", 1.0), ("2026-09-14", 1.5)]
    assert cn._yoy_at(daily, 2) == pytest.approx(-25.0)


# Step 10-11：bond_10y 空结果守卫（上游区间敏感，1y 窗口返回 0 行）
def test_bond_10y_empty_result_guard(fake_ak):
    # ⚠️ mock 必须接受 **kwargs（bond_10y 走 AUTO_6M，会传 start_date/end_date）
    fake_ak({"bond_china_yield": lambda **kw: df_of([], ["曲线名称", "日期", "10年"])})
    assert cn._fetch_one("bond_10y") == []

    # 只取「中债国债收益率曲线」，其余两条曲线必须被过滤掉
    rows = [
        ["中债国债收益率曲线", "2026-09-14", 1.6888],
        ["中债商业银行普通债收益率曲线(AAA)", "2026-09-14", 1.9516],
    ]
    fake_ak({"bond_china_yield": lambda **kw: df_of(rows, ["曲线名称", "日期", "10年"])})
    out = cn._fetch_one("bond_10y")
    assert out == [("2026-09-14", pytest.approx(1.6888))]


# Step 10-12：零写盘（Web 只读边界；任何 open(写) 都视为违约）
def test_no_file_writes(fake_ak, monkeypatch):
    import builtins

    fake_ak({
        "macro_china_cpi": lambda: df_of([["2026年08月份", 0.8]], ["月份", "全国-同比增长"]),
        "macro_china_pmi": lambda: df_of([["2026年08月份", 49.8]], ["月份", "制造业-指数"]),
    })
    real_open = builtins.open
    offenders = []

    def guard(file, mode="r", *a, **kw):
        if any(m in str(mode) for m in ("w", "a", "x", "+")):
            offenders.append(str(file))
            raise AssertionError(f"cn_econ_fetcher 不得写盘: {file}")
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr(builtins, "open", guard)
    raw, failed = cn.fetch_cn_econ_raw(["cpi", "pmi"])
    payload = cn.build_cn_econ_payload(raw, failed)
    assert payload["as_of"] == "2026-08"
    assert not offenders


# ---- 端点语义（部分失败仍缓存 / 全失败不缓存）----
# ⚠️ 与 BLS `/api/econ` 的**有意差异**：中国版 13 个接口相互独立，
#    "1 个失败就整份不缓存"会让每次请求都重打 13 个接口（用户等 10s+）。


@pytest.fixture
def cn_client(monkeypatch):
    from fastapi.testclient import TestClient

    import web.app

    # 缓存是模块级状态，跨测试必须清空（与 test_web.py 的 _reset_watch_cache 同纪律）
    web.app._cn_econ_cache["ts"].clear()
    web.app._cn_econ_cache["payload"].clear()
    web.app._cn_econ_raw.clear()
    web.app._cn_econ_raw_ts.clear()
    return TestClient(web.app.app), web.app


def _rows(pairs):
    return list(pairs)


# Step 10-9：13 个里部分失败 → payload 仍被缓存 + failed 如实列出
def test_partial_failure_still_cached(cn_client, monkeypatch):
    client, app = cn_client
    calls = {"n": 0}

    def fake_fetch(keys=None, timeout=None):
        calls["n"] += 1
        raw = {}
        for k in (keys or list(cn.CN_ECON_SERIES)):
            raw[k] = [("2026-08", 1.0)] if k not in ("cpi", "ppi", "pmi") else []
        return raw, ["cpi", "ppi", "pmi"]

    monkeypatch.setattr(app, "fetch_cn_econ_raw", fake_fetch)
    first = client.get("/api/econ/cn").json()
    assert sorted(first["failed"]) == ["cpi", "pmi", "ppi"]      # 按字母序：cpi < pmi < ppi
    assert first["as_of"] == "2026-08"           # 其余序列成功 → as_of 非空 → **照常缓存**
    second = client.get("/api/econ/cn").json()
    assert calls["n"] == 1                        # 第二次命中缓存，未再打上游
    assert second["failed"] == first["failed"]


# Step 10-10：全部失败（as_of 为空）→ 不写缓存（否则一次抖动锁死 6 小时）
def test_total_failure_not_cached(cn_client, monkeypatch):
    client, app = cn_client
    calls = {"n": 0}

    def fake_fetch(keys=None, timeout=None):
        calls["n"] += 1
        keys = keys or list(cn.CN_ECON_SERIES)
        return {k: [] for k in keys}, list(keys)

    monkeypatch.setattr(app, "fetch_cn_econ_raw", fake_fetch)
    first = client.get("/api/econ/cn").json()
    assert first["as_of"] is None
    assert len(first["failed"]) == len(cn.CN_ECON_SERIES)
    client.get("/api/econ/cn")
    assert calls["n"] == 2                        # 未缓存 → 每次都重试（不被锁死）


# 分组端点：只返回该组 series；四象限在累积 raw 足够时由后到的组补上
def test_group_endpoint_scope(cn_client, monkeypatch):
    client, app = cn_client
    # ⚠️ 必须给 2 个点：方向由「最新 vs 上期」得出，单点序列没有方向 → 算不出四象限
    monkeypatch.setattr(app, "fetch_cn_econ_raw", lambda keys=None, timeout=None: (
        {k: [("2026-07", 0.5), ("2026-08", 0.8)] for k in (keys or [])}, []))
    price = client.get("/api/econ/cn?group=price").json()
    assert sorted(s["key"] for s in price["series"]) == ["cpi", "ppi"]
    growth = client.get("/api/econ/cn?group=growth").json()
    assert sorted(s["key"] for s in growth["series"]) == ["gdp", "pmi"]
    # 累积 raw 已含 cpi/ppi → 该组响应能算出四象限
    assert growth["quadrant"] is not None
    # 非法组名由 FastAPI 直接 422（与 days 越界同纪律）
    assert client.get("/api/econ/cn?group=nope").status_code == 422


# 增长轴口径必须写进 basis（前端标注与断言 #4 都依赖它）
def test_basis_states_pmi_level_rule(cn_client, monkeypatch):
    client, app = cn_client
    monkeypatch.setattr(app, "fetch_cn_econ_raw", lambda keys=None, timeout=None: (
        {k: [("2026-08", 1.0)] for k in (keys or [])}, []))
    payload = client.get("/api/econ/cn").json()
    assert "PMI 与 50 荣枯线比较" in payload["basis"]["growth"]
    assert "水平口径" in payload["basis"]["growth"]
    # C1：文案里不得出现"70 城"（verify_ui 会断言房价模块不含该字面量）
    assert "70 城" not in payload["basis"]["price_note"]
