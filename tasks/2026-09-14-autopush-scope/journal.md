# 任务日志：自动提交范围收窄（路径白名单 + 提交链拆分）

- **日期**：2026-09-14
- **计划**：`tasks/2026-09-14-autopush-scope/plan.md`
- **角色**：编码执行者（Phase 3 Step 3.6）
- **状态**：代码 / 测试 / 文档**已完成并验证**；**仓库外 Hermes cron 调整待用户执行**（plan 步骤 5）

## 1. 目标

| # | 目标 | 结果 |
|---|---|---|
| G1 | 任何 cron 都不得把**源码/测试/文档的半成品**提交入库 | 仓库内（`src/git_ops.py`）已达成并用真实 git 证明；**仓库外 Hermes cron 仍全量**（见 §5 / G7） |
| G2 | 数据同步（Railway）新鲜度不劣化 | 未改任何时点 / 频率；只收窄提交范围 → 零劣化 |

## 2. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/git_ops.py` | 新增 `_DATA_PATHS = ("data","context","alerts")`；`_has_changes` → `git status --porcelain -- <paths>`；`_commit` → `git add <paths>`（禁 `-A`/`--all`/`.`）；模块 docstring 补范围语义 |
| `tests/test_phase26.py` | **11 → 16 条**：新增 5 条（白名单实参 / status 同范围 / 源码 WIP 不触发 / `reports` 不入列 / 忽略文件不触发）；fixture 增可选 `status_stdout_paths`（**既有 11 条零改动**） |
| `docs/architecture.md` | **append-only** +1 决策行（26 期「`git add -A` 全量语义」原文保留） |
| `docs/system-overview.md` | §6 +1 行「自动提交范围」；§9 新增 **G7**（仓库外链仍全量） |
| `docs/pitfalls.md` | 新增 1 节 4 条（同范围 / 白名单边界 / 真实 git 证明 / 范围与频率解耦） |
| `AGENTS.md` | Working Rules +1 条「自动提交范围白名单」 |
| `docs/commands.md` | 快速检查表 +2 行（`test_phase26` / 同口径 `git status`） |
| `tasks/2026-09-14-autopush-scope/journal.md` | 本文件 |

**三入口零改动**：`daily_report.py:263` / `snapshot_report.py:98` / `opening_analyzer.py:122` 均为位置参数 2 个 → `auto_commit_push` 签名不变即无影响（已逐个核对）。

## 3. 验证结果（全部实跑，串行）

| 验证 | 命令 | 结果 |
|---|---|---|
| 本任务单测 | `venv/Scripts/python -m pytest tests/test_phase26.py -v` | **16 passed**（11 既有全绿 + 5 新增） |
| 全量回归 | `venv/Scripts/python -m pytest tests/ -q` | **637 passed** |
| 静态前提 | `git check-ignore -v reports context alerts data` | 仅 `reports` 命中 `.gitignore:40` ✓ |
| 静态前提 | `git add --dry-run data/ context/ alerts/` | `exit=0` ✓ |
| 静态前提 | `git --version` | `2.53.0.windows.1`（支持 `--` pathspec）✓ |
| **真实 git 冒烟**（临时仓库，plan §5.3） | 临时脚本 | **ALL PASSED**：数据文件入 commit；**源码 WIP 未入 commit 且仍留在工作区**；被忽略文件未入库；message 格式正确；无 remote → push 失败返回 `False` 但 **commit 已落盘**（正是要验的） |
| **G1 仓库内只读验收**（plan §5.4 等价式） | 临时脚本 | **ALL PASSED**：现场全量 status 有 `M snapshot_report.py` / `M src/reporter.py`（其它 agent 正在写），白名单口径为**空** → `_has_changes=False` ⇒ 此刻真跑数据入口只会 `No changes, skipping.` |

## 4. 遇到的问题 / 与 plan 的偏差

| # | 偏差 | 说明与处置 |
|---|---|---|
| D1 | **plan §4.1 的 hermes 命令形式不成立** | `hermes cron ls` 与 `hermes cron show <id>` 都**不存在**（实际子命令为 `list`；无 `show`；`status` 不接受 id）。改用 `hermes cron list` + `hermes cron runs <id>` |
| D2 | **plan 把 5 分钟 cron 称为「每日数据更新」** | 那是**提交信息**，cron 实名 **`MarketPulse 自动推送GitHub`**（`*/5`，id `6f6e40a6f8b4`，`Deliver: local`，`source=builtin`）。另有 `MarketPulse 数据同步到GitHub`（`15 8 * * *`，id `b664e567f5c2`） |
| D3 | **步骤 3（统一入口 CLI）未执行** | 该 cron 是 Hermes **builtin** 任务（`source=builtin`），**不是 shell 命令** → §4.4「让 Hermes 侧调用仓库内唯一入口」无从落地；plan 亦标注其为**可选**。仓库内部分（步骤 1/2）已足够达成 G1 的代码侧 |
| D4 | **§5.4 第 2 步"执行一次数据入口（AUTO_PUSH 默认开）"未原样执行** | 那会**真 push** → 触发 Railway 重部署 + 与外部 cron 抢提交（plan §5.3 自己也明令禁止）。改为**只读等价验收**（白名单口径为空 vs 全量非空 + `_has_changes=False`），效果等价、零副作用 |
| D5 | **新发现（plan 未覆盖）** | `git add <paths>` 对**不存在**目录 → `exit=128 fatal: pathspec … did not match any files`；对**存在但为空**目录 → `exit=0`。已写入 `docs/pitfalls.md` |
| D6 | plan §4.7 要求 pitfalls 补 2 条 | 实补 **4 条**（多出的两条来自本次实测：白名单目录缺失边界、范围与频率解耦） |

## 5. 阻塞门 Step 0 结论

- **0.1（是否含抓取）**：该 cron 的**提交**行为已实证（信息 `auto: 每日数据更新[ <时间>]`，内容含任意工作区文件）；**抓取**行为**无法从 CLI 读到命令文本**（`runs` 只给 run-id + `source=builtin`）。用仓库证据反推：`data/news.json` / `data/watchlist.json` 的提交时点**不规则**（22:50 / 22:15 / 21:46 / 21:41 / 21:05 / 20:55 / 20:25 …，**并非每 5 分钟一次**）→ **该 cron 自己不做数据抓取**，只把工作区已有改动推走 ⇒ 对应 plan §4.6「纯提交」分支。
- **0.2（是否有意兜底 Agent 产出）**：**事实上**在兜底（§3.2 证据：`docs/pitfalls.md`、`tasks/*/journal.md`、`tests/conftest.py`）。是否"有意"**需用户确认**；未确认前按 plan 默认"是"处理（保留一条全量兜底链）。
- **仍未确认（需用户执行）**：cron 的命令/路径配置不可读 → **步骤 5 必须由用户处置**。

## 6. 未运行的检查（如实标注）

- ❌ **未做真实 push 验证**：会触发 Railway 重部署 + 抢提交 → 由下一次外部 cron 自然发生时观察 `git log` 确认。
- ❌ **未验证 Hermes cron 配置变更后的行为**：仓库外配置，本进程读不到 → 依赖用户执行并观测。
- ⚠️ **仓库外链仍是全量 `git add -A`**（`docs/system-overview.md` §9 G7）：在用户处置前，**G1 只对 Python 侧三入口成立**。

## 7. 下次注意

1. 改 `src/git_ops.py` 后跑 `pytest tests/test_phase26.py -v`；真实 git 证明一律**在临时仓库**做。
2. 判断"改动会不会被自动提交"用 `git status --porcelain -- data context alerts`（与 `_has_changes` **同口径**），不要用全量 status 推断。
3. 外部 5 分钟 cron 仍是全量 `git add -A`：**不要把写了一半的源码/文档留在工作区**（本会话已被它扫走过多次半成品，`git status` 会突然变干净而让人误判"改动丢了"）。
4. `reports/` **永远不要**加进 `_DATA_PATHS`（ignore 命中 → `git add` fatal → 三入口数据提交全挂）。
5. 若日后新增需自动入库的数据目录（如新的 `xxx_output/`），需同时改 `_DATA_PATHS` + `test_reports_not_in_whitelist` 的集合断言（改动即需复核）。
