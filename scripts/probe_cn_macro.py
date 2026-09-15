"""中国宏观数据源探针（AkShare）—— 可重跑的「静默停更」回归工具。

动机：本项目**最大的历史陷阱是数据源静默停更** —— `macro_usa_*` 停更一年才被发现、
`us_sector_heat` 静默降级成空。`/macro/cn` 引入 13 个 AkShare 接口 = 13 个新的停更
风险点，必须有可重跑的探针把「当前可用性」固化下来。

行为：
- 逐个调用在册接口，输出「可用性 / 最新数据月份 / 耗时 / 行数 / 列名」表；
- 退出码非 0 若：任一**在册可用**接口变为不可用，或其最新月份落后 > `max_lag` 个月；
- `--include-rejected` 附带跑「已否决清单」（东财报告族，列名 `商品/日期/今值/预测值/前值`），
  它们**预期就是坏的**，仅作对照、不参与退出码（防止有人误把它们"重新启用"）。

约束（勿破坏）：
- **单接口 daemon 线程限时**（AkShare 内部 requests 无 timeout，网络异常可无限挂起）；
- **console 只打 ASCII + 中文**（Windows 控制台是 GBK，emoji 会 `UnicodeEncodeError`
  让脚本中途崩掉，前面的 PASS 看起来像"跑完了"）；
- **只读、零写盘**：不碰 `data/` `context/`；JSON 报告落 `%TEMP%`（不进仓库）。

用法：
    venv/Scripts/python scripts/probe_cn_macro.py
    venv/Scripts/python scripts/probe_cn_macro.py --include-rejected
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import date

log = logging.getLogger("probe_cn_macro")

_PER_CALL_TIMEOUT = 25  # 秒；单接口 daemon 线程限时（AkShare 无 timeout 参数）

# 在册可用（退出码的判据来源）：与 src/cn_econ_fetcher.CN_ECON_SERIES 一一对应。
#   time_col / main_col：取"最新数据月份"用的列（缺列视为不可用）。
#   max_lag：允许的最新月份落后月数（**季度 GDP 给 6**，季度数据天然滞后于月历）。
PROBES_OK: list[dict] = [
    {"key": "cpi", "fn": "macro_china_cpi", "time_col": "月份", "main_col": "全国-同比增长"},
    {"key": "ppi", "fn": "macro_china_ppi", "time_col": "月份", "main_col": "当月同比增长"},
    {"key": "pmi", "fn": "macro_china_pmi", "time_col": "月份", "main_col": "制造业-指数"},
    {"key": "gdp", "fn": "macro_china_gdp", "time_col": "季度", "main_col": "国内生产总值-同比增长",
     "max_lag": 6},
    {"key": "m2", "fn": "macro_china_money_supply", "time_col": "月份", "main_col": "货币和准货币(M2)-同比增长"},
    {"key": "social_financing", "fn": "macro_china_bank_financing", "time_col": "日期", "main_col": "最新值"},
    {"key": "credit", "fn": "macro_china_new_financial_credit", "time_col": "月份", "main_col": "累计-同比增长"},
    {"key": "unemployment", "fn": "macro_china_urban_unemployment", "time_col": "date", "main_col": "value"},
    {"key": "retail", "fn": "macro_china_consumer_goods_retail", "time_col": "月份", "main_col": "同比增长"},
    {"key": "house_price", "fn": "macro_china_new_house_price", "time_col": "日期",
     "main_col": "新建商品住宅价格指数-同比"},
    {"key": "lpr", "fn": "macro_china_lpr", "time_col": "TRADE_DATE", "main_col": "LPR1Y"},
    {"key": "shibor", "fn": "macro_china_shibor_all", "time_col": "日期", "main_col": "O/N-定价"},
    # ⚠️ 区间敏感（R2）：6 个月窗口正常（411 行），**1 年窗口返回 0 行**。
    #    这是上游行为不是 bug —— 下方 REJECTED 里的 `bond_china_yield_1y` 把它固化为"已知行为"。
    {"key": "bond_10y", "fn": "bond_china_yield", "kwargs": "AUTO_6M", "time_col": "日期", "main_col": "10年"},
]

# 已否决清单（仅对照，不参与退出码）：列名 `商品/日期/今值/预测值/前值` = 东财报告族，
# 实测停更在 2025-09 且耗时 5~20s+。⚠️ 不要因为"探针里它坏了"去修它 —— 它就应该被否决。
PROBES_REJECTED: list[dict] = [
    {"key": "pmi_yearly", "fn": "macro_china_pmi_yearly", "note": "东财报告族"},
    {"key": "non_man_pmi", "fn": "macro_china_non_man_pmi", "note": "东财报告族"},
    {"key": "cx_pmi_yearly", "fn": "macro_china_cx_pmi_yearly", "note": "东财报告族"},
    {"key": "industrial_production_yoy", "fn": "macro_china_industrial_production_yoy", "note": "东财报告族"},
    {"key": "m2_yearly", "fn": "macro_china_m2_yearly", "note": "东财报告族"},
    {"key": "gdp_yearly", "fn": "macro_china_gdp_yearly", "note": "东财报告族"},
    {"key": "fx_reserves_yearly", "fn": "macro_china_fx_reserves_yearly", "note": "东财报告族"},
    # 已知行为（R2）：1 年窗口返回 0 行 → 生产侧固定用 6 个月窗口。
    {"key": "bond_china_yield_1y", "fn": "bond_china_yield", "kwargs": "AUTO_1Y", "note": "区间敏感：1y=0 行"},
]


def _months_ago(n: int) -> date:
    """今天往前 n 个月（只用于给 `bond_china_yield` 算 start_date）。"""
    today = date.today()
    idx = today.year * 12 + (today.month - 1) - n
    return date(idx // 12, idx % 12 + 1, 1)


def _resolve_kwargs(spec: dict) -> dict:
    """`kwargs` 支持哨兵 `AUTO_6M` / `AUTO_1Y`（按调用当天算日期窗口）。"""
    raw = spec.get("kwargs")
    if raw == "AUTO_6M":
        return {"start_date": _months_ago(6).strftime("%Y%m%d"), "end_date": date.today().strftime("%Y%m%d")}
    if raw == "AUTO_1Y":
        return {"start_date": _months_ago(12).strftime("%Y%m%d"), "end_date": date.today().strftime("%Y%m%d")}
    return dict(raw or {})


def _call_with_timeout(fn_name: str, kwargs: dict, timeout: int = _PER_CALL_TIMEOUT):
    """在 daemon 线程里调 AkShare（**无 SIGALRM 的 Windows 模式**），超时返回 `(None, "timeout")`。

    AkShare 内部 `requests.get` 大多不传 timeout，网络异常可无限挂起 → 必须限时；
    超时后线程继续在后台，进程退出即终止（与 `fetch_sector_heat` 同范式）。
    """
    import akshare as ak

    box: dict = {}

    def worker() -> None:
        try:
            box["df"] = getattr(ak, fn_name)(**kwargs)
        except Exception as exc:  # noqa: BLE001 —— 探针要如实记录任何失败
            box["err"] = exc

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    if "df" in box:
        return box["df"], None
    if "err" in box:
        return None, f"{type(box['err']).__name__}: {box['err']}"
    return None, f"timeout>{timeout}s"


def _month_of(text) -> str | None:
    """从各种日期文本里提取 `YYYY-MM`（**季度按 Q×3 折算月份**，否则季度 GDP 必然误报滞后）。

    - `"2026年08月份"` → `"2026-08"`；`"2026-08-20"` → `"2026-08"`；
    - `"2026年第1-2季度"` → 取季度号 **2** → `"2026-06"`（Q2 覆盖到 6 月）；
      若按第一个数字算成 `2026-01`，季度数据会**永远**触发滞后告警（假红）。
    """
    if text is None:
        return None
    s = str(text).strip()
    if "季度" in s:
        m = re.search(r"(\d{4})\D*第?(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s*季度", s)
        if not m:
            return None
        quarter = int(m.group(3) or m.group(2))
        return f"{m.group(1)}-{quarter * 3:02d}"
    m = re.search(r"(\d{4})\D{0,3}(\d{1,2})", s)
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}"


def _lag_months(ym: str | None, today: date) -> int | None:
    if not ym:
        return None
    try:
        y, m = (int(x) for x in ym.split("-"))
    except ValueError:
        return None
    return (today.year * 12 + today.month - 1) - (y * 12 + m - 1)


def probe_one(spec: dict, today: date) -> dict:
    """跑单个接口，返回结构化结果（**不抛**）。"""
    fn = spec["fn"]
    kwargs = _resolve_kwargs(spec)
    t0 = time.time()
    df, err = _call_with_timeout(fn, kwargs)
    elapsed = round(time.time() - t0, 2)

    row: dict = {
        "key": spec["key"], "fn": fn, "ok": False, "sec": elapsed,
        "rows": 0, "cols": [], "latest_date": None, "latest_value": None,
        "latest_month": None, "lag": None, "error": err, "max_lag": spec.get("max_lag", 3),
        "note": spec.get("note", ""), "expect": spec.get("expect", "ok"),
        "order": None,
    }
    if df is None:
        return row
    try:
        cols = [str(c) for c in df.columns]
        row["cols"] = cols
        row["rows"] = int(len(df))
        if row["rows"] == 0:
            return row
        tc = spec.get("time_col")
        if tc and tc in cols:
            # ⚠️ **排序口径不统一**（2026-09-14 实测）：cpi/ppi/pmi/gdp/m2/credit/retail
            # 是**倒序**（iloc[-1] 是 2008/2006 年），而 social_financing/unemployment/
            # house_price/lpr/shibor/bond_10y 是**正序**。取 `iloc[-1]` 会把最旧的行当成
            # "最新值"（cpi 实测误得 2008-01）→ 必须**按月份取最大**，不能按位置取尾。
            # 生产侧（cn_econ_fetcher）同样按此纪律：先按月份升序排序，再取尾。
            months = [_month_of(v) for v in df[tc].tolist()]
            dated = [(i, m) for i, m in enumerate(months) if m]
            if months[0] and months[-1]:
                row["order"] = "asc" if str(months[0]) <= str(months[-1]) else "desc"
            if dated:
                idx = max(dated, key=lambda p: (p[1], p[0]))[0]
                row["latest_date"] = str(df[tc].iloc[idx])
                row["latest_month"] = months[idx]
                row["lag"] = _lag_months(row["latest_month"], today)
                mc = spec.get("main_col")
                if mc and mc in cols:
                    row["latest_value"] = str(df[mc].iloc[idx])
        row["ok"] = bool(row["latest_month"])
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"parse: {type(exc).__name__}: {exc}"
    return row


def _print_table(rows: list[dict], title: str) -> None:
    print(f"\n=== {title} ===")
    print(f"{'key':<22}{'ok':<4}{'sec':>7}{'rows':>7}  {'ord':<5}{'latest':<14}{'lag':>5}  note")
    for r in rows:
        latest = r["latest_date"] or "-"
        lag = r["lag"] if r["lag"] is not None else "-"
        note = r["error"] or r["note"] or ""
        note = note[:40]
        print(f"{r['key']:<22}{'Y' if r['ok'] else 'N':<4}{r['sec']:>7}{r['rows']:>7}  "
              f"{(r.get('order') or '-'):<5}{latest:<14}{str(lag):>5}  {note}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="中国宏观数据源探针（AkShare）")
    ap.add_argument("--include-rejected", action="store_true",
                    help="附带跑已否决清单（东财报告族，预期是坏的，仅作对照）")
    ap.add_argument("--show-cols", action="store_true", help="打印每个接口的列名（排错时用）")
    args = ap.parse_args(argv)

    today = date.today()
    print(f"probe_cn_macro  date={today.isoformat()}  akshare importing ...")

    ok_rows = [probe_one(s, today) for s in PROBES_OK]
    rej_rows = [probe_one(s, today) for s in PROBES_REJECTED] if args.include_rejected else []

    _print_table(ok_rows, "IN-USE (13) -- exit code depends on these")
    if rej_rows:
        _print_table(rej_rows, "REJECTED (reference only, NOT part of exit code)")

    if args.show_cols:
        print("\n=== columns ===")
        for r in ok_rows:
            print(f"{r['key']}: {r['cols']}")

    failures: list[str] = []
    for r in ok_rows:
        if not r["ok"]:
            failures.append(f"{r['key']}: unavailable ({r['error'] or 'no rows / missing time col'})")
            continue
        max_lag = r["max_lag"]
        if r["lag"] is not None and r["lag"] > max_lag:
            failures.append(f"{r['key']}: stale latest={r['latest_date']} lag={r['lag']}m > {max_lag}m")

    total = round(sum(r["sec"] for r in ok_rows), 2)
    print(f"\nserial total {total}s   in-use ok {sum(1 for r in ok_rows if r['ok'])}/{len(ok_rows)}")

    # 报告落 %TEMP%（不进仓库；Windows 控制台中文在管道下会乱码/截断 → 以 JSON 为准）
    try:
        out_dir = os.path.join(os.environ.get("TEMP") or ".", "marketpulse-cn-macro-probe")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "probe-cnmacro.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"date": today.isoformat(), "in_use": ok_rows,
                       "rejected": rej_rows, "failures": failures}, fh, ensure_ascii=False, indent=2)
        print(f"json: {path}")
    except OSError as exc:
        print(f"json write failed (ignored): {exc}")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: all in-use interfaces available and fresh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
