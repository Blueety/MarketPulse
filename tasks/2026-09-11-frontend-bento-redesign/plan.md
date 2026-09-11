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

## 15. 附录 A · Step 10 执行前只读核对（2026-09-11 执行者补充）

> **结论：Step 10 不能按 §7 字面直接跑。** 本附录修正 §7 Step 10 与 §11 R5 —— 核对实际代码后，plan 只识别了 2 个缺陷，实际有 **5 个（S1–S5）**，其中 **S2 / S3 / S4 会破坏生产数据**。

| # | plan 的说法 | 实测核对结果 | 若照 plan 做的后果 |
|---|---|---|---|
| **S1** | 「`:50` 用 `.astimezone()`（本地=北京）→ **必须改 `_EASTERN_TZ`**」（R5） | **半对**：`history.json` 的日期口径不是统一美东，而是**按符号所属市场各自的交易所时区**——`analyzer.get_market_date(market)` 中 `a-share → SHANGHAI_TZ`、`us → EASTERN_TZ`；`_fetch_yahoo_watch` 也明确「时间戳转美东日期，与 history.json 美东 date 键对齐」（那条只覆盖美股标的） | A 股 3 列（`sh`/`sz`/`cyb`）的 timestamp 转美东会落到**前一日**（上证 09:30 北京 = 前日 21:30 ET）→ 与既有 90 行**日期整体错位一天**、产生重复日、A 股涨跌幅跨日错算。**正确修法：按符号选时区**（sh/sz/cyb → `SHANGHAI_TZ`；gspc/ixic/vix/vxn/move/gld/btc → `EASTERN_TZ`） |
| **S2** | 未提及 | `HISTORY_MAX = int(_CFG["history"]["retention_days"])` = **90**（`src/analyzer.py:59`），`append_history` / `merge_history` 每次写都做 `records[-HISTORY_MAX:]` | retention 不放宽 → 回填的 1y 数据**立刻被裁回 90 行**，等于白做。且**仅在回填那次临时注入 env 无效**：次日 `daily_report.py` 又会裁回 90 行 |
| **S3** | 未提及 | `append_history(record)` 默认 `merge_existing=False` → 先删同 date 行再 append，即**整行覆盖**；而 seed 脚本的行初始只有 `{date, vix, vxn, move}`（`setdefault`），其余键靠动态赋值 | 某标的本次拉取失败时该键**根本不存在**（不是 `None`）→ 覆盖后 `load_history` 投影为 `None`，**抹掉既有行的真实值**（如 `gld`/`btc` 已有值时） |
| **S4** | 未提及 | `seed_history.py:102-109` 用**小写键** `[s.lower() for s in SYMBOLS]` 调 `save_last_values`；而 `save_last_values` 是**整文件覆盖**、`load_last_values` **原样保留键大小写**，消费方（涨跌幅/`check_breach`）按**大写 symbol** 取值——现网 `data/last_values.json` 的键正是大写（`GSPC`/`IXIC`/…） | 跑一次就把 `last_values.json` 键改成小写 → 次日**全部涨跌幅失真（退化为"首次运行，暂无历史对比"）+ 告警基准全部失效**。注：`docs/pitfalls.md` 六期B 那条「键派生必须 `.upper()`」的**标题与正文自相矛盾**（正文写的是 `[s.lower() for s in SYMBOLS]`），该问题实际**至今未修** |
| **S5** | 未提及 | seed 脚本逐条 `append_history`（每次重写整个文件，90 次 IO）；且新行键序与既有行不同 | 90 行 diff 变成"全量重写"的噪音；无功能影响但审阅成本高 |

### 硬性前置条件（两个方案都需要）

1. **retention 必须常驻放宽到 365**：`config.json` 的 `history.retention_days=365`，或常驻 env `HISTORY_RETENTION_DAYS=365`（`src/config.py` 已有 `ENV_MAP` 映射）。
   ⚠️ `AGENTS.md` 禁止执行者修改生产配置 → **待需求方确认由谁改**。此处不改，Step 10 全部无意义。
2. **回填脚本不得调用 `save_last_values`**（或必须改用大写键），避免污染次日告警基准。
3. **回填前先备份 `data/history.json`**（验证后如需回滚）。

### 方案选择（待需求方拍板）

- **方案 B（推荐）**：不修 `seed_history.py`，新增 `scripts/backfill_history.py` —— 复用 `fetcher._yahoo_chart_get`（query1/query2 双主机轮换，符合 `pitfalls.md:15`）+ `analyzer.merge_history`（**按 date 合并、只写本市场子集、不整行覆盖**、自动裁剪），逐符号按所属市场时区转日期，`range=1y`，全程不碰 `last_values.json`。天然规避 S1/S3/S4/S5，且符合既有「merge 而非覆盖」的架构决策（二十七期）。
- **方案 A（严格照 plan）**：修 `seed_history.py` 三处（helper / 分市场时区 / `range=1y`）**并额外修 S2/S3/S4/S5 共 7 处**；脚本仍是一次性工具。
- **`seed_history_market.py` 不建议使用**：同样含 S1（`.astimezone()`）+ 直连单主机 + 硬编码 8 键行模板，比 `seed_history.py` 更粗糙。

### Step 10 修正后的验证清单

- 回填后 `data/history.json`：行数 ≤365、**date 严格递增且无重复**、A 股行日期与既有行口径一致（抽查 2026-09-11 为北京日、2026-09-10 为美东日）；
- 既有 90 行的**非空值零丢失**（逐键比对回填前后非空计数，`gld`/`btc` 不得因回填变 None）；
- `data/last_values.json` **未被改动**（键仍为大写、`date` 不变）；
- `AUTO_PUSH=0 venv/Scripts/python daily_report.py` 冒烟：涨跌幅基于新基准正常（不出现"首次运行"）；
- `venv/Scripts/python -m pytest tests/ -q` 全绿；`scripts/backtest.py` 可正常回放（样本从 ~90 → ~250）；
- `verify_ui.py` 下 1Y 档 tab 实际渲染出 ~250 点（`maxTicksLimit=14` 不糊）。

---

## 16. 确认（原 §14 保留，附录 A 为执行者补充）

- [ ] 人已审阅计划
- [ ] 文件范围合理（未越界改 `src/`、生成物、用户配置）
- [ ] 没有遗漏测试（`tests/test_web.py` 的 `days` 上限断言已列入）
- [ ] 没有引入不必要依赖
- [ ] 已确认 §9 的 1920×1080 / 1280×720 验收数字
- [ ] 已知悉 1Y 初期仍只有 4 个月数据（R4）

---

# 15. 追加（验收后缺陷）：玻璃感缺失的视觉根因与修复

> 触发：执行者完成 P0 后，需求方反馈「没有效果图里的玻璃感」。
> 测量方式：`tasks/2026-09-11-frontend-bento-redesign/verify_ui.py --port 8015`（Playwright 读计算样式），**两主题各测一遍**。
> **责任归属：这是本方案 §4.2/§7 Step 2 的设计缺陷，不是执行者跑偏。** Step 2 原文写的是
> `.card { background: var(--bg-elevated); border: 1px solid var(--border); border-radius: 12px }`
> —— `--bg-elevated` 是**不透明**色，`--bg-primary` 是**纯色**底。我按「卡片化」设计，没有按「玻璃化」设计。

## 15.1 结论先行

1. **不是「少写几行 CSS」，而是选择了与玻璃视觉互斥的模型。** 当前是「不透明色块 + 纯色底 + 黑投影」，这是**扁平卡片（flat card）**语言；玻璃（glassmorphism）语言由三个**互为前提**的机制组成，当前**三个全缺**。
2. **单独补一行 `backdrop-filter: blur()` 会得到「零视觉变化」。** 因为 `backdrop-filter` 模糊的是「元素背后已绘制的内容」；当前背后是 `body` 的**单一不透明纯色**，模糊纯色 ≡ 同色。**必须先造出可被模糊的背景氛围层，`backdrop-filter` 才有意义。**
3. **先做背景氛围层，再做面板半透明，最后才加 `backdrop-filter`** —— 顺序不能反，否则执行者会反复"加了没效果"。

## 15.2 实测证据（可复现，两主题）

命令：`venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py --port 8015 --theme both`

| 判据 | Dark（期望：玻璃） | Light（期望：玻璃） | 实测结论 |
|---|---|---|---|
| 全站带 `backdrop-filter` 的元素数 | **0** | **0** | ❌ 模糊机制**完全不存在** |
| 全站带 `background-image`（渐变/光斑）的元素数 | **1** | **1** | ❌ 仅 `.card.promo`（既非氛围层） |
| `.kpi-card` 的 `background-color` / alpha | `rgb(17,24,39)` / **1** | `rgb(255,255,255)` / **1** | ❌ 完全不透明 |
| 普通 `.card`（取 `#trend`/`#alerts`）alpha | **1** | **1** | ❌ 完全不透明 |
| `body` 的 `background-color` / `background-image` | `rgb(11,15,20)` / **none** | `rgb(247,248,250)` / **none** | ❌ 纯色底，无氛围 |
| `.topbar` alpha | **1**（`rgb(11,15,20)`） | **1**（`rgb(247,248,250)`） | ❌ 不透明，加 blur 也看不见 |
| `#sidebar` alpha | **1** | **1** | ❌ 同上 |
| `--card-glow` | `inset 0 1px 0 rgba(255,255,255,.03)` | `inset 0 1px 0 rgba(255,255,255,.7)` | ⚠️ 深色下 3% 白 ≈ 肉眼不可见；两主题差 **23 倍**，同名 token 语义未对齐 |
| `--card-shadow`（dark） | `0 1px 2px rgba(0,0,0,.32), 0 2px 8px rgba(0,0,0,.18)` | — | ⚠️ 纯黑投影叠在 `#0B0F14` 上 → 卡片「浮不起来」 |
| `.card.promo` `background-image` | `linear-gradient(135deg, rgb(29,78,216), rgb(14,165,233) 55%, rgb(20,184,166))` | 同 | ❌ 高饱和蓝青渐变 = 营销 banner 语言，与「暗底 + 图 + 玻璃叠层」不符 |
| `.card` / `.card.promo` 的 `border-color` | `rgba(0,0,0,0)`（promo 显式 transparent） | 同 | ❌ 玻璃切边被显式关掉 |

**布局侧的好消息（已达成，玻璃化时不得回退）**：

| 指标 | 本次实测 | §9 验收目标 | 结论 |
|---|---|---|---|
| `scrollHeight` @1920×1080 | **1235** | ≤1240 | ✅ 达成（原 2632） |
| `scrollWidth === innerWidth` | 1920 === 1920 | 必须 | ✅ |
| `.card` / `.kpi-card` 数 | 10 / 4 | — | ✅ 栅格化成功，5 列同排 |
| `console` error | **0** | 0 | ✅ |
| 顶栏日期 | `2026-09-11 周五` | 周五 | ✅ C6 缺陷已修 |
| 占位模块 | 资讯/资金流向/风险偏好 = 「数据未接入」 | 3 处 | ✅ |

→ **只需修视觉层，布局与数据层不要动。**

## 15.3 根因分析（两层）

### 15.3.1 渲染表现根因（用户实际看到什么）

1. **画面没有层次**：整页只有一个纯色 `rgb(11,15,20)`，没有明暗过渡、没有色彩光斑 → 玻璃「折射背景」的对象不存在，观感是「黑底上画了几个深灰矩形」。
2. **卡片像印刷色块，不像透光面板**：卡片是 `rgb(17,24,39)`（alpha=1）盖在 `rgb(11,15,20)` 上，两者只差一点点亮度 → 卡片边界靠一条 `rgb(30,39,51)` 细线维系，没有任何「透光/折射」暗示。
3. **卡片浮不起来**：投影是纯黑（`rgba(0,0,0,.32)`），在近黑背景上对比度几乎为零 → 本应「悬于背景之上」的卡片反而像「背景上贴的补丁」。
4. **边缘没有拾光**：顶部内高光只有 `rgba(255,255,255,.03)`（3% 白）× `#111827` → ΔL 远低于人眼阈值，实际不可见。玻璃的标志性「顶边一道亮线」完全缺失。
5. **promo 卡是全页最扎眼的违和点**：`rgb(29,78,216)→rgb(14,165,233)→rgb(20,184,166)` 是高饱和亮渐变，在一片近黑中像广告位；效果图那张卡是**暗调图片 + 半透明暗遮罩 + 玻璃边**。
6. **滚动时完全没有「玻璃随背景位移」的动感**：因为既没模糊也没背景变化，卡片与背景是刚性绑定。

### 15.3.2 代码逻辑根因（CSS/JS 机制）

| # | 机制根因 | 位置 |
|---|---|---|
| **G1** | **玻璃三要素同时缺失且互为前提**：① 半透明面板 ② `backdrop-filter` ③ 背景可模糊内容。当前 ① `--bg-elevated` alpha=1，② 全站 0 处，③ `body` 是纯色。**缺 ③ 时 ② 的视觉输出恒等于「无」** | `style.css:154-161`（`.card`）、`:188-194`（`.kpi-card`）、`:54-61`（`body`） |
| **G2** | **token 语义错配**：`--bg-elevated` 的语义是「提升层不透明底色」，被直接当卡片底色复用。玻璃需要**独立一组** glass token（bg alpha / border alpha / highlight / blur / saturate），**不能**复用不透明色 token | `style.css:4,32` |
| **G3** | **`--card-glow` 双主题量级不一致**：dark 取 `.03`、light 取 `.7`（**23 倍**）。同一 token 名承载两种完全不同的视觉强度 → 深色主题下高光失效，且改 light 参数会误伤 dark | `style.css:19,43` |
| **G4** | **`--card-shadow` 在深色下是纯黑**（`rgba(0,0,0,...)`）。深色底上玻璃卡片需要的是「微弱外发光 + 内高光」，黑投影在近黑背景上不可见 | `style.css:42` |
| **G5** | **边框是不透明深色** `rgb(30,39,51)`：形成的是「描边线」，不是玻璃的「半透明切边」。玻璃边必须是 `rgba(255,255,255,.08~.14)`，靠背景透出形成切边高光 | `style.css:34,156` |
| **G6** | **promo 卡走「实色渐变填充」路径**（`.card.promo{background:linear-gradient(...); border-color:transparent}`），语义上被实现为「彩色卡片」而非「图 + 玻璃叠层」，因此**无法通过调 token 变成玻璃**，必须单独改结构 | `style.css:216-232` |
| **G7** | **无 `saturate()`**：玻璃感相当一部分来自背景色被 `saturate(160~180%)` 提纯后透出。只加 `blur()` 不加上 `saturate()` → 透出来仍是灰调 | 全站 |
| **G8** | **无背景氛围层**：`.dash`/`.main`/`body` 都没有 `background-image` 或 `::before` 光斑 → 这是 G1 的 ③，也是**修复的首要工作项**（工作量占比 ~50%） | `style.css:54-61,142-151` |

### 15.3.3 因果链（必须按序修复，这是本追加的核心）

```text
[背景氛围层]  ← 缺失（G8）：body 无渐变/光斑，纯色
      │  没有它，后面两步全部无效
      ▼
[面板半透明]  ← 缺失（G1①）：--bg-elevated alpha=1
      │  没有它，backdrop-filter 采样不到任何东西
      ▼
[backdrop-filter: blur() saturate()]  ← 缺失（G1②）
      │  只有到这里，前三步才开始产生「玻璃」视觉
      ▼
[半透明亮边 + 内高光 + 外发光]  ← 缺失（G3/G4/G5）：切边拾光
      ▼
[玻璃感]
```

**反例（务必写进交接说明）**：若只做第三步（给 `.card` 加 `backdrop-filter: blur(20px)`），在 alpha=1 的卡片上**连模糊层都不渲染**；在 alpha<1 但背景纯色的情况下，模糊纯色 = 同色 → **两次都得到「零变化」**。这就是"加了没效果"的机制解释。

## 15.4 修复方案（替代方案 + 选型）

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（选）真玻璃** | `body` 叠多层 `radial-gradient` 氛围层 → 卡片改低 alpha → 加 `backdrop-filter: blur() saturate()` → 半透明亮边 + 内高光 + 外发光 | 唯一能产生真正「透光模糊」的机制；Chromium/Safari 支持良好（本项目已依赖 `:has()` 与 `color-mix()`，`backdrop-filter` 必然支持） |
| B 伪玻璃（降级） | 不做 `backdrop-filter`，仅用「半透明底 + 多层 `inset/outer` 阴影 + 亮边 + 氛围光斑」模拟 | 视觉约达 80%，**零层叠上下文副作用、零滚动开销**；作为 `@supports not (backdrop-filter: blur(1px))` 降级路径 |
| C 图片背景 | 页面铺一张暗色纹理图，玻璃叠上去 | 最接近效果图的 promo 观感，但违反 §13「不新增二进制资源」；且整页图片会拖累加载与主题切换 |

**选型：A 为主 + B 作为 `@supports` 降级。** 理由：A 是必要机制；B 独用时在深色底上玻璃感依然弱（无模糊），只能兜底不能主用。

**氛围层的实现要点（避免踩坑）**：氛围层**不要**新建 `position:fixed` 的 DOM 层，而是**直接给 `body` 叠多层背景**：

```text
/* 伪代码 —— 只描述层序，不写完整实现 */
body {
  background-image:
    var(--ambient-1),   /* 左上蓝光斑 */
    var(--ambient-2),   /* 右上紫光斑 */
    var(--ambient-3);   /* 底部青光斑 */
  background-color: var(--bg-primary);   /* 最底层，保持原纯色 */
  background-attachment: fixed;          /* 光斑固定，卡片滚动时"玻璃扫过背景"更有真实感 */
  background-repeat: no-repeat;
}
```

**为什么不用新增 DOM 层**：① 背景**不参与布局**，绝不会把刚达成的 `scrollHeight = 1235` 撑大（新增 in-flow 层会直接毁掉 §9 验收）；② 不引入 `z-index` 关系变化（避免与 `.topbar:100` / `#sidebar:60` / `.nav-backdrop:55` 打架）；③ 无额外合成层，零滚动开销。⚠️ 若坚持用 `body::before{position:fixed;z-index:-1}`，会被 `body` 自身的不透明 `background` **盖住而完全不可见**（经典陷阱），需同时把 `body` 底色改成透明 —— **不推荐**。

### 15.4.1 推荐的 glass token（双主题，**必须分别调参，不可一 token 通吃**）

**Dark（`[data-theme="dark"]`）**

| token | 建议值 | 说明 |
|---|---|---|
| `--glass-bg`（展示型卡：KPI / promo / 板块） | `rgba(255,255,255,.045)` | 低 alpha 才算玻璃 |
| `--glass-bg-strong`（**数据密集卡**：`#overview`/`#trend`/`#alerts`） | `rgba(17,24,39,.72)` | 保证表格小字可读性（见 R17） |
| `--glass-border` | `rgba(255,255,255,.10)` | 半透明亮边 |
| `--glass-highlight` | `inset 0 1px 0 rgba(255,255,255,.10)` | 顶边拾光（替代 `--card-glow` 的 3%） |
| `--glass-blur` | `blur(18px) saturate(180%)` | 必须带 `saturate`（G7） |
| `--glass-shadow` | `0 8px 32px rgba(0,0,0,.40)` | 替代 `--card-shadow` 的 1~2px 小黑影 |
| `--ambient-1` | `radial-gradient(900px 620px at 10% -8%, rgba(59,130,246,.22), transparent 62%)` | 蓝 |
| `--ambient-2` | `radial-gradient(760px 520px at 90% 4%, rgba(139,92,246,.18), transparent 62%)` | 紫 |
| `--ambient-3` | `radial-gradient(900px 640px at 55% 105%, rgba(20,184,166,.14), transparent 62%)` | 青 |
| `--bg-primary` | 不变 `#0B0F14` | 作为最底背景层 |

**Light（`:root`）**

| token | 建议值 |
|---|---|
| `--glass-bg` | `rgba(255,255,255,.62)` |
| `--glass-bg-strong` | `rgba(255,255,255,.86)` |
| `--glass-border` | `rgba(255,255,255,.90)` |
| `--glass-highlight` | `inset 0 1px 0 rgba(255,255,255,1)` |
| `--glass-blur` | `blur(16px) saturate(150%)` |
| `--glass-shadow` | `0 8px 28px rgba(16,24,40,.10)` |
| `--ambient-1` | `radial-gradient(900px 620px at 10% -8%, rgba(22,119,255,.12), transparent 62%)` |
| `--ambient-2` | `radial-gradient(760px 520px at 90% 4%, rgba(114,46,209,.10), transparent 62%)` |
| `--ambient-3` | `radial-gradient(900px 640px at 55% 105%, rgba(19,194,194,.10), transparent 62%)` |
| `--bg-primary` | 不变 `#F7F8FA` |

**同时退役 / 整改**：`--card-glow` → 由 `--glass-highlight` 取代（消除 G3 的 23 倍量级错配）；`--card-shadow` → 由 `--glass-shadow` 取代（消除 G4 的纯黑投影）。

### 15.4.2 顶栏 / 侧栏（可选，收益高）

`.topbar`、`#sidebar` 当前 `background: var(--bg-primary)` alpha=1，改为 `rgba(11,15,20,.72)`（light 为 `rgba(247,248,250,.72)`）+ `backdrop-filter: blur(12px) saturate(160%)` → 滚动时内容在顶栏/侧栏下模糊穿过，是效果图里最明显的玻璃线索。

### 15.4.3 promo 卡（结构改造，必须单独处理 —— G6）

目标形态 = 「氛围图 + 半透明暗遮罩 + 玻璃边 + 白字」：

- 底色由**高饱和亮渐变**改为**低饱和暗调**（如 `linear-gradient(160deg, rgba(37,99,235,.50), rgba(15,23,42,.78))` 叠一层 `radial-gradient` 作为"图片氛围"），保留现有 `.promo-visual` 内联 SVG 作为"图像抽象"。
- `border-color: transparent` → 改回 `var(--glass-border)`（当前这个声明把玻璃切边显式关掉了）。
- 加同一套 `--glass-blur`。

## 15.5 实施步骤（每步可独立验证）

| # | 步骤 | 文件 | 验证 |
|---|---|---|---|
| **G-1** | 定义 glass token（双主题）：新增 `--glass-bg`/`--glass-bg-strong`/`--glass-border`/`--glass-highlight`/`--glass-blur`/`--glass-shadow`/`--ambient-1~3`；退役 `--card-glow`/`--card-shadow`（或保留为别名以免遗漏引用） | `web/static/style.css` | 断言 `getComputedStyle(document.documentElement).getPropertyValue('--glass-blur')` 非空 |
| **G-2** | `body` 叠三层 `radial-gradient` 氛围 + `background-attachment: fixed` + 保留 `background-color: var(--bg-primary)` 作最底 | `web/static/style.css` | 断言 `getComputedStyle(document.body).backgroundImage` 含 `radial-gradient`；**且 `scrollHeight` 仍 ≤1240**（背景不参与布局，必须不变） |
| **G-3** | `.card` / `.kpi-card` 改玻璃：`background: var(--glass-bg)`、`border: 1px solid var(--glass-border)`、`box-shadow: var(--glass-shadow), var(--glass-highlight)`、`backdrop-filter: var(--glass-blur)` + `-webkit-` 前缀 | `web/static/style.css` | 断言 `.kpi-card` 的 `bgAlpha < 1` 且 `hasBackdropFilter === true` |
| **G-4** | 数据密集卡（`#overview`/`#trend`/`#alerts`）用 `--glass-bg-strong` 提高不透明度 | `web/static/style.css` | 目视表格小字可读；断言其 alpha 明显高于展示型卡 |
| **G-5** | `.topbar` / `#sidebar` 改半透明 + `backdrop-filter` | `web/static/style.css` | 断言两者 `bgAlpha < 1` 且 `hasBackdropFilter === true`；滚动时**无模糊残影**（sticky + backdrop-filter 的已知风险，见 R18） |
| **G-6** | `.card.promo` 改「暗调氛围 + 玻璃边 + blur」，去掉高饱和亮渐变与 `border-color: transparent` | `web/static/style.css` | 断言 promo 的 `borderTopColor` alpha > 0 且 `hasBackdropFilter === true` |
| **G-7** | `@supports not (backdrop-filter: blur(1px))` 降级块：退回方案 B（提高 alpha + 加强 inset 高光），保证 FireFox/旧内核不出现「半透明读不清」 | `web/static/style.css` | 用 `-webkit-backdrop-filter` 与 `@supports` 语法检查；目视降级态文字可读 |
| **G-8** | 回归护栏：布局与功能不得回退 | — | 断言 `scrollH ≤1240`、`scrollW === innerWidth`、`consoleErrors === 0`、375 下抽屉开关正常 |

**明确不做**：不动 `app.js` / `index.html` 结构 / `web/app.py`（玻璃化纯 CSS 层，若 G-6 需要调整 promo 的内联 SVG 才动 `index.html`）。

## 15.6 复现路径与关键测量点

### 15.6.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8015`（**本次已占用 8015，下一次验证用 8016**；务必换新端口，同端口会命中陈旧 CSS 副本产生假阴性 —— `pitfalls.md:200`）
3. 打开 `http://127.0.0.1:8015/`，硬刷新 `Ctrl+Shift+R`
4. 现状可观察：整页纯黑无光晕；卡片与背景仅一线之隔、无「悬空感」；顶边无亮线；promo 卡是突兀的亮蓝青块；滚动时卡片与背景刚性绑定、无任何模糊位移。
5. 测量：`venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py --port 8015 --theme both`

### 15.6.2 关键测量点（玻璃化的验收判据）

| 测量点 | 取法 | 现状实测 | 目标 |
|---|---|---|---|
| 全站 `backdrop-filter` 元素数 | 遍历 `document.querySelectorAll('*')` 统计 `backdropFilter !== 'none'` | **0** | **≥ 16**（10 `.card` + 4 `.kpi-card` + `.topbar` + `#sidebar`） |
| 卡片背景 alpha | `getComputedStyle(el).backgroundColor` 解析第 4 位 | **1** | `.kpi-card` **< 0.2**；数据卡 **0.6~0.8** |
| `body` 氛围层 | `getComputedStyle(document.body).backgroundImage` | **none** | 含 **≥ 3 层** `radial-gradient` |
| 顶边高光 | `boxShadow` 中的 `inset ... 0px 1px` 的白色 alpha | **0.03** | **≥ 0.08** |
| 边框颜色 alpha | `getComputedStyle(el).borderTopColor` | `rgb(30,39,51)` → alpha **1** | **0.08~0.14** |
| 外发光 | `boxShadow` 第一段 | `rgba(0,0,0,.32) 0 1px 2px` | 模糊半径 **≥ 24px**（`0 8px 32px`） |
| **布局回归** | `scrollHeight` @1920×1080 | **1235** | **≤1240**（不得因氛围层变大） |
| **溢出回归** | `scrollWidth === innerWidth` | true | 必须 true |
| **功能回归** | `consoleErrors.length` | **0** | **0** |
| **层叠回归** | 375 下 `#menu-toggle` → `body.nav-open` | 正常 | 仍正常（`backdrop-filter` 会创建层叠上下文） |

### 15.6.3 box-sizing 说明（本追加涉及）

`web/static/style.css:51` 仍为 `* { margin:0; padding:0; box-sizing:border-box }` —— **全局 border-box，无例外**。玻璃化对本任务的具体影响：

1. **改边框颜色/透明度不改尺寸**：`border: 1px solid var(--border)` → `1px solid var(--glass-border)`，宽度不变，卡片外尺寸与内容区都不变（border-box 下 border 已计入 `width`）。
2. **`backdrop-filter` 不影响盒模型**：它不参与 `width/height/padding/border` 计算，**只创建层叠上下文**（R18）。所以**不会**改变 §9 的任何尺寸验收值 —— `scrollHeight` 必须仍为 1235。
3. **`padding` 若调整需复核高度**：border-box 下 `height`/`min-height` **含 padding**。`.kpi-card` 当前 `padding:14px 16px` 且靠内容撑高；若为玻璃内边距把 padding 加到 `18px 20px`，卡片实际高度会增加，需复核 §5.2 的「KPI ≥96px」目标（只增不减，风险低）。
4. **氛围层必须不参与布局**：用 `background-image` on `body`（不参与布局）而非新增 in-flow 元素；否则 `scrollHeight` 会从 1235 涨上去，直接破坏 §9 验收。若用绝对/定位层，须 `position:fixed` + `pointer-events:none`，且**不能**用 `z-index:-1`（会被 `body` 不透明底色盖住而不可见）。
5. **`::before` 高光层（若采用）**：`position:absolute; inset:0` 在**绝对定位**下相对包含块的 **padding box**，不含 1px border；需父元素 `position:relative`（`.card` 实测已是 `position:relative` ✅），且必须 `pointer-events:none` 以免挡住表格点击/悬停。
6. **`--card-glow` 退役注意**：当前它是 `box-shadow` 的第二段（`box-shadow: var(--card-shadow), var(--card-glow)`）。替换时须确认没有遗漏引用，否则 `var()` 失效会导致整条 `box-shadow` 声明被丢弃（**CSS 变量未定义时整条声明 invalid**，不是只丢那一段）。

## 15.7 多尺寸验收

| 尺寸 | 玻璃化预期 |
|---|---|
| **1920×1080** | 背景可见 3 处光斑（左上蓝 / 右上紫 / 底部青）；卡片呈半透明、边缘有 1px 亮线、顶边有拾光；卡片间与卡片下方能看到背景明暗过渡；promo 卡为暗调玻璃而非亮渐变；**`scrollHeight` 仍 ≤1240**，`.row-kpi` 仍 5 列同排 |
| **1280×720** | 光斑位置随视口拉伸但不应出现「卡片全落在纯色区、看不出玻璃」的情况（光斑尺寸建议用 `px` 而非 `%`，保证小视口下仍覆盖）；`scrollWidth === 1280`；`backdrop-filter` 全量生效；主图与自选列表堆叠不变 |
| **375×812** | 卡片单列，玻璃仍生效；`backdrop-filter` 层数 = 卡数（性能敏感档，需目视滚动无卡顿）；侧栏抽屉（z=60）与 `.nav-backdrop`（z=55）层叠**未被 `backdrop-filter` 打乱**，点击背景仍能关闭抽屉 |
| **两主题** | Dark 与 Light **各自独立调参**（token 已拆双套）；切换主题后卡片玻璃强度、光斑颜色均需目视复查；不得出现「light 下文字糊在浅色光斑上」 |

## 15.8 风险与注意事项（追加）

| # | 风险 | 等级 | 说明与对策 |
|---|---|---|---|
| **R15** | **只加 `backdrop-filter` 得到零变化** | **高** | 机制见 §15.3.3：模糊纯色 ≡ 同色。**必须按 G-2 → G-3 顺序**。这是执行者最容易"改了看不到效果"进而怀疑代码的点 |
| **R16** | 氛围层把 `scrollHeight` 撑大，毁掉 §9 验收 | **高** | 用 `body` 的 `background-image`（不参与布局）；**不要**新增 in-flow 元素。G-2 验证必须同时断言 `scrollHeight` 不变 |
| **R17** | 半透明导致数据可读性下降 | **中** | 数字密集区（市场概览 6 小卡、趋势图 meta、告警正文）用 `--glass-bg-strong`（dark α≈0.72）；验收时目视 12px 小字是否仍清晰 |
| **R18** | `backdrop-filter` 创建**层叠上下文** | **中** | 任何 `backdrop-filter !== none` 的元素都会成为层叠上下文，改变内部 `z-index` 的参照系。必须回归：`.topbar:100` / `#sidebar:60` / `.nav-backdrop:55` 关系不变；375 下抽屉开关仍正常（`pitfalls.md:201` 同源特异性教训的延伸） |
| **R19** | `position: sticky` + `backdrop-filter` 滚动残影 | **中** | Chromium 在 sticky 元素上 `backdrop-filter` 偶发「模糊层不跟随重绘」。G-5 需**实际滚动**观察顶栏/侧栏是否有残影；有则把顶栏/侧栏降级为方案 B（不用 blur，只提 alpha + 亮边） |
| **R20** | 性能：多层 `backdrop-filter` 的每帧重算 | **中** | 当前将有 **16 个** backdrop 层。建议：只给 `.card`/`.kpi-card`/`.topbar`/`#sidebar`，**不要**给内部子元素重复加；375 档目视滚动帧率；必要时只保留大卡片（10 个） |
| **R21** | 双主题一 token 通吃 | **中** | `--card-glow` 已经踩过（dark 3% vs light 70%，23 倍）。新 glass token **必须双套已定义**，否则 `var()` 未定义会导致**整条 `box-shadow`/`background` 声明被丢弃**（CSS 变量失效是整条声明 invalid，不是只丢一段）—— 表现为「卡片突然没了阴影/底色」，容易被误判为写错选择器 |
| **R22** | promo 卡无法靠调 token 变玻璃 | **中** | G6 是**结构问题**（`.card.promo` 显式 `background:linear-gradient(...)` + `border-color:transparent`），必须单独改，不能指望继承 `.card` 的玻璃规则（会被自身声明覆盖） |
| **R23** | 与效果图强度不匹配 | **中** | 效果图原图在当前会话已不可读（见 §15.9），上面的 alpha/blur 是**按 glassmorphism 通用参数给的工程值**，未经效果图逐像素比对。执行者应先按建议值实现，再与效果图并排比对微调 |

## 15.9 待需求方确认（阻塞项）

1. **【阻塞精度】效果图需重新发送**：原 `image.png` 在本会话已无法读取（早期附件已失效）。玻璃的**强度**（blur 半径、面板 alpha、光斑饱和度）和 **promo 卡是否要真实照片底**，需要重发效果图才能做到逐像素贴近。缺图时按 §15.4.1 的建议值先实现，标注「参数待比对微调」。
2. **强度档位**：轻薄（`blur(12px)` / α≈0.03 / 光斑很淡）↔ 厚重（`blur(24px)` / α≈0.07 / 光斑明显）—— 效果图偏哪一档？
3. **promo 卡形态**：① 纯 CSS 暗调氛围（延续 §13「不新增二进制资源」）② 允许新增一张暗色氛围图（更接近效果图，但引入 ~200-400KB 二进制）。
4. **顶栏/侧栏是否也玻璃化**（G-5）：会引入 sticky + blur 的 R19 风险，收益是效果图里最明显的玻璃线索。

## 15.10 追加确认

- [ ] 人已审阅本追加方案
- [ ] 已知悉**责任归属**：玻璃缺失源于 §7 Step 2 的 token 设计，执行者无过错
- [ ] 已确认修复顺序 G-2（氛围）→ G-3（半透明）→ blur，不可颠倒
- [ ] 已确认布局回归护栏（`scrollHeight ≤ 1240`、无横向溢出、0 console error）**不得回退**
- [ ] 已确认 glass token **双主题双套**，无遗漏（R21）
- [ ] 已重发效果图 / 或同意先按建议参数实现并标注「待比对微调」
