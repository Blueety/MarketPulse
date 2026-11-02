# journal — 自动提交的暂存区泄漏（pathspec 隔离）

- **任务档**：`tasks/2026-09-20-autopush-pathspec-fix/`（`plan.md` 定稿；§10 三项已裁定 D-1=A / D-2=A / D-3=A）
- **执行日期**：2026-09-20 17:2x–18:1x（本机直连）
- **角色**：Phase 3 Step 3.6 执行者（按 plan 实施 + 验证）

## 1. 目标

让"自动提交"**只可能提交白名单路径**，无论暂存区里还有什么。真根因见 plan §3.4：
**`git commit` 不带 pathspec 时提交的是整个暂存区（index）**，范围只写在 `git add` 上不够 ——
`add` 是加法，无法排除 index 里已有的内容。

## 2. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/git_ops.py` | `_commit` 的 commit 加 `"--", *paths`（1 行）+ docstring 详述"为什么 commit 也要 pathspec"与另一半语义 |
| `tests/test_phase26.py` | ① **真临时仓库**行为用例 2 条（唯一一处真 git，文件头已注明例外）；② `test_commit_uses_pathspec` 实参断言（只新增，既有断言零改动） |
| `scripts/auto_commit_data.py` | **新增**：薄封装，复用 `git_ops._has_changes` / `auto_commit_push`（白名单单一事实来源） |
| `D:\hermes\scripts\marketpulse_autopush.py` | **新增（仓库外）**：cron 的 `.py` 包装器（**不是 `.sh`**，原因见 §4.1） |
| `docs/system-overview.md` | G7 行**整行更正**（真根因 + 两处修复 + 护栏；此前把根因写成"prompt 模式不可靠"不准确） |
| `docs/commands.md` | 「cron 自动提交推送」行补 pathspec 语义；新增「仓库外数据同步 cron」一行 |
| `docs/pitfalls.md` | 新增「通用（git 提交范围 = 暂存区…）」两条：pathspec 坑 + **Hermes script 模式 `.py` vs `.sh`** |
| `AGENTS.md` | 「自动提交范围白名单」段补：**commit 必须带 pathspec** + cron 已改 script 模式 |
| `docs/architecture.md` / `docs/frontend-structure.md` | **顺带修正 2 处既有的表格破损**（见 §4.4，非本任务引入） |

**不动**：三入口调用点与签名、`_DATA_PATHS` 取值、`AUTO_PUSH` 门控、失败语义。

## 3. 验证结果

### 3.1 Step 1 红跑（先证明洞真实存在）
```
FAILED tests/test_phase26.py::test_commit_pathspec_isolates_unrelated_staged_changes
  AssertionError: 提交内容应只含白名单内的路径，实际 ['data/d.txt', 'srcfile.py']
  捕获的 git 输出： [main aa8a0d7] auto: 2026-09-20 data sync
                   2 files changed, 1 insertion(+), 2 deletions(-)
                   delete mode 100644 srcfile.py      <== 白名单外的已暂存删除被带走
```
⇒ **事故原样复现**（`git rm` 直接进 index，无需 `git add`）。

### 3.2 修后绿
`pytest tests/test_phase26.py -q` → **1 failed / 18 passed（修前） → 20 passed（修后）**。
全量 `pytest tests/ -q` → **742 passed / 1 failed**（唯一红是既有 `test_us_sector::test_volume_format`，与本轮无关）。

### 3.3 真实仓库的安全 E2E（负例，不伪造 data 改动）
`git add docs/_pathspec_probe.md`（白名单外）→ 跑 `python -m scripts.auto_commit_data`
→ 打印 `[data-commit] 改动=无，跳过（幂等）`、**HEAD 未变**、那个 staged 文件**仍在**；
随后 unstage + 删除，逐项还原 ✔

### 3.4 外部 cron
- `hermes cron edit 6f6e40a6f8b4 --script marketpulse_autopush.py --no-agent --prompt ""`
  ⇒ `no_agent=True` / `script=marketpulse_autopush.py` / prompt 长度 0（已清空）/ **schedule 仍 `*/5`** ✔
- `hermes cron doctor` → **✓ no issues**（9 active jobs）✔
- **定时（builtin）实跑两轮均 `completed`**：`18:05:53`、`18:10:53`，输出文件内容为
  `Mode: no_agent (script)` + `[data-commit] 改动=无，跳过（幂等）` ✔

## 4. 遇到的问题与处置

### 4.1 🔴 `.sh` 包装器在 builtin 路径下跑不通 → 改用 `.py`（本轮最大的坑）
按 plan 先写了 `marketpulse_autopush.sh`（`cd` + `exec venv/Scripts/python -m scripts.auto_commit_data`）：
- **手动 `bash <脚本>` 成功**；**`hermes cron run`（direct）成功**；
- 但 **ticker（builtin，`*/5`）每轮稳定失败**：`Script exited with code 1` +
  **11 个非 ASCII 字节的 stderr**（`hermes` 以 UTF-8+replace 解码，字节被吃成 `?`）。

排除过程（都做了，不是猜）：
1. 复现"PATH 里没有 git"⇒ 得到完全一致的签名（exit 1、stdout 空、stderr 尾行
   `FileNotFoundError: [WinError 2] 系统找不到指定的文件。` = **11 个字符**）—— 与那 11 个 `?` 精确对上；
2. 但调 Hermes 的 `build_subprocess_env()` 实测 **git 在 PATH 上**（`which('git')` 命中 PortableGit）
   —— 注意：那用的是**我进程**的 env，ticker 进程的 env 无从直接测量；
3. 全机搜 `marketpulse_autopush.sh` ⇒ **只有一份**（我写的），`~/.hermes/scripts` 与
   `%LOCALAPPDATA%\hermes` 都没有副本；
4. **判别实验**：把包装器换成 `echo PROBE-77; exit 7`（并把诊断写在第一条语句、`cd` 之前）
   ⇒ 下一轮 builtin **仍报 exit 1、探针日志也没落盘** ⇒ **builtin 根本没在执行这份文件**
   （即 builtin 路径下 bash 的执行环境与 direct 不同，`shutil.which("bash")` 在 ticker 进程里
   解析到的可能不是同一个）。

**处置**：改用 **`.py` 包装器**（Hermes 对 `.py` 走 `_windows_cron_python_invocation`，
绕开 bash 分支）——同目录既有 `marketpulse_daily.py` 长期正常运行即为先例。切换后**两轮定时运行立即 completed** ✔
（`.sh` 已删除，避免与 `.py` 并存产生歧义。）

> ⚠️ 教训已写进 `docs/pitfalls.md`：**Hermes script 模式必须等一轮真实定时运行才算验证通过；
> 只验 `hermes cron run` 会漏**（direct 成功 ≠ builtin 成功）。排查要看
> `D:\hermes\cron\output\<job>\<时间>.md` 与 `.../cron/executions.db`。

### 4.2 一处对 plan 伪代码的有意偏离（需复核）
plan §5 Step 4 的伪代码只调 `_commit`（**不 push**）。但该 cron 的存在意义就是"把数据推到 Railway"
（原 prompt 里有 `git push origin master`）⇒ **只提交不推送是功能回退**。
故 `scripts/auto_commit_data.py` 改用 `git_ops.auto_commit_push()`（commit + push 一次覆盖，
自带 Clash 代理注入 / gh 凭据助手兜底 / `GIT_TERMINAL_PROMPT=0` 防挂死）。
退出码语义：0 = 成功（含"无改动跳过"）；1 = 提交或推送失败。**请求复核这一处。**

### 4.3 G7 根因更正的落地细节
G7 是**单行超长 markdown 表格行**（789 字符），逐字符 Edit 不现实 ⇒ 用一次性脚本按行首
`| **G7** |` 定位整行替换（脚本由编辑器工具落盘，不经 shell，规避转义传递坑）；替换后自检
**竖线数 = 5**（4 列表）✔。新行 1084 字符，含真根因 + 两处修复 + 护栏 + 任务档指针。

### 4.4 顺带修正 2 处**既有**表格破损（并发现我自己昨天引入的一处）
写文档时做了一次全量表格结构自检（"行内未转义竖线 ≥8"），抓到 3 处：
1. `docs/architecture.md:78` —— `|r|>0.5`（相关性绝对值）出现 2 次 ⇒ 表格被撑坏（十二期既有）；
2. `docs/frontend-structure.md:150` —— `forward{"1"|"3"|"5"|"10"}` ⇒ 同上；
3. 🔴 `docs/system-overview.md` 的 **G9 行**（**我昨天在鉴权任务里写的**）——
   单元格里写了 `grep \`auth|login|token|password|API_KEY|Secret\`` 这个**含 5 个裸竖线**的模式
   ⇒ G9 行有 10 个竖线，表格从那一行起错乱。**已全部转义修正**，复检 0 可疑行。
   > 这条自检脚本落 `%TEMP%`（未入库）；**建议将来把它变成仓内的一条 doc-lint**（见 §7）。

### 4.5 与我并发的另一会话
执行期间仓库里有**另一个会话在提交**（`c7cbc21 chore(security): finish wecom removal…`、
`2cbd180 docs: sync wecom removal and record the cron overreach (G7 relapse)`），
且 `hermes cron` 也被改过。故本轮的 commit 范围要按**本轮自己改的文件**显式指定，
不要 `git add -A`（否则会把别人的在途改动一起带上——这正是本任务在修的同一类问题）。

## 5. 下次注意什么

1. **任何"限定提交范围"的实现，都要检查"提交侧有没有 pathspec"** —— 只收窄 `add`/`status` 是不够的。
2. **Hermes script 模式优先 `.py`**；非要用 `.sh`，`hermes cron run` **和**一轮真实定时跑各验一次。
3. **排查 cron 失败的三个取证点**：`hermes cron runs <id>`（状态 + 首行 stderr）、
   `D:\hermes\cron\output\<id>\<时间>.md`（脚本 stdout/stderr 原文）、
   `D:\hermes\cron\executions.db`（`status` / `error`）。
4. 改超长 markdown 表格行用脚本按行首定位整行替换，改完**自检竖线数**。
5. 并发会话存在时，提交必须按"自己改的文件"显式 `git add`。

## 6. 明确未做（与 plan §9 对照）

- ❌ 未改 `_DATA_PATHS` 取值；❌ 未改三入口调用点/签名；❌ 未动 `reports/` 的排除决策
- ❌ 未改 cron 的 `*/5` 频率（数据新鲜度零劣化）
- ❌ 未做"自动 detect 并还原别人的 staged 改动"（越权）
- ❌ 未修 G4/G5/G6 等无关缺口

## 7. 后续建议（不属本轮范围）

1. **把"markdown 表格结构自检"做成仓内一条断言**（本轮抓到 3 处真破损，其中一处是我自己引入的）
   —— 判据简单（表格行内未转义竖线数应等于表头列数），很适合放进 `tests/` 或验收脚本。
2. `tests/test_us_sector.py::test_volume_format` 仍是既有红（`$12.0亿` vs 期望 `$1.2B`）。
3. 企业微信旧凭据吊销仍未完成（用户侧操作），见 `tasks/2026-09-20-wecom-cred-revoke/journal.md` §7。

## 4.6 ⭐ 生产环境的真实闭环验收（2026-09-20 18:15:54 定时运行）

任务报告后，cron 的**下一轮定时运行**恰好走了完整链路，构成最强的验收证据：

```
$ hermes cron runs 6f6e40a6f8b4
37ff36a823c549de85df3be890458acc  completed  2026-09-20T18:15:54  source=builtin
输出： [data-commit] 改动=有，提交并推送=ok
       To https://github.com/Blueety/MarketPulse.git
         2cbd180..57315d0  master -> master
```

而**同一时刻工作区里躺着 8 个未提交的源码/文档改动**（`src/git_ops.py`、`tests/test_phase26.py`、
6 份文档、`AGENTS.md`）—— 即 16:35 事故的**同一场景**。核对结果：

| 检查 | 结果 |
|---|---|
| 该提交的内容 | `57315d0 auto: 2026-09-20 data sync`，**只有 `data/news.json` 一个文件** ✔ |
| 白名单外的路径是否混入 | **0 个**（`git show --name-only` 过滤 `^(data\|context\|alerts)/` 后无剩项）✔ |
| 我那 8 个在飞的改动 | **全部仍在工作区未提交** ✔ |

⇒ **验收标准 #1 在生产环境真实达成**（不只是单测里构造的场景）：
"index/工作区里有白名单外的改动时，自动提交只产生白名单内的提交"。
修前该提交会把那 8 个文件一起带走（正是 `6ec1562` 的形态）。
另附：`scripts/auto_commit_data.py` 的 **commit+push 正向路径**也因此得到端到端验证
（§3.3/§3.4 当时只覆盖了"无改动"分支）。

---

## 7. 架构师复核（2026-09-20 20:5x，plan 作者）

### §4.2 的偏离 —— ✅ **批准，且定性为 plan 缺陷而非执行者越权**

plan §5 Step 4 的伪代码只调 `_commit`（不 push）是我写漏了：`scripts/auto_commit_data.py`
替代的是**原 prompt 的完整流程**（add + commit + **push**），只 commit 不 push 是功能回退。
执行者的修正（改用 `git_ops.auto_commit_push()`）比我原稿更好——它自带
`AUTO_PUSH` 门控 / Clash 代理注入 / gh 凭据助手兜底 / `GIT_TERMINAL_PROMPT=0` 防挂死，
且**正向路径已获生产级 E2E 验证**（`57315d0` 推送成功，见本 journal 尾部）。
退出码语义（0=成功含跳过 / 1=失败）合理。**无需回改。**

### §4.1 的教训—— 已同步进 `skills/hermes-cron-script/SKILL.md`

「direct 成功 ≠ builtin 成功，必须等一轮真实定时运行」这条比我原 skill 里写的
"`hermes cron run` 实跑验证"**更强**，已更新该 skill（原判据不足）。

### 验收状态

P0-4 **闭环**。三处修复点（`git_ops` pathspec / `auto_commit_data.py` / cron script 化）
全部落地且获生产环境验证。
