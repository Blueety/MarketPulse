"""二十六期：cron 执行后自动 commit + push 的单测（先测后码）。

验证 src/git_ops.auto_commit_push 行为（纯 stdlib，零网络）：
- env 门控（AUTO_PUSH == "0" 关闭且零子进程；缺省 / 非 "0" 启用）
- 无改动跳过（git status --porcelain 空 → 不 commit/push）
- commit message 格式 `auto: {date} {type}`
- push 注入代理 env（http_proxy/https_proxy）且不污染 os.environ
- push 失败（CalledProcessError / TimeoutExpired / FileNotFoundError）→ 返回 False 不抛异常
- root 参数化用 tmp_path，**绝大多数用例 monkeypatch subprocess.run**

⚠️ **例外（2026-09-20，pathspec 修复）**：文件末尾的
`test_commit_pathspec_isolates_unrelated_staged_changes` 用**真临时仓库**跑真 git ——
因为"`git commit -- <paths>` 是否真的只提交这些路径"**只有 git 自己说了算**：
mock 只能证明"我们传了正确实参"，证明不了"git 会照此隔离"。这是刻意的、唯一的一处真实 git。
"""
import os
import subprocess
from pathlib import Path

import pytest

from src import git_ops


def _git_sub(args) -> str | None:
    """从 git 命令列表里取出**子命令**（跳过 `-c key=value` 与其它开关）。"""
    i = 1
    while i < len(args):
        if args[i] == "-c":
            i += 2
            continue
        if args[i].startswith("-"):
            i += 1
            continue
        return args[i]
    return None


@pytest.fixture
def fake_git(monkeypatch):
    """替换 git_ops.subprocess.run 为可控假实现，记录每次调用。"""
    calls = []
    state = {"status_stdout": "", "push_fail": None}

    class _Completed:
        def __init__(self, stdout=""):
            self.stdout = stdout

    def _run(args, *a, **kw):
        calls.append({
            "args": list(args),
            # 规范化出「git 子命令」：`_push` 可能是 `git -c credential.helper=… push`，
            # 按 args[1] 识别会认不出（2026-09-19 实测 3 条用例假红）。
            "sub": _git_sub(list(args)),
            "cwd": kw.get("cwd"),
            "env": kw.get("env"),
            "timeout": kw.get("timeout"),
        })
        if args[:2] == ["git", "status"]:
            # 三十四期：`_has_changes` 改为路径限定（调用形如 git status --porcelain -- <paths>）。
            # 仅当用例显式设置 status_stdout_paths 时才分流 → 既有 11 条用例行为完全不变。
            if "--" in args and "status_stdout_paths" in state:
                return _Completed(stdout=state["status_stdout_paths"])
            return _Completed(stdout=state["status_stdout"])
        # ⚠️ 用 `"push" in args` 而非 `args[:2] == ["git","push"]` 识别 push：
        #    2026-09-19 起 `_push` 会在失败后用 `git -c credential.helper=… push` 重试（兜底姿势），
        #    按前两位匹配会**漏掉兜底那次调用** → 假实现把它当成功 ⇒ "push 失败" 用例假绿。
        if "push" in args:
            if state["push_fail"] == "called":
                # `push_fail_once`：只让**第一次** push 失败（测兜底救回）。判据用"此前是否已 push 过"，
                # 不能 pop 标志位 —— pop 掉之后兜底那次会再次走进 raise 分支（实测踩过）。
                prior_push = any("push" in c["args"] for c in calls[:-1])
                if state.get("push_fail_once") and prior_push:
                    pass
                else:
                    raise subprocess.CalledProcessError(1, list(args))
            elif state["push_fail"] == "timeout":
                raise subprocess.TimeoutExpired(list(args), git_ops._PUSH_TIMEOUT)
            elif state["push_fail"] == "filenotfound":
                raise FileNotFoundError("git not found")
        return _Completed()

    monkeypatch.setattr(git_ops.subprocess, "run", _run)
    return calls, state


def _has_call(calls, sub):
    return any(c.get("sub") == sub for c in calls)


# ---- env 门控 ----

def test_disabled_explicit_zero(monkeypatch, fake_git):
    """AUTO_PUSH == "0" → 直接返回 False，零子进程调用。"""
    calls, _ = fake_git
    monkeypatch.setenv("AUTO_PUSH", "0")
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=Path("/tmp")) is False
    assert calls == []


def test_enabled_by_default_when_unset(monkeypatch, fake_git, tmp_path):
    """缺省（AUTO_PUSH 未设置）→ 启用，有改动时 commit + push。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path) is True
    assert _has_call(calls, "add")
    assert _has_call(calls, "commit")
    assert _has_call(calls, "push")


def test_enabled_when_nonzero(monkeypatch, fake_git, tmp_path):
    """AUTO_PUSH 为非 "0"（如 "1"）→ 启用。"""
    calls, state = fake_git
    monkeypatch.setenv("AUTO_PUSH", "1")
    state["status_stdout"] = " M data/history.json\n"
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path) is True
    assert _has_call(calls, "push")


# ---- 无改动跳过 ----

def test_no_changes_skips(monkeypatch, fake_git, tmp_path, capsys):
    """porcelain 为空 → 返回 False，不 commit/push，打印 skip。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = ""
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path) is False
    assert not _has_call(calls, "add")
    assert not _has_call(calls, "commit")
    assert not _has_call(calls, "push")
    assert "[auto-push] No changes, skipping." in capsys.readouterr().out


# ---- commit message 格式 ----

def test_commit_message_format(monkeypatch, fake_git, tmp_path):
    """commit message 必须为 `auto: {date} {type}`（F5 全 ASCII）。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path)
    commit = next(c for c in calls if c.get("sub") == "commit")
    assert commit["args"][1:4] == ["commit", "-m", "auto: 2026-09-02 daily report"]


def test_commit_message_format_snapshot(monkeypatch, fake_git, tmp_path):
    """snapshot 类型：`auto: {date} {market} {time} snapshot`。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M context/2026-09-02.json\n"
    git_ops.auto_commit_push("2026-09-02", "a-share midday snapshot", root=tmp_path)
    commit = next(c for c in calls if c.get("sub") == "commit")
    assert commit["args"][3] == "auto: 2026-09-02 a-share midday snapshot"


# ---- 代理注入且不污染 os.environ ----

def test_push_injects_proxy_and_no_pollution(monkeypatch, fake_git, tmp_path):
    """push 子进程 env 副本注入代理；全局 os.environ 不被污染。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path)
    push = next(c for c in calls if c.get("sub") == "push")
    assert push["env"]["http_proxy"] == git_ops._PROXY
    assert push["env"]["https_proxy"] == git_ops._PROXY
    # 不污染全局环境
    assert "http_proxy" not in os.environ
    assert "https_proxy" not in os.environ


# ---- push 失败不抛异常 ----

def test_push_failure_calledprocess(monkeypatch, fake_git, tmp_path, capsys):
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    state["push_fail"] = "called"
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path) is False
    assert _has_call(calls, "push")  # push 已尝试
    assert "[auto-push] Failed" in capsys.readouterr().out


def test_push_first_attempt_failure_still_lands(monkeypatch, fake_git, tmp_path, capsys):
    """**新契约（2026-09-19）**：第一次 push 失败但第二次成功 ⇒ 整体算**成功**（返回 True）。

    背景：非交互环境里默认凭据助手取不到凭据 ⇒ 四个 cron 的自动提交只落本地、没推上去（实测现场）。
    现在 `_push` 是**两段尝试**（先 `gh` 凭据助手，再老姿势）⇒ 前一段失败、后一段成功属于正常路径。
    """
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    monkeypatch.setattr(git_ops.shutil, "which", lambda name: "C:/Program Files/GitHub CLI/gh.exe")
    state["status_stdout"] = " M data/marketpulse.db"
    state["push_fail"] = "called"
    state["push_fail_once"] = True
    assert git_ops.auto_commit_push("2026-09-19", "econ-calendar", root=tmp_path) is True
    pushed = [c["args"] for c in calls if "push" in c["args"]]
    assert len(pushed) == 2, pushed                          # 两种姿势各一次
    assert "credential.helper=!" in " ".join(pushed[0])      # 先 gh 凭据助手（实测可用）
    assert pushed[1] == ["git", "push", "origin", "master"]  # 再老姿势兜底


def test_push_failure_timeout(monkeypatch, fake_git, tmp_path, capsys):
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    state["push_fail"] = "timeout"
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path) is False
    assert "[auto-push] Failed" in capsys.readouterr().out


def test_push_failure_filenotfound(monkeypatch, fake_git, tmp_path, capsys):
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    state["push_fail"] = "filenotfound"
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path) is False
    assert "[auto-push] Failed" in capsys.readouterr().out


# ---- root 作为 cwd 传入 ----

def test_root_passed_as_cwd(monkeypatch, fake_git, tmp_path):
    """所有 git 子进程的 cwd 必须等于传入的 root。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path)
    for c in calls:
        assert c["cwd"] == str(tmp_path)


# ---- 三十四期（2026-09-14）：自动提交范围收窄为路径白名单 ----
# G1 内核：任何 cron 都不得把源码/测试/文档的半成品提交入库（原 `git add -A` 会扫走）。
# 真实 git 行为证明见 tasks/2026-09-14-autopush-scope/plan.md §5.3 临时仓库冒烟。

def test_add_uses_path_whitelist(monkeypatch, fake_git, tmp_path):
    """add 必须按白名单逐路径，且**全程不得出现 `-A` / `--all` / `.`**（本方案核心护栏）。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path)
    add = next(c for c in calls if c.get("sub") == "add")
    assert add["args"] == ["git", "add", *git_ops._DATA_PATHS]
    for c in calls:
        for bad in ("-A", "--all", "."):
            assert bad not in c["args"][2:], f"出现全量提交实参 {bad!r}: {c['args']}"


def test_commit_uses_pathspec(monkeypatch, fake_git, tmp_path):
    """commit 必须带 `-- <白名单>`（2026-09-20 pathspec 修复）。

    不带 pathspec 的 `git commit` 提交的是**整个暂存区** ⇒ 别处的 `git rm` / `git mv`
    造成的已暂存删除/重命名会被带走（实测事故）。本用例只钉"实参形状"，
    "git 真的照此隔离"由文件末尾的真仓库行为用例证明。
    """
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path)
    commit = next(c for c in calls if c.get("sub") == "commit")
    assert "--" in commit["args"], "commit 缺 pathspec 分隔符 --"
    assert commit["args"][commit["args"].index("--") + 1:] == list(git_ops._DATA_PATHS)
    for bad in ("-A", "--all", "."):
        assert bad not in commit["args"][2:], "commit 出现全量实参 %r" % bad


def test_status_limited_to_paths(monkeypatch, fake_git, tmp_path):
    """status 必须与 add **同范围**（`--` 之后 == 白名单）—— 否则 R1 语义错标。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M data/history.json\n"
    git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path)
    status = next(c for c in calls if c.get("sub") == "status")
    assert "--" in status["args"]
    assert status["args"][status["args"].index("--") + 1:] == list(git_ops._DATA_PATHS)


def test_source_wip_does_not_trigger_commit(monkeypatch, fake_git, tmp_path):
    """G1 核心：只有源码 WIP（白名单路径内无变更）→ 返回 False、零 commit / 零 push。

    `status_stdout` 模拟**旧实现的全量口径**（有源码改动），`status_stdout_paths` 模拟
    收窄后口径（空）→ 若有人把 `_has_changes` 改回全量，本用例立刻红。
    """
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M web/static/app.js\n"
    state["status_stdout_paths"] = ""
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path) is False
    assert not _has_call(calls, "commit")
    assert not _has_call(calls, "push")


def test_reports_not_in_whitelist():
    """`reports/` 被 .gitignore:40 排除 → 不得进白名单（`git add reports` 会直接抛
    CalledProcessError → 三个入口的数据提交全部失败，且只打一行日志极易漏看，R2）。"""
    assert "reports" not in git_ops._DATA_PATHS
    # 白名单变更必须是有意为之：改这一行即需复核 plan §4.6 / R2
    assert set(git_ops._DATA_PATHS) == {"data", "context", "alerts"}


def test_ignored_only_change_skips(monkeypatch, fake_git, tmp_path):
    """仅被忽略文件变化（如 data/marketpulse.db / -wal）→ porcelain 不可见 → 跳过提交（幂等）。

    真实 git 下"忽略文件不进 porcelain"由 §5.3 冒烟另证（本文件纪律：零真实 git）。
    """
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = ""            # 全量口径下也为空（忽略文件本就不可见）
    state["status_stdout_paths"] = ""
    assert git_ops.auto_commit_push("2026-09-02", "daily report", root=tmp_path) is False
    assert not _has_call(calls, "add")
    assert not _has_call(calls, "commit")


# ---- 行为用例（唯一一处真 git）：pathspec 隔离 -----------------------------------------------
# 背景（2026-09-20 事故）：`git commit`（**不带 pathspec**）提交的是**整个暂存区**，
# 而不是"刚 `git add` 的那些"。`git add <白名单>` 只能**添加**、无法**排除** index 里已有的内容
# ⇒ 别处 `git rm` / `git mv` 造成的**已暂存删除/重命名**会被无差别带走。实测复现见
# tasks/2026-09-20-autopush-pathspec-fix/plan.md §2.2。

def _real_git(root, *args) -> str:
    """在临时仓库里跑真 git（仅本组用例使用；夹具的初始提交才用 `-A`）。"""
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture
def real_repo(tmp_path):
    """白名单三目录 + 一个源码文件的临时真仓库（初始提交已完成、工作区干净）。"""
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "context").mkdir()
    (root / "alerts").mkdir()
    (root / "srcfile.py").write_text("x = 1\n", encoding="utf-8")
    (root / "data" / "d.txt").write_text("1\n", encoding="utf-8")
    (root / "context" / "c.json").write_text("{}\n", encoding="utf-8")
    (root / "alerts" / "a.md").write_text("a\n", encoding="utf-8")
    _real_git(root, "init", "-q", "-b", "main")
    _real_git(root, "config", "user.email", "t@example.com")
    _real_git(root, "config", "user.name", "t")
    _real_git(root, "add", "-A")            # 仅夹具的初始快照用 -A（不是被测代码）
    _real_git(root, "commit", "-q", "-m", "init")
    return root


def test_commit_pathspec_isolates_unrelated_staged_changes(real_repo):
    """🔴 真根因护栏：`git commit -- <paths>` 必须**只**提交白名单路径，index 里其余的已暂存改动原样保留。

    场景复刻 2026-09-20 事故：index 里已有**白名单外**的已暂存改动（`git rm` 直接进 index，
    无需 `git add`），同时白名单内有正常改动 ⇒ 自动提交绝不能把那个删除带走。
    """
    root = real_repo
    _real_git(root, "rm", "-q", "srcfile.py")                        # 白名单外的 staged 删除
    (root / "data" / "d.txt").write_text("2\n", encoding="utf-8")    # 白名单内的改动
    git_ops._commit(root, "2026-09-20", "data sync")

    committed = _real_git(root, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert committed == ["data/d.txt"], "提交内容应只含白名单内的路径，实际 %s" % committed
    assert "D  srcfile.py" in _real_git(root, "status", "--porcelain"), \
        "白名单外的已暂存删除被带走了 ⇒ pathspec 隔离失效"


def test_commit_pathspec_also_carries_unstaged_whitelist_changes(real_repo):
    """另一半语义（R3，**期望行为**）：白名单内**未暂存**的改动也应被提交。

    `_commit` 仍是 `add <paths>` + `commit -- <paths>` 叠加 ⇒ 未暂存的 data 改动照样进提交，
    这样 `_has_changes`（按 pathspec 看工作区）与 `_commit`（按 pathspec 提交）**同口径**。
    """
    root = real_repo
    (root / "data" / "d.txt").write_text("3\n", encoding="utf-8")     # 只改工作区，**不 add**
    git_ops._commit(root, "2026-09-20", "data sync")
    committed = _real_git(root, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert committed == ["data/d.txt"]
    assert _real_git(root, "status", "--porcelain") == ""            # 工作区已干净


# ---- 行为用例（唯一一处真 git）：pathspec 隔离 -----------------------------------------------
# 背景（2026-09-20 事故）：`git commit`（**不带 pathspec**）提交的是**整个暂存区**，
# 而不是"刚 `git add` 的那些"。`git add <白名单>` 只能**添加**、无法**排除** index 里已有的内容
# ⇒ 别处 `git rm` / `git mv` 造成的**已暂存删除/重命名**会被无差别带走。实测复现见
# tasks/2026-09-20-autopush-pathspec-fix/plan.md §2.2。

def _real_git(root, *args) -> str:
    """在临时仓库里跑真 git（仅本组用例使用；夹具的初始提交才用 `-A`）。"""
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture
def real_repo(tmp_path):
    """白名单三目录 + 一个源码文件的临时真仓库（初始提交已完成、工作区干净）。"""
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "context").mkdir()
    (root / "alerts").mkdir()
    (root / "srcfile.py").write_text("x = 1\n", encoding="utf-8")
    (root / "data" / "d.txt").write_text("1\n", encoding="utf-8")
    (root / "context" / "c.json").write_text("{}\n", encoding="utf-8")
    (root / "alerts" / "a.md").write_text("a\n", encoding="utf-8")
    _real_git(root, "init", "-q", "-b", "main")
    _real_git(root, "config", "user.email", "t@example.com")
    _real_git(root, "config", "user.name", "t")
    _real_git(root, "add", "-A")            # 仅夹具的初始快照用 -A（不是被测代码）
    _real_git(root, "commit", "-q", "-m", "init")
    return root


def test_commit_pathspec_isolates_unrelated_staged_changes(real_repo):
    """🔴 真根因护栏：`git commit -- <paths>` 必须**只**提交白名单路径，index 里其余的已暂存改动原样保留。

    场景复刻 2026-09-20 事故：index 里已有**白名单外**的已暂存改动（`git rm` 直接进 index，
    无需 `git add`），同时白名单内有正常改动 ⇒ 自动提交绝不能把那个删除带走。
    """
    root = real_repo
    _real_git(root, "rm", "-q", "srcfile.py")                        # 白名单外的 staged 删除
    (root / "data" / "d.txt").write_text("2\n", encoding="utf-8")    # 白名单内的改动
    git_ops._commit(root, "2026-09-20", "data sync")

    committed = _real_git(root, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert committed == ["data/d.txt"], "提交内容应只含白名单内的路径，实际 %s" % committed
    assert "D  srcfile.py" in _real_git(root, "status", "--porcelain"), \
        "白名单外的已暂存删除被带走了 ⇒ pathspec 隔离失效"


def test_commit_pathspec_also_carries_unstaged_whitelist_changes(real_repo):
    """另一半语义（R3，**期望行为**）：白名单内**未暂存**的改动也应被提交。

    `_commit` 仍是 `add <paths>` + `commit -- <paths>` 叠加 ⇒ 未暂存的 data 改动照样进提交，
    这样 `_has_changes`（按 pathspec 看工作区）与 `_commit`（按 pathspec 提交）**同口径**。
    """
    root = real_repo
    (root / "data" / "d.txt").write_text("3\n", encoding="utf-8")     # 只改工作区，**不 add**
    git_ops._commit(root, "2026-09-20", "data sync")
    committed = _real_git(root, "show", "--name-only", "--pretty=format:", "HEAD").split()
    assert committed == ["data/d.txt"]
    assert _real_git(root, "status", "--porcelain") == ""            # 工作区已干净
