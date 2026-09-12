"""一次性迁移：data/history.json（宽表）→ SQLite history 长表。

- 读 JSON 文件本身（不走 analyzer.load_history——切换后那会读 SQLite，迁移必须读迁移前的 JSON）；
- 逐记录展开长行（None 保留为 NULL；change 一律 NULL，PRD D3）；
- 单事务批量 upsert（overwrite 模式），幂等：每次重跑先 DELETE FROM history 再全量重灌；
- 逐值全量比对（数据量小，成本可忽略）后打印报告；
- 收尾 wal_checkpoint(TRUNCATE)，防 -wal 残留。

用法（项目根执行）：
    venv/Scripts/python scripts/migrate_to_sqlite.py --db <tmp>   # 演练（不动正式库）
    venv/Scripts/python scripts/migrate_to_sqlite.py              # 正式迁移 data/marketpulse.db
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import storage  # noqa: E402

log = logging.getLogger("marketpulse")


def migrate(json_path: Path, db_path: Path) -> bool:
    """执行迁移并逐值校验；返回是否全部成功。"""
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


def main() -> int:
    parser = argparse.ArgumentParser(description="history.json → SQLite 一次性迁移")
    parser.add_argument("--db", default=str(storage.DB_PATH), help="目标 DB 路径（默认正式库）")
    parser.add_argument("--json", default=str(storage.DATA_DIR / "history.json"), help="迁移源 JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ok = migrate(Path(args.json), Path(args.db))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
