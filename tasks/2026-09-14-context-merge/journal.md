# Journal — `generate_context` 加合并语义（修复盘中快照清空当日 context）

- **日期**：2026-09-14
- **任务目录**：`tasks/2026-09-14-context-merge/`
- **计划**：`plan.md`（方案 A · 合并语义，需求方已选定）
- **性质**：后端数据层，执行者按 plan C-0 ~ C-5 实施，未改动计划外架构

---

## 1. 目标（已达成）

盘中快照按 `--market` 只取本市场子集，但 `generate_context` 全量覆盖写 → 每次快照抹掉当天其它市场的数据
（实测 `fd0602d`：`us open snapshot` 把 `context/2026-09-14.json` 从 90 行砍到 12 行）。
修复：`generate_context(..., merge=True)` —— **合并「输入」，重算「派生」**。

---

## 2. 改动文件清单

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/reporter.py` | +91 / −4 | 新增 `_load_prev_context` / `_prev_sector` / `_merge_market_inputs`；`generate_context` 加 `merge: bool = False`；`correlation`/`watchlist` 先算 payload 变量（None → 保留旧值） |
| `snapshot_report.py` | +2 / −1 | `sector_heat=sector_heat`（去掉 `if sector_heat else []`）+ `merge=True` |
| `tests/test_context_merge.py` | 新增 258 行（14 条） | M-1~M-10 + `us_sector_heat` 保留 + `correlation` 重建 + **R3 接线护栏 2 条** |
| `docs/pitfalls.md` | +9 | 新段「模块 src/reporter.py（context 同日合并 2026-09-14）」 |
| `daily_report.py` | **未改** | 走默认 `merge=False`，行为逐字节不变（M-6 护栏） |

**提交**（被本仓库 `auto: 每日数据更新` cron 扫入，非手动 commit）：`377a468`（测试初版）→ `da152fe`（源码 + 测试）→ `749bdf2`（接线护栏 +37 行）。
`git status` 变 clean、`git diff` 为空是 cron 吞改动的正常现象，改动是否入库以 `git log --oneline -- <path>` 为准（`da152fe` 含 `src/reporter.py` +91）。

---

## 3. 验证结果（全部实跑）

| # | 命令 | 结果 |
|---|---|---|
| C-0 | `venv/Scripts/python -m pytest tests/ -q` | **620 passed**（基线） |
| C-3（先红） | `pytest tests/test_context_merge.py -q`（改动前） | **11 failed / 1 passed** —— 失败为 `TypeError: unexpected kwarg 'merge'`，M-6 回归护栏通过 |
| C-3（后绿） | 同上（改动后） | **12 passed** |
| C-4 | `venv/Scripts/python %TEMP%/mp_ctx_merge_e2e.py`（等价链路，不跑真实快照） | **ALL PASSED**；对照组 `merge=False` 复现原损害：`SH=None / status=休市 / sector=[] / keywords=['market summary 2026-09-14']`；`merge=True` 后 `SH=3120.0 / status=横盘 / keywords=['医药 surge …','光伏 surge …','地产 drop …']` |
| C-5a | `pytest tests/ -q` | **639 passed**（= 620 基线 + 我的 14 + 并行会话新增 5） |
| C-5b | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 首跑 **EXIT=1**（仅 `A-5b` 悬停恢复 scrollTop 断言）；**串行复跑 EXIT=0、`failures: []`**，1920 档 `scrollH=1216 ≤ 1240` |
| 定向回归 | `pytest tests/test_context_merge.py tests/test_phase27.py tests/test_phase8.py tests/test_context.py -q` | **74 passed** |

---

## 4. 遇到的问题

1. **`verify_ui` 首跑 A-5b 假红**：`A-5b 悬停恢复后自动滚动继续` 是 rAF 采样类时序断言（`actual=(234, 5) expect=None`）。本次改动仅 `src/reporter.py` + `snapshot_report.py`（后端 context 生成），`web/` 未动，A-5b 与资讯自动滚动无关；串行复跑即 `failures: []`。判为 CPU 争用下的采样假红（与 `docs/pitfalls.md` 已记载的同类现象一致），**未改断言、未放松判据**。
2. **`context/2026-09-03.json` 被测试污染（改动前既有，需求方指令后已修 —— 见 §7）**：实证 —— 仅跑 `pytest tests/test_phase27.py`（不涉及本次改动路径）就会让 `git status` 出现 `M context/2026-09-03.json` + `M data/backup/history_2026-09.json`。根因是入口类测试漏隔离 **`reporter.CONTEXT_DIR`**（reporter 在 import 时绑定该 Path → 打在定义方 `analyzer` 上不生效），主污染源为 `test_snapshot_passes_history`；`dr.main()` 末尾的 `export_monthly_backups()` 则写真实 `data/backup/`。污染已被 cron 提交（`da152fe`，333 行删除）。⚠️ **订正**：一度把 `git log` 取到的"上一个提交"`bd2c3ff` 当成正常版本 —— 实测它也是污染版（`gainers=0`、`history_30d` 尾部却到 `2026-09-14`）；真正正常版本是 `c30e2131`，见 §8。
3. **cron 抢提交 + 并行会话**：会话期间 `auto: 每日数据更新` cron 多次 `git add -A`，把源码/测试提交掉（`git status` 变 clean）；同时工作区存在另一会话的在途改动（`AGENTS.md`/`docs/*.md`/`tasks/2026-09-14-autopush-scope/`）。故：① 已用 `git log -- <path>` 反查确认改动入库；② `docs/pitfalls.md` 采用**短锚点插在 git_ops 段之前**的方式追加，未触碰并行会话内容；③ 未执行任何 `git add .`。
4. **接线护栏测试首次写错导入**：`snapshot_report.py` 是仓库根模块（`import snapshot_report as snap`），不是 `src/` 子模块 —— 已按既有测试（`tests/test_phase7.py:16`）的写法修正。

---

## 5. 下次注意什么

- **新增 `generate_context` 调用点：只取市场子集就必须 `merge=True`，且不得把 `None` 转成 `[]`**（`[]` 会被判为"要覆盖"，修复静默失效）。全量入口（daily）保持不传。
- 改动 `tests/test_phase27.py` 或新增 context 相关测试时：patch 点必须打在**使用方模块**（`rep` / `snap` / `alerts`），否则会写真实 `context/`（跑 `git status --short` 自查）。
- 验证纪律：`pytest` 与 `verify_ui` **串行**跑；采样类断言失败先串行复跑 + 读 `%TEMP%\marketpulse-verify\verify-report.json` 的 `failures`，不要凭代码推理下结论。
- 该仓库改动随时可能被 cron 提交：`git status` / `git diff` 不能作为"改动丢失"的证据，用 `git log --oneline -- <path>`。

---

## 6. 未做 / 待需求方确认（plan §7、§9）

- **不改**：`get_market_date`/`get_us_eastern_date` 日期口径、`daily_report.py` 调用、`web/app.py::_find_context_with_key`、`fetch_all`/`MARKETS`/`RETRIES`。
- **待确认 1**：`context/2026-09-14.json`（今天）被 `fd0602d` 破坏后是否需要从 git 历史恢复（取回的版本也缺 `us_sector_heat`/`correlation`/`watchlist`）。
- **待确认 2**：`data/watchlist.json`（AAPL/苹果）与 `config.json`（515300.SS）不一致的来源（独立问题，本计划不处理）。
- **待确认 3（本次新增）**：已按指令执行 —— 见 §8（`context/2026-09-03.json` 恢复至 `c30e2131`）。

---

## 7. 追加修复：测试隔离缺陷（需求方指令「这个修了」）

### 7.1 改动

| 文件 | 改动 | 说明 |
|---|---|---|
| `tests/conftest.py` | +25 | 新增 autouse 护栏 `isolate_real_output_paths`：把 `rep.CONTEXT_DIR` → `tmp_path/"context"`、`storage.DEFAULT_BACKUP_DIR` → `tmp_path/"backup"`（与既有 `isolate_watchlist_file` 同款纪律；10 个测试文件真实调用 `dr.main()`/`sr.main()`，逐个改用例是下策，且 `docs/pitfalls.md` 已明确「隔离必须做在 autouse fixture 里」） |
| `tests/test_phase27.py` | 改 1 处（+12/−7） | `test_generate_context_excludes_today`：patch 目标 `an.CONTEXT_DIR`/`an.load_history` → **`rep.*`**（原先不生效，断言真空通过）；`today_rows` 改为**全键宽记录**（`{k: None for k in st.HISTORY_KEYS}`，否则 `history_30d` 的 `r["vxn"]` 越界）；新增**落点锁** `assert path == tmp_path/"context"/"2026-09-03.json"` 与**非真空断言** `[r["date"] for r in captured["h"]] == ["2026-09-02"]` |

**未改**：`sr.main()` 的 `merge=True` 生产逻辑、`context/2026-09-03.json` 的历史内容（是否恢复待指令 —— 它现在与 HEAD 一致，即仍是 `da152fe` 的污染版本）。

### 7.2 根因订正（第一次报告归因不完整）

第一次报告把污染归给 `test_phase27.py:219`。实测内容比对后**主污染源是 `test_snapshot_passes_history`（line 285+）**：其桩数据 `fetch_all → {"VIX": 21.0}`、`last_values` 空 → `change_pct=null`、tmp DB 只 seed 1 条 `2026-09-02` → 与观察到的污染文件**逐项吻合**（VIX 21.0 / change null / 1 条 history / 空板块）。line 219 也写同一文件（`20.0/0.0`），但执行更早、被覆盖。

### 7.3 验证（实跑）

| 命令 | 结果 |
|---|---|
| `git status --short`（跑前） | clean（无 `context/` / `data/backup/` 条目） |
| `pytest tests/test_phase27.py tests/test_phase25.py tests/test_phase24.py tests/test_phase8.py tests/test_phase12.py tests/test_phase14.py -q`（跑后立刻查 status） | **100 passed**，`git status` 仍**无** `M context/2026-09-03.json`、**无** `M data/backup/history_2026-09.json` → 污染消除 ✅ |
| 对照（修复前，同一会话早前实测） | 仅跑 `pytest tests/test_phase27.py` 即产生上述两个 `M` → 缺陷可复现 |
| `pytest tests/test_phase27.py -k excludes_today` | 1 passed（修正后的断言真被用上：注入 fixture 的行被读到、当日行被剔除） |
| `pytest tests/ -q` | **639 passed**（条数与修复前一致，无回归） |

---

## 8. 恢复被污染的 `context/2026-09-03.json`（需求方指令「恢复」）

### 8.1 先扫描再恢复（不能用 `git log` 取「上一个提交」）

对 `context/2026-09-03.json` 的历史版本逐条 `git show <h>:<path>` 校验（临时探针脚本，已删）：

| commit | 时间 | `history_30d` 尾日期 | 条数 | gainers | VIX |
|---|---|---|---|---|---|
| `da152fe` | 09-14 23:15 | 2026-09-02 | 1 | 0 | 21.0 |
| `bd2c3ff` | 09-14 18:55 | 2026-09-14 | 30 | 0 | 20.0 |
| `07cfb8e` | 09-12 13:51 | 2026-09-11 | 30 | 0 | 20.0 |
| `9bae413` | 09-12 13:05 | **`20260903`（无分隔线假日期）** | 30 | 0 | 20.0 |
| `06a0b15` | 09-04 17:45 | 2026-09-04 | 30 | 0 | 20.0 |
| **`c30e2131`** | 09-04 08:01 | **2026-09-03** | 30 | **5** | 14.32 |
| `d01447c` | 09-04 00:00 | 2026-09-03 | 30 | 0 | None |

结论：**唯一通过内容不变量校验的版本是 `c30e2131`**（`auto: 2026-09-03 daily report`）—— 文件 `date` 与 `history_30d.dates[-1]` 自洽、板块非空；`bd2c3ff` 及其后所有版本都是测试覆盖后的产物。

### 8.2 执行与核对

```text
git checkout c30e2131 -- context/2026-09-03.json
```

恢复后核对（工作区实测）：9 键齐全；`history_30d` 30 条 `2026-07-28 → 2026-09-03`；
A 股板块 gainers `资源/有色 +0.89 / 医药 +0.35 / 光伏/新能源 +0.34 / 地产/基建 +0.30 / 金融 +0.16`、
losers `通信/电子 −0.68 / 农业 −0.48 / 消费 −0.24 / 军工 −0.14 / 其他 +0.04`；
`us_sector_heat` 5+5；`search_keywords` 5 条板块词；`correlation` 1 对；`watchlist.stocks` 1 条。

### 8.3 状态

- `git status` → `M context/2026-09-03.json`（**已暂存**，待提交；本仓库 auto-commit cron 大概率会把它一并提交）。
- 未重跑测试（恢复只涉及数据文件，与代码无关；且 §7.3 已证明后续跑测试不会再污染它）。
- 数据文件恢复属「需求方明确指令」下的例外操作（AGENTS 常规规则为不修改生成文件）。
