# 实施计划：把 v2 开发流程落进本项目

## 任务概要

- **档位**: `T3 — 12 文件（含 8 个新建） / 0 调用方 / 行为无变化 / 无源码改动 / 预估 120 行`
- **目标**: 把 project-scaffold 的 v2 流程层（规模/类型双轴档位 + 闸门 A·B + skills + docs/agents + docs/adr + CONTEXT.md + 任务模板）落进本项目；**保留本项目已有的全部项目专属规则**（自动提交范围白名单（`src/git_ops.py` 只允许 data/context/alerts，禁止 `git add -A`）、Railway 入口 `app.py` 勿删勿移、`.db`/`context/`/`alerts/` 入库即线上数据源、`reports/` 被 gitignore 排除）
- **来源**: 用户指令（本次会话）+ `D:\Obsidianhouse\AISTUDY\project-scaffold\project-scaffold`（v2：WORKFLOW.md / templates/）
- **相关文件**:
  - `AGENTS.md`（改：Project Map / Required Reading / Working Rules / Done Means 加 v2 层）
  - `docs/agents/{任务分级,架构师,执行者}.md`（新建）
  - `docs/adr/README.md`（新建）+ `docs/adr/0001-adopt-v2-flow.md`（本次决策）
  - `CONTEXT.md`（新建，空壳；v2 约定不预填）
  - `skills/{bug-fix,pre-review}/SKILL.md`（替换 v1 → v2）、`skills/tdd/SKILL.md`（新建）
  - `tasks/_template/{prd,plan,journal}.md` 与 `tasks/README.md`（替换 v1 → v2）
- **验证命令**:
  1. 死链检查：`AGENTS.md` / `docs/agents/*.md` / `skills/**/SKILL.md` / `tasks/README.md` 里反引号引用的仓库路径逐个 `test -e`
  2. `git diff -U0 AGENTS.md | grep '^-'`：确认删除行只有刻意扩写的规则行

## 步骤

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | 复制 v2 流程层文件 | 8 新建 + 5 替换 | 覆盖项目专属内容 | 替换前用 `md5sum` 对比：本项目 v1 skills/模板与其它项目逐字节相同 ⇒ 是模板副本，无项目内容 |
| 2 | AGENTS.md 合并 v2 规则 | `AGENTS.md` | 丢失既有规则 | `git diff -U0 AGENTS.md` 逐条核对删除行 |
| 3 | 死链检查 + diff 范围检查 | — | — | 见验证命令 |

## 测试 Seam

- 不适用：纯文档/流程迁移，无可执行行为变化（本项目有 pytest（`venv/Scripts/python -m pytest tests/ -v`），本次无源码改动）。

## 修 bug 时必填

- 不适用：类型轴 = 文档迁移，不是 bug。

## 不做什么

- 不改 `src/**`、`web/**`、`tests/**`、`data/**`、`reports/**`、`context/**`、`alerts/**`。
- 不动 `app.py`（Railway 入口）与 `src/git_ops.py` 的自动提交白名单。
- 不执行 `git add -A` / `git add .`（本项目明确禁止）。
- 不推送：本次改的是 markdown，不在 auto-push 白名单内，不会被 cron 自动推。

## 预估 diff 范围

- 新增文件: 8（`docs/agents/*` ×3、`docs/adr/{README,0001-*}.md`、`CONTEXT.md`、`skills/tdd/SKILL.md`）
- 修改文件: 6（`AGENTS.md`、`skills/bug-fix/SKILL.md`、`skills/pre-review/SKILL.md`、`tasks/_template/{prd,plan,journal}.md`、`tasks/README.md`）
- 删除文件: 0

## 档位自评依据

- 文件数 ≥ 5（T3 线）→ 规模轴 T3；类型轴 = 文档迁移（行为无变化）→ 不触发闸门 A / seam 确认。
- 取更严者 **T3** ⇒ 计划落盘 + 过闸门 B（无 DEBUG 残留、无一次性脚本）。
