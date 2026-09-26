# 执行日志

## 目标

把 project-scaffold 的 v2 流程层（双轴档位、闸门 A·B、skills、docs/agents、docs/adr、CONTEXT.md、任务模板）落进本项目；**保留本项目已有的项目专属规则**：自动提交范围白名单（`src/git_ops.py` 只允许 data/context/alerts，禁止 `git add -A`）、Railway 入口 `app.py` 勿删勿移、`.db`/`context/`/`alerts/` 入库即线上数据源、`reports/` 被 gitignore 排除

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `AGENTS.md` | Project Map / Required Reading / Working Rules / Done Means 加 v2 层（只增不删，3 行刻意扩写） |
| `docs/agents/任务分级.md` | 新建（两轴判档 + 6 条信号 + 3 条升级规则） |
| `docs/agents/架构师.md` | 新建（UI 复现指向 `docs/commands.md`，不写死包管理器） |
| `docs/agents/执行者.md` | 新建 |
| `docs/adr/README.md` | 新建（ADR 三条准入 + 格式 + 不该写的内容） |
| `docs/adr/0001-adopt-v2-flow.md` | 新建（本次决策记录） |
| `CONTEXT.md` | 新建（空壳，按 v2 约定不预填） |
| `skills/bug-fix/SKILL.md` | 替换 v1 → v2（闸门 A 的 10 种回路构造 / 最小化 / 假设排序 / Phase 5 seam / 闸门 B） |
| `skills/pre-review/SKILL.md` | 替换 v1 → v2（双轴 + 12 条坏味道基线） |
| `skills/tdd/SKILL.md` | 新建（seam 先约定 / 反模式 / 垂直切片） |
| `tasks/README.md` | 替换 v1 → v2（判档信号表，不凭感觉建目录） |
| `tasks/_template/{prd,plan,journal}.md` | 替换 v1 → v2（plan 增档位/seam/修 bug 必填；journal 增 ADR 编号） |

项目专属技能目录原样保留：hermes-cron-script / source-value-layer / ui-verify-assertion。

## 验证结果

| 检查 | 结果 |
|---|---|
| 一次性死链检查脚本（临时文件，已删） | `checked 57 refs in 9 files` → `OK: all referenced paths exist` |
| `git diff -U0 AGENTS.md \| grep '^-'` | 删除行只有刻意扩写的规则行（`skills/` 那行、`计划应包含…`、`日志内容…`），项目专属规则一行未丢 |
| `git status --short -- <本次路径>` | 新增 `CONTEXT.md`、`docs/adr/`、`docs/agents/`、`skills/tdd/`、`tasks/2026-09-26-flow-v2-migration/` |

- 未运行的检查及原因：lint / typecheck / 测试均未跑——本次只改 markdown，无源码改动。

## 遇到的问题

- 本仓 `skills/` 下有**未跟踪**的项目专属技能目录（hermes-cron-script / source-value-layer / ui-verify-assertion），不是本次产物；提交时按具体路径 `git add`，没有用 `git add skills`。
- 本项目的 auto-push 白名单只有 `data/` `context/` `alerts/`，本次新增的都是 markdown ⇒ 不会被定时任务自动提交/推送。

## 下次注意什么

- 流程层文件（`docs/agents/`、`skills/{bug-fix,pre-review,tdd}`、`tasks/_template/`、`tasks/README.md`）是脚手架 v2 的**逐字节副本**：上游改了要整文件覆盖回来，别在副本里改（下次同步会丢）。
- `AGENTS.md` 是本仓唯一的流程真源，项目专属规则与流程规则混在一起；上游流程升级只做加法，禁止重排既有规则。
- 判 bug 类任务先看类型轴：无法复现 = 直接 T3，不看规模。
- 本仓有未跟踪的项目专属技能目录，`git add` 必须带具体路径。
## 涉及的 ADR

- `docs/adr/0001-adopt-v2-flow.md`

## 下一步

- 无遗留项；待办见上面「下次注意什么」。
