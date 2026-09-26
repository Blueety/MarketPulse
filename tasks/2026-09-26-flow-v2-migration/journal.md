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

## 补充（并行会话，2026-09-26 15:40）

本任务的执行过程中，另一个会话（cwd = `D:\AGENT\Music\Music`，收到同一条「更新一下 project-scaffold」指令、且用户已在那边选定「把 v2 流程套到实际项目」）**同时**在改本仓：它写了 `AGENTS.md` / `docs/agents/*` / `docs/adr/*` / `skills/*`，本会话写了 `CONTEXT.md` / `tasks/_template/*` / `tasks/README.md`，两边交叉覆盖过同一批文件（`skills/pre-review/SKILL.md`、`docs/agents/*` 各被覆盖一次）。最终提交内容取「最后写入者」，本会话已逐文件核对内容一致性。

### 本会话额外做的三件事

1. **`CONTEXT.md` 不是空壳**：v2 约定「新建项目时是空的」，但本项目不是新项目——AGENTS.md 里积了 20+ 条术语/数据源/入库语义的坑，因此按 v2 的「术语 + 关系 + 已消歧的歧义」结构**填实**（触发 vs 告警、`history` 指 SQLite 长表、`context/`/`alerts/` 其实会入库、`-wal` 必须 checkpoint）。
2. **`skills/pre-review/SKILL.md` 补回「独立期望值预言机」一节**（§6，并给 `allowed-tools` 加 `Bash`）：这是本项目 2026-09-16 记录在 `.workbuddy/memory/MEMORY.md` §4 的既有方法论，v2 副本化时被整体覆盖丢了。双轴与预言机不冲突：预言机是**两轴共用的取证手段**（尤其在阈值 / 时区 / 分档类断言上）。
3. **补两处 v2 落地后的漂移**：`docs/commands.md` 增「提交前（闸门 B 清理）」命令表（`grep -rn "\[DEBUG-"` / `git status --short` / 完整测试 / `git diff`，并写明 auto-push 白名单会把临时文件推上线）；`docs/system-overview.md` 的「2 个 Agent 工作流技能」已过时——加了 `tdd` 后是 6 个。

### 独立验证（本会话实跑，非转述）

| 检查 | 结果 |
|---|---|
| `venv/Scripts/python -m pytest tests/ -q` | **860 passed**（含 `test_doc_consistency.py`：`AGENTS.md` 的 `days 上限 **3650**` 未被本次重写碰掉） |
| 参考路径核对（自写脚本，131 条引用 / 13 个流程文件） | 无新增死链；报出的 20 条全是相对路径写法（`last_values.json` 在 `data/` 下）、示例占位（`YYYY-MM-DD.md`）或本次刻意删除的旧脚本 |
| 脚手架本体（`project-scaffold`） | 独立重跑 `init.ps1`（Windows PowerShell **5.1** 与 pwsh 7 两个宿主）与 `init.sh`（Git bash）：各 **18 个文件**、两平台产物**逐文件相同**、`{{PROJECT_NAME}}` 零残留、UTF-8 无 BOM、中文文件名（`docs/agents/任务分级.md`）完好 |

### 待用户裁定的一个分歧

本文件上一段主张「流程层文件是脚手架 v2 的**逐字节副本**，别在副本里改」；本会话的做法是**本地化**（`CONTEXT.md` 填实、pre-review 保留预言机、模板加本项目上下文入口）。两种都有道理：副本化便于上游同步，本地化保住本项目已有的沉没成本。建议界线为——**脚手架 v2 的「机制」保持副本化（`docs/agents/*`、`skills/tdd`），本项目「内容」允许本地化（`CONTEXT.md`、`skills/pre-review` 的预言机、模板的 Context Pointers）**。
