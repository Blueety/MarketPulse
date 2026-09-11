# MarketPulse 视觉保真补齐（对照效果图）· 实施计划

> 架构师产出。**只提供规格，不含完整实现代码**；代码由执行者编写。
> 现状事实来自代码核对（`web/static/app.js` / `web/templates/index.html` / `web/static/style.css`）。

---

## 0. 前置说明

| 项 | 说明 |
|---|---|
| 触发 | 玻璃化任务 `tasks/2026-09-11-glassmorphism-fix/` 的 **§4.6.5** 记录了 5 条"与玻璃无关、但与效果图不符"的差距，需求方当时决定"下一个任务"处理。本任务即承接它 |
| 任务关系 | 独立于玻璃化（已完成并验收）与纹理调优 `2026-09-12-glass-texture-tuning/`。⚠️ 但**与 `2026-09-11-chart-hover-crosshair/` 都改 `app.js`** → **必须串行**，不要并发编辑 |
| prd.md | 无。Goal 来源 = §4.6.5 的差距清单 + 效果图 |
| 依赖 | **零新增依赖**（图标用 CSS 色块，不引 SVG 库、不引图标字体、不引图片） |

### 0.1 本任务的 5 项差距（均来自 §4.6.5）

| # | 差距 | 效果图 | 当前实现 |
|---|---|---|---|
| **V1** | 每行标的缺彩色小图标 | 自选列表 / 市场概览 / 资金流向 / 行业板块 **每行都有 ~16px 彩色圆角方块**（按品种品牌色） | 4 处列表**全部没有**图标 |
| **V2** | 趋势图 y 轴位置 | 刻度在**右侧**（`+6% / +3% / 0 / -3% / -6%`） | `scales.y` 未设 `position` → 默认**左侧** |
| **V3** | 品牌字风格 | `MarketPulse`（常规大小写、非等宽、无字距） | `MARKETPULSE`（`--mono` 等宽大写 + `letter-spacing:.1em`） |
| **V4** | 头像形状 | 深色**圆角方块** | 蓝色**圆形**（`border-radius:50%`） |
| **V5** | 侧栏导航标签 | 市场概览 / 自选列表 / 新闻资讯 / **宏观数据** / **市场日历** / 板块表现 / **设置** | 市场概览 / 市场趋势 / 市场情绪 / 美股板块 / 自选列表 / 最新资讯 / 告警记录 |

---

## 1. 任务目标

**Goal**

补齐 5 项与效果图的视觉差距：给 4 处列表每行加品牌色圆角图标、趋势图 y 轴移到右侧、品牌字改为效果图风格、头像改圆角方块、侧栏导航标签对齐效果图。

**一句话验收标准**

4 处列表（市场概览 / 自选列表 / 美股行业板块 / A 股热点板块）**每行首列都有 16px 品牌色圆角图标**；趋势图 y 轴刻度在**右侧**；顶栏品牌显示 `MarketPulse`；头像是深色圆角方块；侧栏 7 项标签与效果图用词一致且**无不响应的死链接**。

**必须保持（回归护栏）**

| 指标 | 当前实测 | 本任务要求 |
|---|---|---|
| `scrollHeight` @1920×1080 | **1216** | ≤1240（不变；加图标可能增 2~6px，须复核） |
| `scrollWidth === innerWidth`（三视口） | 1920/1280/375 | 仍成立（**加列后最易横向溢出**） |
| backdrop 全覆盖 | 11 / 11 | 不变 |
| Console error | 0 | 0 |
| `verify_ui.py` | EXIT=0 / ALL PASSED | 仍 EXIT=0（断言同步见 §5 Step F-5） |
| `pytest tests/` | 459 passed | 不变 |
| 玻璃 token（`--glass-*`、氛围 4 层） | 已落地 | **不动** |

**Out of Scope**

- 不动 `--glass-*` / 氛围层 / 布局栅格 / 断点。
- 不新增数据源（宏观数据就算 nav 加了"宏观数据"项，也不因此新增接口）。
- 不加新依赖、不加图片/SVG 库。
- 不做 crosshair（属 `2026-09-11-chart-hover-crosshair/`，串行排在后面）。

---

## 2. 现状基线（代码事实）

| 事实 | 位置 |
|---|---|
| `OVERVIEW_CARDS`（数据驱动 6 小卡定义：`id/label/source/[scale]/[suffix]`） | `app.js:79-86` |
| `renderOverview()` 渲染 `.mini-card`（`mini-label / mini-val / mini-sub`，无图标） | `app.js:149-171` |
| `renderWatchlist()` 渲染表格行（4 列：名称/现价/涨跌幅/迷你条），空态 `colspan="4"` | `app.js:679+` |
| `renderUsSectors()` 渲染 `.bar-row`；`.bar-row` 网格 = `minmax(0,1fr) 64px 58px`（3 列：名称/条/值） | `app.js:195+`、`style.css:412` |
| `renderSector()` 渲染 A 股板块表 `<td>` 4 列（板块/涨跌幅/成交额/领涨股） | `app.js:174-192` |
| `buildLineOptions()` 的 `scales.y`（**无 `position`** → 默认左） | `app.js:375-384` |
| `.brand-mark`：`--mono` / 14px / 700 / `letter-spacing:.1em` | `style.css:107` |
| 顶栏品牌文本 `MARKETPULSE`（大写） | `index.html` 顶栏 `.brand` |
| `.avatar`：`26px` 圆 / `border-radius:50%` / `background:var(--blue)` | `style.css:120`、`index.html:40` |
| 侧栏 7 个 `.nav-item`（`data-target`：`overview/trend/sectors/us-sectors/watchlist-section/news/alerts`） | `index.html:47-53` |
| 375 断点已隐藏 `.brand-mark` / `.avatar` / `#notify-btn` | `style.css:505` |

---

## 3. 方案

### V1 · 彩色小图标

**实现选型（零依赖）**：

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（选）** | `<i class="ico" style="background:<品牌色>">` 的 **16px 圆角方块**（`border-radius:4~5px`），**内含 1 个字符**（需求方 Q2 已定「内含字母」，2026-09-12） | 与效果图的"彩色圆角方块"一致；零依赖、零图片；颜色可由数据驱动 |
| B | 每个品种内联 SVG 徽标 | 更精致，但 8~20 个标的各写一份 SVG → diff 爆炸、难维护 |
| C | 图标字体 / SVG sprite 库 | 违反"不引入新依赖" |

**颜色来源**（单一事实来源，避免到处硬编码）：

- 已有序列色 token 直接复用：`--c-gspc / --c-ixic / --c-sh / --c-sz / --c-cyb / --c-vix / --c-gld / --c-btc`（`style.css` 已定义，双主题各一套）。
- 新增品种（美元指数 / 10Y 美债 / 原油 / 各板块）在 `app.js` 集中一个 `ICON_COLORS` 映射表补色，**不要在渲染函数里散写色值**。

**字符来源（每条目 1 个字符，数据驱动，禁止在渲染函数里硬编码）**：

| 落点 | 字符规则 |
|---|---|
| 市场概览 6 小卡 | `OVERVIEW_CARDS` 每项加 `char` 字段：`美股·标普500 → 美`、`A股·上证指数 → A`、`黄金ETF → 金`、`美元指数 → 元`、`10Y美债 → 债`、`原油 → 油` |
| 自选列表 | 按 `symbol` 查 `ICON_CHARS` 映射；查不到 → 取**名称首字符**（如 `红利低波ETF → 红`） |
| 美股行业板块 / A 股热点板块 | 取**板块名首字符**（`科技 → 科`、`能源 → 能`） |

**图标样式**：

```text
.ico { width:16px; height:16px; border-radius:5px; font-size:9px; line-height:1;
       color:#fff; display:inline-flex; align-items:center; justify-content:center;
       font-weight:600; flex-shrink:0; }
```

⚠️ **可读性风险（必须目视复核）**：16px 方块内放 1 个汉字，`font-size` 只能到 9px，处在可读下限。若看不清，按此顺序调整：
① `font-size` 提到 10px + 图标放大到 **18px**（`.bar-row` 图标列同步 18px → 20px）；
② 汉字改**单字母/符号**（如 `S` / `A` / `G`）；
③ 退回纯色块（放弃 Q2 的字符）。

**4 处落点与数据驱动方式**：

| 落点 | 改法 | 陷阱 |
|---|---|---|
| 市场概览 6 小卡 | `OVERVIEW_CARDS`（`app.js:79-86`）每项加 `color` 字段，`renderOverview` 在 `mini-label` 前插入图标 | 无 |
| 自选列表 | 按 `symbol` 查 `ICON_COLORS`（查不到回退中性色），在第 1 个 `<td>` 内插入图标 | ⚠️ 空态 `colspan="4"` → **必须改 5** |
| 美股行业板块 | `renderUsSectors` 每行插入图标；`.bar-row` 网格 → **`18px minmax(0,1fr) 64px 58px`** | ⚠️ 网格列数变了，`style.css:412` 必须同步 |
| A 股热点板块表 | `renderSector` 每行插入图标 `<td>` | ⚠️ 表头 4 列 → 5 列；`index.html` 的 `colspan="4"` 加载态 → **5** |

> 💡 建议统一一个 `iconHtml(keyOrSymbol)` 辅助函数返回图标 HTML，4 处共用，避免 4 份重复实现。

### V2 · y 轴移到右侧

在 `buildLineOptions()` 的 `scales.y` 加 `position: 'right'`：

```text
y: {
  position: 'right',     // ← 新增（效果图标度在右）
  grid: { color: tc.gridLine },
  border: { display: false },
  ticks: { ... 不变 ... }
}
```

⚠️ 两点：
1. **`saturate`/网格不要动**，只加 `position`。
2. **crosshair 任务已完成**（`2026-09-11-chart-hover-crosshair`，内联插件在 `app.js:452-562`），且已按设计**动态读轴侧**（`app.js:492` 注释「R7 勿写死 left」）→ 本任务把 y 轴移到右侧后，气泡应**自动改贴右侧，不需要改 crosshair**。
   ⚠️ **但必须回归验证**：轴移到右侧后重跑 crosshair 验收，确认气泡仍贴在**当前轴侧**而非仍贴左边。**这是本次唯一的跨任务回归点**（断言 F-7）。

### V3 · 品牌字

- `index.html`：`.brand-mark` 文本 `MARKETPULSE` → **`MarketPulse`**。
- `style.css:107`：去掉 `font-family: var(--mono)` 与 `letter-spacing: .1em`，改为系统字体 + 正常字距（保留 `font-weight:700` / `font-size:14px`）。
- ⚠️ 375 断点本就 `display:none`（`style.css:505`），移动端不受影响。

### V4 · 头像

- `style.css:120`：`border-radius: 50%` → **`6px`**（圆角方块）；`background: var(--blue)` → 深色表面（如 `var(--bg-hover)` 或 `rgba(255,255,255,.10)`），文字色改 `var(--text-secondary)`。
- `.avatar` 保留 `is-placeholder`（"数据未接入"占位，opacity .5）。

### V5 · 侧栏导航标签（Q1 已定：10 项方案）

效果图 7 项中，**宏观数据 / 市场日历 / 设置 3 项在页面里没有对应区块**：

| 效果图项 | 页面是否有对应区块 |
|---|---|
| 市场概览 | ✅ `#overview` |
| 自选列表 | ✅ `#watchlist-section` |
| 新闻资讯 | ✅ `#news`（当前标签"最新资讯"） |
| 板块表现 | ✅ `#us-sectors`（行业板块表现双 tab） |
| **宏观数据** | ❌ 无独立区块（宏观指标散在市场概览 6 小卡内） |
| **市场日历** | ❌ 完全不存在 |
| **设置** | ❌ 完全不存在 |

→ 照抄 7 项会造出 **3 个点了没反应的死导航**。**Q1 已定（需求方 2026-09-12）：采用「4 映射 + 3 保留 + 3 占位」的 10 项方案。**

**最终 nav（自上而下）**：

| # | 标签 | `data-target` | 性质 |
|---|---|---|---|
| 1 | 市场概览 | `overview` | 真实（不变） |
| 2 | 市场趋势 | `trend` | 真实（效果图无，**保留**） |
| 3 | 市场情绪 | `sectors` | 真实（效果图无，**保留**） |
| 4 | 自选列表 | `watchlist-section` | 真实（不变） |
| 5 | **新闻资讯** | `news` | 真实，**改名**（原「最新资讯」） |
| 6 | **板块表现** | `us-sectors` | 真实，**改名**（原「美股板块」） |
| 7 | 告警记录 | `alerts` | 真实（效果图无，**保留**） |
| — | （1px 分隔线） | — | — |
| 8 | 宏观数据 | **无** | **占位** `is-disabled` |
| 9 | 市场日历 | **无** | **占位** `is-disabled` |
| 10 | 设置 | **无** | **占位** `is-disabled` |

**占位项实现**（当前 7 项全是 `<a>`，需**新增** `is-disabled` 形态）：

```text
<span class="nav-item is-disabled" title="未开放"><svg …/><span>宏观数据</span></span>
```

- 用 `<span>` 而非 `<a>`，**不带 `href` / `data-target`** → 天然不可点、也不参与 `data-target` 断言。
- `style.css` 追加：`.nav-item.is-disabled { opacity:.45; cursor:not-allowed; }`
- ⚠️ **不要**给占位项写 `href="#"`（会跳到页顶，且会被断言误判成有效项）。

---

## 4. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/static/app.js` | **改** | `ICON_COLORS` 映射 + `iconHtml()` 辅助 + 4 处渲染函数插入图标 + `scales.y` 加 `position:'right'` + `OVERVIEW_CARDS` 加 `color` 字段 |
| `web/static/style.css` | **改** | `.ico`（16px 圆角方块）样式；`.bar-row` 网格加图标列；`.brand-mark` 去等宽/字距；`.avatar` 改圆角方块 |
| `web/templates/index.html` | **改** | 品牌文本 `MarketPulse`；A 股板块表 `colspan` 4→5；侧栏 nav 标签与占位项 |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **改（扩展，禁止覆盖）** | 同步断言（§5 Step F-5） |

---

## 5. 实施步骤（每步可独立验证）

### Step F-1 · 先跑基线

`venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` → 应 **EXIT=0 / ALL PASSED**（当前 `scrollHeight@1920=1216`）。
（若不是 0，先修再开始；否则加图标后分不清是本次改的还是本来就坏的。）

### Step F-2 · 图标（V1）

- 建 `ICON_COLORS` + `iconHtml()`；改 4 处渲染函数；同步 `style.css` 的 `.ico` 与 `.bar-row` 网格；同步 2 处 `colspan` 4→5。
- **验证**：4 处列表每行首列出现 16px 品牌色圆角方块；三视口**无横向溢出**；空态/加载态表格不塌陷。

### Step F-3 · y 轴右侧（V2）

- `buildLineOptions` 的 `scales.y` 加 `position: 'right'`。
- **验证**：刻度出现在右侧；`+6%/+3%/0/-3%/-6%` 未被裁切；切类别 tab 后仍正确；缩放/平移不受影响。

### Step F-4 · 品牌字 + 头像（V3 / V4）

- 按 §3 V3 / V4 改 `index.html` + `style.css`。
- **验证**：顶栏显示 `MarketPulse`（系统字体、无字距）；头像为深色圆角方块；375 档两者仍隐藏（无回归）。

### Step F-5 · 侧栏导航（V5）—— 需 §12 Q1 先定

- 按决策改 `index.html:47-53`。
- **验证**：**每个 nav 项点击后都能滚动到存在的目标**（或为明确 disabled 态）；无 `data-target` 指向不存在的 id。

### Step F-6 · 同步断言（不做就是假绿）

在 `verify_ui.py` 追加：

| # | 断言 | 目标 |
|---|---|---|
| F-1 | 4 处列表的图标数量 == 行数（`mini-card / watchlist tr / bar-row / sector tr`） | 全部相等 |
| F-2 | 趋势图 `chart.scales.y.position` | `'right'` |
| F-3 | `.brand-mark` 文本 | `'MarketPulse'` |
| F-4 | `.avatar` 的 `border-radius` | 非 50%（圆角方块） |
| F-5 | 所有 `.nav-item` 的 `data-target` 都能 `document.getElementById(...)` 命中，**或**该项带 disabled/占位标记 | true |
| F-6 | **回归**：`scrollHeight` @1920 ≤1240、`scrollWidth === innerWidth`、console error 0、backdrop 11/11 | 不变 |
| F-7 | **跨任务回归**：`chart.scales.y.position === 'right'` 时，crosshair 的 `$crosshairLabel` 仍产生且气泡贴**右侧**（气泡左边缘接近 `chartArea.right`） | true |

- **验证**：先跑一次，F-1~F-5 应 **FAIL**，改完应 **PASS**（证明断言在测东西）。

### Step F-7 · 全量回归 + 收尾

- `verify_ui.py` EXIT=0；`pytest tests/ -v` 全绿。
- 三视口 + 双主题目视。
- 追加 `docs/pitfalls.md`：**加列表列时必须同步 `colspan` 与 `grid-template-columns`**；**nav 标签照抄效果图会造出死链接**。
- 写 `tasks/2026-09-12-visual-fidelity/journal.md`。

---

## 6. 复现路径、测量点与盒模型说明

### 6.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8050`（**每次换新端口**；或直接跑 `verify_ui.py`，它自动挑空闲端口）
3. 打开 `http://127.0.0.1:8050/`，硬刷新 `Ctrl+Shift+R`。
4. 对照效果图逐项检查：市场概览 6 小卡 / 自选列表 / 美股行业板块 / A 股热点板块（切到 A 股 tab）每行首列图标；趋势图右侧刻度；顶栏 `MarketPulse`；头像方块；侧栏 7~10 项标签。

### 6.2 关键测量点

| 测量点 | 取法 | 目标 |
|---|---|---|
| 图标存在且数量对 | `querySelectorAll('.mini-card .ico').length` 等 4 组，与各自行数比对 | 相等 |
| 图标尺寸 | `.ico` 的 `offsetWidth × offsetHeight` | **16 × 16** |
| 图标圆角 | `.ico` 的 `borderRadius` | 4~6px |
| 网格列数同步 | `.bar-row` 的 `gridTemplateColumns` | **4 段**（含 18px 图标列） |
| 表格列数同步 | 表头 `th` 数与空态 `td.colspan` | 5 / 5 |
| y 轴位置 | `Chart.getChart($('#chart-main')).scales.y.position` | `'right'` |
| 品牌文本 / 字体 | `.brand-mark` 的 `textContent` 与 `fontFamily` | `MarketPulse` / 非 `--mono` |
| 头像 | `.avatar` 的 `borderRadius` + `backgroundColor` | 非 50% / 深色 |
| nav 有效性 | 遍历 `.nav-item`：`getElementById(data-target)` 命中 或 带 disabled 标记 | 全部 |
| `scrollHeight` @1920 | `scrollingElement.scrollHeight` | **≤1240**（当前 1216） |
| 无横向溢出 | `scrollWidth === innerWidth`（三视口） | true |

### 6.3 盒模型说明

`style.css:51` 为全局 `* { box-sizing: border-box }`（无例外），对本任务的三点影响：

1. **图标给固定尺寸最安全**：`.ico { width:16px; height:16px; border-radius:5px; }` —— border-box 下即使后续加 `border` 或 `padding` 也不会撑破 16px。
2. **⚠️ 加「列」会改变布局宽度，是最易横向溢出的操作**：
   - `.bar-row` 网格从 3 列变 4 列 → 必须压缩其它列或给图标列固定 `18px`，否则 375 档溢出。
   - 表格加 1 个 `<td>` → `colspan` 必须同步（空态/加载态），否则该行只占部分列、表格错位。
3. **不要给图标用 `margin-right` 推间距**：`.bar-row` / 表格用 `gap` 或列宽控制；图标列本身承担间距更安全。
4. 375 断点已隐藏 `.brand-mark` / `.avatar` → 改 V3/V4 后在 375 档看不到差异，**不要因此误判为改动没生效**（用 1920 档验收）。

---

## 7. 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | 4 处列表每行有 16px 品牌色圆角图标；y 轴刻度在右；顶栏 `MarketPulse`；头像圆角方块；nav 无死链接；`scrollHeight ≤1240` |
| **1280×720** | 图标不挤压文本（名称列需 `min-width:0` + `text-overflow:ellipsis`）；`.bar-row` 4 列仍不溢出；`scrollWidth === 1280` |
| **375×812** | 单列；表格/网格加列后**必须仍无横向溢出**；`.brand-mark`/`.avatar` 隐藏（既有断点，无回归） |
| **双主题** | 图标颜色复用 `--c-*` token → 自动随主题；若新增的 `ICON_COLORS` 用了硬编码色值，**必须补 light 档**，否则浅色主题下图标不可见 |
| **空态 / 加载态** | 自选列表与 A 股板块表在"数据暂缺 / 加载中"时，`colspan` 正确、不塌陷 |

---

## 8. 验证命令

```bash
# 【主验收】自动挑空闲端口 + 三视口 + 退出码 0/1
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

# 手动查看（每次换新端口）
venv/Scripts/python -m uvicorn web.app:app --port 8050

# 回归
venv/Scripts/python -m pytest tests/ -v
```

---

## 9. 风险与注意事项

| # | 风险 | 等级 | 说明与对策 |
|---|---|---|---|
| **R1** | **加列引发横向溢出** | **高** | `.bar-row` 网格与两张表格都要加列；375 与 1280 最易溢出。判据：`scrollWidth === innerWidth`；名称列须 `minmax(0,1fr)` + `min-width:0` + ellipsis |
| **R2** | **`colspan` 未同步 → 表格错位** | **高** | 自选列表空态 `colspan="4"`（`app.js:687`）与 A 股板块加载态 `colspan="4"`（`index.html`）都要改 **5**。加列时一并 grep `colspan` |
| **R3** | **nav 照抄效果图 → 死导航** | **高** | 宏观数据 / 市场日历 / 设置 3 项无对应区块。见 §12 Q1；断言 F-5 专防此项 |
| **R4** | ~~`app.js` 与 crosshair 任务冲突~~ | ✅ **已解除** | crosshair **已完成**（`2026-09-11-chart-hover-crosshair` 有 journal；插件在 `app.js:452-562`）→ 本任务**无需**与其串行。⚠️ 但保留一处跨任务回归：y 轴移到右侧后须复核 crosshair 气泡仍贴当前轴侧（见 §3 V2 第 2 点、断言 **F-7**） |
| **R5** | 图标颜色在 light 主题下不可见 | **中** | 复用 `--c-*`（双套已定义）最安全；新增 `ICON_COLORS` 若写死深色 → 浅底看不见。判据：双主题目视 |
| **R6** | `scrollHeight` 被图标顶破 | **中** | 加图标/加行高会让总高上升几 px；当前 1216，余量 24px。若超过 1240，优先收紧行内 padding，不要动栅格 |
| **R7** | y 轴移到右侧后刻度被裁切 | **中** | Chart.js 会自动布局，但需目视确认 `+6%/-6%` 未被切；必要时给 `scales.y` 加 `afterFit` 或调整 `layout.padding` |
| **R8** | 品牌字改动影响顶栏宽度 | **低** | `MarketPulse` 比 `MARKETPULSE` 略窄，375 档本就隐藏，无溢出风险；但 1280 档需确认顶栏不换行 |
| **R9** | 断言不同步 → 假绿 | **中** | 既有断言**都不覆盖**图标/轴侧/品牌/头像/nav，漏改不会被发现。必须加 F-1~F-5 |

---

## 10. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `web/static/app.js` | +约 85 / −5 行：`ICON_COLORS` + `ICON_CHARS` + `iconHtml()` + 4 处渲染插入 + `OVERVIEW_CARDS.color/char` + `position:'right'` |
| 修改 | `web/static/style.css` | +约 25 / −6 行：`.ico`、`.bar-row` 网格、`.brand-mark`、`.avatar` |
| 修改 | `web/templates/index.html` | +约 12 / −10 行：品牌文本、2 处 `colspan`、nav 标签 |
| 修改（扩展） | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | +约 25 行（F-1~F-6 断言） |
| 新增 | `tasks/2026-09-12-visual-fidelity/plan.md` | 本文件 |
| 新增 | `tasks/2026-09-12-visual-fidelity/journal.md` | 执行完成后写 |
| 新增 | `docs/pitfalls.md` 追加段 | 2 条（加列必须同步 colspan/网格；nav 照抄会产生死链接） |

**净代码变更估算**：约 **+155 / −46 行**（含 Q2 的字符映射数据）。

---

## 11. 不做什么

- 不动 `--glass-*` / 氛围层 / 布局栅格 / 断点 / 玻璃化成果。
- 不新增数据源与接口（尤其"宏观数据"nav 项不因此新增接口）。
- 不加新依赖、不加图片/SVG 库、不加图标字体。
- 不做 crosshair（另任务，串行）。
- 不新建"市场日历 / 设置"页面（超出本任务）。

---

## 12. 待确认（阻塞项）

### 12.1 决议（需求方 2026-09-12）

- **Q1 → 采用推荐方案**：「4 映射 + 3 保留 + 3 占位」的 **10 项** nav。完整清单与占位项实现（`<span class="nav-item is-disabled">`，**不带 `href` / `data-target`**）见 **§3 V5**。
- **Q2 → 图标内含 1 个字符**。字符由数据驱动（`OVERVIEW_CARDS.char` / `ICON_CHARS` 按 symbol 查 / 板块名首字符）；样式 16px 方块 + 9px 白字。**可读性处于下限**，调整顺序见 **§3 V1**。
- **Q3 → ⏳ 未答，按默认执行**：A 股热点板块表**也加图标**（效果图 A 股 tab 内同样有图标，且 V1 已列为 4 处之一）。若不同意，请在开工前指出。

> **至此无未决阻塞项，可开工。** 下表保留原始候选方案供追溯。

| # | 问题 | 说明与建议 |
|---|---|---|
| **Q1** | **侧栏导航如何处理 3 个无对应区块的项（宏观数据 / 市场日历 / 设置）？** | **推荐**：能映射的 4 项改名对齐效果图；无区块的 3 项按现有 disabled 模式渲染为**不可点占位**（灰化 + `title="未开放"`）；保留 3 项有真实内容的（市场趋势 / 市场情绪 / 告警记录）。最终 10 项而非 7 项 —— **有意为之**：删掉真实内容的导航入口是损失，造死链接是缺陷，占位是两者之间的正确解。<br>**替代**：若你更看重与效果图**完全一致**，则删除 市场趋势/市场情绪/告警记录 三个入口并重排为 7 项（代价：这 3 个区块失去导航入口）。 |
| **Q2** | 图标要不要**内含字母**（如"美""A""VIX"）？ | 效果图疑似是纯色块或极简符号，看不清是否有字。**默认：纯色块**（最干净、零维护）。若要字母，则 `iconHtml()` 里加首字母逻辑即可。 |
| **Q3** | A 股热点板块表**是否也要加图标**？ | 效果图里 A 股板块在"行业板块表现"的 A 股 tab 内，同样有图标 → **默认要加**（4 处之一）。 |

---

## 13. 确认

- [ ] 人已审阅本计划
- [x] **Q1 已定**：10 项 nav（4 映射 + 3 保留 + 3 占位）—— 见 §3 V5
- [x] **Q2 已定**：图标**内含 1 个字符**，数据驱动 —— 见 §3 V1
- [ ] **Q3 按默认执行**：A 股热点板块表也加图标（未答，若不同意请指出）
- [ ] 已知悉**图标字符的可读性风险**：16px 方块 + 9px 汉字处在可读下限，落地须目视并按 §3 V1 的顺序调整
- [ ] 已确认图标用 **CSS 色块**、零新依赖
- [ ] 已确认加列时**同步 `colspan` 与 `grid-template-columns`**（R1/R2）
- [ ] 已确认 `ICON_COLORS` 若新增色值须**补 light 档**（R5）
- [ ] 已确认本任务**与 crosshair 串行**（都改 `app.js`）
- [ ] 已确认 `verify_ui.py` **只扩展、不覆盖**
- [ ] 已确认回归护栏（`scrollHeight ≤1240`、无横向溢出、0 console error）不得回退
