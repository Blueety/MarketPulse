# 执行日志

> 由 Agent 在任务结束时填写。新会话接手时先读这份日志，不用从头解释。
> 只写会复用的内容，不写过程流水账。

## 目标

把 MarketPulse 的脚手架文件同步到 `project-scaffold` 当前版本（6eb5ee9）：9 个「两边都改过」的文件逐个裁决，装进 v2 新机制（T0/T1 通知 + T2/T3 批准、独立子 agent 审查、`review.md` 裁决单、机械闸门 `check-gates`），并把闸门对既有仓库报出的债务量化下来。

## 主要提交

- **主要提交**: `96fa3ab`
  <!-- 一个任务目录对应一个主要提交（见 tasks/README.md）。 -->

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `.gitignore` | 并集：保留 `venv/`、`!data/alerts.log`、`data/*.corrupt-*` 等本地条目，采纳模板的 `tasks/**/tmp/`（`*`→`**`，覆盖 `tasks/_archive/<任务>/tmp/`） |
| `AGENTS.md` | Required Reading 换新版清单并保留本项目指针；Working Rules 采纳「T0/T1 通知、T2/T3 批准 / 派执行者子 agent / 不可逆外部动作先报告」并保留自动提交白名单教训；新增「## 编码规范」按真实约定填满 8 条；`Project Map` 补 3 个新技能 + 闸门 + `.scaffold-version` |
| `README.md` | 新增「## 技术栈」（填真实值）、「## 🧭 开发约定」、「## 📚 相关文档」；修复拼接处丢失的「## 🧪 测试」标题；测试数 281 → 877；`WEB_AUTH_*` → `MP_AUTH_*` |
| `docs/architecture.md` | 新增「## 接口契约」「## 数据模型」；模块表 6 条格式性违规清零（多路径/带说明的路径格改为单路径，说明移入职责列）；数据流与关键决策里遗留的 `data/history.json` 标注为已被 SQLite 取代 |
| `docs/commands.md` | 新增「## UI 变更怎么验」（接本仓 3 条 verify 脚本）；闸门 B 表补 `check-gates.sh --staged` / 全量两行 |
| `docs/pitfalls.md` | 环境相关新增两条本次实跑踩到的坑（Windows `bash.exe` 是 WSL 桩、Git Bash PATH 缺 `/usr/bin` 导致 `find` 撞 `find.exe`） |
| `docs/adr/README.md` / `docs/agents/{任务分级,架构师,执行者}.md` | 模板升级（无本地改动，取新版） |
| `skills/{bug-fix,tdd,research}/SKILL.md` | 模板升级 |
| `skills/pre-review/SKILL.md` | 取新版（新增「谁执行 / 改动摘要 / 声称完成前 / 验收标准→证据 / 未判断的」），并**重新并入本项目的「独立期望值预言机」一节**（§7，模板里没有）+ 对应 Rule；`allowed-tools` 补 `Bash(git add:*)`、`Bash(git status:*)` |
| `skills/{refactor,receiving-review,self-audit}/SKILL.md` | **新增**（脚手架 v2 的 3 个新流程） |
| `tasks/README.md` / `tasks/_template/{prd,plan,journal}.md` | 模板升级；**新增** `tasks/_template/{review,slice}.md` |
| `scripts/check-gates.sh` / `scripts/check-gates.awk` / `.githooks/pre-commit` | **新增**（机械闸门；与脚手架逐字节一致） |
| `.scaffold-version` | **新增**（基线 commit 6eb5ee9 + 存量违规计数） |
| `tasks/2026-11-02-scaffold-sync/{plan,review,journal}.md` | 本任务 |

## 验证结果

| 命令 | 结果 |
|---|---|
| `bash scripts/scaffold-update.sh <项目>`（预览）+ `--write` | 9 冲突 / 9 升级 / 8 新增 / 1 保留；写盘后 9 个冲突标记 |
| `grep -rn '^<<<<<<<\|^>>>>>>>'`（全仓库 .md/.sh/.awk/.gitignore） | **无输出**（冲突全部裁决完） |
| `venv/Scripts/python -m pytest tests/ -q` | **877 passed**（0 failed，150s）——改动前同样 877，行为零变化 |
| `venv/Scripts/python -m pytest tests/test_doc_consistency.py -q` | 1 passed（`days` 上限 3650 的文档断言仍成立） |
| `sh scripts/check-gates.sh --staged` | **通过**（0 项） |
| `sh scripts/check-gates.sh`（全量） | 914 → **908** 项，剩余全部是旧任务文件缺新模板章节 |
| 独立子 agent 双轴审查（T2 必做） | 17 条发现：13 改 / 3 不改（上游机制文件）/ 1 不接受（有反证），见 `review.md` |

- 未运行的检查及原因: lint / typecheck（本项目未配置，见 `docs/commands.md`）；`verify_ui.py`（零前端改动，无触发条件）。

## 遇到的问题

- **本机 `bash` 指向 WSL 桩**：omp shell 里 `bash` 解析到 `C:\Windows\System32\bash.exe`，所有输出变成 `?`、退出码 1。必须显式用 `D:/Claude/Git/usr/bin/bash.exe`（**Windows 形式路径**；`/d/Claude/...` 反而不认）。
- **Git Bash 的 PATH 少了 `/usr/bin`**：Windows 的 `find.exe` 抢在 MSYS `find` 前面 ⇒ 更新器报 `FIND: 参数格式不正确`，随后被判成「找不到基线」。修法：`PATH="/d/Claude/Git/usr/bin:/usr/bin:$PATH"`。
- **基线是猜的**：项目没有 `.scaffold-version`（旧 init 脚本不写），脚本按内容比对挑到 36d0751（一致率 52%）。脚手架仓库的 git 历史在 2026-10-29 被重写过，项目生成时的 Sep-26 版本在历史里已不存在 ⇒ 三方合并的 base 只能是最早的可用版本。后果：部分「冲突」其实是模板演进 + 本地改动的叠加，必须逐个读，不能机械取 theirs。
- **`write` 工具对中文长文本的模糊匹配会失配**：`edit` 报 "below the 95% similarity threshold" 时改用 Python 读写做整段替换更可靠；`conflict://<N>` 写入只接受 `conflict://N` 形式（写成 `AGENTS.md#conflict-4` 会生成一个同名新文件）。

## 下次注意什么

- 同步脚手架时**先看 `.scaffold-version`**：有基线才对得上三方；没有就先跑一次 `--write` 把基线写进去（本次已建）。
- **9 个冲突里只有两类**：机制类（`docs/agents/*`、大部分 `skills/*`）整份取模板；内容类（`AGENTS.md` / `README.md` / `docs/{architecture,commands,pitfalls}.md` / `skills/pre-review`）必须人工并集——尤其 `skills/pre-review` 的「独立期望值预言机」一节模板里没有，每次同步都要检查它还在。
- **机制文件不要本地化**：`scripts/check-gates.*`、`.githooks/pre-commit`、`docs/agents/*` 与脚手架逐字节一致，本地改了下次同步必冲突；发现它们有 bug 就报上游（本次记了 2 条，见「下一步」）。
- 闸门存量债的构成会变：`docs/architecture.md` 的模块表必须**一格一路径**，第二列写多路径或带括号说明就会被判「模块不存在」。

## 涉及的 ADR

- 无（本次是机制同步，未产生新的取舍决策；「钩子暂不启用」的判断写在 `AGENTS.md` 与 `review.md`，不足 ADR 三条准入）

## 下一步

- **存量债清零**（908 条，全部是旧任务文件缺新模板章节）：这是独立任务，按 `tasks/README.md` 的「闸门升级后的存量违规」走——要么批量补章节，要么把已收尾的旧任务归档进 `tasks/_archive/`（闸门跳过归档目录）。
- **上游缺陷 2 条**（报给 `project-scaffold`，本仓不本地改）：
  1. `scripts/check-gates.sh:228` 规模兜底按「**任一**候选任务声明 T2/T3」短路，且候选为空时退回所有在飞任务 ⇒ 一个只改代码的提交只要仓库里有任意 T2 任务就放行。判据应改成「**本次贵任**累计 `src/` 改动 ≥4 文件且该任务档位 < T2」。
  2. `scripts/check-gates.awk:453` 注释称 `field_filled` 管住「目标」，实际 `plan_check` 没有这条调用。
- `docs/commands.md` 开头「5 个 JSON API」仍是旧值（真实 6 页面 + 12 GET + 1 POST，见 `docs/architecture.md` 的接口契约）；同类旧值可能还有 `tasks/` 下的历史文档，本次未批量清理。
- `docs/agents/架构师.md` 一半 `【】` 伪标题、一半 `##`（模板原样，属上游排版问题）。

## 雾区变化

- **解掉的雾区项**: 「脚手架怎么更新」——现在有 `.scaffold-version` 基线 + 更新器用法（`--diff` 预览 / `--write` / `--keep-local` 裁决）+ 本目录的冲突裁决记录。
- **新增的雾区项**: 「908 条闸门存量债怎么清」——按任务补章节还是归档，尚无结论（已记在「下一步」）。

## 一致性走查

- **本次是否走查**: 未到触发条件

## 结束状态

- **结束状态**: `DONE_WITH_CONCERNS`
