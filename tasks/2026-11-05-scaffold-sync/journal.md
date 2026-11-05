# 执行日志

## 目标

把项目脚手架从基线 `fe434d2` 同步到上游当前 `f0a83d0`：升级机制/流程文档，裁决冲突，并让本仓闸门保持 0 违规。上游新加的断链校验在本仓不成立（见「遇到的问题」），最终以 `keep-local` 处置并留缺陷清单待报。

## 主要提交

- **主要提交**: `75d31c4`（第二轮：同步上游 `115092e`）；第一轮为 `1414bf3`

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `.scaffold-version` | 基线 `fe434d2` → `f0a83d0`；`gate_violations=385` → `0`；新增 4 条 `decision keep-local` |
| `AGENTS.md` | 合并模板改动（seam 写进 plan、闸门自动跑）；删掉「闸门会拦文档断链 / ADR 互指」两条未启用的能力，加 `keep-local` 说明 |
| `README.md` | 合并模板改动并去重（原合并稿有 4 条重复、`--no-verify` 与 AGENTS 禁止项冲突）；相关文档链接表保持本仓排版 |
| `docs/adr/README.md` | 模板新增「被否决方案先写最强理由」「取代关系两边都写」 |
| `docs/agents/任务分级.md` | 模板新 seam 措辞；「规模底线」一段改写成本仓实际行为（只看本次索引）；记 `keep-local` |
| `docs/agents/执行者.md` | 模板 seam 措辞 |
| `docs/pitfalls.md` | 新增 2026-11-05 条：385 项假红的根因、误判分类表、回滚放弃的 3 项修复、上游缺陷待报清单 |
| `skills/tdd/SKILL.md` | 模板 seam 措辞 |
| `tasks/README.md` | 模板 seam 措辞；journal 两行按实际闸门能力改写（逐行判、`- 返工: 0 次` 会被计为一条结果） |
| `tasks/_template/plan.md` | 模板 seam 措辞 |
| `tasks/2026-11-05-scaffold-sync/plan.md` | 本任务计划（T2） |
| `tasks/2026-11-05-scaffold-sync/review.md` | 独立审查裁决单（12 条发现 + 9 条未判断） |
| `tasks/2026-11-05-scaffold-sync/upstream-report.md` | 上游缺陷报告（D1–D7；副本投在脚手架仓库根 `UPSTREAM-BUGS-2026-11-05-marketpulse.md`） |
| `scripts/check-gates.sh` / `.awk` | 第二轮：升到上游 `115092e` 模板版，与 `templates/` 逐字节一致 |
| `tasks/_template/journal.md` / `docs/agents/任务分级.md` | 第二轮：恢复成模板内容（保留 `keep-local` 撤销后的原样） |
| `docs/architecture.md` / `docs/commands.md` / `docs/system-overview.md` | 第二轮：15 处历史断链的修正（归档脚本指真实路径、新浪 URL 段与环境变量式路径改描述式、图标路径、`reports/` 产物路径） |
| `web/static/vendor/liquid-glass/README.md` | 第二轮：「来源」列两处包内布局改成不带斜杠链的写法 |

回滚（与模板逐字节一致，故未出现在 diff 里）：`scripts/check-gates.sh`、`scripts/check-gates.awk`、`tasks/_template/journal.md`。

## 验证结果

| 命令 | 结果 |
|---|---|
| `scaffold-update.sh /d/AGENT/MarketPulse`（预览） | `冲突 2 / 升级 9 / 保留 6`；写盘后 `--diff` 逐条核对 |
| `sh scripts/check-gates.sh` | 闸门检查通过（0 项） |
| `sh scripts/check-gates.sh --staged` | 通过（提交前钩子同款） |
| `venv/Scripts/python -m pytest tests/ -q` | **880 passed**, 12 warnings（137s） |
| `scaffold-update.sh … --refresh-gate-count` | `存量违规 0 条` → `.scaffold-version` 写回 `gate_violations=0`，5 条裁决行保留 |
| `scaffold-update.sh …`（再预览） | 5 个文件全部 `跳过（已裁决 keep-local，模板未变）`，`汇总: 升级 0` |
| `awk -v kind=journal -v fpath=… -f scripts/check-gates.awk`（探针） | 「条目一行 + 缩进 `→` 下一行」→ 报 `[x] 「下次注意什么」这条没有去向: 改 A 必须同步 B`（证明逐行判） |
| `grep -c '^  \[x\] reports/' /d/tmp/gates-after-sync.txt` | `210`（313 = 33 venv + 6 .venv + 210 reports + 64 .workbuddy） |
| `grep -n "独立期望值预言机" skills/pre-review/SKILL.md` | 命中（`keep-local` 裁决仍生效，§7 未丢） |

- 未运行的检查及原因: `verify_ui.py` 等浏览器验收（零前端/零后端行为改动，无触发条件）；lint / typecheck（本项目未配置，见 `docs/commands.md`）。

**第二轮复跑（上游 `115092e` 之后）**

| 命令 | 结果 |
|---|---|
| `scaffold-update.sh …`（预览 → `--write`） | 4 个机制文件「覆盖（机制文件：取模板版）」，基线写到 `115092e` |
| `sh scripts/check-gates.sh` | 首次 **17 项** → 修完 15 处断链 + 2 处写法后 **0 项** |
| `sh scripts/check-gates.sh --staged` | 通过（其间抓到 `reports/backtest_report.md` 在 staged 合成根下不可见 ⇒ 改成「`reports/` 下的 …」写法，记为上游客 D7） |
| `venv/Scripts/python -m pytest tests/ -q` | **880 passed**（134s） |
| `venv/Scripts/python -m pytest tests/test_doc_consistency.py tests/test_scripts.py -q` | 5 passed |
| `scaffold-update.sh … --refresh-gate-count` | 「存量违规 0 条」→ `.scaffold-version` 写回 `gate_violations=0` |
| `git hash-object` × 4 个机制文件 vs `115092e:templates/<path>` | 全部 MATCH |

- 返工: 18 次
<!-- = `review.md` 两轮「逐条处理」的 12 + 6 条（第一轮独立审查 12 条、第二轮 6 条）。 -->

## 遇到的问题

- **新闸门的断链校验在本仓一上来就是 385 项**：`f0a83d0` 的 `check_links()` 用 `find . -name '*.md'`，把 `.gitignore` 覆盖的 `venv/`(33)、`.venv/`(6)、`reports/`(210)、`.workbuddy/`(64) 全扫了（313 项），剩下 72 项是占位符 / CSS 类名串 / 点号表达式 / 子目录相对路径的误判。证据：`/d/tmp/gates-after-sync.txt`（升级后实跑）、`scripts/check-gates.sh:161` 的实现与它自己的注释「只查活文档」矛盾。
- **`--keep-local` 不写回裁决**：`--write --keep-local X` 只打印「记下裁决」，`.scaffold-version` 里没有那一行（实测两次）；`--refresh-gate-count` 只刷计数。手工按 `git rev-parse f0a83d0:templates/<path>` 的 blob 写入 5 条 `decision` 行后才生效（再预览显示「跳过（已裁决 keep-local）」）。
- **取下游缺省值的合并稿会带进未落地的规则**：`AGENTS.md`/`README.md` 合并稿声称闸门会拦「文档断链 / ADR 互指」，`tasks/_template/journal.md` 示范「`→` 写下一行」，而我保留的是 old gate ⇒ 独立审查抓出 4 条 Major（文档描述的能力不存在、照模板写会被自家闸门拦）。证据：`review.md` 第 1–4 条 + `awk -v kind=journal` 探针实跑输出。
- **README 合并稿重复**：首次合并把「修 bug / 写测试 / 重构 / 提交前 / 收到意见」写了两遍（ours 与 theirs 都覆盖同一批主题），已重排成一份并在同一轮补回 `CONTEXT.md` 用词那条。
- **第二轮「为过闸门改写措辞」踩了两个坑**（第 2 轮独立审查发现，均为 Major）：① 把新浪行情站 URL 里的 `hisdata_klc2` 写成「本地目录」——为满足闸门的路径形状判定造出了**假事实**（证据：`akshare/fund/fund_etf_sina.py` 用它拼 `finance.sina.com.cn/.../hisdata_klc2/klc_kl.js`）；② 上游报告的 D6 把项目自写的 provenance README 当成「上游原样 vendored」，据此断言「三条硬约束都不可行」，与同一提交的 pitfalls 自相矛盾。教训：改写措辞前先确认**这个路径到底指谁**，别让校验器倒推事实。
- **`--staged` 与全量结论相反**：`reports/backtest_report.md`（`.gitignore` 的产物）在全量模式下 `[ -e ]` 通过、在 staged 的合成根里不存在 ⇒ 钩子恒红。已改成「`reports/` 下的 `backtest_report.md`」写法，并作为上游客 D7 记入报告。

## 下次注意什么

- 同步前先跑 `--diff` 并**逐条读模板侧内容**，不要只看「升级 N / 冲突 M」的汇总：本轮 4 条 Major 全在「升级」文件里，冲突文件反而没问题。→ pitfalls
- 机制文档（`docs/agents/*`、`tasks/_template/*`、`skills/*`）描述的是闸门能力，回滚闸门时必须同步回滚或改写它们的相应段落。→ pitfalls
- 更新器的 `--keep-local` 在「本次没有文件改动」时不写 `.scaffold-version`，裁决要手写 `decision <策略> <路径> <模板 blob sha>`。→ pitfalls
- 合并稿合完先自查同类主题有没有双份（本次 README 出现 5 条重复）。不沉淀
- 上游缺陷四条（`find` 不尊重 `.gitignore`、`emit_link` 误判、journal 逐行 vs 按条目、`- 返工: 0 次` 被计为结果）修好之前，下次同步仍要保留 `keep-local`。→ pitfalls

## 涉及的 ADR

- 无（同步是机制更新，未产生新的取舍决策；`keep-local` 的裁决理由已写进 `docs/pitfalls.md`，未达 ADR 三条准入）

## 下一步

- 上游 `115092e` 已修 D1–D4，本任务的 4 条 `keep-local` 已全部撤销（只剩 `skills/pre-review/SKILL.md` 这条本仓固有的）。剩余上游客：D5（`--keep-local` 未落盘，未复现）、D6（缺 `.gates-ignore` 排除表，本项目不需要但别人会撞）、D7（`--staged` 看不到 gitignored 产物，**建议优先修**，否则每个用产物目录的项目提交都被拦）。
- 顺手可清的两处既有表述（非本轮引入，未动以免拉宽 diff）：`docs/pitfalls.md` 的 `seed_history` 行指向的 `legacy/README.md` 并不记录该脚本退役原因（原因在 `tasks/_archive/2026-09-24-qa-bughunt/{journal,bug_report,plan}.md`）；`docs/commands.md` 归档脚本条目首列改成真实路径后，「已移档到该 `legacy/` 目录」略冗余。
- 顺带可清的历史断链（新校验本来能抓到）：`scripts/migrate_to_sqlite.py`、`src/wecom_sdk.py`、`scripts/wecom_service.bat`、`hisdata_klc2/klc_kl.js` 在活文档里仍被引用。

## 雾区变化

- **解掉的雾区项**: 「脚手架怎么升级 + 怎么裁决」现在有完整闭环：预览 → 写盘 → 解冲突 → 记裁决 → 刷新计数 → 闸门/pytest 复跑 → 独立审查。第二轮还解掉「上游修好后怎么解除 `keep-local`」：先把手改过的机制文件恢复成模板内容（否则会被判「本地改过、模板没动」而跳过），再 `--write`。
- **新增的雾区项**: 上游 D7（`--staged` 与全量结论不一致）修好前，涉及 gitignored 产物的文档路径都得写成描述式。

## 一致性走查

- **本次是否走查**: 未到触发条件（不是 T3，距上次走查 < 10 个任务）

## 结束状态

- **结束状态**: DONE_WITH_CONCERNS

关注点：上游 D7 未修，涉及产物路径的文档只能写描述式；`skills/pre-review/SKILL.md` 的 `keep-local` 是本仓固有分叉（§7 独立期望值预言机），每次上游改它都要重新判断。
