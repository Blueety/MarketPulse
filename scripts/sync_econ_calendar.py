"""经济事件日历落盘（P1 + P3 叙事层 + 结果值层）。

任务档：`tasks/2026-09-18-event-timeline-page/`（plan §6.3）、
`tasks/2026-09-19-timeline-event-values/`（plan 定稿，值层）。

```bash
python -m scripts.sync_econ_calendar                       # 抓两源 + 落盘 + 抓近期叙事层 + 结果值层 + **自动 commit/push**
python -m scripts.sync_econ_calendar --dry-run             # 只看抓到什么，不写库、不推送
python -m scripts.sync_econ_calendar --from 2026-01-01 --to 2027-12-31
python -m scripts.sync_econ_calendar --skip-news           # 只更新日历
python -m scripts.sync_econ_calendar --skip-values         # 只更新日历 + 叙事层，不抓结果值层
python -m scripts.sync_econ_calendar --news-window 30      # 叙事层只抓最近 30 天的事件
python -m scripts.sync_econ_calendar --no-push             # 落盘但不提交（本地调试）
```

**cron 用法**：Hermes cron 每天调一次 `venv\\Scripts\\python -m scripts.sync_econ_calendar` 即可 ——
落盘后会自动走 `src/git_ops.auto_commit_push(date, "econ-calendar")`（路径白名单 `data/context/alerts`、
消息 `auto: {date} econ-calendar`、经 Clash 代理 push）。**这一步必须做**：线上 Railway 读的是仓库里的
`data/marketpulse.db`，不 push 则页面看不到新事件。

**结果值层（2026-09-19）**：骨架落盘后，从 TradingView 经济日历取 `actual / forecast / previous / unit /
importance`（`src/econ_values.py`）并 **join 回既有行**（`storage.update_econ_event_values`，**preserve 语义**：
空值不抹既有值；**只 UPDATE 不 INSERT** ⇒ 不做历史回填）。顺序硬约束：**骨架先落库**，
否则 UPDATE 匹配不到行（值层只 enrich 已有行）。

**容错纪律（plan §6.3）**：单个源失败 → 该源记 `failed` 并**保留库内既有数据**（"失败不覆盖"，
与 `/api/econ` 的"失败不缓存"是相反方向的对策，原因不同：这里是历史事件不能因一次网络抖动被抹掉）。
两源**全失败**才以退出码 2 收场，供 cron 侧告警。
⚠️ 值层源（TradingView）失败也进 `failed`（归一化为 `tradingview`）⇒ 退出码 1。它的降级是
"页面退化成只有事件名"，不丢数据，但**要让人看见**，故不静默。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date as _date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import econ_calendar as ec      # noqa: E402
from src import econ_values as ev        # noqa: E402
from src import git_ops                  # noqa: E402
from src import storage as st            # noqa: E402
from src import timeline as tl           # noqa: E402

log = logging.getLogger("marketpulse")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同步经济事件日历（Fed 官方 + 第三方镜像 + 结果值层）")
    ap.add_argument("--dry-run", action="store_true", help="只抓取并打印，不写库")
    ap.add_argument("--from", dest="d_from", help="只落盘 date >= 该日期（YYYY-MM-DD）")
    ap.add_argument("--to", dest="d_to", help="只落盘 date <= 该日期")
    ap.add_argument("--skip-news", action="store_true", help="跳过叙事层（Google News）抓取")
    ap.add_argument("--skip-values", action="store_true",
                    help="跳过结果值层（TradingView）抓取与 join")
    ap.add_argument("--news-window", type=int, default=45,
                    help="叙事层只抓最近 N 天已发生的事件（默认 45）")
    ap.add_argument("--timeout", type=int, default=30, help="单请求超时秒数（默认 30）")
    ap.add_argument("--no-push", action="store_true",
                    help="落盘后不自动 commit+push（默认自动，与 daily_report/snapshot_report 同口径；"
                         "env AUTO_PUSH=0 亦可全局关闭）")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    events, failed = ec.collect_events(timeout=args.timeout)
    print(f"[1/3] 抓取：事件 {len(events)} 条" + (f"，失败源 {failed}" if failed else ""))
    if failed and not events:
        print("★ 两个源全部失败 → 不写库（保留既有数据），退出码 2")
        return 2
    for kind in ec.KINDS:
        n = sum(1 for e in events if e["kind"] == kind)
        if n:
            print(f"      {kind:<6} {n:>3}")

    picked = events
    if args.d_from:
        picked = [e for e in picked if e["date"] >= args.d_from]
    if args.d_to:
        picked = [e for e in picked if e["date"] <= args.d_to]
    print(f"[2/3] 范围过滤后待落盘：{len(picked)} 条"
          f"（{picked[0]['date'] if picked else '-'} ~ {picked[-1]['date'] if picked else '-'}）")

    if args.dry_run:
        print("[3/3] --dry-run：不写库。样本：")
        for e in picked[:8]:
            print("      ", e["date"], e["kind"], "|", e["time_et"] or "--:--", "|", e["title"][:70])
        print("      ... 共", len(picked), "条；失败源:", failed or "无")
        if not args.skip_values:
            # dry-run 也真跑一次值层 join（只读、零写盘）：这才是"干跑"的意义 —— 事先看见命中率
            values, vfail = ev.collect_values(picked, timeout=args.timeout)
            _print_values(picked, len(values), None, vfail, dry=True)
        return 0

    st.init_db()
    written = st.upsert_econ_events(picked)
    total = st.count_econ_events()
    print(f"[3/3] 落盘：写入 {written} 条，库内共 {total} 条")

    # ---- 结果值层（必须在骨架落盘之后：只 UPDATE 既有行，先落骨架才匹配得到）----
    if not args.skip_values:
        values, vfail = ev.collect_values(picked, timeout=args.timeout)
        hit_rows = st.update_econ_event_values(values) if values else 0
        _print_values(picked, len(values), hit_rows, vfail, dry=False)
        failed = failed + sorted({f.split(":")[0] for f in vfail})

    if not args.skip_news:
        today = _date.today().isoformat()
        since = (_date.today() - timedelta(days=args.news_window)).isoformat()
        todo = [e for e in picked if since <= e["date"] <= today]
        print(f"[news] 叙事层：对 {len(todo)} 个已发生事件抓 Google News（窗口 {since} ~ {today}）")
        rows, nfail = tl.fetch_event_news(todo, today=today, timeout=args.timeout)
        if rows:
            st.upsert_event_news(rows)
        print(f"[news] 写入 {len(rows)} 条，失败 {len(nfail)} 条" + (f"：{nfail[:6]}" if nfail else ""))

    # 落盘后提交推送（与 daily_report / snapshot_report / opening_analyzer 三个入口同口径）：
    # `git_ops.auto_commit_push` 走**路径白名单**（data / context / alerts，不用 `-A`）+
    # `auto: {date} {type}` 消息 + 经 Clash 代理 push；无改动则幂等跳过；失败只记日志不抛（退出码仍 0）。
    # ⚠️ **必须提交**：线上（Railway）读的是仓库里的 `data/marketpulse.db`，不 push 则页面看不到新事件。
    if not args.no_push:
        pushed = git_ops.auto_commit_push(_date.today().isoformat(), "econ-calendar")
        # 返回值语义：True = 已提交并推送；False = 关闭 / **无改动** / 失败（三者靠上一行 [auto-push] 日志区分）
        print("[git] 自动提交推送：" + ("已提交并推送" if pushed
              else "未提交（无改动 / AUTO_PUSH=0 / 失败，见上一行 [auto-push] 日志）"))

    if failed:
        print(f"⚠️ 部分源失败（已保留既有数据）：{failed}")
        return 1
    return 0


def _print_values(skeleton: list[dict], hit: int, written: int | None, vfail: list[str],
                  dry: bool) -> None:
    """值层小结。M = **窗口内的**骨架条数（`econ_values.in_window`，与 `collect_values` 同源）。

    `written` 为 `None` 表示 dry-run（不写库）；非 None 时它是**写入库的 `(date, kind)` 组数**，
    与 `hit` 的差 = "骨架里没有该行"（update 只 UPDATE ⇒ rowcount 0）。正常应相等。
    """
    w_from, w_to = ev.value_window()
    total = len(ev.in_window(skeleton))
    src = sorted({f.split(":")[0] for f in vfail})
    tail = f"，值侧失败 {src}" if src else ""
    if dry:
        print(f"[values] 值层（dry-run，不写库）：命中 {hit}/{total} 条"
              f"（窗口 {w_from} ~ {w_to}）{tail}")
    else:
        print(f"[values] 值层：命中 {hit}/{total} 条，写入库 {written} 组"
              f"（窗口 {w_from} ~ {w_to}）{tail}")


if __name__ == "__main__":
    raise SystemExit(main())
