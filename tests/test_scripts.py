"""运维脚本回归（BUG-005 迁移脚本退役 / BUG-005b 备份失败当成功）。

纪律：本文件**只碰 tmp_path**（`--db` / `--backup-dir` 一律显式指向 tmp），
绝不读写真 `data/marketpulse.db`；归档脚本因「危险默认值」而拒绝执行，故对它的用例
必须同时传 `--db`/`--json`（万一护栏失效，也只影响 tmp 目标）。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# `scripts/` 无 `__init__.py` ⇒ 靠命名空间包导入（conftest 已把仓库根放进 sys.path）。
import scripts.backup_db as backup_db
from src import storage

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVED_MIGRATE = REPO_ROOT / "tasks" / "2026-09-24-qa-bughunt" / "legacy" / "migrate_to_sqlite.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    """真跑脚本（子进程）：工作目录 = 仓库根，显式 UTF-8，避免中文输出解码炸测试。"""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=120,
    )


def _seed_history(path: Path, days: int = 3) -> int:
    """建 tmp 库并写 `days` 行（迁移脚本若真的执行会先 DELETE 掉它们）。返回行数。"""
    storage.init_db(db_path=path)
    storage.upsert_history_rows(
        [("2026-09-0%d" % i, "vix", 20.0 + i, None) for i in range(1, days + 1)],
        db_path=path,
    )
    return storage.count_rows(db_path=path)


def _argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["backup_db.py", *args])


# ---- BUG-005：迁移脚本已归档 ⇒ 必须拒绝执行、且目标库行数不变 ----

def test_archived_migrate_script_refuses_to_run(tmp_path):
    """BUG-005：三十一期迁移已完成 ⇒ 脚本移档 legacy 并**拒绝执行**。

    它的真实行为是 `DELETE FROM history` 后从旧 `data/history.json`（末行 2026-09-11）
    全量重灌 —— 裸跑一次就把生产库 272 个日期塌回旧快照。判据（全部可观察）：
    非 0 退出 + 输出明确说明退役 + **目标 tmp 库行数不变** + `scripts/` 下已无该脚本。
    """
    src_json = tmp_path / "history.json"
    src_json.write_text(json.dumps([{"date": "2026-09-11", "vix": 19.9}]), encoding="utf-8")
    db = tmp_path / "archived-target.db"
    before = _seed_history(db)

    proc = _run(ARCHIVED_MIGRATE, "--db", str(db), "--json", str(src_json))
    out = (proc.stdout or "") + (proc.stderr or "")

    assert proc.returncode != 0, "归档脚本必须非 0 退出，实际输出:\n%s" % out
    assert "BUG-005" in out and "legacy" in out, "必须明确拒绝执行，而不是静默/崩溃:\n%s" % out
    assert storage.count_rows(db_path=db) == before, "目标库行数不得被改动"
    assert not (REPO_ROOT / "scripts" / "migrate_to_sqlite.py").exists(), "脚本应从 scripts/ 移出"


# ---- BUG-005b：backup_db.py 失败必须非 0（cron 视角不能「失败当成功」）----

def test_backup_db_returns_zero_on_success(tmp_path, monkeypatch):
    db = tmp_path / "backup-source.db"
    storage.init_db(db_path=db)
    storage.upsert_history_rows([("2026-09-05", "vix", 20.0, None)], db_path=db)
    out_dir = tmp_path / "backups"

    _argv(monkeypatch, "--db", str(db), "--backup-dir", str(out_dir))
    assert backup_db.main() == 0
    assert list(out_dir.glob("history_*.json")), "成功路径应产出月度备份文件"


def test_backup_db_returns_nonzero_when_backup_dir_unusable(tmp_path, monkeypatch):
    """真实失败场景（不 monkeypatch 业务函数）：备份目录位置被一个**文件**占位 ⇒ mkdir 抛 OSError。"""
    db = tmp_path / "backup-source.db"
    storage.init_db(db_path=db)
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("x", encoding="utf-8")

    _argv(monkeypatch, "--db", str(db), "--backup-dir", str(blocked))
    assert backup_db.main() == 1


def test_backup_db_returns_nonzero_when_export_raises(tmp_path, monkeypatch):
    """导出函数抛出的**任意**异常都要被兜住（不是只 `except OSError`）。"""
    db = tmp_path / "backup-source.db"
    storage.init_db(db_path=db)

    def boom(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(backup_db, "export_monthly_backups", boom)
    _argv(monkeypatch, "--db", str(db), "--backup-dir", str(tmp_path / "backups"))
    assert backup_db.main() == 1
