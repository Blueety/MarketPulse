# Plan — 黄金展示位换 COMEX 期货（GC=F）：概览卡 + 另类资产趋势图

> 日期：2026-09-13 ｜ 角色：架构师 ｜ 状态：待用户确认后交执行者
> 背景：概览卡现显示 GLD×10=3,987.70（×10 是画图缩放非金价），用户确认两处黄金展示位都换 `GC=F`（COMEX 黄金期货，现货 ~$4,348，[Investing.com](https://www.investing.com/currencies/xau-usd)）。

## 0. 结论先行

两处改动共用一个数据源决策：**黄金的"报价"一律走 `GC=F`（`/api/macro` 实时链路），GLD 保留在 history/SQLite 作 EOD 历史**（不动数据生产链路，`src/*` 零改动）。

| 展示位 | 现状 | 改后 |
|---|---|---|
| 行 3 概览小卡「黄金 ETF」 | GLD 收盘 ×10 = 3,987.70（EOD，语义错位） | `GC=F` 实时报价 ~4,3xx（与美元/美债/原油同链路） |
| 另类资产 tab 趋势图黄金线 | history 的 `gld` 序列（EOD，图例「黄金 ETF」） | `/api/macro` 的 `gc=f` 30 日序列（实时，图例「黄金 COMEX」）；BTC 不动 |

**选型理由**：趋势图换数据源有两条路——(A) 前端叠加 `/api/macro` 序列（选定，零后端/零数据管线改动）；(B) daily_report 的另类资产改取 GC=F 写 history（动 SYMBOLS/ALT_SYMBOLS/history 键/已迁移 SQLite 数据，爆炸半径大且归一化后曲线形状与 GLD 无差异，否决）。

**已核实的基础设施**：`renderMainChart` 走 `buildTradingAxis` + `buildLinePts`（共享日期轴 + 逐序列投影），GC=F 日期轴与 history 日期轴合并后可直接走既有管线；`/api/macro` 响应已含 `trend.series`（`_build_watchlist_payload` 产物，归一化 + raw，key=`gc=f`）；`state.macro` 到达后当前**不会**重渲主图（需补一行触发）。

## 1. 任务目标

概览卡黄金位显示真实金价（~4,3xx 实时）；另类资产趋势图的黄金曲线换为 GC=F（图例「黄金 COMEX」）；BTC 与其余展示位不动。

## 2. 要改的文件列表

| 文件 | 改动 |
|---|---|
| `web/app.py` | `_MACRO_DEFAULT` 追加第 4 项 `{"symbol": "GC=F", "label": "黄金COMEX"}`（默认链：env `MACRO_STOCKS` > config.json `macro.stocks` > 内置默认） |
| `web/static/app.js` | ① `OVERVIEW_CARDS`：`GLD` 条目 → `{ id: 'GC=F', label: '黄金 · COMEX', source: 'macro', icon: 'gold', char: '金' }`（去 scale）；② `ICON_COLORS` 补 `"GC=F"`（沿用 GLD 金色）；③ `GROUPS` alt 组 `keys` 收窄为 `["btc"]` + 新增 `macroGold: "gc=f"` 标记；④ `renderMainChart`：alt 组时把 `state.macro.trend.series` 中 `key==="gc=f"` 的序列并入数据集 + **日期轴取 history 与 gc=f 的并集**；⑤ macro fetch 成功回调补 `renderMainChart()`（覆盖 macro 晚到 / 用户停在 alt tab 的时序） |
| `tests/test_web.py` | 宏观默认标的断言补 `GC=F`（既有 /api/macro 用例同步）；概览渲染无后端断言可加 |
| `docs`（收尾） | AGENTS.md `/api/macro` 描述「美元/10Y/原油」→「美元/10Y/原油/黄金」；architecture 决策行（黄金报价位 GLD→GC=F）；pitfalls 记一条「`scale:10` 是画图缩放不是换算公式，展示位禁继承图表缩放」 |

**零改动**：`src/*`（fetcher/analyzer/storage）、`/api/history` 的 `gld` 序列（保留输出，UI 不再消费）、BTC、日报另类资产板块（EOD 语义不属"报价位"）。

## 3. 实现步骤（每步可独立验证）

### S1 后端：宏观默认标的 +4
`_MACRO_DEFAULT` 加 `GC=F`。**配置覆盖检查**（执行者必做）：`grep macro config.json` 与 Railway env `MACRO_STOCKS`——任一存在则把 `GC=F` 补进那份列表，否则该环境下黄金卡显示「数据未接入」（默认链被覆盖时内置默认不生效）。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v`（macro 用例断言更新后全绿）。

### S2 概览卡切换
`OVERVIEW_CARDS` 黄金条目换 `GC=F` + `ICON_COLORS` 补键。 Weekend 显示周五期货收盘，与交易软件一致。

**验证**：起 uvicorn（新端口）→ 概览黄金卡显示 ~4,3xx 且与宏观三卡同为实时链路；断网/改坏 symbol → 显示「数据未接入」（既有空态，不白屏）。

### S3 另类资产趋势图换 GC=F（本任务核心，单独成步）
1. `GROUPS` alt 组：`keys: ["btc"]`、新增 `macroGold: "gc=f"`。
2. `renderMainChart` 内 alt 组分支：

   ```text
   gc = (state.macro?.trend?.series || []).find(s => s.key === 'gc=f')
   axisDates = gc ? mergeSortedUnique(history.dates, macro.trend.dates) : history.dates
   datasets = [btc 走既有管线] + [gc=f 用 buildLineDataset，色沿用金 #E5C07B，
               逐日投影：macro dates→值 map 映射到 axisDates，缺口 spanGaps]
   gc 缺失（macro 未到达/取数失败）→ 只画 BTC + 图例注「黄金加载中/暂缺」
   ```

3. macro fetch `.then` 成功后补调 `renderMainChart()`（macro 晚到且当前停在 alt tab 时补画金线）。
4. `renderTrendMeta` 对 alt 组的序列计数/标签同步（2 条：比特币 + 黄金 COMEX）。

**验证**：`verify_ui.py` 三视口（硬规定）+ 人工：alt tab 金线存在、与 BTC 同图、图例正确；对比 GLD 归一化曲线确认形状一致（改前改后截图各一张）。

### S4 全量回归 + 文档收尾
- `venv/Scripts/python -m pytest tests/ -v` 全绿；`git diff` 范围核对；
- docs 三处收尾（§2 表）；pitfalls 记「画图缩放 ≠ 展示换算」。

## 4. UI 专项说明

**复现路径（改前）**：起 uvicorn → 概览「黄金 ETF」卡显示 3,987.70（周五收盘）；趋势区「另类资产」tab → 黄金线图例「黄金 ETF」。

**关键测量点**：
- 概览卡：`GC=F` 值 ~4,3xx（4 位数 + 千分位），`fmtNumSep` 无需改；卡片宽度不变（位数与原值相近）；
- 趋势图：alt 组日期轴并集后 x 轴刻度数变化（history 交易日 ∪ macro 交易日，多出 A 股独有休市日的空档由 spanGaps 连线）——`tickLimit` 限刻度逻辑已有，复核标签不糊；
- 图例两条（比特币 / 黄金 COMEX）不溢出图区。

**box-sizing**：不涉及布局改动（数据源替换），全局 `border-box` 无新增风险。

**多尺寸验收**：
- **720p**：概览卡 4 位数正常显示；趋势图图例两行内、x 轴刻度照常限量；
- **1080p**：同上无差异。

## 5. 风险评估和注意事项

1. **配置覆盖陷阱（最重要）**：`env MACRO_STOCKS > config.json > 默认`——Railway 若设了 env，只改代码默认值**不生效**，黄金卡会显示「数据未接入」。S1 的覆盖检查是必做项，不是可选项。
2. **黄金卡可用性从 EOD 变实时**：宏观取数失败时黄金卡「数据未接入」（原 GLD 卡只要有 history 就有值）。接受——与另外三张宏观卡语义一致。
3. **时序**：`/api/macro` 晚于首渲染到达 → 用户停在 alt tab 时金线缺失；S3-⑤ 的补渲染解决。macro 取数失败 → alt 图只有 BTC（可接受的降级，图例有注）。
4. **日期轴并集**：history 日期是美股 ET 与 A 股北京归档的混合（27 期设计），macro 全为 ET 交易日——并集排序后 A 股独有日在 GC=F 序列上为空点，`spanGaps` 连线即可；断言 x 轴不出现乱序。
5. **图例与颜色**：GC=F 沿用 GLD 的金色（`#E5C07B`），视觉连续；图例文案「黄金 COMEX」与概览卡标签一致。
6. **双端一致性**：改后概览卡（实时期货价）与日报另类资产板块（GLD EOD）数值不同——**语义不同源，属预期**，日报不动。

## 6. 验证命令（引用 docs/commands.md）

| 用途 | 命令 |
|---|---|
| 单测 | `venv/Scripts/python -m pytest tests/test_web.py -v` |
| 全量 | `venv/Scripts/python -m pytest tests/ -v` |
| 手测 | `venv/Scripts/python -m uvicorn web.app:app --port 8020`（新端口）→ 概览卡 + alt tab |
| UI 验收（必跑） | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` |

## 7. 预计影响的文件范围

`web/app.py`（+1 行）、`web/static/app.js`（±~30 行，集中在 OVERVIEW_CARDS/GROUPS/renderMainChart/ICON_COLORS 四点）、`tests/test_web.py`（±~8 行）、docs 收尾。**不动**：`src/*`、`/api/history` 输出、日报链路、前端样式。
