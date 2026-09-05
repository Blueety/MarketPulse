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
---

## 【任务 S：A股红显 + 周六 cron】（只读实测，未改代码）

### P1 A 股三行红色 —— 根因与位置
**实测（8002，dark）**：上证/深证/创业板三行**整行红底** `rgb(255,110,94)/7%`（= var(--red) 7% = row-flash 样式）；涨跌幅列文案「休市」却带 `pos` 绿类（rgb(47,214,168)）；名称列「上证指数连跌1日」（trendSub 拼入）。

**根因（index.html renderOverview）**：
1. **整行红 = row-flash 误配「连跌」**：L262 `else if (st.indexOf("异动") >= 0 || /连[涨跌]\d+日/.test(st)) rowCls = "row-flash"` —— row-flash（语义=异动红、CSS red 7% 背景）把 A 股三行「连跌1日」趋势当异动整行染红。周六休市日趋势并非当日异动 → 误导。
2. **「休市」绿字 = chg cls 未随文案分支**：L257 `cls = chg==null?"":(chg>=0?"pos":"neg")` 独立计算，而 L268 `chgCell = isWeekend ? "休市" : …` 只换文本不换 cls → A股 chg 原始值 ≥0 → td 得 `pos` 绿，「休市」二字绿显示，红底+绿字自相矛盾。

**是否需改**：需。改法（renderOverview L257-270 区域）：
- L262 row-flash 匹配去掉 `连[涨跌]`（只留「异动」）；连跌趋势已由 trendSub（L269-270）在名称列表达，无需行级红。
- 休市/回填分支将 cls 置空：`cls` 与 chgCell 同条件计算（isWeekend||srcDate → ""），避免「休市/未收盘」继承涨跌色。
- （可选）周六回填行如需弱化用 muted 文本，不用红绿。

### P2 周六 cron —— 脚本 gate 已上线，Hermes 层仍需处理
**Gate 现状（已实施）**：`analyzer.py:84-90` `is_market_holiday`（周末退化）+ `snapshot_report.py:38-50` `_is_market_closed` → main 入口 `return 0` + log「休市…跳过（不取数/不渲染/不合并/不提交）」。A股 open/midday/close 与美股 open/noon 周六被拦；us close/daily 不拦（ET 周五收盘后数据有效，正确）。

**今日（09-05 周六）实况**：`2026-09-05-a-share-open.md`（09:45）与 `midday.md + midday-analysis.md`（11:45/11:46）均生成了——git log 证明 gate 代码提交于今日 15:20-16:21 批次，**晚于 09:45/11:45 cron** → 产物是 gate 上线前遗留；15:00 A股收盘无 `a-share-close.md` → gate 已拦截（首个 gate 保护时段）。当前 16:29，今日再无 A 股盘中 cron。

**判断**：脚本级 gate **已足够挡住脚本产物**（周六触发 → return 0、无 .md、无 commit）；**残余风险在 Hermes prompt 层**：6 个 Hermes cron 仍是每日 schedule，周六触发后脚本无当日新 .md → Hermes 若照旧生成 analysis/推送会读不到当日文件（可能误读旧文件或空报推送；今日 11:45 analysis 即 gate 前产物 + 已推送）。

**建议**：
- **Hermes 侧（推荐，需用户操作）**：a) 5 个盘中档（A股午盘/收盘/开盘、美股开盘/午盘）周六/周日 pause 或改工作日 schedule；b) 或 prompt 加休市判定：先检查「当日对应快照 .md 是否存在」，不存在则跳过生成/推送。日报 8:00 档保留周末（美股周五收盘有效，正文注明 A股为最近交易日）。
- **仓库侧（可选加固）**：gate 已是 return 0 不产文件——倾向保持「不产垃圾文件」，让 Hermes prompt 判文件缺失来跳过（在 Hermes prompt 修，二选一）。
- 验证：今晚 21:30 美股开盘 cron（北京周六 = ET 周六 09:30 不开盘）→ 脚本 log「休市…跳过」；Hermes 侧确认无多余推送后闭环。
---

## 【任务 T：收盘价列不整齐】（只读实测 8003，未改代码）

### 实测现象与量化
10 行收盘价 td：右缘一致（1220px）、`text-align:right` ✓、mono+tabular ✓（style.css:212-216 无误）。但 **7 行（标普/纳指/VIX/VXN/MOVE/GLD/BTC）带内联 `<span class="src-sub">（09-04收盘）</span>`（index.html:268），3 行（A股上证/深证/创业板——09-05 行直接有值无回填）纯数字**。

### 根因一句话
回填日期标注 `src-sub` **内联尾随数字文本**（td 同一 inline 流），td 右对齐时标注把数字整体推离右缘 ≈标注宽（~65px）——带标注 7 行数字右缘聚在「列右缘−65px」，纯数字 3 行贴列右缘 → **两簇右缘参差**，视觉锯齿。非 tabular/对齐规则问题（均已正确）。

### 最小修复（2 条 CSS，零 JS 结构改动，标注信息保留）
`web/static/style.css`：
1. `.data-table td.num.val { position: relative; }`（+现 L220 规则合并）
2. `.src-sub`（现 L219）改**绝对定位脱离数字流**：
```css
.src-sub { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); white-space: nowrap; color: var(--text-muted); font-size: 11px; }
```
效果：数字文本仍是 td 右对齐唯一流内容 → 10 行数字右缘统一贴列右缘；标注左置格内垂直居中（「数据截至 09-04」语义仍在格内左侧，不与数字争行、不占宽）。A股无标注行不受影响。

改动前后对比：
| | 前 | 后 |
|---|---|---|
| 收盘价数字右缘 | 带标注行退 ~65px、A股贴边 → 两簇锯齿 | 10 行统一贴列右缘 |
| 标注（09-04收盘） | 数字尾随（占流推挤） | 格左绝对定位小字，语义保留 |

备选（不取）：标注移入名称列——重蹈行高双行/拥挤；标注删除——丢来源语义（任务要求保留）。

### 验证
1. 8004 新端口 + `tab.evaluate`：10 行 `td.val` 数字文本右缘一致（Range 量各数字文本节点右边界差 ≤1px）；标注 span 位于 td 左半区且垂直居中。
2. 375px 窄屏：标注不溢出（absolute+nowrap，列宽不足时以 `right:12px; left:auto` 兜底或允许被后列遮盖——实测后定）；行高不变。
3. 截图对比改前后；排序/涨跌幅列不受影响（仅 val 列定位）。

### 风险
- absolute 标注可能与左侧「指数」列文字重叠（td.padding 12px 内靠左、指数列右缘在 12px 边界）→ left:12px 位于本列 padding 起点，与指数列尾字间距 ≥8px，实测确认；若重叠改 `left: auto; right: 8px`（标注置于格右、数字左让? 数字右对齐仍在右缘——标注与数字同行右端冲突）→ 先按 left 方案实测。
- td.val 16px 600 数字与 11px 标注同格垂直居中：top:50% translate 对单行 td 生效；行高由 padding 定，无 overflow 风险。
### T2 修正：去行内标注（用户纠正——绝对定位左置标注制造列左缘阶梯，否决）

**最终方案（A）一句话**：收盘价列恢复**纯数字右对齐、零行内标注**；回填来源语义上移到表格标题一次性说明 + 行 `title` 工具提示兜底（不占视觉流）。B 方案（全行第二行统一小字）否决：10 行全部变双行/占位空行，破坏单行紧凑，行高参差回潮。

改动点：
1. `web/templates/index.html` renderOverview：
   - L268：`valCell = fmtNum(it.value, 2)` —— 删除 `src-sub` span 拼接；保留来源语义于行级：`'<td class="num val"' + (srcDate ? ' title="数据回填自 ' + srcDate + '"' : "") + '>' + valCell + '</td>'`（原生 hover 提示，零视觉）。
   - L59 标题一次性说明：renderOverview 收集本次 `srcDate` 去重集合 `srcDates`；渲染后若非空，将 h2-sub 更新为 `· 最新交易日（部分标的回填至 {集合 join}）`（11px muted，仅一行字）；全部当日数据时保持现文本「· 最新交易日」。
2. `web/static/style.css`：`.src-sub` 规则删除或留空（不再使用）；无需新规则（h2-sub 已有 11px muted 样式）。可选加 `.h2-sub { font-size: 12px; color: var(--text-muted); }` 微调。

效果对比：
| | 改动前（T 版 absolute） | 改动后 |
|---|---|---|
| 收盘价列 | 数字右缘齐，但左缘 7 行灰标注 / 3 行空 → 阶梯 | **纯数字 10 行右对齐，两缘皆齐** |
| 回填语义（09-04） | 每行灰字（视觉噪声） | 标题「…（部分标的回填至 09-04）」一次 + 行 title hover |
| 行高/参差 | 不变（单行） | 单行不变 |

验证：
1. 8004 新端口 + `tab.evaluate`：`#overview-body tr td.val` 内无 span 子元素、10 行文本右缘一致（Range 量化差 ≤1px）；`#overview h2-sub` 含「回填至 09-04」；`td.val[title]` 存在且值=09-04。
2. 全当日数据场景（周一开盘后无回填）：h2-sub 回落「· 最新交易日」、无 title——验证时以单测/临时数据或代码审查覆盖分支。
3. 截图对比；排序/涨跌幅列无涉。
---

## 【任务 U：自选股加载慢】（只读分析，未改代码）

### 现象与时序定位
- 前端：主数据（/api/history L997、/api/latest L1004、/api/alerts L1089）各自独立 fetch 不互阻 → 概览/趋势/告警秒出；/api/watchlist（L1105）独立 fetch + 12s 前端超时（L1106-1108），**自选股区渲染与 lede 自选格须等该响应 resolve** → 其它模块先出、自选股「过一会」。
- 后端：`/api/watchlist` → `fetch_watchlist`（fetcher.py:609-645）**无缓存/TTL，每次请求实时取数**；A股 515300.SS 走 `_fetch_a_share_watch`（L582-606）：新浪（akshare 内部 requests **无 timeout**，同 L435 板块注释）→ 外层 daemon 线程 `join(SECTOR_TIMEOUT=10s)`（L89/643）截断；新浪失败 pass 后**回退 Yahoo 双主机轮换**（L605-606，主机级 403/429 重试 + sleep(1)）→ 单标的整链最坏吃满 10s。

### 根因一句话
`/api/watchlist` 每次页面加载实时打新浪/Yahoo 且无缓存；A 股路径新浪阻塞（无 timeout）至外层 10s 截断、失败再叠加 Yahoo 回退轮换 → 慢请求；前端虽已并发，但自选股 UI（含 KPI 自选格）仍须等该响应后才挂载。

### 最小优化（推荐 ①+③ 组合）
**① 后端短 TTL 内存缓存（首选）**：`web/app.py` `/api/watchlist` 加 60-120s TTL 模块级缓存（`_cache = {"ts": 0, "payload": None}`；命中且 <TTL 直返；未命中取数成功后写缓存；取数失败且有旧缓存 → 回退旧缓存 + payload 标 stale）。页面刷新/重复打开不再实时打新浪；首次访问仍有真实耗时（可接受）。并发共享加 `threading.Lock` 防击穿。改动约 10 行、只动 app.py、不动 fetcher。注意：uvicorn 默认单 worker（本项目部署单进程）缓存一致；若日后多 worker 各持一份，语义仍正确仅各自首访慢。

**③ 前端渲染解耦**：`renderLede`/lede 自选格不等 watch——/api/latest 到即先画 3 格（自选格占位「—」），watchlist 响应到达后单独补画 lede 第 4 格 + watchlist 区（现状 state.watch 复用已具备，改渲染触发顺序）。自选股卡本身渲染前显示「加载中…」骨架（现状占位若为空则补）。改动 index.html renderLede/watchlist 挂载处。

**②（可选，不推荐先做）**：`_fetch_a_share_watch` 新浪失败不叠加回退 Yahoo（或 A股 watchlist 直切 Yahoo 源），可减半最坏耗时——但牺牲新浪代理兼容与数据（H 任务已证新浪沪 ETF 日线停更、Yahoo 同停）→ 收益有限，暂缓。

### 改动前后对比
| | 前 | 后 |
|---|---|---|
| 重复打开/刷新页面 | 每次实时打新浪（1-10s），自选股区晚出 | 60-120s 内缓存直返（<50ms），自选股与主模块几乎同时出 |
| 首次访问 | 同左 | 同左（不可免，受新浪 10s 上限约束） |
| lede KPI | 若等 watch 才画自选格 | latest 到先画 3 格、自选格异步补画 |

### 验证
1. 连续 `curl -w %{time_total} /api/watchlist` ×2：首次（取数耗时）、二次 <50ms（缓存命中）；60s 后第三次回到取数耗时。
2. 页面加载（8004 新端口 + Network 面板/performance API）：概览/趋势渲染时间 ≈ 旧基线（不被 watchlist 拖慢）；自选股区在 watchlist resolve 后补挂。
3. 取数失败场景（断网模拟或新浪超时）：接口返回旧缓存 payload + `stale` 标记、前端不报「数据暂缺」崩溃；无缓存时回退「数据暂缺」（现状语义）。
4. `pytest tests/ -v` 回归（test_web 若断言 api_watchlist 调用次数/新参数需同步——预计新增 TTL 参数默认兼容）。

### 风险
- 缓存使数据最长旧 60-120s：盘中用户强刷想要最新价 → 命中缓存旧值；可接受（看板用途分钟级）或提供 `?fresh=1` 绕过（可选）。
- 前端补画 lede 自选格：需处理 watch 到达前格子的占位与到达后的重绘不闪烁（transition 200ms 内完成）。
- 12s 前端超时 > 后端 10s 限时 → 前端超时分支实际几乎不触发（后端先返），保留作兜底。
---

## 【任务 V：表格横线连续 + 收盘价居中】（只读方案，未改代码）

### V1 行分隔线断开成三段
**根因**：`.data-table td.name { display:flex; … }`（style.css:210，缩进显示原属 768px media 内但 CSS 无缩进语义 → **全局生效**）把「指数」列 td 从标准 table-cell 改成 flex 容器——`border-collapse:collapse`（L187）的单元格共享 border 机制对非 cell 的 flex 盒失效：该 td 的 `border-bottom`（L203）画在独立 flex 盒底，与相邻 `td.num`/`td.chg` 的 collapse 共享线无法合并 → 「指数|收盘价」「收盘价|涨跌幅」交界处断点，横线呈三段。
**改法（主案 + 兜底）**：
1. `web/static/style.css:210`：移除 `td.name` 的 `display:flex/flex-direction/align-items/gap`，恢复默认 table-cell（行线即连续）；内部间距改由子元素承担：`.trend-sub { margin-left: 8px; }`（名称文本与 trend-sub 保持 inline 邻接）。index.html 渲染结构不变。
2. 兜底（若仍有 1px 断点）：行线从 td 底部上移到相邻行交界——`.data-table td { border-bottom: none; } .data-table tr + tr td { border-top: 1px solid var(--border); }`（同样依赖 collapse 共享，与 1 同机制；1 已修复则不必启用）。
验证：8004 截图/`tab.evaluate` 量每行 bottom border 各 td 段 y 坐标一致连续；无竖线引入。

### V2 收盘价列居中（用户定夺：右对齐→居中）
**现状**：收盘价 td 为 `td.num.val`（style.css:215 `td.num{text-align:right}` + L219 `td.num.val`），表头 `th.num`（L217 right）。
**改法**：
1. `web/static/style.css:219` `.data-table td.num.val { … }` 追加 `text-align: center;`（特异性 0,2,2 > `td.num` 0,1,1 → 仅收盘价列居中；涨跌幅列 `td.num.chg`（无 val）保持右对齐）。
2. 表头同步居中：`web/templates/index.html:62` 收盘价 `<th class="th-sort num" data-sort="value">` 追加 `val` class → `class="th-sort num val"`；style.css 加 `.data-table th.num.val { text-align: center; }`（或并入 L217 后）。
3. 「休市/—」文本在涨跌幅列（chg）→ 右对齐不变；指数列左对齐不变（用户要求保持现状）；居中后小数点不再对齐——用户明确接受。
验证：`tab.evaluate` 断言 `td.val`/`th.val` computed text-align=center、`td.chg`/名称列未变；截图确认无竖线、横线连续。

### 风险
- V1 移除 flex 后若名称文本与 trend-sub 无间距观感挤 → 用 `.trend-sub{margin-left:8px}`（已含）；行高不受影响（单行 inline）。
- V2 `td.num.val` 亦用于其它含 val 的表格？仅 overview 收盘价列使用 val class（watchlist 表独立类）→ 影响面单列。低。
---

## 【任务 W：sparkline 数据点少/像假】（只读实测 8003，未改代码）

### 各卡实际点数（实测 /api/history?days=30 + /api/watchlist）
标普 29/30、纳指 29、VIX 29、上证 **30/30**、深证/创业 30、ETF 515300.ss **30/30**（trend.dates 30）——**点数全部充足，无截断 bug**。drawOneSpark（index.html:349-374）全量非 null 点折线绘制，无抽稀/无平滑——渲染也没丢点。

### 根因（观感，非数量）
1. **停更断尾**（主因，任务 H 传播）：ETF/美股系列（watchlist 3mo 窗口补齐到 30 点）尾端仍缺 09-03/09-04 → 折线截至 09-02 戛然而止，KPI 卡无「数据截至」标注 → 残缺、像假的。
2. **40px 高 × 窄幅标的本就近平**：VIX 近 30 日窄幅 → 曲线近乎平线；无端点/无网格参考 → 「假图」观感。
3. 无最小点数门控/空态提示：断尾标的与正常标的混排无区别表达。

### 是否需修：数据层面不需要（点数正常）；渲染级建议轻改 + 等任务 H 自愈复查
**最小改进（2 条，成本低，可等周一复查后一并定）**：
1. KPI sparkline canvas（index.html:335 或 drawOneSpark L349）`title`/卡右上 9px 角注「至 MM-DD」（=series 末非 null 日期）——断尾（09-02）与完整（09-04+）一眼区分，消除「假/残缺」误解；数据补齐后标注自然更新。
2. drawOneSpark（L349-374）可选：起点/终点加 2px 圆点端点 + `min===max`（平线）时画 1px 中线而非空白——提升窄幅标的真实感（低优先）。

**与任务 H 关联**：ETF 停更自愈观察点=周一 09-07 复查新浪 bar 是否含 09-03/09-04；若自愈 → 本问题大半消失（仅剩窄幅平线观感）；若仍停 → 数据层走 H 方案 2（东财源替换/并源）前置验证，渲染层只做上述标注兜底。

### 验证
1. `curl /api/history?days=30` 与 `/api/watchlist`（已验，29-30 点）。
2. 标注落地后：`tab.evaluate` 断言 ETF sparkline title=「至 2026-09-02」、标普=「至 2026-09-04」（断尾可见）。
3. 周一复查：新浪 515300 bar 尾日期 + watchlist trend 尾值 → 自愈与否决定是否启用 H 方案 2。

### 风险
- 纯标注/端点渲染改动，零数据与布局风险；若等自愈则本项暂不动手（零成本观望）。低。
