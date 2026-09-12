"""analyzer.merge_history 单元测试（不联网，tmp 目录隔离）。

覆盖：新键新建行 / 已有行合并更新且保留他键 / 同日幂等无重复行 /
非 None 过滤 / date 字符串化 / 90 天裁剪 / 临时文件零残留 / 坏文件容错重建。
"""

import pytest

from src import analyzer as an
from src import storage as st


class TestMergeHistory:
    def _set_file(self, tmp_path, monkeypatch):
        """三十一期：JSON 文件隔离 → SQLite tmp DB 隔离（方法名保留以最小化 diff）。"""
        db_path = tmp_path / "test-history.db"
        monkeypatch.setattr(st, "DB_PATH", db_path)
        st.init_db()
        return db_path

    def test_new_date_creates_row_with_defaults(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {"SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0})
        data = an.load_history()
        assert len(data) == 1
        row = data[0]
        assert row["date"] == "2026-09-03"
        assert row["sh"] == 3100.0 and row["sz"] == 10000.0 and row["cyb"] == 2200.0
        # 其余历史键置 None
        for k in ("gspc", "ixic", "vix", "vxn", "move", "gld", "btc"):
            assert row[k] is None

    def test_merge_updates_existing_row_keeps_other_keys(self, tmp_path, monkeypatch):
        # 模拟 A 股收盘已写好 sh/sz/cyb，美股开盘只带 gspc/ixic：
        # 合并后不应抹除 A 股键
        self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {"SH": 3100.0, "SZ": 10000.0, "CYB": 2200.0})
        an.merge_history("2026-09-03", {"GSPC": 4500.0, "IXIC": 17500.0})
        data = an.load_history()
        assert len(data) == 1  # 同一 date，未新增重复行
        row = data[0]
        assert row["sh"] == 3100.0 and row["sz"] == 10000.0 and row["cyb"] == 2200.0
        assert row["gspc"] == 4500.0 and row["ixic"] == 17500.0

    def test_same_day_repeated_merge_idempotent(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {"SH": 3100.0})
        an.merge_history("2026-09-03", {"SH": 3120.0})
        an.merge_history("2026-09-03", {"SH": 3130.0})
        data = an.load_history()
        assert len(data) == 1
        assert data[0]["sh"] == 3130.0

    def test_none_values_not_written(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {"SH": 3100.0, "SZ": None, "GSPC": None})
        row = an.load_history()[0]
        assert row["sh"] == 3100.0
        # 非 None 键不会因 values 中的 None 而被置空
        assert row["sz"] is None  # 新建行默认 None

    def test_ignores_unknown_keys(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {"SH": 3100.0, "FOO": 999.0})
        row = an.load_history()[0]
        assert row["sh"] == 3100.0
        assert "foo" not in row

    def test_case_insensitive_key_normalization(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {"sh": 3100.0, "GsPc": 4500.0})
        row = an.load_history()[0]
        assert row["sh"] == 3100.0 and row["gspc"] == 4500.0

    def test_empty_values_is_noop(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {})
        assert an.load_history() == []
        an.merge_history("2026-09-03", {"SH": None, "SZ": None})
        assert an.load_history() == []

    def test_malformed_date_rejected(self, tmp_path, monkeypatch):
        """三十一期：存储层强制 YYYY-MM-DD——int date 等畸形值不再字符串化入库
        （真实库曾因 20260903 脏行炸掉 web 读侧 strptime，格式护栏优先于旧宽容行为）。"""
        self._set_file(tmp_path, monkeypatch)
        an.merge_history(20260903, {"SH": 3100.0})
        assert an.load_history() == []   # 畸形日期被写入口拦下，不入库

    def test_permanent_retention_no_trim(self, tmp_path, monkeypatch):
        """三十一期：永久保留，不再按 90 天裁剪（旧 test_rolling_90 行为废止）。"""
        from datetime import date, timedelta

        self._set_file(tmp_path, monkeypatch)
        start = date(2026, 1, 1)
        for i in range(95):
            an.append_history(
                {"date": (start + timedelta(days=i)).isoformat(), "vix": 20.0}
            )
        new = (start + timedelta(days=95)).isoformat()
        an.merge_history(new, {"SH": 3100.0})
        data = an.load_history()
        assert len(data) == 96   # 全量保留，无裁剪
        assert data[-1]["date"] == new

    def test_no_tmp_residue(self, tmp_path, monkeypatch):
        db_path = self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {"SH": 3100.0})
        assert not db_path.with_name("test-history.db.tmp").exists()   # 事务原子性，无临时残留

    def test_corrupt_db_rebuilds(self, tmp_path, monkeypatch):
        """坏 DB 文件 → 自愈重建后 merge 落地（语义同旧「坏文件容错重建」）。"""
        db_path = self._set_file(tmp_path, monkeypatch)
        db_path.write_bytes(b"not a sqlite file")
        an.merge_history("2026-09-03", {"SH": 3100.0})
        data = an.load_history()
        assert len(data) == 1
        assert data[0]["date"] == "2026-09-03"


class TestAppendHistoryPreserve:
    """append_history(merge_existing=...) 语义（A 定稿保护）。"""

    def _set_file(self, tmp_path, monkeypatch):
        """三十一期：JSON 文件隔离 → SQLite tmp DB 隔离（方法名保留以最小化 diff）。"""
        db_path = tmp_path / "test-history.db"
        monkeypatch.setattr(st, "DB_PATH", db_path)
        st.init_db()
        return db_path

    def test_merge_existing_preserves_intraday_value(self, tmp_path, monkeypatch):
        # 当日行已有快照写入的美股盘中值（gspc=7727.09）；日报盘中跑 fetch 到 None
        self._set_file(tmp_path, monkeypatch)
        an.append_history({"date": "2026-09-04", "gspc": 7727.09})
        an.append_history({"date": "2026-09-04", "gspc": None}, merge_existing=True)
        row = an.load_history()[-1]
        assert row["gspc"] == 7727.09  # 盘中值保留，未被整行抹空

    def test_merge_existing_false_default_overwrites(self, tmp_path, monkeypatch):
        # 默认 merge_existing=False 保持既有覆盖语义（回归锁）
        self._set_file(tmp_path, monkeypatch)
        an.append_history({"date": "2026-09-04", "gspc": 7727.09})
        an.append_history({"date": "2026-09-04", "gspc": None})
        row = an.load_history()[-1]
        assert row["gspc"] is None

    def test_merge_existing_true_with_real_value_overwrites(self, tmp_path, monkeypatch):
        # fetch 成功（有值）→ 照常定稿覆盖，行为与现状一致
        self._set_file(tmp_path, monkeypatch)
        an.append_history({"date": "2026-09-04", "gspc": 7727.09})
        an.append_history({"date": "2026-09-04", "gspc": 7750.0}, merge_existing=True)
        row = an.load_history()[-1]
        assert row["gspc"] == 7750.0

    def test_merge_existing_true_no_prior_row_creates(self, tmp_path, monkeypatch):
        # 无当日行 + merge_existing=True → 正常新建行、键值照写
        self._set_file(tmp_path, monkeypatch)
        an.append_history({"date": "2026-09-04", "gspc": 7750.0}, merge_existing=True)
        data = an.load_history()
        assert len(data) == 1
        assert data[0]["date"] == "2026-09-04"
        assert data[0]["gspc"] == 7750.0
