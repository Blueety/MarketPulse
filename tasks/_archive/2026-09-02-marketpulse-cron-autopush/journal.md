# 二十六期执行日志：cron 执行后自动 commit + push

日期：2026-09-02
执行者：Hy3

## 目标

实现 MarketPulse 三个 cron 入口（daily_report / snapshot_report / opening_analyzer）在 `main()` 末尾自动将本次产生的 `data/` `context/` `alerts/` 等变更 `git add -A` + commit（`auto: {date} {type}`）+ push 到 `origin/master`，确保 Railway 部署与最新数据同步。覆盖 PRD F1–F6 / NF1–NF3。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/git_ops.py` | 新增（~95 行）：`auto_commit_push(date_str, report_type, root=PROJECT_ROOT) -> bool` + 私有 `_enabled` / `_has_changes` / `_commit` / `_push`；纯 stdlib，零新依赖 |
| `tests/conftest.py` | +3 行：`os.environ["AUTO_PUSH"] = "0"` 护栏（防 pytest 真实调 `main()` 误推） |
| `tests/test_phase26.py` | 新增（11 条）：env 门控 / 无改动跳过 / message 格式 / 代理注入且不污染 os.environ / push 失败不抛 / root 作为 cwd |
| `daily_report.py` | +2 行：`from src.git_ops import auto_commit_push`；`main()` 尾部 `return 0` 前调 `auto_commit_push(date, "daily report")` |
| `snapshot_report.py` | +2 行：同上；`auto_commit_push(date, f"{market} {time} snapshot")` |
| `opening_analyzer.py` | +2 行：同上；`auto_commit_push(date, f"{market} opening analysis")` |
| `docs/architecture.md` | 模块表 +1 行、数据流 +1 段、关键决策表 +1 行（cron 自动提交推送） |
| `docs/commands.md` | 何时跑什么 +1 行、验证要点 +1 条 |

## 验证结果

- **单元测试**：`pytest tests/test_phase26.py -v` → 11 passed（门控 / 无改动跳过 / message 格式 / 代理注入且不污染 os.environ / push 失败 CalledProcessError·TimeoutExpired·FileNotFoundError 均返回 False 不抛 / root 作为 cwd）。
- **接线隔离回归**：`test_phase25`(17) + `test_phase7`(37) + `test_phase15`(30) 全绿；conftest `AUTO_PUSH=0` 下真实 `main()` 调用不会触发真实 git。
- **全量回归**：`pytest tests/ -v` → 374 passed（原有 363 + 新增 11）。
- **E2E 真跑**：`venv/Scripts/python daily_report.py` 跑通完整闭环，`main()` 末尾正确调用 `auto_commit_push` 并打印 `[auto-push] No changes, skipping.`（见下「遇到的问题」）。
- **幂等（F4）**：在已干净的工作区连续两次直接调用 `auto_commit_push('2026-09-02','daily report')` → 均返回 False 并打印 skip，`git log --oneline -1` 不变。
- **真实 commit+push 路径（temp-repo 演示）**：独立临时 git 仓库中调用 `auto_commit_push` → `RETURN: True`；本地与远端 `git log -1` 均为 `auto: 2026-09-02 daily report`（F5 格式正确）；变更内容已提交并推送成功。证明 `git add -A` + `commit` + `push` 全链路真实可用。

## 遇到的问题

1. **编辑失误（已修复）**：初次在 `daily_report.py` 用 `PUT 32.=32:` 误将原有的 `from src.image_renderer import render_report_image` 整行替换成 git_ops 导入，导致 `daily_report` 模块丢失 `render_report_image` 属性、`test_phase25` 两个用例 `AttributeError`。已恢复两行导入（`image_renderer` 在前、`git_ops` 在后），重跑 17 passed。
2. **遗留 Hermes「每日数据更新」cron 抢先提交（已知风险已发生）**：E2E 真跑 `daily_report.py` 时，遗留 cron 在我代码执行前已 `git add -A` + commit（`auto: 每日数据更新`）+ push，故本脚本 `auto_commit_push` 运行时工作区已干净，打印 `No changes, skipping.`（F4 幂等正确触发，但我的 commit+push 分支本次未被真实仓库执行）。当前 `origin/master..HEAD` = 0，源码已上线，但 commit message 为遗留格式。
3. **eval 内核在 temp-repo 演示中超时被杀**：改用独立 `.py` 脚本经 venv 运行，正常通过。

## 下次注意什么

- 编辑多行 import 块时不要用 `PUT N.=N:` 替换单行（会吞掉原行），应 `PUT >N:` 插入或整块重排。
- **交付动作（非本仓库范围）**：上线后应请用户在 Hermes 侧移除「每日数据更新」cron 的 `git add -A`/commit/push 步骤，否则与脚本内置逻辑双重提交、message 格式混杂（`auto: 每日数据更新` vs F5 的 `auto: {date} {type}`）。移除后，后续每次 cron 将统一以 F5 格式提交。
- 推送失败重试（F6）已由 `scripts/push_retry.sh` + Hermes cron 承担；若需代理一致性，可为该 shell 补同一 `http_proxy`/`https_proxy` env。
- 本地反复跑务必 `AUTO_PUSH=0`，真跑验证限一次（会触发 Railway 重部署）。
