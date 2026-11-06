# 实施计划 · 首页趋势卡双视图（对比 / 点位）

> 执行者只读本文件 + `prd.md` + 规范文件。**不要**读规划对话。
> 后端零改动：`/api/history` 已支持 `symbols` / `days`（`web/app.py:283-336`），`values` 是归一化、`raw` 是原始值。

## 任务概要

- **档位**: `T3 — 5 文件 / 0 调用方 / 行为有变 / 有现存 UI 门禁兜底 / 预估 320 行`
- **类型**: 加功能
- **目标**: 趋势卡升级为 `对比`（跨组自选）+ `点位`（单指数绝对点位，最大 10 年）双视图，共用同一 canvas，卡片高度不变。
- **相关文件**:
  - `web/templates/index.html`（趋势卡 98-131 行）
  - `web/static/app.js`（`GROUPS` 47-52、`state` 125-133、`buildQuery` 159-161、`renderTrendTabs` 702-724、`renderTrendMeta` 725-742、`renderMainChart` 750-851、`DOMContentLoaded` 装配 1300-1345）
  - `web/static/style.css`（追加 `.trend-chips / .trend-chip / .point-bar` 段）
  - `scripts/verify/verify_ui.py`（`tabCount` 探针 284 行、断言 4958 行、新增 `TM-*` 组）
  - `AGENTS.md` + `docs/pitfalls.md`（各一小段）
- **验证命令**:
  - `venv/Scripts/python.exe -m pytest tests/ -q`
  - `venv/Scripts/python.exe scripts/verify/verify_ui.py`
  - `venv/Scripts/python.exe scripts/verify/verify_offline_assets.py`

## 设计定稿（照此实现，不要另择方案）

### 状态

`state` 增加四个字段（`web/static/app.js:125` 处）：

```js
trendView: 'compare',   // 'compare' | 'point'
customKeys: [],         // 自选 tab 选中的 series key（小写，如 'gspc'）
point: { symbol: 'GSPC', days: 260, payload: null },  // 点位视图独立数据
```

localStorage 键（读不到就用默认，写失败静默 `try/catch`）：
`mp-trend-view` / `mp-trend-custom`（JSON 数组）/ `mp-point-symbol` / `mp-point-days`。

### DOM（`index.html` 趋势卡 `.card-head` 内）

```html
<div class="card-head">
  <h2>市场趋势 <span class="h2-sub" id="range-label">近 30 日</span></h2>
  <div class="seg" id="trend-view">
    <button type="button" data-view="compare" class="active">对比</button>
    <button type="button" data-view="point">点位</button>
  </div>
  <div class="seg" id="trend-tabs"></div>          <!-- 保持：JS 渲染，追加第 5 个「自选」 -->
  <div class="seg range-bar" id="range-bar"></div> <!-- 保持 4 个按钮不变 -->
  <div class="point-bar hidden" id="point-bar">    <!-- 2026-11-06 审查 C3：放进 head 与 tabs/range 二选一 -->
    <label class="point-label" for="point-symbol">标的</label>
    <select id="point-symbol"></select>
    <div class="seg" id="point-range"></div>       <!-- 1Y/3Y/5Y/10Y/全部，JS 渲染 -->
  </div>
</div>
<div class="trend-chips hidden" id="trend-chips"></div>   <!-- 自选 tab 专用，默认 hidden -->
```

⚠️ `.card-head` 是 `flex-wrap: wrap`：**默认态不要再塞可见元素**；新控件默认 `hidden`（门禁 `scrollHeight @1920 ≤ 1240`）。`#point-bar` 与 `#trend-tabs`/`#range-bar` **互斥显示**，同处 head 一行 ⇒ 点位态不额外增高（实测 1216）；`#trend-chips` 留在 head 之后的独立行，只在「对比 + 自选」时出现（实测 +34px → 1250，已接受）。

### 视图切换

- `#trend-view` 点击 → `setTrendView(v)`：切 `active` 类、切 `hidden` 显示 `#trend-chips` / `#point-bar` / `#trend-tabs` / `#range-bar`、写 localStorage、`window.__mpTrendMode = v`、再渲染。
- 点 `point` 时若 `state.point.payload` 为空或 symbol/days 变更 → `fetchPoint()`，否则直接 `renderPointChart()`。
- 切回 `compare` 直接 `renderMainChart()`（数据已在 `state.history`）。

### 对比视图

- `renderTrendTabs()`：`GROUPS` 四个照旧（**顺序不变**），末尾追加 `{id:'custom', name:'自选'}` 的按钮；点击逻辑同现有，`state.trendGroup = 'custom'` 时渲染 chips 行并显示。
- `renderTrendChips()`：10 个 chip（顺序同 `/api/history` 的 `series` 顺序，label 用 payload 的 `series[i].label`，缺则用 `SYMBOLS` 镜像常量）；点击 toggle `state.customKeys`（**至少保留 1 个**，取消最后一个时忽略），写 localStorage，`renderMainChart()`。
- `renderMainChart()` 取 `g.keys`：`custom` 组用 `state.customKeys`。**「自选」组合恒 ≥1**（chip 处理器与 `loadCustomKeys()` 双重保证），所以「一个都不选」的空态**不可达**：`renderMainChart()` 只保留通用「暂无趋势数据」兜底，不写 custom 专属文案。
- 现有归一化、tooltip、crosshair、zoom、`renderTrendMeta` 行为全部保持不变。

### 点位视图

- `#point-symbol` 由 JS 填充 10 个选项（`{value:'GSPC', text:'标普500'}` …，顺序同 `SYMBOLS` 注册表；写死一份与 `src/fetcher.py` 同序的常量数组即可，标注「与 SYMBOLS 同步」）。
- `#point-range` 按钮：`1Y=260 / 3Y=780 / 5Y=1300 / 10Y=2600 / 全部=3650`，`data-days` 属性承载。
- `fetchPoint()` → `GET /api/history?symbols=<SYM>&days=<N>`（大写符号；**只取 series[0]**）。
- `renderPointChart()`：
  - `raw` 为 y 值（绝对点位，**不归一化**）；x 轴复用现有 `buildTradingAxis` + `buildLinePts`（与对比视图同一套日期轴，保证 crosshair 行为一致）。
  - MA20 / MA60：对 `raw` 做滑动均值，窗口内不足 N 个有效值时该点为 `null`。
  - y 轴 tick：`fmtNumSep(v, 0)`（≥1000 用 0 位小数；<100 用 2 位，按最大值判断）。
  - crosshair：`plugins: [typeof window.makeHoverCrosshair === 'function'
      ? window.makeHoverCrosshair({ formatter: function (v) { return fmtNumSep(v, 2); } })
      : window.hoverCrosshair]`（`chart-crosshair.js` 硬契约：formatter 放**插件对象**上，不写进 `options.plugins`）。
  - meta（`#trend-meta`）：`<span class="meta-item">上证 1Y +12.30%</span>`、`区间最高 …`、`区间最低 …`、`数据自 YYYY-MM-DD`（`dates[0]`）。
  - 无数据 / `payload.series[0].raw` 全空 → `#chart-main-empty` 文案「该指数在所选窗口内暂无数据（数据自 <dates[0]> 起）」。
  - `window.__chartFailed || !window.Chart` → 沿用现有降级分支（隐藏 canvas + 提示），与对比视图同一路径。
  - 暴露测试钩子：`window.__mpTrendMode`、`window.__mpPointSymbol`、`window.__mpPointDays`、`window.__mpPointRawFirst`（`raw` 首个非空值，断言用）。

### 高度不变

- 两视图共用 `#chart-main` / `#chart-main-wrap` / `#chart-main-empty` / `#home-fail-bar` / `#home-chart-skel`；切换只 destroy + 重建 Chart 实例。

## 步骤

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | 改 `index.html` 趋势卡：加 `#trend-view` seg、`#trend-chips`、`#point-bar`（后两者 `hidden`） | `web/templates/index.html` | 低（只加容器） | `curl` 页面含新 id；`pytest tests/test_web.py -q` |
| 2 | `app.js` 状态 + 视图切换 + 自选 tab/chips + `renderMainChart` 分支（compare 路径行为不变） | `web/static/app.js` | **中**：`renderMainChart` 是首页最热路径，必须零回归 | 手工：默认态截图与改前一致；`verify_ui` 的 F-*/CS-* 全绿 |
| 3 | `app.js` 点位视图（fetch + render + MA + meta + 钩子） | `web/static/app.js` | 中：crosshair formatter 挂错会整页抛错 | 手工：点位 1Y 出图、tooltip 数值为绝对点位 |
| 4 | `style.css`：`.trend-chips/.trend-chip/.point-bar/#point-symbol` 样式（≤60 行，移动端 chips 可换行） | `web/static/style.css` | 低 | 390×844 截图 |
| 5 | `verify_ui.py`：`tabCount` 4→5；新增 `TM-1..TM-6` 断言组 | `scripts/verify/verify_ui.py` | 中：新增断言必须能对**旧实现**变红（先写断言再确认它红） | 见下「测试 Seam」 |
| 6 | 文档：`AGENTS.md` 首页模块描述加「趋势卡双视图」；`docs/pitfalls.md` 加一条（为何共用 canvas / `#trend-tabs` 顺序契约 / 10Y 档依赖回填） | `AGENTS.md`、`docs/pitfalls.md` | 低 | `sh scripts/check-gates.sh --staged` |

**不要做**：不改 `web/app.py`、不改 `src/**`、不跑 `scripts/backfill_history.py`（10 年回填是独立步骤，由派发方处理）。

## 测试 Seam

- **要测的 seam**: 前端渲染 seam —— `scripts/verify/verify_ui.py` 的 Playwright 真实页面断言（本任务无 Python 纯逻辑 seam，因为后端零改动）。
- **公开接口是什么**: 页面上可观察的 DOM/图表状态 + `window.__mp*` 钩子；不是内部函数。
- **错误与边界**:
  - 自选只剩 1 个 chip 时再取消无效（「至少保留 1 个」不变量，见 TM-5c）——因此**没有**「一个都不选 → 空态」这条边界（2026-11-06 审查 F6 定案；既有 tab 轮询要求每个 tab 切后都有图 + meta ≥1，空态会让门禁变红）；
  - 点位取数失败（注入 500）→ 卡内文案「点位数据获取失败」+ canvas 隐藏 + `#trend-meta` 清空，且 history 刷新成功**不得**抹掉该失败条（TM-9a..f）；
  - 点位视图某标的在该窗口全空 → 空态文案含「数据自」；
  - `window.Chart` 缺失（`__chartFailed`）→ 两视图都隐藏 canvas 并显示失败文案（复用现有分支，`verify_offline_assets.py` 已覆盖）。
- **为什么选这个 seam**（而不是更浅的那个）: 变化全在渲染层，没有可单测的纯函数；用真实浏览器断言「dataset 数 / y 值量级 / 请求 URL / 容器高度」才是用户能感知的结果。

### `TM-*` 断言组（写进 `verify_ui.py`，命名沿用既有分组风格）

| 编号 | 断言 | 采集方式 |
|---|---|---|
| TM-1 | 趋势卡头存在 `#trend-view` 两个按钮，`对比` 为 `active`，`#trend-tabs button` 共 5 个 | 探针 evaluate |
| TM-2 | 切「点位」后 `#point-bar` 可见、`#trend-tabs`/`#range-bar` 隐藏 | 探针 evaluate |
| TM-3 | 点位 1Y：`performance.getEntriesByType('resource')` 里出现 `symbols=<当前符号>&days=260` | 先点「点位」再切「1Y」，读资源条目 |
| TM-4 | 点位图的 y 值 == `/api/history` 响应 `series[0].raw` 首个非空值（±0.01）——**同源比对**，不用实现自己写的 `__mpPointRawFirst` 当期望值（钩子本身另由 TM-4c 对齐同一响应） | evaluate + `fetch` 同 URL |
| TM-5 | 切「自选」→ 10 个 chip；勾 `GSPC`、`SH` → dataset 数 = 2，且两条线首个非空 y 都在 100±0.01；再验证「只剩 1 个时取消无效」（TM-5c） | evaluate + click |
| TM-6 | 两视图来回切换后 `#chart-main-wrap` 高度变化 ≤ 2px，且 pageerror 数 = 0 | 前后读 `getBoundingClientRect().height` |
| TM-8 | `#range-label` 跟随视图/档位：点位 1Y → `1Y`；点位 10Y → `10Y（实际 N 个月）`（回填前不冒充 10 年）；切回对比 → `近 30 日` | 探针 evaluate（等目标状态出现，避免读到上一档位） |
| TM-9 | 点位取数失败（`page.route` 注入 500）：卡内文案「点位数据获取失败」+ canvas 隐藏 + `#trend-meta` 清空；随后 history 刷新成功**不得**抹掉失败条 | route + evaluate |

⚠️ 写完后**先对本任务改动前的主干代码跑一遍确认 TM-* 会红**（用 `git stash` 之外的只读方式：读 `git show HEAD:web/static/app.js` 无法造红 —— 改为先在未改 `app.js` 的页面上跑一次脚本，记录 TM-1/2/5 失败，再改代码）。

## 修 bug 时必填

（不适用：类型 = 加功能）

## 不做什么

- 不新建页面/路由/API；不改 `/api/history` 响应形状。
- 不做 10 年数据回填、不改 `data/marketpulse.db`。
- 不做 A/B 比值、分面小图、相关性矩阵。
- 不动 KPI / 板块 / 告警 / 资讯 / 自选列表模块。
- 不引入任何外部 CDN、不新增第三方库。
- 不改 `.env`、不改 `config.json`。

## 预估 diff 范围

- 新增文件: 无（仅任务目录文档）
- 修改文件: `web/templates/index.html`（+18）、`web/static/app.js`（+230）、`web/static/style.css`（+55）、`scripts/verify/verify_ui.py`（+95）、`AGENTS.md`（+2）、`docs/pitfalls.md`（+1 条）
- 删除文件: 无

## 确认

- [x] 人已审阅计划（用户 2026-11-06「先这样做吧」）
- [x] 档位声明与实际文件范围一致
- [x] 文件范围合理
- [x] 没有遗漏测试
- [x] 测试 seam 已写入本节
- [x] 没有引入不必要依赖
