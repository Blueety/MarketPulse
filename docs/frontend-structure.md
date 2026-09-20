# MarketPulse 前端结构（交接 / 优化用）

> 生成时间：2026-09-16。基于工作区实测（行数、行号、调用关系均为当时实况）。
> 定位：**只描述现状**，不含改造建议的实施细节；末尾 §9 给优化切入点。
> 相关文档：`docs/architecture.md`（后端分层）、`docs/system-overview.md` §2.4（Web 看板功能面）、`docs/pitfalls.md`（历史坑）。

---

## 1. 一页速览

| 维度 | 现状 |
| --- | --- |
| 页面 | **4 个**：`/`（看板）、`/macro`（全球宏观）、`/macro/cn`（中国宏观）、**`/timeline`（市场日历，2026-09-18 上线；用户可见名与「市场日历」占位项合并，2026-09-19）** |
| JSON API | **10 个**：`/api/history` `/api/latest` `/api/alerts` `/api/news` `/api/watchlist` `/api/macro` `/api/econ` `/api/econ/cn` `/api/cn/quotes` **`/api/timeline`** |
| 模板 | 6 个 web 模板（4 页 + 2 个 include） + 1 个非 web 模板（`report_card.html`，长图渲染用） |
| 静态资产 | `style.css` 1 份 + 业务 JS **4 份**（`app.js` / `macro.js` / `macro_cn.js` / **`timeline.js`**） + 共享插件 1 份 + SVG 素材 6 个（flags 2 / icons 4） |
| JS 框架 | **无框架、无构建**：原生 ES5 风格 IIFE + Chart.js 4.4.1（CDN）+ chartjs-plugin-zoom |
| 前端总规模 | ≈ **6,100 行**（`style.css` 1074 + `app.js` 1229 + `macro.js` 722 + `macro_cn.js` 805 + **`timeline.js` 380** + `chart-crosshair.js` 262 + 模板 ~572 + `web/app.py` 1254（含后端） |
| 主题 | 双主题（light / dark），CSS 自定义属性 token 驱动，`localStorage["mp-theme"]` 持久化 |
| 验收 | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（Playwright，**5 视口**，退出码 0/1；断言组 `MX/NA/QM/UX/PW/TL`） |

**请求拓扑**

```
浏览器
 ├─ GET /  |  /macro  |  /macro/cn  |  /timeline
 │                                        → Jinja2 渲染（no-cache 头，注入 asset_v / base_prefix / active_page）
 ├─ GET /static/*                        → _RevalidateStatic（强制 Cache-Control: no-cache，未变则 304）
 └─ fetch /api/*                         → FastAPI 只读端点（各自 TTL 内存缓存，失败恒 HTTP 200 降级空结构）
```

---

## 2. 文件清单

| 路径 | 行数 | 字节 | 角色 | 被谁引用 |
| --- | ---: | ---: | --- | --- |
| `web/templates/index.html` | 200 | 10.6 K | 看板页（bento 四行） | `/` 路由 |
| `web/templates/macro.html` | 125 | 6.5 K | 全球宏观页（五级块） | `/macro` 路由 |
| `web/templates/macro_cn.html` | 129 | 7.0 K | 中国宏观页（五级块） | `/macro/cn` 路由 |
| `web/templates/timeline.html` | 84 | 4.0 K | **市场日历页**（即将到来 / 已发生 / 口径与来源三块；内部名 timeline） | `/timeline` 路由 |
| `web/templates/_topbar.html` | 18 | 1.5 K | 顶栏（品牌 / 搜索 / 数据日 / 通知 / 头像 / 刷新） | **4 页** include，**无参数** |
| `web/templates/_sidebar.html` | 39 | 8.0 K | 侧栏（**12 项**导航 + 主题按钮 + 市场状态） | **4 页** include，吃 `base_prefix` / `active_page` |
| `web/templates/report_card.html` | 160 | 4.6 K | **非 web**：`src/image_renderer.py:202` 长图 HTML 模板 | 图片渲染链路 |
| `web/static/style.css` | 1074 | 68 K | 全站唯一样式表（含 `@media` × 16 处） | **4 页** `<link>` |
| `web/static/app.js` | 1229 | 56.3 K | 看板页业务脚本（21 个区块） | `index.html` |
| `web/static/macro.js` | 722 | 35.1 K | 全球宏观页业务脚本（单 IIFE） | `macro.html` |
| `web/static/macro_cn.js` | 805 | 36.1 K | 中国宏观页业务脚本（单 IIFE） | `macro_cn.html` |
| `web/static/timeline.js` | 380 | 20 K | **市场日历页**业务脚本（单 IIFE；本页无图表 ⇒ **不引入** Chart.js） | `timeline.html` |
| `web/static/chart-crosshair.js` | 262 | 14.8 K | **跨页共享**：crosshair 插件 + `cssVar`/`themeColors`/`withAlpha` | 3 页（**必须在业务脚本前**；`/timeline` 无图表故不引） |
| `web/static/flags/{cn,us}.svg` | — | — | 国旗图形素材（图标级简化） | `app.js:iconFlagHtml` |
| `web/static/icons/{dollar,bond,gold,oil}.svg` | — | — | 品种类圆形素材 | `app.js:iconAssetHtml` |
| `web/app.py` | 1254 | 60 K | FastAPI 应用：**4 页路由 + 10 API** + 静态挂载 + 资产版本号 | — |

---

## 3. 页面骨架

### 3.1 `index.html`（`/`）—— Bento 栅格，`.dash` 内 4 个视觉行

| 行 | 容器类 | 模块 id | 数据源 | 渲染函数 |
| --- | --- | --- | --- | --- |
| 行 1 | `.row-kpi`（5 等分） | `#lede`（`display:contents`，内含 4 张 KPI 卡） | `/api/history` + `/api/latest` + `/api/watchlist` + `/api/macro` | `renderLede()` + `paintSparklines()` |
| | | `#promo-global`（静态 promo，**"数据未接入"**） | 无 | **纯静态 HTML**，JS 不碰（`renderPlaceholders()` 只处理 `#fund-flow`） |
| 行 2 | `.row-main`（1.9fr / 1fr） | `#trend`（四图合一 + 4 类别 tab + 4 档时间范围 `#range-bar`） | `/api/history?days=` | `renderMainChart()` / `renderTrendTabs()` |
| | | `#watchlist-section`（**默认 `hidden`**） | `/api/watchlist` | `renderWatchlist()` |
| 行 3 | `.row-3`（3 列） | `#overview`（6 小卡 `#overview-body`） | `/api/latest` | `renderOverview()` |
| | | `#sectors`（3 子块：`#risk-appetite` / `#fund-flow` **占位** / `#market-relation`） | `/api/latest` | `renderRiskAppetite()` / `renderMarketRelation()` |
| | | `#us-sectors`（纯 CSS 双 tab：A股 `#sector-body` / 美股 `#us-sectors-body`） | `/api/latest` | `renderSector()` / `renderUsSectors()` / `renderSectorAsOf()` |
| 行 4 | `.row-news`（1fr / 2.4fr） | `#alerts`（`#alert-list`，自动循环滚动） | `/api/alerts` | `renderAlerts()` + `alertScroller` |
| | | `#news`（`#news-body`，自动循环滚动） | `/api/news` | `renderNews()` + `newsScroller` |

- KPI 卡 4 张 = 美股 / A股 / VIX / 自选；sparkline 用**原生 canvas 手绘**（不走 Chart.js）。
- 行 1 另有 `#promo-global`；顶部 `#lede` 与 promo 在**同一栅格**靠 `display:contents` 实现。

### 3.2 `macro.html`（`/macro`）—— `.mac` 五级分层

| 级别 | id | 内容 | 数据源 |
| --- | --- | --- | --- |
| 一级（无边框 `.mac-flat`） | `#mac-regime` | 当前宏观环境：`#regime-level` / `#regime-quadrant` / **`#regime-matrix`（2×2 四象限矩阵，2026-09-18）** / `#regime-score` / `#regime-factors` | `/api/macro`.regime + `/api/econ`.quadrant |
| 二级（唯一重卡 `.mac-card-hero`） | `#mac-market` | 主图 + 品种胶囊 `#macro-pills` + 范围 `#macro-range` | `/api/macro`.trend |
| 三级 | `#mac-metrics` | 两栏：`#macro-vars`（核心变量 3 个）+ `#macro-factors`（四维度打分） | `/api/macro` |
| 四级（`.mac-card-quiet`） | `#mac-signals` | 两栏：`#macro-rel`（相关性，默认 2~3 条 + `#macro-rel-more`）+ `#macro-history`（历史环境分布） | `/api/macro`.correlation / history_regime |
| 五级（`.mac-card-quiet`） | `#mac-econ` | 经济数据（BLS 四序列，`#econ-asof` + `#econ-basis`） | `/api/econ` |

### 3.3 `macro_cn.html`（`/macro/cn`）—— 同套 `.mac-*`，复用 + 少量 `.cn-*`

| 级别 | id | 与 `/macro` 的差异 |
| --- | --- | --- |
| 一级 | `#cn-regime` | 加 `data-quadrant` 供验收断言；右卡是 **PMI 3M**（非 Macro Score）；`#cn-axis` 两轴；**`#cn-matrix`（2×2 四象限矩阵，2026-09-18）** |
| 二级 | `#cn-market` | `#cn-pills` / `#cn-range` / `#cn-chart` |
| 三级 | `#cn-metrics` | `#cn-vars`（13 序列切片）+ `#cn-factors` |
| 四级 | `#cn-rates` | **利率与流动性** `#cn-rate-list`（Δ 单位 bp）+ **地产·北京/上海** `#cn-estate`（`.cn-dual`） |
| 五级 | `#cn-econ-card` | `#cn-econ` 明细 |

> `.cn-*` 只在 `style.css:837-881` 补了 ~8 条规则（`cn-dual` / `cn-city*`），其余全部复用 `.mac-*`。

### 3.4 共享骨架的两个模板参数

`web/app.py` 三个页面路由都传 3 个变量：

| 变量 | 含义 | 值 |
| --- | --- | --- |
| `asset_v` | 静态资源版本号 = `_ASSET_FILES` 中文件 **mtime 最大值**（`app.py:118`） | `"1789..."` 等 |
| `base_prefix` | 侧栏锚点前缀 | 首页 `""`（→ `#overview`）；宏观页 `"/"`（→ `/#overview` 回首页） |
| `active_page` | 侧栏高亮项 | `dashboard` / `macro` / `macro-cn` |

**侧栏 11 项**：市场概览·市场趋势·市场情绪·板块表现·自选列表·新闻资讯·告警记录（页内锚点，`data-target`）/ 宏观数据·中国宏观·**市场日历**（跨页链接，`href="/..."`，**不写 `data-target`**）/ 设置（`is-disabled` 占位）。验收断言 `navCount == 11 && navDisabled == 1 && !navBad`。

> 2026-09-19：「市场日历」原本是 2026-09-12 效果图遗留的**占位项**，现由真实页面 `/timeline` 接手（占位删除、位置原地保留）⇒ `navCount` 12→11、`navDisabled` 2→1。

---

### 3.5 `timeline.html`（`/timeline`）—— 市场日历（2026-09-18 上线；2026-09-19 接手同名占位项）

> 「市场日历」这个名字与位置**继承自 2026-09-12 效果图遗留的占位项**（来历见 `tasks/2026-09-12-visual-fidelity/plan.md` §12 Q1）。**内部命名一律保持 `timeline`**：路由 `/timeline`、`timeline.js`、`#tl-*` 类名、`TL-*` 断言、`econ_events` 表 —— 只有用户可见的名字是「市场日历」。

| 区块 | id | 内容 | 数据源 |
| --- | --- | --- | --- |
| 头部 | `.tl-head` | 标题 + 口径说明 + `#tl-scope`（库内事件数/可回溯范围/本轮窗口） | `/api/timeline`.stats / db_range |
| **即将到来** | `#tl-upcoming` | 未来 `future_days`（默认 30）天的排定日程；**未来事件不显示「事件后」窗口** | `past` 之外的 `upcoming[]` |
| **已发生** | `#tl-past` | 日期倒序；每天 = 事件行 + 当日涨跌 + 事件后 +1/3/5/10 交易日 + 叙事层；底部「加载更早」`#tl-more`（90 天 → 1 年 → 3.3 年 → 10 年，到库内最早事件自动隐藏） | `past[]` |

> **事件名中文化（2026-09-19，用户「英文看不懂」）**：服务端 `econ_calendar.zh_title()` 按「类型 + 数据期 + 估计阶段」**模板生成**中文名（如 `美国 8 月 CPI（消费者物价指数）`、`美联储议息会议（9 月 15-16 日）`、`美国 2026 年 Q2 GDP 终值`），**只翻译结构、不翻译内容**；源站**英文原文不丢** —— 挂在 payload 的 `title` 与 DOM 的 `data-title-en` / `title=`（悬停可见），由 `TL-10`/`TL-10b` 双向对账（中文必须出现、原文必须一致）。
> 源标题没有数据期时（如 `US CPI Release`）**不带月份**——不用发布日期顶替（那是错口径）。
> ⚠️ **新闻标题不在此列**：那是检索原文，翻译即二次加工。
| 口径与来源 | `#tl-meta` | 三个源的说明（`#tl-src`）+ 五条诚实边界（`.tl-honest`）+ 同步失败提示（`#tl-fail`） | `sources[]` / `failed[]` |

**每日一行**：`.tl-day`（`data-date`）→ 日期列（`.tl-date` + `.tl-week` + `.tl-rel` 今天/N 天后/已过 N 天）
+ 主列（`.tl-events` → `.tl-ev[data-kind]` / `.tl-metrics` 当日 / `.tl-metrics.tl-fwd` 事件后 / `.tl-news`）。

> ⚠️ 本页**没有图表**（不引 Chart.js / chart-crosshair.js）：两分区都是文字卡片，
> 唯一"图形"是日期列的对齐；主题按钮点击后只 `render()` 重渲染（颜色全走 token）。

---

## 4. API 契约（前端消费视角）

| 端点 | 消费方 | 缓存 TTL | 失败语义 | 关键字段 |
| --- | --- | --- | --- | --- |
| `GET /api/history` | `app.js`、`macro_cn.js` | 无 | 空数组降级 | `dates[]`、`series[].{key,values,raw}`；上限 `days≤3650`，支持 `symbols` / `start_date` / `end_date` |
| `GET /api/latest` | `app.js` | 无（读 context 文件） | `date:null` + 空结构 | `date`、`indices[10]`、`sector_heat`、`us_sector_heat`、`risk_appetite`、`correlation` |
| `GET /api/alerts` | `app.js` | 无 | `[]` | 最近 10 条（日期倒序） |
| `GET /api/news` | `app.js` | 无（读 `data/news.json`） | 空结构 | `date`、最多 8 条 `items[{title,url,source,published,summary}]`；URL 白名单 `http(s)://` |
| `GET /api/watchlist` | `app.js` | **90 s** | 有旧缓存 → 回退 + `stale:true`；否则空结构 | `stocks[]`、`hidden`（无配置）、`as_of` |
| `GET /api/macro` | `app.js`、`macro.js` | **300 s** | 只缓存成功结果 | `stocks`、`trend`(5Y)、`regime`、`correlation`、`history_regime` |
| `GET /api/econ` | `macro.js` | **6 h** | `as_of` 为空则不缓存 | BLS 四序列 + `inflation_axis` / `growth_axis` / `quadrant` |
| `GET /api/econ/cn?group=` | `macro_cn.js` | **6 h/组** | 单序列失败进 `failed`；**全部失败才不缓存** | 13 序列 + 中国版四象限；`group ∈ price\|growth\|money\|rate\|labor\|estate` |
| `GET /api/cn/quotes` | `macro_cn.js` | **90 s** | 失败降级 + `failed[]` | `cny`、`bond10y`、`credit_spread`(bp)、`as_of` |
| `GET /api/timeline?days=90&future_days=30` | `timeline.js` | **6 h**（按 `(days,future_days)` 分键） | 读 db，**不联网**；全空不写缓存 | `as_of`、`window`、`db_range`、`stats`、`sources`、`past[]` / `upcoming[]`（每个 day：`events[]` + `market{gspc,ixic,sh,vix_chg}` + `forward{"1"\|"3"\|"5"\|"10"}`） |

> 所有端点**恒定 HTTP 200**，降级用空结构表达 → 前端必须自行判空显示「数据暂缺」，不能靠 `r.ok`。

> 🔒 **鉴权（2026-09-19 起）**：上表全部端点（含页面与 `/static/*`）都要求 **HTTP Basic Auth**
> （`MP_AUTH_USER` / `MP_AUTH_PASS`）。前端零改动 —— Basic Auth 是浏览器原生机制，
> 一次弹窗后浏览器会**自动**对同域的后续请求（页面跳转、静态资源、XHR/fetch）带 `Authorization`。
> 这也是选它而不用 Bearer Token 的原因：`<a href="/macro">` 这类导航无法带自定义 header。
> 本地开发与自动化验收用 `MP_AUTH_DISABLED=1` 关闭鉴权。


---

## 5. JS 结构

### 5.1 `app.js`（看板页，无 IIFE，**全局函数 + 单例 `state`**）

| 行 | 区块 | 要点 |
| ---: | --- | --- |
| 5 | 主题切换 | `getTheme()` / `applyTheme()` |
| 24 | 序列色常量 | `SERIES_VAR` / `SERIES_FALLBACK` / `ALL_KEYS` / `colors()` |
| 47 | 配置常量 | `GROUPS`（4 类别 tab）、`PLACEHOLDERS`、`OVERVIEW_CARDS` |
| 71 | 图标系统 | `ICON_COLORS` / `iconHtml` / `iconFlagHtml` / `iconAssetHtml` |
| 107 | **全局 `state`** | `days` / `history` / `latest` / `latestDate` / `watch` / `macro` |
| 114 | 工具函数 | `escapeHtml` / `fmtNum` / `fmtPct` / `fmtAxisPct`（crosshair 默认口径）/ `buildQuery` |
| 142 | 日期工具 | `isWeekendDate` / `weekdayLabel`（**禁 `new Date("YYYY-MM-DD")`**） |
| 156 | 数据索引 | `sourceMap(kind)`：`indices` 是 list，必须按 symbol 建映射 |
| 171-345 | 渲染器 | `renderOverview` / `renderSector` / `renderRiskAppetite` / `renderUsSectors` / `renderSectorAsOf` / `renderAlerts` / `renderMarketRelation` / `renderNews` / `renderPlaceholders` |
| 362 | 自动滚动 | `makeAutoScroller(bodyId, itemSel)` → `newsScroller` + `alertScroller`（`scrollTop` + rAF，16 px/s） |
| 491 | 趋势主图 | `buildTradingAxis` / `buildLinePts` / `buildLineDataset` / `buildLineOptions` / `tickLimit` / `rangeShort` / `renderTrendTabs` / `renderTrendMeta` / `renderMainChart`（**四图合一**：归一化到 100） |
| 691 | crosshair | 使用 `window.hoverCrosshair`（默认口径） |
| 799-910 | KPI | `renderLede()` + `drawOneSpark` / `paintSparklines` / `repaintSparklines`（原生 canvas） |
| 911-956 | 自选列表 | `renderWatchlist`（纯 CSS 迷你条） |
| 957-1056 | 外壳行为 | `updateTopbarDate` + 市场状态机（`MARKET_SESSIONS` / `marketSessionOf` / `updateMarketStatus`，60 s 轮询） |
| 1057-1229 | 刷新与初始化 | `refresh()`（history + latest）→ `DOMContentLoaded` 里再拉 alerts / news / watchlist / macro |

**加载时序（`DOMContentLoaded`）**：`renderPlaceholders` → `renderTrendTabs` → `renderLede` → `updateMarketStatus`(+60 s 定时) → `refresh()`（history & latest 并行）→ alerts / news / watchlist / macro **各自独立 fetch**（watchlist & macro 带 12 s `Promise.race` 超时）。**没有统一 await，也没有 loading 汇总**。

### 5.2 `macro.js` / `macro_cn.js`（单 IIFE，函数内聚）

两份结构同构：

1. **外壳**：`getTheme` / `applyTheme` / `marketHM` / `marketSessionOf` / `marketStateOf` / `updateMarketStatus` / `bindShell`（抽屉 + 锚点是**逐字复制**的第三、四份）
2. **取数**：`getJSON(url, timeoutMs)`（AbortController）
   - `macro.js`：`loadAll()` = `/api/macro`(15 s) + `/api/econ`(15 s)
   - `macro_cn.js`：`loadEcon()`（**按组串行**：先 `price`+`growth` 出四象限，再其余组）+ `loadQuotes()` + `loadHistory()`
3. **派生**：`allSeries` / `byKey` / `asOfMonth` / `basis` / `failedKeys` / `regime`
4. **渲染**：`renderRegime` / `renderPills` / `bindPills` / `renderChart` / `renderChartFoot` / `renderVars` / `renderFactors` / `renderRelation` / `renderHistory` / `renderEcon` / `renderAll`
   - 四象限矩阵（2026-09-18）：`QUAD_CELLS`（四格 key → 兜底中文名，**渲染顺序 = 视觉顺序**：左上 goldilocks / 右上 reflation / 左下 deflation / 右下 stagflation）+ `quadrantMatrixHtml(curKey, curLabel, ax)` —— 两页**同源复制**（与 shell 的刻意复制同一决策，改一处必须同步改另一处）。当前格恒用服务端 `quadrant_label`，`ax` 由调用方按页传入（`/macro` 用 `↑/↓`；`/macro/cn` 用 `上行/回落` + `扩张/收缩`，因增长轴是 **PMI 与 50 的水平口径**）
   - `macro_cn.js` 另有 `fmtPeriod` / `yoyTitle` / `chgCell` / `varRow` / `renderRates` / `spreadRow` / `renderEstate`
5. **crosshair**：`macroCrosshairFormatter` / `cnCrosshairFormatter` → `window.makeHoverCrosshair({ formatter })`

### 5.3 `chart-crosshair.js`（共享插件 + 3 个全局小工具）

挂在 `window` 上：`cssVar` / `themeColors` / `withAlpha` / `hoverCrosshair`（默认口径）/ `makeHoverCrosshair({formatter})`。
硬契约见文件头注释（`id === 'hoverCrosshair'`、内联插件不 `Chart.register`、写 `chart.$crosshairLabel` / `chart.$crossSource`、`afterEvent` 节流 0.5 px、画在 `afterDatasetsDraw`）。

---

### 5.4 `timeline.js`（单 IIFE，本页无图表）

1. **外壳**：与 `app.js` / `macro.js` / `macro_cn.js` **同构的第 4 份副本**（`getTheme` / `applyTheme` / `MARKET_SESSIONS` / `marketSessionOf` / `updateMarketStatus` / `bindShell`）—— 改一处必须**四页同改**。
2. **取数**：`getJSON(url)`（AbortController 20 s）→ `/api/timeline?days&future_days`；`load(force)` 传 `_=<ts>` 绕过浏览器缓存。
3. **渲染**：`render()` → `fillList()` → `dayHtml()`；`metric()` 统一"标签 + 带向值的 `<b>`"；
   `fmtPct()` / `cls()` **按四舍五入后的方向判色**（`|v| < 0.005` 不写符号、不染方向色）。
   `weekdayZh()` 用 `Date.UTC` 纯函数取星期（**不用 `new Date("YYYY-MM-DD")`**，见 §7-12）。
4. **不做**：任何因果措辞、任何"利好/利空"标签、任何对 `forward` 为 `null` 的"补 0"。

---

## 6. CSS 结构（`style.css`，1074 行 / 单文件）

**Token 层**

| 范围 | 内容 |
| --- | --- |
| `:root`（1-40） | Light：底色 `--bg-*` / 文字 `--text-*` / 语义色 `--green --red --blue --orange` / glass 五件套 `--glass-*` / 氛围层 `--ambient-1,2` / **图表序列色 `--c-*`（10 个）+ 图表 UI 色** / 过渡 `--t-*` |
| `[data-theme="dark"]`（42-77） | 同键覆盖（#0B0F14 底 + #111827 卡 + 提亮 accent + `--text-muted` 对比度修正到 ≈6.9:1） |
| `body`（82-94） | 两层 `background-image` + `background-attachment: fixed` |

**区块顺序（行号即索引）**

| 行 | 区块 |
| ---: | --- |
| 96 | 顶栏 |
| 140 | 统一细滚动条（Chromium + Firefox 门控 `-moz-appearance`） |
| 166 | 骨架 `.shell` / `#sidebar` / `.nav*` / `.sidebar-footer` / `.ms-*` 市场状态 |
| 214 | **Bento 栅格**：`.dash` / `.row-kpi`(5) / `.row-main`(1.9:1) / `.row-news`(1:2.4) |
| 222 | 卡片 `.card` + `.card-head` + `.h2-sub` |
| 260 | KPI 卡 + promo 卡（`.lede{display:contents}`） |
| 323 | 趋势图 `.chart-wrap`(clamp 高度) / `.seg` 分段控件 |
| 350 | 数据表格 `.data-table` / `.pos` `.neg` / 迷你条 `.mini-bar` |
| 372 | 涨跌幅 badge `.chg-pill` |
| 392 | 市场概览 6 小卡 |
| 412 | 中卡子块（风险偏好仪表 / 资金流向 / 市场关系 pills） |
| 483 | **纯 CSS 双 tab**（`:checked` + `~` 兄弟选择器） |
| 519 | 美股 tab 表格（与 A 股同构） |
| 533 | 告警列表（左色条 + 紧凑行） |
| 544 | 静态占位 `.ph-*`（`data-placeholder="1"`） |
| 556 | 可访问性 / 微交互 |
| 564 | 响应式 1499 / 575:1399 / 580:1299 / 591:1024 |
| 595 | 平板·移动抽屉 `#sidebar` |
| 622 | 小屏手机（单列 + 显隐低价值列） |
| 675 | 骨架屏 `.skeleton` |
| 721 | **宏观页 `.mac-*`**（research terminal 风格，721-951；**2026-09-18 新增四象限矩阵 `.regime-matrix` / `.rm-axis` / `.rm-cell` / `.rm-skel` 于 838-853** —— 新类名，`.mac-*` 未动） |
| 952 | **中国宏观 `.cn-*`**（仅 8 条规则，952-997） |
| 998 | **事件时间线 `.tl-*`**（2026-09-18，998-1074；含 `.tl .up/.down` 涨跌色与 ≤768/≤480 两档响应式） |

**断点全景**（14 处 `@media`）：`768`(×4 处) / `1499` / `1399` / `1299` / `1024` / `480`(×4) / `1440 min-width` / `prefers-reduced-motion`。

---

## 7. 硬约束（改前端前必读）

这些是历史踩坑后的**有意设计**，不是待清理的坏味：

1. **主题初始化 4 处同源**：`index.html` head 内联脚本、`macro.html` head 内联脚本、`macro_cn.html` head 内联脚本、各 JS 的 `applyTheme()`。三页内联脚本语义**不一致**：`index.html` 只在值为 `light` 时写属性，两个宏观页是「显式应用任意存储值」。改一处必须四处同改。
2. **`chart-crosshair.js` 必须在业务脚本之前**：顺序错 → `plugins:[undefined]` 被 Chart.js **静默忽略**（不报错、横线不出现）。
3. **`_ASSET_FILES` 登记**（`app.py:115`）：新增/重命名静态文件必须加进去，否则改它不换 `?v=` → 验证吃到旧副本。
4. **shell 行为三副本**：`app.js` / `macro.js` / `macro_cn.js` 各有一份顶栏侧栏 shell 逻辑（主题、抽屉、市场状态、锚点），**刻意的复制**，改必须三处同改。
5. **canvas 位图 == 显示尺寸**：容器显式给高度 + `maintainAspectRatio:false` + **禁 `!important` 覆盖 canvas 尺寸**（DPR=2 时验收断言 `bitmapW == cssW×2 ± 1`）。
6. **双 tab 的 radio 必须是 `.tab-panels` 的前置同级兄弟**，且**不能 `display:none`**（会让 label 点击与键盘焦点一起失效）。
7. **骨架屏 `colspan` 必须等于实际列数**（板块表 5 列；自选表 5 列）——写少会错位。
8. **`.h2-sub` 必须是 `h2` 内的行内 span**：`#us-sectors-asof` 放进 `h2` 之外会撑破 `scrollHeight ≤ 1240` 护栏。
9. **`#lede` 用 `display:contents`**：不要让 JS 给它写样式（会破坏与 promo 同栅格）。
10. **`renderSectorAsOf()` 必须在两个板块都渲染完后调用**（越权提前读 `_sectorAsOf` 会拿到半成品）。
11. **验收脚本是唯一真源**：`venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（Playwright，5 视口 1920/1600/1280/900/375，自动挑空闲端口）。**不要以 `curl 200` 或肉眼看代替。**
11b. **验收三态语义（2026-09-20 起）**：`PASS` / `FAIL` / `SKIP`。**`SKIP` 只表示"该条无法判定，因为上游不可用（独立直连探测确认）"，它既不是通过、也不是回归** —— 看到 SKIP 先查那行 `上游探测: macro=? econ=?`，**别去改前端代码**。反过来：上游**可用**时同样的失败仍然是 `FAIL`（所以 SKIP 不会掩盖真回归）。新写断言时默认 `deps=()`（永不 SKIP）；只有**确证依赖上游数据**才标 `deps=("macro"|"econ",)`，且**"空态也该成立"的断言不许标**（会变成掩盖 bug 的开关）。
12. **不要用 `new Date("YYYY-MM-DD")`**：会有本地时区偏移，日期/星期一律走 `app.js:142` 的日期工具。
13. **四象限矩阵的排布与契约（2026-09-18）**：排列固定为教材口径（横轴通胀 左低右高 / 纵轴增长 上高下低），**不许为"好看"改排列**；象限**无褒贬**，只做中性高亮（`--bg-elevated` + `--blue` 边框），**禁止染红绿**（会被读成涨跌）。`#regime-quadrant`（文字行）与 `#cn-regime[data-quadrant]` 是既有验收契约，矩阵是**新增兄弟元素**、不得替换它们；骨架节点必须标在**容器内部**（`clearSkel` 是 removeChild 自身，标在容器上会把容器删掉）。

14. **事件时间线的三条契约（2026-09-18）**：① `forward` 为 `null` = **未走满** ⇒ 必须渲染「待走满」，**绝不允许显示 0.00%**（`TL-6` 逐格与 API 对打）；② 事件与行情**并列展示**，事件区不得出现因果措辞、不得打「利好/利空」标签（`TL-7`）；③ 事件类型只能是 `src/econ_calendar.KINDS` 的枚举（`TL-3`），**归一化漏配会让同一事件在页面上出现三四次**。另：侧栏 nav 由 11 项变 12 项，`verify_ui` 的 `F-5` / `CN-7` 两处 `navCount` 已同步。

---

## 8. 未接入 / 占位清单（现状）

| 位置 | 形态 | 说明 |
| --- | --- | --- |
| `#fund-flow`（资金流向） | **唯一** `data-placeholder="1"` 模块 | 验收断言全站计数 = 1、文案 = "数据未接入" |
| `#promo-global`（全球市场动态） | 静态 promo 卡 | 文案"数据未接入"，无数据源 |
| 顶栏搜索 / 通知 / 头像 | `.is-placeholder` + `disabled` | 纯视觉 |
| 侧栏「设置」 | `.nav-item.is-disabled` | `navDisabled == 1`（「市场日历」占位已于 2026-09-19 被同名真实页面接手） |
| `#us-sectors` 的「查看全部 →」 | `.link-btn` + `disabled` | — |
| `#watchlist-section` | 默认 `hidden`，`/api/watchlist` 返回 `hidden:true` 时保持隐藏 | 无配置不闪现 |

---

## 9. 优化切入点（供参考）

**架构层面**

1. **`app.js` 1229 行单体** —— 无 IIFE、全全局函数，`state` 单例被所有渲染器直接读写。拆分时可先按 §5.1 的区块边界切（工具 / 渲染器 / 图表 / 外壳）。
2. **shell 三副本** —— 抽共享文件是可行的，但**成本明确**：需在 3 个模板里按「业务脚本之前」的顺序引入 + 在 `_ASSET_FILES` 登记。
3. **`style.css` 881 行单文件** —— 内含 3 个页面的样式（`.dash-*` 系 + `.mac-*`/`.cn-*` 系）。拆分注意 `.cn-*` 依赖 `.mac-*` 的变量与选择器顺序。
4. **取数无统一层** —— `app.js` 6 处裸 `fetch`，超时/降级/错误文案各写各的（watchlist & macro 有 12 s race，alerts/news/trend 没有）。

**体验层面**

5. **加载态不统一** —— 骨架屏只在 HTML 静态写好（overview / watchlist / sectors / alerts），news / KPI / 宏观页首屏是空白或「—」。
6. **响应式坏带** —— `1500–1919`（五列 KPI 无专属断点）与 `769–1024`（三列挤爆）曾实测为坏带，已补断点；改动栅格后**必须五视口重测**，别只测 1920/1280/375。
7. **图表 CDN 依赖** —— Chart.js 与 zoom 插件走 jsdelivr，`onerror` 只置 `window.__chartFailed/__zoomFailed` 标志，各页未统一消费（`macro` 页有 `#macro-chart-fail`，首页只有 `.chart-empty`）。
8. **`macro_cn.js` 分组串行取数** —— 冷启动 13 个 AkShare 接口 + 中债 8 s，前端超时已给到 30 s；交互上可考虑更明确的进度反馈。

---

## 10. 验证命令

```bash
# UI 验收（5 视口，退出码 0 = 全绿）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

# 后端契约测试
venv/Scripts/python -m pytest tests/test_web.py -v

# 本地起服务
venv/Scripts/python -m uvicorn web.app:app --port 8000
```

> ⚠️ `verify_ui.py` 常年存在 12 条基线红（上游数据层 10 条 + Firefox CSSOM 2 条），见 `docs/system-overview.md` §9 G8。
> 判"是不是我改出来的"必须做基线 A/B（`git archive HEAD` 建隔离副本），**不能只看绝对条数**。
