# 实施计划：自动提交范围收窄（路径白名单 + 提交链拆分）

> **需求来源**：2026-09-14 会话讨论（本任务无 `prd.md`，Goal 取自该讨论的结论）
> **产出**：架构师只读分析后出具；**未改动任何项目文件**
> **状态**：**Step 0 有两项阻塞前置**（见 §4.1），确认前不进入执行
> **本文性质**：方案文档，不含完整可运行代码

---

## 1. 任务目标

**Goal（源自 2026-09-14 会话）**：
> 调整 cron 自动代码提交的时机与行为，使其不影响开发（不吞掉半成品、不让 `git status` 失真）。

**经分析后的目标修正** —— 原始诉求是"改时间"，但实测表明**时间不是根因**：

- 数据是 24 小时流动的（A 股 09:30–15:00 / 美股 21:30–04:00 北京时间），**不存在"完全安静的时段"**；
- 真正的根因是 **`git add -A` 全量扫描工作区** —— 只要触发瞬间有半成品，它就会入库。

**因此目标重定义为两条**：

| # | 目标 | 度量 |
|---|---|---|
| G1 | 任何 cron 都不得把**源码/测试/文档的半成品**提交入库 | 造一个源码 WIP 后跑提交，`git log --stat` 不含该文件 |
| G2 | 数据同步（Railway）的新鲜度**不劣化** | 数据提交时点仍覆盖 08:01 / 09:45 / 11:45 / 14:40–15:15 / 21:46 / 00:01 |

---

## 2. 结论先行与方案选型

**选定：以 B（路径白名单）为主，A（降频）为辅。**

**相对会话初版建议的一处关键修正**：初版把"降频"当作必需项，实测后确认**危险的是"提交"，不是"抓取"**。若「每日数据更新」的 5 分钟高频里包含"抓取数据（重写 `data/news.json` / `data/watchlist.json`）"与"提交"两件事，则只需把 **commit 收窄到数据路径**，**高频抓取可原样保留** —— 不必为了安全牺牲数据新鲜度。故 A 从"必需"降级为"降噪可选"。

| 方案 | 决策 | 理由 |
|---|---|---|
| **B 路径白名单** | **采纳（主）** | 根治 G1：源码 WIP 永不被任何 cron 扫走；改动面小（`src/git_ops.py` 三处 + 测试新增）；**既有 11 条断言全部仍通过**（§4.5） |
| **A 降频** | **采纳（辅，可选）** | 白名单落地后 5 分钟频率已无害；A 的剩余价值仅为"减缓仓库膨胀（`data/watchlist.json` 1938 行/次）+ 减少噪声提交（242/400）" |
| C 清洁度门（见到源码改动就跳过本次提交） | **不采纳** | 分不清"写完待提交"与"写了一半" → 会让数据同步被无限推迟（假让路） |
| D 锁文件（写码前 `touch .devlock`） | **不采纳** | 纪律型方案；本项目 `pitfalls.md` 已记录同类方案失效（Agent 会忘） |
| 只保留深夜单一时点 | **不采纳** | 与 G2 冲突：Railway 白天将拿不到当天 A 股数据 |
| 把「每日数据更新」整条停掉 | **不采纳** | 它当前实际承担"兜底提交数据 + 兜底提交 Agent 产出"两职；直接停会让 `docs/pitfalls.md`、`tasks/*/journal.md` 不再入库（见 Step 0.2） |

---

## 3. 基线实测（本方案的事实依据）

以下均为**本仓库实测**，非推测。

### 3.1 提交时点分布

| 项 | 实测值 |
|---|---|
| 最近 400 次提交中 `auto: 每日数据更新` | **242+ 次**（主导噪声） |
| 其触发间隔 | **≈5 分钟**（`22:45:13` / `22:50:13` / `22:55:13`，秒级对齐） |
| 09-14 单日 18:40–22:55 | **36 次提交 / 4.25 小时** |
| 峰值小时（近 400 次） | 22 点 38 · 23 点 35 · 00 点 33 · 12 点 30 |
| 仓库内 `src/git_ops.py` 提交时点 | 固定 **08:01 / 09:45 / 11:45 / 14:40 / 15:15 / 21:46 / 00:01** |

### 3.2 「每日数据更新」的实际提交内容（抽查 5 次）

```text
1103cb2 22:01  web/static/macro.js · web/templates/macro.html · web/static/style.css
1f67d01 14:20  snapshot_report.py · src/reporter.py
d7136d4 22:50  tests/conftest.py · context/2026-09-14.json · data/watchlist.json(1938行)
fd40677 22:55  docs/pitfalls.md · tasks/2026-09-14-.../verify_ui.py · journal.md
b56a590 12:56  data/backup/history_2026-09.json · docs/pitfalls.md · tasks/*/journal.md
```

**`web/` `src/` `tests/` `docs/pitfalls.md` `tasks/*/journal.md` —— 这些只可能是正在被写的文件。**

### 3.3 白名单可行性（已用 `git check-ignore -v` + `git add --dry-run` 验证）

| 路径 | 是否被 `.gitignore` 排除 | tracked 文件数 | 可否进白名单 |
|---|---|---|---|
| `data/` | 否（仅内部 `marketpulse.db*` 等被排除） | 19 | **可** |
| `context/` | 否 | 16 | **可** |
| `alerts/` | 否 | 3 | **可** |
| `reports/` | **是**（`.gitignore:40`） | 0 | **不可** |

- `git check-ignore -v reports context alerts data` → 仅 `reports` 命中 `.gitignore:40`
- `git add --dry-run data/ context/ alerts/` → `exit=0`，三个路径全部被接受

> **关键坑**：`.gitignore` 中被排除的路径**不能**作为 `git add` 的显式 pathspec（会直接报 `The following paths are ignored…`）。因此白名单**必须排除 `reports/`** —— 它的产物本来就不入库（tracked=0），当前 `git add -A` 也是跳过它的，收窄后行为不变。

---

## 4. 实现步骤

### 4.1 Step 0 · 前置确认（阻塞门，未确认不得动代码）

| # | 待确认 | 为什么影响选型 | 未确认时的默认假设 |
|---|---|---|---|
| **0.1** | 「每日数据更新」cron 的**实际命令**与职责：它是否同时承担"抓取数据（重写 `data/news.json` / `data/watchlist.json`）"与"提交"？ | 若含抓取 → commit 只能收窄、频率保留；若纯提交 → 可整体降频甚至停用 | 假设为"抓取 + 提交"（与 §3.2 证据一致），按"收窄不降频"设计 |
| **0.2** | 该 cron 是否**有意**用来兜底提交 Agent 产出（`docs/pitfalls.md` / `tasks/*/journal.md`）？ | 若"是" → 必须额外保留一条**全量**提交链（否则 Agent 产出不再入库）；若"否" → 可彻底禁用它提交源码 | 假设为"是"（§3.2 证据显示它确实在提交这些文件），按 §4.6 保留代码链 |

> `hermes` CLI 可用（`scripts/push_retry.sh:19` 有 `hermes cron rm "MarketPulse推送重试"` 的用例；`docs/architecture.md` 记录过 `hermes cron edit 4337889a4cc3`）。确认命令：`hermes cron ls` → `hermes cron show <id>`。

**本步骤只读，不改任何配置。**

---

### 4.2 Step 1 · `src/git_ops.py` 新增白名单常量 + 路径限定的改动判定

**改点**：新增模块常量与改造 `_has_changes`。

```text
# 伪代码
_DATA_PATHS = ("data", "context", "alerts")   # reports/ 有意排除（被 .gitignore:40 排除）

def _has_changes(root, paths=_DATA_PATHS) -> bool:
    """目标路径存在未提交变更（git status --porcelain -- <paths> 非空）。"""
    cmd = ["git", "status", "--porcelain", "--", *paths]
    ...  # 其余不变（capture_output/text/timeout=_STATUS_TIMEOUT）
    return bool(result.stdout.strip())
```

**为什么 `_has_changes` 也必须限定路径（这是本方案最容易写错的一处）**：

若只收窄 `git add` 而不收窄 `_has_changes`，则当**只有源码 WIP**时：`status --porcelain`（全量）非空 → 判定"有改动" → `git add data context alerts` 无内容可暂存 → `git commit` 因"nothing to commit"报错 → `CalledProcessError` → 函数返回 `False`。

后果不是崩溃（异常被捕获），而是：**日志出现误导性的 `[auto-push] Failed`**，且返回值语义从"数据没变"错标成"提交失败"。限定路径后语义恢复准确：`False` ⇔ 目标路径无变更。

**验证**：`venv/Scripts/python -c "from src import git_ops; print(git_ops._has_changes(__import__('pathlib').Path('.')))"` → 工作区 clean 时应为 `False`。

---

### 4.3 Step 2 · `_commit` 收窄为白名单 add

```text
# 伪代码
def _commit(root, date_str, report_type, paths=_DATA_PATHS):
    msg = f"auto: {date_str} {report_type}"
    subprocess.run(["git", "add", *paths], cwd=root, check=True, timeout=_COMMIT_TIMEOUT)
    subprocess.run(["git", "commit", "-m", msg], cwd=root, check=True, timeout=_COMMIT_TIMEOUT)
```

- **禁止** `-A` / `--all` / `.` —— 需由测试钉死（§4.5 测试 1）
- `auto_commit_push(date_str, report_type, root=PROJECT_ROOT)` **签名保持不变** → `daily_report.py:263` / `snapshot_report.py:98` / `opening_analyzer.py` 三处调用点**零改动**
- `AUTO_PUSH` 门控、代理注入（仅子进程 env 副本）、三级 timeout（15/30/120s）、失败不抛异常、退出码恒 0 —— **全部不变**

**验证**：临时仓库真 git 冒烟（§5.3）。

---

### 4.4 Step 3 · 统一提交入口（推荐，消除"两处定义漂移"）

**动机**：Step 0.1 若确认 Hermes cron 自己写了 git 命令，那么"提交范围"会同时存在于**仓库代码**与**仓库外配置**两处 —— 这正是本项目反复踩的漂移坑（`pitfalls.md`："改任一侧必须同步另一侧"）。正确做法是让 Hermes 侧**不再自己写 git 命令**，改为调用仓库内唯一入口。

```text
# 伪代码：src/git_ops.py 末尾新增 CLI
if __name__ == "__main__":
    # argparse: --type（默认 "data refresh"）、--date（默认今天，可用 analyzer.get_us_eastern_date 或直接 date.today()）
    # 直接调用 auto_commit_push(date, type)
    # 退出码恒 0（与既有纪律一致）
```

Hermes cron 命令随之变为：

```bash
cd /d D:/AGENT/MarketPulse && venv/Scripts/python -m src.git_ops --type "data refresh"
```

**替代方案（不推荐）**：让 Hermes cron 直接写 `git add data context alerts && git commit … && git push …`。缺点是提交范围两处定义、必然漂移。

**注意**：本步骤使 `git_ops` 从"纯库"变为"库 + CLI"。它是**可选**的（Step 1+2 已能达成 G1），但若执行 Step 5 时发现 Hermes 侧确实自带 git 命令，则本步骤**强烈建议执行**。

---

### 4.5 Step 4 · 测试（新增护栏，而非修改既有断言）

**关键性质：既有 `tests/test_phase26.py` 的 11 条断言全部仍然通过，无需改动。** 原因：

- `_has_call(calls, sub)` 判据是 `c["args"][1:2] == [sub]` → 对 `["git","add","data","context","alerts"]` 仍成立；
- `fake_git` 对**任意** `git status` 调用都返回同一个 `status_stdout` → 路径限定不影响桩；
- commit message 格式、代理注入、失败路径断言与 add 范围正交。

> 这符合项目纪律：**不得"删断言/放松断言让它变绿"**。本步是**新增**，不是修改。

**新增 5 条**（追加到 `tests/test_phase26.py`）：

| # | 测试名 | 断言 | 防的是什么 |
|---|---|---|---|
| 1 | `test_add_uses_path_whitelist` | add 调用参数 `== ["git","add","data","context","alerts"]`；**全部调用中不存在 `-A`/`--all`/`.`** | 回归到全量 add（本方案的核心护栏） |
| 2 | `test_status_limited_to_paths` | status 调用参数含 `"--"` 且其后 `== ["data","context","alerts"]` | `_has_changes` 未限定路径（§4.2 的语义错标陷阱） |
| 3 | `test_source_wip_does_not_trigger_commit` | `status_stdout` 含 ` M web/static/app.js` 但**路径限定时为空** → 返回 `False`、**零 commit/push** | **G1 的核心行为断言**（源码 WIP 不再触发提交） |
| 4 | `test_reports_not_in_whitelist` | `"reports" not in git_ops._DATA_PATHS` | 防回归加回 `reports`（`.gitignore:40` 排除它，加进去会让 `git add` 直接报错） |
| 5 | `test_ignored_only_change_skips` | 仅 `data/marketpulse.db` 类被忽略文件变化 → status 空 → 跳过 | 被忽略文件不应触发提交 |

**测试 3 的桩写法**（要点：让 `git status -- <paths>` 与全量 status 返回不同结果）：
需在 `fake_git` 中按 `args` 是否含 `"--"` 分流返回，**或在测试内局部覆写** `state["status_stdout"]`。**不要**为了这条测试改动 11 条既有用例。

---

### 4.6 Step 5 · Hermes 侧 cron 调整（仓库外配置，需用户执行）

**5a. 数据提交链**（视 Step 0.1 结论二选一）：

- 若含抓取 → **只改提交命令为白名单/统一入口**（§4.4），频率**保持 `*/5` 不变**（G2 不劣化）
- 若纯提交 → 改为每天 **6 个时点**，各紧跟业务入口 5–15 分钟做兜底重试：

| 北京时间 | 紧跟 |
|---|---|
| 08:10 | daily report（08:01） |
| 09:50 | A 股开盘快照 + opening analysis（09:45） |
| 11:50 | A 股午盘快照（11:45） |
| 15:20 | A 股收盘快照（14:40 / 15:15） |
| 22:00 | 美股开盘快照（21:46） |
| 00:15 | 美股午盘快照（00:01） |

**5b. 代码/文档提交链**（仅当 Step 0.2 = "是" 时保留）：

保留一条**全量**提交 cron，但**降频到最低**。推荐**首选项**是**改为任务收尾由 Agent 显式提交**（本会话即构成授权），因为"入库 Agent 产出"本质是**事件触发**（一份工作写完）而非**频率触发**；频率型方案必然在某个"写了一半"的瞬间撞上。

若保留兜底，建议：**每天 1 次，08:30**（日线定稿之后、Agent 会话高峰 18:00–23:00 之外）。**明确标注为"接受残余半成品风险"**。

---

### 4.7 Step 6 · 文档回填

| 文件 | 动作 | 纪律 |
|---|---|---|
| `docs/architecture.md` | **新增一行决策**（自动提交范围收窄） | ⚠️ **append-only**：第 26 期那行明确写着"`git add -A` 全量语义"，是已定稿决策。**必须保留旧行、追加新行**，严禁"旧文→新文"整体替换（`pitfalls.md` 明令，曾被覆盖过一次） |
| `docs/system-overview.md` | §6 关键决策表"cron 自动提交"行补范围说明；§9 缺口表视情况新增"代码提交链残余风险" | 本文是现状快照，需与代码一致 |
| `docs/pitfalls.md` | 追加本任务坑位：`_has_changes` 必须与 `add` **同范围**（否则日志/返回值语义错标）；`.gitignore` 排除的路径不能进 add 白名单 | 只写可复用规则，不写泛化建议 |
| `AGENTS.md` | 新增规则：**提交范围白名单**（哪些路径可自动提交）+ 若采纳 Agent 显式提交则写清收尾动作 | 复用规则而非泛化建议 |
| `docs/commands.md` | 「何时跑什么」表补"改了 `src/git_ops.py` 后"一行 | — |

---

## 5. 验证命令

> 全部来自 `docs/commands.md`；所有命令在 venv 内执行。**验证一律串行**（`pitfalls.md`：并行跑 pytest 与 Playwright 会互相制造假失败）。

### 5.1 单元测试

```bash
venv/Scripts/python -m pytest tests/test_phase26.py -v     # 11 条既有（应全绿，零改动）+ 5 条新增
venv/Scripts/python -m pytest tests/ -v                    # 全量回归（27 个测试文件）
```

### 5.2 静态自检（零副作用）

```bash
git check-ignore -v reports context alerts data            # 仅 reports 命中 .gitignore:40
git add --dry-run data/ context/ alerts/                   # exit=0，路径被接受
git status --porcelain -- data context alerts              # 与 git_ops._has_changes 同口径
```

### 5.3 真实 git 冒烟（**在临时仓库做，不在本仓库**）

**动机**：G1 的验收必须用**真实 git** 证明"源码 WIP 不被提交"，桩测试只能证明参数正确。

```text
步骤：
1. 建临时目录，git init，建 data/ context/ alerts/ web/static/ 目录
2. 写入 data/a.json（应被提交）+ web/static/app.js（不应被提交）
3. git add . && git commit -m init        # 建立基线
4. 修改两个文件（都留未提交改动）
5. 调用 git_ops.auto_commit_push("<date>", "whitelist smoke", root=<tmp>)
   - 无 remote → push 失败、函数返回 False（符合既有纪律：失败不抛异常）
   - 但 commit 已落盘 ← 这正是要验证的
6. git -C <tmp> show --stat HEAD          # 断言：只含 data/a.json，不含 web/static/app.js
7. git -C <tmp> status --porcelain        # 断言：app.js 仍为未提交状态
```

**为什么不在本仓库真跑**：
- 会 push → 触发 Railway 重部署（`docs/commands.md` 明令"真跑验证限一次"）
- 会与 Hermes「每日数据更新」cron **抢提交**（`pitfalls.md` 记录过多次竞态）
- 若验证失败，本仓库工作区已被污染

### 5.4 G1 端到端验收（本仓库，**只读式**）

```text
1. 造一个源码 WIP：在 web/static/app.js 末尾追加一行注释
2. 执行一次数据入口（AUTO_PUSH 保持默认开启），或直接经统一入口触发一次提交
3. 断言：
   git status --porcelain -- web/static/app.js   → 仍为 " M"（未被提交）
   git log -1 --stat                             → 不含 app.js
4. 恢复：git checkout -- web/static/app.js   ← 必须恢复（pitfalls：验证期模拟改动后必须恢复）
5. 用 git log --oneline -3 核对提交是否发生、message 是否符合 `auto: {date} {type}`
```

### 5.5 未运行的检查必须标注

- ❌ **未做**：真实 push 到 origin 的验证（触发 Railway 重部署 + 抢提交风险）→ 由下一次 Hermes cron **自然发生**时观察 `git log` 确认
- ❌ **未做**：Hermes cron 配置变更的行为验证（仓库外配置，我无法读取）→ **Step 0 + Step 5 依赖用户执行**

---

## 6. 风险评估与注意事项

| # | 风险 | 级别 | 说明与缓解 |
|---|---|---|---|
| R1 | **`_has_changes` 与 `add` 不同范围** | **高** | 只改 add 不改 status → 源码 WIP 时日志报 `Failed`、返回值语义错标。§4.2 已含；测试 2/3 钉死 |
| R2 | **`reports/` 误入白名单** | **高** | 被 `.gitignore:40` 排除 → `git add reports` 直接抛 `CalledProcessError` → **三入口的数据提交全部失败**（且只打一行 `Failed`，极易漏看）。测试 4 钉死 |
| R3 | **仓库外配置与仓库代码漂移** | **中** | Hermes 侧若自带 `git add -A`，仓库内改了也不生效。缓解：§4.4 统一入口（让范围只有一处定义）；Step 0.1 先确认 |
| R4 | **Agent 产出不再入库** | **中** | 若 Step 0.2 = "是" 而无兜底链，`docs/pitfalls.md` / `tasks/*/journal.md` 会积压在工作区。缓解：§4.6 5b（收尾显式提交 或 08:30 全量兜底） |
| R5 | **`architecture.md` 决策行被覆盖** | **中** | 第 26 期那行是已定稿的"`git add -A` 全量语义"。编辑必须 append-only；`pitfalls.md` 明令并记录过覆盖事故 |
| R6 | **Hermes cron 高频抓取若被一并降频** | **中** | 会把"数据新鲜度"降级为"每天 6 次"，`data/news.json` / `data/watchlist.json` 刷新率同步下降。缓解：§2 已明确"只收窄提交、保留抓取频率" |
| R7 | **兜底全量 cron 的残余半成品风险** | **低–中** | 08:30 全量提交仍可能撞上半成品。**明确标注为接受风险**；首选改为 Agent 收尾显式提交 |
| R8 | **`git status --porcelain -- <paths>` 的 git 版本兼容** | **低** | 该写法自 git 1.7 起支持；本机已验证 `git add --dry-run` exit=0。建议在计划中确认 `git --version` |
| R9 | **本仓库真跑验证污染工作区** | **低** | §5.3 已改为临时仓库冒烟；§5.4 有恢复步骤 |

### 范围外发现（记录，不在本任务处理）

- `scripts/push_retry.sh:14` 内联硬编码企业微信 `bot_id`（`aibQlFgEwim7Ma40C3ZWee47Mbrpgg6uDCT`）。与 `docs/system-overview.md` §9 **G1**（`wecom_*` 硬编码凭据）同属一类问题，**本次不动**，建议并入 G1 一并处置（改走 `.env` + 已泄露凭据需在后端重置）。

---

## 7. 影响文件范围

| 类型 | 文件 | 改动量（估） |
|---|---|---|
| 修改 | `src/git_ops.py` | +15 ~ +35 行（常量 + `_has_changes` 路径限定 + `_commit` 收窄；§4.4 可选 CLI +~20 行） |
| 修改 | `tests/test_phase26.py` | +5 条测试，~80 行；**既有 11 条零改动** |
| 修改 | `docs/architecture.md` | +1 决策行（append-only） |
| 修改 | `docs/system-overview.md` | §6 1 行 + §9 视情况 1 行 |
| 修改 | `docs/pitfalls.md` | +2 条坑位 |
| 修改 | `AGENTS.md` | +1~2 条规则 |
| 修改 | `docs/commands.md` | 「何时跑什么」+1 行 |
| **仓库外** | Hermes「每日数据更新」cron 命令/时点 | 需用户执行（§4.6 / §5b） |
| 新增 | `tasks/2026-09-14-autopush-scope/plan.md` | 本文件 |
| 新增 | `tasks/2026-09-14-autopush-scope/journal.md` | 执行者收尾填写 |
| 删除 | 无 | — |

**`daily_report.py` / `snapshot_report.py` / `opening_analyzer.py` 零改动**（签名不变）。

---

## 8. 不做什么

- **不改**三个入口的业务时点（08:01 / 09:45 / 11:45 / 14:40–15:15 / 21:46 / 00:01）—— 与数据新鲜度绑定
- **不改** `AUTO_PUSH` 门控语义、代理注入方式、timeout、失败→返回 False 的既有纪律
- **不改** `src/fetcher.py` / `src/analyzer.py` / `src/reporter.py` 等业务模块
- **不改** `.gitignore`（`reports/` 保持排除；白名单绕开它而不是放开它）
- **不改**既有 11 条 `test_phase26` 断言（只新增）
- **不引入新依赖**（纯 stdlib，与 26 期纪律一致）
- **不做** `git_ops` 之外的提交链重构（例如给其他脚本加提交能力）
- **不处理** §6 范围外发现（`push_retry.sh` 硬编码凭据 / `wecom_*` G1）

---

## 9. 确认清单

- [ ] **Step 0.1** 已确认「每日数据更新」cron 的实际命令与职责（是否含抓取）
- [ ] **Step 0.2** 已确认它是否被有意用于兜底提交 Agent 产出
- [ ] 已确认 `git --version` 支持 `git status --porcelain -- <paths>`（R8）
- [ ] 已确认白名单 `("data", "context", "alerts")` 与"哪些产物希望自动入库"一致
- [ ] 已确认 §4.6 5b 的代码提交链选型（Agent 收尾显式提交 / 08:30 全量兜底 / 两者）
- [ ] 文件范围合理、无遗漏测试、无新依赖
- [ ] 人已审阅本计划

---

## 附：核心逻辑伪代码（汇总）

```text
# ---- src/git_ops.py ----

_DATA_PATHS = ("data", "context", "alerts")     # 有意排除 reports/（.gitignore:40 已排除）

_has_changes(root, paths=_DATA_PATHS):
    run(["git", "status", "--porcelain", "--", *paths])   # ← 必须与 add 同范围（R1）
    return stdout 非空

_commit(root, date_str, report_type, paths=_DATA_PATHS):
    run(["git", "add", *paths])                            # ← 禁止 -A / --all / .（测试 1 钉死）
    run(["git", "commit", "-m", f"auto: {date_str} {report_type}"])

auto_commit_push(date_str, report_type, root=PROJECT_ROOT):   # 签名不变
    if not _enabled(): return False
    try:
        if not _has_changes(root): print("No changes, skipping."); return False
        _commit(root, date_str, report_type)
        _push(root)                                        # 代理注入逻辑原样
        return True
    except (CalledProcessError, TimeoutExpired, FileNotFoundError) as e:
        print(f"[auto-push] Failed: {e}"); return False     # 不抛异常、退出码恒 0

# ---- 可选：统一入口（§4.4） ----
if __name__ == "__main__":
    # argparse: --type(默认 "data refresh") / --date(默认今天)
    auto_commit_push(date, type)
    # 退出码恒 0
```
