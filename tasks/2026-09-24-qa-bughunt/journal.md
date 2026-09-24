# journal — QA 走查缺陷修复（2026-09-24 缺陷轮）

- **输入**：本目录 `bug_report.md`（16 条缺陷 + 7 项需求缺失）；**方案**：本目录 `plan.md`（架构师）。
- **执行者**：逐批实施 + 链路级回归测试；每批跑验证命令、更新 `plan.md` §9 看板 ☐→✅、把证据写回本文件。
- **基线**：`pytest tests/ -q` → **774 passed / 41s**（缺陷全在覆盖外）。
- **数据自保**：开工前 `cp data/marketpulse.db data/marketpulse.db-pre-b0`（286720 B / 2718 行 / 272 日期，
  事件表 103 行）；`.gitignore` 已加 `data/*.db-pre-*` 与 `data/*.corrupt-*`（防留档副本被 auto-push 带上线）。

---

## B0 紧急止血（P0）— 已完成

### 改动

| Bug | 文件 | 改动要点 |
|---|---|---|
| 001 | `src/analyzer.py`、`src/storage.py` | 自愈分支重写：锁/忙（`OperationalError` + `locked`/`busy`）→ 退避重试 `_LOCK_RETRY_DELAYS=(0.2,0.5,1.0)`，**绝不重建**；真损坏（`PRAGMA integrity_check` 非 ok）→ `os.replace` 改名留档 `<db>.corrupt-<ts>`（含 `-wal/-shm`）后重建；改名失败 ⇒ 放弃重建并抛出；其它 `DatabaseError` ⇒ 原样抛出。storage 侧补 `is_lock_error`、`_connect` 显式 `PRAGMA busy_timeout=10000`、`_count_rows_strict`（`restore_if_empty` 改用它 ⇒ **锁不再等于"空库"**，不会往非空库灌备份） |
| 002 | `src/config.py`、`src/settings_store.py` | 读侧透传 `cost`（旧实现重建条目时只留 symbol/label）；写读收敛到同一份规则：`config.normalize_watchlist_cost` / `watchlist_cost_provided` / `WATCHLIST_LIMIT`（`settings_store.WATCHLIST_MAX` 改为引用它） |
| 003 | `src/settings_store.py`、`src/config.py` | 写侧 float 校验加 `isfinite`；新增 `_dumps_strict`（`allow_nan=False`，`_non_finite_path` 定位到具体键）；读侧 `_valid_number`/`env_float` 拒非有限（`Infinity` 阈值 ⇒ 回退内置默认） |
| 004 | `web/app.py` | `_authorized` **整个函数体**包进 try + 两侧统一 `encode("utf-8")` 比较（非 ASCII 口令不再 500） |
| 010（顺带） | `src/config.py` | `ENV_MAP` 补 `ALERT_THRESHOLD_SZ`（SCHEMA 有、env 漏 ⇒ 静默失效） |
| 007 读侧半（顺带） | `src/config.py` | `_read_json` 改捕 `(ValueError, OSError)`（`UnicodeDecodeError` ⊂ `ValueError` ⇒ 坏字节 config 不再拖垮四 API + 三入口） |

### 验证（实际跑过）

```text
pytest tests/ -q                      → 812 passed（774 基线 + 38 条新回归，零新增红）
pytest tests/test_storage.py::TestBug001LockIsNotCorruption tests/test_settings_store.py tests/test_config.py tests/test_web.py -q
                                      → 259 passed（分层跑通）
```

**人工复现（真实锁 + 真实 uvicorn，`%TEMP%\mp-b0-repro.py`，结果 ALL PASS）**：

| 路径 | 结果 |
|---|---|
| ① 另一连接持有**真·写锁** 1.5s 后 `append_history` | 写入成功、等待 1.54s（退避重试生效）；日期集合 `2026-09-00/01/02/03` 全在、`gspc=[0.5,1.0,2.0,3.0]` 未丢；库文件存在、**无 `.corrupt-*`**、未删库 |
| ①′ 锁**持续**不放（v1 实测） | 4 次尝试后抛出、耗时 46s（= 4×busy_timeout 10s + 1.7s 退避），数据原样、无留档 —— 设计内的最坏情形 |
| ② `POST /api/settings {watchlist.stocks:[… cost:100.0]}` | 200；响应值 / 磁盘 `config.json` / `GET /api/settings` 三处都带回 `cost: 100.0` |
| ③ `POST {"alert.vix": 1e999}` | 400 `alert.vix 需为有限数字（不接受 Infinity/NaN）`；文件字节不变 |
| ④ 非 ASCII 凭据（服务端口令 `密码123`） | 正确口令 200 / 错口令 401 / 无凭据 401（旧实现 500） |

### B0 遇到的问题（含 2 个真实取证教训）

1. **v1 复现脚本两个自带 bug**（不是产品缺陷）：① sqlite 连接有线程亲和性，持锁线程里用另一线程创建的连接 commit 直接抛 `ProgrammingError` ⇒ 锁永不释放，反而**证明了**"锁持续时抛错且不删库"；② 把 uvicorn 日志丢进 `DEVNULL` 导致「鉴权没生效」看不到原因 —— 收 stderr 后发现根因是**环境里已有 `MP_AUTH_DISABLED=1`**（QA 会话留下的），`httpx` 客户端全 200 是 fail-open，不是 bug。**下次**：起真实服务前先 `env.pop("MP_AUTH_DISABLED")`。
2. `json.dumps(..., allow_nan=True)` 是默认值 —— 只要校验链有一处漏 `isfinite`，非法字面量就会落盘；因此**校验 + 序列化两道闸**都要有（第 2 道用 `allow_nan=False` 并在错误里指出是哪个键）。
3. 长表形状陷阱：`append_history` 一次写 **10 个符号行**，断言"行数 == N"会误判；测试一律断言**日期集合**或按 symbol 过滤。

---

## B1 脚本与持久化安全（P1/P2）— 已完成

| Bug | 文件 | 改动要点 | 证据 |
|---|---|---|---|
| 005 | `scripts/migrate_to_sqlite.py` → `tasks/2026-09-24-qa-bughunt/legacy/`、`docs/commands.md` | 归档 + 退役护栏：原实现逐行保留为 `_legacy_*`（仅存档），新 `main()` **不解析参数、无条件拒绝**（log.error + stdout + `return 1`）；`docs/commands.md` 的 migrate 条目换成「已归档，勿再执行」并写明「没有 `--dry-run`」 | 直接调 `_legacy_migrate`（原实现）于 3 行 tmp 库 → **3→10 行**（坐实 `DELETE FROM history` + 旧 JSON 重灌）；归档 `main()` 返回 1 且目标库行数不变 |
| 005b | `scripts/backup_db.py` | `export_monthly_backups` 包 try/except：失败 `log.error` + `return 1`，成功/空库语义不变 | `tests/test_scripts.py` 4 条 |
| 006 | `src/alerter.py` | 写盘前用 `_read_existing_blocks` 读回同 `(date,type)` 的既有块，按 symbol 合并（既有顺序保留、同 symbol 以本次渲染为准、新块追加），块外的内容（分隔符/尾注）收进 fragments 原样保留；`pending` 为空仍**早退不写文件**（幂等） | 把 `_read_existing_blocks` 换成 `({},[])`（等价旧行为）→ 同日两次 run 只剩 1 块、MOVE 丢；修复后 2 块且 MOVE 保留（`tests/test_alerter.py` 25 passed） |
| 014 | `src/settings_store.py` | `_backup_stamp()`（秒+9 位纳秒+进程序号，字典序=时间序）；`_unique_tmp()` 用 `tempfile.mkstemp(dir=同目录)` + `os.close(fd)`；`_atomic_write` 先序列化再建 tmp、失败 unlink 后 re-raise | 换回固定名模拟旧实现 → 两次 `os.replace` 源同名；修复后两个唯一名、备份名唯一（`tests/test_settings_store.py` 27 passed） |
| B1-4a | `src/storage.py` | `export_monthly_backups` 追加 `econ_events_YYYY-MM.json`（两表并进同一文件；当月覆盖 / 历史月冻结 / 缺历史月自愈；失败只 log）；`restore_if_empty` 在 history 之前按同规则恢复事件表（**仅空表触发**、幂等、`_count_econ_rows_strict` 判空、坏文件跳过）；恢复用整行 `INSERT … ON CONFLICT`（保留值层与 `value_fetched_at` 原样，不复用会刷新时间戳的 upsert） | `tests/test_storage.py` → 43 passed（新增 7 例） |
| B1-4b | `src/git_ops.py` | `auto_commit_push` 在 `_commit` **之前**调 `_data_guard(root)`：① `storage.wal_checkpoint`；② 行数守卫 vs `git show HEAD:data/marketpulse.db` 临时副本（HEAD>0 且当前==0 → 拒绝；HEAD>200 且当前 < HEAD×0.5 → 拒绝；事件表同「HEAD 有行、当前 0 行」拒绝）；③ 放行侧只 warning（DB 不存在 / HEAD 无该文件 / `git show` 失败 / 任何未预期异常都放行 —— 护栏是可用性部件，绝不卡死推送）；④ 拒绝 ⇒ `log.error` 打印两边行数 + 返回 False 且**不执行** `git add/commit/push` | `tests/test_git_ops.py` → 22 passed（8 条行为 + 8 case 边界参数化，真 git 临时仓库 + bare origin）；`tests/test_phase26.py` → 20 passed（白名单/pathspec 护栏未回归） |

**B1 期间发现并修掉一个 B0 引入的回归（重要）**：B1Guard 的真实数据探针发现
「`web/app.py` 启动只调 `restore_if_empty()`、不调 `init_db()`」，而 B0 把该函数的第一步改成
`_count_rows_strict` + `except DatabaseError → return 'db'` 后，把「**DB 文件不存在** ⇒ `_connect`
建出空文件 ⇒ `no such table: history`」也归进了"本轮不动作" ⇒ **恢复链静默失效**（实测
`outcome='db'`、恢复 0 行；B0 之前这条路能恢复）。
修复（Main）：分流改成 **锁/忙 ⇒ 跳过本轮；其余 `DatabaseError`（缺表/缺文件/损坏）⇒ 照旧走恢复链**，
回归测试 `tests/test_storage.py::TestBug001LockIsNotCorruption::test_missing_db_file_still_triggers_restore`
（修前实测 `assert 'db' == 'backup'` 红，修后绿）。**教训**：给容错加守卫时，必须把「已知的良性错误」
逐一枚举并保留原路径 —— 只写"非 X 则跳过"会把 X 之外的一切（含正常路径）一起静默掉。

---

## B2 契约与容错（P2）— 已完成

| Bug | 文件 | 改动要点 | 证据 |
|---|---|---|---|
| 007 | `web/app.py` | 新增 `_read_text(path)`（`read_bytes().decode("utf-8", errors="replace")`，OSError→None），本模块三个「读文本 + `json.loads`」读盘点统一改用它（`_read_context_file` / `_parse_alert_file` / `_load_news`）；坏字节在解码层消解，`json.loads` 只捕 `JSONDecodeError`。全模块已无裸 `read_text(encoding="utf-8")`（grep 复核） | 反证脚本（临时恢复旧读法 + `\xff` 的 `news.json` 打 `/api/news`）：新 200 / 旧 `UnicodeDecodeError` ⇒ 旧实现确实 500、测试非假绿 |
| 009 | `web/static/app.js`、`web/templates/index.html`、`web/static/style.css` | `renderWatchlist()` 消费 `payload.stale` → 写 `#watchlist-stale`（h2 内独立 span，`hidden` 默认）+ 文案「⚠ 取数失败，展示上次快照（as_of）」（无 `as_of` 则不写括号，不编造时点） | 浏览器实测：拦截 `/api/watchlist` 返回 stale 态 → 角标可见、卡片仍渲染 11 行；无 stale 时 `display:none`；1920/1280 档卡高与对照完全一致（528/480px）、无横向溢出 |
| 012 | `web/app.py` | `_CN_QUOTES_TIMEOUT=15` + `_load_cn_quotes_limited()`（daemon 线程 + `join`，范式照 `src/fetcher.fetch_sector_heat`）；`/api/cn/quotes` 走限时包装，超时/异常 → 空态（`as_of:None` + `failed` 三项），HTTP 恒 200 | 实测冷启动 14.85s（Yahoo CNY=X 403 轮换失败 4.46s + 中债 `bond_china_yield` 12.60s）；限时器实测（`sleep(60)` + 阈值 0.3s）→ 200 / 0.38s / 空态 |
| 008 | `web/static/settings.js`、`web/static/timeline.js`、`web/static/backtest.js` | settings 页绑 `#refresh-btn` → `load()`（死按钮变活）；`/timeline`、`/backtest` 各自把 `#topbar-date` 写成数据日（`p.as_of`，取不到就保持 `—`）。**`/settings` 有意保持 `—`**（该页没有数据日字段，不造假日期，注释写明） | 浏览器实测：settings 点刷新 → `/api/settings` 请求数 2→3；`/timeline`、`/backtest` 的 `#topbar-date` = `2026-09-24`（= 各自 `as_of`） |
| 016 半 | `tests/test_web.py` | `_wl_payload` docstring 标注「纯函数级用例，链路级覆盖见 `test_settings_cost_persists_and_shows_pnl`」；新增 9 条 B2 链路/行为锚点用例 | `tests/test_web.py` → **156 passed**（基线 147 + 9） |

**偏离 plan 一处（已论证）**：plan §4 写「三个子页 `#topbar-date` 不等于 `—`」，但 `/settings` 的数据源
`/api/settings` 里**没有任何数据日字段** ⇒ 按"没有可取的数据日就保持 `—`、不造假"处理，`settings` 保持 `—`，
测试只断言 `timeline`/`backtest` 的写入分支。

### 决策落定 / 观察项

1. ✅ **已定档（2026-09-24 用户决定）**：`/api/cn/quotes` 取数上限 **15s → 20s**。理由：实测冷启动
   **14.85s**（Yahoo CNY=X 403 轮换失败 4.46s + 中债 `bond_china_yield` 12.60s）正好压在 15s 上，
   上游再慢 0.2s 就会把"本来会成功"的响应降级成空态；20s 与中债自身 `fetch_bond_yield_curves(timeout=20)`
   同量级（语义 = "最多等一次完整取数"），前端 `macro_cn.js` 30s 留 10s 余量。
   落地：`web/app.py::_CN_QUOTES_TIMEOUT = 20`（注释写明定档理由）+ 前端注释同步 + 新增参数护栏测试
   `tests/test_web.py::test_cn_quotes_timeout_parameter_stays_above_measured_cold_start`
   （断言 上限 ≥ 中债内层 timeout、且 上限×1000 < 前端 fetch 毫秒数）。
   **证伪**：把上限改回 15s → 该用例 **失败**（`15 >= 20` 不成立），改回 20s → 通过 ⇒ 护栏非空洞。
   `pytest tests/` → **857 passed**（+1）。
2. **事件表按月备份 ≈ 60 个小文件**：`data/backup/econ_events_*.json` 覆盖 2021-01 … 2027-12（事件表含
   **未来日程**，所以月份跨度远大于 history 的 13 个月），多数只有 1 行；且按 history 的「历史月冻结」
   纪律，**未来月份的文件在"其月份到来之前"不会刷新**（如 `econ_events_2027-12.json` 今天写一次就冻结，
   要等 2027-12 才更新）。恢复链按月份升序合并，功能上没问题；可选的替代：未来月不冻结（`m >= 当月` 就覆盖）
   或整表存单文件（`econ_events_all.json`）—— 两个都要改 plan 的命名/纪律，故留给你决定。

### 附：B1-4a 的真实产出（`python scripts/backup_db.py`，2026-09-24 10:28）

`data/backup/` 新增 60 个 `econ_events_YYYY-MM.json`（样本 `econ_events_2026-09.json` 键：`export_date/month/
record_count/records/news_record_count/news_records`，9 月 8 条事件 + 6 条叙事），`history_2026-09.json` 当月覆盖更新。

### 生产数据零改动的证明

`data/marketpulse.db` md5 **`bbd45076ec2b800fb9340cc355497532`**（B0 动手前 09:41 与全部批次跑完后
相同，286720 B）；行数 2718 / 事件 103；测试期间 `git status -- data/` 始终无 `.db` 变更、无 `*.corrupt-*` 残留
⇒ 开工前的 `data/marketpulse.db-pre-b0` 副本已删除（验证后确认无需保留）。

---

## B3 界面与文档 / B4 卫生与测试（P2/P3）— 已完成

| Bug | 文件 | 改动要点 |
|---|---|---|
| 015（D-2） | 仓库根 + `tasks/…/legacy/README.md` + `.gitignore` | 删除 `seed_history.py`、`seed_history_market.py`、`_dbg/`（3 个 tracked 文件）、`_dbg_hist.json`、`web_uvicorn.log`、`_phase5_run.log`、`task brief.md`；`app.py`（旧入口）、`render.yaml` 移档 `legacy/` + README 写明每个文件的退役原因；`*.log` 已在 `.gitignore`（未重复追加） |
| 013 | `AGENTS.md`、`docs/architecture.md`、`docs/commands.md`、`docs/system-overview.md` | `days` 上限一律以代码为准 → **3650**（`AGENTS.md` 原写 365、`commands.md` 原写 366→422、`architecture.md` Web 行原写 365）；新增 `tests/test_doc_consistency.py`：真值取自 `inspect.signature(web.api_history)` 的 `Le(le=3650)`（pydantic v2 下 `le` 在 `FieldInfo.metadata` 里），**文档漂移即红** |
| 011（D-1） | `.gitignore`、`docs/architecture.md`、`docs/system-overview.md` | 注释改成事实：`data/marketpulse.db` **入库 = 线上数据源**（那行 ignore 对 tracked 文件是惰性的，只保留并注明）；`-wal/-shm` 真排除 ⇒ 提交前必须 `wal_checkpoint`（现由 B1-4 护栏强制）；备份 = `data/backup/{history,econ_events}_YYYY-MM.json`，两者都必须入库；G6（仓库根残留）标记**已解决**（含精确位置与核对命令） |
| 016 | `tests/test_backtest.py`、`tests/test_phase26.py`、新建 `tests/test_test_hygiene.py` | 删除两对被遮蔽的重复块：`test_backtest.py` 40 行（2 组）、**额外** `test_phase26.py` 62 行（`_real_git` + `real_repo` + 两条真 git 用例，319-380 整段 == 381-440 ⇒ 前段永不执行）；元测试用 `ast` 按 `(作用域, 函数名)` 检测同文件重名（正则会把注释里的 `def test_x` 误算），下钻 `if/for/while/with/try` 但不进函数体；**证伪**：临时放一份双定义文件 → 按预期红、两个不同类各自同名 → 不误报 |

顺带（Main 补的收尾）：`scripts/backfill_history.py` 两处 docstring 的 `seed_history.py` 引用标注为已删除；
`docs/pitfalls.md:61/243` 同类引用同步；`docs/system-overview.md:243`（部署平台仍列 `app.py`/`render.yaml`）
与维护脚本清单里的 `migrate_to_sqlite.py` 同步为归档状态。

---

## 全量验收（Main，2026-09-24 收尾）

```text
pytest tests/ -q -p no:cacheprovider                    → 856 passed, 0 failed（基线 774；+82）
verify_ui.py（清环境后）                                  → PASS 710 / FAIL 0 / SKIP 0 → ALL PASSED
B1-4 护栏演练（脚本入口 python -m scripts.auto_commit_data，真 git 临时仓库 + bare origin）
  ├ ① HEAD 300 行 + 工作区清空     → 退出码 1、HEAD 未前进、data/ 仍未提交、远端未收到 → PASS
  ├ ② 正常新增 3 行                → 退出码 0、HEAD 前进、已 push；**提交进去的副本含 303 行**
  │                                  （证明护栏的 wal_checkpoint 真在提交前生效）      → PASS
  └ ③ 事件表被清空（history 正常） → 退出码 1、HEAD 未前进                              → PASS
反证（修前会红）
  ├ BUG-002 链路：cost 读侧丢弃（旧）→ 本批新增用例红；修后绿
  ├ BUG-006：`_read_existing_blocks` 换回旧行为 → 同日重跑只剩 1 块、MOVE 丢
  ├ BUG-007：旧读法 + `\xff` news.json → 500（新：200 空结构）
  ├ BUG-013：文档退回 365/366→422 → `tests/test_doc_consistency.py` 红
  └ 恢复链回归：`test_missing_db_file_still_triggers_restore` 修前实测 `assert 'db' == 'backup'` 红
生产数据零改动：`git status -- data/` 空、`data/marketpulse.db` md5 前后一致、无 `*.corrupt-*` 残留
```

### 本轮新增的两个「环境/夹具」级发现（已写进 `docs/pitfalls.md`）

1. 🔴 **父进程残留的 `CONFIG_PATH` 会静默换掉验收用的配置**：`verify_ui.py` 起 uvicorn 时继承
   `os.environ`（只 pop `MP_AUTH_DISABLED`）⇒ 我的会话环境里残留了 `CONFIG_PATH=<pytest tmp>/none.json`
   + `MP_SKIP_RESTORE=1`，门禁于是跑出 **8 条红**（自选列表 `hidden=true` 引发 `自选列表可见且有行` /
   `F-1b` / `PF-2` / `PF-4` / `A-4` / `A-5` 级联）。**清掉这三个变量后同一份代码 PASS 710 / FAIL 0**。
   教训：门禁红之前先确认环境干净（判据：`web.app._load_watchlist()` 是否 `hidden=True, stocks=0`）。
2. ⚠️ **`git add <dir>` 对无 tracked 文件的目录 fatal**：临时仓库演练时 `git add data context alerts`
   报 `pathspec ... did not match any files` ⇒ 整条提交失败。生产仓库没暴露是因为 `context/`、`alerts/`
   真有 tracked 文件；顺带用 `git check-ignore` 纠正了 `AGENTS.md` 里「`context/`/`alerts/`/`data/alerts.log`
   被 gitignore 排除」的三处旧说法（实际：`*.log` + `!data/alerts.log` 是**反排除**，三者都会随 auto-push 入库）。

---
