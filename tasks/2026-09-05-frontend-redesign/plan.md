# 实施计划 — MarketPulse 前端 UI/UX 重构（按 PRD，2026-09-05）

> 任务目录：`tasks/2026-09-05-frontend-redesign/` ｜ PRD：`D:\下载\prd.md`（一~二十节 + 验收清单，全读）
> 定位：Professional Financial Dashboard × 现代 FinTech × Apple 克制；不做花哨 SaaS/霓虹/玻璃/渐变；**严格按 PRD，不引入外部站点约束**。
> 前置：I/I.5/I.6 已上线（lede、row-flash、trend-sub、3 列表格）——本计划在其上重构，不推翻业务逻辑（PRD §十九）。
> 实测基线（8001，1440px，2026-09-05）：行高 46/50.8 参差、`td.num` 左对齐、7/10 行 row-dim 淡化、container max-width 1440（1920+ 两侧留白）——重构需修复项。

## 0. 目标 ↔ PRD 节映射

| PRD | 目标 | 落地位置 |
|---|---|---|
| §二 布局 | Sidebar 220-240 + main flex:1，`max-width:none`+padding 24-40，1440/2K/4K 铺满 | index.html 骨架 + style.css |
| §三 Header | 56-64px 细边框；左 MARKETPULSE+市场看板；右 数据截至/刷新/主题 | 改造 topbar |
| §四 颜色 | Light #F7F8FA 优先完整设计 + Dark 完整；accent #1677FF、涨 #16A085、跌 #F05A5A；无霓虹/渐变/大蓝底/玻璃 | :root 双主题 token + JS 图表色同步 |
| §五 KPI | Market Summary 4 卡：数字 28-32px tabular、状态次级、sparkline（可选）、低圆角无阴影 | 现 lede → 4 卡重构 |
| §六 表格 | 5 列（指数/最新价/涨跌/涨跌幅/状态）、细 border、数字右对齐 tabular | overview 表重构 |
| §七/八 趋势 | 7/30/90 筛选+资产分类；2 chart 50/50（小屏堆叠）；高足量；grid 极淡；线 1.5-2px；tooltip 精致 | charts 区 + renderChart options |
| §九 图例 | 灰标签+彩色点+选中 opacity；弃彩色 pill 堆 | 图例 DOM/CSS/交互 |
| §十 Sidebar | 6 菜单；active=浅 bg + 2px accent 左线；线性图标 | 新增 aside + 锚点 |
| §十一~十四 | 圆角 8-10/6px、阴影禁用、系统字体+tabular、四级信息层级 | CSS 全局 |
| §十五/十六 响应式 | 1280/1440/1920/2560 铺满；移动端抽屉/KPI2列/表横滚/chart 单列高 260-320 | media queries + 抽屉 |
| §十七 Dark | #0B0F14/#0F141B 分层，非纯黑霓虹 | data-theme=dark 变量 |
| §十八 微交互 | hover 100-150ms、切换 200-300ms、reduced-motion | transition 全局 + 开关 |
| §十九 不破坏 | API/计算/时间/状态/Dark/Refresh/组件功能全保留 | 仅动 DOM/CSS/展示 JS |
| §二十 验收 | PRD 末尾 checklist 逐项过（几何脚本化断言） | P4 |

## 1. 决策点（实施前定案）

- **a) 状态列删/留**：按 PRD 回 **5 列**（指数/最新价/涨跌/涨跌幅/状态）。理由：PRD §六 明确 5 列且「规范优先」；I.5 的 trend-sub 移出名称列 → 状态列承载「连涨/连跌N日」趋势文本（现状 status 字段后端已下发，前端过滤显示即可，不动后端）→ 一举修复 I.6 行高参差。涨跌绝对额：前端由 `value/(1+change_pct/100)` 算 prev 差值，**不加后端接口**（保留 §十九）。
- **b) Sidebar**：**纯前端**——单页模板内加 `<aside>` + section id 锚点滚动（平滑 200ms）；不改 app.py 路由/不拆页。active 态由 scroll 监听或点击更新。
- **c) 图标**：**内联 SVG**（6 个 16px stroke 线性图标内联进 aside；用 `<svg>` 直接写入模板或 JS 数组渲染），零新依赖（符合 PRD 验收「不引入不必要 UI 依赖」）。
- **d) 与 I.5/I.6 整合不返工**：重构直接改现有 renderOverview/renderLede/renderCharts 的 class 与模板串，保留其数据读取/计算逻辑；trend-sub 从名称列迁状态列（1 行 JS）；:root 变量重写为双主题 token（变量名沿用 --bg-*/--text-* 族，图表 JS 的 COLORS/themeColors 改为按 `data-theme` 取数组并重绘）；row-flash/row-dim 语义保留但收窄（I.6 修复项并入 P3）。
- 不确定/需问用户（实施前确认）：① KPI sparkline 数据源——现 /api/latest 无 30d 序列，sparkline 需复用 /api/history 或 /api/watchlist trend 各标的最后 ~15 点（可行但每 KPI 一次 join，实施时按最小实现，可降级为「不画 sparkline、留空位」）；② 侧栏「新闻资讯/宏观数据/市场日历/设置」为目标 PRD 菜单但当前页面无对应内容模块——首版锚点指现有最接近区块或占位禁用态（建议：导航只列现有内容可达项，其余置 disabled 灰态，待业务模块落地再启）。

## 2. 涉及文件

- `web/templates/index.html`（主战场：骨架 aside/header/main、renderOverview、renderLede、图例、theme toggle、chart options）
- `web/static/style.css`（全部 token/组件/响应式重写；预估 diff ~60%）
- `tests/test_web.py`（若 DOM class 断言受影响则同步，预计无 API 契约变化）
- 不改：`web/app.py`、`src/*`、`data/`（§十九）

## 3. 分阶段实施（每阶段独立可验证）

### 阶段 1：布局骨架（Sidebar + Header + 主区铺满）
- index.html：`body` 结构改为 `.shell{display:flex}` → `<aside id="sidebar">`（220-240px，含 6 菜单 + 内联 SVG）+ `<main>`（flex:1）；现有 `.container` 改 main 内主区 `max-width:none; padding: 24px 32px`（1920/2560 可 32-40px）；Header 56-64px 细边框（改造现有 topbar：左品牌、右 数据截至/刷新/主题 保持原事件）；各 section 加 id（overview/trend/watchlist/alerts…）供锚点。
- style.css：sidebar 固定 `position:sticky; top:0; height:100vh`；active 菜单 `background:rgba(accent,.08)+2px left line`；移动端隐藏 → P4 抽屉。
- 验证：8001 `tab.evaluate`：1440/1920 视口断言 `sidebar.offsetWidth≈230`、`main 宽 = viewport - sidebar - padding`（无中间挤）、滚动锚点跳转正常；`pytest tests/test_web.py` 无涉。

### 阶段 2：颜色/双主题 tokens（Light 优先）
- style.css `:root` 重写 Light：bg #F7F8FA、card #FFF、text #111827/#6B7280/#9CA3AF、accent #1677FF、pos #16A085、neg #F05A5A、border 极浅灰；`[data-theme="dark"]` 覆盖：bg #0B0F14/#0F141B/#111827 分层、border 低对比、accent 提亮（如 #3B82F6 系）。主题切换逻辑保留（现有 toggle 改设 `document.documentElement.dataset.theme`，localStorage 持久化同现状）。
- 图表色同步：index.html 的 COLORS/themeColors 改为函数按 theme 返回色组；切主题时对存活 Chart 实例调 `chart.update()` 或销毁重渲染（renderCharts 已集中，按现有重渲染路径走）。
- 验证：两主题切换截图；`tab.evaluate` 断言切换后 `getComputedStyle(document.body).backgroundColor` 与 css 变量、图表 line 色取自新主题（读 canvas 附近 chart.options.data.datasets[0].borderColor）。

### 阶段 3：组件重构（KPI/表格/趋势图/图例）
- **KPI**：renderLede 输出改 4 卡（.kpi-card：label 小字 → 28-32px tabular 数字 → 状态+涨跌幅语义色；圆角 8-10px 无阴影，`border:1px solid var(--border)`）；sparkline 可选（决策①，最小实现：用 /api/history 对应标的最后 15 点画 40px 高 mini canvas 或跳过）。
- **表格 5 列**：renderOverview：名称列回单行（trend-sub 移除）；新增「涨跌」列（前端算 diff）；恢复「状态」列（status 过滤：连涨/连跌N日、异动、失败显示；休市/未开盘 交易状态由涨跌幅列 `休市/—` 表达——与 I.5 语义一致但列数对齐 PRD）；`td.num/th.num{text-align:right}`；row-dim 收窄（I.6 修复③：仅失败/异常行弱化，休市回填行不透明淡化）；细 border + hover 浅背景（现 hover 已接近）。
- **趋势区**：range 7/30/90（现 chart_days 控制？/api/history?days= 已支持 1-90，前端按钮接上）；资产分类组（现 group-bar 已有雏形 → 按 PRD 4 组配置）；2 chart 50/50 并排 grid（现有 charts-grid 改造 `repeat(2,1fr)`，小屏 1fr）；chart options：grid 极淡、line 1.5-2px、tooltip 小型化（Chart.js tooltip padding/font 调）；图例：灰标签+彩色圆点 2px + 未选中 opacity .35（改现有 legend/chip 逻辑与 DOM）。
- 验证：表格几何断言（行高一致 ±1px、td.num 右对齐、5 列 th/td 匹配）；range 切换触发 /api/history?days= 变化；两 chart 等高并排；图例点击显隐仍工作；截图对照。

### 阶段 4：响应式 + 微交互 + 验收
- 响应式断点：1280（紧凑 padding）、1440/1920/2560（铺满 + 大屏略增 padding）；移动端 ≤768：sidebar → 顶部抽屉（汉堡按钮显隐 overlay + 遮罩，100-200ms 过渡）、KPI 2 列 grid、表格 .table-scroll 横滚、chart 单列高 260-320px（canvas height !important 按任务 E 教训配 maintainAspectRatio:false）。
- 微交互：统一 transition 100-150ms（hover）/200-300ms（主题/抽屉）；`:focus-visible` outline accent；`prefers-reduced-motion: reduce` → 关 transition/Chart 动画（matchMedia 读 Chart.defaults.animation=false，任务 I 预案）。
- 验收（PRD §二十 checklist 脚本化）：container 宽=viewport（2560 视口断言）、KPI 数字字号 ≥28px tabular、表行高等一致、chart 高 ≥280、无「扁条」、图例无 pill 堆叠、light/dark 完整、1280-2560 + 移动端抽屉/KPI 2 列/chart 单列各截一图、`pytest tests/ -v` 全绿（应无涉）。

## 4. 验证命令汇总

- 几何断言（每阶段）：browser 8001 + `tab.evaluate`（宽高/对齐/主题/行高断言，脚本按上文）
- 回归：`venv/Scripts/python -m pytest tests/ -v`（预期无 API 契约变化，test_web 仅当 class 断言受影响同步）
- 语法护栏：新增大段内联 JS 改动按 constraint #39 只对新增片段 `node --check`，勿整段提取主脚本
- 渲染验收：1280/1440/1920/2560 + 375 移动端各全页截图，光/暗双主题

## 5. 风险评估

1. **CSS 变量大规模重写**：Chart.js 已实例不随 CSS 变量自动变色 → 主题切换必须走 chart 重渲染路径（P2 验证点），漏则图例/线色与 UI 违和（既有 pitfall #48）。
2. **5 列回归 I.5 决策**：需用户点头（决策 a）——若用户仍想 3 列，表格按 3 列但数字右对齐+行高修，PRD 优先权冲突处标「按用户最新选择」。
3. **移动端抽屉/锚点**：单页 6 菜单部分目标无内容（新闻/宏观/日历/设置）→ disabled 灰态占位，避免假跳转（决策②需确认）。
4. **sparkline 数据 join**：/api/history 只含 10 指数（自选在 /api/watchlist）→ 红利低波 ETF KPI 的 sparkline 需 watchlist trend；两接口异步合并增加时序复杂度 → 默认 P3 先不做 sparkline，仅 KPI 大数字+状态（PRD「可以增加」为可选），确认需要再做。
5. 模板缓存（pitfalls #FastAPI）：验收用 8001 另起端口防 8000 旧模板/静态缓存。

## 6. 回归面

- 业务 JS（fetch/渲染/图表/时间/状态/Dark/Refresh）逻辑保留：改 class/结构不更算法 → 功能回归面≈0（以 pytest + 浏览器功能点击验证兜底：排序、组筛选、range、图例、刷新、主题）。
- 后端/数据层零改动（§十九）；docs 无涉；生成文件无涉。
- 待确认后开工（不确定点见 §1 ① ② 与决策 a）。
---

## 【任务 R：与目标效果图差异对照】(clip_20260905_122955_7.png)

> 注：本环境 vision 模型不可用，未能亲看图；以用户朗读特征为基准 + 8002 新端口 DOM 实测（1440px，dark 默认）逐项对照。PRD 与截图冲突处以**截图为准**（用户纠偏指令），冲突点标注提请定夺。

| # | 项 | 效果图样 | 现状（实测 8002） | 是否改 | 最小改法 |
|---|---|---|---|---|---|
| ① | 默认主题 | 深色主（bg #0f172a 系、卡 #334155 系偏亮） | **dark 默认 ✓**（bodyBg #0B0F14、卡 #111827）——色阶更暗、色相偏蓝灰 | 低 | 两可选：维持现色（接近）或将 dark tokens 调向 #0f172a/#1e293b/#334155 三级（改 style.css:21-30 变量值即可） |
| ② | 表格列数 | **3 列**（指数/收盘价/涨跌幅） | **5 列**（指数/最新价/涨跌/涨跌幅/状态，index.html:58-62）——与 PRD §六(5列)冲突 | **高（需定夺）** | 按截图回 3 列：删「涨跌/状态」th+td（renderOverview 模板串 L248-250 区），「最新价」改名「收盘价」；趋势文本（连跌1日）再入名称列单行小字或省略（I.5/I.6 教训：保持单行，防行高参差）。**若保留 5 列请明示** |
| ③ | KPI sparkline 位置 | **卡右侧**迷你图 | **卡底部**（.lede-cell 高 148，canvas.kpi-spark relTop 93 全宽 241×40，index.html:316 顺序 label/val/sub/canvas） | 高 | lede-cell 改 CSS grid：左列 label+val+sub、右列 canvas 宽 ~90-110px 高 40 居中；canvas 尺寸经 drawSparklines 依容器重设（index.html:318+ 绘图函数取容器宽） |
| ④ | KPI 卡边框/圆角 | 无硬边框、靠色阶区分、圆角 8-12 | border:1px solid + radius 10px + bg 同卡色（style.css:218） | 中 | 去 border（或降 --border 透明度），卡 bg 再提亮一档（#1a2436 系）拉开与 body 色阶；左 2px accent 线保留（有信息量） |
| ⑤ | nav active | 图标+文字蓝青高亮 + 左竖条 | 左竖条 2px ✓ 但 active 文字/图标为浅灰白（.nav-item.active color text-primary，style.css:118-122）；bg 蓝 10% | 中 | `.nav-item.active { color: var(--blue); }` + svg 随 currentColor 变蓝（1 行 CSS） |
| ⑥ | Header/侧栏底部 | Header：M logo+标题、数据截至、**圆形刷新**；侧栏底部：深色切换+最后更新时间 | Header：MARKETPULSE 文本 + ⟳ 字符按钮 + ☀️ emoji 切换（index.html:26-36）；数据截至 ✓；**侧栏底部 597px 空白无切换/时间** | 中 | a) 刷新/主题换 20px 圆形内联 SVG 图标按钮；b) 侧栏底部加「主题切换 + 数据最后更新 HH:MM」小段（复用 overview-date/applyTheme；不引依赖）；M logo 是否图形化 → 效果图有 M logo：可选 24px 方形 accent 底 M 字标（纯 CSS/文本） |
| ⑦ | 趋势区顶部控件 | 7/30/90 + 自定义对比下拉 + 分类筛选(全部/美股/A股/波动率/另类) + 顶部彩色圆点图例 | 7/30/90 ✓ + group-bar(JS 分类按钮) + symbol-filter chips（无自定义对比下拉；图例为 chips 非圆点） | 中 | 「自定义对比」下拉：现 symbol-filter 支持多选 → 加 select 多选 UI 或 dropdown 面板复用它；图例 chips 改圆点+灰标签（P3 图例方案已含） |
| ⑧ | 图表布局 | **左右两个大图**（美股/A股）一屏 | 2×2 四组全显（charts-grid 4 canvas 各 696×340） | **高** | charts-grid 默认只显 美股/A股 两组（分类筛选切换波动率/另类时换出）；或 grid 保持 4 组但收成 2 列×高图、默认高亮前两类——按截图：默认两图 50/50 并排，图高 ≥320 |
| ⑨ | 整体配色 | 深 bg + 偏亮卡 + 蓝青 accent（#3b82f6 系?） | #0B0F14/#111827 + blue accent（图例蓝） | 低 | 与①同批调 token；涨 #16A085/跌 #F05A5A 已用（PRD 值，效果图绿红直觉同族） |

### Top 3 差异（先做）
1. **② 表格 3 vs 5 列**——需用户定夺（PRD 5 列 vs 截图 3 列冲突；本次以截图为准倾向回 3 列）。
2. **③ KPI sparkline 右置** + ④ 卡无边框靠色阶（同一 lede-cell 布局重做）。
3. **⑧ 趋势区两图一屏布局** + ⑦ 自定义对比下拉/圆点图例。

### 是否动后端：**全部不需要**（纯 index.html/style.css；涨跌列若保留由前端算、状态/趋势文本后端已下发；自定义对比下拉复用现有 /api/history?days + 多选过滤，无新接口）。

### 实施顺序建议
R-1（②列数定夺后）：表格列数/名称列单行 → R-2（③④）lede-cell grid 右 spark + 卡色阶 → R-3（⑧）趋势区默认两图+筛选换组 → R-4（⑦⑤⑥）控件/图例/侧栏底部/图标化 → R-5 验收（PRD checklist + 截图逐项过）。均并入现有 P3/P4 阶段产物上改，不返工。
