"""src/storage.py 单元测试（三十一期：SQLite 存储层，不联网）。

patch 点纪律（有意例外）：storage 函数内 `db_path or DB_PATH` 为调用时属性查找，
monkeypatch.setattr(storage, "DB_PATH", tmp) 单点全局生效。
"""

import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from src import analyzer as an
from src import storage as st


def _month_str(offset: int = 0) -> str:
    """相对本月的 `YYYY-MM`（+历史月 / 0 当月）：测试不写死月份，跨月不腐烂。"""
    d = datetime.now().replace(day=1)
    y, m = divmod(d.year * 12 + (d.month - 1) + offset, 12)
    return "%04d-%02d" % (y, m + 1)


def _month_last_day(month: str) -> str:
    """`YYYY-MM` 的月末（下月 1 号的前一天），用于构造"历史月里的一条新日期"。"""
    y, m = int(month[:4]), int(month[5:7])
    nxt = datetime(y + (m == 12), (m % 12) + 1, 1)
    return (nxt - timedelta(days=1)).strftime("%Y-%m-%d")


def _event(date: str, kind: str = "cpi", title: str = "CPI", source: str = "fed", **extra) -> dict:
    """事件行（骨架 + 可选值层，形状同 `query_econ_events` / 备份文件里的 `records` 元素）。"""
    ev = {"date": date, "kind": kind, "title": title, "agency": "BLS", "source": source,
          "time_et": "08:30", "status": "ok", "note": None}
    ev.update(extra)
    return ev


@pytest.fixture
def db(tmp_path, monkeypatch):
    """tmp SQLite + DB_PATH 单点 patch + 建表。"""
    p = tmp_path / "test.db"
    monkeypatch.setattr(st, "DB_PATH", p)
    st.init_db()
    return p


def _rows(dates_values, symbol="gspc"):
    return [(d, symbol, v, None) for d, v in dates_values]


class TestInit:
    def test_init_idempotent_preserves_data(self, db):
        st.upsert_history_rows(_rows([("2026-09-01", 5.0)]))
        st.init_db()  # 重复 init 不清数据
        assert st.count_rows() == 1

    def test_init_creates_wal_mode(self, db):
        conn = sqlite3.connect(str(db))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"


class TestUpsert:
    def test_overwrite_mode_updates_value(self, db):
        st.upsert_history_rows(_rows([("2026-09-01", 5.0)]))
        st.upsert_history_rows(_rows([("2026-09-01", 6.0)]))
        recs = st.rows_to_records(st.query_history())
        assert recs[0]["gspc"] == 6.0

    def test_overwrite_mode_allows_null(self, db):
        st.upsert_history_rows(_rows([("2026-09-01", 5.0)]))
        st.upsert_history_rows(_rows([("2026-09-01", None)]))   # 定稿覆盖：允许写 NULL
        recs = st.rows_to_records(st.query_history())
        assert recs[0]["gspc"] is None

    def test_preserve_mode_keeps_existing_on_null(self, db):
        st.upsert_history_rows(_rows([("2026-09-01", 5.0)]))
        st.upsert_history_rows(_rows([("2026-09-01", None)]), preserve_existing=True)
        recs = st.rows_to_records(st.query_history())
        assert recs[0]["gspc"] == 5.0   # merge_existing 语义：NULL 不抹盘中值

    def test_preserve_mode_updates_real_value(self, db):
        st.upsert_history_rows(_rows([("2026-09-01", 5.0)]))
        st.upsert_history_rows(_rows([("2026-09-01", 7.0)]), preserve_existing=True)
        recs = st.rows_to_records(st.query_history())
        assert recs[0]["gspc"] == 7.0

    def test_per_symbol_rows_independent(self, db):
        """长表下每 symbol 独立行：单 symbol 更新不影响同日他 symbol（27 期纪律结构性成立）。"""
        st.upsert_history_rows([("2026-09-01", "gspc", 5.0, None), ("2026-09-01", "vix", 20.0, None)])
        st.upsert_history_rows([("2026-09-01", "gspc", 6.0, None)], preserve_existing=True)
        recs = st.rows_to_records(st.query_history())
        assert recs[0]["gspc"] == 6.0 and recs[0]["vix"] == 20.0

    def test_empty_rows_noop(self, db):
        assert st.upsert_history_rows([]) == 0
        assert st.count_rows() == 0

    def test_malformed_date_skipped(self, db):
        """int date 等畸形值不入库（web 读侧 strptime 会炸的脏行，在写入口拦下）。"""
        n = st.upsert_history_rows([("20260903", "sh", 1.0, None), ("2026-09-01", "gspc", 2.0, None)])
        assert n == 1
        assert [r[0] for r in st.query_history()] == ["2026-09-01"]

    def test_symbol_lowercased_on_write(self, db):
        st.upsert_history_rows([("2026-09-01", "GSPC", 5.0, None)])
        assert [r[1] for r in st.query_history()] == ["gspc"]


class TestQuery:
    def test_null_roundtrip(self, db):
        st.upsert_history_rows([("2026-09-01", "vix", None, None)])   # NULL 语义：写 None 读 None
        rows = st.query_history(symbols=["vix"])
        assert rows[0][2] is None

    def test_order_by_date_asc(self, db):
        st.upsert_history_rows(_rows([("2026-09-03", 3.0), ("2026-09-01", 1.0), ("2026-09-02", 2.0)]))
        rows = st.query_history()
        assert [r[0] for r in rows] == ["2026-09-01", "2026-09-02", "2026-09-03"]

    def test_symbols_filter_case_insensitive(self, db):
        st.upsert_history_rows([("2026-09-01", "gspc", 1.0, None), ("2026-09-01", "vix", 2.0, None)])
        assert [r[1] for r in st.query_history(symbols=["GSPC"])] == ["gspc"]
        assert len(st.query_history(symbols=["gspc", "VIX"])) == 2

    def test_date_range_filter(self, db):
        st.upsert_history_rows(_rows([("2026-08-31", 1.0), ("2026-09-01", 2.0), ("2026-09-30", 3.0),
                                      ("2026-10-01", 4.0)]))
        rows = st.query_history(start_date="2026-09-01", end_date="2026-09-30")
        assert [r[0] for r in rows] == ["2026-09-01", "2026-09-30"]   # 字符串比较对 YYYY-MM-DD 安全

    def test_empty_db_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(st, "DB_PATH", tmp_path / "fresh.db")
        st.init_db()
        assert st.query_history() == []
        assert st.count_rows() == 0
        assert st.get_date_range() == (None, None)


class TestCorruptDb:
    def test_query_corrupt_returns_empty(self, db):
        db.write_bytes(b"not a sqlite file at all")
        assert st.query_history() == []      # 损坏 → 空历史（纪律同坏 JSON，不崩）
        assert st.count_rows() == 0
        assert st.get_date_range() == (None, None)


class TestConvert:
    def test_rows_to_records_full_keys_and_sort(self, db):
        rows = [("2026-09-02", "gspc", 2.0, None), ("2026-09-01", "vix", 1.0, None)]
        recs = st.rows_to_records(rows)
        assert [r["date"] for r in recs] == ["2026-09-01", "2026-09-02"]
        assert recs[0]["vix"] == 1.0 and recs[0]["gspc"] is None   # 缺键补 None
        assert set(recs[0].keys()) == {"date", *st.HISTORY_KEYS}

    def test_wide_narrow_roundtrip(self):
        records = [{"date": "2026-09-01", "gspc": 1.0, "vix": None}]
        rows = st.records_to_rows(records)
        assert ("2026-09-01", "gspc", 1.0, None) in rows
        assert ("2026-09-01", "vix", None, None) in rows            # None 语义保留
        assert len(rows) == len(st.HISTORY_KEYS)                    # 全键展开
        back = st.rows_to_records(rows)
        assert back[0]["gspc"] == 1.0 and back[0]["vix"] is None

    def test_records_to_rows_skips_no_date(self):
        rows = st.records_to_rows([{"gspc": 1.0}, {"date": "2026-09-01", "gspc": 1.0}])
        assert len(rows) == len(st.HISTORY_KEYS)   # 无 date 记录跳过；有 date 全键展开
        assert ("2026-09-01", "gspc", 1.0, None) in rows

    def test_history_keys_sync_with_analyzer(self):
        """storage.HISTORY_KEYS 与 analyzer._HISTORY_KEYS 同源锁定（漂移即测试红）。"""
        assert tuple(sorted(st.HISTORY_KEYS)) == tuple(sorted(an._HISTORY_KEYS))


class TestMonthlyBackup:
    def test_export_two_months_and_freeze(self, db, tmp_path):
        st.upsert_history_rows(_rows([("2026-08-31", 1.0), ("2026-09-01", 2.0)]))
        bdir = tmp_path / "backup"
        rep = st.export_monthly_backups(backup_dir=bdir)
        assert {r["month"] for r in rep} == {"2026-08", "2026-09"}
        assert (bdir / "history_2026-08.json").exists()
        assert (bdir / "history_2026-09.json").exists()
        aug = json.loads((bdir / "history_2026-08.json").read_text(encoding="utf-8"))
        assert aug["month"] == "2026-08" and aug["record_count"] == 1
        assert aug["records"] == [["2026-08-31", "gspc", 1.0, None]]

    def test_export_current_month_overwrites_history_month_frozen(self, db, tmp_path, monkeypatch):
        bdir = tmp_path / "backup"
        st.upsert_history_rows(_rows([("2026-08-31", 1.0), ("2026-09-01", 2.0)]))
        st.export_monthly_backups(backup_dir=bdir)
        # 历史月数据在 DB 内被改写 → 重导出时 8 月文件冻结不更新；当月文件覆盖
        st.upsert_history_rows(_rows([("2026-08-31", 99.0)]), preserve_existing=True)
        st.upsert_history_rows(_rows([("2026-09-02", 3.0)]))
        rep = st.export_monthly_backups(backup_dir=bdir)
        actions = {r["month"]: r["action"] for r in rep}
        assert actions["2026-08"] == "frozen"
        assert actions["2026-09"] == "written"
        sep = json.loads((bdir / "history_2026-09.json").read_text(encoding="utf-8"))
        assert sep["record_count"] == 2   # 当月覆盖为最新 2 行

    def test_export_missing_historical_month_selfheals(self, db, tmp_path):
        """历史月文件缺失 → 从 DB 补写（自愈规则，D1）。"""
        st.upsert_history_rows(_rows([("2026-08-31", 1.0)]))
        bdir = tmp_path / "backup"
        st.export_monthly_backups(backup_dir=bdir)
        (bdir / "history_2026-08.json").unlink()
        rep = st.export_monthly_backups(backup_dir=bdir)
        actions = {r["month"]: r["action"] for r in rep}
        assert actions["2026-08"] == "written"   # 缺失即补，即便已非当月
        assert (bdir / "history_2026-08.json").exists()


class TestRestore:
    def test_non_empty_db_untouched(self, db, tmp_path):
        st.upsert_history_rows(_rows([("2026-09-01", 5.0)]))
        bdir = tmp_path / "backup"
        bdir.mkdir()
        (bdir / "history_2026-08.json").write_text(json.dumps(
            {"month": "2026-08", "records": [["2026-08-31", "gspc", 99.0, None]]}), encoding="utf-8")
        assert st.restore_if_empty(backup_dir=bdir) == "db"
        assert st.count_rows() == 1   # 幂等：非空库不动作

    def test_restore_from_backup_ascending_merge(self, db, tmp_path):
        bdir = tmp_path / "backup"
        bdir.mkdir()
        # 文件名乱序写入，验证按文件名（月份）升序合并
        (bdir / "history_2026-09.json").write_text(json.dumps(
            {"month": "2026-09", "records": [["2026-09-01", "gspc", 2.0, None]]}), encoding="utf-8")
        (bdir / "history_2026-08.json").write_text(json.dumps(
            {"month": "2026-08", "records": [["2026-08-31", "gspc", 1.0, None]]}), encoding="utf-8")
        assert st.restore_if_empty(backup_dir=bdir) == "backup"
        rows = st.query_history()
        assert [r[0] for r in rows] == ["2026-08-31", "2026-09-01"]
        assert [r[2] for r in rows] == [1.0, 2.0]

    def test_restore_falls_back_to_legacy_json(self, db, tmp_path, monkeypatch):
        bdir = tmp_path / "backup"
        monkeypatch.setattr(st, "DEFAULT_BACKUP_DIR", bdir)   # 无备份目录
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps([
            {"date": "2026-09-01", "gspc": 1.0, "vix": None},
            {"date": "2026-09-02", "gspc": 2.0, "vix": 21.0},
        ]), encoding="utf-8")
        monkeypatch.setattr(st, "DATA_DIR", tmp_path)         # legacy 固定读 DATA_DIR/history.json
        (tmp_path / "history.json").write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        assert st.restore_if_empty(backup_dir=bdir) == "json"
        recs = st.rows_to_records(st.query_history())
        assert recs[0]["gspc"] == 1.0 and recs[0]["vix"] is None
        assert recs[1]["vix"] == 21.0

    def test_restore_all_missing_returns_empty(self, db, tmp_path, monkeypatch):
        monkeypatch.setattr(st, "DEFAULT_BACKUP_DIR", tmp_path / "no-backup")
        monkeypatch.setattr(st, "DATA_DIR", tmp_path / "no-data")
        assert st.restore_if_empty() == "empty"
        assert st.count_rows() == 0   # 全缺失 → 空库不崩（页面「数据暂缺」）

    def test_restore_skips_corrupt_backup_file(self, db, tmp_path):
        bdir = tmp_path / "backup"
        bdir.mkdir()
        (bdir / "history_2026-08.json").write_text("{broken", encoding="utf-8")
        (bdir / "history_2026-09.json").write_text(json.dumps(
            {"month": "2026-09", "records": [["2026-09-01", "gspc", 2.0, None]]}), encoding="utf-8")
        assert st.restore_if_empty(backup_dir=bdir) == "backup"
        assert [r[0] for r in st.query_history()] == ["2026-09-01"]   # 坏文件跳过继续


class TestBug001LockIsNotCorruption:
    """BUG-001（2026-09-24，致命）：**瞬时锁不得被判成"库损坏"→ 删库**。

    旧实现 `except sqlite3.DatabaseError` 按**父类**捕获，而 `OperationalError`（"database is
    locked"）⊂ `DatabaseError` ⇒ 双进程撞锁（snapshot cron / 外部 */5 提交 / 日历同步）时
    整个生产库（2715 行 / 272 个日期）被 `unlink` 后重建，只剩当日行；随后被 auto-push
    带上线。同族第二个坑：`count_rows` 把锁也当"0 行"，`restore_if_empty` 据此在**非空库**上灌备份。

    注入点说明：直接 monkeypatch `analyzer.upsert_history_rows`（analyzer 调用的那个名字）
    —— 这是"锁"发生的**真实边界**，且不依赖 10s busy_timeout（真锁要等 10s 才抛，测试不能那么慢）。
    """

    @staticmethod
    def _seed(db):
        st.upsert_history_rows(_rows([("2026-09-01", 1.0), ("2026-09-02", 2.0)]))

    @staticmethod
    def _dates():
        """长表下 `append_history` 一次写 10 个符号行 ⇒ 断言**日期集合**（不是行数）。"""
        return sorted({r[0] for r in st.query_history()})

    @staticmethod
    def _gspc():
        return [r[2] for r in st.query_history(symbols=["gspc"])]

    def test_lock_then_success_keeps_old_rows(self, db, monkeypatch):
        """一次瞬时锁 → 退避重试后写入成功，**旧行一行不少**（旧实现会把库删掉）。"""
        self._seed(db)
        real = an.upsert_history_rows
        calls = {"n": 0}

        def flaky(rows, preserve_existing=False, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is locked")
            return real(rows, preserve_existing=preserve_existing, **kw)

        monkeypatch.setattr(an, "upsert_history_rows", flaky)
        monkeypatch.setattr(an, "_LOCK_RETRY_DELAYS", (0.0,))
        an.append_history({"date": "2026-09-03", "gspc": 3.0})
        assert calls["n"] == 2, "锁冲突必须重试"
        assert self._dates() == ["2026-09-01", "2026-09-02", "2026-09-03"]   # ★ 旧日期仍在
        assert self._gspc() == [1.0, 2.0, 3.0]                               # ★ 旧值未被抹
        assert db.exists() and not list(db.parent.glob("*.corrupt-*"))       # 未删库、未留档

    def test_persistent_lock_raises_without_touching_db(self, db, monkeypatch):
        """锁持续存在 → 退避用尽后**抛出**（三入口必须感知），库与数据原样不动。"""
        self._seed(db)

        def always_locked(rows, preserve_existing=False, **kw):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(an, "upsert_history_rows", always_locked)
        monkeypatch.setattr(an, "_LOCK_RETRY_DELAYS", (0.0, 0.0, 0.0))
        with pytest.raises(sqlite3.OperationalError):
            an.append_history({"date": "2026-09-03", "gspc": 3.0})
        assert self._dates() == ["2026-09-01", "2026-09-02"]
        assert self._gspc() == [1.0, 2.0]
        assert db.exists() and not list(db.parent.glob("*.corrupt-*"))

    def test_busy_error_also_retries(self, db, monkeypatch):
        """`database is busy` 同属可重试类（不同 SQLite 版本的措辞差异）。"""
        self._seed(db)
        real = an.upsert_history_rows
        calls = {"n": 0}

        def flaky(rows, preserve_existing=False, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise sqlite3.OperationalError("database is busy")
            return real(rows, preserve_existing=preserve_existing, **kw)

        monkeypatch.setattr(an, "upsert_history_rows", flaky)
        monkeypatch.setattr(an, "_LOCK_RETRY_DELAYS", (0.0,))
        an.append_history({"date": "2026-09-03", "gspc": 3.0})
        assert self._dates() == ["2026-09-01", "2026-09-02", "2026-09-03"]

    def test_real_corruption_is_quarantined_not_deleted(self, db, monkeypatch):
        """真损坏（文件非 SQLite）→ 原库**改名留档** `.corrupt-<ts>` 后重建，绝 `unlink`。"""
        self._seed(db)
        garbage = b"this is not a sqlite database" * 64
        db.write_bytes(garbage)                        # 就地破坏
        monkeypatch.setattr(an, "_LOCK_RETRY_DELAYS", (0.0,))
        an.append_history({"date": "2026-09-04", "gspc": 4.0})
        kept = sorted(db.parent.glob("test.db.corrupt-*"))
        assert len(kept) == 1, "损坏库必须留档"
        assert kept[0].read_bytes() == garbage, "留档必须是原始字节（可事后人工提取）"
        assert self._dates() == ["2026-09-04"]         # 重建后可写

    def test_non_lock_operational_error_is_not_rebuilt(self, db, monkeypatch):
        """非锁类 `OperationalError`（如只读库）→ 原样抛出，**不重建**（不能拿"不认识的错"当损坏）。"""
        self._seed(db)

        def readonly(rows, preserve_existing=False, **kw):
            raise sqlite3.OperationalError("attempt to write a readonly database")

        monkeypatch.setattr(an, "upsert_history_rows", readonly)
        monkeypatch.setattr(an, "_LOCK_RETRY_DELAYS", (0.0,))
        with pytest.raises(sqlite3.OperationalError):
            an.append_history({"date": "2026-09-03", "gspc": 3.0})
        assert db.exists() and not list(db.parent.glob("*.corrupt-*"))
        assert self._dates() == ["2026-09-01", "2026-09-02"]

    def test_quarantine_failure_leaves_db_untouched(self, db, monkeypatch):
        """Windows 现实：他进程持有 `-wal` ⇒ `os.replace` 抛 `PermissionError`。
        必须**放弃重建并抛出**，一个字节都不许删（旧实现会在 unlink 处崩且可能删掉一半）。"""
        self._seed(db)
        db.write_bytes(b"broken-not-sqlite" * 32)

        def deny(*a, **kw):
            raise PermissionError(32, "The process cannot access the file")

        monkeypatch.setattr(an.os, "replace", deny)
        with pytest.raises(PermissionError):
            an.append_history({"date": "2026-09-04", "gspc": 4.0})
        assert db.read_bytes() == b"broken-not-sqlite" * 32     # 原文件仍在
        assert not list(db.parent.glob("*.corrupt-*"))

    def test_restore_skipped_when_db_locked(self, db, tmp_path, monkeypatch):
        """锁不是"库是空的"的证据：`restore_if_empty` 不得因此往非空库灌备份。"""
        self._seed(db)
        bdir = tmp_path / "backup"
        bdir.mkdir()
        (bdir / "history_2026-08.json").write_text(json.dumps(
            {"month": "2026-08", "records": [["2026-08-31", "gspc", 99.0, None]]}), encoding="utf-8")

        def locked(*a, **kw):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(st, "_count_rows_strict", locked)
        assert st.restore_if_empty(backup_dir=bdir) == "db"
        assert self._dates() == ["2026-09-01", "2026-09-02"]     # 备份行未被灌进来
        assert 99.0 not in self._gspc()

    def test_missing_db_file_still_triggers_restore(self, tmp_path, monkeypatch):
        """🔴 回归（B1Guard 探针 2026-09-24 发现）：**DB 文件根本不存在**时恢复链必须照旧执行。

        `_connect` 会把不存在的路径建成空文件 ⇒ `SELECT COUNT(*) FROM history` 抛
        `no such table: history`。若把这类错误也当「本轮不动作」，全新部署（Railway 临时文件系统 /
        将来把 DB 从 git 摘掉）会**静默不恢复**、页面一路「数据暂缺」——B0 的锁守卫一度误伤此路。
        """
        monkeypatch.setattr(st, "DB_PATH", tmp_path / "fresh.db")     # 故意不存在
        bdir = tmp_path / "backup"
        bdir.mkdir()
        (bdir / "history_2026-09.json").write_text(json.dumps(
            {"month": "2026-09", "records": [["2026-09-01", "gspc", 2.0, None]]}), encoding="utf-8")
        assert st.restore_if_empty(backup_dir=bdir) == "backup"
        assert self._dates() == ["2026-09-01"]
        assert self._gspc() == [2.0]

    def test_is_lock_error_classification(self):
        assert st.is_lock_error(sqlite3.OperationalError("database is locked")) is True
        assert st.is_lock_error(sqlite3.OperationalError("database table is locked")) is True
        assert st.is_lock_error(sqlite3.OperationalError("database is busy")) is True
        assert st.is_lock_error(sqlite3.OperationalError("no such table: history")) is False
        assert st.is_lock_error(sqlite3.DatabaseError("file is not a database")) is False
        assert st.is_lock_error(OSError("boom")) is False


class TestEconMonthlyBackup:
    """B1-4a（D-3）：经济事件两张表纳入按月备份 / 空表恢复。

    修复前 `export_monthly_backups` 只导 `history_*`、`restore_if_empty` 也只恢复 history ⇒
    `econ_events`（骨架 + 结果值层）与 `econ_event_news`（叙事层）**无任何备份/恢复路径**：
    Railway 的临时文件系统下一重建库，整块经济日历数据就永久消失（备份链是线上的主数据源）。
    """

    @staticmethod
    def _seed_events():
        """上月 2 条 + 本月 1 条事件（带结果值层）+ 本月 1 条叙事层。"""
        prev, this = _month_str(-1), _month_str(0)
        st.upsert_econ_events([
            _event(f"{prev}-05", kind="cpi"),
            _event(f"{prev}-10", kind="ppi"),
            _event(f"{this}-01", kind="cpi"),
        ])
        st.update_econ_event_values([{"date": f"{this}-01", "kind": "cpi", "actual": 3.1,
                                      "forecast": 3.0, "unit": "%", "value_source": "tradingview"}])
        st.upsert_event_news([(f"{this}-01", "cpi", 4, "CPI 前瞻", "https://example.com/a")])

    def test_export_writes_econ_file_with_db_row_counts(self, db, tmp_path):
        """产出 `econ_events_YYYY-MM.json`，行数/内容与库一致（含值层与叙事层）。"""
        self._seed_events()
        bdir = tmp_path / "backup"
        rep = {r["file"]: r for r in st.export_monthly_backups(backup_dir=bdir)}
        this, prev = _month_str(0), _month_str(-1)
        cur = json.loads((bdir / f"econ_events_{this}.json").read_text(encoding="utf-8"))
        old = json.loads((bdir / f"econ_events_{prev}.json").read_text(encoding="utf-8"))
        assert cur["record_count"] == 1 and old["record_count"] == 2      # ★ 与库一致
        assert [r["date"] for r in cur["records"]] == [f"{this}-01"]
        assert cur["records"][0]["actual"] == 3.1 and cur["records"][0]["unit"] == "%"   # ★ 值层一并归档
        assert cur["news_record_count"] == 1
        assert cur["news_records"] == [[f"{this}-01", "cpi", 4, "CPI 前瞻", "https://example.com/a"]]
        assert rep[f"econ_events_{this}.json"]["rows"] == 1
        assert rep[f"econ_events_{prev}.json"]["rows"] == 2

    def test_export_econ_current_overwrites_history_month_frozen(self, db, tmp_path):
        """当月覆盖 / 历史月冻结（与 history 同纪律），历史月文件缺失则自愈补写。"""
        self._seed_events()
        bdir = tmp_path / "backup"
        st.export_monthly_backups(backup_dir=bdir)
        this, prev = _month_str(0), _month_str(-1)
        frozen_before = (bdir / f"econ_events_{prev}.json").read_bytes()
        st.upsert_econ_events([_event(_month_last_day(prev), kind="cpi", title="改期后的标题")])
        st.upsert_econ_events([_event(f"{this}-02", kind="ppi")])
        rep = {r["file"]: r for r in st.export_monthly_backups(backup_dir=bdir)}
        assert rep[f"econ_events_{prev}.json"]["action"] == "frozen"
        assert rep[f"econ_events_{this}.json"]["action"] == "written"
        assert (bdir / f"econ_events_{prev}.json").read_bytes() == frozen_before      # ★ 历史月冻结
        cur = json.loads((bdir / f"econ_events_{this}.json").read_text(encoding="utf-8"))
        assert cur["record_count"] == 2                                              # ★ 当月覆盖为最新
        (bdir / f"econ_events_{prev}.json").unlink()
        rep2 = {r["file"]: r for r in st.export_monthly_backups(backup_dir=bdir)}
        assert rep2[f"econ_events_{prev}.json"]["action"] == "written"                # 缺失即补（自愈）
        assert rep2[f"econ_events_{prev}.json"]["rows"] == 3

    def test_export_econ_failure_keeps_history_report(self, db, tmp_path):
        """事件表读不出来（旧库没这两张表）→ 只记日志，history 备份报告照常返回（不抛）。"""
        st.upsert_history_rows(_rows([(f"{_month_str(0)}-01", 1.0)]))
        conn = sqlite3.connect(str(db))
        conn.executescript("DROP TABLE econ_events; DROP TABLE econ_event_news;")
        conn.commit()
        conn.close()
        rep = st.export_monthly_backups(backup_dir=tmp_path / "backup")
        assert [r["file"] for r in rep] == [f"history_{_month_str(0)}.json"]
        assert rep[0]["action"] == "written"

    def test_restore_events_into_empty_tables(self, db, tmp_path, monkeypatch):
        """空表 → 从 `econ_events_*.json` 恢复事件（含值层原样）与叙事层。"""
        monkeypatch.setattr(st, "DATA_DIR", tmp_path / "no-legacy")    # 隔离真实 data/history.json
        prev = _month_str(-1)
        bdir = tmp_path / "backup"
        bdir.mkdir()
        (bdir / f"econ_events_{prev}.json").write_text(json.dumps({
            "month": prev, "record_count": 1,
            "records": [_event(f"{prev}-05", actual=2.9, value_source="tradingview",
                               value_fetched_at="2026-01-01T00:00:00")],
            "news_records": [[f"{prev}-05", "cpi", 2, "标题", "https://example.com/n"]],
        }, ensure_ascii=False), encoding="utf-8")
        assert st.restore_if_empty(backup_dir=bdir) == "backup"
        rows = st.query_econ_events()
        assert [(r["date"], r["kind"]) for r in rows] == [(f"{prev}-05", "cpi")]
        assert rows[0]["actual"] == 2.9                                    # ★ 值层写回
        assert rows[0]["value_fetched_at"] == "2026-01-01T00:00:00"         # ★ 不是"恢复时刻"
        assert st.query_event_news()[(f"{prev}-05", "cpi")]["count"] == 2   # ★ 叙事层同批恢复

    def test_restore_events_is_idempotent_when_table_not_empty(self, db, tmp_path, monkeypatch):
        """非空事件表不动作（幂等）：库里的行绝不被备份覆盖。"""
        monkeypatch.setattr(st, "DATA_DIR", tmp_path / "no-legacy")
        this = _month_str(0)
        st.upsert_econ_events([_event(f"{this}-01", title="库里的")])
        bdir = tmp_path / "backup"
        bdir.mkdir()
        (bdir / f"econ_events_{this}.json").write_text(json.dumps(
            {"month": this, "records": [_event(f"{this}-01", title="备份里的")]},
            ensure_ascii=False), encoding="utf-8")
        assert st.restore_if_empty(backup_dir=bdir) == "empty"    # history 仍空（返回值是 history 链语义）
        assert [r["title"] for r in st.query_econ_events()] == ["库里的"]
        st.upsert_history_rows(_rows([(f"{this}-01", 1.0)]))      # history 非空 → 连门都进不去
        assert st.restore_if_empty(backup_dir=bdir) == "db"
        assert [r["title"] for r in st.query_econ_events()] == ["库里的"]

    def test_restore_events_skips_corrupt_backup_file(self, db, tmp_path, monkeypatch):
        """坏备份文件跳过继续（恢复链不得因单个文件中断）。"""
        monkeypatch.setattr(st, "DATA_DIR", tmp_path / "no-legacy")
        this, prev = _month_str(0), _month_str(-1)
        bdir = tmp_path / "backup"
        bdir.mkdir()
        (bdir / f"econ_events_{prev}.json").write_text("{broken", encoding="utf-8")
        (bdir / f"econ_events_{this}.json").write_text(json.dumps(
            {"month": this, "records": [_event(f"{this}-01")]}, ensure_ascii=False), encoding="utf-8")
        assert st.restore_if_empty(backup_dir=bdir) == "backup"
        assert [r["date"] for r in st.query_econ_events()] == [f"{this}-01"]

    def test_restore_events_skipped_when_db_locked(self, db, tmp_path, monkeypatch):
        """瞬时锁不是"空表"的证据：判空抛错 → 跳过本轮事件表恢复（一行都不写）。"""
        monkeypatch.setattr(st, "DATA_DIR", tmp_path / "no-legacy")
        bdir = tmp_path / "backup"
        bdir.mkdir()
        (bdir / f"econ_events_{_month_str(0)}.json").write_text(json.dumps(
            {"records": [_event(f"{_month_str(0)}-01")]}, ensure_ascii=False), encoding="utf-8")

        def locked(*a, **kw):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(st, "_count_econ_rows_strict", locked)
        assert st.restore_if_empty(backup_dir=bdir) == "empty"
        assert st.query_econ_events() == []
