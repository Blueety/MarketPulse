# journal — 市场日历「事件结果值」层（actual / forecast / previous）

- **任务档**：`tasks/2026-09-19-timeline-event-values/`（`plan.md` 定稿，§11 五个决策点全部采纳推荐项）
- **执行日期**：2026-09-19（下午至傍晚，本机直连）
- **角色**：Phase 3 Step 3.6 执行者（按 plan 实施 + 验证，不做架构决策）

## 1. 目标

`/timeline`（侧栏「市场日历」）的事件行只有名字、没有数值（用户原话：「加息议会没说加息多少，
CPI 公布没说公布了多少、与预期差多少」）。本轮新增**结果值层**：事件行渲染
`实际 / 预期 / 前值 / 变动 / 偏离预期`。

## 2. 改动文件清单

### 新增
| 文件 | 内容 |
|---|---|
| `src/econ_values.py`（约 330 行） | TradingView 经济日历抓取（按月分段）+ `kind -> headline` 精确标题映射（PCE 首选/备选两级、GDP 按期次）+ `date`(UTC) → 美东日期归一 + 同日多行择优 + 只算值不写库；失败返回空 + `failed` |
| `tests/test_econ_values.py`（**25 条，不联网**） | ET 转换（跨日 + 夏令时两侧）/ 分段 / 精确匹配 / GDP 期次 / `forecast:0` vs `None` / 真实双非农择优与歧义告警 / PCE 首选优先 / 只 enrich 既有行 / `unit` 键缺失 / 整源失败 / preserve / 只 UPDATE 不 INSERT / 8 列迁移 |
| `tasks/2026-09-19-timeline-event-values/journal.md` | 本文件 |

### 修改
| 文件 | 改动 |
|---|---|
| `src/storage.py` | `_SCHEMA` 的 `econ_events` +8 列；新增 `ECON_VALUE_COLS` + 幂等 `_migrate_econ_events()`（`init_db()` 内调用）；`_ECON_COLS` 投影扩到 17；新增 `update_econ_event_values()`（preserve：逐列 `COALESCE(新, 旧)`；**只 UPDATE 不 INSERT**；全空值不写） |
| `scripts/sync_econ_calendar.py` | 新增"抓值 → join → 落库"步骤（**在骨架落盘之后**）+ `--skip-values` + `[values]` 小结行 + `failed` 汇总归一化 `tradingview`；docstring 补用法与顺序硬约束 |
| `src/timeline.py` | `build_timeline()` 的 item **逐键显式**加 8 个值层键；`SOURCE_NOTES` 新增第 3 条（TradingView 值层，共 4 条） |
| `web/static/timeline.js` | 值片段渲染（`fmtNum/trim2/signedTrim/deltaText/missText/valueItems/valueHtml`）；`eventHtml(ev, pending)` 增参；`matchMedia('(max-width: 767px)')` 两态 + `change` 重渲染 |
| `web/static/style.css` | 新增 `.tl-val` 段（1 条规则 + 5 行注释说明为何必须 `nowrap`、为何不设 height） |
| `web/templates/timeline.html` | 「口径与来源」新增 2 条（值来源 + CPI 指数水平/原始数值口径） |
| `verify_ui.py` | 新增 `assert_timeline_values()`（`EV-1 ~ EV-11`，16 条 check）+ main 接线 |
| `docs/architecture.md` | 模块表补「结果值层」行（并补 `src/storage.py` 的 econ 表与值层列说明）；关键决策表补 2026-09-19 行 |
| `docs/commands.md` | 快速检查表 +2 行（值层单测 / 独立核算）；「何时跑什么」补值层一行、事件日历 cron 行补 `[values]` 判据与 `--skip-values` |
| `docs/pitfalls.md` | 新增「数据层（结果值层 TradingView，2026-09-19）」小节（5 条实测坑） |
| `AGENTS.md` | 更正 `data/marketpulse.db` 的入库状态描述（见 §5.6） |
| `data/marketpulse.db` | 迁移 +8 列 + 29 组值落库（**tracked 文件，随提交上线**） |
| `data/... econ_event_news` | 真跑时叙事层顺带刷新 13 条（`--skip-news` 未加，见 §4.4） |

**未动**（plan §5「不动」清单逐条核对）：`web/app.py`、`src/econ_calendar.py`、`/`、`/macro`、
`/macro/cn`、`data/history.json`、既有 `TL-*` 断言语义（只增不改）。

## 3. 实测证据（步骤 0，探针落 `%TEMP%\mp-ev\`，不落仓库）

### 3.1 端点与字段（`tv_shape.py` / `tv_titles.py`）
- `GET economic-calendar.tradingview.com/events?from&to&countries=US` + `Origin`/`Referer`
  → **HTTP 200 / 1.67s / 229654 bytes**，外层 `{status, result[]}`。
- **`unit` 是"键缺失"而非 null**：近 13 个月 4658 条里**只有 2072 条带该键**，
  值只有 `%`(1807) / `$`(206) / `cf`(59)；`CPI` 与 `Non Farm Payrolls` **连键都没有**。
- 标题枚举核实：`PPI MoM`（不是 `PPI`）；`Non Farm Payrolls`（另有 `... Annual Revision` 干扰项）；
  `GDP Growth Rate QoQ Adv / 2nd Est / Final`；`Core PCE Price Index MoM`（另有 `PCE Price Index MoM`）；
  `Retail Sales MoM`；`Industrial Production MoM`；`Fed Interest Rate Decision`；`CPI`（另有 `CPI s.a` 干扰项）。

### 3.2 join 命中率基线（`join_probe.py`，`past_days=120 / future_days=60`）
```
库内 103 条 → 去重后 103 条 → 窗口内 41 条
命中率：过去 26/26（100.0%，零容差）  未来 7/15  歧义合并 0
未命中 8 条全部是 ≥2026-10-28 的未来事件（与 plan §2.2 的"未命中 8 条 ≥2026-10-28"逐条一致）
```
> 注：plan 记的是"过去 33/33"，本轮按 120/60 窗口复跑得 **26/26**（窗口宽度不同，**结论一致**：
> 零容差 100% 命中、未命中全是未来尾段）。真正决定实现的是"过去事件零容差全中"这条。
> **已把值层窗口与页面默认窗口取齐（90/30）**，故步骤 3 的基线口径是 **29 条全命中、其中 22 条带 actual**。

## 4. 验证结果

### 4.1 步骤 1（storage 迁移）— 通过
```
迁移前 cols(9) → 迁移后 cols(17)（含 8 新列）
count_econ_events(): 103 → 103（不变）
再跑一次 init_db()：列完全相同（幂等）
原 9 列对备份逐行相同（sha256[:16] c3774a1b8bc12a15，diff 0）
history 2675 行 / econ_event_news 13 行：不变
临时库：新库直接 17 列；update 只命中已有行（2 组，不建行）；actual=None 不抹 334.98；全空 → 0 组
```

### 4.2 步骤 2（模块 + 单测）— 通过（25 passed）
首轮 24 passed / 1 failed：`collect_values` **只把窗口用在抓取上、没用在骨架行上**
（窗口外的骨架行仍会被 join）⇒ 修在模块侧（`in_window()` 独立成函数，sync 日志与 join 同源），
修后 25 passed。

### 4.3 步骤 3（sync 接入）— 通过
```
--dry-run：  [values] 值层（dry-run，不写库）：命中 29/29 条（窗口 2026-06-21 ~ 2026-10-19）
             写库核对：跑前后 sha256 相同（8a019f5cab9e5b6a）、actual is not null 仍为 0  ⇒ 零写盘
真跑 --no-push：[values] 值层：命中 29/29 条，写入库 29 组；[news] 13 条；EXIT=0
独立核算（裸 sqlite3）：count(actual is not null) = 22（== 步骤 0 的过去命中数 22）
  2026-09-16 FOMC (4.0, 4.0, 3.75, '%', 1, 'Federal Reserve', 'Fed Interest Rate Decision')
  2026-09-11 CPI  (334.98, 334.85, 333.92, None, 0, 'Bureau of Labour Statistics', 'CPI')
  2026-07-30 GDP  -> 'GDP Growth Rate QoQ Adv' / 2026-08-26 -> '2nd Est' / 2026-09-30 -> 'Final'
  过去 22 条带值层且全部带 actual；未来 7 条带值层但 0 条带 actual（符合 D-2a）
骨架 8 内容列对备份逐行相同（diff 0，仅 fetched_at 刷新）；history 2675 / news 13 不变
wal_checkpoint() 已跑（data/ 下无 -wal/-shm 残留）
```

### 4.4 步骤 4（payload 透传）— 通过
`curl /api/timeline?days=90&future_days=30`：29 事件（过去 22 / 未来 7）、**8 个值层键全在**、
`sources` 4 条（第 3 条 = TradingView 值层）、`failed: []`、非空 actual 全在过去、未来全 null。

### 4.5 步骤 5（前端）— 通过
- **`verify_ui.py` 的 `EV-*` 组：ALL PASSED（16 条 check）**
  - `EV-2` 三方对账：sqlite 22 == API 22 == DOM 22（前置 >0）
  - `EV-3` 真实数据：FOMC `实际 4.00% ｜ 预期 4.00% ｜ 前值 3.75% ｜ 加息 25bp ｜ 符合预期`；
    CPI `实际 334.98 ｜ 预期 334.85 ｜ 前值 333.92 ｜ 变动 +1.06 ｜ 高于预期 +0.13`
  - `EV-6` mock 全空值 → 29 行仍在、无 pageerror、不渲染 0
  - `EV-11` 768 参照行三词齐全 / 375 参照行只剩 `实际 334.98 ｜ 变动 +1.06`，`modes` 唯一（单份 DOM）
- **既有 `TL-*` 16 条复跑仍绿**（含 `TL-7` 无因果措辞、`TL-6` 不显示假 0.00%、`TL-8` 四视口无溢出）
- **几何实测**（`geom.py`，Chromium DPR=1）：
  | 视口 | 有值行 rowH | dayH | 值片段 | 同行 | 溢出 |
  |---|---|---|---|---|---|
  | 1920×1080 | **20** | **71.73** | 15.94 × 180.41 | 29/29 | 0 |
  | 1280×720 | **20** | **71.73** | 同上 | 29/29 | 0 |
  | 375×812 | 20/42/62/67 | 178.08 | 同上 | 2/29 | 0 |
  ⇒ 与 plan §8.2 的预测一致：**≥768 档行内追加、行高与卡片高完全不变**（`dayH 71.73` 与改造前实测值
  分毫不差）；375 档折行、卡片变高（plan §8.4 已预期，且横向溢出恒为 0）。
  截图落 `%TEMP%\mp-ev\timeline-past-{1920x1080,1280x720,375x812,1280-dark}.png`（不落仓库）。

### 4.6 全量单测
```
venv/Scripts/python -m pytest tests/ -q
721 passed, 1 failed  ← 唯一失败 tests/test_us_sector.py::TestFetchUsSectorHeat::test_volume_format
```
**基线 A/B 结论：该失败与本轮无关（既有红）**。判据两条：① 本轮 `git diff --stat -- src/fetcher.py`
为空（该用例只依赖 `src/fetcher.py` 的格式化）；② 用 `git archive HEAD | tar -x` 建隔离副本
（venv 用 junction 指回，**完全不动工作区**）跑同一用例，**HEAD 上同样失败**
（`assert '$12.0亿' == '$1.2B'` —— 期望值停留在旧的 `$B` 口径，某次"板块表列对齐"改动改了格式化函数
但没同步该断言）。**未修**（不属本轮范围，且改了就是 spread 到无关模块）。

## 5. 遇到的问题与处置

### 5.1 我自己的断言/实现问题（3 处，全部修掉）
1. **`collect_values` 窗口只卡一侧**（真缺陷）：窗口外的骨架行仍会被 join。修法：`in_window()`
   独立成函数，抓取范围与骨架筛选两侧都卡，且 sync 日志的分母与它同源。
2. **PCE「首选/备选标题」优先级没生效**（真缺陷）：`Core PCE Price Index MoM`（首选）与
   `PCE Price Index MoM`（备选）同日并存，两者择优键完全并列 ⇒ 由**上游返回顺序**决定，
   实测取到了备选（dry-run 里连续 3 条 `并列候选` warning）。修法：`pick_for` 先取
   `min(首选序号)` 把备选整批排除**再**排序；补 2 条单测（首选存在/首选缺失）。
3. **`EV-11` 断言范围两次写宽**（假红）：
   ① 375 档要求含字面「变动」，但 FOMC 的变动项按 D2.1④ 走 `加息 25bp` 文案 ⇒ 改为**文案族**判定；
   ② "全页不得含 预期/前值" 把**未来行**（待公布分支，那里本就必须带 预期/前值）判红 ⇒ 收窄到
   "有实际值的行"。另外把参照行改为**数据驱动**（取 API 里三个操作数都非空的事件，优先 CPI 2026-09-11）。

### 5.2 计划解释的两处偏差（**需你确认**）
1. **`unit` 缺失时「变动」不加 `pp` 后缀**。plan D2.1④ 原文是"其余类显示 `+0.3pp`"，但 plan 的
   硬约束 ① 又写明"`unit` 缺失不得猜单位、不加任何单位后缀"。两者在**无单位指标**（CPI 指数 / 非农）
   上冲突：`334.98 - 333.92 = +1.06` 不是"百分点"，加 `pp` 就是猜单位。
   **本轮的取舍：优先硬约束** ⇒ `unit == "%"` 才加 `pp`（PPI/GDP/PCE/零售/工业产出/FOMC），
   无单位指标显示 `变动 +1.06` / 变动 `+141`。若你要按 D2.1④ 字面统一加 `pp`，改一行即可
   （`timeline.js` 的 `deltaText`）。
2. **`EV-5` / `EV-6` / `EV-7` 的分层**。plan §7.2 把三层判据写进同一组断言，但浏览器看不到同步脚本
   与 TV 请求：
   - `EV-5`（2025-12-16 真实双非农择优）**不可在页面复现**（该日不在值层 90 天窗口内，按 D-5a 不 enrich）
     ⇒ 真值由 `tests/test_econ_values.py` 用该案例的 fixture 锁死（`act=64/fc=50`）；浏览器侧只验
     可观测不变量"每行至多一个值片段"。
   - `EV-6` 的"`failed` 含 `tradingview`"与 `EV-7` 的"preserve"同理 ⇒ 由单测锁（整源失败返回空 /
     `actual=None` 不抹旧值）；浏览器侧验"值侧全空时页面不崩、不渲染 0"。
   - 已在 `verify_ui.py` 的 `EV` 组 docstring 里写明这个分层，避免后人以为漏测。

### 5.3 `verify_ui.py` 的 GBK 陷阱（预防性）
新增文案含 `「」` 与全角 `｜`：**先显式验证过 cp936 可编码**再落盘（`.encode('gbk')` 全 OK），
断言标签一律只用 GBK 内字符。

### 5.4 真跑范围
`--skip-news` **未加**（为跑一遍完整链路，验证新增步骤没打乱既有 `[news]` 顺序），
叙事层顺带刷新了 13 条 `econ_event_news`（同 `(date,kind)` 覆盖，无新增行）。
`--no-push` 已加 ⇒ 未推送、未触发 Railway 重部署。

### 5.5 web 启动不跑迁移（**重要，已写进 pitfalls 与 storage docstring**）
`web/app.py` 的启动恢复链在**库非空时提前 `return "db"`，不调 `init_db()`**；而
`query_econ_events` 把 `sqlite3.DatabaseError` 吞成 `[]` ⇒ 若某个部署副本还是旧的 `.db`，
`/timeline` 会变成"近 90 天内没有事件"**而不是报错**。本轮按 plan 的「列先行、代码后行」执行
（`.db` 已 tracked，迁移随本次提交上线），**未改 `web/app.py`**（plan 明列"不动"）。

### 5.6 `AGENTS.md` 的过时描述（plan §4 D8 要求顺手更正，已改）
原文「`data/marketpulse.db` + `-wal`/`-shm`: …gitignore 排除…」不实：`.db` **是 tracked 文件**
（`git cat-file -e HEAD:data/marketpulse.db` 通过、`git ls-files` 有它），`.gitignore:42` 对已跟踪文件无效
⇒ **它随部署上线**，而 `data/backup/` 恢复链只恢复 `history`、造不出事件表。已改为实测口径。

## 6. 下次注意什么

1. **接外部数据源前先统计"键存在率"**，别照抄一条样本的字段表（`unit` 就是这么漏的）。
2. **"多个可接受键 + 择优规则"的匹配，必须回答"并列时谁决定"** —— 答案不能是"上游返回顺序"
   （PCE 首选/备选就是这么错的）。
3. **窗口类参数要"两侧都卡"**（抓取范围 + 被 enrich 的行），并把窗口规则抽成单一函数给日志复用，
   否则"命中 N/M"的分母会与真实窗口漂移。
4. **三方对账的 sqlite 侧必须与页面同 range**，否则计数必然不等（本轮靠"值层窗口与页面默认窗口取齐"
   才让断言字面成立；改窗口要同步改断言范围）。
5. **迁移的独立验收比对要剔除 `fetched_at`**，否则 103 行全报"不同"、被误读成数据被改。
6. **断言要按"文案族"与"数据驱动期望值"写**，不要把某个具体措辞写死（FOMC 的变动项就不是"变动"）。
7. `verify_ui.py` 约 5 分钟，**必须前台 + 显式 timeout**；迭代断言时用只跑单组的临时 runner
   （本轮落 `%TEMP%\mp-ev\run_ev.py`），全脚本留给收尾。

## 7. 明确未做（与 plan §12 对照）

- ❌ 不用 TradingView 替换 Fed / 镜像骨架；❌ 不抓 BLS/BEA 正文、不引新依赖
- ❌ 不做因果推断、不打利好/利空标签；❌ 不新增 nav 项、不改既有 `TL-*` 语义
- ❌ 不改 `/`、`/macro`、`/macro/cn`，不动 `data/history.json`
- ❌ 不把 TV 的 288 个指标全量入库（只 enrich 既有 8 类）
- ❌ 不加 ±N 天模糊匹配（零容差实测 100% 命中）
- ❌ 不派生 CPI 同比/MoM；❌ 不顺带回填历史值（只 enrich 窗口内既有行）
- ❌ 不给 `unit` 缺失的指标补单位（`点` / `千人` / `%`）
- ❌ 不用"两份 DOM + CSS 隐藏"做两态

## 8. 后续建议（不属本轮范围）

1. **`tests/test_us_sector.py::test_volume_format` 是既有红**：期望值 `$1.2B` 与实现的 `$12.0亿`
   口径不一致，建议单独一条小改动同步断言（本轮按"不碰无关模块"未动）。
2. **值层窗口加宽前必读**：`src/econ_values.py` 的 `VALUE_PAST_DAYS/VALUE_FUTURE_DAYS` 与
   `verify_ui.py` 的 `EV-2` sqlite 侧 range 必须同改。
3. `skills/source-value-layer/SKILL.md` 可补两条本轮实测教训：**"键存在率"统计**与
   **"首选/备选标题并存时不得靠排序"**（本轮未改该文件 —— 它不在 plan 的文件清单里）。
4. Hermes cron「MarketPulse 事件日历同步」的判据行建议追加 `[values]`（`docs/commands.md` 已记，
   cron prompt 全文在 `tasks/2026-09-18-event-timeline-page/journal.md` §14.4，需你侧更新）。
