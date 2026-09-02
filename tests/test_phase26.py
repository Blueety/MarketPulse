"""二十六期：cron 执行后自动 commit + push 的单测（先测后码）。

验证 src/git_ops.auto_commit_push 行为（纯 stdlib，零真实 git / 网络）：
- env 门控（AUTO_PUSH == "0" 关闭且零子进程；缺省 / 非 "0" 启用）
- 无改动跳过（git status --porcelain 空 → 不 commit/push）
- commit message 格式 `auto: {date} {type}`
- push 注入代理 env（http_proxy/https_proxy）且不污染 os.environ
- push 失败（CalledProcessError / TimeoutExpired / FileNotFoundError）→ 返回 False 不抛异常
- root 参数化用 tmp_path，全程 monkeypatch subprocess.run
"""
import os
import subprocess
from pathlib import Path

import pytest

from src import git_ops


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
            "cwd": kw.get("cwd"),
            "env": kw.get("env"),
            "timeout": kw.get("timeout"),
        })
        if args[:2] == ["git", "status"]:
            return _Completed(stdout=state["status_stdout"])
        if args[:2] == ["git", "push"]:
            if state["push_fail"] == "called":
                raise subprocess.CalledProcessError(1, list(args))
            if state["push_fail"] == "timeout":
                raise subprocess.TimeoutExpired(list(args), git_ops._PUSH_TIMEOUT)
            if state["push_fail"] == "filenotfound":
                raise FileNotFoundError("git not found")
        return _Completed()

    monkeypatch.setattr(git_ops.subprocess, "run", _run)
    return calls, state


def _has_call(calls, sub):
    return any(c["args"][1:2] == [sub] for c in calls)


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
    commit = next(c for c in calls if c["args"][1:2] == ["commit"])
    assert commit["args"][1:4] == ["commit", "-m", "auto: 2026-09-02 daily report"]


def test_commit_message_format_snapshot(monkeypatch, fake_git, tmp_path):
    """snapshot 类型：`auto: {date} {market} {time} snapshot`。"""
    calls, state = fake_git
    monkeypatch.delenv("AUTO_PUSH", raising=False)
    state["status_stdout"] = " M context/2026-09-02.json\n"
    git_ops.auto_commit_push("2026-09-02", "a-share midday snapshot", root=tmp_path)
    commit = next(c for c in calls if c["args"][1:2] == ["commit"])
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
    push = next(c for c in calls if c["args"][1:2] == ["push"])
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
