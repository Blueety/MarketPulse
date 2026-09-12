"""src/storage.py 单元测试（三十一期：SQLite 存储层，不联网）。

patch 点纪律（有意例外）：storage 函数内 `db_path or DB_PATH` 为调用时属性查找，
monkeypatch.setattr(storage, "DB_PATH", tmp) 单点全局生效。
"""

import json
import sqlite3

import pytest

from src import analyzer as an
from src import storage as st


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
