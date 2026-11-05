# 审查裁决单

## 审查范围

- **固定点**：工作区改动（`git diff HEAD` + 新增 `tasks/2026-11-05-scaffold-sync/plan.md`），无提交 SHA——本次改动在审查时尚未提交。
- **审查者**：独立子 agent `ScaffoldSyncReview`——它**没有接触主线程的会话历史**，只看下面这几样
- **给了它什么**：`plan.md`、完整 diff（`/d/tmp/scaffold-sync.diff`）、更新器预览（`/d/tmp/scaffold-preview.diff`）、升级后新闸门原始输出（`/d/tmp/gates-after-sync.txt`）、`AGENTS.md`、`docs/architecture.md`、`skills/pre-review/SKILL.md`、`docs/pitfalls.md`、上游脚手架仓库（只读）
- **轮次**：第 1 轮

## 审查者原文

## Standards

**1. `AGENTS.md:104` — 闸门能力被写成既定事实，实际两条校验已随脚本回滚消失**
- 问题：合并后这句列出「**文档里写的相对路径是否真实存在**」「**ADR 的 `Superseded-By` / `Supersedes` 是否互指**」两项提交前检查，但本次把 `scripts/check-gates.{sh,awk}` 回滚到 f0a83d0 之前的版本，两个校验器全都不在其中。
- 证据：`grep -n "引用的\|Superseded\|ADR-0" scripts/check-gates.sh scripts/check-gates.awk` 无任何命中；`git show f0a83d0:templates/scripts/check-gates.sh | diff --strip-trailing-cr - scripts/check-gates.sh` 显示 `check_links()` / `check_adr()` / `check_anchors()` 整段（模板 854 行 → 本地 623 行）缺失。回滚后实跑只剩缺 `review.md` 一项，也正是因为这两条根本不存在。
- 严重度：Major
- 建议：删掉这两项，或改成「文档断链 / ADR 互指两条校验本次未启用（见 `docs/pitfalls.md` 2026-11-05 条）」；其余条目（`[DEBUG-`、模块表、plan/journal/切片/review 字段）确实是 kept gate 的行为，保留。

**2. `README.md:250` — 同一处失实，合并时把模板措辞整句吞进了本仓**
- 问题：这条同样声称 `--staged` 会拦「**文档里指向不存在文件的相对路径**」「**ADR 的取代关系只写一边**」。
- 证据：同上，kept gate 无对应实现；`docs/pitfalls.md:1154` 自己写着这两条是 f0a83d0 新加的、本次没采用。
- 严重度：Major
- 建议：与第 1 条同改；「规模低报」这一项是真的（`scripts/check-gates.sh` 的 `check_scale` 仍在），保留。

**3. `tasks/README.md:117` + `tasks/_template/journal.md:53-56,65` — 新模板示范的 journal 写法会被 kept gate 判红**
- 问题：升级后的模板注释与 `tasks/README.md` 都说「按**条目**判（`→` 写成下一行也算）」，并示范「条目一行 + `→ pitfalls` 下一行」。kept gate 是**逐行**判：每一非空行都要自带 `→` 或「不沉淀」，照新模板写出来的条目行会被判「没有去向」，提交被拦。
- 证据：`scripts/check-gates.awk:546-558` 把「下次注意什么」按行 split 后逐行要求 `→`／「不沉淀」。实跑：用升级后的 `tasks/_template/journal.md`，在「下次注意什么」写入它自己示范的两条，再 `awk -v kind=journal -v fpath=tasks/x/journal.md -f scripts/check-gates.awk`，输出
  `[x] …「下次注意什么」这条没有去向: 改 A 必须同步 B` 和 `[x] …「下次注意什么」这条没有去向: 这个仓库的测试必须在 Git Bash 里跑`
- 严重度：Major
- 建议：`tasks/_template/journal.md` 属机制文件（上游 README 的 mechanism 清单里含 `tasks/_template/*`），本地不能 fork ⇒ 三选一：① 连闸门一起升级；② 把 `tasks/_template/journal.md` 也记 `keep-local`（并对 `tasks/README.md:117` 保留旧表述）；③ 至少把 `tasks/README.md:117` 的「按条目判」改回「每行必须有去向」，并在 pitfalls 里记这条机制/模板不一致。

**4. `tasks/README.md:118` + `tasks/_template/journal.md:37` — 「闸门不会把它算成一条验证结果」是错的**
- 问题：新增断言说模板自带的 `- 被打回: 0 次` 不会被算作验证结果；实际它正好把「验证结果为空」兜过去了——一份没有任何验证记录的 journal 能过闸门。
- 证据：`scripts/check-gates.awk:379-387` 的 `count_result_items()` 会把 `- 被打回: 0 次` 计 1 条。实跑：模板只填 `结束状态: DONE`、`验证结果` 仅留「未运行的检查及原因:」时无违规；删掉 `- 被打回` 那一行后立刻报 `「## 验证结果」里没有一行结果`。
- 严重度：Major（断言失实 + 闸门假阴性被文档背书）
- 建议：删掉该括号断言，改为「这一行模板自带，闸门不判它填得对不对」；把「空验证结果会被这行放行」记进 `docs/pitfalls.md`，并作为上游缺陷一起报（属 `count_result_items` 的口径问题）。

**5. `README.md:253` — 把 `git commit --no-verify` 写成合规的「临时绕过」，与本仓禁止项冲突**
- 问题：升级进来的这条说「临时绕过：`git commit --no-verify`（别习惯性用）」，而 `AGENTS.md` 编码规范「禁止」里明确写了「用 `git commit --no-verify` 绕闸门」。
- 证据：`AGENTS.md` 编码规范末条禁止项；两文件对同一动作一个「禁止」一个「临时绕过」。
- 严重度：Minor
- 建议：删掉该半句，或改成「禁止 `--no-verify`（见 `AGENTS.md` 禁止项）」。

**6. `.scaffold-version:6` — `gate_violations=2` 不等于当前真实值**
- 问题：更新器把它定义为「上次跑闸门的存量违规数」，而本仓刚写进 `docs/pitfalls.md:1182` 的自查条要求它「等于当前真实值」。评审时唯一违规是缺 `review.md`（真实值 1），review.md 落地后应为 0。
- 证据：`git show f0a83d0:templates/scripts/scaffold-update.sh` 的 `gate_report()` 用 `grep -c '^  \[x\]'` 计数、`--refresh-gate-count` 专门负责刷新；`docs/pitfalls.md:1182` 的原文要求。
- 严重度：Minor
- 建议：收尾前跑一次 `bash <scaffold>/scripts/scaffold-update.sh <项目目录> --refresh-gate-count`（只改计数不动文件），或手改成 0，并在 `journal.md` 贴一次实跑输出。

**7. `data/news.json` — 生成物改动混进本次改动集，且不在 plan 范围内**
- 问题：整份资讯快照被刷新（date 2026-11-04 → 2026-11-05），与本任务无关，却位于同一工作区改动里，容易被 pathspec 之外的 `git add` 顺手带走。
- 证据：`git status` 列出 `M data/news.json`；内容为当日华尔街见闻抓取；plan 的「相关文件」无此项；`AGENTS.md` Working Rules「不修改 `.env`、生产配置、生成文件」与编码规范禁止「改 `.env` 与生成物」；该路径本就在 `src/git_ops.py` 的 `_DATA_PATHS` 自动提交白名单内。
- 严重度：Minor
- 建议：本次提交的 pathspec 显式排除 `data/news.json`（交给 `scripts/auto_commit_data.py` 链路），或在 journal 记明「由本任务期间的运行产生、不纳入本次提交」。

**8. `docs/pitfalls.md:1158` — 误判构成的数字与自己的合计对不上**
- 问题：写 `reports/（~250，生成物）`，但同段合计是 313 项，33+6+~250+64 算不出来；实测 reports/ 是 210。
- 证据：`grep -c '^  \[x\] reports/' /d/tmp/gates-after-sync.txt` = 210；`venv/` 33、`.venv/` 6、`.workbuddy/` 64，合计正好 313。
- 严重度：Minor
- 建议：`~250` 改成 `210`。

## Spec

**9. `docs/agents/任务分级.md:66` — 新增段落描述的是新闸门的规模底线，kept gate 没有这些行为**
- 问题：该段写「取两者的最大值：本次索引自己的改动数、以及所有在飞 **T0 / T1** 任务各自的累计值——报错会点名是哪个任务，改动全在本次索引里时写「本次改动」」。这三项（在飞 T0/T1 累计、报错点名、`本次改动` 措辞）都只在模板新脚本里；本地脚本在「没碰任务目录」时只量索引，且只要候选任务声明了 T2/T3 就直接 `return 0`。
- 证据：`grep -n "本次改动" scripts/check-gates.sh scripts/check-gates.awk` 无命中；`scripts/check-gates.sh` 的 `check_scale()` 里无空索引短路、无 `tasks/*/` 累计循环；模板侧对应代码见 `git show f0a83d0:templates/scripts/check-gates.sh` 的 `check_scale`。
- 严重度：Major
- 建议：`docs/agents/*` 是机制文件 ⇒ 这一节随脚本一起 `keep-local`（模板再变就重判），或在段首明确「本仓当前闸门未实现此段，见 `docs/pitfalls.md`」并接受下次同步冲突。当前状态等于把一个未落地的规则当成流程真源。

**10. 回滚记录低估了「放弃」的范围**
- 问题：plan 步骤 4 与 `docs/pitfalls.md:1154` 只写「放弃本次两条新校验（文档断链 / ADR 互指）」，但这次回滚同时丢掉了模板里的两处**修复**：`emit_violations` 改数非空行（否则汇总项数比屏幕多 1）、`check_scale` 的空索引短路与在飞任务累计。下次同步时只看断链 bug 会漏掉这两项。
- 证据：`diff --strip-trailing-cr` 模板 vs 本地 `check-gates.sh` 的 `emit_violations`（本地 `while ...; do n=$((n+1))` 无 `[ -n "$l" ]`）与 `check_scale` 两处 hunk。
- 严重度：Minor
- 建议：在 `docs/pitfalls.md` 那条里补一行「同时放弃：违规计数 off-by-one 修复、规模底线空索引短路/在飞累计」，或拆成三条上报项。

**11. plan 步骤 4 的「缺陷报上游」没有任何留痕**
- 问题：决策依赖「机制不 fork、报上游」成立，但两个仓库里都找不到报告证据；`.scaffold-version` 只记 sha，不记原因，理由只在任务快照 `plan.md` 与 `docs/pitfalls.md` 里，且都没有「已报 / 待报」。
- 证据：上游 `project-scaffold` HEAD 仍是 f0a83d0（2026-11-05 18:06 提交，之后无提交），无 issue/报告文件；本仓 plan/pitfalls 全文无报告链接或日期；上游 `README.md:142` 要求机制文件本地改动「应当报上游」。
- 严重度：Minor
- 建议：在 `docs/pitfalls.md` 那条加一行「上游报告：<链接/日期>」或「待报（本仓零写入约束）」，否则下次同步无法判断这个 keep-local 是否还有必要。

**12. `tasks/2026-11-05-scaffold-sync/plan.md:5,8-12` — 文件范围与实际改动不一致**
- 问题：档位写「T2 — 18 文件」，`docs/pitfalls.md` 在「相关文件」里被归为「保留（本地改过、模板未动）」，但实际本次给它**新增 32 行**（整个 keep-local 决策段）；实际改动是 12 改 + 1 新增目录（3 文件），与 18 不符。
- 证据：`git status --porcelain`（12 个 M + `?? tasks/2026-11-05-scaffold-sync/`）；`git diff HEAD -- docs/pitfalls.md` 为 +32 行。
- 严重度：Minor
- 建议：把 `docs/pitfalls.md` 从「保留」挪到「本次修改」，并把档位里的文件数改成实际值；否则「档位声明与实际文件范围一致」这个勾是无据的。

## 逐条处理

| # | 审查者发现（原文摘要） | 处理 | 依据 |
|---|---|---|---|
| 1 | `AGENTS.md:104` 闸门能力被写成既定事实（文档断链 / ADR 互指），实际脚本已回滚 | **改** | 该行删掉这两项，末尾加「⚠️ 上游 `f0a83d0` 新加的…本仓**未启用**（`keep-local` 裁决，理由见 `docs/pitfalls.md` 2026-11-05）」。复跑 `sh scripts/check-gates.sh` → 0 项（review.md 落地后） |
| 2 | `README.md:250` 同一处失实 | **改** | 同条口径重写：只列实际启用的校验 + 括注「本仓未启用」；`check_scale`/规模低报保留（确实存在） |
| 3 | 新 journal 模板示范「条目 + `→` 下一行」，kept gate 逐行判 ⇒ 照它写会被拦 | **改** | ① `git checkout HEAD -- tasks/_template/journal.md` 整份回滚并记 `keep-local`（sha `9433342…`）；② `tasks/README.md:117` 改写为「**同一行**，续行不算；上游 f0a83d0 的『按条目判』本仓未启用」。自验探针：`awk -v kind=journal …` 对「条目一行 + 缩进 `→`」输出 `[x] …「下次注意什么」这条没有去向: 改 A 必须同步 B`（见 `journal.md`「遇到的问题」） |
| 4 | 「闸门不会把它算成一条验证结果」是错的（`- 返工/被打回: 0 次` 会被计为一条结果 ⇒ 假阴性） | **改** | `tasks/README.md:118` 改成「不查（但这一行**会**被算成一条验证结果 ⇒ 只剩它时闸门看不出『验证结果为空』）」；该口径写进 `docs/pitfalls.md` 的上游缺陷 ④ |
| 5 | `README.md:253` 把 `--no-verify` 写成「临时绕过」，与 `AGENTS.md` 禁止项冲突 | **改** | 改为「**禁止** `git commit --no-verify` 绕闸门（见 `AGENTS.md` 编码规范的「禁止」）」 |
| 6 | `.scaffold-version` 的 `gate_violations=2` 不是当前真实值 | **改** | review.md 落地后跑 `scaffold-update.sh <项目> --refresh-gate-count` → 写回 0（实跑输出见 `journal.md` 验证结果） |
| 7 | `data/news.json` 生成物改动混进改动集 | **不改** | 不是本任务产生：它在 `src/git_ops.py` 的 `_DATA_PATHS` 自动提交白名单内，属数据链路产物；本次提交用显式 pathspec，只点 13 个文档/基线路径 + 任务目录，不含 `data/`。理由记入 `journal.md` |
| 8 | `docs/pitfalls.md:1158` 的 `~250` 与合计 313 对不上（实测 210） | **改** | 改成 `210`；并核 `grep -c '^  \[x\] reports/' /d/tmp/gates-after-sync.txt` = 210 |
| 9 | `docs/agents/任务分级.md:66` 描述的新规模底线本仓未实现 | **改** | 该段改写成「只看**本次索引**自己的改动数」+ 括注上游增强版未启用（`keep-local` 裁决）；同时整份记 `keep-local`（sha `b18e60a…`），保留新 seam 措辞 |
| 10 | 回滚范围被低估（同时放弃 `emit_violations` 非空行修复、`check_scale` 空索引短路/在飞累计） | **改** | `docs/pitfalls.md` 加「**回滚同时放弃了 3 项模板修复**」并逐条列出（第三项是 journal 按条目判） |
| 11 | 「缺陷报上游」无留痕 | **改** | `docs/pitfalls.md` 加「**上游报告**：待报（本仓对脚手架仓库零写入）」+ 四条缺陷清单；本仓对上游仍零写入 |
| 12 | plan 的档位文件数（18）与「相关文件」清单与实际不符 | **改** | 改为 `T2 — 13 文件`；`docs/pitfalls.md` 移到「本次按本仓实况改过的文档」；新增「本次新增 `keep-local` 裁决」行；步骤表补 4b |

## 审查者明确未判断的

1. `sh scripts/check-gates.sh --staged` 在最终索引上的结果——审查者没有提交、也没有跑该模式。**收尾时已实跑**，见 `journal.md` 的验证结果。
2. `pytest tests/ -q` 的结果（审查时还在进行中）。**收尾时已实跑**：880 passed。
3. 385 项里那 72 项是否 100% 都是误判——审查者抽看了但未逐条对仓库历史核实。
4. `--keep-local` 的 sha 口径：审查者按 `git rev-parse <commit>:templates/<path>` 的 blob 核对（两条相等），未跑更新器确认内部 `template_sha` 与 blob 在所有情形下一致，也未跑下一次同步验证裁决会被跳过。
5. `AGENTS.md` 合并时模板侧另外两处改动（plan.md 示例路径改成 `todo-title-search`、新增「动手前先确认钩子真的挂上了」bullet）是否被有意保留成本仓等价表述——审查者判不出是取舍还是遗漏。
6. `data/news.json` 的改动是不是本任务期间跑程序产生的（时间线无法闭合）。
7. 上游是否已在对话/issue 里收到断链 bug 的报告——两个仓库内都没有留痕，无法确认。
8. `docs/adr/README.md` 新增的「被否决方案先写最强理由」「两边都要写」两条建议本身是否适用于本仓（只核了它声称的闸门能力，未评价内容主张）。
9. `.githooks/pre-commit` 本身没变、也没实跑；钩子在新旧脚本组合下的真实拦截行为未验。

## 结论

审查者结论：无 Critical，但**不建议原样提交**——4 条 Major 属同一类（新文档描述了 kept gate 不存在的能力），其中第 3 条会让下一个照模板写 journal 的人被自己仓库的闸门拦下。

处理结论：第 1–6、8–12 条已改并复跑验证；第 7 条按「不是本任务产生、走数据链路」不改并留痕。第 3 条的根因（机制模板与 kept gate 不一致）无法在本仓消除，已记 `keep-local` + 缺陷清单待报上游。复跑：`sh scripts/check-gates.sh` 0 项、`--staged` 通过、`pytest tests/ -q` 880 passed。
