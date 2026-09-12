"""SQLite 存储层（三十一期：历史行情 JSON → SQLite）。

职责：history 长表 (date, symbol, value, change) 的建表 / upsert（preserve|overwrite 双模式，
精确对应 append_history(merge_existing=) 与 merge_history 的「NULL 不抹盘中值」语义）/ 范围查询 /
长宽互转 / 按月备份导出 / 空库恢复三级降级。纯标准库 sqlite3，WAL 模式。

- symbol 一律小写键（与 analyzer._HISTORY_KEYS 同源，测试锁定同步）。
- NULL 是语义（休市/未收盘），写入与读取都必须保留（PRD D3：change 列保留但一律 NULL，
  change_pct 由读侧相邻收盘价派生——不存时点 change）。
- DB_PATH 是唯一测试 patch 点：函数内 `db_path or DB_PATH` 为调用时属性查找，
  monkeypatch.setattr(storage, "DB_PATH", tmp) 单点全局生效（对「补丁打使用方」纪律的
  有意例外，理由见 docs/pitfalls.md）。
- 查询侧损坏容错：DB 文件损坏 → 返回 []（纪律同 load_history 的坏 JSON → 空历史，不崩）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger("marketpulse")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "marketpulse.db"
DEFAULT_BACKUP_DIR = DATA_DIR / "backup"

# 与 analyzer._HISTORY_KEYS 同源（测试锁定同步）；顺序仅作文档用途，存储/读取按名取值
HISTORY_KEYS = ("gspc", "ixic", "sh", "sz", "cyb", "vix", "vxn", "move", "gld", "btc")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    date   TEXT NOT NULL,
    symbol TEXT NOT NULL,
    value  REAL,
    change REAL,
    PRIMARY KEY (date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_symbol_date ON history(symbol, date);
"""


def _connect(db_path=None) -> sqlite3.Connection:
    """打开连接（父目录自动创建）；路径参数缺省走模块级 DB_PATH（调用时查找）。"""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path), timeout=10)


def init_db(db_path=None) -> None:
    """建表（幂等，不清数据）+ WAL。重复调用安全。"""
    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def wal_checkpoint(db_path=None) -> None:
    """WAL 收尾（迁移/恢复后调用，防 -wal 残留导致部署副本不一致）。"""
    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def upsert_history_rows(rows, preserve_existing: bool = False, db_path=None) -> int:
    """批量 upsert 长行 [(date, symbol, value, change), ...]，返回写入行数。

    日期格式强制 YYYY-MM-DD（畸形行跳过并告警——防 int date 等脏值入库炸读侧 strptime）；
    symbol 强制小写（存储键纪律）。preserve_existing=True → 已有行的 value/change 不被
    NULL 抹掉（对应 append_history(merge_existing=True) 定稿保护）；False → 无条件覆盖
    （允许写 NULL；对应同日定稿覆盖 / 迁移 / 回填）。
    """
    clean, skipped = [], 0
    for (d, s, v, c) in rows:
        d, s = str(d), str(s).lower()
        if not _DATE_RE.match(d):
            log.warning("history 行日期格式异常，跳过: %r (symbol=%s)", d, s)
            skipped += 1
            continue
        clean.append((d, s, v, c))
    rows = clean
    if skipped:
        log.warning("共跳过 %d 行畸形日期", skipped)
    if not rows:
        return 0
    if preserve_existing:
        sql = ("INSERT INTO history(date, symbol, value, change) VALUES (?, ?, ?, ?) "
               "ON CONFLICT(date, symbol) DO UPDATE SET "
               "value = CASE WHEN excluded.value IS NULL THEN history.value ELSE excluded.value END, "
               "change = CASE WHEN excluded.change IS NULL THEN history.change ELSE excluded.change END")
    else:
        sql = ("INSERT INTO history(date, symbol, value, change) VALUES (?, ?, ?, ?) "
               "ON CONFLICT(date, symbol) DO UPDATE SET "
               "value = excluded.value, change = excluded.change")
    conn = _connect(db_path)
    try:
        with conn:
            conn.executemany(sql, rows)
    finally:
        conn.close()
    return len(rows)


def query_history(symbols=None, start_date=None, end_date=None, db_path=None) -> list[tuple]:
    """查长行 [(date, symbol, value, change), ...]，date 升序（排序在读取侧一次性保证）。
    symbols 大小写不敏感（统一小写比对）；损坏 DB → 返回 []（不崩，纪律同坏 JSON）。"""
    sql = "SELECT date, symbol, value, change FROM history"
    conds, params = [], []
    if symbols:
        syms = sorted({str(s).lower() for s in symbols})
        conds.append(f"symbol IN ({','.join('?' * len(syms))})")
        params.extend(syms)
    if start_date:
        conds.append("date >= ?")
        params.append(str(start_date))
    if end_date:
        conds.append("date <= ?")
        params.append(str(end_date))
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY date ASC, symbol ASC"
    conn = _connect(db_path)
    try:
        return [(r[0], r[1], r[2], r[3]) for r in conn.execute(sql, params)]
    except sqlite3.DatabaseError as exc:
        log.warning("history 查询失败（DB 损坏？），按空历史处理: %s", exc)
        return []
    finally:
        conn.close()


def count_rows(db_path=None) -> int:
    """history 总行数；损坏 DB → 0（与查询侧同容错）。"""
    conn = _connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        log.warning("history 计数失败（DB 损坏？），按 0 处理: %s", exc)
        return 0
    finally:
        conn.close()


def get_date_range(db_path=None) -> tuple[str | None, str | None]:
    """(最小日期, 最大日期)；空库 / 损坏 → (None, None)。"""
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT MIN(date), MAX(date) FROM history").fetchone()
        return (row[0], row[1]) if row else (None, None)
    except sqlite3.DatabaseError as exc:
        log.warning("history 日期范围查询失败，按空处理: %s", exc)
        return (None, None)
    finally:
        conn.close()


def rows_to_records(rows) -> list[dict]:
    """长行 → 宽记录（history.json 记录同构）：emit 全键（缺键补 None）、date 升序、None 保留。"""
    by_date: dict[str, dict] = {}
    for date, symbol, value, _change in rows:
        rec = by_date.setdefault(str(date), {"date": str(date)})
        rec[str(symbol)] = value
    out = []
    for date in sorted(by_date):
        rec = by_date[date]
        for k in HISTORY_KEYS:
            rec.setdefault(k, None)
        out.append(rec)
    return out


def records_to_rows(records) -> list[tuple]:
    """宽记录（history.json 记录）→ 长行；无 date 的记录跳过；change 一律 NULL（D3）。"""
    rows = []
    for rec in records:
        date = str(rec.get("date", ""))
        if not date:
            continue
        for k in HISTORY_KEYS:
            rows.append((date, k, rec.get(k), None))
    return rows


# ---- 按月备份（D1 修正版：每文件仅当月记录，历史月冻结）----

def export_monthly_backups(backup_dir=None, db_path=None) -> list[dict]:
    """按月导出快照到 backup_dir（默认 data/backup/，提交 Git）。

    - 当月文件每次运行覆盖更新；历史月文件写成后冻结（历史月记录不可变）；
    - 历史月文件缺失时从 DB 补写（自愈）；
    - 文件结构 {export_date, month, record_count, records:[[date,symbol,value,change],...]}；
    - 返回 [{file, month, rows, action}]。
    """
    bdir = Path(backup_dir or DEFAULT_BACKUP_DIR)
    bdir.mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path)
    try:
        months = [r[0] for r in conn.execute(
            "SELECT DISTINCT substr(date, 1, 7) FROM history ORDER BY 1")]
    except sqlite3.DatabaseError as exc:
        log.warning("备份导出失败（DB 损坏？）: %s", exc)
        return []
    finally:
        conn.close()
    current_month = datetime.now().strftime("%Y-%m")
    report = []
    for m in months:
        path = bdir / f"history_{m}.json"
        if m != current_month and path.exists():
            report.append({"file": path.name, "month": m, "rows": 0, "action": "frozen"})
            continue
        rows = query_history(start_date=f"{m}-01", end_date=f"{m}-31", db_path=db_path)
        payload = {
            "export_date": datetime.now().astimezone().isoformat(timespec="seconds"),
            "month": m,
            "record_count": len(rows),
            "records": [[d, s, v, c] for (d, s, v, c) in rows],
        }
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        report.append({"file": path.name, "month": m, "rows": len(rows), "action": "written"})
    return report


# ---- 空库恢复三级降级（D2，P0）----

def restore_if_empty(db_path=None, backup_dir=None) -> str:
    """DB 为空时恢复数据，返回 'db' | 'backup' | 'json' | 'empty'。

    降级链：DB 非空 → 'db'（不动作）；空 → 按文件名（月份）升序合并 backup_dir 下
    history_YYYY-MM.json → 仍空 → 读 data/history.json（旧宽格式一次性兼容导入）→
    仍无 → 'empty'（页面显示「数据暂缺」，不崩）。幂等：仅空库触发。
    """
    if count_rows(db_path) > 0:
        return "db"
    init_db(db_path)
    bdir = Path(backup_dir or DEFAULT_BACKUP_DIR)
    if bdir.exists():
        for f in sorted(bdir.glob("history_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                rows = [(r[0], r[1], r[2], r[3]) for r in data.get("records", [])
                        if isinstance(r, list) and len(r) == 4]
            except (json.JSONDecodeError, OSError, TypeError, KeyError) as exc:
                log.warning("备份文件解析失败，跳过 %s: %s", f.name, exc)
                continue
            if rows:
                upsert_history_rows(rows, preserve_existing=False, db_path=db_path)
        if count_rows(db_path) > 0:
            wal_checkpoint(db_path)
            return "backup"
    legacy = DATA_DIR / "history.json"
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("旧 history.json 读取失败: %s", exc)
            data = []
        if isinstance(data, list):
            rows = records_to_rows([r for r in data if isinstance(r, dict) and r.get("date")])
            if rows:
                upsert_history_rows(rows, preserve_existing=False, db_path=db_path)
        if count_rows(db_path) > 0:
            wal_checkpoint(db_path)
            return "json"
    return "empty"
