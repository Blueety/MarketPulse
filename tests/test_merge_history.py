"""analyzer.merge_history 单元测试（不联网，tmp 目录隔离）。

覆盖：新键新建行 / 已有行合并更新且保留他键 / 同日幂等无重复行 /
非 None 过滤 / date 字符串化 / 90 天裁剪 / 临时文件零残留 / 坏文件容错重建。
"""

import json

import pytest

from src import analyzer as an


class TestMergeHistory:
    def _set_file(self, tmp_path, monkeypatch):
        history_file = tmp_path / "history.json"
        monkeypatch.setattr(an, "HISTORY_FILE", history_file)
        return history_file

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

    def test_date_stringified(self, tmp_path, monkeypatch):
        self._set_file(tmp_path, monkeypatch)
        an.merge_history(20260903, {"SH": 3100.0})  # 非字符串 date
        assert an.load_history()[0]["date"] == "20260903"

    def test_rolling_90(self, tmp_path, monkeypatch):
        from datetime import date, timedelta

        self._set_file(tmp_path, monkeypatch)
        start = date(2026, 1, 1)
        # 先以 append 铺 90 条历史
        for i in range(90):
            an.append_history(
                {"date": (start + timedelta(days=i)).isoformat(), "vix": 20.0}
            )
        # 再 merge 一条新日期 → 仍裁剪到 90
        new = (start + timedelta(days=95)).isoformat()
        an.merge_history(new, {"SH": 3100.0})
        data = an.load_history()
        assert len(data) == 90
        assert data[-1]["date"] == new

    def test_no_tmp_residue(self, tmp_path, monkeypatch):
        history_file = self._set_file(tmp_path, monkeypatch)
        an.merge_history("2026-09-03", {"SH": 3100.0})
        assert not history_file.with_name("history.json.tmp").exists()

    def test_corrupt_file_rebuilds(self, tmp_path, monkeypatch):
        history_file = self._set_file(tmp_path, monkeypatch)
        history_file.write_text("{broken", encoding="utf-8")
        an.merge_history("2026-09-03", {"SH": 3100.0})
        data = an.load_history()
        assert len(data) == 1
        assert data[0]["date"] == "2026-09-03"
