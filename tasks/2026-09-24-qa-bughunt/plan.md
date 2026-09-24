# plan — QA 走查缺陷修复（2026-09-24 缺陷轮）

- **任务档**：`tasks/2026-09-24-qa-bughunt/`（输入：本目录 `bug_report.md`，16 条缺陷 + 7 项需求缺失）
- **角色**：架构师（本文件为方案；**未改任何项目文件**）
- **基线**：`pytest tests/ -q` → **774 passed / 41s**（缺陷全在覆盖外）
- **目标**：把「数据不可逆丢失 / 配置与鉴权静默失效 / 功能整块不可用」三类先清零，再收契约与卫生；每条缺陷都要有**链路级回归测试**（不再靠绕过生产入口的假绿）。

---

## 0. 独立复核结论（架构师逐条读码验证）

报告对 5 条 P0/P1 的判断**全部成立**，代码级证据如下；另补 4 处补充/修正。

| 编号 | 报告结论 | 我的复核 | 决定性证据 |
|---|---|---|---|
| BUG-001 | 瞬时锁 → 删库 | ✅ 成立 | `src/analyzer.py` 自愈分支 `except sqlite3.DatabaseError`；而 `sqlite3.OperationalError`（"database is locked"）**是 `DatabaseError` 的子类** ⇒ 锁错误落入「损坏」分支；随后 `p.unlink()` 无 try ⇒ Windows `PermissionError` 逃出 |
| BUG-002 | cost 全链路断 | ✅ 成立（两侧都断） | 读侧 `src/config.py:_valid_watchlist` 重建条目 `stocks.append({"symbol": sym, "label": label})` **丢弃 cost**；写侧 `src/settings_store.py:_validate_stocks` 反而**支持** cost（`cost_f = float(cost)` + `>0`）⇒ 读写不对称 |
| BUG-003 | Infinity 入盘 | ✅ 成立 | float 分支只校验 `gt/min/max`（无 `math.isfinite`）；`_atomic_write` 用 `json.dumps(data, ensure_ascii=False, indent=2)`（`allow_nan` 默认 True） |
| BUG-004 | 非 ASCII 凭据 500 | ✅ 成立 | `_authorized` 的 `try` 只包 `b64decode().decode()`；`hmac.compare_digest(u, _auth_user())` 在 `try` 之外，str 含非 ASCII 时抛 `TypeError`（CPython 已知语义） |
| BUG-005 | 迁移脚本清空生产库 | ✅ 成立 | `scripts/migrate_to_sqlite.py` `executescript(... DELETE FROM history; ...)` + `--db`/`--json` 均有 `default=`；`docs/commands.md` 列为常规命令 |
| BUG-006 | 告警文件被覆盖 | ✅ 成立 | `src/alerter.py:run_alert_checks` 写盘只用 `pending`：`path.write_text("\n".join(render_alert(a,...) for a in pending))` |
| BUG-007 | 非 UTF-8 → 500 | ✅ 成立 | `web/app.py:_load_news` `except (json.JSONDecodeError, OSError)`；`UnicodeDecodeError ⊂ ValueError` 不被捕获 |
| BUG-010 | ENV_MAP 缺 SZ | ✅ 成立 | `ENV_MAP` 有 VIX/VXN/MOVE/GSPC/IXIC/SH/CYB，**无 `ALERT_THRESHOLD_SZ`** |
| BUG-013 | days 上限文档漂移 | ✅ 成立 | `web/app.py:1005` `Query(30, ge=1, le=3650)`（注释写明 D9 放宽）；`AGENTS.md` 仍写 365、`docs/commands.md` 仍写 366→422 |
| BUG-016 | 测试假绿 + 死代码 | ✅ 成立 | `tests/test_backtest.py`：`test_pure_stats_have_single_implementation_in_src_backtest` 在 137 与 177 各一份、`test_scripts_entry_keeps_cli_and_render` 在 162 与 202 各一份 ⇒ **同名后定义遮蔽前者，前两块永不执行** |

### 补充与修正

- **补 A（BUG-002 前端半边已确认）**：`web/static/settings.js:renderStocks()` 行模板只有 `data-wl="symbol"` / `data-wl="label"` 两个输入，**没有 cost 输入**；但 `state.stocks.push({symbol:"",label:"",cost:null})` 与 `collect()` 里的 `var c = (s.cost == null) ? "" : ...; item.cost = Number(c)` **已经就位** ⇒ 前端只缺一个输入框 + 一个 `data-wl="cost"` 绑定（`data-wl` 的 change 监听是通用的，无需新增逻辑）。
- **补 B（BUG-003 爆炸面比报告更大）**：能写入 `Infinity` 的键 = `SCHEMA` 中**所有只带 `gt` 不带 `max`** 的 float 键 —— `alert.{vix,vxn,move,gspc,ixic,sh,sz,cyb,k_factor}`（9 个）+ `analysis.{vix.peaceful,vix.panic,move.normal,move.tight}`（4 个）⇒ 不是「VIX 一个标的被静默关闭」，而是**全部标的阈值 + 动态阈值 k 因子**可被一次请求同时废掉。`watchlist.corr_high_threshold` 带 `max:1.0` 反而挡住 Infinity（可作为「加 max 即安全」的现成对照）。
- **补 C（报告「待确认」项①已判定）**：`web/app.py` 的 `_cn_econ_raw[k] = raw.get(k)`（失败腿会**覆盖**上一次成功值）⇒ 降级结果是 None / 计入 `failed`（前端「数据暂缺」），**不是错值**；代价是「最后一次已知良好值」也丢，但被 6h payload 缓存 + 「失败不写 ts、下轮重试」兜住。⇒ 现状**可接受**，修复不属于本计划；若要做，按「失败不覆盖已有非空值」单独立项（行为变更）。
- **补 D（BUG-011 的放大链已坐实）**：`scripts/auto_commit_data.py` 的 docstring 明写它刻意调用 `auto_commit_push`（**commit + push 两件事**），白名单含 `data/` ⇒ 「删库 → 空库被提交并推送」是**可执行的真实路径**，不是理论风险。

---

## 1. 根因归类（16 条 → 4 个家族）

### F1 「容错边界画错」（BUG-001 / 003 / 004 / 005 / 007）— 最危险的一族

同一个模式反复出现：**该宽的地方过宽、该窄的地方过窄**。

| 形态 | 表现 | 本族成员 |
|---|---|---|
| 异常族按「父类」捕获 | `DatabaseError` 吞掉 `OperationalError`（锁）→ 走破坏性恢复 | BUG-001 |
| 异常族按「枚举」捕获 | `(JSONDecodeError, OSError)` 漏掉 `ValueError` 家族 → 500 | BUG-007 |
| `try` 边界画漏 | 只包解码、没包比较 → 500 违反自己写的「绝不 500」契约 | BUG-004 |
| 校验漏域 | `gt/min/max` 不含「有限性」→ 非法值穿透到磁盘 | BUG-003 |
| 危险默认值 | 破坏性操作（`DELETE`）配 `default=` ⇒ 裸跑即事故 | BUG-005 |

**统一修法原则**（写进 `docs/pitfalls.md`）：
1. **破坏性恢复只对「可证明不可恢复」的错误开放**（corruption 需 `PRAGMA integrity_check` 或明确的 `malformed`/`not a database`），可重试类错误（locked/busy）走退避重试；
2. **恢复动作本身要留后路**：先 rename 成 `.corrupt-<ts>`，绝不 `unlink` 唯一副本；
3. **容错层不得改变对外契约**：声明「恒 200 / 恒 401」的函数，其 `try` 必须包住**函数体全部**；
4. **数值入盘前先判有限性**（`math.isfinite`），写盘同时用 `allow_nan=False` 做第二道闸；
5. **危险脚本默认安全侧**：目标路径必填 + `--force` 二次确认 + `--dry-run` 真的只打印。

### F2 「写读两侧不对称」（BUG-002 / 010）
写侧（`settings_store`）比读侧（`config._valid_watchlist`）更严更能干，且**两处各写一遍**规则（cost 的「有限且 >0」、自选上限 20、去重）。⇒ 改法不是「补一行」，而是**收敛成单一事实来源**（`src/config.py` 提供 `normalize_watchlist(raw)`，`settings_store` 复用它做校验，写读同构）。BUG-010 同类：`SCHEMA` 有 `alert.sz`（设置页能改），`ENV_MAP` 却无 `ALERT_THRESHOLD_SZ`（env 改不动）。

### F3 「声明与实现漂移」（BUG-008 / 009 / 011 / 013）
契约写在注释/文档/文案里，但**没有机器强制**：`stale` 字段无人消费、`topbar-date` 无人写入、`.gitignore` 注释与 `git ls-files` 事实相反、`days` 上限三处不同。⇒ 修法：能加断言的加断言（文档值 → 用测试钉住），不能的就把声明删掉（宁可不说）。

### F4 「测试假绿」（BUG-016）
两类：**绕过生产入口**（`test_web.py` 直接注入带 cost 的 dict 调 `_build_watchlist_payload`，跳过 `load_config`）+ **同名遮蔽**（`test_backtest.py` 重复定义）。⇒ 修法：链路级用例从**入口**出发（POST → 读 `load_config()` / `GET /api/watchlist`），并加一条「测试文件内不得有重复函数名」的元测试。

---

## 2. 分批计划

> 批次内可并行；批次间串行（B0 完成前不动 B1 的写路径）。

### B0 紧急止血（P0：数据 + 功能不可用）

| Bug | 文件 | 改法要点 |
|---|---|---|
| BUG-001 | `src/analyzer.py` | ① 自愈分支拆两类：`sqlite3.OperationalError` 且消息含 `locked`/`busy` → **重试**（`storage` 侧设 `busy_timeout` + 3 次指数退避），不重建；② 仅当真损坏（`PRAGMA integrity_check` 非 ok）才重建；③ 重建前 `os.replace(db, db + ".corrupt-<ts>")`（含 `-wal/-shm` 一同改名），失败即放弃重建并**抛出**；④ 重建失败后**不得**再吞异常（三入口需感知）；⑤ `unlink`/`replace` 的 `OSError`（WinError 32）单独捕获并记录 |
| BUG-002 | `src/config.py` + `web/static/settings.js` | ① `_valid_watchlist` 透传 cost（`float`、`math.isfinite`、`>0`；非法 → 丢弃该键并 warn）；② 抽 `normalize_watchlist_item()` 供 `settings_store._validate_stocks` 复用（写读同构）；③ `renderStocks()` 行模板加 `<input data-wl="cost" placeholder="成本价（可选）">`（`collect()` 已就绪） |
| BUG-003 | `src/settings_store.py` + `src/config.py` | ① `_validate_one` float 分支加 `math.isfinite`（统一给 `gt/min/max` 前置）；② `_atomic_write` 与 `validate_updates` 的 tmp 写改用 `allow_nan=False`；③ 读侧 `_read_json`/`_merge_valid`/`env_float` 对非有限值回退默认并 warn |
| BUG-004 | `web/app.py` | ① `compare_digest` 两侧统一 `encode("utf-8")`（bytes 版本支持任意字节且仍常量时间）；② **整个函数体**包进 `except Exception: return False`（对齐 docstring 契约）；③ 无凭据/坏头路径不得早退到 500 |

**B0 验收**：新增回归测试（见 §4）全绿 + `pytest tests/ -q` 无新增红 + 三条人工复现路径按报告「复现」步骤走一遍结果翻转（锁不删库 / POST cost 后可读 / Infinity → 400 / 中文口令 → 401）。

### B1 脚本与持久化安全（P1/P2）

| Bug | 文件 | 改法要点 |
|---|---|---|
| BUG-005 | `scripts/migrate_to_sqlite.py`、`docs/commands.md` | 迁移已于三十一期完成 ⇒ **归档移除**：文件移到 `tasks/2026-09-24-qa-bughunt/legacy/migrate_to_sqlite.py`（与 D-2 的留档模式一致），`docs/commands.md` 删掉该命令并注明「迁移已完成、脚本已归档，勿再执行」。若你更倾向保留可跑脚本：`--db/--json` 改必填 + `--force` + `--dry-run` 真只打印 + `DELETE` 前先备份到 `data/backup/history_pre_migrate.json` |
| BUG-005b（补充） | `scripts/backup_db.py` | 收尾统一 `try/except` → 失败 `return 1` + `log.error`（cron 可见），成功才 `return 0`；避免「失败当成功」 |
| BUG-006 | `src/alerter.py` | 写盘前读回同 `(date, alert_type)` 既有块，按 symbol 并集合并后再写（文件多块本就是既有格式） |
| BUG-014 | `src/settings_store.py` | 备份名加微秒（或进程内序号）；tmp 改 `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)`；单 worker 前提（memory #66）下先做「唯一 tmp 名」，文件锁列为可选 |
| B1-4（新增，D-3） | `src/storage.py`、`src/git_ops.py` | 事件表备份/恢复 + 提交前护栏（含强制 `wal_checkpoint`）—— `scripts/auto_commit_data.py` **无需改**（它已按 `auto_commit_push` 的返回值给退出码）。详见下方细则 |

**B1-4 提交前护栏 + 事件表备份（D-3，已确认要做）**

已核实的现状：`src/git_ops.auto_commit_push()` 是**全部推送路径的唯一漏斗**（三入口 + `scripts/auto_commit_data.py` 都经它）；`storage.export_monthly_backups()` 只导出 `history_*`，`restore_if_empty()` 也只恢复 history ⇒ 事件表（`econ_events`/`econ_event_news`）无任何备份/恢复路径。

1. **备份面扩到事件表**（`src/storage.py`）：
   - `export_monthly_backups()` 追加 `data/backup/econ_events_YYYY-MM.json`（按月、当月覆盖 / 历史月冻结，与 history 同纪律），并把报告项行数一并返回；
     **⚠️ 2026-09-24 用户定档：改为单文件 `data/backup/econ_events.json` 全量重写**（事件表含未来日程且每个月都会变 ⇒ 按月冻结既产出 60 个 1 行文件、又让未来月备份停在旧值；空表时不覆盖已有备份）。理由与实测见 `journal.md`。
   - `restore_if_empty()` 在恢复 history 后按同一命名规则恢复事件表（**仅空表触发**，幂等）；
   - 触发点不变（报告链路的 backup 步骤 + `scripts/backup_db.py`）。
2. **提交前护栏**（`src/git_ops.py`，新增 `_data_guard(root) -> tuple[bool, str]`，在 `auto_commit_push()` 的 `_commit` 之前调用）：
   - 第一步 `storage.wal_checkpoint()`：保证 `-wal` 里的新行落进**将要提交的那个 `.db`**（D-1 的纪律由代码强制，不再靠人记得）；
   - 第二步行数守卫：当前 `query_history()` 行数 vs `git show HEAD:data/marketpulse.db` 导出到临时目录的副本行数；
     - `HEAD > 0` 且 `当前 == 0` → **拒绝**（空库上线是 BUG-001 的放大链）；
     - `HEAD > 200` 且 `当前 < HEAD * 0.5` → **拒绝**（骤减多为事故）；
     - 事件表同样按「HEAD 有行、当前为 0」拒绝；
   - 放行条件：HEAD 中无该文件（首次）/ DB 不存在 / `git show` 失败（浅克隆、无 HEAD）→ 记 `warning` 后**放行**（护栏不得把正常推送卡死）；
   - 拒绝行为：`log.error` 打印两边行数与原因，返回 `False`、**不执行** `git add/commit/push`（`scripts/auto_commit_data.py` 因此返回 1，Hermes cron 可见）。
3. **回归测试**：造一个「HEAD 有 300 行、工作区库被清空」的临时仓库 → `auto_commit_push` 返回 False 且 `git status` 与 HEAD 一致；反例（正常新增行）→ 照常提交；`git show` 失败路径 → 不阻塞。

### B2 契约与容错补齐（P2）

| Bug | 文件 | 改法要点 |
|---|---|---|
| BUG-007 | `web/app.py`、`src/config.py` | 统一 `read_bytes()` + `decode(errors="replace")`，或 `except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError)`；断言「坏字节 → 200 + 空结构/默认值」 |
| BUG-009 | `web/app.py`（已产出）+ `web/static/*.js` | 前端消费 `stale`：卡片角标「取数失败，展示上次快照（as_of）」；`stale` 字段与 `as_of` 同处下发（已就绪） |
| BUG-010 | `src/config.py` | `ENV_MAP` 补 `ALERT_THRESHOLD_SZ`；加参数化测试覆盖 SCHEMA 里全部 8 个告警阈值 env（防再次漏项） |
| BUG-012 | `web/app.py` + cn 取数 | `/api/cn/quotes` 复用既有 daemon-thread 限时范式（**上限 20s**：plan 原写 15s，2026-09-24 用户按实测 14.85s 冷启动定档放宽）+ 超时返回空态/旧值；断言冷启动墙钟上限 + 参数护栏（≥ 一次完整取数 20s，< 前端 fetch 30s） |

### B3 界面与文档（P2/P3）

| Bug | 文件 | 改法要点 |
|---|---|---|
| BUG-008 | `web/static/settings.js`、`web/templates/_topbar.html` | settings 页绑定 `#refresh-btn`（重跑 `load()`）或隐藏该按钮；`/timeline`、`/backtest`、`/settings` 补写 `#topbar-date`（有数据的页面写数据日） |
| BUG-013 | `AGENTS.md`、`docs/commands.md` | 以代码为准（3650）改文档；AGENTS.md 是 agent 上下文文件，漂移会持续误导 ⇒ 优先改它 |
| BUG-011 | `.gitignore`、`docs/`、`data/backup/` | 按 D-1 采纳 A：① `.gitignore:41-45` 注释改成事实——「本库**入库**，即线上数据源；`-wal/-shm` 排除 ⇒ 写库后提交前必须 `wal_checkpoint`（由 `git_ops` 护栏强制）；事件表备份见 `data/backup/econ_events.json`」；② 把「DB 入库 + 事件表备份」写进 `docs/architecture.md` 的数据流；③ 事件表备份/恢复的落地在 B1-4（同批）；`git rm --cached` 方案**不在本批**，单独立项（需验证 Railway 恢复链） |

### B4 卫生与测试（P3）

| Bug | 文件 | 改法要点 |
|---|---|---|
| BUG-015 | 仓库根 | 按 D-2 执行：**删除** `seed_history.py`、`seed_history_market.py`、`_dbg/`、`_dbg_hist.json`、`web_uvicorn.log`、`_phase5_run.log`、`task brief.md`；**移档** `app.py`（旧入口）、`render.yaml` → `tasks/2026-09-24-qa-bughunt/legacy/`（附 `legacy/README.md` 一句说明「已退役，仅存档」）；`.gitignore` 追加 `*.log`。删前逐个 `git log --oneline -1 -- <file>` 确认近期无使用；`AGENTS.md` 中涉及这些文件的记录同步更新 |
| BUG-016 | `tests/` | ① 删除 137/162 两处被遮蔽的重复块；② 按 §4 补链路级用例；③ 加元测试「同文件内不得重复定义同名 test」；④ 修 `test_web.py:1882` 绕入口的用例（改为走 `load_config`） |

---

## 3. 决策（已定，2026-09-24 用户确认「按你的建议」）

| # | 决策 | 采纳 | 理由 |
|---|---|---|---|
| D-1 | git 跟踪的 `data/marketpulse.db` | ✅ **A：保持入库** + `.gitignore` 注释改对 + 提交前 `wal_checkpoint` 纪律（由 B1 护栏强制执行）+ 事件表纳入备份 | B 方案（`git rm --cached` + 扩展恢复链）会改变线上数据来源，必须单独验证 Railway 恢复链，不与该批缺陷修复纠缠 |
| D-2 | 仓库根残留危险脚本/调试产物 | ✅ **删除**：`seed_history.py`、`seed_history_market.py`、`_dbg/`、`_dbg_hist.json`、`web_uvicorn.log`、`_phase5_run.log`、`task brief.md`；**移档**到 `tasks/2026-09-24-qa-bughunt/legacy/`：`app.py`（旧入口）、`render.yaml`；`*.log` 进 `.gitignore` | 删除项均为文档已标「勿再使用」或纯调试产物；`render.yaml` 涉及部署历史（已迁 Railway），留档优于删除 |
| D-3 | 提交前护栏 + 事件表备份 | ✅ **加**（设计见 B1-4） | BUG-001 的爆炸半径（删库 → 空库被 commit+push 上线）靠它兜底；`git_ops.auto_commit_push()` 是全部推送路径的唯一漏斗，成本 ≈ 40 行 |

---

## 4. 每条缺陷的回归测试（必须链路级，不得绕过生产入口）

| Bug | 测试（文件名建议） | 断言要点 |
|---|---|---|
| 001 | `tests/test_phase31_storage.py`（或并入既有 storage 测试） | 模拟 `OperationalError("database is locked")` → `query_history()` **仍含旧行**、DB 文件未被删；`DatabaseError`（真损坏）→ 走 rename 备份而非 unlink；Windows `PermissionError` 不逃出入口 |
| 002 | `tests/test_web.py` | `POST /api/settings{cost}` → `load_config()["watchlist"]["stocks"][0]["cost"] == 1.5` 且 `GET /api/watchlist` 的 `pnl_pct` 非空；`cost` 非法（0/-1/Infinity/"abc"）→ 丢弃或 400，不产生 `cost:null` 之外的怪值 |
| 003 | `tests/test_settings_store.py` | `POST {alert.vix: Infinity/1e999/"inf"}` → 400 且文件字节不变；`json.loads(mode=strict)` 恒可解析（断言 `allow_nan=False` 生效） |
| 004 | `tests/test_web.py` | `Authorization: Basic base64("qa:密码123")` → 401（非 500）；名字或口令任一非 ASCII 都走 False 分支 |
| 005 | `tests/test_scripts.py` | 裸跑 → 非 0 退出且 DB 行数不变；带 `--force` 且在临时路径上 → 行为符合注释 |
| 006 | `tests/test_alerter.py` | 同日两次 `run_alert_checks`（触发集合不同）→ 文件块集合 == 两次触发并集 |
| 007 | `tests/test_web.py` | `news.json`/`config.json` 写入 `\xff` → `/api/news`、`/api/settings` 仍 200 + 空结构/默认值 |
| 008 | `tests/test_web.py`（模板层）或 `verify_ui.py` | `/settings` 存在 `refresh` 绑定（模板/JS 断言）；三个子页 `#topbar-date` 不等于 `—` |
| 009 | `tests/test_web.py` | 上游失败 → 响应含 `stale: true` + `as_of`；前端标记（由 `verify_ui.py` 或静态断言覆盖） |
| 010 | `tests/test_config.py` | 参数化：SCHEMA 中每个 `alert.*` 阈值键都有对应 env 且生效 |
| 012 | `tests/test_web.py` | 冷缓存下 `/api/cn/quotes` 墙钟 ≤ 上限（限时器生效后返回空态而非阻塞） |
| 013 | `tests/test_web.py` | 断言文档中的上限值 == `api_history` 的 `le`（用 `inspect.signature` 或直接钉 3650），文档漂移即红 |
| 014 | `tests/test_settings_store.py` | 同秒两次 `apply_updates` → 产生两个不同备份；并发 tmp 名唯一 |
| 016 | 元测试 | `tests/` 内同一文件不得重复定义同名 `test_*`（CollectionError 前置拦截） |
| B1-4a | `tests/test_storage.py` | `export_monthly_backups()` 产出 `econ_events.json`（单文件全量，**定档**）且行数与库一致；跨月（含未来月）改动都会刷新；空表不覆盖备份；`restore_if_empty()` 对空表恢复事件表；非空表不动作（幂等） |
| B1-4b | `tests/test_git_ops.py`（或既有同类） | 临时仓库：HEAD 300 行 + 工作区库清空 → `auto_commit_push` 返回 False、`git status` 与 HEAD 一致（**未提交**）；正常新增行 → 提交成功；`git show` 失败（无 HEAD）→ 放行不阻塞；提交前 `-wal` 内容已并入 `.db`（checkpoint 生效） |

> 纪律（`AGENTS.md`）：测试要断言**可观察契约**，不要钉实现细节/文案；不得为了让变更「有测试」而写空断言。

---

## 5. 验证命令

```bash
venv/Scripts/python -m pytest tests/ -q                     # 基线 774 passed；修复后应 ≥774 且无新增红
venv/Scripts/python -m pytest tests/ -q -k "lock or cost or isfinite or non_ascii or stale or env_sz"
venv/Scripts/python -m uvicorn web.app:app --port 8127       # 逐 Bug 手工复现（每轮换端口）
venv/Scripts/python -m uvicorn web.app:app --port 8128       # Basic Auth 实例（非 ASCII 凭据）
CONFIG_PATH=<tmp副本> venv/Scripts/python -m uvicorn web.app:app --port 8126   # 设置写链路
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py      # B3 前端改动后
venv/Scripts/python -m scripts.auto_commit_data              # B1-4 护栏：无改动「跳过」/ 空库「拒绝」都不许推
venv/Scripts/python scripts/backup_db.py                     # B1-4：data/backup/ 新增/刷新 econ_events.json（单文件）
venv/Scripts/python -m pytest tests/ -q -k "guard or backup or single_impl"
```
**改动前后都要做的数据自保**：`cp data/marketpulse.db{,-pre-b0}`；B0 期间**不得**在生产库上触发重建路径（用 `CONFIG_PATH`/`--db` 指向临时库）。

---

## 6. 风险与注意事项

| 风险 | 说明 | 对策 |
|---|---|---|
| 修 BUG-001 时误触发重建 | 新逻辑若判错，仍可能毁生产库 | 改前备份 DB；重建分支先写 `.corrupt-<ts>`；用临时库跑破坏性用例 |
| 「锁重试」掩盖真故障 | 退避重试会把持续锁冲突拖长报告时长 | 重试上限 3 次 + 明确日志 + 超限后抛错（不静默） |
| BUG-002 收敛重构波及写路径 | `settings_store` 已有通过用例（含 cost 校验文案） | 先抽公共函数、保留 `settings_store` 对外行为与报错文案，再让 `config` 复用；断言两侧同构 |
| BUG-003 读侧回退改变既有配置语义 | 若用户环境已存 `Infinity`（本地实测文件未污染） | 回退默认 + warn 日志，不静默吞；文档记明 |
| BUG-004 改 bytes 比较 | 编码不一致会导致「永远 401」 | 两侧都 `encode("utf-8")`（同一编码），并保留非 ASCII 单测 |
| BUG-006 合并写盘 | 若既有文件格式被外部工具依赖 | 保持「多块 Markdown」既有格式，仅改合并策略 |
| BUG-012 加限时 | 超时返回空态会让中国宏观页出现「数据暂缺」 | 与既有降级语义一致（memory #94），并在前端沿用「数据暂缺」文案 |
| BUG-005/015 删文件 | 删的是仓库内容，影响他人工作区 | 按 D-2 定；删前 `git log --oneline -1 -- <file>` 确认无近期使用 |
| BUG-011 选 B 方案 | 改变线上数据来源 | 与缺陷修复**隔离**，立项单独验证 Railway 恢复链 |
| 测试假绿复发 | 新写的链路测试若仍绕过入口，等于没修 | 断言从 API/入口出发；元测试禁止同文件重名 |

---

## 7. 未覆盖 / 仍待确认

- 真实浏览器矩阵（Safari/Firefox 的日期解析与 `backdrop-filter`）、Railway 线上实例（鉴权三连、`/docs` 暴露面）、wkhtmltoimage 图片链路、真实 Hermes cron 并发时序（**用于评估 BUG-001 的实际触发概率** ⇒ B0 完成后建议加一次 cron 时序观察）。
- `src/econ_fetcher._growth_axis` 缺证据时是否确定性返回 `expanding`：**仍未验证**（需真实 BLS 报文）。
- 报告「需求缺失」1–7 项：本计划不含实现；其中 **3（事件表备份）** 已并入 B1/D-3，其余建议单独立项（鉴权节流、跨文件事务、图片契约守卫、依赖固定、日志轮转）。

---

## 8. 完成定义（DoD）

- B0 四条修复后：锁不删库、cost 全链路可用、非有限值 400、非 ASCII 凭据 401；
- 每条缺陷都有链路级回归测试，`pytest tests/ -q` 无新增红且重复定义块已删除；
- B1 脚本安全侧默认生效（裸跑不再清库），告警文件同日重跑不再丢块，设置写路径无秒级冲突；
- **B1-4 落地**：事件表进 `data/backup/` 且恢复链覆盖；`auto_commit_push` 在「空库 / 行数骤减」时拒绝提交推送，并在提交前强制 `wal_checkpoint`；
- B3 文档与代码一致（`days` 上限、`.gitignore` 注释），死按钮与恒 `—` 日期消失；
- B4 仓库根危险产物按 D-2 清干净（删除项已删、`legacy/` 已建档、`*.log` 已忽略）；
- `docs/pitfalls.md` 追加 F1 的 5 条修法原则；本目录 `journal.md` 记录每条 Bug 的修复与验证证据。

---

## 9. 执行看板（逐条划掉用）

| # | 缺陷 | 批次 | 主改文件 | 回归测试 | 状态 |
|---|---|---|---|---|---|
| 001 | 锁被判损坏 → 删库 | B0 | `src/analyzer.py`（+`src/storage.py` busy_timeout） | `test_phase31_storage.py` | ✅ |
| 002 | cost 全链路断 | B0 | `src/config.py` + `web/static/settings.js` | `test_web.py` 链路用例 | ✅ |
| 003 | Infinity 入盘 | B0 | `src/settings_store.py` + `src/config.py` | `test_settings_store.py` | ✅ |
| 004 | 非 ASCII 凭据 500 | B0 | `web/app.py` | `test_web.py` 鉴权用例 | ✅ |
| 005 | 迁移脚本清库 | B1 | `scripts/migrate_to_sqlite.py`（移档 legacy）+ `docs/commands.md` | `test_scripts.py` | ✅ |
| 005b | `backup_db.py` 失败当成功 | B1 | `scripts/backup_db.py` | `test_scripts.py` | ✅ |
| 006 | 告警文件覆盖 | B1 | `src/alerter.py` | `test_alerter.py` | ✅ |
| 014 | 设置备份/tmp 冲突 | B1 | `src/settings_store.py` | `test_settings_store.py` | ✅ |
| — | 事件表备份 + 推送护栏（D-3） | B1-4 | `src/storage.py`、`src/git_ops.py` | 见 §4 B1-4a/4b | ✅ |
| 007 | 非 UTF-8 → 500 | B2 | `web/app.py`、`src/config.py` | `test_web.py` | ✅ |
| 009 | stale 无消费者 | B2 | `web/static/*.js` | `test_web.py` + `verify_ui.py` | ✅ |
| 010 | ENV_MAP 缺 SZ | B2 | `src/config.py` | `test_config.py` 参数化 | ✅ |
| 012 | cn/quotes 阻塞 13.5s | B2 | `web/app.py` + cn 取数 | `test_web.py` 墙钟断言 | ✅ |
| 008 | 死按钮 / 日期恒 — | B3 | `web/static/settings.js`、`_topbar.html` | `verify_ui.py` | ✅ |
| 013 | days 上限文档漂移 | B3 | `AGENTS.md`、`docs/commands.md` | `test_web.py` 文档一致性 | ✅ |
| 011 | `.gitignore` 注释与事实相反 | B3 | `.gitignore`、`docs/architecture.md` | —（文档项；备份链由 B1-4a 覆盖） | ✅ |
| 015 | 仓库根残留产物 | B4 | 仓库根 + `.gitignore` + `AGENTS.md` | —（人工核对清单） | ✅ |
| 016 | 测试假绿/死代码 | B4 | `tests/` | 元测试（同名禁止） | ✅ |

> 执行者每完成一批：跑 §5 命令 → 更新本表 ✅→✅ → 把证据（命令 + 输出摘要）写进 `journal.md`。

> **定档注（2026-09-24 用户）**：① BUG-012 的取数上限 **15s → 20s**；② B1-4a 的事件表备份由
> 「按月 + 历史月冻结」改为**单文件全量** `econ_events.json`。两处均已落地 + 补参数/性质护栏测试，证据见 `journal.md`。
