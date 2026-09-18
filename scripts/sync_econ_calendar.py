"""经济事件日历落盘（P1 + P3 叙事层）。

任务档：`tasks/2026-09-18-event-timeline-page/`（plan §6.3）。

```bash
python -m scripts.sync_econ_calendar                       # 抓两源 + 落盘 + 抓近期叙事层
python -m scripts.sync_econ_calendar --dry-run             # 只看抓到什么，不写库
python -m scripts.sync_econ_calendar --from 2026-01-01 --to 2027-12-31
python -m scripts.sync_econ_calendar --skip-news           # 只更新日历
python -m scripts.sync_econ_calendar --news-window 30      # 叙事层只抓最近 30 天的事件
```

**容错纪律（plan §6.3）**：单个源失败 → 该源记 `failed` 并**保留库内既有数据**（"失败不覆盖"，
与 `/api/econ` 的"失败不缓存"是相反方向的对策，原因不同：这里是历史事件不能因一次网络抖动被抹掉）。
两源**全失败**才以退出码 2 收场，供 cron 侧告警。
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date as _date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import econ_calendar as ec      # noqa: E402
from src import storage as st            # noqa: E402
from src import timeline as tl           # noqa: E402

log = logging.getLogger("marketpulse")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="同步经济事件日历（Fed 官方 + 第三方镜像）")
    ap.add_argument("--dry-run", action="store_true", help="只抓取并打印，不写库")
    ap.add_argument("--from", dest="d_from", help="只落盘 date >= 该日期（YYYY-MM-DD）")
    ap.add_argument("--to", dest="d_to", help="只落盘 date <= 该日期")
    ap.add_argument("--skip-news", action="store_true", help="跳过叙事层（Google News）抓取")
    ap.add_argument("--news-window", type=int, default=45,
                    help="叙事层只抓最近 N 天已发生的事件（默认 45）")
    ap.add_argument("--timeout", type=int, default=30, help="单请求超时秒数（默认 30）")
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
        return 0

    st.init_db()
    written = st.upsert_econ_events(picked)
    total = st.count_econ_events()
    print(f"[3/3] 落盘：写入 {written} 条，库内共 {total} 条")

    if not args.skip_news:
        today = _date.today().isoformat()
        since = (_date.today() - timedelta(days=args.news_window)).isoformat()
        todo = [e for e in picked if since <= e["date"] <= today]
        print(f"[news] 叙事层：对 {len(todo)} 个已发生事件抓 Google News（窗口 {since} ~ {today}）")
        rows, nfail = tl.fetch_event_news(todo, today=today, timeout=args.timeout)
        if rows:
            st.upsert_event_news(rows)
        print(f"[news] 写入 {len(rows)} 条，失败 {len(nfail)} 条" + (f"：{nfail[:6]}" if nfail else ""))

    if failed:
        print(f"⚠️ 部分源失败（已保留既有数据）：{failed}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
