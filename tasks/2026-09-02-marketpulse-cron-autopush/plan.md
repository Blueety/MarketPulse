# 二十六期：MarketPulse cron 执行后自动 commit + push

日期：2026-09-02
架构：先读 `docs/architecture.md`；命令引用 `docs/commands.md`。

## 1. 任务目标

引用 `tasks/2026-09-02-marketpulse-cron-autopush/prd.md` Goal：

> 每次 MarketPulse 的 cron 任务（daily_report / snapshot_report / opening_analyzer）执行完成后，自动将本次产生的文件变更（报告、数据缓存、context 等）commit 并 push 到 GitHub，确保 Railway 部署始终与最新数据同步。

功能需求 F1–F6（自动 commit / push origin master / Clash 代理 `http://127.0.0.1:7890` / 无改动跳过 / message `auto: YYYY-MM-DD {报告类型}` / push 失败由 cron 重试）与非功能需求 NF1–NF3（零新依赖、可选步骤不影响报告流程、幂等）全部纳入本期范围。

## 2. 关键事实核查（实施前必须知道）

| 事实 | 结论 | 依据 |
|---|---|---|
| `data/`、`context/` 已被 git 跟踪 | 自动 commit 的实际载荷 = `data/last_values.json` + `data/history.json` + `context/*.json`（+ 触发告警日新增 `alerts/*.md`） | `git ls-files data/`=2、`context/`=4、`alerts/`=0；`.gitignore` 无这三目录 |
| `reports/` **不入库** | `.gitignore:40 reports/`；PRD「不改动文件」表称 reports 为 git tracked 与事实不符。日报 md/png、快照、开盘报告永远本地留存，`git add -A` 不会带上它们。Railway web 看板只读 `data/`+`context/`+`alerts/`，不受影响，**按 PRD 字面不改 .gitignore** | `git check-ignore -v reports/2026-09-01.md` → `.gitignore:40:reports/` |
| 已有遗留自动提交机制 | git log 存在多笔 `auto: 每日数据更新`（含时间后缀变体），由 Hermes「每日数据更新」cron 以 `git add -A` 扫入（pitfalls 二十期/二十一期/二十三期已记录为常态）；origin/master 当前同步（0 未推） | `git log`、`git rev-list --count origin/master..HEAD`=0 |
| push 重试设施已存在 | `scripts/push_retry.sh`（bash：重推 origin master → 成功通知 QQBot → `hermes cron rm` 自删重试 cron）。F6 的 cron 级重试已由此承担 | 仓库实测 |
| 测试会真实执行 `main()` | `tests/test_phase25.py` 用 monkeypatch 网络后调 `daily_report.main()`；若 main 尾部无条件 git 操作，**pytest 会触发真实 commit/push** | grep 实测 |
| 分支/身份/远程 | 当前分支 `master`；remote `origin=https://github.com/Blueety/MarketPulse.git`；user.name=zjh / email 已配 | `git branch/remote/config` |
| 脚本各自已有 date 变量 | daily 用 `get_us_eastern_date()`（美东）；snapshot/opening 用 `get_market_date(market)`（A 股按北京时间/us 按美东），commit 日期直接复用，与报告归档日期一致 | 源码实测 |

## 3. 方案决策（对 PRD 两个方案的取舍）

| 决策点 | 选择 | 原因 |
|---|---|---|
| 方案 A vs B | **方案 B：新建 `src/git_ops.py`**（PRD「src/ 可选」明确允许） | 三入口需要逐字相同的 ~30 行 git/代理子进程逻辑；三份拷贝违背仓库「每个函数只做一件事、DRY」与 AGENTS.md「保持 diff 最小、复用既有模式」；逻辑单点后可被单测覆盖，NF1（无新依赖）不受影响（纯 stdlib） |
| 开关默认值 | **默认开启**（env `AUTO_PUSH` 缺省即启用；显式 `AUTO_PUSH=0` 关闭） | F1 要求 cron 执行后自动 commit；Hermes cron 命令能否传 env 不可从仓库验证，默认开保证需求落地；手动本地开发可用 `AUTO_PUSH=0` 关（见风险表） |
| 测试护栏 | **conftest.py 顶部强制 `os.environ["AUTO_PUSH"] = "0"`**（与既有 CONFIG_PATH 隔离同款） | test_phase25 真实调 `main()` → 无护栏则 pytest 推库；护栏必须在任何 main 接线**之前**合入 |
| 子进程健壮性 | 全部 `subprocess.run(..., timeout=…)`：status 15s / add+commit 30s / push 120s；push 注入 `http_proxy`/`https_proxy=http://127.0.0.1:7890` 到 env 副本 | PRD 片段无 timeout，代理黑洞会挂死 cron；代理 env 仅作用于 push 子进程（F3），不污染其它步骤 |
| 仓库根路径 | `PROJECT_ROOT = Path(__file__).resolve().parents[1]`（src/ 上一级），不硬编码 `D:\AGENT\MarketPulse` | PRD 片段硬编码 cwd；派生路径可移植、可测（单测传 tmp_path） |
| push 失败处理 | `auto_commit_push` 返回 False、print `[auto-push] Failed: …`、**不抛异常**；入口 main 退出码恒 0 | F6 = cron 重试（既有 push_retry.sh 承担），Python 内不重试；延续仓库「决策 H：退出码恒 0」+ 图片渲染容错先例 |
| 输出通道 | 三态结果用 `print()` 到 stdout（`[auto-push] No changes, skipping.` / `Committed and pushed: …` / `Failed: …`），与 PRD 片段一致 | logging basicConfig 默认写 stderr；Hermes cron 若按 stdout 探测，print 可见 |
| commit message | 全 ASCII：`auto: {date} {report_type}`。类型映射：daily → `daily report`；snapshot → `{market} {time} snapshot`（如 `a-share midday snapshot`/`us noon snapshot`）；opening → `{market} opening analysis` | F5 示例 `auto: 2026-09-02 daily report`；规避 Windows cp936 控制台中文乱码 |
| `git add -A` 全量语义 | 保留（与 PRD 片段、遗留 cron 现状一致） | 会扫入执行瞬间未提交的开发文件（tasks/、src/ 等）——沿用仓库既有接受语义（pitfalls 记录「改动已安全入仓库」），不扩大为限定路径 add（偏离 PRD 字面） |

## 4. 涉及文件

### 改动（新增/修改）

| 文件 | 改动 | 量级 |
|---|---|---|
| `src/git_ops.py` | **新增**公共模块：`auto_commit_push(date_str, report_type) -> bool` + 私有步骤（env 门控 / `has_changes` / `commit_all` / `push`） | ~70 行 |
| `tests/conftest.py` | 追加 `os.environ["AUTO_PUSH"] = "0"`（防 pytest 误推，**先于 main 接线合入**） | +1 行 |
| `tests/test_phase26.py` | **新增**单测（见 §5 步骤 1） | ~120 行 |
| `daily_report.py` | import `git_ops`；`main()` 尾部 `return 0` 前调 `auto_commit_push(date, "daily report")` | +2~3 行 |
| `snapshot_report.py` | 同上；`main()` 的 `run_alert_checks` try/except 之后、`return 0` 前调 `auto_commit_push(date, f"{market} {time} snapshot")` | +2~3 行 |
| `opening_analyzer.py` | 同上；`main()` 尾部 `return 0` 前调 `auto_commit_push(date, f"{market} opening analysis")` | +2~3 行 |
| `docs/architecture.md` | 模块表加 `src/git_ops.py` 行、数据流加一行、关键决策表加决策行 | +3 行块 |
| `docs/commands.md` | 「何时跑什么」+「验证要点」补 git 逻辑改动条目 | +2 行块 |

### 不改动

- `data/*`、`reports/*`、`alerts/*`、`context/*`（生成物；auto-commit 只 add 不触碰内容）
- `config.json`、`.env`（gitignore 排除）、`requirements.txt`（零新依赖）
- `scripts/push_retry.sh`（F6 已由其 + Hermes cron 承担，本期不改；仅 §7 提示对齐）

## 5. 实现步骤（每步独立可验证）

> 顺序有讲究：**护栏（步骤 2）必须先于任何 main 接线（步骤 4-6）**，否则中途跑 pytest（test_phase25 真实调 `main()`）会触发真实 commit/push。

1. **写 `tests/test_phase26.py` 单测（先测后码）**
   覆盖：env 门控（缺省开 / `AUTO_PUSH=0` 关且零子进程调用）；无改动跳过（porcelain 空 → 不 commit/push）；commit message 格式 `auto: {date} {type}`；push 注入代理 env 且不污染 os.environ；push 失败（CalledProcessError/超时）→ 返回 False 不抛异常；`root` 参数化用 tmp_path + monkeypatch `subprocess.run`，全程无真实 git。
   - 验证：`venv/Scripts/python -m pytest tests/test_phase26.py -v`（新测试红 → 步骤 2 后绿）
2. **`tests/conftest.py` 加护栏**（与既有 CONFIG_PATH 强制赋值同风格）
   `os.environ["AUTO_PUSH"] = "0"`，注释说明防止 main() 接线测试触发真实推送。
   - 验证：全量 `venv/Scripts/python -m pytest tests/ -v` 仍全绿（隔离先行）
3. **实现 `src/git_ops.py`**（纯 stdlib：logging/os/subprocess/pathlib，零新依赖）
   函数契约：`auto_commit_push(date_str, report_type, root=PROJECT_ROOT) -> bool`；内部 `_enabled()`（env AUTO_PUSH ≠ "0"）→ 关则直接返回 False 无输出；`_has_changes(root)`；`_commit(root, date_str, report_type)`；`_push(root)`（代理 env 副本 + timeout）。三态 print 到 stdout。
   - 验证：`venv/Scripts/python -m pytest tests/test_phase26.py -v` 全绿
4. **`daily_report.py` 接线**：`from src import git_ops`；`main()` 尾 `return 0` 前调 `git_ops.auto_commit_push(date, "daily report")`。
   - 验证：`venv/Scripts/python -m pytest tests/test_phase25.py tests/test_phase26.py -v`（test_phase25 真实 main 调用在 AUTO_PUSH=0 下安全跳过）
5. **`snapshot_report.py` 接线**：同模式，`date` 复用 `get_market_date(market)`。
   - 验证：`venv/Scripts/python -m pytest tests/test_phase7.py tests/test_phase26.py -v`
6. **`opening_analyzer.py` 接线**：同模式。
   - 验证：`venv/Scripts/python -m pytest tests/test_phase15.py tests/test_phase26.py -v`
7. **全量回归**。
   - 验证：`venv/Scripts/python -m pytest tests/ -v`（既有 382 + 新增全绿；无真实 git/网络副作用）
8. **端到端真跑验证**（真实产生一笔当日数据 commit/push，与每日 cron 行为无异；代理须已开）：
   - `venv/Scripts/python daily_report.py`
   - `git log --oneline -1` → 应为 `auto: YYYY-MM-DD daily report`（F5 格式）
   - `git status --porcelain` → 空（F2 已推送、工作区干净）
   - 立即再跑一次同一脚本 → stdout 应现 `[auto-push] No changes, skipping.` 且 `git log --oneline -1` 不变（F4 幂等）
   - 若代理未开：push 失败仅 print `[auto-push] Failed: …`、脚本退出码 0、commit 保留本地；随后可手动 `git push origin master` 或交由既有重试 cron
9. **文档收尾**：`docs/architecture.md`（模块表 + 决策表 + 数据流）与 `docs/commands.md`（验证要点/何时跑什么）补本期条目；`git diff` 复核改动范围；按 AGENTS.md 写 `tasks/2026-09-02-marketpulse-cron-autopush/journal.md`。
   - 验证：`git diff --stat` 与预期文件清单一致；架构文档条目与实现一致

## 6. 验证命令（引用 docs/commands.md）

| 步骤 | 命令 | 出处/依据 |
|---|---|---|
| 单测 | `venv/Scripts/python -m pytest tests/test_phase26.py -v` | commands.md 快速检查第 1 条（同族） |
| 接线回归 | `venv/Scripts/python -m pytest tests/test_phase25.py tests/test_phase7.py tests/test_phase15.py -v` | 覆盖三个被改入口的既有测试 |
| 全量 | `venv/Scripts/python -m pytest tests/ -v` | commands.md 完整检查 |
| 主脚本闭环 | `venv/Scripts/python daily_report.py` | commands.md 快速检查第 2 条 |
| E2E 断言 | `git log --oneline -1` / `git status --porcelain` / 重复运行观察 skip | PRD 验证节 + F4/F5 |

## 7. 风险评估与注意事项

| 风险 | 缓解 | 状态 |
|---|---|---|
| pytest 触发真实推送（test_phase25 真实调 `main()`） | conftest 强制 `AUTO_PUSH=0`，护栏先于接线合入 | 已识别，步骤顺序硬约束 |
| 手动本地验证触发 Railway 重部署（每次 push 自动 redeploy） | 本地反复跑用 `AUTO_PUSH=0`（cmd: `set AUTO_PUSH=0&& venv\Scripts\python daily_report.py`；bash: `AUTO_PUSH=0 venv/Scripts/python daily_report.py`）；真跑验证限一次 | 需执行者遵守 |
| push 挂死/代理黑洞 | 每步 subprocess timeout（15/30/120s） | 已设计 |
| 遗留 Hermes「每日数据更新」cron 与脚本内置 push 双重提交 | 脚本侧 F4 空仓跳过兜底；**上线后应由用户在 Hermes 侧移除该 cron 的 git add/commit/push 步骤**（交付配置，非本仓库文件）——否则 message 风格混杂（`auto: 每日数据更新` vs F5 格式） | 后续交付动作，计划末尾提示 |
| `git add -A` 扫入执行瞬间未提交的开发改动（tasks/、src/ 等） | 沿用遗留 cron 既有语义（pitfalls 已记录为正常）；开发期可用 AUTO_PUSH=0 减少意外 | 接受，文档注明 |
| PRD 称 reports/alerts 为 tracked，实为 gitignore/空 | 不改 .gitignore（PRD「不改动」字面）；数据同步目标由 data/+context/ 达成；Railway 看板不读 reports/ | 事实已在 §2 记录，向用户说明 |
| commit 中文乱码（Windows cp936） | F5 message 全 ASCII | 已设计 |
| 多入口同日多次运行产生多笔 commit | F4 自然去重：仅数据/告警实际变化时产生 commit；重复 message 无害（内容不重复） | 幂等 NF3 达成 |
| push_retry.sh 未显式走代理 | 现状可直接 push（git 侧已配代理/凭据，origin 同步为证）；若 F3 场景下失败，需为 retry cron 的 shell 补同一代理 env | 后续可选对齐 |
| git 不在 cron shell PATH | git_ops 捕获 FileNotFoundError → Failed 日志、退出码 0，不中断报告 | 已设计 |

## 8. 预计影响的文件范围

- **代码**：`src/git_ops.py`（新增，~70 行）、`daily_report.py`、`snapshot_report.py`、`opening_analyzer.py`（各 +2~3 行）
- **测试**：`tests/test_phase26.py`（新增）、`tests/conftest.py`（+1 行）
- **文档**：`docs/architecture.md`、`docs/commands.md`（条目化增量）
- **不改动**：`src/*` 其它模块、`web/*`、`scripts/*`、`requirements.txt`、`.env`、`config.json`、`data/`、`reports/`、`alerts/`、`context/`、`.gitignore`
- **运行时副作用**：每个入口脚本正常执行结束后最多一次 `git commit`（有改动时）+ 一次代理 push；`AUTO_PUSH=0` 时零副作用

## 9. 后续交付配置（非本仓库范围，需向用户确认）

1. Hermes「每日数据更新」cron 停用其 `git add -A`/commit/push 步骤（防与脚本内置逻辑双重提交、统一 message 格式）。
2. 推送失败检测：Hermes cron 以 stdout `[auto-push] Failed` 为信号调度既有 `scripts/push_retry.sh` 重试 cron（F6 闭环；push_retry.sh 成功路径已含自删 + QQBot 通知）。
3. 如 A 股/美股时区导致同日多脚本共享 date 归档口径与 commit 日期期望不符，以各脚本既有归档日期为准（已复用）。
