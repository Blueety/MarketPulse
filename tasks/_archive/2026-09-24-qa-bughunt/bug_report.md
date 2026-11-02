# MarketPulse 缺陷排查报告（QA 走查）

- 日期：2026-09-24
- 范围：三入口（daily_report / snapshot_report / opening_analyzer）→ 报告/告警/context 持久化 → SQLite 存储 → FastAPI 看板（6 页 + 11 JSON API + Basic Auth）→ 设置页配置写链路 → scripts/ 运维脚本 → 测试套件
- 环境：Windows 10 19045 / venv Python 3.14.4（部署侧 railway.toml 声明 3.11）/ fastapi+starlette(JSONResponse `allow_nan=False`)/ Chromium 无头 1440×900
- 实测实例：8123（`MP_AUTH_DISABLED=1`）、8124（Basic Auth 开启）、8126（`CONFIG_PATH` 指向临时副本，用于设置写链路）
- 环境副作用：`config.json` 摘要 `ddd49e84f803c5ea` 前后一致；`data/`、`context/` 与基线逐文件比对 **0 变化**；三个实例已停止，临时副本已删
- 基线：`pytest tests/ -q` → **774 passed / 41s**（缺陷全部不在测试覆盖内）

## 材料清单

| 类别 | 内容 |
|---|---|
| 已有 | 全部源码、`tests/`（774 条）、`docs/`、生产 SQLite（只读）、真实 `context/`·`alerts/`·`reports/` 样本、`railway.toml` / `Procfile` / `requirements.txt` |
| 缺失（本次未运行，已标注） | 线上 Railway 实例访问；真实 Hermes cron 时序日志；wkhtmltoimage / imgkit 环境；非 Chromium 浏览器（Safari / Firefox） |

## 测试策略与执行结果

| 维度 | 执行内容 | 结果 |
|---|---|---|
| 冒烟 | 6 个页面路由 + 11 个 JSON API 全量请求（含 `/docs`、`/redoc`、`/openapi.json`、`/favicon.ico`） | 全部 200/401/422 符合预期，无 500 |
| 核心流程 | 报告/告警/自选/回测/时间线数据与 SQLite、`context/`、`alerts/` 对账 | 线上口径与样本一致 |
| 边界 | `days`（0/1/-1/365/366/730/1e9/'abc'/1.5/数组）、`group` 枚举、`future_days`、凭据族、设置值（null/bool/字符串/负数/0/极大/非有限/超限自选） | 见 BUG-003/004/013 |
| 异常处理 | 坏 JSON、非 UTF-8 字节、缺失文件、上游超时、DB 锁竞争 | 见 BUG-001/007/012 |
| 安全 | 鉴权头族、路径遍历、注入（SQL/XSS）、敏感信息、越权写路径 | 见已排除表（仅 BUG-004 例外） |
| 性能 | 冷/热缓存延迟对比（`/api/cn/quotes` 13.50s→0.02s 等） | 见 BUG-012 |
| 兼容性 | 依赖版本（本地 3.14 vs 部署 3.11）、时区（ET/上海/北京口径）、编码 | 见需求缺失 6、BUG-007 |
| 数据一致性 | DB 与报告/缓存/context 写入顺序、并发写、告警去重、备份链 | 见 BUG-001/006/011 |
| 部署运维 | 自动提交白名单范围、`.gitignore` 与跟踪状态、健康检查、危险脚本 | 见 BUG-005/011/015 |
| 用户体验 / 回归 | 死按钮、无反馈、文案指向不存在的控件、子页顶栏日期、陈旧数据标注 | 见 BUG-002/008/009 |
| 未覆盖 | 真实浏览器矩阵、线上 Railway、真实 cron 并发时序、wkhtmltoimage 图片链路 | 见文末「未运行 / 待确认」 |

---

## 致命

### BUG-001 瞬时数据库锁被误判为「库损坏」→ 删除整个 marketpulse.db

- 严重程度：致命 ｜ 优先级：P0 ｜ 复现概率：偶现（并发窗口）
- 位置：`src/analyzer.py:638-651`（`_upsert_history_rows_selfheal`）
- 复现（已执行，平台无关）：
  1. 让 `storage.upsert_history_rows` 首次调用抛 `sqlite3.OperationalError("database is locked")`（模拟 snapshot cron / 日历同步 / 外部 `*/5` 提交与 daily_report 撞锁）；
  2. 调 `analyzer.append_history({"date": "2026-09-03", "sh": 102.0})`。
- 预期：重试或退避；至少不删数据。
- 实际：日志 `history DB 损坏，删除重建后重试: database is locked` → `unlink` `db`/`-wal`/`-shm` → `init_db()` → 只写当日行。实测 `query_history()` 从 2 行塌成「仅当日 10 键」；真实库为 2715 行 / 272 个日期，将塌成 1 天。同一 helper 也被 `merge_history` 使用（第二次复现同样清空）。
- Windows 差异（已实测）：另一个进程持有 `-wal` 时 `Path.unlink` 抛 `PermissionError`（WinError 32），**逃出 `append_history`**，三入口直接崩。
- 放大链：`data/marketpulse.db` 是 **git 跟踪**文件（`git ls-files` 命中，`git check-ignore` 未命中）→ auto-push 白名单含 `data/` → 空库会被提交并推给 Railway；`data/backup/` 只备份 `history`，`econ_events`/`econ_event_news` 无任何备份/恢复路径；`restore_if_empty` 仅在**空库**触发，此刻库非空（当日行），恢复链不会兜底。
- 验证方式：新增测试「模拟 OperationalError(database is locked) → `query_history()` 仍含旧行、且 `data/<db>` 未被删除」；再补一条 Windows 下 `PermissionError` 不逃出入口的测试。
- 修复方向：重建前先 `PRAGMA integrity_check`；只对真正的损坏类 `DatabaseError` 重建；锁错误走重试（`busy_timeout` + 指数退避）；重建前把原库另存 `.corrupt-<ts>` 副本。

---

## 严重

### BUG-002 组合盈亏（cost）全链路断开，且设置页文案指向不存在的控件

- 严重程度：严重 ｜ 优先级：P0 ｜ 复现概率：必现
- 位置：`src/config.py:160`（`_valid_watchlist` 重建条目时只保留 `symbol`/`label`）、`web/static/settings.js:renderStocks()`（行模板只有 symbol/label/删除）、消费点 `web/app.py:548-553`
- 复现：
  1. `POST /api/settings {"watchlist.stocks":[{"symbol":"515300.SS","label":"红利低波ETF","cost":1.5}, …]}` → 200；
  2. `config.json` 原文含 `"cost": 1.5`，但**响应/`GET /api/settings` 的条目没有 cost**；
  3. `GET /api/watchlist` → `"cost":null,"pnl_pct":null`，`overview.covered=0`；
  4. 首页「持仓盈亏」列 11 行全为 `—`，卡片文案「未录成本价（在设置页录入后显示盈亏）」；设置页自选行只有 symbol/label 两个输入框（浏览器实测 `inputsByKey={symbol:11,label:11}`，`hasCostInput:false`）。
- 预期：录入成本价 → 保存 → 首页显示盈亏%。
- 实际：**录不进去（无控件）、存不住（读侧丢弃）**，且提示文案把用户指向一个不存在的控件（死路流程）。任何一次设置保存也不会把 `cost` 从 `config.json` 抹掉（写侧 deep-merge 原文件），所以文件里有、界面永远没有 —— 状态自相矛盾。
- 为什么测试没抓到：`tests/test_web.py:1882-1932` 直接注入带 `cost` 的 stock dict 调 `_build_watchlist_payload`，绕过 `load_config`。
- 验证方式：新增链路测试「settings POST cost → 读 `load_config()`/`GET /api/watchlist` 能看到 cost 与 pnl_pct」；前端在设置页出现成本输入框且首页盈亏列随成本变化。
- 修复方向：`_valid_watchlist` 透传合法 `cost`（finite 且 >0）；设置页行模板补 cost 输入（`collect()` 已有读取逻辑，只缺 UI）。

### BUG-003 POST /api/settings 接受 Infinity → config.json 写入非法 JSON，阈值静默变 ∞

- 严重程度：严重 ｜ 优先级：P1 ｜ 复现概率：必现（构造请求即可）
- 位置：`src/settings_store.py:_validate_one`（float 分支只校验 `gt/min/max`）、`_atomic_write`（`json.dumps` 默认 `allow_nan=True`）
- 复现：`POST /api/settings {"alert.vix": Infinity}`（或 `1e999` / `"Infinity"` / `"inf"`）→ **200 saved**。
- 预期：400（非有限数不是合法阈值）。
- 实际：
  1. `config.json` 落成 `"vix": Infinity`，`node -e JSON.parse` 直接报 `Unexpected token 'I'`（非 RFC 8259）→ 任何非 Python 消费方（Node/Go/Rust/前端）都读不了；
  2. `GET /api/settings` 与 `/api/backtest` 的 `threshold_config.fallback` 把该值显示为 `null`（设置页画面上阈值「消失」）；
  3. 进程内 `alert_threshold("VIX")` 实测 `inf`，`check_breach("VIX", 30.0, 15.0, history=[])` 返回 `None`（+100% 也不告警）⇒ **该标的告警被静默永久关闭**。`{"alert.k_factor": 1e999}` 同样 200 并写入 `"k_factor": Infinity`（波及全标的动态阈值）。
- 验证方式：`math.isfinite` 拒收 + 断言 `config.json` 永远可被 strict JSON 解析；回补一条「非有限值 → 400 且文件不变」的测试。
- 修复方向：校验层加 `math.isfinite`；写盘 `json.dumps(..., allow_nan=False)`；读侧对非有限值回退内置默认。

### BUG-004 Basic Auth 遇非 ASCII 凭据抛 500（中文密码账号永远登不上）

- 严重程度：严重 ｜ 优先级：P1 ｜ 复现概率：必现
- 位置：`web/app.py:149-164`（`try/except` 只包 `base64`+`decode`，未包 `hmac.compare_digest`）
- 复现：服务端 `MP_AUTH_USER=qa` `MP_AUTH_PASS=密码123`，`curl -u 'qa:密码123' http://host/api/latest` → **500 Internal Server Error**；无凭据请求也可由任意人触发（刷栈 + 日志噪音）。
- 服务端 traceback（实测）：
  ```
  File "web/app.py", line 164, in _authorized
      return hmac.compare_digest(u, _auth_user()) and hmac.compare_digest(p, _auth_pass())
  TypeError: comparing strings with non-ASCII characters is not supported
  ```
- 预期：401。该函数 docstring 明写「任何异常形态都返回 False（401），**绝不抛给 FastAPI 变成 500**」—— 契约被自身实现破坏。
- 影响面：用户名为/password 含非 ASCII（中文口令是**本产品用户最可能的选择**）时，登录永远 500；浏览器只会反复弹窗再失败。
- 验证方式：`Authorization: Basic base64("qa:密码123")` → 401（不是 500）；加一条非 ASCII 凭据的鉴权单测。
- 修复方向：比较前统一转 bytes（`compare_digest` 支持 bytes）或对非 ASCII 直接返回 False；把整个 `_authorized` 体包进 `try/except Exception`。

### BUG-005 scripts/migrate_to_sqlite.py 默认可清空生产 history（文档称「幂等重跑」）

- 严重程度：严重 ｜ 优先级：P1 ｜ 复现概率：必现（默认参数即触发）
- 位置：`scripts/migrate_to_sqlite.py:48-60`（`executescript` 里 `DELETE FROM history;`）+ `--db/--json` 均有默认值；`docs/commands.md` 把它列为常规验证命令
- 复现：项目根 `venv/Scripts/python scripts/migrate_to_sqlite.py`（文档原文「一次性迁移（幂等重跑）」）。
- 预期：幂等，不动既有数据。
- 实际：先 `DELETE FROM history`，再从 `data/history.json`（**末行 2026-09-11 的旧快照**）全量重灌 → 272 个日期塌成约 1 年前的那批日期，中间两周（09-12 ~ 09-23）丢失；脚本随后打印「迁移完成」并把失败当成功（`scripts/backup_db.py` 恒返回 0 同类）。
- 验证方式：把 `--db`/`--json` 改为必填并加 `--force` 二次确认；或直接删除该脚本（迁移已完成）。
- 修复方向：见上；同时让 `--dry-run` 真正只打印计划。

---

## 一般

### BUG-006 同日重跑同一 (date,type) 覆盖告警文件 → 该条告警当日永久丢失

- 严重程度：一般 ｜ 优先级：P2 ｜ 复现概率：偶现（同日重跑且触发集合变化）
- 位置：`src/alerter.py:95-105`（`path.write_text("\n".join(render_alert(a) for a in pending))` 只写 pending）
- 复现（已执行）：run1 MOVE 触发 → 文件含 MOVE 块；run2 同 date/type 改由 VIX 触发 → 文件被整段替换，**MOVE 块消失**；`alerts.log` 已记 MOVE，run3 不再补写 ⇒ 记录不可恢复。
- 修复方向：写前读回既有块、按 symbol 合并（或每次触发追加新块）；文件保留多块本就是既有格式。
- 验证方式：连续三次 `run_alert_checks` 断言文件内块集合 == 当日触发集合的并集。

### BUG-007 非 UTF-8 文件导致 500（违反「恒 200」契约），config 同类损坏会拖垮全站

- 严重程度：一般 ｜ 优先级：P2 ｜ 复现概率：偶现（文件损坏/半写）
- 位置：`web/app.py:1064-1069`（`except (json.JSONDecodeError, OSError)`，文档写「坏 JSON → 空结构、HTTP 200 恒定，不 500」）；`src/config.py:_read_json` 同类
- 复现（已执行）：`data/news.json` 写入含 `\xff` 字节 → `_load_news()` 抛 `UnicodeDecodeError`（`ValueError` 子类，不被 `except` 捕获）→ `GET /api/news` 500；同法构造 `config.json` → `load_config` 抛异常 ⇒ `/api/settings`、`/api/backtest`、`/api/watchlist` 与三个入口脚本同时挂。
- 修复方向：`except` 补 `ValueError`（或 `UnicodeDecodeError`）；统一 `read_bytes()` + `decode(errors="replace")`。
- 验证方式：坏字节文件下 `/api/news`、`/api/settings` 返回 200 + 空结构/默认值。

### BUG-008 设置页顶栏刷新按钮是死按钮；三个子页顶栏日期恒为「—」

- 严重程度：一般 ｜ 优先级：P2 ｜ 复现概率：必现
- 位置：`web/templates/settings.html:89`（只引 `settings.js`）+ `settings.js` 无 `refresh-btn` 绑定；`web/templates/_topbar.html:18` 初值 `—`
- 复现（已执行）：`/settings` 点击 `#refresh-btn` → 抓包 **0 个请求**（`app.js`/`macro.js`/`macro_cn.js`/`timeline.js`/`backtest.js` 都有绑定，唯 `settings.js` 没有）；`#topbar-date` 在 `/timeline`、`/backtest`、`/settings` 无任何写入者，恒为 `—`。
- 影响：无反馈操作（用户以为在刷新）；日期芯片长期显示 `—`。
- 修复方向：settings.js 绑定刷新（重跑 `load()`）或隐藏该按钮；子页写入 `topbar-date`。
- 验证方式：点击后出现请求/表单重建；子页日期芯片显示数据日。

### BUG-009 回退旧缓存时前端无任何陈旧提示（`stale` 信号无消费者）

- 严重程度：一般 ｜ 优先级：P2 ｜ 复现概率：偶现（取数失败）
- 位置：`web/app.py:1234-1241`（`stale["stale"]=True`）→ `web/static/*.js` 中无任何 `stale` 消费（grep 零命中）
- 影响：自选卡展示的是上一次缓存，用户无从分辨是否过期（与「数据截至」标注纪律不一致）。
- 修复方向：前端消费 `stale` 显示「取数失败，展示上次快照（as_of）」；验证：断网/上游失败时卡片出现陈旧标注。

### BUG-010 `ALERT_THRESHOLD_SZ` 未进 ENV_MAP ⇒ 文档承诺的 env 覆盖对深证静默失效

- 严重程度：一般 ｜ 优先级：P2 ｜ 复现概率：必现
- 位置：`src/config.py:32-47`（含 SH/CYB/GSPC/IXIC/VIX/VXN/MOVE，独缺 SZ）；`docs/commands.md` 声称 `ALERT_THRESHOLD_*` 通用覆盖
- 复现（已执行）：打印 ENV_MAP keys → 无 `ALERT_THRESHOLD_SZ`；设置 `ALERT_THRESHOLD_SZ=9` 不生效，设置页也不会标注。
- 修复方向：补映射 + 参数化测试覆盖 8 个阈值 env。

### BUG-011 `.gitignore` 注释与事实相反：DB 实际入库并随部署上线，事件表无备份

- 严重程度：一般 ｜ 优先级：P2 ｜ 复现概率：必现
- 位置：`.gitignore:41-45`（「三十一期：SQLite 库不入 git（Railway 经 data/backup/ 恢复链取数）」）vs `git ls-files data/marketpulse.db` 命中、`git check-ignore` 未命中
- 影响：运维按注释理解会误判数据来源与风险；真实情况是「提交的 .db 二进制即线上数据源」，而 `.gitignore` 同时排除了 `-wal/-shm` ⇒ 提交的副本可能漏最新行（需 `wal_checkpoint`）；`econ_events`/`econ_event_news` 无备份路径，一旦 BUG-001 触发即不可恢复。
- 修复方向：二选一并把注释写对 —— 真入库就给三张表都做备份；真排除就 `git rm --cached` 并扩展恢复链。

### BUG-012 `/api/cn/quotes` 冷启动同步阻塞 13.5s（无超时、无失败降级提示）

- 严重程度：一般 ｜ 优先级：P2 ｜ 复现概率：必现（冷缓存）
- 位置：`web/app.py` `/api/cn/quotes`（TTL 90s，取数直连 AkShare/中债，未见线程限时）
- 复现（已执行）：冷 13.50s / 热 0.02s（`/api/macro` 冷 0.02s、`/api/history` 0.03s 对比）
- 影响：中国宏观页首屏最长等待 13s+；上游挂起会占住 worker（单 worker 部署时阻塞其他请求）。
- 修复方向：复用项目既有 daemon-thread 限时范式（15s）+ 超时返回空态/旧值。

### BUG-013 文档与实现漂移：`/api/history` 的 days 上限

- 严重程度：一般 ｜ 优先级：P3 ｜ 复现概率：必现
- 位置：`docs/commands.md`（「days 边界 91→200、**366→422**」）、`AGENTS.md`（「`days` 上限 **365**」）vs `web/app.py:1005` `Query(30, ge=1, le=3650)` 与 `tests/test_web.py:566-570`（3650 合法 / 3651→422）
- 复现（已执行）：`/api/history?days=366` 与 `=730` 均 200。
- 修复方向：以代码/测试为准改文档（`AGENTS.md` 是 agent 上下文文件，漂移会误导后续实现）。

---

## 轻微

### BUG-014 设置保存的备份/临时文件名秒级冲突，且写路径无并发保护

- 位置：`src/settings_store.py` `_backup`（`config.json.bak-%Y%m%d-%H%M%S`）、`validate_updates` 的 `<name>.validate-tmp`、`_atomic_write` 的 `<name>.settings-tmp`（均为固定名）
- 影响：同一秒内两次保存 → 第二个备份覆盖第一个（丢了最接近当前状态的回滚点）；并发 POST → 共享同一 tmp 文件，`load_config` 可能读到对方内容、`finally: unlink()` 会把对方文件删掉（校验误判/丢失更新）。
- 修复方向：备份名加微秒或序号；tmp 用 `tempfile.NamedTemporaryFile(dir=parent, delete=False)`；写路径加文件锁。

### BUG-015 仓库根残留危险/调试产物（部分与生产数据同名的旧脚本）

- 位置：`seed_history.py`、`seed_history_market.py`（`AGENTS.md` 明标「勿再使用」：小写键覆盖 `last_values` + 整行覆盖 `history`）、`app.py`（旧入口）、`render.yaml`（已迁 Railway）、`_dbg/`、`_dbg_hist.json`、`task brief.md`、`web_uvicorn.log`、`_phase5_run.log`（后两者为已提交的日志）
- 影响：仓库里同时存在「文档说危险」与「可一键执行」的脚本；审计与新人上手成本高。
- 修复方向：删除或移到 `tasks/` 归档；`*.log` 加入 `.gitignore`。

### BUG-016 测试套件对上述缺陷零覆盖（个别为假绿）

- 位置：`tests/test_web.py:1882-1932`（cost 用例注入 stock dict，绕过 `load_config` → 掩盖 BUG-002）；`tests/test_backtest.py:173-199` 与 `137-170` 重复（前块被同名函数遮蔽，永不执行）
- 影响：774 passed 给出「全绿」假象，而删库/成本/POST 非有限值/鉴权 500 四类严重缺陷都不在覆盖内。
- 修复方向：按各 Bug 的「验证方式」补链路级测试；删除重复块；对入口脚本的危险默认值加断言。

---

## 需求缺失（不算 Bug，建议立项）

| # | 缺失项 | 说明 |
|---|---|---|
| 1 | Basic Auth 无限速/无失败节流 | 可无限次尝试口令；建议失败延迟或简单锁定 |
| 2 | 跨文件无事务 | 报告已落盘但 DB/缓存写失败时无回滚（实测顺序：report → history → alerts → cache → context → image → backup → push），外部 `*/5` 提交可能推走「半成品」 |
| 3 | 事件两表无备份/恢复 | `data/backup/` 仅 `history`，Railway 恢复链造不出 `econ_events` |
| 4 | 线上（Railway）设置页只读 | 云端无法改阈值，需改代码或 env |
| 5 | 图片契约无强制 | `IMAGE_WIDTH=600`、`MAX_IMAGE_BYTES=800KB`、`RENDER_TIMEOUT` 均为死常量，Playwright 无超时/体积守卫（`src/image_renderer.py:20-22`） |
| 6 | 依赖未固定 | `requirements.txt` 多为 `>=`，本地 3.14 / 部署 3.11，fastapi/starlette 行为可能漂移 |
| 7 | 无日志轮转 | 脚本日志散落仓库根，无统一日志目录 |

---

## 已排除（核对后不成立，避免误报）

| 项 | 结论 |
|---|---|
| XSS | 8 条外部数据源（news/板块/自选/告警 md/事件/econ 数值）到 `innerHTML` 的路径**全部** `escapeHtml`（`app.js:135` 定义，news url/title 亦转义） |
| SQL 注入 | `src/storage.py` 全部占位符绑定，无字符串拼 SQL / 常量表名插值 |
| 路径遍历 / 越权 | `/static/../config.json`、`/static/%2e%2e/config.json` 均 401；`/nope` 401；`/healthz` 按设计放行且不查 DB |
| 鉴权头族 | 坏 base64 / 无冒号 / 空口令 / 错用户 / 超长 8KB 头 / `basic` 小写前缀 / `Basic ` 空 → 均 401（**仅非 ASCII 例外 = BUG-004**） |
| 敏感信息 | `.env` 未被跟踪（仅 `.env.example`）；`/api/settings` 只回白名单值，不含密钥 |
| SQLite 单点 | `--db` 会静默新建空库（`backup_db.py`）等属运维脚枪，已并入 BUG-005 描述 |
| NaN/Infinity 响应 | 11 个 API 实测响应体无 `NaN/Infinity` 字面量（`starlette` 用 `allow_nan=False`，故非有限值只会 500 或被上游吸收） |
| 零方差动态阈值回退 | 实测构造全平坦历史 → `threshold_mode=fixed`、阈值回退固定值（scout 的「回退未实现」**不成立**） |
| 美股去重门 `prev=None` 假阳性 | 实测「上一行 gspc/ixic 为 None」→ 判定 `False`（不误判为重复日） |
| 测试污染生产数据 | 跑全量 774 条后 `data/`、`context/` 逐文件摘要 **0 变化**（含 `news.json`、`marketpulse.db`）；`conftest` 的 context/backup/watchlist autouse 隔离有效 |
| 自动提交范围 | 白名单 `/ 同范围` 由既有测试钉死（本报告未复测 git push 路径） |
| `/api/history` 366 未拒绝 | 非漏校验：代码上限 3650，是**文档**过期（BUG-013） |

---

## 汇总表

| 编号 | 标题 | 模块 | 严重度 | 优先级 | 复现概率 | 状态 |
|---|---|---|---|---|---|---|
| BUG-001 | 瞬时锁被判为损坏 → 删库重建（history+事件表全失） | src/analyzer.py | **致命** | P0 | 偶现 | 已复现 |
| BUG-002 | 组合盈亏 cost 全链路断开 + 设置页无成本输入控件 | src/config.py / settings.js | 严重 | P0 | 必现 | 已复现 |
| BUG-003 | POST /api/settings 接受 Infinity → config.json 非法 + 阈值 ∞ | src/settings_store.py | 严重 | P1 | 必现 | 已复现 |
| BUG-004 | Basic Auth 非 ASCII 凭据 → 500（中文密码登不上） | web/app.py | 严重 | P1 | 必现 | 已复现 |
| BUG-005 | migrate_to_sqlite 默认清空生产 history 并重灌旧 JSON | scripts/ | 严重 | P1 | 必现 | 已静态确认 |
| BUG-006 | 同日重跑覆盖告警文件 → 告警记录永久丢失 | src/alerter.py | 一般 | P2 | 偶现 | 已复现 |
| BUG-007 | 非 UTF-8 文件 → 500（news / config） | web/app.py / src/config.py | 一般 | P2 | 偶现 | 已复现 |
| BUG-008 | 设置页刷新按钮死按钮；子页顶栏日期恒「—」 | web/static, templates | 一般 | P2 | 必现 | 已复现 |
| BUG-009 | 陈旧缓存回退无提示（stale 无消费者） | web/app.py + static | 一般 | P2 | 偶现 | 静态确认 |
| BUG-010 | ALERT_THRESHOLD_SZ 未进 ENV_MAP | src/config.py | 一般 | P2 | 必现 | 已复现 |
| BUG-011 | .gitignore 注释与事实相反（DB 实际入库、事件表无备份） | .gitignore / 部署 | 一般 | P2 | 必现 | 已核实 |
| BUG-012 | /api/cn/quotes 冷启动 13.5s 同步阻塞 | web/app.py + cn 取数 | 一般 | P2 | 必现 | 已实测 |
| BUG-013 | 文档漂移：/api/history days 上限 365/366→422 | docs/commands.md, AGENTS.md | 一般 | P3 | 必现 | 已核实 |
| BUG-014 | 设置备份/临时文件秒级冲突 + 无并发保护 | src/settings_store.py | 轻微 | P3 | 偶现 | 静态确认 |
| BUG-015 | 仓库根残留危险脚本/调试产物入库 | 仓库根 | 轻微 | P3 | 必现 | 已核实 |
| BUG-016 | 测试套件对上述缺陷零覆盖（含假绿与死代码） | tests/ | 轻微 | P3 | 必现 | 已核实 |

---

## 建议修复顺序

1. **BUG-001**（数据不可逆丢失，且会被推送放大）→ 立刻加损坏判定 + 锁重试，并为 DB 增设备份。
2. **BUG-003 / BUG-004**（一个能让配置失效并关掉告警，一个让线上账号登不上/未认证可刷 500）。
3. **BUG-002**（功能整块不可用，用户看得见；修读侧一行 + 前端一个输入框）。
4. **BUG-005**（运维脚枪，改默认值即可）。
5. 其余按 P2/P3 排入常规迭代；BUG-016 的链路测试与 BUG-001/002/003 的修复同批落地。

## 未运行 / 待确认

- 真实浏览器矩阵（Safari/Firefox 的 `new Date('YYYY-MM-DD HH:mm')` 解析与 `backdrop-filter` 路径）、Railway 线上实例（鉴权三连、`/docs` 暴露面）、wkhtmltoimage 图片链路、真实 Hermes cron 并发时序（用于评估 BUG-001 的实际触发概率）。
- `web/app.py` 部分失败时用 `_cn_econ_raw[k] = raw.get(k)` 覆写旧成功值（:1336-1345）→ 是否会把四象限降级为错值而非 None：**待确认**（`build_cn_econ_payload` 在 `src/cn_econ_fetcher.py`，本次未逐行确认单腿退化分支）。
- `src/econ_fetcher._growth_axis` 缺证据时是否确定性返回 `expanding`：**待确认**（需真实 BLS 报文）。
