# 前端 UI/UX 重构实施记录（2026-09-05）

## 目标
按 tasks/2026-09-05-frontend-redesign/plan.md 四阶段，将看板重构为 Professional Financial Dashboard × 现代 FinTech × Apple 克制：
- P1 布局骨架：body→flex shell，侧栏 220-240px + 主区 flex:1，Header 细栏，section 锚点，内联 SVG 图标。
- P2 颜色/双主题：Light(#F7F8FA) 优先完整 + Dark(#0B0F14) 分层；图表色随主题取数组，切主题重渲染。
- P3 组件：KPI→4 卡；概览表回 5 列（指数/最新价/涨跌/涨跌幅/状态），涨跌前端逆算，状态列承载趋势文本。
- P4 响应式+验收：抽屉导航、KPI 2 列、表格横滚、图表防扁条、微交互/focus/reduced-motion，过 PRD §二十。
约束：不改 web/app.py / src/* / data/*；不引新依赖；自动推送 cron 提交。

## 改动文件
- web/templates/index.html（结构/JS）
- web/static/style.css（token/布局/组件/响应式）

## P1 布局骨架
- body 内：<header class="topbar"> + <div class="shell">（<aside id="sidebar"> + <main class="main" id="main">）。
- 侧栏 6 菜单（概览/自选列表 可用，新闻/宏观/日历/设置 disabled 灰态占位），内联 SVG 6 图标零依赖。
- Header 左品牌(MARKETPULSE/市场看板) 右 数据截至/刷新/主题 按钮。
- 各 section 加 id（overview/watchlist-section/trend-section/sector-section/alerts-section）供锚点。
- JS：nav 锚点平滑滚动 + active 态；menu-toggle 抽屉开关占位（P4 接）。
验证：node --check 通过；浏览器 1280 几何断言（sidebar 232 sticky / shell flex / main flex:1 maxW none / 6 菜单含 1 active + 4 disabled / 5 section id）。

## P2 颜色/双主题
- token 反转：:root = Light（#F7F8FA/#FFFFFF/#111827/#6B7280/#9CA3AF/#1677FF/#16A085/#F05A5A + 极浅 border）；[data-theme=dark] 覆盖（#0B0F14 分层）。
- 图表色 COLORS→COLORS_LIGHT/COLORS_DARK + colors() 按 theme 取；柱状 up/down 随主题（#16A085/#F05A5A vs #3fb950/#f85149）。
- 切主题：theme-toggle 改 dataset.theme + localStorage + applyTheme，并 if(state.history) renderCharts 重渲染（否则图例/线色违和）。
验证：light 默认 bodyBg #F7F8FA / text #111827；切 dark bodyBg #0B0F14；colors() 调色板随主题切换；5 canvas 正常重渲染。

## P3 组件
- KPI（renderLede）：.lede-cell 改为卡片（border 1px / radius 10 / 无阴影 / 状态色左边线），label 小字 + 28px tabular 数字 + 状态+涨跌幅语义色。
- 概览表回 5 列 thead：指数/最新价/涨跌/涨跌幅/状态；渲染 5 单元格。
- 涨跌绝对额前端逆算：prev=value/(1+chg/100)，diff=value-prev。
- 状态列：状态文本 + 状态点（失败橙/异动红/休市未开盘灰/其它绿）；趋势文本（连涨连跌）随 it.status 入状态列。
- row-dim 收窄：仅失败→row-warn、异动/连涨跌→row-flash，休市/回填不再淡化。
- 表格 .num 右对齐、状态列左对齐、.src-sub 小字；价格列 16px 600。
- 图例：symbol-filter chip 未选中 opacity .35。
验证：5 列表头（指数/最新价/涨跌/涨跌幅/状态）；10 行；上证行 涨跌 +0.00 / 状态"连跌1日"；价格右对齐；状态点存在；KPI 卡片 border 1px radius 10px。

## P4 响应式 + 验收
- 移动端抽屉：≤768 .sidebar→fixed 离屏 translateX(-100%)；#menu-toggle 显示；点击切换 body.nav-open→滑入；背景遮罩点击关闭。
- KPI ≤768 两列（flex 1 1 45%）；charts-grid 单列；表格 .table-scroll 横滚。
- 微交互：button/chip/nav/icon-btn transition；行 hover 浅背景；:focus-visible 蓝描边；prefers-reduced-motion 关动画。
- 主图 canvas 高度：base 340 / 768→300 / 480→280（≥280 无扁条）；自选股图保持 220（任务 E 内联 !important）。
验证：
- 1280：sidebar sticky、menu-toggle none、KPI 28px、chartBox 363px≥280、grid 双列、main 1048 铺满。
- 375：sidebar fixed translateX(-240) 隐藏→点击 translateX(0) 滑入；menu-toggle flex；KPI 148px×2 两列；grid 单列；bodyScroll=375 无溢出；表格在 311 容器内横滚（table 448 内部滚）。
- 全流程 pytest 449 passed / 0 failed（无 API 契约变化）。

## 踩坑（已修）
1. 图表色 COLORS 块无分号、6 空格缩进，字符串替换需精确字节（先 repr 校验）。
2. renderOverview 误用 esc()，实际函数名 escapeHtml → 运行时报错表格卡加载态；改 escapeHtml。
3. 跨端口 CSS 缓存：headless 对 /static/style.css 跨端口命中 304/陈旧，验证须用全新端口（8014→8015→8016 递进）。
4. 侧栏基础规则是 #sidebar(id) 而 768 媒体用 .sidebar(class) → id 特异性压过 class，移动端不 fixed；统一改 #sidebar。
5. .shell 基础 align-items:flex-start，移动端变 column 后 main 不横向拉伸→按表格 nowrap 撑到 512 溢出；768 加 align-items:stretch 修复。

## 风险/后续
- 图表图例为 Chart.js 默认（彩色方块+文字），未做"灰标签+彩色点 2px"自定义图例；如需严格贴合 PRD §九可后续加。
- sparkline 按默认处理未做（PRD 标可选）。
- 侧栏 disabled 菜单（新闻/宏观/日历/设置）为灰态占位，等对应功能后再接。
