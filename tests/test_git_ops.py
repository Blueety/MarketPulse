"""git_ops 单测：自动提交推送的**推送兜底**与凭据助手构造（2026-09-19）。

背景（实测）：本机默认凭据助手是 PortableGit 的 `helper-selector` → GCM，在**非交互**环境
（cron / 子进程）取不到凭据 ⇒ push 失败 `could not read Username ... terminal prompts disabled`
⇒ 四个 cron 的自动提交**只落到本地**。修法是失败后用 `gh` 凭据助手重试（`gh` 已登录、走 keyring）。
本文件锁住：助手参数构造（含**路径引号**）、无 gh 时不改变行为、失败自动重试、无 gh 时原样抛。
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from src import git_ops as go
from src import storage as st


def test_gh_helper_args_quotes_absolute_path(monkeypatch):
    """`gh` 绝对路径含空格 ⇒ 必须加引号（否则 sh 在空格处切断，实测报 /c/Program: No such file）。"""
    monkeypatch.setattr("shutil.which", lambda name: r"C:\Program Files\GitHub CLI\gh.exe")
    args = go._gh_helper_args()
    assert args[:2] == ["-c", "credential.helper="], args      # 先清空已配置的助手（避免两个助手串联）
    assert args[2] == "-c", args
    assert args[3] == 'credential.helper=!"C:/Program Files/GitHub CLI/gh.exe" auth git-credential', args[3]


def test_gh_helper_args_absent_when_gh_missing(monkeypatch):
    """找不到 gh ⇒ 返回空（保持原有行为，不引入新失败面）。"""
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert go._gh_helper_args() == []


def test_push_prefers_gh_helper_when_available(monkeypatch, tmp_path):
    """有 gh 时**优先**用它（代理 + gh 助手是实测可用姿势：3.8s 成功）。

    老姿势（默认助手）当前必然卡满 120s 再超时 ⇒ 放在后面兜底，避免每天白等 2 分钟。
    """
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(go.subprocess, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: "C:/Program Files/GitHub CLI/gh.exe")
    go._push(tmp_path)
    assert len(calls) == 1, calls
    assert "credential.helper=!" in " ".join(calls[0])
    assert calls[0][-3:] == ["push", "origin", "master"], calls[0]


def test_push_falls_back_to_plain_after_gh_failure(monkeypatch, tmp_path):
    """gh 助手失败（含**超时**）⇒ 退回老姿势；两种失败都必须接住，否则兜底不会执行。"""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd, go._PUSH_TIMEOUT)   # 超时也必须触发兜底
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(go.subprocess, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: "C:/Program Files/GitHub CLI/gh.exe")
    go._push(tmp_path)
    assert len(calls) == 2, calls
    assert "credential.helper=!" in " ".join(calls[0])               # 先 gh 助手
    assert calls[1] == ["git", "push", "origin", "master"], calls[1]  # 再老姿势


def test_push_raises_when_no_gh_available(monkeypatch, tmp_path):
    """没有 gh 可兜底时，原样抛出（不掩盖失败，`auto_commit_push` 捕获后记日志）。"""
    def fake_run(cmd, **kw):
        raise subprocess.CalledProcessError(128, cmd, stderr="boom")

    monkeypatch.setattr(go.subprocess, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(subprocess.CalledProcessError):
        go._push(tmp_path)


def test_push_child_env_forbids_interactive_credentials(monkeypatch, tmp_path):
    """子进程 env 必须禁掉交互式凭据（否则 cron 里 git 会等输入 → 挂死，实测 14 分钟）。"""
    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env") or {}
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(go.subprocess, "run", fake_run)
    go._push(tmp_path)
    assert seen["env"].get("GIT_TERMINAL_PROMPT") == "0"
    assert seen["env"].get("GCM_INTERACTIVE") == "never"
    assert seen["env"].get("http_proxy") == go._PROXY      # 代理仍在（网络只能走 7890）


# ---- B1-4b（D-3）：提交前数据护栏 -------------------------------------------------------------
# 背景：`auto_commit_push` 是**全部推送路径的唯一漏斗**，而 BUG-001 的放大链正是
# 「瞬时锁 → 库被删重建（只剩当日行）→ 空/残库被 add + commit + **push 上线**」。
# 护栏在 `_commit` 之前比"当前库行数 vs HEAD 里那个库的行数"，空库 / 腰斩 / 事件表被清空
# 一律拒绝；同时强制 `wal_checkpoint()`，保证 `-wal` 里的新行落进将要提交的那个 `.db`。
#
# 本组用例用**真 git 临时仓库**（`root=` 指到 tmp_path，外加一个 bare origin 让 push 真的能成功）
# + tmp DB（`storage.DB_PATH` 同步指过去）：绝不碰真实仓库与真实 `data/marketpulse.db`。

def _git(root, *args) -> str:
    """临时仓库里跑真 git（测试助手；生产侧的 git 调用纪律见 `_push` 上方注释）。"""
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, check=True).stdout


def _origin(root: Path) -> Path:
    """夹具创建的 bare origin 路径（与 root 同级）。"""
    return root.parent / "origin.git"


def _seed_history(n: int) -> int:
    """写入 n 行合法日期（2024-01-01 起连续递增），返回写入后行数。"""
    base = date(2024, 1, 1)
    st.upsert_history_rows([((base + timedelta(days=i)).isoformat(), "gspc", float(i), None)
                            for i in range(n)])
    return st.count_rows()


def _commit_all(root) -> str:
    """工作区全量入库（夹具/种子用），返回新 HEAD。"""
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return _git(root, "rev-parse", "HEAD").strip()


def _head_db_rows(root) -> int:
    """`HEAD:data/marketpulse.db` 里的 history 行数（导出成文件再数：仓库里不含 `-wal`）。"""
    with tempfile.TemporaryDirectory(prefix="mp-head-test-") as td:
        copy = Path(td) / "head.db"
        with open(copy, "wb") as fh:
            subprocess.run(["git", "show", "HEAD:data/marketpulse.db"], cwd=str(root),
                           stdout=fh, stderr=subprocess.DEVNULL, check=True)
        return st.count_rows(db_path=copy)


@pytest.fixture
def guard_repo(tmp_path, monkeypatch):
    """真 git 仓库（含 bare origin）+ 仓库内 tmp DB；AUTO_PUSH 打开（conftest 默认关）。"""
    root = tmp_path / "repo"
    for sub in ("data", "context", "alerts"):
        (root / sub).mkdir(parents=True)
        (root / sub / "seed.txt").write_text("seed\n", encoding="utf-8")   # 空目录不入 git，pathspec 会炸
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "master")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    subprocess.run(["git", "init", "-q", "--bare", str(_origin(root))], check=True,
                   capture_output=True)
    _git(root, "remote", "add", "origin", str(_origin(root)))
    _git(root, "push", "-q", "-u", "origin", "master")
    monkeypatch.setattr(st, "DB_PATH", root / "data" / "marketpulse.db")
    monkeypatch.setenv("AUTO_PUSH", "1")        # conftest 全局设 0（防测试真推 GitHub），本组显式打开
    st.init_db()
    return root


def test_guard_refuses_emptied_db(guard_repo, caplog):
    """HEAD 300 行 + 工作区库被清空 → **拒绝**：不产生提交、不推送，HEAD 里的库原样保留。"""
    root = guard_repo
    _seed_history(300)
    st.wal_checkpoint()
    origin_before = _git(_origin(root), "rev-parse", "master").strip()
    head_before = _commit_all(root)
    conn = sqlite3.connect(str(st.DB_PATH))
    conn.execute("DELETE FROM history")
    conn.commit()
    conn.close()
    assert st.count_rows() == 0
    with caplog.at_level(logging.ERROR, logger="marketpulse.git"):
        assert go.auto_commit_push("2026-09-24", "data sync", root=root) is False
    assert _git(root, "rev-parse", "HEAD").strip() == head_before                  # 未产生新提交
    assert "data/marketpulse.db" in _git(root, "status", "--porcelain", "--", "data")  # 改动仍在工作区
    assert _head_db_rows(root) == 300                                             # ★ HEAD 的库未被替换
    assert _git(_origin(root), "rev-parse", "master").strip() == origin_before    # ★ 也没推上去
    assert any(r.levelno >= logging.ERROR for r in caplog.records)                # 拒绝必须留 error 级日志


def test_guard_allows_normal_growth_and_pushes(guard_repo):
    """正常新增行（行数只增不减）→ 照常提交 + 推送。"""
    root = guard_repo
    _seed_history(300)
    st.wal_checkpoint()
    head_before = _commit_all(root)
    _seed_history(310)
    assert go.auto_commit_push("2026-09-24", "data sync", root=root) is True
    head_after = _git(root, "rev-parse", "HEAD").strip()
    assert head_after != head_before
    assert _head_db_rows(root) == 310                                    # ★ 新行随提交入库
    assert _git(_origin(root), "rev-parse", "master").strip() == head_after   # ★ 已推送


def test_guard_releases_when_db_absent_from_head(guard_repo):
    """首次提交：HEAD 里没有 `data/marketpulse.db`（`git show` 必失败）→ 放行，不得卡死。"""
    root = guard_repo
    assert _seed_history(30) == 30
    st.wal_checkpoint()
    assert go.auto_commit_push("2026-09-24", "data sync", root=root) is True
    assert _head_db_rows(root) == 30                                     # 库已随本次提交入库


def test_guard_releases_when_repo_has_no_head(tmp_path, monkeypatch):
    """无 HEAD（全新仓库 / 浅克隆）→ 放行、照常提交（护栏只拦"有据可查的丢失"）。"""
    root = tmp_path / "fresh"
    for sub in ("data", "context", "alerts"):
        (root / sub).mkdir(parents=True)
        (root / sub / "seed.txt").write_text("seed\n", encoding="utf-8")   # 空目录不入 git，pathspec 会炸
    _git(root, "init", "-q", "-b", "master")          # 零提交：`git show HEAD:...` 必失败
    monkeypatch.setattr(st, "DB_PATH", root / "data" / "marketpulse.db")
    monkeypatch.setenv("AUTO_PUSH", "1")
    st.init_db()
    assert _seed_history(5) == 5
    st.wal_checkpoint()
    monkeypatch.setattr(go, "_push", lambda r: None)  # 无 origin：本用例只验"护栏不放拦"
    assert go.auto_commit_push("2026-09-24", "data sync", root=root) is True
    assert _git(root, "rev-parse", "HEAD").strip()


def test_guard_checkpoints_wal_before_commit(guard_repo, tmp_path):
    """提交前 `-wal` 里的新行必须已并入 `.db`（否则推上去的是"少一批行"的库，D-1）。"""
    root = guard_repo
    _seed_history(3)
    st.wal_checkpoint()
    _commit_all(root)
    # 故意留一个连接不关：SQLite 只在**最后一个连接关闭**时自动 checkpoint ⇒ 新行只落在 -wal
    conn = sqlite3.connect(str(st.DB_PATH))
    try:
        conn.execute("INSERT INTO history(date, symbol, value, change) VALUES (?, ?, ?, ?)",
                     ("2026-09-24", "gspc", 9.9, None))
        conn.commit()
        snapshot = tmp_path / "no-wal.db"
        snapshot.write_bytes(st.DB_PATH.read_bytes())
        assert st.count_rows(db_path=snapshot) == 3      # ★ 前置：此刻 .db 里还没有这条新行
        assert go.auto_commit_push("2026-09-24", "data sync", root=root) is True
        assert _head_db_rows(root) == 4                  # ★ checkpoint 生效：新行进了提交
    finally:
        conn.close()


def test_guard_refuses_emptied_event_table(guard_repo, caplog):
    """事件表「HEAD 有行、当前 0 行」同样拒绝（history 一张没少也照拦）。"""
    root = guard_repo
    _seed_history(5)
    st.upsert_econ_events([{"date": "2026-09-01", "kind": "cpi", "title": "CPI", "source": "fed"},
                           {"date": "2026-09-02", "kind": "ppi", "title": "PPI", "source": "fed"}])
    st.wal_checkpoint()
    origin_before = _git(_origin(root), "rev-parse", "master").strip()
    head_before = _commit_all(root)
    conn = sqlite3.connect(str(st.DB_PATH))
    conn.execute("DELETE FROM econ_events")
    conn.commit()
    conn.close()
    assert st.count_econ_events() == 0
    with caplog.at_level(logging.ERROR, logger="marketpulse.git"):
        assert go.auto_commit_push("2026-09-24", "econ-calendar", root=root) is False
    assert _git(root, "rev-parse", "HEAD").strip() == head_before
    assert _git(_origin(root), "rev-parse", "master").strip() == origin_before
    assert any(r.levelno >= logging.ERROR for r in caplog.records)


def test_guard_refuses_sharp_history_drop(guard_repo):
    """行数骤减（HEAD > 200 且当前不足一半）→ 拒绝：这是"事故"而非"裁剪"的判据。"""
    root = guard_repo
    _seed_history(400)
    st.wal_checkpoint()
    head_before = _commit_all(root)
    conn = sqlite3.connect(str(st.DB_PATH))
    conn.execute("DELETE FROM history WHERE date > '2024-02-09'")     # 只留 40 行
    conn.commit()
    conn.close()
    assert 0 < st.count_rows() < 200
    assert go.auto_commit_push("2026-09-24", "data sync", root=root) is False
    assert _git(root, "rev-parse", "HEAD").strip() == head_before
    assert _head_db_rows(root) == 400


def test_guard_allows_mild_prune(guard_repo):
    """阈值取宽：400 → 250 行（未腰斩）属正常裁剪，照常提交。"""
    root = guard_repo
    _seed_history(400)
    st.wal_checkpoint()
    _commit_all(root)
    conn = sqlite3.connect(str(st.DB_PATH))
    conn.execute("DELETE FROM history WHERE date > '2024-09-06'")     # 留 250 行
    conn.commit()
    conn.close()
    assert st.count_rows() == 250
    assert go.auto_commit_push("2026-09-24", "data sync", root=root) is True
    assert _head_db_rows(root) == 250


@pytest.mark.parametrize("head, cur, refused", [
    ((300, 0), (0, 0), True),        # 清空
    ((1, 0), (0, 0), True),          # 哪怕 HEAD 只有 1 行
    ((300, 0), (150, 0), False),     # 恰好一半 → 不算腰斩（边界）
    ((201, 0), (100, 0), True),      # 略高于阈值：100 < 100.5
    ((200, 0), (50, 0), False),      # 未超过绝对下限（阈值取宽的自觉取舍）
    ((0, 5), (0, 0), True),          # 事件表被清空
    ((0, 0), (0, 0), False),         # 两边都空（首次）→ 放行
    ((300, 7), (300, 7), False),     # 一行不差 → 放行
])
def test_row_guard_reason_boundaries(head, cur, refused):
    """行数判据的边界（纯函数）：tuple 均为 (history 行数, econ_events 行数)。"""
    reason = go._row_guard_reason(head, cur)
    assert bool(reason) is refused, f"head={head} cur={cur} → {reason!r}"
