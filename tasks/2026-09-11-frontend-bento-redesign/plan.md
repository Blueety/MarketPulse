# MarketPulse 前端重构 · 实施计划（Bento Dashboard）

> 架构师产出（Phase 3）。**只提供方案，不含完整实现代码**；代码由执行者编写。
> 本计划的基线数据来自 **Playwright 实测**（1920×1080 / 1280×720 各跑一次，非代码推演）。

---

## 0. 前置说明：prd.md 缺失

`tasks/2026-09-11-frontend-bento-redesign/prd.md` **不存在**。本计划的目标来源为：

1. 需求方提供的效果图 `image.png`；
2. 2026-09-11 范围确认（4 项问答，见下）。

**建议**：由需求方把下面「§1 目标」+「§2 验收」反写成 `prd.md` 归档，本文件保持为实现计划。

**已确认的范围决策（引用）**

| # | 问题 | 决策 |
|---|---|---|
| Q1 | 实施范围 | 先把前端**能做的全做**；没有的功能先做「样子」，后续再接 |
| Q2 | 无数据源模块（资讯 / 资金流向 / 风险偏好） | **静态占位保视觉**，文案「数据未接入」，后续只改数据层 |
| Q3 | 趋势图 1Y | **扩 retention 到 365**（同步改 `/api/history` 上限） |
| Q4 | 基线实测 | 允许架构师启动 uvicorn 实测 |

---

## 1. 任务目标

**Goal（引用效果图 + 上述决策）**

把 `web/` 看板从「单列流式 section 堆叠」重构为效果图所示的 **三栏 bento 栅格仪表盘**：

- **有数据源的模块全部接真实数据**：4 张 KPI 卡、市场趋势大图、自选列表、市场概览、美股行业板块、告警。
- **无数据源的模块静态占位保视觉**：最新资讯、资金流向（近5日）、风险偏好、顶栏搜索、全球市场动态配图。
- **保持双主题**（深/浅）与既有只读语义（web 进程绝不写 `data/` `context/` `alerts/`）。

**一句话验收标准**

1920×1080 下 9 个模块 **≤ 1.15 屏**内呈现（现状实测 2.44 屏）、页面无横向溢出、Console 无 error、深浅两主题正常。

---

## 2. 实测基线（Playwright，DPR=1）

启动：`venv\Scripts\python -m uvicorn web.app:app --port 8014` → `http://127.0.0.1:8014/`

### 2.1 视口级

| 指标 | 1920×1080 dark | 1280×720 dark |
|---|---|---|
| `window.innerWidth × innerHeight` | 1920 × 1080 | 1280 × 720 |
| `document.scrollingElement.scrollHeight` | **2632** | **2655** |
| `scrollWidth` | 1920（无横向溢出） | 1280（无横向溢出） |
| 首屏可见占比 | 1080 / 2632 = **41 %** | 720 / 2655 = **27 %** |
| `window.__chartFailed` / `__zoomFailed` | false / false | false / false |
| Chart.js 实例数 | 5 | 5 |
| `console` error | **0** | **0** |

### 2.2 关键元素

| 元素 | 属性 | 1920×1080 | 1280×720 |
|---|---|---|---|
| `.shell` | `display / align-items / 高` | flex / `flex-start` / 2576 | flex / `flex-start` / 2599 |
| `#sidebar` | `w × h`、`position`、`offsetTop` | 232 × **1024**、`sticky`、56 | 232 × **664**、`sticky`、56 |
| `.main` | `w × h`、`padding` | 1688 × 2576、`24px 32px 48px` | 1048 × 2599、同上 |
| `#lede` | `h`、子格数 | 114、4 | 114、4 |
| `.lede-cell` | `w × h`、`grid-template-columns` | 396 × 98、`256px 96px` | 236 × 98、`96px 96px` |
| `#overview` | `h` | 498 | 498 |
| `#trend` | `h` | 922 | 945 |
| `.charts-grid` | `grid-template-columns`、`h` | `804px 804px`、743 | `484px 484px`、766 |
| `.chart-box` | `w × h` | 804 × 363 | 484 × 363 |
| `#sectors` | `h` | 275 | 275 |
| `#watchlist-section` | `h` | 375 | 375 |
| `#alerts` | `h` | 316 | 316 |
| `.sidebar-footer` | `offsetTop`、`h` | 967、41 | 607、41 |
| 数据行数 | overview / sector / **watch** / alert | 10 / 5 / **1** / 2 | 同 |
| `nav-item` 数 | — | 6（其中 4 个 `disabled`） | 6 |

### 2.3 canvas 位图 / 显示尺寸失配（实测，重要）

| canvas | 位图 `width × height`（属性） | CSS 显示尺寸 | 缩放比 |
|---|---|---|---|
| `chart-gspc-ixic` @1920 | 726 × 363 | 804 × 340 | 横向 **1.107×**、纵向 **0.937×** |
| `chart-gspc-ixic` @1280 | 484 × 242 | 484 × 340 | 横向 1.000×、纵向 **1.405×** |
| `chart-watchlist` @1920 | 640 × 243 | 640 × 220 | 纵向 0.905× |

→ **非等比拉伸**，1280 下纵向被拉 40 %。这是「图表看起来糊/线变形」的量化根因。

---

## 3. 根因分析（两层）

### 3.1 渲染表现根因（用户实际看到什么）

1. **页面在 1080p 下总高 2632px = 2.44 屏**，首屏只能看到 KPI + 概览表 + 趋势图上排；效果图把同样 9 个模块压在 ~1050px（≈1 屏）。
2. **趋势图是 2×2 四张小图**（每组 804×363），无法做跨市场对比；效果图是 1 张大图 + 类别 tab。
3. **自选股区只有 1 行数据却占 375px 高**，其中 640×220 的图只有 1 条线，下方大片空白（`watchRows=1`）。
4. **卡片没有任何卡片特征**：`background:transparent; border:none; border-radius:0`，纯靠 `.card{border-bottom}` 的 hairline 分隔 → 与效果图的「圆角卡片栅格」观感完全不同。
5. **顶栏没有搜索框 / 星期 / 通知 / 头像**，侧栏没有「板块表现」与底部「市场已开盘 + 北京时间」。

### 3.2 代码逻辑根因（CSS/JS 机制）

| # | 现象 | 机制根因 | 位置 |
|---|---|---|---|
| C1 | 无法形成 bento 栅格 | `.main` 是 `display:block` 单列流；`.card` 靠 `border-bottom` 分隔，**布局模型本身不支持多列** | `style.css:133-149` |
| C2 | canvas 位图 ≠ 显示尺寸（非等比拉伸） | `.chart-box canvas{width:100%!important;height:340px!important}` 用 `!important` 覆盖 Chart.js 写入的行内尺寸，两边打架；且趋势图 4 张走 `buildLineOptions` **未传 `maintainAspectRatio:false`**（默认 `true` → 按 2:1 算位图），只有自选股图传了 | `style.css:263-268`、`app.js:388-468`、`app.js:712` |
| C3 | KPI 行放不下第 5 张 promo 卡 | `.lede-cell{flex:1 1 200px}` + `display:grid; grid-template-columns:1fr 96px` → 只会等分铺满，**无跨列/权重能力** | `style.css:209-220` |
| C4 | 侧栏与主区是两个独立滚动上下文 | `.shell{display:flex;align-items:flex-start}` + `#sidebar{position:sticky;height:calc(100vh - 56px)}` | `style.css:86-95` |
| C5 | 改卡片化会连带失效一批隐式规则 | `.card:last-child{border-bottom:none}`、`.card h2`、`.chart-box:has(.chart-empty){display:none}`、`#overview .data-table{table-layout:fixed}` 均绑定旧的「区块」模型 | `style.css:142-165, 269, 420-425` |
| C6 | 「休市」判定基准错 | `const isWeekend = (new Date().getDay() % 6) === 0` 用的是 **运行当天**的星期，不是**数据日**的星期 → 工作日浏览时永远不显示「休市」 | `app.js:127` |
| C7 | 美股行业板块数据拿不到 | `context/*.json` **已有 `us_sector_heat` 键**（已核实 `context/2026-09-11.json` 键集含它），但 `web/app.py` 只读 `sector_heat`，**从未暴露** | `web/app.py:401-420`、`src/reporter.py:977` |
| C8 | 1Y 不可用 | `data/history.json` 恰好 **90 行**（2026-05-14 → 2026-09-11）；`history.retention_days=90`；`/api/history` 为 `Query(30, ge=1, le=90)` | 实测 + `web/app.py:396` + `src/config.py:26` |

---

## 4. 目标架构（替代方案 + 选型理由）

### 4.1 布局模型 → **选 12 栅格 + 按行 sub-grid（方案 A）**

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（选）** | `.main` 内加 `.dash`（12 列 grid），再按视觉行拆 `.row-kpi/.row-main/.row-3/.row-news` 四个 sub-grid | 模块数多（9）、跨断点列数变化频繁，span 比 areas 好维护；现有 HTML 已是平铺 `<section>`，**不用改 DOM 层级** |
| B | `grid-template-areas` 命名区域 | 可读性好，但 4 个断点要写 4 套 areas，维护成本高 |
| C | 继续 flex + 手工 row wrapper | 行内高度不一致时需等高 hack；与效果图的「跨行卡片」不兼容 |

**关键约束**：列定义必须写 `repeat(N, minmax(0, 1fr))`。若写 `1fr`，grid item 的 `min-content`（表格 `white-space:nowrap`、canvas）会顶破容器产生横向溢出 —— 与 `pitfalls.md:202`（flex column 溢出）同源问题。

### 4.2 图表 → **保留 Chart.js，四图合一 + tab 切换（方案 A）**

| 方案 | 评价 |
|---|---|
| **A（选）** | 不引新依赖（`AGENTS.md` 禁止未说明的依赖）；`buildTradingAxis`/`buildLinePts`/`buildLineDataset` 已沉淀可复用；渐变面积 Chart.js v4 原生支持（`fill:{target:'origin'}` + `createLinearGradient`） |
| B | 换 ECharts：面积渐变更容易，但要重写全部图表逻辑 + 新依赖 + 新 CDN 降级路径，**收益可用 A 达到** |

**必须同步修复 C2**（否则大图拉伸更明显）：`maintainAspectRatio:false` + 容器显式高度 + **删除 canvas 的 `!important` 尺寸**。

### 4.3 新增宏观标的（美元指数 / 10Y美债 / 原油）→ **新增 `/api/macro` 复用 watchlist 取数（方案 A）**

| 方案 | 评价 |
|---|---|
| **A（选）** | `_fetch_yahoo_watch(symbol)` 接受**任意 Yahoo 符号**，`fetch_watchlist` 已按 `.SS/.SZ` vs Yahoo 分流 → 美股/指数/期货符号可直接用；新端点约 25 行，语义独立 |
| B | 加进 `src/fetcher.py::SYMBOLS`：会连带 history / context / 告警 / 日报 / 快照 / 回测 / 大量测试（风险面过大） |
| C | 直接塞进现有 `watchlist.stocks`：会污染「自选列表」语义（列表会从 1 行变 9 行），且共用一个 12s 超时 |

**符号建议**：美元指数 `DX-Y.NYB`、10Y美债 `^TNX`、原油 `CL=F`（执行者须先实测可达性，Yahoo 对本机 IP 有限流历史）。

### 4.4 占位策略 → **单一常量块 + 语义标记**

在 `app.js` 顶部集中一个 `PLACEHOLDERS` 常量，DOM 上加 `data-placeholder="1"`，文案统一「数据未接入」。后续接源只需替换数据层，**grep `data-placeholder` 即可定位全部待接点**。

「全球市场动态」promo 卡用 **CSS 渐变 + 内联 SVG**，**不新增二进制图片资源**（避免仓库膨胀，且效果图的雪山图与金融语境不匹配）。

### 4.5 1Y → **retention 365 + 显式期望管理**

`HISTORY_MAX` 只在 **写** 时裁剪（`src/analyzer.py:59` → `append_history`），**放宽它不会扩已有 90 行**。因此：

- 放宽 `le=365` 后，1Y 视图初期**仍只有 2026-05-14 起的 4 个月**，需跑回填补齐（§7 Step 10）。
- 回填有前置缺陷必须先修（见 R5）。

---

## 5. 目标布局规格

### 5.1 视觉行与栅格占位

| 行 | 容器 | 模块 | 1920（≥1500） | 1280（1200–1499） | 768–1199 | ≤480 |
|---|---|---|---|---|---|---|
| 1 | `.row-kpi` | 4 KPI + 1 promo | `repeat(5,1fr)` 同排 | `repeat(3,1fr)` → 3+2 | `repeat(2,1fr)` | `1fr` |
| 2 | `.row-main` | 市场趋势 + 自选列表 | `1.9fr 1fr` | `1.9fr 1fr` | `1fr`（堆叠） | `1fr` |
| 3 | `.row-3` | 市场概览 + 市场情绪 + 行业板块 | `repeat(3,1fr)` | `repeat(2,1fr)` → 2+1 | `repeat(2,1fr)` | `1fr` |
| 4 | `.row-news` | 最新资讯 | `1fr` | `1fr` | `1fr` | `1fr` |

`gap`：16px（≤480 时 12px）。

### 5.2 高度策略

| 模块 | 高度来源 | 目标值 |
|---|---|---|
| KPI 卡 | 内容 + `min-height` | ≥ 96px（1920）、≥ 88px（1280） |
| 市场趋势图容器 | `clamp()` | `clamp(300px, 40vh, 460px)`（1920@1080 → 432px） |
| 自选列表 | 内容自适应 + `min-height` | `min-height: 240px`（**防 1 行塌陷**，见 R8） |
| 市场概览 6 小卡 | 内部 `repeat(3,1fr)` ×2 行 | ≈ 150px |
| 行业板块条 | 行高 × 8 | ≈ 240px |
| 最新资讯 | 内容 | ≈ 120px |

---

## 6. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/templates/index.html` | **改（近重写）** | 141 → ≈260 行：`.dash` 骨架、顶栏搜索/星期/通知、侧栏第 7 项 + 底部市场状态、9 个模块、3 个 `data-placeholder` |
| `web/static/style.css` | **改** | 475 → ≈700 行：卡片 token 重写、栅格布局、图表容器高度、断点重写、删除失效规则 |
| `web/static/app.js` | **改** | 823 → ≈950 行：四图合一 + tab、KPI 卡、自选迷你条、美股行业板块、市场状态/星期、占位模块、修 C6 |
| `web/app.py` | **改（小）** | +≈35 行：`/api/latest` 增 `us_sector_heat`、新增 `/api/macro`、`le=90 → 365` |
| `tests/test_web.py` | **改（小）** | +≈25 行、改 1 处断言（`days=91` 由 422 → 200，新增 `days=366 → 422`） |
| `tasks/2026-09-11-frontend-bento-redesign/plan.md` | 新增 | 本文件 |

**预计不动**：`src/*`、`daily_report.py`、`snapshot_report.py`、`opening_analyzer.py`、`scripts/backtest.py`、`data/*`、`context/*`、`alerts/*`、`reports/*`。

**仅在 Step 10 可选回填时触及**：`seed_history.py`（并须先修 R5）。

---

## 7. 实现步骤（每步可独立验证）

### Step 0 · 基线与回归护栏

- 用 §2 的实测数字作为「before」快照留档（截图 + JSON）。
- **不引入前端测试框架**（无 npm 构建链；引入 vitest/playwright-test 属新依赖，违反 `AGENTS.md`）。UI 验收改用 Playwright 脚本 + 人工目视。
- **临时产物落点纪律（见 R14，本会话已踩坑）**：
  - 验证脚本**有意保留**在 `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（可复跑的验收工具，入库有益）。
  - **截图 / 测量 JSON 一律写到系统临时目录**（`$env:TEMP`），**不要落在仓库内**，避免二进制入库。
  - 若确实落在仓库（如 `_dbg/`），**用完立即删除**；注意外部「每日数据更新」cron 会 `git add -A` 抢先提交。
- **验证**：`venv/Scripts/python -m pytest tests/test_web.py -v` 全绿（后端契约未动）。

### Step 1 · 后端：暴露 `us_sector_heat`（P0）

- 把 `api_latest` 内的 `_load_sector_heat()` 调用改为「取一次 ctx，读两个键」，并抽出 `_sector_payload(ctx, key)` 纯函数。
- **保持 `_load_sector_heat()` 签名与行为不变**（`tests/test_web.py:249-275` 直接调它，未 monkeypatch），内部改为调 `_sector_payload`。
- **`api_latest` 的「历史为空」提前 return 分支也要补 `us_sector_heat` 键**，否则前端结构在空数据下不一致。

```text
# 伪代码
def _sector_payload(ctx, key):
    sh = ctx.get(key) if isinstance(ctx, dict) else None
    if not isinstance(sh, dict):
        return {"gainers": [], "losers": []}
    return {"gainers": sh.get("gainers") or [], "losers": sh.get("losers") or []}

def _load_sector_heat():
    return _sector_payload(_load_latest_context(), "sector_heat")

# api_latest 内：
ctx = _load_latest_context()
...
return {..., "sector_heat": _sector_payload(ctx, "sector_heat"),
             "us_sector_heat": _sector_payload(ctx, "us_sector_heat")}
```

- **验证**：`pytest tests/test_web.py -v`（既有 `test_api_latest` / `test_endpoints_empty_data` 只断言子集键，**新增键不会破坏**它们）；实测 `curl http://127.0.0.1:8014/api/latest` 的 `us_sector_heat.gainers` 长度应为 **5**（真实 context 有 11 只 SPDR ETF）。

### Step 2 · CSS：卡片 token 化

- `.card` 改为：`background:var(--bg-elevated); border:1px solid var(--border); border-radius:12px; padding:16px`。
- 新增 token（light/dark **双套齐**）：`--radius-card`、`--card-shadow`、`--card-glow`。
- 删除 `.card{border-bottom}` / `.card:last-child{...}`。
- **验证**：Playwright 断言 `.card` 的 `boxSizing === 'border-box'`、`borderRadius === '12px'`；切主题后 `getComputedStyle(.card).backgroundColor` 在 `#FFFFFF ↔ #111827` 间切换。

### Step 3 · bento 栅格骨架

- `index.html`：`.main > .dash > (.row-kpi / .row-main / .row-3 / .row-news)`，把既有 `<section>` 按 §5.1 归位。
- `style.css`：加 `.dash` + 四个 `.row-*` 规则，列一律 `minmax(0, 1fr)`。
- **验证**：Playwright 断言 `document.scrollingElement.scrollWidth === window.innerWidth`（1920/1280/375 三个视口均成立）；`.row-kpi` 在 1920 下 `gridTemplateColumns` 为 5 列。

### Step 4 · 趋势图：四图合一 + 类别 tab（本任务技术核心）

- `index.html`：删除 4 个 `.chart-box`，改为
  `#trend-tabs`（股票 / 波动率 / 宏观 / 另类资产）+ `#range-bar`（7D/30D/90D/1Y）+ 单个 `#chart-main-wrap > canvas#chart-main`。
- `app.js`：
  - `GROUPS` 增加/调整为一个「主图类别」注册表（保留 `keys` 过滤能力）。
  - 新增 `renderMainChart(activeGroupId)`：按 `state.history` 过滤该组 series → `buildLineDataset` → 单实例渲染；**切换 tab 只 destroy+重建，不发网络请求**（复用 `state.history`）。
  - `buildLineOptions` 增加 `maintainAspectRatio:false` 与面积渐变支持（`createLinearGradient` + `fill:{target:'origin'}`，颜色用 `colors()[key]` 加低透明度）。
  - 保留 `charts` 注册表 + 重渲染前 `destroy()`（`pitfalls.md:134` 纪律）。
- `style.css`：**删除** `.chart-box canvas{width:100%!important;height:340px!important}`，改为 `#chart-main-wrap{height:clamp(300px,40vh,460px)}` + `canvas{display:block;width:100%;height:100%}`（**不加 `!important`**）。
- **验证（关键）**：Playwright 断言 `canvas.width === canvas.offsetWidth`（DPR=1 时严格相等；DPR>1 时 `=== offset × DPR`），`canvas.height` 同理。这是 C2 的回归护栏。
- **验证**：切换 4 个 tab 后图表仍可交互（`window.Chart.getChart(canvas)` 可读），无 `Canvas is already in use` 报错。

### Step 5 · KPI 卡 + 自选列表 + 修 C6

- KPI 卡：`.row-kpi` 5 列；复用 `drawOneSpark`（sparkline 高度 40 → 56，宽度改 `100%` 自适应）；`resize` 时调 `repaintSparklines()`（**已有**，注意保留）。
- 自选列表：表头 `名称 / 现价 / 涨跌幅`；每行右侧加**纯 CSS 百分比迷你条**（不用 Chart.js，省实例、省 640px 宽图）。
- **修 C6**：新增 `isWeekendDate(dateStr)`，手动解析 `YYYY-MM-DD` 并用 `Date.UTC(y,m-1,d)` + `getUTCDay()` 判定，**禁止** `new Date("2026-09-11")`（该写法按 UTC 午夜解析，负时区会退到前一天）。
- 顶栏日期栏显示 `2026-09-11 周五`（数据日 + 数据日星期）。
- **验证**：断言 `isWeekendDate('2026-09-11') === false` 且星期标签为「周五」；`isWeekendDate('2026-09-12') === true`。⚠️ 效果图写的「2026-09-11 周四」是**错的**，不要照抄。

### Step 6 · 市场概览 6 小卡 + 美股行业板块

- 6 小卡：美股 / A股 / 黄金 → **现成**（`/api/latest` 的 `GSPC`/`SH`/`GLD`，黄金沿用 `×10` 显示口径）；
  美元指数 / 10Y美债 / 原油 → Step 8 未就绪时**占位「数据未接入」**。
- 行业板块卡：消费 `/api/latest` 的 `us_sector_heat.gainers`（11 只 ETF 取前 8），行内条宽 = `Math.abs(change) / maxAbs * 100%`，正绿负红；表头右侧「查看全部 →」（占位，`:disabled`）。
- **验证**：断言渲染 8 行、条宽按比例、`change` 与 context 值逐值一致。

### Step 7 · 占位模块（静态保视觉）

- `app.js` 顶部集中常量：

```text
const PLACEHOLDERS = [
  { id: 'news',          title: '最新资讯',        note: '数据未接入' },
  { id: 'fund-flow',     title: '资金流向（近5日）', note: '数据未接入' },
  { id: 'risk-appetite', title: '风险偏好',        note: '数据未接入' },
];
```

- DOM 标 `data-placeholder="1"`；「市场已开盘 / 北京时间」按 `Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai'})` 实时计算 + `is_market_holiday` 语义（**纯前端，不新增端点**）。
- **验证**：`grep -c 'data-placeholder' web/templates/index.html` == 3；目视与效果图同排同高。

### Step 8 · `/api/macro`（P1，可选）

- `web/app.py` 新增 `@app.get("/api/macro")`，复用 `fetch_watchlist` + `_normalize_series`；标的来源优先 env `MACRO_STOCKS`（JSON），其次 `config.json` 的 `macro.stocks`。
- ⚠️ `AGENTS.md`「不修改生产配置」→ **不改 `config.json`**，走 env 或由需求方手动加。
- **验证**：`curl /api/macro` → 200 + 3 项；强制 Yahoo 失败时返回 200 + 空结构（不 500）。

### Step 9 · 1Y / retention 365

- `web/app.py:396`：`Query(30, ge=1, le=90)` → `Query(30, ge=1, le=365)`。
- **必改测试** `tests/test_web.py:547-549`：`days=91` 由 422 → 200；新增 `days=366 → 422`。**不改这两行，「测试全绿」就是假绿。**
- retention：推荐 env `HISTORY_RETENTION_DAYS=365`（`src/config.py:46` 已有 ENV_MAP 映射），或由需求方手动改 `config.json` 的 `history.retention_days`。
- 前端：x 轴 `maxTicksLimit` 随 `state.days` 自适应（≤30 → 10，≤90 → 10，365 → 14），否则 365 点标签会糊成一团。
- **验证**：`pytest tests/test_web.py -v` 全绿；`curl "/api/history?days=365"` 返回 200 且 `len(dates) === 90`（当前只有 90 行，符合预期）。

### Step 10 · （可选）1Y 数据回填

只有在需要「1Y 不是空的」时才做，且**必须先修 R5 两处缺陷**：

1. `seed_history.py:36-38` 直连 `query1.finance.yahoo.com`，**违反 `pitfalls.md:15`**（Yahoo chart 调用必须走 `_yahoo_chart_get` 主机轮换）→ 改走 helper。
2. `seed_history.py:50` 用 `.astimezone()`（本地 = 北京）算日期，而 history 行的日期口径是**美东** → 直接回填会造出与既有行错位/重复的日期。**必须改 `_EASTERN_TZ`。**
3. `range` 由 `6mo` 改为 `1y`。

- **验证**：回填后 `data/history.json` 行数 ≤ 365、日期严格递增无重复、与既有 90 行日期口径一致（抽查美东收盘日）；重跑 `pytest tests/` 全绿。

### Step 11 · 响应式 + 多尺寸验收

- 断点按 §5.1 落地；移动端抽屉规则的选择器要与基础规则**同源特异性**（`pitfalls.md:201`：`#sidebar` vs `.sidebar` 会被 id 压过）。
- **验证**：Playwright 跑 1920×1080 / 1280×720 / 375×812 三个视口，断言 §9 的验收项。

### Step 12 · 清理与记录

- 保留 `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（验收脚本，入库）；删除系统临时目录外的截图与 JSON。
- 追加 `docs/pitfalls.md`：C2（canvas 位图/显示失配的量化判据）、C6（星期基准必须取数据日）、C7（context 有键但端点不暴露）、R14（auto-commit cron 会扫入临时产物）。
- 写 `tasks/2026-09-11-frontend-bento-redesign/journal.md`。

---

## 8. 复现路径与关键测量点

### 8.1 复现路径（精确步骤）

1. `cd d:/AGENT/MarketPulse`
2. 启动：`venv\Scripts\python -m uvicorn web.app:app --port 8014`
   ⚠️ **每次验证换新端口**（8014 → 8015 → 8016 递进）。同一端口复测会命中 304/陈旧 CSS 副本，产生「改动没生效/侧栏没 fixed」类假阴性（`pitfalls.md:200`）。
3. 浏览器打开 `http://127.0.0.1:8014/`，硬刷新 `Ctrl+Shift+R`。
4. 现状可观察到的 5 个问题：① 页面需滚动 2.4 屏；② 趋势区是 2×2 小图；③ 自选股区 1 行数据 + 640×220 空图；④ 所有 section 无卡片边框；⑤ 顶栏无搜索/星期，侧栏 6 项含 4 项置灰。
5. DevTools Console 应无 error。

### 8.2 关键测量点（执行者须逐项实测并记录）

| 测量点 | 取法 | 现状值 | 目标值 |
|---|---|---|---|
| 页面总高 | `document.scrollingElement.scrollHeight` | 2632 @1920 / 2655 @1280 | **≤1240** @1920；≤2400 @1280 |
| 横向溢出 | `scrollingElement.scrollWidth === innerWidth` | true | **必须 true**（三视口） |
| 栅格可用宽 | `.main` 的 `clientWidth` − padding | 1624（含 padding） | 记录实际值作列宽基准 |
| KPI 卡盒 | `.kpi-card` 的 `offsetWidth / offsetHeight` | 396 × 98 | ≥260 × 96 @1920；≥200 × 88 @1280 |
| 主图 canvas | `canvas.width/height`（位图） vs `offsetWidth/offsetHeight` | 726×363 vs 804×340 | **必须相等**（DPR=1） |
| 主图容器 | `#chart-main-wrap` 的 `clientHeight` | 363（`.chart-box`） | 432 @1080（=40vh，clamp 内） |
| 卡片盒模型 | `.card` 的 `getComputedStyle().boxSizing` | `border-box` | 保持 `border-box` |
| 侧栏贴底 | `#sidebar` 的 `offsetTop + offsetHeight` | 56 + 1024 = 1080 | == `innerHeight`（sticky 生效） |
| 底部状态条 | `.sidebar-footer` 的 `offsetTop` | 967 | 仍贴侧栏底（不随主区滚动走） |
| 层级 | `.topbar` / `#sidebar` / `.nav-backdrop` 的 `z-index` | 100 / 60 / 55 | 新增卡片层级 **< 55**，不得与其竞争 |
| 数据行数 | `#sector-body tr` / `#watchlist-body tr` | 5 / **1** | 5 / N（N 依配置，须不塌陷） |

### 8.3 box-sizing 说明（必须显式确认）

`web/static/style.css:46` 是 `* { margin:0; padding:0; box-sizing:border-box }` —— **全局 border-box，无例外**。由此推出四条对本任务有直接影响的结论：

1. **新增卡片的 `padding` 不会撑高 `height`**：若写 `.kpi-card{height:96px; padding:14px 16px}`，96px **已含**上下 padding，内容区仅 68px。
2. **`max-height` 同样含 padding**（这点是 border-box 与 content-box 的关键差异；content-box 下 `max-height` 不约束 padding，会出现「盒子被 padding 顶破」）。
3. **图表清晰度不由 CSS 的 `height` 决定**，而由 canvas 的 `width`/`height` **位图属性**决定。C2 的修复本质是让 CSS 显示尺寸 = Chart.js 计算的位图尺寸，因此**必须删掉 `!important` 高度**，否则无论怎么调 `clamp()` 都只是把「拉伸比例」改成另一个错的数。
4. `#sidebar{height:calc(100vh - 56px)}` 在 border-box 下含 `padding:16px 12px` → 内容区 = 该值 − 32px（实测 1024 → 992）。

**纪律**：本次不引入 `content-box`。若确实需要（例如要在 padding 外做绝对定位对齐），必须显式写 `box-sizing:content-box` 并在该行加注释说明原因，同时通知验收方复核 `max-height` 行为。

---

## 9. 多尺寸验收

### 9.1 1920×1080（常规窗口，主验收）

- `scrollHeight ≤ 1240` —— 9 个模块在 **≤1.15 屏**内**全部可见**（无需长滚动）。
- `.row-kpi` **5 列同排**：4 KPI + 1 promo，每列 ≈ 300px。
- `.row-main` **主图 + 自选列表同排**（约 1.9 : 1）。
- `.row-3` **三列同排**（市场概览 / 市场情绪 / 行业板块）。
- `.row-news` 通栏。
- 主图容器 `clientHeight` = 432px（`40vh`）；canvas 位图 == 显示尺寸。
- `scrollWidth === 1920`；Console 0 error。

### 9.2 1280×720（小窗口）

- `scrollWidth === 1280` —— **无横向溢出**（本档最易踩 `min-content` 溢出，必须验证）。
- `.row-kpi` 退化为 `repeat(3,1fr)` → **3 + 2 两行**；每列 ≈ 326px，KPI 不折行。
- `.row-main` **堆叠**（主图在上、自选列表在下）—— 720p 下不追求同排。
- `.row-3` 退化为 `repeat(2,1fr)` → **2 + 1**。
- `scrollHeight ≤ 2400`（允许比 1080p 更长，但不允许溢出）。
- 主图容器高度 = `clamp(300, 288, 460)` → **300px**（`40vh` = 288 < 300，取下限）。
- canvas 位图仍 == 显示尺寸（**C2 回归重点档位**：现状此档纵向拉伸 1.405×）。

### 9.3 375×812（附加，移动端）

- `scrollWidth === 375`；侧栏为 `fixed` 抽屉（`body.nav-open` 时 `translateX(0)`）。
- 所有卡片单列；`.table-scroll` 横向滚动，**页面本身不横滚**。
- 图表高度 280px（保持 ≥280 防扁条，`pitfalls.md:211` 同源约束）。

---

## 10. 验证命令

引用 `docs/commands.md` 的既有命令：

```bash
# 后端契约回归（每次改 web/app.py 后必跑）
venv/Scripts/python -m pytest tests/test_web.py -v

# 全量套件（提交前）
venv/Scripts/python -m pytest tests/ -v

# 启动看板（每次换新端口；8014 起）
venv/Scripts/python -m uvicorn web.app:app --port 8014

# 若改了 src/ 或配置默认值 / 动了 seed_history.py
AUTO_PUSH=0 venv/Scripts/python daily_report.py

# 环境校验（若换机器）
venv/Scripts/python -c "import matplotlib; matplotlib.use('Agg')"
```

**新增（一次性、不落库）**：Playwright 测量脚本，覆盖 §8.2 全部测量点 + §9 三个视口。用完删除。

**当前基线回归命令**（本次已跑通）：
`venv/Scripts/python -m pytest tests/test_web.py -v` → 全绿；`console error == 0`。

---

## 11. 风险与注意事项

| # | 风险 | 等级 | 说明与对策 |
|---|---|---|---|
| **R1** | 删掉 canvas `!important` 后图表高度塌 0 | **高** | `maintainAspectRatio:false` 时 Chart.js **完全依赖容器高度**；容器若只有 `height:100%` 而父级无确定高度 → 高度 0、图表不可见。**必须**给 `#chart-main-wrap` 显式 `clamp()` 高度。对策：Step 4 验证 `clientHeight > 0` |
| **R2** | 12 栅格 + `nowrap` 表格横向溢出 | **高** | 列定义必须 `minmax(0, 1fr)`，否则 grid item 的 `min-content` 顶破容器（与 `pitfalls.md:202` 同源）。对策：Step 3 在 375/1280 双视口断言 `scrollWidth === innerWidth` |
| **R3** | `tests/test_web.py:547-549` 会因 `le` 放宽而失败 | **高** | `days=91` 现断言 422；放宽到 365 后变 200 → **必须同步改**，否则「全绿」是假绿。对策：Step 9 明确列入改动清单 |
| **R4** | 1Y 期望落空 | **高** | retention 只影响**后续写入**的裁剪，**不扩已有 90 行**（实测 `2026-05-14 → 2026-09-11`，恰好 90）。放宽后 1Y 初期仍只有 4 个月。对策：Step 10 可选回填 + 向需求方明确告知 |
| **R5** | 回填脚本会污染日期口径 | **中** | `seed_history.py:50` 用 `astimezone()`（本地 = 北京）算日期，与 history 的**美东**日期口径不一致 → 造出错位/重复日期；且 `:36` 直连 `query1` 单主机，违反 `pitfalls.md:15`。**不修不要跑。** |
| **R6** | 占位模块被误判为 bug | **中** | 统一 `data-placeholder="1"` + 文案「数据未接入」，便于后续 grep 清理；在 `journal.md` 明确列出 3 个占位点 |
| **R7** | 主题漏改（卡片色只改一套） | **中** | 新增 token 必须 `:root`（light）+ `[data-theme="dark"]` **双套齐**；切主题后仍需 `renderCharts(state.history)` 重渲染（`pitfalls.md:203` 同源） |
| **R8** | 自选列表实际只有 **1 只**标的 | **中** | 实测 `config.json` 的 `watchlist.stocks` 仅 `515300.SS`（红利低波ETF）→ 效果图的 8 行不会出现。列表卡必须 `min-height` 防塌陷，且行数自适应 |
| **R9** | `515300.SS` 日线停更 | **低** | 沪 ETF 日线自 09-03 起停更（`pitfalls.md:17`），迷你条/趋势会显示旧序列，**非本次引入** |
| **R10** | 效果图自身有错，不能照抄 | **中** | ①「2026-09-11 周四」是**错的**（实为周五）；②「Nasdaq 100」与我们的 `IXIC`（纳斯达克**综合**）语义不符——**建议改标签为「纳斯达克综合」**，不改数据源 |
| **R11** | 字体/等宽差异 | **低** | Windows 下 `ui-monospace` 落到 Consolas，数字宽度与效果图（Inter/SF）不一致，属可接受差异，不做字体外链 |
| **R12** | 移动端抽屉失效 | **中** | 移动端媒体查询选择器必须与基础规则**同源特异性**（`pitfalls.md:201`：基础写 `#sidebar` 则媒体查询也要 `#sidebar`） |
| **R13** | 新增依赖 | **低** | 全程**零新增依赖**；promo 卡不引图片资源（CSS 渐变 + 内联 SVG） |
| **R14** | 外部 auto-commit cron 会把临时产物提交进仓库 | **中（已实际发生）** | 本会话架构阶段已踩坑：Hermes「每日数据更新」cron 跑了 2 次 `git add -A`（提交 `a5329eb`、`a8a987e`），把 `_dbg/measure.py`、`_dbg/measure.json`、3 张基线截图（合计 ≈887 KB PNG）提交入库。**对策**：验证脚本落 `tasks/<task>/verify_ui.py` 有意入库；截图/JSON 落 `$env:TEMP`；**不要**在仓库内留临时文件。执行者写一次临时脚本就会被自动提交，务必按此纪律落点 |

---

## 12. 预估 diff 范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改（近重写） | `web/templates/index.html` | 141 → ≈260 行 |
| 修改 | `web/static/style.css` | 475 → ≈700 行（token + 布局重写，删除约 40 行失效规则） |
| 修改 | `web/static/app.js` | 823 → ≈950 行（改 ≈35 %，删 4 图逻辑、加 1 图 + tab） |
| 修改（小） | `web/app.py` | +≈35 行（`us_sector_heat`、`/api/macro`、`le=365`） |
| 修改（小） | `tests/test_web.py` | +≈25 行、改 1 处断言 |
| 新增 | `tasks/2026-09-11-frontend-bento-redesign/plan.md` | 本文件 |
| 可选修改 | `seed_history.py` | 仅在 Step 10 执行时；+≈8 行（helper + 时区 + range） |
| 新增 | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 验收用 Playwright 脚本（有意入库，可复跑） |
| 删除（补救，需人确认） | `_dbg/measure.py`、`_dbg/measure.json`、`_dbg/shot-*.png` | 本会话被 auto-cron 提交进 `a5329eb`/`a8a987e`，现工作区已删除但**未提交**，见 R14 |
| 不动 | `.gitignore` | 不新增忽略规则（`_dbg/` 是既有受版本控制的调试夹具目录） |

**净代码变更估算**：约 **+450 / −320 行**（不含本计划文档）。

---

## 13. 不做什么

- 不改 `src/*`、`daily_report.py`、`snapshot_report.py`、`opening_analyzer.py`、`scripts/backtest.py`（本次零后端业务逻辑变更）。
- 不改 `data/`、`context/`、`alerts/`、`reports/`（生成物）；web 进程保持只读语义。
- 不改 `config.json`（`AGENTS.md` 禁止；retention 走 env 或由需求方手动改）。
- 不引入任何新依赖（不换 ECharts、不装 vitest/playwright-test、不引图表插件）。
- 不新增二进制图片资源。
- 不实现「资金流向 / 风险偏好 / 最新资讯 / 搜索」的**真实数据源**（本次只做静态占位）。
- 不扩 `SYMBOLS` 注册表（宏观标的走 `/api/macro`，避免连带 history/context/告警/回测）。
- 不清理历史数据里既有的重复行（`pitfalls.md:172`，靠滚动自然淘汰）。

---

## 14. 确认

- [ ] 人已审阅计划
- [ ] 文件范围合理（未越界改 `src/`、生成物、用户配置）
- [ ] 没有遗漏测试（`tests/test_web.py` 的 `days` 上限断言已列入）
- [ ] 没有引入不必要依赖
- [ ] 已确认 §9 的 1920×1080 / 1280×720 验收数字
- [ ] 已知悉 1Y 初期仍只有 4 个月数据（R4）
