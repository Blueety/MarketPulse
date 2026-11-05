# 实施计划

## 任务概要

- **档位**: `T2 — 13 文件 / 0 调用方 / 行为无变（文档与流程）/ 有 check-gates 与 pytest 覆盖 / 预估 330 行`
- **类型**: `重构`（机制/文档同步，运行时行为零变化；例外：本次同步的 `check-gates` 新校验未采用，见步骤 4）
- **目标**: 用仓库外更新器把脚手架从基线 `fe434d2` 升到当前 `f0a83d0`，人工裁决 2 处内容文件冲突，并把新校验在本仓跑到 0 违规。
- **相关文件**:
  - 上游更新器：`D:/Obsidianhouse/AISTUDY/project-scaffold/project-scaffold/scripts/scaffold-update.sh`（仓库外，不改）
  - 自动升级（模板取新版，本地无改动）：`docs/adr/README.md`、`docs/agents/执行者.md`、`skills/tdd/SKILL.md`、`tasks/README.md`（后两者在冲突/校对阶段又按本仓实况改过，见步骤 4）、`tasks/_template/plan.md`
  - 人工合并（冲突）：`AGENTS.md`、`README.md`
  - 本次按本仓实况改过的文档：`docs/pitfalls.md`（新增 2026-11-05 条）、`tasks/README.md`（journal 两行按实际闸门能力改写）、`AGENTS.md` / `README.md`（删掉「闸门会拦文档断链 / ADR 互指」这两条未启用的能力）
  - 保留（本地改过、模板未动）：`.gitattributes`、`.gitignore`、`CONTEXT.md`、`docs/architecture.md`、`docs/commands.md`
  - 跳过（`keep-local` 裁决、模板未变）：`skills/pre-review/SKILL.md`（含本仓独有的「独立期望值预言机」§7，必须仍在）
  - **本次新增 `keep-local` 裁决**：`scripts/check-gates.sh`、`scripts/check-gates.awk`、`tasks/_template/journal.md`（整份回滚）、`docs/agents/任务分级.md`（保留新 seam 措辞，只把「规模底线」一段改成本仓实际行为）——理由见步骤 4
  - 基线：`.scaffold-version`（更新器写回 `commit=f0a83d0`）
- **验证命令**:
  - `sh scripts/check-gates.sh`（全量，必须 0 项）
  - `sh scripts/check-gates.sh --staged`（钩子同款）
  - `venv/Scripts/python -m pytest tests/ -q`（必须全绿）
  - `grep -n "独立期望值预言机" skills/pre-review/SKILL.md`
  - `git diff --stat`

## 步骤

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | 预览三方合并（已完成，落 `/d/tmp/scaffold-preview.diff`），确认冲突只有 `AGENTS.md` / `README.md` 两处内容文件 | 只读 | 低 | 汇总行 `冲突 2` |
| 2 | `--write` 落盘（机制文件取模板版，冲突文件写冲突标记，备份留 `.git/scaffold-work/<ts>/`） | 上述 11 个升级/冲突文件 | 中：机制文件被整体替换 | `git status` 列出文件与预览一致 |
| 3 | 人工解冲突：把模板侧 4 处 `AGENTS.md` + 2 处 `README.md` 的措辞改动逐条并入本仓版本，**不丢**本仓独有的 `app.py` 事故护栏段、auto-push 白名单段等 | `AGENTS.md`、`README.md` | 高：误删本仓条目 | `grep -c "app.py" AGENTS.md`；`grep -n "自动提交范围白名单" AGENTS.md`；`git diff AGENTS.md` 逐段看 |
| 4 | ~~跑新闸门并修存量~~ **改为 `keep-local`**：新闸门的断链校验在 `--write` 后实测 **385 项**（313 项来自 `.gitignore` 覆盖的 `venv/`33 + `.venv/`6 + `reports/`210 + `.workbuddy/`64，源于 `check_links` 用 `find . -name '*.md'` 而非 `git ls-files --exclude-standard`；另 72 项是占位符 `YYYY-MM-DD`、CSS 类名串、点号表达式、子目录相对路径的误判）。机制文件不 fork ⇒ 回滚 + 记 `keep-local`，缺陷报上游 | `scripts/check-gates.sh`、`scripts/check-gates.awk`、`.scaffold-version` | 中：放弃本次两条新校验（文档断链 / ADR 互指），连带放弃 3 项模板修复 | 回滚后 `check-gates.sh` 0 项；预览显示「跳过（已裁决 keep-local，模板未变）」 |
| 4b | 处理「新文档描述旧闸门」的连锁问题（独立审查发现 4 条 Major）：`tasks/_template/journal.md` 整份回滚（新模板示范「条目一行 + `→` 下一行」，而闸门逐行判 ⇒ 照它写会被拦）；`docs/agents/任务分级.md` 只把「规模底线」一段改成本仓实际行为；`AGENTS.md` / `README.md` / `tasks/README.md` 删掉未启用的闸门能力描述 | 上列 5 个文件 | 中：机制文件局部改动 | 逐条跑 `awk -v kind=journal` 探针验证逐行判；`check-gates.sh` 仍 0 项 |
| 5 | 全量回归 + 钩子同款检查 | — | 低 | `pytest` 全绿；`--staged` 通过 |
| 6 | 派独立子 agent 出 `review.md`，逐条处理 | `tasks/2026-11-05-scaffold-sync/review.md` | 低 | review.md 字段齐全 |
| 7 | 写 `journal.md`，提交（显式 pathspec，不用 `git add -A`） | — | 低 | 提交后 `git status` 干净 |

## 测试 Seam

- **要测的 seam**: 不新增测试。本次是机制文件同步，行为由现有 `tests/test_scripts.py`（闸门脚本）+ `tests/test_doc_consistency.py`（文档一致性）+ 全量 pytest 覆盖。
- **公开接口是什么**: `scripts/check-gates.sh` 的退出码与违规项数；`.githooks/pre-commit` 的拦截行为。
- **错误与边界**: 新旧校验规则重叠处（`[DEBUG-`、模块表、`plan.md` 字段、`journal.md` 逐行去向）必须仍然按原语义判；**未启用的新校验（文档断链、ADR 互指）不得在任何活文档里被写成既有能力**（这是本次独立审查的主要发现）；`docs/agents/任务分级.md` 的机制文件局部改动只允许出现在「规模底线」一段。
- **为什么选这个 seam**（而不是更浅的那个）: 闸门脚本的合同就是「commit 被拦截与否」，直接跑它比读 diff 更能证明同步没把判定语义改坏。

## 不做什么

- 不改上游脚手架仓库（`project-scaffold` 本体零写入）。
- 不 `--force` 覆盖本仓脏状态；不 `--accept-guess`（基线来自 `.scaffold-version`，非猜测）。
- 不动 `skills/pre-review/SKILL.md` 的 `keep-local` 裁决（模板未变，无需重新判断）。
- 不做未列入预览的额外重构；不批量清理历史任务文档里的旧表述。

## 预估 diff 范围

- 新增文件: `tasks/2026-11-05-scaffold-sync/{plan,review,journal}.md`、`.scaffold-version` 修改
- 修改文件: 上述 11 个（9 升级 + 2 冲突合并）
- 删除文件: 无

## 确认

- [x] 人已审阅计划（用户指令「更新一下这个项目的脚手架」即授权本次同步规模）
- [x] 档位声明与实际文件范围一致
- [x] 文件范围合理
- [x] 没有遗漏测试（无新逻辑，靠现有脚本测试 + 全量 pytest）
- [x] 测试 seam 已写入本节
- [x] 没有引入不必要依赖

---

## 第二轮：上游 `115092e` 修复后解除全部 `keep-local`（2026-11-05 20:15–21:10）

- **触发**：上游 `115092e` 修掉 D1–D4；用户确认可以更新。
- **档位**：仍属本任务（T2），不新开目录。
- **步骤**：
  1. 删掉 4 条 `keep-local` 裁决（除 `skills/pre-review/SKILL.md`），`tasks/_template/journal.md` 与 `docs/agents/任务分级.md` 先恢复成模板内容再去同步（否则会被判「本地改过、模板没动」而跳过）；
  2. `--write` 覆盖 `scripts/check-gates.{sh,awk}`（机制文件语义）；新基线 `115092e`；
  3. 新闸门跑出 17 项 → 15 项真实历史断链逐条修文档，2 项是自写 vendored README 的「包内布局」写法（改成不带斜杠链的描述式）；
  4. 把第一轮加的「本仓未启用」措辞全部恢复成模板口径（两条校验现已启用）；
  5. `docs/pitfalls.md` 改两轮实录 + 「写非仓库路径别写成路径形状」教训；上游报告补「修复验收」与 D6。
- **验证**：`sh scripts/check-gates.sh` 0 项；`--staged` 通过；`pytest tests/ -q` 880 passed；`--refresh-gate-count` → 存量违规 0 条；4 个机制文件 `git hash-object` 与 `115092e:templates/<path>` 逐字节一致。
- **不做什么**：不动 `skills/pre-review/SKILL.md` 的 `keep-local`（§7 是本仓独有）；不向上游写任何文件（只投一份报告副本）。

---

## 第三轮：上游 `ce88c06`（`--staged` 与「活文档」范围）后回退为过闸门做的措辞改写

- **触发**：上游修掉 D7（`--staged` 看不到 `.gitignore` 产物）并用「按位置划活文档」取代 D6 的排除表建议。
- **步骤**：`--write` 升 `scripts/check-gates.sh`（唯一变化文件）；**回退**第二轮为迁就闸门改的 5 处措辞
  （`web/static/vendor/liquid-glass/README.md` 两处「包内布局」、`AGENTS.md`/`docs/architecture.md`/`docs/commands.md`/`docs/pitfalls.md`
  的 `reports/backtest_report.md`）；pitfalls 记「为过闸门改措辞前先确认为什么要改」；上游报告追加第三轮。
- **验证**：`check-gates.sh` 0 项、`--staged` 0 项（含 `reports/` 产物引用）、`--refresh-gate-count` 0 条、
  `git hash-object` 与 `ce88c06:templates/scripts/check-gates.sh` MATCH、`pytest tests/ -q` 见 journal。
- **教训**：校验器不该要求文档改写成它的语法；上游一修，那些改写净收益为 0（本轮全部回退）。
