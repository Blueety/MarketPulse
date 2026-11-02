# 审查裁决单

<!-- 只有 T2 / T3 需要这份文件（见 docs/agents/任务分级.md）。

     它由两半合成：**独立审查者的产出** + **被审查方的处理结果**。
     跨会话接手时，这份文件回答「这次改动的每一条审查意见后来怎么样了」。

     写它的人是被审查方（执行者），所以有两条硬规则：
     - 每条发现必须**逐字引用审查者的原文**，不能只写自己的总结
     - 不能静默删除任何一条 -->

## 审查范围

- **固定点**：`9900f97`（本次改动的起点；改动未提交，审查用的是 `git diff` 全量工作区快照 + 9 个未跟踪新文件）
- **审查者**：独立子 agent `ScaffoldMergeReview`（reviewer 角色）——它**没有接触主线程的会话历史**，只看下面这几样
- **给了它什么**：`plan.md`（本次无 `prd.md`，Spec 基准即 plan 的「目标 / 不做什么 / 步骤」）、`git diff` 全文（1203 行）、9 个未跟踪新文件的路径清单、`AGENTS.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` / `CONTEXT.md`
- **轮次**：第 1 轮

## 审查者原文

## 改动摘要

这是一次**脚手架同步**（`project-scaffold` → MarketPulse 的三方合并落盘），意图层面要达成三件事：① 把脚手架 v2 的流程机制（档位改为「T0/T1 通知、T2/T3 批准」、独立子 agent 审查、决策单 `review.md`、5 个模板）搬进来；② 装一套可机器判定的提交前闸门（`scripts/check-gates.sh` + `.awk` + `.githooks/pre-commit`），但因存量违规暂不启用；③ 人工补写 `docs/architecture.md` 的「接口契约 / 数据模型」与 `README.md` 的「技术栈 / 开发约定 / 相关文档」。影响面在文档与流程脚本，`src/` `web/` `data/` 零改动（`git diff --stat` 18 文件 + 9 个未跟踪新文件，无冲突标记残留）。新增概念有四个：机械闸门（`check-gates`）、裁决单（`review.md`）、切片文件（`NN-*.md`）、脚手架基线（`.scaffold-version`）；未动公开接口与数据形状。

## Standards

### 硬违规

- **[AGENTS.md:67-80]** 新增的「## 编码规范」整节以模板占位符落地（`- **命名**：\`<文件 / 组件 / 函数 / 变量 / 常量 各用什么形式>\`` 等 8 条），没有一条是 MarketPulse 的实际约定。这不是「留空」，是**把填充指令当成规则发布**，而同一批改动引入的 `skills/pre-review/SKILL.md:96-97`（「硬违规只能引用写在这里的东西……这一节留空等于 Standards 轴永远报不出硬违规」）与 `skills/self-audit/SKILL.md:120-126`（走查第 6 步专查本节）都把它当作唯一硬违规来源。结果是：本次同步宣称建立了 Standards 轴的规范底座，实际给的是一个永远报不出硬违规的空壳 —— 违反 `AGENTS.md` 自身新增的这条约定。建议要么填真实约定，要么删掉本节并注明「未填，硬违规暂不可判」。
- **[AGENTS.md:103,105]** 同一节相邻两条互相打架：103 行说「提交前闸门是**自动**的：`.githooks/pre-commit` 会跑 `scripts/check-gates.sh --staged`……**不要**用 `git commit --no-verify` 绕过」，105 行紧接着说「**钩子暂未启用**（`core.hooksPath` 为空）」。实测 `git config core.hooksPath` 为空（退出码 1）、`sh scripts/check-gates.sh --staged` 现跑出 7 项违规但**没有任何东西拦提交**。读者按 103 行行动（认为有阻断、不去手工跑）就会把违规提交进去，这属于把「装了但没启用」写成「已生效」的表述失实。建议把 103 行改成「启用后……」，或把 105 行的 caveat 前置为条件句。
- **[AGENTS.md:116]** Done Means 要求「跑过 lint 与 typecheck」，而同一文件 65 行写「Lint / Typecheck / Build: 无（纯 Python 脚本项目，暂未配置）」，`docs/commands.md` 也没有任何 lint 入口。两条要求互斥，导致每个任务都只能写「未运行 + 原因」，等于把一条永久不可满足的验收项塞进流程。建议改成「本项目未配置 lint（见 Commands），跳过并说明」。
- **[README.md:15]** 新增的技术栈写「Web 看板 HTTP Basic Auth（`WEB_AUTH_*`，Railway 侧配置）」，本仓库不存在 `WEB_AUTH_*`：实际变量是 `MP_AUTH_USER` / `MP_AUTH_PASS` / `MP_AUTH_DISABLED`（`README.md:121-123` 同文件自证，`docs/commands.md:33`、`docs/architecture.md:49`、`.workbuddy/memory/MEMORY.md:181` 一致）。照新写的前缀去 Railway 配变量会配了个没人读的键。
- **[docs/architecture.md:41,45,54]** 新增的接口契约有四处与代码对不上，且自相矛盾：
  - 「**3 个页面路由 + 9 个 JSON API**」，同句括号里却列了 6 个页面（`/` `/macro` `/macro/cn` `/timeline` `/backtest` `/settings`），`web/app.py` 实际是 6 个 HTML 路由 + 12 个 `GET /api/*` + 1 个 `POST /api/settings`；
  - 45 行的 API 清单漏了 `/api/timeline`（`web/app.py:1117`）、`/api/backtest`（:1160）、`/api/settings`（:1193/:1202）；
  - 41 行说「全部只读」，54 行说「`/settings` 的 `POST` 是唯一写入口」—— 同节两句互斥，且写入口根本不是 `/settings`（该路径只有 `@app.get("/settings", ...)`，`web/app.py:1222`），是 `POST /api/settings`。
- **[docs/architecture.md:67]** 数据模型「谁能写」列写 `storage.append_history` / `merge_history`，这两个函数不在 `storage.py`：实际定义在 `src/analyzer.py:731`（`append_history`）与 `:746`（`merge_history`），`storage.py` 对外是 `upsert_history_rows`（`src/storage.py:185`）。同文件 146 行的既有决策表自己写的是「`analyzer.load_history/append_history/merge_history` 三函数签名不变」，前后冲突。
- **[skills/pre-review/SKILL.md:9,60]** 新增的 scoped `allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git log:*)`，但流程第 1 步要跑的正是 `git add -A`（60 行）。同文件 4-8 行的注释写明 scoped 权限的目的就是「第 1、2 步要跑它们，不放行的话审查者按 skill 走会直接卡在第一步」—— 恰恰没放行第 1 步的 `git add`。任何按 skill 走的独立审查者都会在第一步被自己的权限挡下。（顺带：`git add -A` 与 `AGENTS.md:96` 对该命令的禁止表述方向相反，虽然那条限定在自动提交上下文，技能正文把它写成标准步骤会放大歧义。）
- **[docs/commands.md:43-50]** 新增了强制闸门，但「提交前（闸门 B 清理）」表里没有它：`sh scripts/check-gates.sh` / `--staged` 一次都没出现，而 `AGENTS.md` 声明 `docs/commands.md` 是命令真源（`AGENTS.md:46`「改行为前：`docs/commands.md`」），且 `AGENTS.md:103` 让读者去跑一个本文件里查不到的命令。该表仍以 `grep -rn "\[DEBUG-"` 为唯一判据，与 `AGENTS.md:117`「提交时 `scripts/check-gates.sh` 会自动验」并存，读不出哪个是当前判据。
- **[scripts/check-gates.sh:228]** 规模底线按「**任一**候选任务声明了 T2/T3 就放行」，而 `docs/agents/任务分级.md:45,64` 的措辞是「**这个任务**累计改了 4 个 `src/` 文件而没有 T2/T3 就拦下」。实现在候选列表上 `task_is_high_tier "$d" && return 0` 短路，且候选为空时会退回**所有在飞任务**，于是：一个只改代码（没碰任务目录）的 10 文件提交，只要仓库里任意一个在飞任务是 T2，就通过。这道闸门本来的定位是「T0/T1 不再等人确认的唯一机械兜底」，这个短路把兜底变成了可绕过的。

### 判断题（坏味道）

- **[docs/agents/架构师.md:26,53]** 标题体系分裂：文件里 8 节都是 `【前置阅读】`/`【你的职责】` 这类 `【】` 伪标题，新增/改写的两节却是真 Markdown `##`（`## 项目尺度架构设计`、`## UI / 视觉类问题`），而紧跟其后的又是 `【任务尺度输出：plan.md】`。同一份文件一半靠 H2 划节、一半靠方括号，任何按标题遍历的工具（本仓库的 `check-gates.awk` 就有 `md_section`）在这份文件上会漏掉 8 节里的 8 节。是模板并入项目文件时只换了标题符、没统一。
- **[AGENTS.md:39-40]** 指向本仓库不存在的脚本：40 行说 `.scaffold-version` 由 `scripts/scaffold-update.sh` 写入，但 `scripts/` 下只有 `auto_commit_data.py` / `backfill_history.py` / `backtest.py` / `backup_db.py` / `check-gates.*` / `probe_cn_macro.py` / `push_retry.sh` / `render_report_image.py` / `sync_econ_calendar.py`，没有这个更新器（它住在外部的 project-scaffold 仓库）。同理 `.githooks/pre-commit:5` 写「由 init 脚本通过 `git config core.hooksPath .githooks` 启用」，本仓库也没有这个 init 脚本 —— 两处都会让读者去找一个不存在的文件。
- **[AGENTS.md:105]** 对存量违规的归因不实：「914 条（旧任务 + `docs/architecture.md` 模块表与 `src/` 实际文件名大规模不符）」。实测 `sh scripts/check-gates.sh` 报 915 项，按消息归类是 89×「缺 `## 主要提交`/`## 雾区变化`/`## 一致性走查`/`## 结束状态`」、87×「缺 `## 涉及的 ADR`」、83×「缺 `## 任务概要`」等旧任务缺新模板章节，**涉及 `architecture.md` 的只有 6 项**；而且这 6 项的原因是模块表第二列带了说明文字（`src/econ_values.py（2026-09-19 新建）`、`web/app.py（FastAPI 应用 + 5 端点）、…`），文件本身都在，不是「文件名不符」。把主因写成架构表会误导后续清零的人先去重写模块表。
- **[scripts/check-gates.awk:453-454]** 注释与实现不符：注释称「目标没写就是空的，`field_filled` 已经管住了」，但 `plan_check` 里没有任何 `field_filled("目标")` 调用（全文 `field_filled` 调用点见 :438-:594，无「目标」）。`AGENTS.md:90` 要求计划包含目标，闸门实际不查；这条注释会让下一个维护者以为已覆盖。
- **[docs/architecture.md:87]** 新增的数据模型说实体都在 `data/marketpulse.db`，但同文件「数据流」仍写 `├──> data/history.json（按 date 追加/覆盖，90 天滚动）`，「关键决策」表也还有「历史存储 `data/history.json` 列表按 date 键追加/覆盖，仅保留最近 90 条」。新增节直接与同文件其余章节矛盾，而 plan 步骤 4 的验证是「通读新增两节」—— 通读没覆盖邻节。（前两处是 SQLite 化之前的历史文本，本次没被要求改，但既然新增节把它们证伪了，不一起修就等于新造一处文档矛盾。）

### 各维度

- **Correctness**：[scripts/check-gates.sh:228] 规模闸门短路绕过（见上）；其余主路径实跑通过（`--help` 退出码 0、全量 915 项、`--staged` 7 项）。
- **Performance**：无问题。全量自查实测约 24s、`--staged` 2.5s，符合脚本头「搬进 awk 把分钟级降下来」的说明；`mktemp` 物化整棵索引后 `trap 'rm -rf'` 清理。
- **Tests**：新增的 `check-gates.sh` / `.awk` / `pre-commit` 没有任何自动化测试，只有手工冒烟（我跑的三种模式）。仓库既有 pytest 套件覆盖不到文档/脚本，尚无回归护栏；这属于新增脚本的常态风险，不单独计为缺陷，但建议至少把 `--help`/空索引/一个故意违规的 fixture 固化成测试。
- **Security**：未发现问题。`check_gate_b` 用 `git grep -I -i` 而非 `eval`；临时目录路径全程加引号；`.githooks/pre-commit` 无参数透传注入面。
- **Conventions**：见判断题两条（`架构师.md` 标题体系、失效脚本指针）。
- **Docs**：本轮改动是文档占大头，问题集中在「新增的活文档与代码现状不一致」（`README.md:15`、`architecture.md:41/45/54/67`、`commands.md:43-50`、`AGENTS.md:67-80/103/105/116`）。`docs/pitfalls.md` 两条新增与 `docs/commands.md` 的「UI 变更怎么验」是准确的：三条 verify 脚本路径我逐个验过都在。

## Spec

Spec 基准：`tasks/2026-11-02-scaffold-sync/plan.md`（本次无 `prd.md`）。

### 缺失 / 部分实现

- **[AGENTS.md:73-80]** 部分实现。plan「目标」是「把已生成项目的脚手架文件三方合并到脚手架 6eb5ee9；9 个两边都改过的文件逐个裁决，冲突残留清零」，模板带来的「## 编码规范」节被原样留在交付里（8 条 `<…>` 占位）。同步的意图是「装进来的机制可用」，而这一节装进来的是不可用状态的机制（Standards 轴无硬违规来源）。要么按本仓库实际约定填，要么明确写成「未填 + 原因」并让 `pre-review` 降级为只跑坏味道。
- **[docs/architecture.md:41,54,67]** 部分实现（plan 步骤 4「补架构文档缺失的两节（接口契约 / 数据模型）」）。两节确实写了（`39-78`），但内容与代码对不上：端点数量、唯一写入口路径、`append_history` 归属模块三处错误。验收层面这等于「补了节」而不是「补了正确的节」；`skills/self-audit/SKILL.md:110-116` 明确说这两节「机器完全不查，是最容易烂的地方」，必需靠人对着代码核 —— 这次没核。

### 范围蔓延

- **[docs/pitfalls.md:147-157]** plan 的「不做什么」只允许「不改 `docs/pitfalls.md` / `docs/commands.md` 的既有条目，只做并集」，但这两条（Windows `bash.exe` 是 WSL 桩、Git Bash PATH 缺 `/usr/bin`）不是并集产物而是本次新写的内容，且带本机绝对路径 `D:/Claude/Git/usr/bin/bash.exe`。与本次同步无直接关系（是操作脚手架更新器时踩的坑）。同样 [docs/commands.md:56-70] 的「UI 变更怎么验」表也是新增内容而非并集，虽然内容准确、指向的脚本都存在。两条都不算错误，但按 plan 的字面范围属于夹带。

### 实现可疑

- **[AGENTS.md:103,105]** 见 Standards 硬违规第 2 条：闸门「自动」与「未启用」并存，是本次最容易被后续会话误读的表述。
- **[scripts/check-gates.sh:228]** 见 Standards 硬违规最后一条：规模兜底与 `docs/agents/任务分级.md:45,64` 的判据不是同一个口径。
- **[skills/pre-review/SKILL.md:9,60]** 见 Standards 硬违规：scoped 权限与本 skill 自己的第 1 步冲突，按 skill 走会被自己挡住。

### 验收标准 → 证据

plan 没有「## 验收标准」节，只有「验证命令」与各步骤的「验证」列，逐条对证据：

- `venv/Scripts/python -m pytest tests/ -q` → **无证据**（本次只读审查未运行；任务目录只有 `plan.md`，没有 `journal.md` 落验证结果）。
- `grep -rn '<<<<<<<'`（必须无输出）→ **已验证**：`grep -rn '^<<<<<<<\|^>>>>>>>' --include=*.md .` 无输出。
- `sh scripts/check-gates.sh --help` → **已验证**：退出码 0，usage 正常打印。
- 步骤 3「9 个冲突文件逐个裁决」→ 部分可验：diff 的 18 个修改文件均无冲突标记；但「裁决是否保留了项目既有内容」只能逐 hunk 读（我读了，见小结），无 git 侧证据。
- 步骤 4「补架构两节 → 通读新增两节」→ **已证伪**：两节与代码不符（`docs/architecture.md:41/54/67`），且与同文件「数据流」矛盾（:87）。
- 「不在 `docs/` 之外引入行为变化」→ 已验证：`git diff --stat` 无 `src/` `web/` `data/` 条目。

## Verification

- 已运行（全部只读）：
  - `git diff`（读 `D:/tmp/omp/scaffold-diff.patch` 全文 1203 行，含 `--stat` 尾部）
  - `wc -l` 新增 9 个未跟踪文件；`cat .scaffold-version`；`git config core.hooksPath`（空，退出码 1）
  - `grep -n "@app\.\(get\|post\|route\)" web/app.py`（路由清单：6 HTML + 12 GET API + 1 POST API）
  - `grep -n "WEB_AUTH\|MP_AUTH"` 全仓（证明 `WEB_AUTH_*` 不存在）
  - `grep -n "^def " src/storage.py` + `grep -rn "def append_history\|def merge_history"`（证明二者在 `src/analyzer.py`）
  - `sed -n '36,90p' src/storage.py`（三张表与列比对 `docs/architecture.md:67-70`）
  - `grep -n "TTL" web/app.py`（6h / 300s / 90s 缓存口径）
  - `grep -n '^<<<<<<<' --include=*.md`（无输出）
  - `sh scripts/check-gates.sh --help`（exit 0）
  - `sh scripts/check-gates.sh`（915 项，含按消息归类统计；`grep -c architecture.md` = 6）
  - `sh scripts/check-gates.sh --staged`（7 项：6 条架构模块表 + 本任务缺 `review.md`）
  - `ls` 三条 verify 脚本（`verify_ui.py` / `verify_skin.py` / `verify_scroll_degrade.py` 均存在）
- 未运行：
  - `pytest tests/ -q` —— 本次是只读文档审查，且不承担执行者侧的验证职责；plan 的该条验收因此在我这里记为「无证据」。
  - `verify_ui.py` / 任何 UI 验收 —— 本次零前端改动，无触发条件。
  - `sh scripts/check-gates.sh tasks/_archive/...` —— 仓库尚无 `tasks/_archive/`。

## 未判断的

- **9 个冲突的「裁决」是否忠实于 scaffold 模板原版** —— 看不到 `project-scaffold` 仓库（`.scaffold-version` 指向 `/d/Obsidianhouse/AISTUDY/project-scaffold/project-scaffold`，本机不可读），无法逐行区分「模板演进」与「本地改写」。我只能验证结果的内部一致性。
- **914 与实测 915 的差额来源** —— `.scaffold-version` 记的是安装时刻的计数，本次新增的 `tasks/2026-11-02-scaffold-sync/plan.md`（及其缺 `review.md`）可能正好贡献 1 项，但没有安装时刻的原始输出可比对。
- **`pre-review` 的 scoped `allowed-tools` 是否真的会拦 `git add -A`** —— 取决于 harness 对 `Bash(git diff:*)` 的匹配实现，仓库内无从验证；我只能判定「技能正文要求的命令不在自己声明的权限里」这一事实。
- **README 的「281 测试通过」与 plan 的「877 条既有测试」哪个对** —— 前者是 diff 之外的既有文本，后者是 plan 的档位说明，两者互相矛盾但都不属于本次 diff 的产物。
- **`docs/commands.md:14`「5 个 JSON API」、`tests/test_web.py` 的「4 页 10 API」与实际的 6 页 / 13 端点** —— 均属 diff 之前的既有文本，未在本次改动范围内，故不列为发现，但它们是 `architecture.md:41` 那句错话可能的上游来源。
- **`scripts/check-gates.awk` 在本机 locale 下的多字节匹配是否全部正确** —— 我读了作者为此写的大量注释（全角冒号、`（`/`(` 分支匹配、字节级 `index`），但没有构造非 UTF-8 locale 的用例实跑，无法证实 `/usr/bin/env -u LANG awk` 下行为不变。

## 小结

- **Standards**：13 条，最严重 —— `AGENTS.md:67-80` 把「编码规范」以模板占位符发布，使本次同步宣称建立的 Standards 硬违规底座实质为空；次严重是 `AGENTS.md:103/105` 把未启用的闸门描述成自动生效。
- **Spec**：4 条，最严重 —— plan 步骤 4 的「补接口契约 / 数据模型」只做到了「补了节」：`docs/architecture.md:41/54/67` 的端点数量、唯一写入口路径、`append_history` 归属模块三处与 `web/app.py`、`src/analyzer.py` 直接冲突，而这两节正是 `self-audit` 声明机器完全不查、只能靠人核的地方。

## 逐条处理

| # | 审查者发现（原文摘要） | 处理 | 依据 |
|---|---|---|---|
| S1 | `AGENTS.md:67-80` 编码规范以模板占位符发布，Standards 硬违规来源是空壳 | **改** | 已按本仓库既有做法填满 8 条（命名 / 目录 / 错误处理 / 输入校验 / 密钥 / 依赖 / 测试 / 禁止），每条都指到代码或命令（`src/fetcher.py` `SYMBOLS`、`web/app.py` `_ASSET_FILES`、`src/env_util.require_env`、`tests/test_env_util.py`、`conftest.py` 的 `AUTO_PUSH=0`）。`AGENTS.md:73-80` |
| S2 | `AGENTS.md:103,105` 「闸门是自动的」与「钩子暂未启用」并存，等于把未生效写成已生效 | **改** | 改成「启用后由 `.githooks/pre-commit` 跑 `--staged` 自动拦截」，并把「⚠️ 钩子当前未启用（`core.hooksPath` 为空）」独立成条、放在最前。实测 `git config core.hooksPath` 为空、`sh scripts/check-gates.sh --staged` 7 项违规却无物拦提交。`AGENTS.md:103-104` |
| S3 | `AGENTS.md:116` Done Means 要求 lint/typecheck，而 Commands 声明未配置 | **改** | 该条改为「lint 与 typecheck（本项目未配置，见 Commands ⇒ 跳过并说明）」。`AGENTS.md:115` |
| S4 | `README.md:15` 写 `WEB_AUTH_*`，实际是 `MP_AUTH_*` | **改** | 改为 `MP_AUTH_USER` / `MP_AUTH_PASS` / `MP_AUTH_DISABLED`（`web/app.py:133-142` 实证）。顺带把过期的「281 测试通过」改为实测 877 |
| S5 | `docs/architecture.md:41,45,54` 端点数量 / 唯一写入口 / 「全部只读」三处与 `web/app.py` 不符 | **改** | 按 `grep -n '@app\.\(get\|post\|route\)' web/app.py` 的实际路由重写：6 页面 + `/healthz` + 12 个 `GET /api/*` + 1 个 `POST /api/settings`；写明 `/settings` 只有 `GET`、写入口是 `POST /api/settings`；补 `/api/timeline` / `/api/backtest` / `/api/settings`。`docs/architecture.md:41-63` |
| S6 | `docs/architecture.md:67` 把 `append_history` / `merge_history` 归给 `storage.py` | **改** | 改为 `src/analyzer.py` 的 `append_history` / `merge_history` → `src/storage.py` 的 `upsert_history_rows`（preserve/overwrite 双模式）；初改时我写的 `append_history_rows` 在 `storage.py` 并不存在，`grep -n '^def ' src/storage.py` 核对后已删。`docs/architecture.md:71` |
| S7 | `skills/pre-review/SKILL.md:9,60` scoped `allowed-tools` 没放开第 1 步的 `git add -A` | **改** | 加 `Bash(git add:*)`、`Bash(git status:*)`，并把第 1 步的 `git add -A` 注明「只为出审查用的 diff，不是提交动作，真正提交仍受 AGENTS.md 范围白名单约束」。`skills/pre-review/SKILL.md:9,61-63` |
| S8 | `docs/commands.md:43-50` 闸门 B 表里没有新增的 `check-gates.sh`，与「commands 是命令真源」冲突 | **改** | 表首两行加 `sh scripts/check-gates.sh --staged`（判据 0 项违规）与 `sh scripts/check-gates.sh`（存量基线 914，不判单次改动），并标注钩子未启用。`docs/commands.md:49-50` |
| S9 | `scripts/check-gates.sh:228` 规模兜底按「任一候选任务为 T2/T3」短路，可被任意在飞 T2 任务放行 | **不改** | 这是**脚手架机制文件，与 `project-scaffold` 6eb5ee9 逐字节一致**（本仓政策：机制类文件不本地化，否则每次同步都冲突）。当前钩子未启用 ⇒ 不产生实际拦截；已记入本任务 journal 的「下一步」，作为给脚手架仓库的上游修复建议（判据应改为「本任务累计 `src/` 改动 ≥4 文件且该任务档位 < T2」） |
| J1 | `docs/agents/架构师.md` 一半 `【】` 伪标题、一半 `##` | **不改** | 同上：`docs/agents/*` 是脚手架机制文件，本次按模板整份取新版（`diff ours/base` 仅 1 行 whitespace）。标题体系问题出在模板本身，属上游 |
| J2 | `AGENTS.md:39-40` 指向本仓库不存在的 `scripts/scaffold-update.sh` | **改** | 写明该脚本在**仓库外** `D:/Obsidianhouse/AISTUDY/project-scaffold/project-scaffold/scripts/scaffold-update.sh`，本仓库没有。`AGENTS.md:40` |
| J3 | `AGENTS.md:105` 把 914 条存量违规主因归给 architecture 模块表 | **改** | 改为「绝大多数是旧任务缺新模板章节（各数十条），architecture 模块表只有 6 条（第二列把说明文字写进了路径）」。`AGENTS.md:104` |
| J4 | `scripts/check-gates.awk:453` 注释称查「目标」，实际没查 | **不改** | 同 S9：上游机制文件。已在 journal「下一步」里记为上游缺陷 |
| J5 | `docs/architecture.md:87` 新增「数据模型」与同文件「数据流 / 关键决策」里遗留的 `data/history.json` 矛盾 | **改** | 数据流的 `data/history.json（90 天滚动）` 改为 `data/marketpulse.db`（history 长表；`history.json` 仅 `--history` 演练用）；关键决策里那条旧记录标注「已由三十一期 SQLite 化取代」；模块表 `web/app.py（5 端点）` 同步改为真实路由数。`docs/architecture.md:33,91,115` |
| P1 | Spec：`AGENTS.md:73-80` 部分实现（占位符） | **改** | 同 S1 |
| P2 | Spec：`docs/architecture.md:41,54,67` 部分实现（补了节但内容错） | **改** | 同 S5 / S6；本轮改后逐条对过 `web/app.py` 路由表与 `src/storage.py` 函数表 |
| P3 | Spec 范围蔓延：`docs/pitfalls.md:147-157` 与 `docs/commands.md:56-70` 是新增内容而非「并集」 | **不接受** | 反证：plan「不做什么」限定的是「**不改** `docs/pitfalls.md` / `docs/commands.md` 的**既有条目**，只做并集」——新增条目不在禁令内；且 `AGENTS.md` Working Rules 要求「任务结束后：可复用的规则追加到 `docs/pitfalls.md`」，本次两条（Windows `bash.exe` 是 WSL 桩、Git Bash PATH 缺 `/usr/bin`）正是本次操作实跑踩到的可复用规则。`commands.md` 的「UI 变更怎么验」是把模板新增的**判据**接到本仓已有的三条 verify 脚本上，属模板要求的落地而非夹带 |

## 审查者明确未判断的

- **9 个冲突的「裁决」是否忠实于 scaffold 模板原版** —— 看不到 `project-scaffold` 仓库（`.scaffold-version` 指向 `/d/Obsidianhouse/AISTUDY/project-scaffold/project-scaffold`，本机不可读），无法逐行区分「模板演进」与「本地改写」。我只能验证结果的内部一致性。
- **914 与实测 915 的差额来源** —— `.scaffold-version` 记的是安装时刻的计数，本次新增的 `tasks/2026-11-02-scaffold-sync/plan.md`（及其缺 `review.md`）可能正好贡献 1 项，但没有安装时刻的原始输出可比对。
- **`pre-review` 的 scoped `allowed-tools` 是否真的会拦 `git add -A`** —— 取决于 harness 对 `Bash(git diff:*)` 的匹配实现，仓库内无从验证；我只能判定「技能正文要求的命令不在自己声明的权限里」这一事实。
- **README 的「281 测试通过」与 plan 的「877 条既有测试」哪个对** —— 前者是 diff 之外的既有文本，后者是 plan 的档位说明，两者互相矛盾但都不属于本次 diff 的产物。
- **`docs/commands.md:14`「5 个 JSON API」、`tests/test_web.py` 的「4 页 10 API」与实际的 6 页 / 13 端点** —— 均属 diff 之前的既有文本，未在本次改动范围内，故不列为发现，但它们是 `architecture.md:41` 那句错话可能的上游来源。
- **`scripts/check-gates.awk` 在本机 locale 下的多字节匹配是否全部正确** —— 我读了作者为此写的大量注释（全角冒号、`（`/`(` 分支匹配、字节级 `index`），但没有构造非 UTF-8 locale 的用例实跑，无法证实 `/usr/bin/env -u LANG awk` 下行为不变。

对以上 6 条的处理：①②按「本机不可读脚手架仓库」接受为盲区，已由 `.scaffold-version` 记录的 commit 6eb5ee9 兜底；③已按「技能正文不得要求自己没声明的命令」直接修（S7）；④已用实测 877 统一（S4）；⑤其中 `docs/commands.md:14` 的「5 个 JSON API」在本轮顺带核对——**仍为旧值，未改**，属独立文档债，记入 journal「下一步」；⑥接受为盲区。

## 结论

第 1 轮：Standards 13 条（9 改 / 3 不改 / 1 不改见 J1）、Spec 4 条（3 改 / 1 不接受且有反证）。**无未解决的 Critical**；未解决项全部集中在「脚手架机制文件与上游仓库逐字节一致」这一政策边界上，已列为上游待办。改后复跑：`grep -rn '^<<<<<<<'`（无冲突标记）、`sh scripts/check-gates.sh --staged`（**通过**）、`venv/Scripts/python -m pytest tests/ -q` 全绿（877 passed）。

**本轮之后的追加改动（不在审查者看到的那份 diff 里）**：为了让 `--staged` 真正能当提交门用，把 `docs/architecture.md` 模块表的 6 条格式性存量违规也清了（30–35 行：把「多个路径 / 带说明文字的路径」拆成单路径 `reports/` / `alerts/` / `data/` / `web/` / `src/storage.py` / `src/econ_values.py`，说明文字移进职责列）。全仓库存量违规因此从 914 降到 908，剩下**全部**是旧任务文件缺新模板章节——那是独立治理任务，见 `tasks/README.md`。
