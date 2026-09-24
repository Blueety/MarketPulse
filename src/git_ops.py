"""MarketPulse cron 执行后自动 commit + push（二十六期）。

daily_report / snapshot_report / opening_analyzer 三个入口在 main() 末尾调用
auto_commit_push(date, report_type)，将本次产生的 data/ / context/ / alerts/ 等变更
add + commit + push 到 origin/master，确保 Railway 部署与最新数据同步。

设计要点（见 tasks/2026-09-02-marketpulse-cron-autopush/plan.md §3）：
- 纯 stdlib（logging/os/subprocess/pathlib），零新依赖（NF1）。
- **提交范围 = 路径白名单 `_DATA_PATHS`（data / context / alerts），禁止 `-A` / `--all` / `.`**：
  `git add -A` 会扫走工作区里正在写的源码/测试/文档半成品（2026-09-14 实测被外部 cron 多次
  扫走，见 tasks/2026-09-14-autopush-scope/plan.md §3.2）。`_commit` 与 `_has_changes` 必须
  **同范围** —— 只收窄 add 不收窄 status，会让"仅源码 WIP"时日志误报 `Failed`、返回值语义错标。
- 开关：env AUTO_PUSH == "0" 时完全跳过，返回 False 且零子进程（默认开启）。
- 无改动（`git status --porcelain -- <白名单>` 为空）跳过，幂等（NF3）。
- push 经 Clash 代理（http_proxy/https_proxy=http://127.0.0.1:7890），仅注入 push
  子进程 env 副本，不污染 os.environ（F3）。
- 每步 subprocess 带 timeout；失败仅 print 日志、返回 False、不抛异常——cron 重试
  由既有 scripts/push_retry.sh + Hermes cron 承担（F6），入口退出码恒 0。
- commit message 全 ASCII：`auto: {date} {report_type}`（F5，规避 Windows cp936 乱码）。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from src import storage

logger = logging.getLogger("marketpulse.git")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_PROXY = "http://127.0.0.1:7890"
_STATUS_TIMEOUT = 15
_COMMIT_TIMEOUT = 30
_PUSH_TIMEOUT = 120

# 自动提交范围白名单（三十四期，2026-09-14）：只有本次运行会产出的数据目录可被自动入库。
# - `reports/` **有意排除**：它被 .gitignore:40 排除，而 gitingore 命中的路径**不能**作 `git add`
#   的显式 pathspec（会直接抛 `The following paths are ignored…` → 三个入口的数据提交全挂）。
# - 顺序即 `git add` 的实参顺序，测试 test_add_uses_path_whitelist 钉死。
_DATA_PATHS: tuple[str, ...] = ("data", "context", "alerts")

# ---- 提交前数据护栏（2026-09-24，D-3 / B1-4b）------------------------------------------
#: 守卫目标：仓库里**将要被提交的那个** DB 文件（相对于 `root`）。刻意不取
#: `storage.DB_PATH` 的模块默认值 —— 护栏守的是"这个仓库要推上去的库"，`root=` 指到临时
#: 仓库时（测试）就不该去碰进程外那个真实库。
_DB_REL = "data/marketpulse.db"

#: 骤减判据：HEAD 行数超过 `_DROP_MIN_ROWS` 且当前不足其 `_DROP_RATIO` → 拒绝。
#: （历史裁剪的正当代价远小于"删库上线"，阈值取宽：只有"腰斩"才拦。）
_DROP_MIN_ROWS = 200
_DROP_RATIO = 0.5


def _enabled() -> bool:
    """AUTO_PUSH 未设置或 ≠ "0" 时启用（默认开启）。"""
    return os.environ.get("AUTO_PUSH", "") != "0"


def _has_changes(root: Path, paths: tuple[str, ...] = _DATA_PATHS) -> bool:
    """**目标路径内**存在未提交变更（`git status --porcelain -- <paths>` 非空）。

    必须与 `_commit` 的 add 同范围（R1）：若此处全量、add 收窄，则"只有源码 WIP"时会判定
    "有改动" → add 无可暂存内容 → commit 报 nothing to commit → 日志出现误导性
    `[auto-push] Failed`，且返回值语义从"数据没变"错标成"提交失败"。
    """
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=_STATUS_TIMEOUT,
    )
    return bool(result.stdout.strip())


def _commit(root: Path, date_str: str, report_type: str, paths: tuple[str, ...] = _DATA_PATHS) -> None:
    """`git add <白名单路径>` + `git commit -m "auto: {date} {type}" -- <白名单路径>`。

    **禁止** `-A` / `--all` / `.`（全量会把源码/测试/文档半成品一并入库）；
    范围由 tests/test_phase26.py::test_add_uses_path_whitelist 钉死。

    🔴 **为什么 commit 也必须带 pathspec（2026-09-20 修复）**：
    `git commit`（**不带 pathspec**）提交的是**整个暂存区（index）**，而不是"刚 `git add` 的那些"。
    `git add <paths>` 只能**添加**，无法**排除** index 里已有的内容 ⇒ 别处 `git rm` / `git mv`
    造成的**已暂存删除/重命名**会被无差别带走（实测事故：架构师的 `git rm` 4 文件被外部 cron
    的自动提交一起提交了）。加上 `-- <paths>` 后，git 只提交这些路径，**index 里其余已暂存改动原样保留**。

    另一半语义（有意保留）：`commit -- <paths>` 会把白名单内**未暂存**的改动也一并提交
    ⇒ `add` 仍然需要，两者叠加才让 `_has_changes`（按 pathspec 看工作区）与 `_commit` 同口径。
    行为护栏：test_phase26.py 的 `test_commit_pathspec_isolates_unrelated_staged_changes`
    （真临时仓库，唯一一处真 git）。
    """
    msg = f"auto: {date_str} {report_type}"
    subprocess.run(["git", "add", *paths], cwd=str(root), check=True, timeout=_COMMIT_TIMEOUT)
    subprocess.run(["git", "commit", "-m", msg, "--", *paths],
                   cwd=str(root), check=True, timeout=_COMMIT_TIMEOUT)


def _gh_helper_args() -> list[str]:
    """`gh` 凭据助手参数：`-c credential.helper= -c credential.helper=!<gh> auth git-credential`。

    ⚠️ **为什么需要它（2026-09-19 实测）**：本机默认凭据助手是 PortableGit 的 `helper-selector`
    → 走 GCM（.NET），在**非交互**环境（cron / 子进程）里取不到凭据，push 直接失败：
    `fatal: could not read Username for 'https://github.com': terminal prompts disabled`
    —— 结果是**四个 cron 的自动提交全部只落到本地、没推上去**（远端之所以是最新的，
    只是因为人工推送把本地提交顺带带上去了）。
    本机 `gh` CLI 已登录（keyring），用它的凭据助手可在非交互下静默取到凭据。

    - 取**绝对路径并加引号**：cron 的 PATH 可能没有 `C:\\Program Files\\GitHub CLI`，
      而路径含空格 ⇒ 不加引号会被 sh 在空格处切断（实测报 `/c/Program: No such file`）。
    - 找不到 `gh` → 返回 `[]`（不改变原有行为，只放弃兜底）。
    """
    exe = shutil.which("gh")
    if not exe:
        return []
    quoted = '"%s"' % str(exe).replace("\\", "/")
    return ["-c", "credential.helper=", "-c", "credential.helper=!%s auth git-credential" % quoted]


def _push(root: Path) -> None:
    """git push origin master，经 Clash 代理（仅作用于本子进程 env 副本）。

    **两级尝试**（2026-09-19 加）：① 现有姿势（代理 + 默认凭据助手）；
    ② 失败则用 `gh` 凭据助手重试（`credential.helper=` 先清空再设，避免两个助手串联）。
    ② 能覆盖"GCM 在非交互环境取不到凭据"这一类**静默失败**（表现为提交在本地越堆越多）。
    """
    env = os.environ.copy()
    env["http_proxy"] = _PROXY
    env["https_proxy"] = _PROXY
    # ⚠️ **必须显式关掉交互式凭据**（2026-09-19 实测）：cron / wrapper 环境里没有这两个变量时，
    #    默认凭据助手取不到凭据会**转去等终端输入** ⇒ `git push` 一直挂着（实测 `_push` 卡 14 分钟），
    #    提交只落本地、推送永远不完成。设上之后首选姿势**秒级失败**，立刻走下面 gh 助手的兜底。
    env["GIT_TERMINAL_PROMPT"] = "0"        # 不许 git 问终端要用户名/密码
    env["GCM_INTERACTIVE"] = "never"        # 不许 GCM 弹交互（含 GUI）
    # ⚠️ **绝不要给这里的 subprocess 加 `capture_output=True`**（同日实测）：凭据助手阻塞时，
    #    git 的**孙进程**会一直持有管道，`subprocess.run` 的 `timeout` 只杀直接子进程、
    #    仍要等管道关闭 ⇒ 整个调用挂死（超时形同虚设）。让 stderr 直接落到调用方控制台。
    #
    # 尝试顺序（2026-09-19 定）：**gh 助手优先**，老姿势（默认助手）作兜底。
    #   理由：老姿势当前**必然卡满 120s 再超时**（实测：代理 + GCM 既不成功也不快速失败），
    #   每天白等 2 分钟；gh 助手是实测可用的姿势（代理 + gh → 20~40s 成功）。
    #   gh 不可用时自动退回老姿势（保持既有行为）。两种失败都要接住 `TimeoutExpired` ——
    #   只接 `CalledProcessError` 会让超时直接冒泡、**兜底根本不会执行**（本轮踩过）。
    helper = _gh_helper_args()
    attempts: list[list[str]] = []
    if helper:
        attempts.append(["git", *helper, "push", "origin", "master"])
    attempts.append(["git", "push", "origin", "master"])
    last_exc: Exception | None = None
    for idx, cmd in enumerate(attempts):
        try:
            subprocess.run(cmd, cwd=str(root), check=True, timeout=_PUSH_TIMEOUT, env=env)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_exc = exc
            logger.warning("[auto-push] 第 %d 种姿势失败（%s）：%s", idx + 1, type(exc).__name__,
                           "gh 凭据助手" if "credential.helper=!" in " ".join(cmd) else "默认凭据助手")
    if last_exc is not None:
        raise last_exc


def _db_row_counts(db_path) -> tuple[int, int]:
    """(`history` 行数, `econ_events` 行数) —— 读侧容错口径（损坏 / 被锁 / 缺表 → 0）。

    ⚠️ 0 的语义是**故意保守**的：两侧都用 0 表示"读不出来"。对**当前库**而言，读不出来
    （被锁 / 损坏 / 被清空）就命中"HEAD 有行、当前 0 行"的拒绝规则 ⇒ 宁可拒绝一次提交，
    也绝不把读不出来的库推上线（BUG-001 的放大链正是"删库 → 空库被 commit + push"）；
    对 **HEAD 副本**而言 0 行不触发任何拒绝（HEAD 无该文件 / 读不动 → 放行）。
    """
    return (len(storage.query_history(db_path=db_path)),
            len(storage.query_econ_events(db_path=db_path)))


def _head_db_counts(root: Path) -> tuple[int, int] | None:
    """HEAD 中 `data/marketpulse.db` 的 (history, econ_events) 行数；取不到 → None。

    `git show` 的标准输出**重定向到临时文件**（不是 `capture_output`）：二进制 blob 必须落文件
    才能读，而且管道有实测坑 —— git 的孙进程会一直持有管道，`subprocess` 的 timeout 形同虚设
    （见 `_push` 上方注释）。`stderr` 走 DEVNULL 只求不刷屏，同样不是管道。

    HEAD 里没有这个文件（首次提交）/ 拿不到 HEAD 对象（浅克隆、无 HEAD）/ 副本读不出
    → `CalledProcessError` 或 0 行 → 调用方放行。
    """
    with tempfile.TemporaryDirectory(prefix="mp-head-") as td:
        copy = Path(td) / "head.db"
        with open(copy, "wb") as fh:
            subprocess.run(["git", "show", f"HEAD:{_DB_REL}"], cwd=str(root), stdout=fh,
                           stderr=subprocess.DEVNULL, check=True, timeout=_STATUS_TIMEOUT)
        return _db_row_counts(copy)


def _row_guard_reason(head: tuple[int, int], cur: tuple[int, int]) -> str:
    """行数守卫判据（纯函数）：返回拒绝原因；放行 → 空串。两个 tuple 均为 (history, econ_events)。"""
    h_hist, h_econ = head
    c_hist, c_econ = cur
    if h_hist > 0 and c_hist == 0:
        return f"history 表被清空（HEAD {h_hist} 行 → 当前 0 行）"
    if h_hist > _DROP_MIN_ROWS and c_hist < h_hist * _DROP_RATIO:
        return f"history 行数骤减（HEAD {h_hist} 行 → 当前 {c_hist} 行，不足一半）"
    if h_econ > 0 and c_econ == 0:
        return f"econ_events 表被清空（HEAD {h_econ} 行 → 当前 0 行）"
    return ""


def _data_guard(root: Path) -> tuple[bool, str]:
    """提交前数据护栏：返回 `(放行?, 原因)`；**拒绝时调用方不得执行 `git add/commit/push`**。

    ① `storage.wal_checkpoint()`：`-wal` 里的新行先落进**将要提交的那个** `.db`。
    `.gitignore` 排除 `-wal/-shm`（D-1：DB 本身入库、即线上数据源）⇒ 不 checkpoint 就会把
    「少最后一批行」的库推上线；这一步把纪律从"靠人记得"变成代码强制。
    ② 行数守卫（对比 `HEAD:data/marketpulse.db` 的副本，见 `_row_guard_reason`）。

    放行侧（**都只记 warning**）：DB 文件不存在 / HEAD 里没有该文件 / `git show` 失败
    （浅克隆、无 HEAD）/ 任何未预期异常 —— 护栏是**可用性**部件，绝不能把正常推送卡死。
    """
    db = root / _DB_REL
    if not db.exists():
        logger.warning("[data-guard] %s 不存在，跳过行数守卫", _DB_REL)
        return True, "db-missing"
    try:
        storage.wal_checkpoint(db_path=db)
    except Exception as exc:  # noqa: BLE001 —— 收尾失败不该阻断推送（下行守卫仍会兜底）
        logger.warning("[data-guard] wal_checkpoint 失败（继续）: %s", exc)
    try:
        try:
            head = _head_db_counts(root)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            head = None                       # 首次提交 / 浅克隆 / 无 HEAD / git 不在 PATH
            logger.warning("[data-guard] 读不到 HEAD:%s（%s），跳过行数守卫", _DB_REL, exc)
        if head is None:
            return True, "head-unavailable"
        cur = _db_row_counts(db)
        reason = _row_guard_reason(head, cur)
        if reason:
            logger.error("[data-guard] 拒绝提交：%s（HEAD history=%d / 当前 history=%d；"
                         "HEAD econ_events=%d / 当前 econ_events=%d）",
                         reason, head[0], cur[0], head[1], cur[1])
            return False, reason
        return True, "ok"
    except Exception as exc:  # noqa: BLE001 —— 未预期错误一律放行（见 docstring 放行侧）
        logger.warning("[data-guard] 行数守卫异常（放行）: %s", exc)
        return True, f"guard-error: {exc}"


def auto_commit_push(date_str: str, report_type: str, root: Path = PROJECT_ROOT) -> bool:
    """将当前仓库变更 commit 并 push 到 origin/master。

    成功返回 True；以下情况返回 False：关闭（AUTO_PUSH=0）/ 无改动 / **数据护栏拒绝** /
    任意失败（代理黑洞、超时、无 git）。失败仅打印日志，不抛异常（F6 + 退出码恒 0 约定）。

    2026-09-24（D-3）：`_commit` **之前**过一道 `_data_guard` —— 空库 / 行数腰斩 / 事件表被清空
    一律拒绝（不 add、不 commit、不 push），`scripts/auto_commit_data.py` 据此返回 1、Hermes cron
    可见。护栏本身对"读不出 HEAD""DB 不存在"等情况放行，不会卡死正常推送。
    """
    if not _enabled():
        return False
    try:
        if not _has_changes(root):
            print("[auto-push] No changes, skipping.")
            return False
        allowed, reason = _data_guard(root)
        if not allowed:
            print(f"[auto-push] Refused by data guard: {reason}")
            return False
        _commit(root, date_str, report_type)
        _push(root)
        print(f"[auto-push] Committed and pushed: {date_str} {report_type}")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"[auto-push] Failed: {exc}")
        return False
