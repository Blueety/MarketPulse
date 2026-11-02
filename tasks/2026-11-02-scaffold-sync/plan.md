# 实施计划

> 由 Agent 在只读分析后填写。T1 的档位声明是通知（不等确认），T2 / T3 要人批准后才实施；
> 实施一律交给执行者子 agent，它只读这份文件。

## 任务概要

- **档位**: `T2 — 26 文件 / 0 调用方 / 行为无变（文档与流程脚本） / 无覆盖测试（877 条既有测试作护栏） / 预估 +700 行`
  - 说明：本次是脚手架同步（`project-scaffold/scripts/scaffold-update.sh --write`），只改 `AGENTS.md` / `docs/*` / `skills/*` / `tasks/_template/*` / `README.md` / `.gitignore` 与新增的 `scripts/check-gates.*`、`.githooks/pre-commit`、`.scaffold-version`；不碰 `src/` `web/` `data/`。
- **类型**: `重构`（流程/文档机制升级，运行时行为零变化）
- **目标**: 把已生成项目的脚手架文件三方合并到脚手架 6eb5ee9；9 个两边都改过的文件逐个裁决，冲突残留清零。
- **相关文件**:
  - `AGENTS.md` / `README.md` / `.gitignore`（三方合并 + 人工裁决）
  - `docs/commands.md` / `docs/architecture.md` / `docs/pitfalls.md` / `docs/adr/README.md`
  - `docs/agents/{任务分级,架构师,执行者}.md`
  - `skills/{bug-fix,tdd,research,pre-review}/SKILL.md` + 新增 `skills/{refactor,receiving-review,self-audit}/SKILL.md`
  - `tasks/README.md` + `tasks/_template/{prd,plan,journal,review,slice}.md`
  - 新增 `scripts/check-gates.sh` / `scripts/check-gates.awk` / `.githooks/pre-commit` / `.scaffold-version`
- **验证命令**: `venv/Scripts/python -m pytest tests/ -q`；`grep -rn '<<<<<<<'`（必须无输出）；`sh scripts/check-gates.sh --help`

## 步骤

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | 预览三方合并（`scaffold-update.sh <项目>`），确认基线与冲突面 | 无（只读） | 基线靠内容比对猜出（52%），可能把模板演进算成冲突 | 预览报告 9 冲突 / 9 升级 / 8 新增 |
| 2 | `--write` 落盘 | 全部脚手架路径 | 冲突标记进仓库文件 | `git status` 与 `grep '<<<<<<<'` |
| 3 | 逐文件裁决 9 个冲突：机制类取模板、项目内容类合并 | 9 文件 | 合并时丢项目既有教训 | 逐个通读冲突块，人工并集 |
| 4 | 补架构文档缺失的两节（接口契约 / 数据模型） | `docs/architecture.md` | 与模块表的既有描述重复 | 通读新增两节 |
| 5 | 跑全量测试 + 闸门脚本冒烟 | 全仓库 | 文档改动会否影响既有断言 | `pytest tests/ -q`、`sh scripts/check-gates.sh --help` |
| 6 | 独立子 agent 双轴审查 → 逐条裁决（T2 必备） | `tasks/2026-11-02-scaffold-sync/review.md` | 审查发现的错漏被静默跳过 | 每条发现落到「改 / 不改+理由 / 不接受+反证」 |
| 7 | 按审查结论把 `docs/architecture.md` 模块表的 6 条存量违规清掉（**计划外追加**，见 review.md J5 与「结论」） | `docs/architecture.md` | 改表可能牵出新的「src 子目录未声明」违规 | `sh scripts/check-gates.sh --staged` 通过 |

## 测试 Seam

- **要测的 seam**:
- **公开接口是什么**:
- **错误与边界**:
- **为什么选这个 seam**（而不是更浅的那个）:

## 修 bug 时必填

<!-- 仅当类型轴 = bug 时填。见 skills/bug-fix/SKILL.md 闸门 A -->

- **能变红的命令**:
- **已实跑的输出**（脱敏后）:
- **是否已最小化**:
- **3–5 个排序假设**（每个带预测「若 X 是因，则改 Y 会让 bug 消失」）:
  1.
  2.
  3.

## 不做什么

- 不动 `src/` `web/` `data/` 的任何代码与数据
- 不修既有 914 条闸门存量违规（本次只把规则装进来并记录债务）
- 不启用 `core.hooksPath`（存量违规清零前启用会拦掉每次提交）
- 不改 `docs/pitfalls.md` / `docs/commands.md` 的既有条目，只做并集

## 预估 diff 范围

- 新增文件: 8（3 个 skill + 2 个 tasks 模板 + 2 个闸门脚本 + 1 个钩子）另加 `.scaffold-version`
- 修改文件: 18
- 删除文件: 0

## 确认

- [x] 人已审阅计划（用户 2026-11-02 指令：用 `scaffold-update.sh` 更新本项目脚手架）
- [x] 档位声明与实际文件范围一致
- [x] 文件范围合理
- [x] 没有遗漏测试
- [x] 测试 seam 已确认（文档类改动无新 seam，靠既有 877 条测试作护栏）
- [x] 没有引入不必要依赖
