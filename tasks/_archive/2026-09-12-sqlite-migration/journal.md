# Journal — 数据存储升级（JSON → SQLite，三十一期）

- 日期：2026-09-12
- 角色：编码执行者；按 `plan.md`（架构师，含 PRD 修正清单 D1-D9）实施；用户转发方案即视为 §2 确认
- 基线：pytest 471 passed（开工时点，含上任务用例）

## 目标

历史行情 `data/history.json` → SQLite `data/marketpulse.db` 长表 (date, symbol, value, change)，
脚本与 Web 直读 SQLite（直接切换无双写），永久保留（裁剪废止），`/api/history` 支持日期范围
（≤200ms），备份按月归档入库，Web 启动三级恢复（D2 必做）。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `src/storage.py` | 新建 ~230 行 | 建表（PK date+symbol + idx）/WAL/`upsert_history_rows`（preserve\|overwrite 双模式）/`query_history`（date 升序、symbols/范围过滤、损坏→[]）/`rows_to_records`/`records_to_rows`/`get_date_range`/`count_rows`/`export_monthly_backups`（当月覆盖、历史月冻结、缺失自愈）/`restore_if_empty`（三级降级）/`wal_checkpoint`；写入口护栏（日期格式 YYYY-MM-DD、symbol 小写） |
| `scripts/migrate_to_sqlite.py` | 新建 | JSON→SQLite 一次性迁移：单事务、幂等（重跑 DELETE+重灌）、逐值全量比对、`--db` 演练、checkpoint 收尾 |
| `scripts/backup_db.py` | 新建 | `export_monthly_backups` 薄 CLI（D6：核心在 src，scripts 只包装） |
| `src/analyzer.py` | 重写历史层 | 三函数签名不变：`load_history`=rows_to_records(query)；`append_history`=全 10 键 upsert（preserve=merge_existing）；`merge_history`=非 None 子集 upsert(preserve)；`_upsert_history_rows_selfheal`（DB 损坏删库重建重试一次，同旧 JSON 坏文件重建）；HISTORY_MAX 废止（常量保留） |
| `web/app.py` | ±45 行 | `_load_history_raw` 改 storage；`api_history` 加 `start_date/end_date`（pattern 校验、显式范围优先）+ days 上限 365→3650（D9）；startup `_restore_history_db`（MP_SKIP_RESTORE=1 跳过）；HISTORY_FILE 绑定移除 |
| `daily_report.py` | +7 行 | generate_context 后、auto_commit_push 前调 `export_monthly_backups()`（try/except，同一 auto-commit 携带备份） |
| `.gitignore` | +5 行 | db/-wal/-shm 排除；data/backup/ 加「必须保持入库」注释 |
| `src/config.py` | 注释 | retention_days 标 deprecated |
| `tests/conftest.py` | +35 行 | `MP_SKIP_RESTORE=1` 护栏；`tmp_db` fixture + `_TmpDb.seed(records)` 辅助 |
| `tests/test_storage.py` | 新建 28 条 | init 幂等/WAL/双模式 upsert/NULL 往返/过滤/损坏 DB/长宽互转/键同步锁定/按月备份冻结+自愈/恢复三级降级 |
| `tests/` 12 文件 | patch 迁移 | `HISTORY_FILE` 死补丁 → `st.DB_PATH` tmp patch / `tmp_db.seed()`；test_rolling_90×2 → permanent_retention_no_trim；test_date_stringified → malformed_date_rejected |
| 文档 | 收尾 | architecture（模块行+决策行）/AGENTS（storage 行+data 行）/pitfalls（6 条）/commands（2 命令） |

## 验证结果（全部实际运行）

| 项 | 结果 |
|---|---|
| S0 备份 | `%TEMP%/mp-sqlite-migration/history.backup.json` SHA256 与源一致 |
| S1 | `test_storage.py` **28 passed** |
| S2 迁移 | 演练 + 正式各一次：**263 记录 → 2630 长行，逐值比对一致**，0.06s |
| S3 切换 | analyzer 从 DB 读出 263 条（2025-09-11..2026-09-11）值正确；**日报闭环 diff = 空**（SQLite 输出与 JSON 时代逐字节一致） |
| S4 | test_web 62 passed；运行时：`?days=30` **63ms**（≤200ms）、`start_date/end_date` 8 月 21 交易日过滤正确、`days=3650` 返回 261 交易日 |
| S5 备份 | CLI 两次：首次 13 个月全 written、二次历史月 frozen + 当月覆盖；daily 真跑备份接线生效；data/backup 未被 gitignore |
| S6 恢复 | 删 DB → 启 web → 259 交易日恢复（来源 backup，逐值抽查过）；移走备份 → 旧 JSON 兼容导入 ✓；全缺失分支单测锁定 |
| 回归 | `pytest tests/` **498 passed**（471 基线 + 28 storage - 1 合并 + 若干改名）；backtest 用冻结 JSON 正常（D8 标注缺口）；verify_ui **ALL PASSED** |

## 事故记录（已恢复，最重要的一节）

**全量 pytest 在 patch 迁移完成前污染真实 DB**：analyzer 切 SQLite 后、旧 `HISTORY_FILE` patch
变死补丁，期间的全量 pytest（32 failed 那轮及 496 passed 那轮）里，test_phase12/18/24/us_sector
等未迁移用例的 `dr.main()`/`generate_context` 链路向**真实 data/marketpulse.db** 写入了测试数据
（43 个垃圾日期 ×10 行，多为测试 fixture 的周末日期，部分覆盖了真实值）。发现信号：按月备份行数
合计 3140 ≠ 迁移行数 2629 + 当日增量。恢复：用迁移前 JSON 备份（%TEMP%，SHA256 已验）整体
覆盖回 DB（preserve=False）+ 删非 JSON 日期 → **263/2630 逐值一致** → 删 backup 重导 13 文件。
教训：①迁移类任务的「analyzer 切换」与「测试 patch 迁移」必须同批完成后再跑全量测试；
②切换后立即核对 DB 日期分布（畸形/周末/行数异常 = 污点信号）；③迁移前备份放在能随时
覆盖回写的地方是最后防线（本次靠它闭环）。

## 其他问题与偏差

1. **plan「conftest tmp 环境无快照文件」不成立**（同上任务）：DATA_DIR 不被 conftest 隔离 →
   fixture 默认隔离 + 测试内覆盖，两段式。
2. **旧 JSON 断言的语义映射**：test_rolling_90×2 → permanent_retention_no_trim（裁剪废止）；
   test_date_stringified → malformed_date_rejected（写入口格式护栏优先于旧宽容行为——真实库
   曾因 20260903 脏行炸 web）；test_corrupt/non_list 合并为 corrupt_db；test_non_list 无 SQLite 对应。
3. **append_history(merge_existing=True) 的语义微强化**：旧实现「record 中缺失的键」会被置 None
   （丢失），新实现全键展开 + preserve → 缺失键保留旧值。生产调用恒传全 10 键，无实际影响。
4. **uvicorn 下 marketpulse logger 的 INFO 不可见**（root 无 handler，lastResort 只出 ≥WARNING）：
   启动恢复的 INFO 日志在 uvicorn 下看不到，取证用直接调用或看 DB 状态；如需 Railway 可见，
   后续给 web.app 配 logging handler。
5. **probe 自伤两连**：DPR/像素普查类脚本连踩阈值未随尺寸重标、px 变量复用、clip 参数名
   （width/height）等错——取证的结论必须先确认取证工具自身正确。

## 下次注意什么

- 大规模「patch 点迁移」任务：先跑全量测试拿失败清单，按失败分布逐文件迁（比按 grep 清单盲改快）；
  迁移完成后必须再跑一次全量，确认没有"碰巧通过"的用例在读写真实数据。
- 行级存储切换：upsert 双模式（preserve/overwrite）+ NULL 语义 + 全键补 None 是行为等价的三个支柱，
  单测要逐条对应旧行为。
- 直接切换（无双写）任务：S0 的仓库外备份 + 日报闭环 diff 为空是回退与验收的两条底线。
