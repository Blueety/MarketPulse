"""按月导出 history 备份的薄 CLI（核心在 src/storage.export_monthly_backups，D6）。

用法（项目根执行）：
    venv/Scripts/python scripts/backup_db.py [--db <路径>] [--backup-dir <目录>]

当月文件覆盖更新；历史月文件冻结（缺失时从 DB 补写）。data/backup/ 随 auto-push 入库。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import export_monthly_backups  # noqa: E402

log = logging.getLogger("marketpulse")


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite history → data/backup/history_YYYY-MM.json")
    parser.add_argument("--db", default=None, help="DB 路径（默认 data/marketpulse.db）")
    parser.add_argument("--backup-dir", default=None, help="备份目录（默认 data/backup/）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    report = export_monthly_backups(backup_dir=args.backup_dir, db_path=args.db)
    for item in report:
        log.info("%s (%s, %s 行)", item["file"], item["action"], item["rows"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
