# 执行日志 · 前端 Bento 重构

> 对应计划：`tasks/2026-09-11-frontend-bento-redesign/plan.md`
> 执行者：编码 Agent（Phase 3 Step 3.6–3.7）

## 会话记录

### 2026-09-11 22:0x–23:0x

**目标**：把 `web/` 看板从「单列流式 section 堆叠」重构为效果图所示的**三栏 bento 栅格仪表盘**；1920×1080 下 9 类模块 ≤1.15 屏内呈现、无横向溢出、Console 无 error、深浅双主题正常。

**操作（按 plan 步骤）**：

| 步骤 | 内容 | 状态 |
|---|---|---|
| Step 1 | `web/app.py`：新增纯函数 `_sector_payload(ctx, key)`，`_load_sector_heat()` 改为其薄封装（签名/行为不变）；`api_latest` 改为**只取一次** ctx、返回 `sector_heat` + **`us_sector_heat`**（空历史提前 return 分支也补齐）；新增 `/api/macro`（`_MACRO_DEFAULT` / `_load_macro_stocks` / `_load_macro` / TTL 90s 缓存）；`/api/history` 上限 `le=90 → 365` | ✅ |
| Step 2–3 | `style.css` 卡片 token 化（`--radius-card` / `--card-shadow` / `--card-glow`，light+dark 双套）+ `index.html` 加 `.dash > .row-kpi/.row-main/.row-3/.row-news` 栅格骨架 + 顶栏搜索/数据日/通知/头像 + 侧栏 7 项与底部市场状态 | ✅ |
| Step 4 | 趋势**四图合一**：单 `canvas#chart-main` + `#trend-tabs`（4 类别）+ 7D/30D/90D/**1Y**；`buildLineDataset` 加面积渐变（`createLinearGradient`），`buildLineOptions` 显式 `maintainAspectRatio:false`；**删除** `.chart-box canvas{…!important}`（C2 根治） | ✅ |
| Step 5 | KPI 卡 4 张（`#lede{display:contents}` 与 promo 共处 5 列栅格）+ sparkline 高度 40→56、宽度自适应；自选列表改「名称/现价/涨跌幅 + 纯 CSS 百分比迷你条」；**修 C6** `isWeekendDate()`（`Date.UTC`+`getUTCDay`） | ✅ |
| Step 6 | 市场概览 **6 小卡**（美股/A股/黄金 ×10 + 美元指数/10Y美债/原油）+ 美股行业板块横幅条（条宽 = `|Δ|/max|Δ|`） | ✅ |
| Step 7 | 3 个静态占位模块（`PLACEHOLDERS` 常量 + `data-placeholder="1"`，文案「数据未接入」）+ 侧栏「市场已开盘/休市 + 北京时间」（`Intl.DateTimeFormat` Asia/Shanghai，纯前端） | ✅ |
| Step 8 | `/api/macro` 端点 + 前端并行取数（12s 超时兜底，失败降级占位） | ✅ |
| Step 9 | `le=365`；**同步改测试** `days=91` 由 422 → 200、新增 `days=366 → 422`；x 轴 `maxTicksLimit` 随 `state.days` 自适应（7/10/14） | ✅ |
| Step 10 | （可选）1Y 数据回填 | ⏸ 未执行（见「未解决问题」R4/R5） |
| Step 11 | 响应式 1500/1299/768/480 四断点 + `verify_ui.py` 三视口验收 | ✅ |
| Step 12 | 追加 `docs/pitfalls.md`（14 条）+ 本日志 | ✅ |

**改动文件清单**：

| 文件 | 规模 | 说明 |
|---|---|---|
| `web/app.py` | +≈110 行 | `_sector_payload` / `us_sector_heat` / `/api/macro` / `le=365` |
| `tests/test_web.py` | +≈160 行、改 1 处断言 | 48→59 条（us_sector_heat ×3、macro ×7、days 边界） |
| `web/templates/index.html` | 141 → 262 行 | bento 骨架 + 9 类模块 + 3 个 `data-placeholder` |
| `web/static/style.css` | 475 → 约 520 行 | 卡片 token 重写 + 栅格 + 断点重写；删旧 `.chart-box`/`.lede-cell`/`.charts-grid` 等失效规则 |
| `web/static/app.js` | 823 → 约 700 行 | 四图合一 + 6 小卡 + 迷你条 + 占位 + 修 C6；删分组可见集/指标 chips/表格排序 |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 新增 ≈380 行 | Playwright 验收脚本（**有意入库**，可复跑） |
| `docs/pitfalls.md` | +17 行 | 新增「模块 web/（Bento 栅格重构）」章节 |
| `seed_history.py` | 未动 | Step 10 未执行故未触及 |

> ⚠️ **本会话期间外部 Hermes「每日数据更新」cron 连做 4 次 `git add -A`**（`9571bf5`/`2b980cd`/`9fc9b1d`/`cffe16f`），把写到一半的前端与后端改动直接提交入库。故当前 `git diff` 仅剩：本日志、`docs/pitfalls.md`、`verify_ui.py`、`app.js`（原地切 tab 5 行）、`style.css`（`#sidebar z-index` 2 行），以及**非本任务改动**的 `context/2026-09-03.json`（cron 自己重生成的生成物，勿混入本次提交）。

**验证结果**：

1. `venv/Scripts/python -m pytest tests/test_web.py -q` → **59 passed**（Step 1 后）
2. `venv/Scripts/python -m pytest tests/ -q` → **459 passed, 0 failed**
3. `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` → **ALL PASSED**
   - 三视口（1920×1080 / 1280×720 / 375×812，DPR=1）各 17 条：无横向溢出、canvas 位图==显示尺寸、卡片 token、KPI 4 张、概览 6 小卡、A股/美股板块有行、自选可见有行、3 占位文案、4 个 tab、`isWeekendDate` 三态、顶栏数据日
   - 1920 专项：`scrollHeight` **1235 ≤ 1240**（基线 **2632**，≈2.44 屏 → **1.14 屏**）、row-kpi 5 列 / row-main 2 列 / row-3 3 列 / row-news 4 列、主图容器 432px（40vh）、KPI ≥260×96、侧栏贴底、层级 100/60/55、市场状态+北京时间、主题切换（`data-theme`+`localStorage`+卡片底色三态）、**4 个 tab 逐个切换图表可用**、**console error = 0**
   - 1Y 档：canvas 尺寸仍一致、标签「近 1 年」
   - 375 档：侧栏 `fixed` 抽屉（初始 -240 → 点击后 left=0）、主图 280px、无横向溢出
   - 实测报告与截图落 `%TEMP%\marketpulse-verify\`（仓库内无二进制产物）
4. 静态核验：`grep -c data-placeholder web/templates/index.html` = **3**；旧选择器（`charts-grid`/`lede-cell`/`group-bar`/`symbol-filter`/`chart-watchlist`/`th-sort`/`renderWatchChart`）残留 **0**
5. 真实数据实测（TestClient + 本机联网）：`/api/latest` → `sector_heat.gainers`=5、`us_sector_heat.gainers`=5；`/api/macro` → `DX-Y.NYB 99.028 (-0.06%)`、`^TNX 4.926 (-0.36%)`、`CL=F 99.68 (-2.73%)`

**遇到的问题（含根因与修法）**：

1. **plan 与实测不符（3 处，已在开工时报告）**
   - `us_sector_heat.gainers` 恒为 **5** 条（取数层即 Top5），非 plan 所称 11 只 SPDR ETF → Step 6 断言由「渲染 8 行」改为「渲染 `min(8, 实际)` 行」，真实数据下为 5 行。
   - `context/2026-09-11.json` 是**空壳**（板块两键均 0 条）→ `_load_latest_context` 回退到 **2026-09-10**（既有语义，非本次引入）；前端板块卡显示 09-10 数据。
   - plan §12 的「删除 `_dbg/measure.py`、`shot-*.png`（需人确认）」已失效：`_dbg/` 现仅 3 个 json、工作区 clean → 未做删除动作。
2. **`app.js` 整文件写入被空闲超时中断，文件被截断为 0 字节**（`Length=0` 但 `LastWriteTime` 已更新）。修法：改为分 3 块写入（头部 + `// __PART2__` 占位 → replace 占位续写两块）；被取消后 `Get-Item Length` 核实。
3. **1920 总高 1329 > 1240**：根因是 `row-news` 被「告警卡（2 条真实告警 ≈244px）」撑高，而非图表。修法：`.alert-list{max-height:200px→132px}` + `.alert-card` 内距、表格 `td` 内距、`.card h2` 间距、`.mini-card` 内距各收一点、`.main` padding `24/32/32 → 20/28/24` → **1329 → 1235**（未动 plan 强制的 432px 主图高度）。
4. **375 横向溢出 447 > 375**：根因是顶栏（brand ≈190px + 数据日 + 通知 + 头像 + 刷新 + 菜单）。修法：`≤768` 隐藏品牌副标、`≤480` 隐藏 `brand-mark`/头像/通知占位。
5. **`#sidebar` 桌面档 `z-index: auto`**：基础规则漏写（仅 768 媒体内有 60）。修法：基础补 `z-index: 60`。
6. **验收脚本自身 4 个假阴性**（均已修，知识点已入 pitfalls）
   - `.card` 取样命中 promo 卡（渐变无 `background-color`）→ 改测 `#overview`；
   - tab 断言引用被重建的旧按钮节点 → 实现改为**原地 `classList.toggle`**（不再重建 tab DOM），测试也改为每轮重查；
   - 抽屉 `transform` 在 `click()` 同帧读取 → 拆成两次 evaluate 并等 600ms；
   - 首屏只等 4.5s 读到 `#watchlist-section.hidden`（AkShare 冷启动）→ 改 `wait_for_selector('#watchlist-section:not(.hidden)')`。

**与 plan 的偏差（需需求方确认）**：

| # | 偏差 | 理由 |
|---|---|---|
| D1 | 趋势 tab 用**原 4 组**（美股大盘 / A 股大盘 / 波动率 / 另类资产），未采用 plan 字面的「股票/波动率/宏观/另类资产」 | 「四图合一」语义即原 4 图 → 4 tab；宏观数据只在 `/api/macro`（非 history），做成 tab 会恒空。4 tab 全部有数据，且满足「切换 4 个 tab」验收 |
| D2 | `/api/macro` 增加**内置默认 3 标的**（plan 只写 env > `config.json`） | 不加默认则 3 张宏观小卡永远是「数据未接入」；宏观是只读行情、无「未配置即隐藏」语义。未改 `config.json`（遵 AGENTS.md） |
| D3 | `.row-news` 定为 **4 列**（告警 + 最新资讯 + 资金流向 + 风险偏好） | plan §5.1 只定义 row-news=最新资讯，未规定告警/资金流向/风险偏好归属；4 列可在 1240 高度预算内让 9 类模块同屏 |
| D4 | **删除**原「10 指数概览表 + 排序 + 指标 chips(`symbol-filter`) + 分组可见集(`group-bar`)」 | plan Step 6 要求市场概览改 6 小卡；被替代后这些控件无宿主。10 个标的仍全部可达（4 个 tab + KPI 卡 + 6 小卡） |
| D5 | 行业板块卡「查看全部 →」为 `disabled` 占位 | 无对应数据源（Q2 静态占位策略） |

**未解决问题 / 下次注意**：

- **R4（1Y 期望管理）**：`retention` 只在**写**时裁剪，放宽 `le=365` **不会扩已有 90 行**（实测 2026-05-14 → 2026-09-11）。当前 1Y 视图只有 4 个月数据，需 Step 10 回填才能补齐。
- **R5（回填前置缺陷，未修）**：`seed_history.py:36-38` 直连 `query1`（违反 `pitfalls.md:15` 双主机轮换纪律）、`:50` 用 `.astimezone()`（本地=北京）算日期而 history 口径是**美东** → **不修不要跑回填**。
- **retention 未生效于 1Y 补齐**：本次未改 `config.json`、未改 `.env`（遵 AGENTS.md「不修改生产配置」）→ 需由需求方设 `HISTORY_RETENTION_DAYS=365`（`src/config.py` 已有 ENV_MAP 映射）或手改 `config.json` 的 `history.retention_days`，否则 90 天滚动仍会把历史裁回 90 行。
- **`prd.md` 缺失**：plan §0 建议由需求方把「§1 目标 + §2 验收」反写成 `tasks/2026-09-11-frontend-bento-redesign/prd.md` 归档。
- **`context/2026-09-03.json` 有非本任务改动**（cron 重生成），提交本任务时勿一并带入。
- **R8/R9 已按计划容忍**：`config.json` 的 `watchlist.stocks` 只有 1 只（`515300.SS`），自选卡已加 `min-height:240px` 防塌陷；该沪 ETF 日线自 09-03 起停更（`pitfalls.md:17`），迷你条/趋势基于旧序列，**非本次引入**。
- **下次注意**：改前端后必须 `Ctrl+Shift+R` 或换端口验证（Jinja2 模板缓存 + 跨端口 CSS 缓存，`pitfalls.md` 已有两处记载）；`verify_ui.py` 每次运行自动挑空闲端口，天然规避该问题。

---

### 2026-09-11 23:0x–23:5x · Step 10（1Y 历史回填）

**目标**：让 1Y 视图真的有 ~1 年数据（原仅 90 行 = 2026-05-14 起 4 个月）。

**需求方决策**：① 授权执行者改 `config.json`；② 采用**方案 B**（新增回填脚本，不动早期 `seed_history.py`）。

**只读核对先行（关键）**：核对实际代码后发现 plan §7 Step 10 / §11 R5 **只识别了 2 个缺陷，实际有 5 个**，其中 3 个会破坏生产数据：

| # | plan 说法 | 实测 |
|---|---|---|
| S1 | 「统一改 `_EASTERN_TZ`」 | **半错**：history 日期口径是**按符号所属市场时区**（`get_market_date`：a-share→上海、us→美东）。统一转美东会让 A 股（上证 09:30 北京 = 前日 21:30 ET）整体**早一天** |
| S2 | 未提及 | `HISTORY_MAX = retention_days = 90`，每次写都 `records[-90:]` → 回填**立刻被裁掉** |
| S3 | 未提及 | `append_history` 默认**整行覆盖**；seed 新行只有 4 键起步 → 拉取失败的键不存在，会**抹掉既有值** |
| S4 | 未提及 | `seed_history.py:106` 用**小写键**整文件覆盖 `last_values.json`，而消费方按**大写 symbol** 取值 → 跑一次就让次日涨跌幅退化为"首次运行" + 告警基准全失效 |
| S5 | 未提及 | 逐条 `append_history` 重写整个文件 90 次 + 键序不一致 |

**改动**：

| 文件 | 内容 |
|---|---|
| `config.json`（gitignore 排除） | `history.retention_days` `90 → 365`；实测 `HISTORY_MAX = 365`；`.env` 无 `HISTORY_RETENTION_DAYS` 覆盖；`pytest` 不受影响（conftest 隔离） |
| `scripts/backfill_history.py`（新增 ≈230 行） | `--dry-run` / `--symbols` / `--range`；走 `_yahoo_chart_get`（双主机轮换）；按 `A_SHARE_SYMBOLS` 分市场时区；**只新增 date 不存在的行**；丢弃「仅 BTC 有值」的非交易日；经 `merge_history` 按 date 合并；收尾 `ensure_sorted()` 按 date 升序重排 + 断言；**不调用 `save_last_values`**；源间节流 0.5s |
| `data/history.json` | 90 → **263 行**（新增 173 行：2025-09-11 ~ 2026-05-13，与既有段无重叠无缺口） |
| `tasks/.../verify_ui.py` | 新增「1Y 档主图实际渲染 ≥200 个交易日」断言 |
| `docs/pitfalls.md` / `docs/commands.md` / `AGENTS.md` / `docs/architecture.md` | 记录回填纪律与新命令 |

**执行中发现并修复的 bug（S6，我引入的）**：`analyzer.merge_history` 对不存在的 date 只做 `records.append(...)`、**不排序**（依赖"每天只写今天"使末尾天然有序）。回填历史日期导致整段旧数据被 append 到尾部 → 首次写入后实测打印 **`2026-05-14 ~ 2026-05-13`**（即 `/api/latest` 会把最旧日期当"最新日"）。修法：收尾 `ensure_sorted()` 重排 + 原子写 + 断言，现 `严格升序 True / 无重复 True`。**该坑已写入 `pitfalls.md`**。

**另一处必须处理的源问题**：`BTC-USD` 是 7×24，Yahoo 近 1y 返回 **366 个自然日** bar（比 `^GSPC` 的 252 个交易日多 114 个）→ 直接回填会写出 ~110 个「只有 btc 有值」的纯周末行（超 `HISTORY_MAX`、偏离交易日口径、切断 `compute_correlation` 收益链、夸大回测样本）。修法：某天若除 `BTC` 外无任何标的有值 → 整行丢弃（实测丢弃 **104** 行）。

**验证结果（全部实跑）**：

| 验收项 | 实测 |
|---|---|
| 既有 90 行逐键比对（非空值不得变/不得丢） | 改动数 **0** |
| `data/last_values.json` 未被动 | SHA256 `4831efc3…` 前后一致；`date` 仍 `2026-09-10` |
| date 严格升序 / 无重复 | `True` / `True` |
| 新增周末行 | **0**（回填前后均为历史遗留的 4 个） |
| 日期口径抽查（金标准） | `2025-12-25` 仅 `sh/sz/btc`（美股圣诞休市）；`2026-01-01` **整行不存在**（中美双休）；`2026-01-02` 仅美股类（中国元旦假）；`2026-02-17` 仅美股类（春节） |
| `/api/history?days=365` | **259 dates**（2025-09-11 ~ 2026-09-11）；`gspc 252/259`、`vix 251/259`、`cyb 86/259` |
| `/api/history`（默认 30） | 仍 30 dates |
| 涨跌幅消费点 | `GSPC +1.06%`、`SH -1.18%`（基准 `2026-09-10`）→ 正常，**非"首次运行"** |
| `pytest tests/` | **459 passed** |
| `scripts/backtest.py` | 有效交易日 **261**、触发事件 **304**、0.78s（原样本 90） |
| `verify_ui.py` | **ALL PASSED**（含 1Y 档 257 点/条、`scrollHeight` 仍 1235） |

**偏离 / 未闭环**：

1. **未跑 `AUTO_PUSH=0 daily_report.py` 冒烟**：当前为**美东盘中**，跑它会用盘中价覆盖 `data/last_values.json`（`09-10 → 09-11 盘中`），破坏"基准不变"基线、并可能让次日涨跌幅基于盘中值。改用**非破坏性等价验证**（直接复算 `daily_report` 同口径的 09-11 涨跌幅，结果正常）。今晚 Hermes cron 会真实跑通该路径。
2. **CYB（`399006.SZ`）回填段为空**：同一条 `range=1y` 请求，`^GSPC`/`^IXIC` 各 252 天、`000001.SS`/`399001.SZ` 各 243 天，而 `399006.SZ` **只返回 1 天** → 新增段该列全空（`cyb 86/259`）。属外部数据源缺口；如需补齐须改走 AkShare `stock_zh_index_daily(symbol="sz399006")`（含 Sina 源挂起风险，需复用 `fetch_sector_heat` 的 daemon 线程限时模式）。
3. `seed_history.py` / `seed_history_market.py` **未修改**，已在 `AGENTS.md` / `docs/pitfalls.md` 标注"勿再使用"。
4. **`plan.md` 未改**：我曾在 `plan.md` 追加「附录 A · Step 10 执行前只读核对」（已被提交为 `7efc75b`），但架构侧在 `6808ca4` 按新任务 `2026-09-11-glassmorphism-fix/plan.md` §0 的「**不要再向旧 plan 追加内容**」将其还原。→ 本任务记录以 `journal.md` 为准，不再改 `plan.md`。
5. `reports/backtest_report.md` 被回测重新生成（正常产物）。
