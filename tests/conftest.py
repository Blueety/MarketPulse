"""测试隔离（设计 B）。

collection 前（本模块导入时）强制 CONFIG_PATH 指向不存在文件，使全量测试恒用
内置默认值运行——避免用户定制过的 config.json 在 analyzer/reporter import 时被
快照读入，破坏 classify 边界值 / 90 天滚动 / 30 天窗口等默认断言。
"""
import os
from pathlib import Path

os.environ["CONFIG_PATH"] = str(Path(__file__).parent / "_nonexistent_config.json")

# 二十六期护栏：强制关闭自动推送，防止 test_phase25 等真实调用 daily_report.main()
# 触发的 auto_commit_push 误推 GitHub（AUTO_PUSH=0 → git_ops 直接返回 False，零子进程）。
os.environ["AUTO_PUSH"] = "0"

# 三十一期护栏：pytest 期间禁用 web 启动恢复（S6 restore_if_empty 只在空库触发，
# 但测试可能用空 tmp DB 起 TestClient → 触发真实 data/backup 写入 tmp 之外的库）。
os.environ["MP_SKIP_RESTORE"] = "1"

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import storage  # noqa: E402


class _TmpDb:
    """tmp DB 句柄：.path 供 monkeypatch 断言，.seed(records) 等价旧「写 tmp history.json」。"""

    def __init__(self, path):
        self.path = path

    def seed(self, records):
        """宽记录（history.json 记录形状）→ 长行 upsert（overwrite 模式）。"""
        storage.upsert_history_rows(storage.records_to_rows(records))


import pytest  # noqa: E402


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """tmp SQLite fixture：DB_PATH 单点 patch（storage 函数调用时属性查找）+ 建表。

    等价旧「monkeypatch.setattr(使用方, "HISTORY_FILE", tmp_json) + 写 tmp 文件」的隔离机制；
    三十一期后 history patch 点一律改为本 fixture（或直接 setattr(storage, "DB_PATH", ...)）。
    """
    p = tmp_path / "test-history.db"
    monkeypatch.setattr(storage, "DB_PATH", p)
    storage.init_db()
    return _TmpDb(p)
