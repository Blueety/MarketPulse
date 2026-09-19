"""git_ops 单测：自动提交推送的**推送兜底**与凭据助手构造（2026-09-19）。

背景（实测）：本机默认凭据助手是 PortableGit 的 `helper-selector` → GCM，在**非交互**环境
（cron / 子进程）取不到凭据 ⇒ push 失败 `could not read Username ... terminal prompts disabled`
⇒ 四个 cron 的自动提交**只落到本地**。修法是失败后用 `gh` 凭据助手重试（`gh` 已登录、走 keyring）。
本文件锁住：助手参数构造（含**路径引号**）、无 gh 时不改变行为、失败自动重试、无 gh 时原样抛。
"""

from __future__ import annotations

import subprocess

import pytest

from src import git_ops as go


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
