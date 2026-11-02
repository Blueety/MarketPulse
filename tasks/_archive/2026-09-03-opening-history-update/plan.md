# 实施计划 — 开盘/快照数据更新到 history.json（盘中数据进看板）

> 日期：2026-09-03 ｜ 任务目录：`tasks/2026-09-03-opening-history-update/`
> 引用 PRD：`tasks/2026-09-03-opening-history-update/prd.md`
> 前置声明：本 PRD **显式反转**十五期「开盘分析零持久化」决策 C 与七期「快照不写历史」设计；计划按 PRD 执行并在决策表/文档中记录反转。另 PRD 背景部分事实需修正（见现状盘点 4-6、决策 R2/R7）。

## 目标

让 `opening_analyzer.py` 与 `snapshot_report.py` 每次运行把**本次取到的市场子集指数值**合并写入 `data/history.json` 当日行（非整行覆盖、非 10 指数全量），使 web 看板在开盘/快照后即显示当日最新数据，同时不污染收盘序列语义与既有消费方。

## 验收标准（对应 PRD F1-F5 + 修正）

| # | 验收 |
|---|---|
| F1' | `opening_analyzer.py --market a-share` 运行后将 `sh/sz/cyb` 当前价写入 history 当日行（PRD F1 修正：开盘每次只取 2-3 个市场指数，非"10 个"，见决策 R2） |
| F1b | `opening_analyzer.py --market us` 运行后将 `gspc/ixic` 写入当日行；**VIX 不入 history**（见决策 R3） |
| F2 | `snapshot_report.py --market a-share/us/alt` 运行后将对应子集（sh/sz/cyb / gspc/ixic / gld/btc）写入当日行 |
| F3 | 同日多次运行不产生重复行：同 date 键**合并更新**自身市场键、保留他市场键（09:45 开盘 → 11:30 午盘 → 15:00 收盘 → 21:30 美股开盘依次叠加不互相抹除） |
| F4 | 写入后 90 天滚动裁剪（复用 `HISTORY_MAX`） |
| F5 | 数据变更随既有 `auto_commit_push`（两入口已接线，二十六期）提交推送；本期零新增接线 |
| F6 | 盘中行不进入任何"收盘语义"消费方的计算：daily_report / snapshot_report 在**读 history 时剔除自身 date 行**（决策 R4），计算与告警语义与 feature 前一致 |
| F7 | web `/api/latest` 在市场未开时段不出现整列空白（决策 R5，默认采纳后端前值兜底） |
| F8 | 既有测试更新/新增后全绿；`test_phase15` 的「零持久化」断言反转为「合并写入」断言 |

## 现状盘点（只读分析结论）

### 1. 各入口数据形状与日期键（决定 merge 而非 replace）

| 入口 | date 键 | 取数（键集合） | 现状写盘 |
|---|---|---|---|
| `daily_report.py` | 美东日期（ET） | `fetch_all()` 全 10 键收盘 | append_history 整行覆盖 + save_last_values + context（定稿行） |
| `snapshot_report.py` | `get_market_date(market)`：a-share=北京、us/alt=美东 | `fetch_all(market)` 仅子集：a-share={SH,SZ,CYB}、us={GSPC,IXIC}、alt={GLD,BTC} | 只读 history/last_values → 快照/告警文件 → auto_commit_push；**不写 history** |
| `opening_analyzer.py` | `get_market_date(market)` 同上 | `fetch_realtime_quotes(market)`：a-share={SH,SZ,CYB}+VIX、us={GSPC,IXIC}+VIX（新浪实时 current/prev_close/open；VIX 走 Yahoo） | 只写 `reports/opening/` → auto_commit_push；**零持久化**（决策 C，本 PRD 反转） |

### 2. 时序分析：A股(北京日)与美股(美东日)天然同键共行 → 必须合并写

- A 股北京日 D 收盘（15:00）= 美东 D 03:00；美股美东日 D 开盘 = 北京 D 21:30。**同一自然日 D 上，A股各时段（北京键 D）与美股各时段（美东键 D）指向同一行键 D**。
- 因此对键 D 的写入序列为：A股开盘 09:45 → A股午盘 11:30 → A股收盘 15:00 → 美股开盘 21:30 → 美股午盘（次日 00:00）→ daily 全量收盘（次日 08:02，美东 D 20:02，覆盖定稿）。
- 若按 `append_history` 整行替换语义：美股开盘（只有 gspc/ixic）会把 15:00 写好的 A股收盘整行**抹掉** → A股当日数据在美股时段从看板消失约 17 小时。**必须新增按键合并的写函数**（决策 R1）。
- daily 定稿行（append_history 全 10 键覆盖）与 merge 结果等价（merge 遇全量即全覆盖）→ daily_report 零改动（除可选读守卫 R6）。

### 3. 盘中行污染窗口（自愈，但需读时守卫）

- 盘中行在键 D 的存活期约 24h（D 09:45 → D+1 08:02 daily 定稿覆盖）。窗口内 history[-1] 为盘中值：
  - snapshot 午盘/收盘读 history（build_statuses 连涨/动态告警阈值窗口）会看到**本日开盘/更早时段**行 → 阈值/连涨串入盘中点（feature 前注释「文件恒无当日行」即为此假设）；
  - daily 运行时（08:02）history 已含键 D（A股 D 收盘 + 美股 D 午盘 12:00 ET 值）→ 趋势图末点/相关性/状态连涨会基于**美股午盘值**而非当日收盘值 → 与报告正文收盘价不一致。
- 自愈性：次日 daily 定稿后文件恢复纯收盘序列（回测/离线消费在定稿后读取不受影响）。
- **对策（决策 R4）**：daily 与 snapshot 在 load_history 后按自身 date 剔除该行再使用（读时守卫，各 1 行），把盘中行排除在一切"收盘语义"计算外；merge 统一放在 main() 末尾（渲染/告警之后、auto_commit_push 之前），与 daily append 时序同构。

### 4. 与 PRD 背景的出入（需修正的记录）

- PRD 称两入口"只更新 context/ 和 alerts/"：**不实**。snapshot 写 `reports/snapshots/` + 告警文件；opening 只写 `reports/opening/`；**context 仅 daily_report 生成**（四期决策 F）。不影响本计划执行，仅纠正叙述。
- PRD 验证命令 `d['dates'][-1]`：**语法错误**。`data/history.json` 是 `[{date, ...}, ...]` 列表（非含 `dates` 键的 dict）；验证命令见文末修正版。
- F1"10 个指数"：开盘/快照入口按设计只取各自市场子集（2-3 键）。按 PRD 字面每次写全 10 键需把这些入口的取数改为全市场（超范围、破坏"单板块渲染"设计）→ 以"子集键 + merge 合入当日行"达成 PRD 目标（web 显示该市场最新值），见决策 R2。

### 5. 既有测试中会被反转/破坏的断言（实施步骤必须处理）

| 测试 | 现状断言 | 本期动作 |
|---|---|---|
| `tests/test_phase15.py::TestOpeningEntry::test_zero_persistence` | 运行 main 后 data/context 目录 rglob 前后相等（零持久化） | 反转：改为断言 history 被合并写入（date/键值）+ context 仍零写入；注意该测试未重定向 HISTORY_FILE，须 monkeypatch `an.HISTORY_FILE` 或 `oa` 侧写函数 |
| `tests/test_phase27.py::test_snapshot_passes_history` | `run_alert_checks` 收到的 history == 运行后 `an.load_history()`（"文件恒无当日"） | 更新：断言收到的是**剔除自身 date 后**的列表；写入发生在 run_alert_checks 之后（顺序断言） |
| `tests/test_phase7.py::TestSnapshotEntryOrchestration._patch` | 编排假函数清单（未 mock 写盘，因快照本不写） | `_patch` 增加 `merge_history` 桩 + 捕获调用（date/values）断言接线；防止测试触碰真实 data/history.json |
| `tests/test_phase15.py::TestOpeningEntry::test_main_orchestration` | main 编排冒烟（fetch/render/save 全桩） | 同上：补 merge 桩/捕获断言 |

## 设计决策

| # | 决策 | 默认 | 说明/备选 |
|---|---|---|---|
| R1 | **新增 analyzer `merge_history(date, values)`**：按 date 合并写——载入该日期现有行（load_history 投影后具备全 10 键），仅把 values 中**非 None** 的键（大写自动转小写）更新进去；无该日期行则新建；原子写 + 90 天裁剪。`append_history`（整行覆盖）保留给 daily 定稿 | 采纳 | 备选：给 append_history 加 merge 参数（污染既有 7+ 调用/测试语义）；备选：独立盘中文件（见 R9 拒绝理由） |
| R2 | 盘中行 = 各入口**市场子集**（a-share: sh/sz/cyb；us: gspc/ixic；alt: gld/btc），非"每次 10 个" | 采纳 | PRD F1 字面修正如验收 F1'；全 10 键需改取数层，拒绝（超范围） |
| R3 | 写入值 = 该时点价格（snapshot: `fetch_all` 最新价；opening: `quotes[sym]["current"]`）；**opening 不写 VIX**（09:45 北京 = 美东 D-1 21:45，VIX 实时≈美东 D-1 收盘，会与 D-1 行重复/污染趋势图末点） | 采纳 | 备选：opening 连 VIX 一起写（趋势图出现同值重复点，拒绝） |
| R4 | **读时守卫**：daily_report 与 snapshot_report 在 `load_history()` 后剔除 `date == 自身运行日期` 的行再交给所有消费方；写（append/merge）一律在各自计算完成后 | 采纳 | 无守卫则盘中行污染自身告警窗口/连涨/趋势图（盘点 3）；快照注释「文件恒无当日行」以守卫形式保留 |
| R5 | **web 前值兜底（改 `web/app.py` `_compute_latest`）**：最新行某符号为 None（该市场未开盘/已收盘，如北京 09:45-21:30 的美股/波动率列）→ 值回填**最近非空行**该符号值、`change_pct=None`（前端显示数值 + "—"涨跌幅） | 采纳 | **与 PRD「web 不改」冲突，需用户确认**：不兜底则每日北京时段美股/波动率/另类面板整列 "—" 约 12 小时（fmtNum/fmtPct 对 null 渲染 "—"），较 feature 前（显示昨收）明显劣化 |
| R6 | daily_report 加读时剔除守卫（同上 R4 的一份改动落在 daily main） | 采纳 | 与 PRD「daily_report 不改」冲突：daily 未剔除时会读到美股 D 午盘盘中值（盘点 3），趋势图末点 ≠ 正文收盘价；守卫 2 行使其恢复 feature 前"当日行排除"语义 |
| R7 | 涉及开盘/快照的文档同步记录**决策反转**：`opening_analyzer.py` 模块 docstring（删"零持久化"）、`docs/architecture.md` 决策表、`AGENTS.md` 项目地图、session 记忆（决策 C/快照只读原则更新） | 采纳 | — |
| R8 | PRD 验证命令修正：history.json 是列表，取末行 `d[-1]["date"]`（见验证命令） | 采纳 | — |
| R9 | 拒绝备选「独立盘中文件（如 data/intraday.json）+ web 双源」 | — | 与 PRD F1/F2 字面（写入 data/history.json）冲突；需 web 叠加逻辑且盘中行污染同样存在；合并进同一行的设计已把污染隔离在读时守卫内 |
| R10 | 取数失败降级：某 run 全源失败（values/quotes 空或全 None）→ merge 空操作（无键可写、不报错、退出码恒 0） | 采纳 | 复用 fetch 容错 + merge 非 None 过滤天然达成 |

## 涉及文件

| 文件 | 改动 |
|---|---|
| `src/analyzer.py` | +`merge_history(date, values)`（append_history 旁，复用原子写/裁剪模式） |
| `snapshot_report.py` | main：load_history 后剔除自身 date 行（R4）；main 末尾 auto_commit_push 前调 `merge_history(date, values)`（R2 子集） |
| `opening_analyzer.py` | main 末尾 auto_commit_push 前：由 quotes 取市场子集 current → `merge_history(date, values)`（R2/R3）；模块 docstring 去"零持久化"（R7） |
| `daily_report.py` | main：load_history 后剔除自身 date 行（R6，约 1-2 行） |
| `web/app.py` | `_compute_latest`：最新行缺失符号回填最近非空值、change None（R5，约 6 行） |
| `tests/test_analyzer.py` 或新 `tests/test_merge_history.py` | merge_history 单元测试 |
| `tests/test_phase15.py` | `test_zero_persistence` 反转 + 编排测试补桩/捕获 |
| `tests/test_phase7.py` | 编排 `_patch` 补 merge 桩 + 接线断言 |
| `tests/test_phase27.py` | `test_snapshot_passes_history` 断言更新（读时剔除 + 写序） |
| `tests/test_web.py` | `/api/latest` 稀疏行前值兜底用例 |
| `docs/architecture.md`、`AGENTS.md`、`docs/pitfalls.md` | 决策反转记录 + 坑点（merge 语义/读时守卫/盘中行窗口） |
| 记忆（ctx_memory） | #20/#23 相关条目更新为"盘中合并写 history、收盘语义读时剔除" |

不改：`src/reporter.py`、`src/fetcher.py`、`src/alerter.py`、前端 `index.html`、`config.json`、`data/*`（运行时产物）。

## 实施步骤

### 步骤 1：analyzer 新增 `merge_history(date, values)`
- 位置：`append_history` 旁（analyzer.py ~615 后）。
- 语义：`records = load_history()`（投影后全 10 键）；`updates = {k.lower(): v for k, v in values.items() if v is not None and k.lower() in {10 个历史键}}`；行存在 → `row.update(updates)`，不存在 → `{"date": date, **{k: None for k in 10 键}, **updates}`；裁 90；同款 tmp + os.replace 原子写。`date` 冲突行仅一条（先按 date 去重再写，幂等）。
- 验证：`venv/Scripts/python -m pytest tests/test_merge_history.py -v`（或并入 test_analyzer 对应类）。

### 步骤 2：snapshot_report 接线（merge + 读时剔除）
- main：`history = load_history()` 后加一行 `history = [r for r in history if r.get("date") != date]`；`run_alert_checks`/`save_snapshot` 之后、`auto_commit_push` 之前加 `merge_history(date, values)`（导入自 analyzer）。
- 验证：`venv/Scripts/python -m pytest tests/test_phase7.py tests/test_phase27.py -v`（更新后的断言）。

### 步骤 3：opening_analyzer 接线 + 测试反转
- main：`save_opening` 后、`auto_commit_push` 前：
  ```python
  sub = {"SH", "SZ", "CYB"} if market == "a-share" else {"GSPC", "IXIC"}
  hist_values = {s: quotes[s]["current"] for s in sub if s in quotes and quotes[s].get("current") is not None}
  if hist_values:
      merge_history(date, hist_values)
  ```
  （docstring 同步 R7）
- `test_phase15.py`：`test_zero_persistence` 反转——monkeypatch `an.HISTORY_FILE` 到 tmp，断言 main 后该文件出现 date 行且 sh/sz/cyb=桩值、context 目录仍零写入；两个编排测试补 merge 桩/捕获。
- 验证：`venv/Scripts/python -m pytest tests/test_phase15.py -v`。

### 步骤 4：daily_report 读时剔除（R6）
- main：`history = load_history()` 后加 `history = [r for r in history if r.get("date") != date]`（date 为既有 `get_us_eastern_date()` 变量；剔后行集供 build_statuses/compute_correlation/_is_us_duplicate_day/run_alert_checks 使用，append 仍在末尾写全量定稿）。
- 验证：`venv/Scripts/python -m pytest tests/test_phase8.py tests/test_phase12.py tests/test_phase24.py -v`（编排测试已 mock load_history/append_history，应零回归；实况验证见命令 4）。

### 步骤 5：web 前值兜底（R5，待用户确认）
- `_compute_latest`：`cur = last.get(key)` 为 None 时，向前找 records 中最近非空该键值作 `value`，`change_pct=None`（不再用相邻行计算）；其余逻辑不动。
- 新增：稀疏行（末行仅 sh/sz/cyb）→ GSPC value=上一行值、change None；末行全空 → 现状。
- 验证：`venv/Scripts/python -m pytest tests/test_web.py -v`。

### 步骤 6：全量回归 + 文档/记忆同步（R7/R8）
- `venv/Scripts/python -m pytest tests/ -v` 全绿；实况 smoke（见命令 4-6）；更新 opening_analyzer docstring、architecture.md（决策表 R1-R6 + 反转记录）、AGENTS.md 地图、pitfalls.md；更新 ctx_memory 相关条目；按 AGENTS 规范写 `journal.md`。

## 测试设计清单

1. **merge_history**：新键无行 → 新建含 updates + 其余 None；行已存在 → 仅更新非 None 键、保留他键（A股收盘后美股开盘不抹 A股）；同日重复 merge 幂等（无重复行）；None 值键不写；date 类型字符串化；90 天裁剪；.tmp 无残留；坏文件（损坏 JSON）容错重建。
2. **opening 接线**：a-share → merge 收到 (北京date, {SH,SZ,CYB current})；us → {GSPC,IXIC}；quotes 缺某键/全空 → 不写/空操作；context/ 目录零写入（保留原零持久化约束中 context 部分）。
3. **snapshot 接线**：a-share midday → merge 收到 (date, {SH,SZ,CYB})；us open → {GSPC,IXIC}；alt → {GLD,BTC}；merge 发生在 run_alert_checks 之后（写序断言）。
4. **读时剔除**：snapshot/daily 传给 build_statuses/run_alert_checks 的 history 不含自身 date 行（phase27 断言更新）。
5. **web 兜底**：末行稀疏 → 缺失符号回填最近非空值 + change None；末行正常 → 行为不变（既有 test_api_latest 回归）。

## 验证命令（PRD 验证段修正版）

```bash
# 1) 开盘 A 股实跑 → history 末行日期 = 北京今天、含 sh/sz/cyb
venv/Scripts/python opening_analyzer.py --market a-share
venv/Scripts/python -c "import json;d=json.load(open('data/history.json',encoding='utf-8'));print(d[-1]['date'],d[-1].get('sh'))"

# 2) 快照 A 股午盘实跑 → 末行仍为今天且 sh/sz/cyb 更新、无重复行
venv/Scripts/python snapshot_report.py --market a-share --time midday
venv/Scripts/python -c "import json;d=json.load(open('data/history.json',encoding='utf-8'));print(len([r for r in d if r['date']==d[-1]['date']]),d[-1].get('cyb'))"

# 3) 幂等：连续跑两次快照 → 同日仅 1 行
# 4) daily 实跑 → 报告/趋势图末点与正文收盘一致（读时剔除生效），history 定稿行全 10 键
venv/Scripts/python daily_report.py

# 5) web：另起未缓存端口（pitfalls：8000 常被占用）
venv/Scripts/python -m uvicorn web.app:app --port 8001
# GET /api/latest → indices 中未开盘市场符号回填最近非空值、change_pct=null（R5）
# 6) 全量测试
venv/Scripts/python -m pytest tests/ -v
```

## 风险与边界

1. **决策反转波及**：`docs/architecture.md` 决策表与 AGENTS 地图明示"开盘零持久化/快照不写历史"（及会话记忆 #20/#23）；不同步会产生与实现矛盾的文档/记忆。步骤 6 强制执行。
2. **盘中行瞬时语义**：键 D 存活期（约 24h）内 history[-1] 为盘中值——已由读时剔除（R4）把 daily/snapshot 计算隔离；**离线只读方**（backtest、相关性脚本）若恰在盘中窗口运行会看到盘中行（终态文件自愈；backtest 为手动只读工具，风险可接受，记入 pitfalls）。
3. **web 兜底（R5）语义**：回填值显示无当日涨跌幅（"—"），不虚构 0.00%；若用户选择 PRD 字面不改 web，须接受北京时段约 12h 的 "—" 列（决策 R5 备选）。
4. **非交易日误触发**：opening/snapshot 无交易日判断（既有决策 J：周末不触发属 cron 调度配置）；若周末被触发会以最近收盘值写入新 date 行造成重复行——与既有快照语义一致，不改（记入 pitfalls）。
5. **AUTO_PUSH**：盘中每次运行都会 commit+push（含 git add -A 扫入的未提交改动，pitfalls 既有坑）；频率由 cron 次数决定（每日 ≤6 次），可接受。
6. 不改 `save_last_values`：盘中 run 不更新缓存（告警基准仍为上一收盘日，避免盘中基准漂移）；web 涨跌幅来自 history 相邻行而非缓存，不受影响。
