"""MarketPulse cron 执行后自动 commit + push（二十六期）。

daily_report / snapshot_report / opening_analyzer 三个入口在 main() 末尾调用
auto_commit_push(date, report_type)，将本次产生的 data/ / context/ / alerts/ 等变更
add + commit + push 到 origin/master，确保 Railway 部署与最新数据同步。

设计要点（见 tasks/2026-09-02-marketpulse-cron-autopush/plan.md §3）：
- 纯 stdlib（logging/os/subprocess/pathlib），零新依赖（NF1）。
- 开关：env AUTO_PUSH == "0" 时完全跳过，返回 False 且零子进程（默认开启）。
- 无改动（git status --porcelain 为空）跳过，幂等（NF3）。
- push 经 Clash 代理（http_proxy/https_proxy=http://127.0.0.1:7890），仅注入 push
  子进程 env 副本，不污染 os.environ（F3）。
- 每步 subprocess 带 timeout；失败仅 print 日志、返回 False、不抛异常——cron 重试
  由既有 scripts/push_retry.sh + Hermes cron 承担（F6），入口退出码恒 0。
- commit message 全 ASCII：`auto: {date} {report_type}`（F5，规避 Windows cp936 乱码）。
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger("marketpulse.git")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_PROXY = "http://127.0.0.1:7890"
_STATUS_TIMEOUT = 15
_COMMIT_TIMEOUT = 30
_PUSH_TIMEOUT = 120


def _enabled() -> bool:
    """AUTO_PUSH 未设置或 ≠ "0" 时启用（默认开启）。"""
    return os.environ.get("AUTO_PUSH", "") != "0"


def _has_changes(root: Path) -> bool:
    """工作区存在未提交变更（git status --porcelain 非空）。"""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=_STATUS_TIMEOUT,
    )
    return bool(result.stdout.strip())


def _commit(root: Path, date_str: str, report_type: str) -> None:
    """git add -A + git commit -m "auto: {date} {type}"。"""
    msg = f"auto: {date_str} {report_type}"
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True, timeout=_COMMIT_TIMEOUT)
    subprocess.run(["git", "commit", "-m", msg], cwd=str(root), check=True, timeout=_COMMIT_TIMEOUT)


def _push(root: Path) -> None:
    """git push origin master，经 Clash 代理（仅作用于本子进程 env 副本）。"""
    env = os.environ.copy()
    env["http_proxy"] = _PROXY
    env["https_proxy"] = _PROXY
    subprocess.run(
        ["git", "push", "origin", "master"],
        cwd=str(root),
        check=True,
        timeout=_PUSH_TIMEOUT,
        env=env,
    )


def auto_commit_push(date_str: str, report_type: str, root: Path = PROJECT_ROOT) -> bool:
    """将当前仓库变更 commit 并 push 到 origin/master。

    成功返回 True；以下情况返回 False：关闭（AUTO_PUSH=0）/ 无改动 / 任意失败
    （代理黑洞、超时、无 git）。失败仅打印日志，不抛异常（F6 + 退出码恒 0 约定）。
    """
    if not _enabled():
        return False
    try:
        if not _has_changes(root):
            print("[auto-push] No changes, skipping.")
            return False
        _commit(root, date_str, report_type)
        _push(root)
        print(f"[auto-push] Committed and pushed: {date_str} {report_type}")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"[auto-push] Failed: {exc}")
        return False
