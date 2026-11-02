# 方案：自动提交的暂存区泄漏（pathspec 隔离）

> **任务档**：`tasks/2026-09-20-autopush-pathspec-fix/`
> **角色**：Phase 3 Step 3.3 架构师（只读分析 + 方案，**不含完整实现代码**，不改任何项目文件）
> 实测条件：2026-09-20 17:1x，本机直连。
>
> ⚠️ 本文档作者是架构师，**不直接改项目代码**（记忆/文档纠错除外）。
>
> **状态（2026-09-20 17:2x）：定稿，可交付执行者实施。** §10 三项已裁定
> （**D-1=A / D-2=A / D-3=A**，用户原话「按你的来」）。
> **实施顺序硬约束**：**先修 `src/git_ops.py`（Step 1-3），再动外部 cron（Step 4-5）** ——
> 前者影响每天都在跑的三个报告入口，优先级高于 cron；且 cron 的 wrapper 要复用前者修好的 `_commit`。

---

## 0. 结论先行

1. 🔴 **我此前对该事件的根因判断是错的，必须先纠正**：我在 `docs/system-overview.md` G7 与
   `MEMORY.md` 里写了「该 cron 越界，用 `git add -A` 抢走了源码删除」。**实测其 prompt 明确禁止了
   `git add -A` / `--all` / `.` / `commit -a`**（`jobs.json` 原文见 §2.1）。它**忠实执行了自己的 prompt**。
2. **真根因**：`git commit`（**不带 pathspec**）提交的是**整个暂存区（index）**，而不是"我刚 `git add` 的那些"。
   `git add <白名单>` 只能**添加**，无法**排除** index 里已有的内容 ⇒ 我 `git rm` / `git mv` 造成的
   **已暂存删除/重命名**被无差别带走。
3. 🔴 **影响面比 cron 更大**：`src/git_ops.py:74-75` 是**同一个写法**（`git add <paths>` + `git commit -m`），
   ⇒ **三个报告入口（daily_report / snapshot_report / opening_analyzer）有同样的洞**，
   只是以前没被触发（它们在干净工作区里跑）。
4. **修复**：把提交改成 **pathspec 限定** —— `git commit -m <msg> -- <paths>`。
   **已实测验证**该写法能精确隔离（§2.2）。
5. **两个可独立交付的修复点**：① `src/git_ops.py` 的 commit 加 pathspec（**影响三入口，优先**）；
   ② 外部 Hermes cron 改 **script 模式**（把范围从"LLM 遵守 prompt"变为"代码强制"）。
6. **顺带纠正 `docs/system-overview.md` G7 的错误根因**（我已把错误描述提交并推送到远端，需更正）。

---

## 1. 任务目标

**Goal**：让"自动提交"只可能提交白名单路径，**无论暂存区里还有什么**。

验收标准：

1. 构造"index 里有白名单外的已暂存改动（删除/重命名/修改）"的场景 ⇒ 自动提交**只**产生白名单内的提交
2. `src/git_ops.py` 的三个入口行为不变（签名、message 格式、失败语义、`AUTO_PUSH` 门控全不动）
3. `pytest tests/` 无新增失败；`test_phase26.py` 的实参断言同步更新
4. 外部 cron 改为 script 模式后，`hermes cron doctor` 无 issue，且实跑成功
5. `docs/system-overview.md` G7 的根因描述被更正

---

## 2. 取证

### 2.1 🔴 该 cron 的 prompt 原文（`/d/hermes/cron/jobs.json`，job `6f6e40a6f8b4`）

```
3. 有改动时，只提交这三个目录：
   git add data context alerts
   git commit -m "auto: 每日数据更新"
   git push origin master
   ...
硬性禁止：
- 禁止 `git add -A`、`git add --all`、`git add .`、`git commit -a`。
  这会扫走其它会话正在写的源码/测试/文档半成品（web/、src/、tests/、docs/、tasks/），
  这是本任务被收窄的唯一原因。
```

其它实测字段：`no_agent = False`、`script = None`、`workdir = None`、`deliver = 'local'`、
`schedule = */5 * * * *`、`enabled = True`。

⇒ **prompt 的作者已经想到"范围"问题，但把范围绑在了 `git add` 上**。这正是漏洞所在。

### 2.2 🔴 关键机制验证（临时仓库实测，`%TEMP%\git-verify`）

```
初始：srcfile.txt / data.txt 均已提交
操作：git rm srcfile.txt        ← 删除**直接进 index**（无需 git add）
      echo z >> data.txt; git add data.txt

暂存区：                 M  data.txt
                         D  srcfile.txt

执行：git commit -m "auto: only data" -- data.txt
提交后暂存区：           D  srcfile.txt        ← ★ 隔离成功：未被带走
```

⇒ **结论**：`git commit -- <paths>` 只提交指定路径，**index 里其它已暂存改动原样保留**。
（对照：不加 pathspec 的 `git commit` 会把这个 `D` 一起提交 —— 这就是 09-20 那次事故。）

### 2.3 项目自身的同一写法

```python
# src/git_ops.py:74-75
subprocess.run(["git", "add", *paths], cwd=str(root), check=True, timeout=_COMMIT_TIMEOUT)
subprocess.run(["git", "commit", "-m", msg], cwd=str(root), check=True, timeout=_COMMIT_TIMEOUT)
```

`_DATA_PATHS = ("data", "context", "alerts")`；`_has_changes` 用
`git status --porcelain -- <paths>`（**已有** pathspec ✓，两者原本"同范围"）。

⚠️ 但 `_commit` 的 **commit 那一步没有 pathspec** ⇒ 范围只在 `add` 侧成立，提交侧是**全 index**。

### 2.4 事故复盘（为什么以前没暴露）

| 时间 | 场景 | 结果 |
|---|---|---|
| 平时 | 三入口在**干净**工作区跑（我司 WIP 时通常没有 staged 改动） | 洞不显形 |
| 2026-09-20 16:35 | 架构师刚 `git rm` 4 文件 + `git mv` 1 文件（**全部已 staged**），**尚未 commit** | cron 的 `git commit` 无差别带走 ⇒ `6ec1562` |

⇒ 触发条件是 **"index 里存在白名单外的已暂存改动"**，与是谁 stage 的、为什么 stage 的无关。

---

## 3. 修复方案

### 3.1 核心：给 commit 加 pathspec

```
- subprocess.run(["git", "commit", "-m", msg], ...)
+ subprocess.run(["git", "commit", "-m", msg, "--", *paths], ...)
```

已验证有效（§2.2）。**仍保留 `git add <paths>`**（把未暂存的白名单改动纳入），
两者叠加 = "只把白名单加进来 + 只提交白名单"。

> 为什么不是"只留 add、去掉 commit"：`git commit -- <paths>` 会把**未暂存**的该路径改动也一并提交
> （它按 pathspec 取工作区版本），所以 `add` 仍需要，以保证 `_has_changes` 与 `_commit` 的口径一致。

### 3.2 外部 cron：prompt 模式 → script 模式

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（推荐）** | 改 **script 模式**：新增 `scripts/auto_commit_data.py`（薄封装，复用 `git_ops` 的白名单常量与函数），cron 的 `script` 字段指过去、去掉 prompt | ✅ 范围由**代码**强制，不依赖 LLM 遵守 prompt；无 token 成本；失败可见 |
| B | 保留 prompt 模式，把 prompt 里的 commit 改成 `git commit -m "..." -- data context alerts` | 改动最小，但**仍依赖 LLM 每次照做**；同样的"prompt 说了但没做"风险 |

**推荐 A**。理由：本项目的既定倾向是**机械性任务用 script 模式**（用户偏好，见 `MEMORY.md`）；
且 G7 的教训恰恰是"写在 prompt 里的约束没有机器强制"。

⚠️ **A 的落点提醒**：wrapper 必须放 **`$HERMES_HOME/scripts`**（本机 = `D:\hermes\scripts`），
**不是** `~/.hermes/scripts`（本机 `HERMES_HOME=D:\hermes`）。这条今天刚踩过，
详见 `skills/hermes-cron-script/SKILL.md`。

### 3.3 文档更正

`docs/system-overview.md` 的 G7 现写「根因：该 cron 是 prompt 模式、提交姿势由 LLM 临场决定」——
**不准确**，实际 prompt 有明确禁令且被遵守。应改为 §3.4 的口径。

### 3.4 一句话根因（供文档引用）

> **`git commit` 不带 pathspec 时提交的是整个暂存区。** 范围白名单只写在 `git add` 上是不够的 ——
> `add` 是"加法"，无法排除 index 里已有的内容。**只有 `git commit -- <paths>` 才能限定提交范围。**

---

## 4. 涉及文件清单

| 文件 | 改动 |
|---|---|
| `src/git_ops.py` | `_commit` 的 commit 加 `"--", *paths`；docstring 补一条"为什么 commit 也要 pathspec" |
| `tests/test_phase26.py` | 更新/新增实参断言：`git commit` 必须带 `--` + 白名单；新增一条"index 有白名单外 staged 改动时不提交它"的行为用例（可用临时仓库） |
| `scripts/auto_commit_data.py` | **新增**：复用 `git_ops._has_changes/_commit` 的薄封装（无参数、打印一行结果、退出码 0/1） |
| `D:\hermes\scripts\marketpulse_autopush.sh` | **新增（仓库外）**：wrapper，`cd` 到仓库后 `exec venv/Scripts/python -m scripts.auto_commit_data` |
| `docs/system-overview.md` | G7 根因更正（§3.3）+ 记录修复；§8 命令速查若涉及一并同步 |
| `docs/commands.md` | 「cron 自动提交推送」行补 pathspec 语义；补新脚本的用法与判据 |
| `docs/pitfalls.md` | 新增一条「`git add <白名单>` + `git commit` ≠ 范围白名单」（含 §2.2 的实测证据） |
| `AGENTS.md` | 「自动提交范围白名单」段补一句：**commit 必须带 pathspec**，否则 index 里的其它 staged 改动会被带走 |

**不动**：三个入口（`daily_report.py` / `snapshot_report.py` / `opening_analyzer.py`）的调用点
（`auto_commit_push` 签名与位置参数全不变）；`_DATA_PATHS` 的**取值**；`AUTO_PUSH` 门控；失败语义。

---

## 5. 实施步骤（每步可独立验证）

### Step 1 — 先写"会红"的行为用例（红→绿）

在 `tests/test_phase26.py` 加一条用**临时仓库**的行为用例：

```
建临时 git 仓库 → 提交初始文件
→ 制造 staged 的白名单外改动（如 git rm 一个源码文件）
→ 制造白名单内的改动（改 data/xxx 并 add）
→ 调 git_ops._commit(...)
→ 断言：本次 commit 的 --stat 只含 data/ 路径；且 git status 里"源码删除"仍为已暂存
```

**先跑一次：应当是红的**（证明洞真实存在、用例有效），再改实现。

### Step 2 — 改 `src/git_ops.py`

commit 加 `"--", *paths`。重跑 Step 1 ⇒ 应变绿。

### Step 3 — 更新既有断言

`test_add_uses_path_whitelist` 等实参断言同步（新增 `git commit` 的实参断言）。
⚠️ **不要放松**既有断言，只**加**paths 断言。

### Step 4 — 新增仓库内脚本 `scripts/auto_commit_data.py`

薄封装（伪代码）：

```
from src.git_ops import _DATA_PATHS, _has_changes, _commit
root = Path(__file__).resolve().parents[1]
if not _has_changes(root):        print("[data-commit] 改动=无"); exit 0
date = 今天（本地日期，YYYY-MM-DD）
_commit(root, date, "data sync")  # message 与既有格式一致：auto: {date} {type}
print("[data-commit] 改动=有 提交=ok")
```

⚠️ 用**已存在的** `_DATA_PATHS` / `_has_changes` / `_commit`（单一事实来源），
**不要**在新脚本里重写白名单 —— 否则又多一处副本。

### Step 5 — 仓库外 wrapper + 改 cron

```
# D:\hermes\scripts\marketpulse_autopush.sh      ← $HERMES_HOME/scripts，不是 ~/.hermes
cd /d/AGENT/MarketPulse || { echo "[fatal] 仓库目录不存在"; exit 2; }
exec venv/Scripts/python -m scripts.auto_commit_data
```

改 cron（`hermes cron edit 6f6e40a6f8b4`）：设 `script=marketpulse_autopush.sh`、`no_agent=True`，
清空 prompt。**schedule 保持 `*/5` 不变**（数据新鲜度零劣化）。

验证：`hermes cron doctor` 无 issue → `hermes cron run 6f6e40a6f8b4` → `cron runs` 显示 completed。

### Step 6 — 文档更正

按 §4 改 4 份文档，重点是 G7 的根因更正（§3.3）。

---

## 6. 验证命令

```bash
# ① 单测（含新的行为用例）
venv/Scripts/python -m pytest tests/test_phase26.py -v

# ② 全量回归
venv/Scripts/python -m pytest tests/ -q

# ③ 端到端：制造 staged 的白名单外改动，跑新脚本，确认不被带走
#    （在真实仓库操作前先备份；或用临时仓库 + git_ops 单测覆盖）
git rm --cached <某个无关文件>        # 制造 staged 改动（演练后务必恢复）
venv/Scripts/python -m scripts.auto_commit_data
git status --porcelain                 # 期望：那个删除仍显示为已暂存（没被提交）

# ④ cron 侧
hermes cron doctor
hermes cron run 6f6e40a6f8b4 && sleep 70 && hermes cron runs 6f6e40a6f8b4
```

> ⚠️ ③ 若在真实仓库演练，**必须在操作前记录 `git status` 快照**，结束后逐项还原；
> 更稳的做法是让 ③ 由单测（临时仓库）覆盖，真实仓库只跑 ①②④。

---

## 7. 风险评估

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| **R1** | 误以为"改了 cron 就够"，漏掉 `git_ops.py`（三入口仍带洞） | 高 | §3.1 优先于 §3.2；两处必须都改 |
| **R2** | 改 commit 实参破坏既有测试 `test_phase26.py` | 中 | Step 3 显式同步断言；不放松只新增 |
| **R3** | `git commit -- <paths>` 语义与 `git add` 叠加后有意外（如把未暂存的该路径改动也提交） | 中 | 这是**期望行为**（保证 `_has_changes` 与 `_commit` 同口径）；用 Step 1 的用例锁死 |
| **R4** | wrapper 放错目录（`~/.hermes` vs `$HERMES_HOME`） | 中 | §3.2 明确 `D:\hermes\scripts`；今天已踩过一次 |
| **R5** | 改 cron 模式后丢失"失败重试"能力 | 低 | script 模式的退出码可被 Hermes 识别；`scripts/push_retry.sh` 链路不受影响 |
| **R6** | 真实仓库演练时的 staged 改动未还原 | 中 | §6 ③ 的注意项；优先走临时仓库 |
| **R7** | 外部 cron 是**仓库外**配置，本任务只改配置不改进仓库 | 低 | 需 `hermes cron edit`，属运维操作（§3.2 Step 5） |

---

## 8. 预计影响的文件范围

| 类别 | 数量 |
|---|---|
| 主代码 | 1 文件（`src/git_ops.py`，改 1 行 + docstring） |
| 新增脚本 | 1 个（`scripts/auto_commit_data.py`，约 30 行） |
| 测试 | 1 文件（`tests/test_phase26.py`，新增行为用例 + 补断言） |
| 仓库外 | 1 个 wrapper（`D:\hermes\scripts\`）+ 1 条 cron 配置 |
| 文档 | 4 个（`system-overview.md` / `commands.md` / `pitfalls.md` / `AGENTS.md`） |
| **不动** | 三入口调用点、`_DATA_PATHS` 取值、`AUTO_PUSH` 门控、失败语义 |

---

## 9. 明确不做

- ❌ 不改 `_DATA_PATHS` 的取值（`data` / `context` / `alerts` 维持原样）
- ❌ 不改三入口的 `auto_commit_push` 调用点与签名
- ❌ 不动 `reports/` 的排除决策（它被 `.gitignore` 排除，作显式 pathspec 会 fatal）
- ❌ 不改 cron 的 `*/5` 频率（数据新鲜度零劣化是三十四期的既有结论）
- ❌ 不做"自动 detect 并还原别人的 staged 改动"这类自作聪明的事（那是越权）
- ❌ 不修 G4/G5/G6 等无关缺口

---

## 10. 决策裁定（2026-09-20 17:2x，用户已确认「按你的来」= 全采纳推荐项）

| # | 议题 | 裁定 | 落地位置 |
|---|---|---|---|
| **D-1** | 外部 cron 的修法 | ✅ **A：改 script 模式** | Step 4 + Step 5 |
| **D-2** | `git_ops.py` 是否本轮一起修 | ✅ **A：一起修**（影响三入口，优先级高于 cron） | Step 1-3 |
| **D-3** | 是否在 `pitfalls.md` 立通用规则 | ✅ **A：立**（"`git add <白名单>` ≠ 范围白名单"） | Step 6 |

### 10.1 由裁定导出的三条实施硬约束

1. **顺序**：**先 `src/git_ops.py`（Step 1-3）→ 再外部 cron（Step 4-5）**。
   理由：wrapper 要复用修好后的 `_commit`；且三入口的风险面大于 cron。
2. **红→绿**：Step 1 的**行为用例必须先跑成红色**再改实现（证明洞真实存在、用例有效），
   不接受"写完直接绿"——那可能只是用例没测到点上。
3. **不放松既有断言**：`test_phase26.py` 的实参断言只**新增**（`git commit` 的 `-- <paths>`），
   不修改既有断言的语义。

### 10.2 实施后必须验证的两件事（缺一不可）

1. **本地**：`pytest tests/test_phase26.py -v` + `pytest tests/ -q`（无新增失败）
2. **外部 cron**：`hermes cron doctor` 无 issue → `hermes cron run 6f6e40a6f8b4` → `cron runs` 显示 completed
   ⚠️ wrapper 必须放 **`D:\hermes\scripts\`**（`$HERMES_HOME/scripts`），**不是** `~/.hermes/scripts`

---

## 11. 一句话

**我之前的根因判断错了，得先认这个**：cron 没有越界，它也禁止了 `git add -A`。
真正的洞是 **`git commit` 不带 pathspec = 提交整个暂存区** —— 这个洞在 `src/git_ops.py` 里也存在，
而且影响着每天都在跑的三个报告入口。
