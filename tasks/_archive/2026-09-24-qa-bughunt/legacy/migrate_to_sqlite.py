"""【已退役 · 仅存档】一次性迁移：data/history.json（宽表）→ SQLite history 长表。

⚠️ 2026-09-24（QA 缺陷轮 BUG-005）：本脚本**已归档、禁止执行** —— `main()` 无条件拒绝运行
（退出码 1），真正的实现留在下面 `_legacy_migrate` / `_legacy_main` 供查档。

退役原因（原文实现即现场证据）：

1. 三十一期（2026-09-12）迁移早已完成 —— 生产库 `data/marketpulse.db` 就是线上数据源，
   不再需要「history.json → SQLite」这段历史；
2. 原文的真实行为是**先 `DELETE FROM history`、再从 `data/history.json` 全量重灌**；该 JSON
   的末行停在 **2026-09-11**（迁移前的旧快照）⇒ 裸跑一次就把生产库 272 个日期塌回旧快照，
   09-12 ~ 09-23 两周数据**不可逆丢失**；
3. `--db` / `--json` **都有 `default=`**（分别指向生产库与 `data/history.json`）⇒ 不带参数
   裸跑即事故（危险默认值 + 破坏性操作，BUG-005 的根因）；
4. ⚠️ **本脚本没有 `--dry-run`** —— 旧文档写「幂等重跑 / `--db` 可演练」与实现不符：任何一次
   调用都会真实写盘、真实 `DELETE`。`docs/commands.md` 里的该命令条目已删。

要真正执行历史迁移，必须先补齐安全侧：`--db`/`--json` 改必填 + `--force` 二次确认 +
真正的 `--dry-run`（只打印计划）+ `DELETE` 前把现库内容备份到 `data/backup/`。
背景见 `tasks/2026-09-24-qa-bughunt/bug_report.md` BUG-005 与 `plan.md` §2 B1。

原用法（历史记录，**勿再执行**）：
    venv/Scripts/python scripts/migrate_to_sqlite.py --db <tmp>
    venv/Scripts/python scripts/migrate_to_sqlite.py
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("marketpulse")

#: 退役脚本退出码：非 0 ⇒ 调用方 / cron 不会把它当成功。
RETIRED_EXIT_CODE = 1

#: 拒绝执行时打印的说明（同时落日志，便于 cron 留痕）。
RETIRED_NOTICE = (
    "本脚本已退役（BUG-005）：三十一期迁移已完成，且它的真实行为是 `DELETE FROM history` 后"
    "从旧 data/history.json（末行 2026-09-11）全量重灌 —— 裸跑会把生产库塌回旧快照，"
    "并且**没有 `--dry-run`**（不存在「只演练」的开关）。已归档到 "
    "tasks/2026-09-24-qa-bughunt/legacy/，禁止执行。"
)


def main() -> int:
    """退役护栏：**任何调用都拒绝执行**（含 `--db` 指向 tmp 的「演练」），绝不碰任何库。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    log.error(RETIRED_NOTICE)
    print(RETIRED_NOTICE)
    return RETIRED_EXIT_CODE


def _legacy_migrate(json_path: Path, db_path: Path) -> bool:
    """原 `migrate()`（三十一期实现，**仅存档、禁止调用**）：DELETE + 全量重灌 + 逐值比对。

    改动仅为把 `json`/`time` 的导入收进函数体（退役脚本不再假设仓库导入路径可用），
    逻辑逐行保留原文以留存 BUG-005 的现场证据。
    """
    import json
    import time

    from src import storage

    t0 = time.perf_counter()
    if not json_path.exists():
        log.error("迁移源不存在: %s", json_path)
        return False
    records = json.loads(json_path.read_text(encoding="utf-8"))
    records = [r for r in records if isinstance(r, dict) and r.get("date")]
    rows = storage.records_to_rows(records)

    conn = storage._connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS history (
                date   TEXT NOT NULL,
                symbol TEXT NOT NULL,
                value  REAL,
                change REAL,
                PRIMARY KEY (date, symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_symbol_date ON history(symbol, date);
            DELETE FROM history;
        """)
        conn.executemany(
            "INSERT INTO history(date, symbol, value, change) VALUES (?, ?, ?, ?)",
            rows)
        conn.commit()
    finally:
        conn.close()

    # 逐值校验：SQLite 里的每个 (date, symbol) 与 JSON 源一致（None == NULL）
    db_rows = {((d, s)): v for d, s, v, _c in storage.query_history(db_path=db_path)}
    json_map = {(r["date"], k): r.get(k) for r in records for k in storage.HISTORY_KEYS}
    mismatches = [(k, json_map[k], db_rows.get(k)) for k in json_map if db_rows.get(k) != json_map[k]]
    extra = set(db_rows) - set(json_map)
    storage.wal_checkpoint(db_path=db_path)
    elapsed = time.perf_counter() - t0

    ok = not mismatches and not extra
    print(f"迁移完成: 记录 {len(records)} 条 → 长行 {len(rows)} | 耗时 {elapsed:.2f}s | "
          f"逐值比对 {'一致' if ok else f'不一致（mismatch={len(mismatches)} extra={len(extra)}）'}")
    for k, want, got in mismatches[:10]:
        print(f"  MISMATCH {k}: json={want} db={got}")
    for k in list(extra)[:10]:
        print(f"  EXTRA {k}: db={db_rows[k]}")
    return ok


def _legacy_main() -> int:
    """原 `main()`（**仅存档、禁止调用**）：`--db`/`--json` 的 `default=` 就是危险默认值本身。"""
    import argparse

    from src import storage

    parser = argparse.ArgumentParser(description="history.json → SQLite 一次性迁移")
    parser.add_argument("--db", default=str(storage.DB_PATH), help="目标 DB 路径（默认正式库）")
    parser.add_argument("--json", default=str(storage.DATA_DIR / "history.json"), help="迁移源 JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ok = _legacy_migrate(Path(args.json), Path(args.db))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
