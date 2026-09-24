"""SQLite 存储层（三十一期：历史行情 JSON → SQLite）。

职责：history 长表 (date, symbol, value, change) 的建表 / upsert（preserve|overwrite 双模式，
精确对应 append_history(merge_existing=) 与 merge_history 的「NULL 不抹盘中值」语义）/ 范围查询 /
长宽互转 / 按月备份导出（history + 经济事件两张表）/ 空库恢复三级降级 + 事件表恢复。
纯标准库 sqlite3，WAL 模式。

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

-- 经济事件日历（2026-09-18，任务档 tasks/2026-09-18-event-timeline-page）
-- 主键 (date, kind, source)：同一 `(日期, 类型)` 允许来自不同源（fed 官方 / 镜像），
-- 页面上再按 (date, kind) 去重（官方优先）—— 库里保留两源便于对账与排障。
-- 末 8 列为**结果值层**（2026-09-19，任务档 tasks/2026-09-19-timeline-event-values）：
-- 由 TradingView 经济日历 enrich 既有行（**只 UPDATE 不 INSERT**，见 update_econ_event_values）。
-- ⚠️ `CREATE TABLE IF NOT EXISTS` 对**既有库不加列** ⇒ 既有库靠 `_migrate_econ_events` 的幂等
--    `ALTER TABLE ADD COLUMN` 补（两处列清单必须同步，见 ECON_VALUE_COLS）。
CREATE TABLE IF NOT EXISTS econ_events (
    date       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    agency     TEXT,
    source     TEXT NOT NULL,
    time_et    TEXT,
    status     TEXT,
    note       TEXT,
    fetched_at TEXT,
    actual           REAL,
    forecast         REAL,
    previous         REAL,
    unit             TEXT,
    importance       INTEGER,
    value_source     TEXT,
    value_title      TEXT,
    value_fetched_at TEXT,
    PRIMARY KEY (date, kind, source)
);
CREATE INDEX IF NOT EXISTS idx_econ_events_date ON econ_events(date);

-- 事件叙事层（P3）：**按 (date, kind) 存** —— 叙事是"这个事件当天媒体在谈什么"，
-- 同一天若有多个事件（如 09-30 GDP + PCE），各事件各有各的检索口径，不共用一条。
CREATE TABLE IF NOT EXISTS econ_event_news (
    date       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    news_count INTEGER,
    title      TEXT,
    link       TEXT,
    fetched_at TEXT,
    PRIMARY KEY (date, kind)
);
"""


def is_lock_error(exc: BaseException) -> bool:
    """**可重试**的锁/忙冲突：`OperationalError` 家族且消息含 `locked` / `busy`（2026-09-24，BUG-001）。

    ⚠️ 为什么单独一个判定：`sqlite3.OperationalError` ⊂ `sqlite3.DatabaseError`，而
    `analyzer._upsert_history_rows_selfheal` 原来按**父类**捕获 ⇒ "database is locked"
    （其它进程的瞬时写锁）被判成"库损坏"→ **删掉整个库**。锁是**可重试**的，不是损坏。
    """
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def _connect(db_path=None) -> sqlite3.Connection:
    """打开连接（父目录自动创建）；路径参数缺省走模块级 DB_PATH（调用时查找）。

    `timeout=10` 与 `PRAGMA busy_timeout=10000` **双写**：前者是 `sqlite3.connect` 参数
    （CPython 内部同样转成 busy_timeout），后者把它写成库级显式设置 —— 意图是"读写都先等锁
    10s 再报错"，从源头减少"锁 → 误判损坏"的触发面（BUG-001）。
    """
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    try:
        conn.execute("PRAGMA busy_timeout=10000")
    except sqlite3.DatabaseError:
        pass        # 只读/损坏库上设 PRAGMA 失败不该让连接建立本身失败（既有容错纪律）
    return conn


def init_db(db_path=None) -> None:
    """建表（幂等，不清数据）+ 结果值层列迁移 + WAL。重复调用安全。

    ⚠️ **调用方纪律（列先行、代码后行）**：`econ_events` 的结果值层列由本函数补齐，
    而 `web/app.py` 的启动恢复链在「库非空」时**提前 return（不调 init_db）** ⇒
    读侧（`query_econ_events`）在未迁移的库上会静默降级成 `[]`（DatabaseError 被吞）。
    因此**写入方（`scripts/sync_econ_calendar.py`）必须先跑 init_db**（它已经这么做了）。
    """
    conn = _connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        added = _migrate_econ_events(conn)
        if added:
            log.info("econ_events 迁移：新增列 %s", added)
        conn.commit()
    finally:
        conn.close()


#: 结果值层列（2026-09-19）：`(列名, SQLite 声明)`。
#: ⚠️ 与 `_SCHEMA` 里 `econ_events` 的末 8 列**必须同源** —— 一处加列两处都要加，
#: 否则「新建库有列、既有库没列」会分叉成两种表结构。
ECON_VALUE_COLS: tuple[tuple[str, str], ...] = (
    ("actual", "REAL"),
    ("forecast", "REAL"),
    ("previous", "REAL"),
    ("unit", "TEXT"),
    ("importance", "INTEGER"),
    ("value_source", "TEXT"),
    ("value_title", "TEXT"),
    ("value_fetched_at", "TEXT"),
)


def _migrate_econ_events(conn) -> list[str]:
    """给既有 `econ_events` 补结果值层列（**幂等**：缺哪列补哪列），返回本次新增的列名。

    本项目无 migration 框架，而 `_SCHEMA` 是 `CREATE TABLE IF NOT EXISTS`
    ⇒ 对已存在的库**一列也不会加**（plan D6）。故必须显式 `ALTER TABLE ADD COLUMN` + 列存在性检查，
    可重复跑；`PRAGMA table_info` 与 `ALTER` 都在同一连接内，中途失败不提交（由 init_db 的 conn 生命周期兜底）。
    """
    have = {r[1] for r in conn.execute("PRAGMA table_info(econ_events)")}
    if not have:
        return []                       # 表不存在（上面 executescript 已建全列），无需迁移
    added: list[str] = []
    for name, decl in ECON_VALUE_COLS:
        if name not in have:
            conn.execute("ALTER TABLE econ_events ADD COLUMN %s %s" % (name, decl))
            added.append(name)
    return added


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
        log.warning("history 行数查询失败（DB 损坏？）: %s", exc)
        return 0
    finally:
        conn.close()


def _count_rows_strict(db_path=None) -> int:
    """`count_rows` 的**不吞异常**版本；只给"要不要做恢复"这类决策用（2026-09-24，BUG-001 同族）。

    ⚠️ 为什么需要：`count_rows` 把**任何** `DatabaseError`（含"database is locked"）都当 0 行，
    而 `restore_if_empty` 拿"0 行"当"空库"判据 ⇒ **一次瞬时锁就能让恢复链在非空库上灌备份**
    （锁不是"库是空的"的证明）。锁必须冒出来让调用方跳过本轮。
    """
    conn = _connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM history").fetchone()[0])
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
    - 返回 [{file, month, rows, action}]（history 项）+ 事件表项（见 `_export_econ_backups`）。

    2026-09-24（B1-4a，D-3）：**备份面扩到经济事件两张表** —— history 的既有行为与返回结构
    一字不改，事件表项**追加**在同一个列表尾部（`file` 前缀 `econ_events_` 可区分）；
    事件表导出失败只记日志，绝不让备份路径抛异常打断报告链路。
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
    try:
        report.extend(_export_econ_backups(bdir, current_month, db_path=db_path))
    except Exception as exc:  # noqa: BLE001 —— 事件表是**追加**面：任何意外都只记日志，
        log.error("事件表备份导出失败（已跳过，不影响 history 备份）: %s", exc)   # 不得打断报告链路
    return report


# ---- 空库恢复三级降级（D2，P0）----

def restore_if_empty(db_path=None, backup_dir=None) -> str:
    """DB 为空时恢复数据，返回 'db' | 'backup' | 'json' | 'empty'。

    降级链：DB 非空 → 'db'（不动作）；空 → 按文件名（月份）升序合并 backup_dir 下
    history_YYYY-MM.json → 仍空 → 读 data/history.json（旧宽格式一次性兼容导入）→
    仍无 → 'empty'（页面显示「数据暂缺」，不崩）。幂等：仅空库触发。

    2026-09-24（B1-4a，D-3）：**事件表按同一命名规则恢复**（`econ_events_YYYY-MM.json`，
    与 history 的 `history_*.json` 同目录同纪律），只在**该表为空**时动（幂等）；两张事件表
    （`econ_events` + `econ_event_news`）**同批恢复**，只要有一张非空就整段跳过 —— 避免
    「骨架已灌、叙事被跳过」的半态。事件表单独恢复成功（history 仍空）时同样返回 'backup'
    （数据也确实来自 data/backup/，调用方据此不再走 'empty' 的「数据暂缺」告警）。

    ⚠️ 2026-09-24（BUG-001 同族）：判"空"用 `_count_rows_strict`（不吞异常），但**只有锁类错误
    才跳过本轮**：库被其它进程锁住时抛 `OperationalError("...locked")` ⇒ 返回 'db' 且不写任何东西，
    绝不因为一次瞬时锁就往非空库上灌备份。**其余** `DatabaseError`（DB 文件不存在时 `_connect`
    刚建出的空文件 ⇒ `no such table: history`；或是损坏库）**必须继续走恢复链** —— 那是"全新部署 /
    数据源不在仓库里"时让页面有数据的唯一路径（B1Guard 2026-09-24 探针发现：把这类也当"跳过"
    会让恢复链静默失效，实测 outcome='db'、恢复 0 行）。
    """
    try:
        rows = _count_rows_strict(db_path)
    except sqlite3.DatabaseError as exc:
        if is_lock_error(exc):
            log.warning("库被其它进程占用，跳过本轮恢复: %s", exc)
            return "db"
        log.warning("空库判定遇到 %s（按空库继续走恢复链）: %s", type(exc).__name__, exc)
        rows = 0
    if rows > 0:
        return "db"
    init_db(db_path)
    bdir = Path(backup_dir or DEFAULT_BACKUP_DIR)
    try:
        econ_rows = _restore_econ_backups(bdir, db_path=db_path)   # 事件表（仅空表触发）
    except Exception as exc:  # noqa: BLE001 —— 追加面：任何意外只记日志，不打断 history 恢复链
        log.error("事件表恢复失败（已跳过）: %s", exc)
        econ_rows = 0
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
    if econ_rows:
        wal_checkpoint(db_path)     # 只恢复了事件表（history 仍空）：数据同样来自 data/backup/
        return "backup"
    return "empty"


# ------------------------------------------------------------------ 经济事件日历（2026-09-18）

#: `econ_events` 的读取投影。**顺序 = 建表顺序**（`dict(zip(_ECON_COLS, row))` 依赖它）。
#: 末 8 项是结果值层（2026-09-19）——加列必须同时改这里，否则值进了库也读不出来
#: （`src/timeline.py` 侧同理：payload 的 item 是逐键显式构造，缺键同样不透传）。
_ECON_COLS = ("date", "kind", "title", "agency", "source", "time_et", "status", "note", "fetched_at",
              "actual", "forecast", "previous", "unit", "importance",
              "value_source", "value_title", "value_fetched_at")

#: 值层里"有内容"的列（用于判断一条值是否值得写：全空不写，免得只把 `value_fetched_at` 刷成"有值层"）
_VALUE_COLS = ("actual", "forecast", "previous", "unit", "importance", "value_source", "value_title")


def upsert_econ_events(events, db_path=None) -> int:
    """批量 upsert 事件（dict 列表），返回写入条数。

    日期强制 `YYYY-MM-DD`（畸形跳过并告警，纪律同 `upsert_history_rows`）；
    `kind`/`source` 必填（缺失跳过）。同一 `(date, kind, source)` 视为同一条 → 覆盖更新
    （calendars 会改期：SEQUENCE 变化时标题/时刻都可能变）。
    """
    clean = []
    for ev in events or []:
        date = str(ev.get("date") or "")
        kind = str(ev.get("kind") or "").strip()
        source = str(ev.get("source") or "").strip()
        if not _DATE_RE.match(date) or not kind or not source:
            log.warning("econ_events 行字段缺失/日期非法，跳过: %r", {k: ev.get(k) for k in ("date", "kind", "source")})
            continue
        clean.append((date, kind, str(ev.get("title") or "")[:300], ev.get("agency"),
                      source, ev.get("time_et"), ev.get("status") or "ok",
                      ev.get("note"), ev.get("fetched_at") or datetime.now().isoformat(timespec="seconds")))
    if not clean:
        return 0
    sql = ("INSERT INTO econ_events(date, kind, title, agency, source, time_et, status, note, fetched_at) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
           "ON CONFLICT(date, kind, source) DO UPDATE SET "
           "title = excluded.title, agency = excluded.agency, time_et = excluded.time_et, "
           "status = excluded.status, note = excluded.note, fetched_at = excluded.fetched_at")
    conn = _connect(db_path)
    try:
        with conn:
            conn.executemany(sql, clean)
    finally:
        conn.close()
    return len(clean)


def update_econ_event_values(values, db_path=None) -> int:
    """把结果值层写进**既有**事件行，返回写入的 `(date, kind)` 组数。

    **只 UPDATE、绝不 INSERT** ⇒ 天然满足「只 enrich 骨架已有行、不做历史回填」（plan D-5a）：
    值侧有、骨架里没有的事件不会凭空进库。匹配键是 `(date, kind)`（与页面去重口径同键），
    一行 SQL 覆盖该键下的**全部 source 行**（fed / mirror 都写）—— 这样无论页面按哪种源优先去重，
    胜出的那行都带着值。

    **preserve 语义（plan D5，与 `upsert_history_rows(preserve_existing=True)` 同一纪律）**：
    每个值列都是 `COALESCE(新值, 既有值)` ⇒ 新值为 `None` 时**保留已落库的值**，
    绝不用 `null` 抹掉上次抓到的实际值（TradingView 对老事件的 `actual` 偶发为 `null`，
    而"公布当天那次没抓到"是常态）。整源失败时调用方**直接不调用本函数**（失败不覆盖）。

    `values` 元素形状：`{date, kind, actual, forecast, previous, unit, importance,
    value_source, value_title}`；`date`/`kind` 为必填匹配键，其余可空。
    """
    groups = []
    for v in values or []:
        date = str(v.get("date") or "")
        kind = str(v.get("kind") or "").strip()
        if not _DATE_RE.match(date) or not kind:
            log.warning("econ 值层行匹配键缺失/日期非法，跳过: %r",
                        {k: v.get(k) for k in ("date", "kind")})
            continue
        if all(v.get(k) is None for k in _VALUE_COLS):
            continue                    # 全空不写：否则只会把 value_fetched_at 刷成"有值层"
        groups.append((date, kind, v))
    if not groups:
        return 0
    sql = ("UPDATE econ_events SET "
           "actual = COALESCE(?, actual), forecast = COALESCE(?, forecast), "
           "previous = COALESCE(?, previous), unit = COALESCE(?, unit), "
           "importance = COALESCE(?, importance), "
           "value_source = COALESCE(?, value_source), "
           "value_title = COALESCE(?, value_title), "
           "value_fetched_at = COALESCE(?, value_fetched_at) "
           "WHERE date = ? AND kind = ?")
    stamp = datetime.now().isoformat(timespec="seconds")
    conn = _connect(db_path)
    written = 0
    try:
        with conn:
            for date, kind, v in groups:
                cur = conn.execute(sql, (v.get("actual"), v.get("forecast"), v.get("previous"),
                                         v.get("unit"), v.get("importance"),
                                         v.get("value_source"), v.get("value_title"),
                                         stamp, date, kind))
                if cur.rowcount > 0:
                    written += 1        # 骨架里没这一行 ⇒ rowcount 0 ⇒ 不计入（"只 enrich 已有行"）
    finally:
        conn.close()
    return written


def query_econ_events(start_date=None, end_date=None, kinds=None, db_path=None) -> list[dict]:
    """查事件（date 升序）；损坏 DB → 返回 []（不崩，纪律同 history 查询侧）。"""
    sql = "SELECT %s FROM econ_events" % ", ".join(_ECON_COLS)
    conds, params = [], []
    if start_date:
        conds.append("date >= ?")
        params.append(str(start_date))
    if end_date:
        conds.append("date <= ?")
        params.append(str(end_date))
    if kinds:
        ks = sorted({str(k) for k in kinds})
        conds.append("kind IN (%s)" % ",".join("?" * len(ks)))
        params.extend(ks)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY date ASC, kind ASC, source ASC"
    conn = _connect(db_path)
    try:
        return [dict(zip(_ECON_COLS, r)) for r in conn.execute(sql, params)]
    except sqlite3.DatabaseError as exc:
        log.warning("econ_events 查询失败（DB 损坏？），按空处理: %s", exc)
        return []
    finally:
        conn.close()


def count_econ_events(db_path=None) -> int:
    """事件总行数；损坏 DB → 0。"""
    conn = _connect(db_path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM econ_events").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        log.warning("econ_events 计数失败（DB 损坏？），按 0 处理: %s", exc)
        return 0
    finally:
        conn.close()


def upsert_event_news(rows, db_path=None) -> int:
    """批量 upsert 叙事层 [(date, kind, count, title, link), ...]（同 (date,kind) 覆盖）。"""
    clean = []
    for date, kind, count, title, link in rows or []:
        date, kind = str(date or ""), str(kind or "").strip()
        if not _DATE_RE.match(date) or not kind:
            log.warning("econ_event_news 字段非法，跳过: %r/%r", date, kind)
            continue
        clean.append((date, kind, count, title, link, datetime.now().isoformat(timespec="seconds")))
    if not clean:
        return 0
    sql = ("INSERT INTO econ_event_news(date, kind, news_count, title, link, fetched_at) "
           "VALUES (?, ?, ?, ?, ?, ?) "
           "ON CONFLICT(date, kind) DO UPDATE SET news_count = excluded.news_count, "
           "title = excluded.title, link = excluded.link, fetched_at = excluded.fetched_at")
    conn = _connect(db_path)
    try:
        with conn:
            conn.executemany(sql, clean)
    finally:
        conn.close()
    return len(clean)


def query_event_news(dates=None, db_path=None) -> dict[tuple[str, str], dict]:
    """查叙事层 → `{(date, kind): {count, title, link}}`（损坏 DB → {}）。"""
    sql = "SELECT date, kind, news_count, title, link FROM econ_event_news"
    params: list = []
    if dates:
        ds = sorted({str(d) for d in dates})
        sql += " WHERE date IN (%s)" % ",".join("?" * len(ds))
        params.extend(ds)
    conn = _connect(db_path)
    try:
        return {(r[0], r[1]): {"count": r[2], "title": r[3], "link": r[4]}
                for r in conn.execute(sql, params)}
    except sqlite3.DatabaseError as exc:
        log.warning("econ_event_news 查询失败（DB 损坏？），按空处理: %s", exc)
        return {}
    finally:
        conn.close()


def _count_econ_rows_strict(db_path=None) -> tuple[int, int]:
    """(`econ_events` 行数, `econ_event_news` 行数)，**不吞锁错误**（纪律同 `_count_rows_strict`）。

    ⚠️ `count_econ_events` 把任何 `DatabaseError`（含 "database is locked"）当 0 行，那是读侧的
    降级语义；而恢复链拿 0 行当"空表"判据 ⇒ 一次瞬时锁就会在非空表上灌备份。锁必须冒出来。
    """
    conn = _connect(db_path)
    try:
        ev = int(conn.execute("SELECT COUNT(*) FROM econ_events").fetchone()[0])
        news = int(conn.execute("SELECT COUNT(*) FROM econ_event_news").fetchone()[0])
        return ev, news
    finally:
        conn.close()


# ---------------------------------------------------- 经济事件表按月备份 / 空表恢复（2026-09-24，B1-4a）

#: 事件表备份文件名前缀 → `econ_events_YYYY-MM.json`（与 `history_YYYY-MM.json` 同目录同纪律）。
#: ⚠️ **两张表并进同一个文件**（plan 字面命名只写了 `econ_events_*`）：`econ_events`（骨架 +
#: 结果值层）与 `econ_event_news`（叙事层）按 `(date, kind)` 强相关，拆成两个文件会在恢复时
#: 出现「骨架已灌、叙事还没灌」的半态；同档还能少一半文件数。
_ECON_BACKUP_PREFIX = "econ_events_"


def _export_econ_backups(bdir: Path, current_month: str, db_path=None) -> list[dict]:
    """事件表按月导出（纪律逐条对齐 history：当月覆盖 / 历史月冻结 / 缺历史月文件自愈）。

    文件结构（与 history 备份同构，另加叙事层两个键）::

        {export_date, month, record_count, records: [{...17 列...}],
         news_record_count, news_records: [[date, kind, news_count, title, link], ...]}

    `records` 用 **dict**（而非 history 的 4 元组列表）：事件有 17 列，dict 自带列名、与
    `_ECON_COLS` 的顺序解耦，将来加列也不会让恢复侧错位。

    返回报告项（形状同 history：`{file, month, rows, action}`，另加 `news_rows`）——
    `rows` = 该月 `econ_events` 行数，`news_rows` = 该月叙事层行数；冻结项一律报 0
    （不读文件，与 history 口径一致）。DB 读不出来 → 记日志返回 []（不抛）。
    """
    try:
        conn = _connect(db_path)
        try:
            months = [r[0] for r in conn.execute(
                "SELECT DISTINCT substr(date, 1, 7) FROM econ_events "
                "UNION SELECT DISTINCT substr(date, 1, 7) FROM econ_event_news ORDER BY 1")]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        log.warning("事件表备份导出失败（DB 损坏？）: %s", exc)
        return []
    all_news = query_event_news(db_path=db_path)      # 表很小：一次取回按月筛（等价于按月各查一次）
    report = []
    for m in months:
        path = bdir / f"{_ECON_BACKUP_PREFIX}{m}.json"
        if m != current_month and path.exists():
            report.append({"file": path.name, "month": m, "rows": 0, "news_rows": 0,
                           "action": "frozen"})
            continue
        records = query_econ_events(start_date=f"{m}-01", end_date=f"{m}-31", db_path=db_path)
        news_rows = [[d, k, v["count"], v["title"], v["link"]]
                     for (d, k), v in sorted(all_news.items()) if d[:7] == m]
        payload = {
            "export_date": datetime.now().astimezone().isoformat(timespec="seconds"),
            "month": m,
            "record_count": len(records),
            "records": records,
            "news_record_count": len(news_rows),
            "news_records": news_rows,
        }
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        report.append({"file": path.name, "month": m, "rows": len(records),
                       "news_rows": len(news_rows), "action": "written"})
    return report


def _insert_econ_records(records, db_path=None) -> int:
    """整行写事件（骨架 + 结果值层**一次写入**），返回写入条数 —— 只给恢复链用。

    ⚠️ 不能改用 `upsert_econ_events` + `update_econ_event_values` 两步：前者的 SQL 有意不碰值层
    （防重新抓取覆盖已落库的值），后者是 `COALESCE` + 现取时间戳 ⇒ 恢复出来的 `value_fetched_at`
    会变成"恢复时刻"、且全空值行会被跳过。备份是**权威快照**，必须原样写回（含 NULL）。
    """
    rows = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        date = str(rec.get("date") or "")
        kind = str(rec.get("kind") or "").strip()
        source = str(rec.get("source") or "").strip()
        if not _DATE_RE.match(date) or not kind or not source:
            log.warning("事件表备份行字段缺失/日期非法，跳过: %r",
                        {k: rec.get(k) for k in ("date", "kind", "source")})
            continue
        row = dict(rec)
        row["title"] = str(rec.get("title") or "")[:300]     # NOT NULL 列：备份缺失也不许炸插入
        rows.append(tuple(row.get(c) for c in _ECON_COLS))
    if not rows:
        return 0
    updatable = [c for c in _ECON_COLS if c not in ("date", "kind", "source")]
    sql = ("INSERT INTO econ_events(%s) VALUES (%s) ON CONFLICT(date, kind, source) DO UPDATE SET %s"
           % (", ".join(_ECON_COLS), ", ".join("?" * len(_ECON_COLS)),
              ", ".join("%s = excluded.%s" % (c, c) for c in updatable)))
    conn = _connect(db_path)
    try:
        with conn:
            conn.executemany(sql, rows)
    finally:
        conn.close()
    return len(rows)


def _restore_econ_backups(bdir: Path, db_path=None) -> int:
    """按文件名（月份）升序合并 backup_dir 下 `econ_events_*.json` → 事件表；返回事件写入行数。

    **仅空表触发**（幂等）：`econ_events` 与 `econ_event_news` 任一张非空即整段跳过（两张表
    同批恢复，避免半态）。判空用 `_count_econ_rows_strict`（不吞异常）—— 一次瞬时锁不是
    "空表"的证据，锁住了就跳过本轮。
    坏文件 / 结构非法 / 行非法一律只记日志跳过，绝不抛（恢复链不得因单个文件中断）。
    """
    try:
        events, news = _count_econ_rows_strict(db_path)
    except sqlite3.DatabaseError as exc:
        log.warning("事件表空表判定失败（库被占用或损坏？），跳过事件表恢复: %s", exc)
        return 0
    if events > 0 or news > 0:
        return 0
    written = 0
    for f in sorted(bdir.glob(f"{_ECON_BACKUP_PREFIX}*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            log.warning("事件表备份解析失败，跳过 %s: %s", f.name, exc)
            continue
        if not isinstance(data, dict):
            log.warning("事件表备份结构非法（非对象），跳过 %s", f.name)
            continue
        written += _insert_econ_records(data.get("records") or [], db_path=db_path)
        news_rows = [tuple(r) for r in (data.get("news_records") or [])
                     if isinstance(r, (list, tuple)) and len(r) == 5]
        if news_rows:
            upsert_event_news(news_rows, db_path=db_path)
    return written
