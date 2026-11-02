# Plan — 数据存储升级（JSON → SQLite）

> 日期：2026-09-12 ｜ 角色：架构师 ｜ 输入：[prd.md](./prd.md)（用户提供，备份机制按月归档版）
> 状态：**待用户确认 PRD 修正清单（§2）后交执行者**

## 0. 结论先行

方案可行：标准库 `sqlite3` 零新依赖、长表 `(date, symbol, value)` 与现有宽表 JSON 互转无损、个人数据量级（10 年 ~4.4 万行）SQLite 绰绰有余。**核心架构手法：保持 `analyzer.load_history / append_history / merge_history` 三个函数签名不变、只换内部实现**——16 个消费方（daily/snapshot/opening 三入口、reporter、backtest、web、全部测试）中绝大多数零改动自动跟随，把爆炸半径压缩到 analyzer + web 两处。

但 PRD 有 **7 处需要修正/拍板的点**（§2），其中 3 处是实质性设计缺陷，不修会直接违背 PRD 自己的目标：

1. **备份"全量导出"与体积估算自相矛盾**（每文件全量 → 一年 4.3MB 且二次增长，PRD 自己算的 400KB/年 不成立）→ 改为每文件仅含当月记录；
2. **Web 启动恢复标为"可选"** → 必须升为 P0 必做：`data/marketpulse.db` 进 `.gitignore` 后，**Railway 每次部署（临时文件系统）DB 必然不存在**，恢复链不是兜底而是 Railway 的唯一数据来源；
3. **测试迁移被严重低估**：现状 **14 个测试文件直接 monkeypatch `HISTORY_FILE`** 来做 tmp 隔离，切换后全部要改为 tmp SQLite fixture——这是本任务工作量的一半，不是"确认项"而是主体工程。

---

## 1. 任务目标（引用 prd.md Goal）

将历史行情从 `data/history.json` 迁移到 SQLite（`data/marketpulse.db`），脚本与 Web 直接读写 SQLite（不做双写），历史数据永久保留（取消滚动删除），Web `/api/history` 支持日期范围查询（≤200ms），备份按月归档提交 Git，Web 启动时从备份可恢复。

## 2. PRD 修正清单（需用户逐项确认，本 plan 按修正后方案编写）

| # | PRD 原文 | 修正 | 理由 |
|---|---|---|---|
| **D1** | 备份"将 SQLite **全量**导出为 JSON" + 附录体积估算按每月 ~360 条 | **每个 `history_YYYY-MM.json` 仅含当月记录**；当月文件每次运行覆盖，历史月文件写成后冻结；恢复 = 按月升序合并全部文件；自愈规则：某月文件缺失时从 DB 补写 | 全量导出 × 12 月 = 每份都含全部历史，一年 12×360KB≈4.3MB 且随年限二次增长，PRD 风险表"一年约 400KB"不成立；分月归档才与估算一致，且历史月记录不可变（只增不改），冻结无损 |
| **D2** | "Web 启动恢复机制（**可选**）" | **必做（P0）**，且降级链完整：DB 缺失/空 → 按月合并 `data/backup/*.json` → 仍无 → `data/history.json`（旧格式，一次性兼容读）→ 仍无 → 空库显示「数据暂缺」不崩 | Railway 临时文件系统 + DB 入 gitignore ⇒ 每次部署都走恢复；不是边缘场景是主路径。恢复是 web 对自身 DB 副本的一次性引导写入，不违反"web 不写业务数据"边界（仅 DB 空时触发，幂等） |
| **D3** | 表结构含 `change` 列，备份示例里有 change 值 | **列保留（nullable），迁移与写入填 NULL，所有读路径不消费**——change_pct 一律继续由相邻收盘价派生（现状：web `_compute_latest`、`_build_watchlist_payload` 均为读时派生） | 存时点 change 会引入"以哪个基准算"的语义分歧（昨收？前收？），且违背 PRD 自己的验收"返回格式与现有 API 保持一致（前端无需改动）"；读时派生是现有唯一事实来源 |
| **D4** | "reporter.py 修改：趋势图数据从 SQLite 读取" | **reporter.py 预计零改动**：趋势图数据由 `daily_report.py` 调 `load_history()` 后作参数传入（`render_trend_chart(history, ...)`），analyzer 切换后自动来自 SQLite | 消除不必要改动面；PRD 文件清单相应缩减 |
| **D5** | 未提及测试迁移 | **新增主体工作项**：conftest 增加 tmp SQLite fixture；14 个 patch `HISTORY_FILE` 的测试文件改为 patch `storage.DB_PATH` | 现状测试隔离机制完全建立在 JSON 文件路径上（`analyzer.HISTORY_FILE` / `web.app.HISTORY_FILE`），不迁移测试则全量测试必红 |
| **D6** | "每日脚本运行后调用 scripts/backup_db.py" | 备份核心函数放 `src/storage.py`（`export_monthly_backups()`），`scripts/backup_db.py` 只是薄 CLI 包装；`daily_report.py` 直接调 storage 函数 | 入口 import `scripts/` 是反向分层（scripts 应依赖 src）；进程内调用省掉子进程开销与解释器冷启动 |
| **D7** | "保留 90 天" / "Railway 部署与 DB 的关系" | 事实修正：现状 retention 已是 **365**（2026-09-11 已回填 1Y，用户 config.json `history.retention_days: 365`）；且 **history.json 目前是被 git 提交的**（`.gitignore` 未忽略 `data/`，auto-push 每日随行）——即"永久保留 + 异地持久"今天已部分成立。迁移后 DB 不入库，**Railway 持久性从"git 随行"变为"备份恢复链"**，这是本任务最大的架构权衡 | 必须明确接受：换取结构化查询/永久保留的本地保障，代价是 Railway 依赖 S6 恢复链且备份 push 失败期间部署会拿到旧数据（`scripts/push_retry.sh` 已有重试兜底） |

另有两处小修正：**D8** `scripts/backtest.py --history` 读 JSON，切换后输入冻结（回测基于 stale 数据）——标记为已知缺口，本任务不修（建议后续 `--from-db`），验收时注明"数据截至"日期即可；**D9** web `days` 参数上限 `le=365` 建议放宽到 `le=3650`（永久保留的数据查询不到就失去意义），响应结构不变。

## 3. 现状核实（回答 PRD「需确认的现有实现」）

| 问题 | 核实结果 |
|---|---|
| history.json 结构 | **列表**（非 date 键 dict），按时间序 append；每条 `{date, gspc, ixic, sh, sz, cyb, vix, vxn, move, gld, btc}`——**小写 symbol 键**（`_HISTORY_KEYS`，10 键含 GLD/BTC），**`None` 是语义**（休市/未收盘），不得丢失；当前 ~365 行 |
| analyzer 读写函数 | `load_history()`（analyzer.py:601）；`append_history(record, merge_existing=False)`（:632，同日覆盖 + merge_existing 定稿保护 + `HISTORY_MAX` 裁剪 + tmp+`os.replace` 原子写）；`merge_history(date, values)`（:656，市场子集投影并入当日行，不整行覆盖） |
| web /api/history 现状 | 单一漏斗 `_load_history_raw()`（web/app.py:63，`HISTORY_FILE` 经 analyzer 导入后使用方重绑定）→ `api_history`(:471) 与 `_last_records`(:78)→`api_latest` 都走它；返回归一化基准 100 + `raw` + `change_7d` |
| retention 配置 | `src/config.py` DEFAULTS `history.retention_days: 90`，env `HISTORY_RETENTION_DAYS` 覆盖，**用户 config.json 已改 365**；裁剪逻辑只在 `append_history`（`HISTORY_MAX`） |
| daily_report 末尾流程 | `append_history(merge_existing=True)` → `run_alert_checks` → `save_last_values` → `generate_context` → `render_report_image` → `auto_commit_push`。**备份插入点：`generate_context` 之后、`auto_commit_push` 之前**（`git add -A` 保证同一 auto-commit 携带备份，`src/git_ops.py` 零改动） |
| 其他相关事实 | `opening_analyzer.py` 是第三入口（PRD 清单遗漏）——签名保持策略下自动兼容，纳入回归；测试侧 **14 个文件 patch `HISTORY_FILE`**（test_web.py 8 处最多），16 个文件触及 history 函数；analyzer 近期已新增 `WATCHLIST_FILE`/`save_watchlist_snapshot`（自选股文件化任务已实施），本次勿动 |

## 4. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `src/storage.py` | **新建** | SQLite 连接/WAL、`init_db`、`upsert_history_rows`（preserve/overwrite 两模式）、`query_history`、`get_latest`、`get_date_range`、`count_rows`、`rows_to_records` 长转宽、`export_monthly_backups`、`restore_if_empty`；`DB_PATH` 模块级默认 `data/marketpulse.db`（**调用时属性查找**，测试单点 patch） |
| `scripts/migrate_to_sqlite.py` | **新建** | 一次性迁移：JSON 宽表 → 长行 → 事务批量 upsert → 逐值校验 → 报告；`--db` 参数、幂等可重跑 |
| `scripts/backup_db.py` | **新建** | 薄 CLI 包装 `storage.export_monthly_backups`（D6） |
| `src/analyzer.py` | 修改 | 三函数内部换 storage；**删除 `HISTORY_MAX` 裁剪调用**（常量保留防引用断裂，加 deprecated 注释）；`rows_to_records` 产宽记录（全 `_HISTORY_KEYS` 键、None 保留、date 升序） |
| `src/config.py` | 修改 | `retention_days` 保留解析、注释标记 deprecated（白名单校验下未知键本就被忽略，用户 config 不需清理） |
| `web/app.py` | 修改 | `_load_history_raw` 内部改 storage；`api_history` 加 `start_date`/`end_date`（与 `days` 并存：显式范围优先，D9 放宽上限）；startup 恢复钩子（S6） |
| `daily_report.py` | 修改 | `generate_context` 后、`auto_commit_push` 前 try/except 调 `storage.export_monthly_backups()`（失败仅记日志，退出码恒 0） |
| `.gitignore` | 修改 | 加 `data/marketpulse.db` `-wal` `-shm`；`data/backup/` 确认不被忽略（现状未忽略，加注释防误加） |
| `tests/test_storage.py` | **新建** | storage 单测（见 S1） |
| `tests/conftest.py` | 修改 | 新增 `tmp_db` fixture（tmp 路径 + `monkeypatch.setattr(storage, "DB_PATH", ...)` + `init_db` + `seed_db(records)` 辅助） |
| `tests/` 14 个既有文件 | 修改 | `HISTORY_FILE` patch → `tmp_db`/`storage.DB_PATH`（清单见 §8） |
| `docs/architecture.md` `AGENTS.md` `docs/pitfalls.md` `docs/commands.md` | 收尾 | 决策行 / 项目地图 / 坑位 / 新命令 |
| `data/marketpulse.db` | 运行时生成 | gitignore 排除 |
| `data/backup/history_YYYY-MM.json` | 运行时生成 | **提交 Git** |

**零改动**：`src/reporter.py`（D4）、`src/fetcher.py`、`src/git_ops.py`（`git add -A` 自动包含备份）、`src/alerter.py`（只读 `last_values`，不碰 history）、前端三件（响应结构不变）、`snapshot_report.py`/`opening_analyzer.py`（签名保持自动兼容；快照是否也触发备份见 §6 注）。

## 5. 实现步骤（每步可独立验证）

### S0 前置（一次性，人工）
1. 备份 `data/history.json` 到仓库外（如 `tasks/2026-09-12-sqlite-migration/history.backup.json`，该目录 tasks/*/tmp/ 已 gitignore，放 tasks 根下注意勿提交——**放仓库外更稳**）。
2. 用户确认 §2 修正清单（尤其 D1/D2/D3）。

### S1 storage.py 基础设施
- 表结构按 PRD 附录（`PRIMARY KEY(date, symbol)`，`symbol` 存**小写键**）；`PRAGMA journal_mode=WAL`。
- `upsert_history_rows(rows, preserve_existing: bool)`：

  ```text
  preserve_existing=True  → ON CONFLICT(date,symbol) DO UPDATE
                            SET value = CASE WHEN excluded.value IS NULL THEN history.value ELSE excluded.value END,
                                change 同理
  preserve_existing=False → DO UPDATE SET value = excluded.value  （迁移/回填用，允许写 NULL）
  ```

  该二分精确对应 `append_history(merge_existing=)` 与 `merge_history` 的"NULL 不抹盘中值"语义；长表下每 symbol 独立行，27 期"不整行覆盖"纪律自动成立。
- `query_history(symbols=None, start_date=None, end_date=None)` → 长行，**`ORDER BY date ASC`**（pitfalls：`merge_history` 只 append 不排序的历史教训——排序必须在读取侧一次性保证）。
- `rows_to_records(rows)`：长转宽，emit 全键（缺键补 None），输出结构与 history.json 记录逐字段同构。
- 单测：init 幂等 / upsert 双模式 / **NULL 往返**（写 NULL 读 NULL）/ 范围与 symbols 过滤 / 空库行为 / WAL 下并发读写冒烟 / 重复 init 不清数据。

**验证**：`venv/Scripts/python -m pytest tests/test_storage.py -v`

### S2 迁移脚本
- 读 `data/history.json` → 逐记录展开长行（**None 保留为 NULL**，D3：change 一律 NULL）→ 单事务批量 upsert（overwrite 模式）→ 校验：总行数一致 + **逐值全量比对**（数据量小，全量比对成本低）→ 打印报告（条数/失败/耗时）→ `PRAGMA wal_checkpoint(TRUNCATE)` 收尾。
- 幂等：重跑前 `DELETE FROM history`（或 `--append` 关闭）；`--db` 可指临时库做演练。

**验证**：先 `--db` 指临时路径演练一遍 → 正式迁移 → Python 冒烟逐值对比 SQLite vs JSON。

### S3 analyzer 切换 + 测试迁移（**本任务最大风险步，单独成步**）
1. `load_history()`：`storage.query_history()` → `rows_to_records`。签名/返回结构不变。
2. `append_history(record, merge_existing)`：宽转长 upsert（preserve 按参数）；**删除 `HISTORY_MAX` 裁剪**（永久保留）。
3. `merge_history(date, values)`：子集长行 upsert（preserve=True）。
4. `src/config.py`：`retention_days` 注释 deprecated；`HISTORY_MAX` 保留定义但 analyzer 不再使用（注释说明）。
5. **测试迁移**：
   - conftest 新增 `tmp_db` fixture（init tmp DB + patch `storage.DB_PATH`）与 `seed_db(records)` 辅助（宽记录 → upsert，等价旧"写 tmp history.json"）；
   - patch 点变更说明：现状纪律是"monkeypatch 打使用方模块"（因 import-time 绑定）；storage 侧 `db_path or DB_PATH` 是**调用时属性查找**，`monkeypatch.setattr(storage, "DB_PATH", tmp)` 单点全局生效——这是对该纪律的**有意例外**，理由记入 pitfalls；
   - 14 个文件逐个改：`monkeypatch.setattr(analyzer, "HISTORY_FILE", tmp)` → `tmp_db` + `seed_db`。**断言一律不动**（行为等价锁定是既有测试的价值）。
6. 完成后立即跑日报闭环，与迁移前输出对比。

**验证**：`venv/Scripts/python -m pytest tests/ -v` 全绿（重点 test_analyzer / test_web / test_phase27 / test_merge_history）；`AUTO_PUSH=0 venv/Scripts/python daily_report.py` → 当日 `reports/*.md` 与切换前 diff 应为空或仅时间戳级差异。

### S4 web 切换 + 日期范围参数
- `_load_history_raw()` 内部改 `storage.query_history()` + 宽转换（`api_latest`/`_last_records` 自动跟随）。
- `api_history` 加 `start_date: str | None`、`end_date: str | None`（Query 校验格式 YYYY-MM-DD）；语义：显式范围优先，`days` 忽略；两者皆缺省走现默认 30；`days` 上限放宽（D9）。
- 响应结构零变化（归一化/raw/change_7d 照旧）；web 测试 patch 点同步改（test_web.py 8 处）。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v`；起 uvicorn（新端口）：`/api/history?days=30` 响应与切换前 JSON diff 为空；`?start_date=...&end_date=...` 生效；`curl -w "%{time_total}"` ≤ 0.2s。

### S5 备份机制（D1 修正版）
- `storage.export_monthly_backups(backup_dir=DATA_DIR/"backup")`：

  ```text
  months = SELECT DISTINCT substr(date,1,7) FROM history ORDER BY 1
  for m in months:
      path = backup_dir / f"history_{m}.json"
      if m == 当前月 or not path.exists():          # 当月覆盖更新；历史月缺失才补（自愈）
          rows = query_history(start_date=f"{m}-01", end_date=f"{m}-31")
          写 {export_date, month: m, record_count, records}（tmp + os.replace 原子写）
      else: 跳过（历史月冻结，绝不重写）
  报告：各文件记录数/字节
  ```

- `scripts/backup_db.py`：argparse 薄 CLI（`--db`/`--backup-dir`），调 storage 函数。
- `daily_report.py`：`generate_context` 块后、`auto_commit_push` 前插入 try/except 调用（失败仅记日志，不影响退出码）。
- `.gitignore` 加 db/wal/shm 三行；确认 `data/backup/` 未被忽略。
- 备注：`snapshot_report.py` 是否同样触发备份——PRD 未要求，默认**不加**（盘中快照值最多滞后到次日 daily 才进备份链，可接受）；如要加，一行 try/except 调用即可，留待用户定。

**验证**：手跑 CLI 两次 → 同月文件被覆盖不新增；`AUTO_PUSH=0` 真跑 daily → `git status` 出现 `data/backup/history_2026-09.json`（不实际 push）。

### S6 Web 启动恢复（**P0**，D2）
- `storage.restore_if_empty(db_path, backup_dir)`：history 表为空 → 按文件名（=月份）升序合并 `data/backup/*.json` → 仍空 → 读 `data/history.json`（旧宽格式，兼容一次性导入）→ 仍无 → 空库返回（不崩）。恢复写事务，幂等（只在空库触发）。
- `web/app.py` 在 FastAPI startup 事件调用；**conftest 设 `MP_SKIP_RESTORE=1`（或等价开关）防 pytest 触发真实恢复写盘**。
- 降级链即 D2 所列三级，页面在全部缺失时显示「数据暂缺」，不白屏。

**验证**：删 DB → 启 web → 数据完整（与备份逐值比对）；删 DB + 改名 backup 目录 → 启 web → 页面正常、趋势图区「数据暂缺」；恢复现场。

### S7 全量回归 + 文档收尾
- 全量 pytest；三入口 `AUTO_PUSH=0` 冒烟（daily / snapshot a-share midday / opening）；backtest 用冻结 JSON 仍可跑（报告标注数据截止日，D8）。
- `git diff` 核对改动范围 = §4 清单。
- docs 收尾：architecture.md 决策行 + 模块表加 storage；AGENTS.md 项目地图；pitfalls.md（patch 点例外、NULL 语义、恢复链、backtest 缺口）；commands.md（迁移/备份/恢复命令）。

**验证**：`venv/Scripts/python -m pytest tests/ -v` 全绿。

## 6. 验证命令（引用 docs/commands.md + 本任务新增）

| 用途 | 命令 |
|---|---|
| 全量测试 | `venv/Scripts/python -m pytest tests/ -v` |
| 日报闭环 | `AUTO_PUSH=0 venv/Scripts/python daily_report.py` |
| 快照冒烟 | `AUTO_PUSH=0 venv/Scripts/python snapshot_report.py --market a-share --time midday` |
| 迁移演练/正式 | `venv/Scripts/python scripts/migrate_to_sqlite.py --db <tmp>` / 不带 `--db` |
| 备份 | `venv/Scripts/python scripts/backup_db.py` |
| Web + 性能 | `venv/Scripts/python -m uvicorn web.app:app --port 8017`（未用过端口）；`curl -w "%{time_total}" "http://localhost:8017/api/history?days=30"` ≤ 0.2s |
| 日期范围 | `curl "http://localhost:8017/api/history?start_date=2026-08-01&end_date=2026-08-31"` |
| UI 验收（若动前端则必跑；本任务前端零改动，建议仍跑一次回归） | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` |

**注意**：验证期所有入口必须 `AUTO_PUSH=0`；真跑验证限一次（push 触发 Railway 重部署）；迁移前 `data/history.json` 必须先备份（S0），验证后确认未被改写。

## 7. 风险评估和注意事项

| # | 风险 | 应对 |
|---|---|---|
| R1 | **测试迁移面大**（14 文件、~50+ 处 patch），遗漏导致红片 | S3 单独成步、全量 pytest 门禁；逐文件改断言零改动；`seed_db` 辅助最小化每个文件的改动量 |
| R2 | 直接切换、无双写，切换即不可逆运行 | S0 备份 JSON；S3 完成立即日报 diff 对比；回退 = `git revert` + 恢复 history.json（迁移期间 JSON 冻结未删，始终可回） |
| R3 | **Railway 恢复链断裂**（备份尚未 push 时发生部署 → 恢复旧数据） | 备份在 auto_commit 前生成、同一 commit 携带；`push_retry.sh` 重试兜底；S6 验证含"备份缺失"降级分支；接受短暂 stale（D7 已明示权衡） |
| R4 | NULL 语义丢失（休市/未收盘被当成"无此行"或 0） | D3/D4 专项：迁移保留 NULL、查询保留 NULL、宽转换补键、单测锁 NULL 往返；趋势图按 NaN 断点依赖此语义 |
| R5 | 存储层小写/大写键混淆 | 沿用 pitfalls 纪律：存储 symbol 一律小写（`_HISTORY_KEYS` 同源），单测锁 |
| R6 | `merge_existing`/`merge_history` 的"NULL 不覆盖"语义在 SQL 侧走样 | upsert 双模式（preserve/overwrite）+ 单测逐条对应现行为；27 期"不整行覆盖"在长表下结构性地成立 |
| R7 | WAL 文件残留/未 checkpoint 导致部署不一致 | 迁移与恢复完成后 `wal_checkpoint(TRUNCATE)`；db-wal/shm 进 gitignore |
| R8 | web 测试误触发启动恢复写真实 DB | startup 恢复 + conftest 显式跳过开关；restore 幂等（仅空库触发）双保险 |
| R9 | pytest 期间 patch `storage.DB_PATH` 影响其他消费方 | storage.DB_PATH 是唯一 patch 点（有意例外，记 pitfalls）；conftest fixture 作用域按测试隔离 |
| R10 | backtest 输入冻结（D8） | 本任务标注不修；验收报告注明数据截止日；后续任务 `--from-db` |

## 8. 预计影响的文件范围

- **新建 4**：`src/storage.py`（~200 行）、`scripts/migrate_to_sqlite.py`（~100）、`scripts/backup_db.py`（~40）、`tests/test_storage.py`（~150）
- **修改 4 源**：`src/analyzer.py`（三函数内部重写，±80）、`web/app.py`（±50）、`daily_report.py`（+8）、`src/config.py`（注释级 +5）
- **修改测试**：`tests/conftest.py` + 14 个既有测试文件的 patch 点迁移（`test_analyzer / test_web / test_context / test_merge_history / test_phase6a / test_phase6b / test_phase7 / test_phase8 / test_phase12 / test_phase15 / test_phase18 / test_phase24 / test_phase25 / test_phase27 / test_us_sector` 中实际触及者）
- **配置/文档**：`.gitignore`（+3 行）、`docs/architecture.md`、`AGENTS.md`、`docs/pitfalls.md`、`docs/commands.md`
- **运行时生成物**：`data/marketpulse.db`（gitignore）、`data/backup/history_YYYY-MM.json`（入库）
- **预计不动**：`src/reporter.py`（D4 修正）、`src/fetcher.py`、`src/alerter.py`、`src/git_ops.py`、`web/templates/index.html`、`web/static/*`、`snapshot_report.py`、`opening_analyzer.py`

## 9. Done When（对齐 PRD 验收，含修正）

PRD 验收清单全部成立，外加修正项：备份为分月文件（D1）、恢复机制必做且三级降级可用（D2）、API 响应与切换前逐字节一致（D3）、`data/history.json` 切换后不再被任何代码读写（冻结备份）、全量 pytest 绿。
