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

## Sparkline（KPI 卡迷你走势图）
- 数据源：index 卡(GSPC/VIX/SH) 复用 refresh() 已加载的 state.history.series（key=小写 symbol：gspc/vix/sh）；第 4 卡(515300.SS) 走 watch.trend.series（key=515300.ss）。若 state.history 未就绪则降级 fetch /api/history?days=30 一次。
- 渲染：每卡底部加 `<canvas class="kpi-spark" data-sym>`；原生 canvas 画最简折线（1.5px、无轴/网格/标签），高度固定 40px、宽度随卡 100%。颜色取该卡 `.lede-sub` 计算色（pos→绿 / neg→红），无方向用 --muted；主题切换时 `repaintSparklines()` 重读计算色重绘（在 theme-toggle handler 内 renderCharts 之后调用）。
- CSS：`.kpi-spark{width:100%;height:40px;display:block;margin-top:8px}`；卡片总高桌面/移动一致（375 实测 4 卡等高 141px）。
- 缺失兜底：序列全 null/不足 2 点 → clearRect 留空，不崩；单卡缺失不阻断其余（drawOneSpark 顶部守卫）。
验证：
- node --check 整文件 OK。
- 浏览器 8023：1280 下 4 卡各 1 canvas（w=201/h=40，drawn=true）；375 下 4 卡等高 141px、canvas w=113 drawn=true；主题切换后 sparkline 仍绘制（切到 light）。
- 全流程 pytest 449 passed / 0 failed。

## 风险/后续
- 图表图例为 Chart.js 默认（彩色方块+文字），未做"灰标签+彩色点 2px"自定义图例；如需严格贴合 PRD §九可后续加。
- sparkline 已完成（KPI 卡底部迷你折线，数据缺失优雅留空；见上节）。
- 侧栏 disabled 菜单（新闻/宏观/日历/设置）为灰态占位，等对应功能后再接。

## 任务 R 收敛（按效果图差异对照收口；纯前端，不动后端）
目标：把 P1-P4 产物收敛到用户定夺的目标效果图。用户定夺：表格回 3 列（指数/收盘价/涨跌幅）。

### 改动清单（仅 web/templates/index.html + web/static/style.css）
- R-1 表格 3 列：`renderOverview` 删「涨跌/状态」th+td；「最新价」→「收盘价」；趋势文本(连跌N日)经 `st.match(/连[涨跌]\d+日/)` 提取后内联进名称列单行小字（`.data-table td.name` 改 `flex-direction:row; white-space:nowrap` 防行高参差）；td.num/th.num 右对齐保留；3 处 colspan=5→3（加载中/暂无/无选中/失败）。
- R-2 KPI 卡：`renderLede` 输出包 `.lede-info`（label+val+sub）与右侧 `<canvas class="kpi-spark">`；`.lede-cell` 改 `display:grid; grid-template-columns:1fr 96px; align-items:center`；去 `border`（border:none），背景提亮靠色阶——新增 `--bg-kpi` token（Light #FFFFFF / Dark #1A2436）；左 2px accent 线保留。
- R-3 趋势区默认两图：`state.selected` 初值改 `{gspc,ixic,sh,sz,cyb}`（仅两主板）；空组（无选中指标）用 `.chart-box:has(.chart-empty){display:none}` 隐藏整格（不改 renderGroup）；图高 340px 已 ≥320 满足。
- R-4 控件/图标/侧栏底：
  - 图例 chips 已含彩色圆点+灰标签+未选中 opacity .35（P3 既有），无需改。
  - `.nav-item.active{color:var(--blue)}`；SVG `stroke="currentColor"` 随字变蓝。
  - 刷新/主题按钮换 20px 圆形内联 SVG（替换 ⟳/☀️ emoji）；`.icon-btn` 改 20px 圆；`#menu-toggle` 28px 单独保留。
  - 侧栏底部加 `.sidebar-footer`：主题切换按钮（复用 #theme-toggle handler，点它即 `themeBtn.click()`）+ `#sidebar-updated`（refresh 成功后写 HH:MM）；`#sidebar` 加 `display:flex;flex-direction:column` 把 footer 推到底。
  - 顶栏加 24px 方形 accent 「M」字标（`.brand-logo`）。
  - 「自定义对比下拉」：降级保留现有 chips 多选 UI（已满足多选+彩色圆点），未另做 dropdown 面板（按方案逃逸条款标注）。
- 主题微调（①⑨）跳过：现状 dark #0B0F14 系列接受，未改 token 干预 #0f172a。

### 副作用（需告知）
- R-3 共享 `state.selected` 同时驱动表格行：`state.selected` 初值只含两主板 → **表格默认只显 5 行**（标普/纳指/上证/深证/创业板）；点「全选」恢复 10 行。single-source 设计，无法既默认两图又表 10 行而不解耦。

### 验证
- node --check 整文件 OK（rfind 越过 `</script>` 字面量取末段）。
- 浏览器（新端口防缓存 8024/8025/8026，tab.evaluate 主世界断言）：
  - 1280：th=[指数,收盘价,涨跌幅]、rowCount=5、上证/深证/创业板 名称列含「连跌1日」单行；`.lede-cell` display=grid / border 0 / bg #1A2436；sparkline 在 info 右侧且 drawn；trend 图可见 2（美股/A股）+ 自选图常显；nav active 色 rgb(59,130,246)；侧栏底切换+更新时间「更新 HH:MM」；header SVG 图标；brand-logo 存在；侧栏主题按钮点击 dark→light 且 sparkline 重绘。
  - 375：4 卡等高 84px、grid `1fr 40px`、val 16px 不溢出、3 列、trend 图可见 3（2 trend + watchlist）。
  - 2560：shell 铺满（main=viewport−sidebar，无 max-width 上限）；light 主题 body #F7F8FA / KPI #FFF / nav #1677FF / sparkline 重绘。
- 全流程 pytest：449 passed / 0 failed（8 条既有警告，无新增）。

### 新坑（已补 docs/pitfalls.md 模块 web/前端重构 节）
- R-3 两图默认 + `:has(.chart-empty)` 隐空组；R-1 趋势文本单行（td.name flex-row nowrap）；R-2/R-5 移动端卡高一致（480 块 spark 40 + lede-val 16px !important + label/sub nowrap，避 768 块 22px 覆盖）；R-4 nav active var(--blue)+SVG currentColor。

## 用户反馈两改动（纯前端；表默认10行 + 删 header 主题按钮）

### 改动 1：表格默认回 10 行（解耦表/图单源）
- 根因：R-3 把 `state.selected` 收窄成两主板，因它同时驱动「表格行」与「趋势组可见」，表格被牵连只剩 5 行。
- 解耦：新增 `state.visibleGroups`（趋势区分组可见集，默认 `DEFAULT_GROUPS = [chart-gspc-ixic, chart-sh-sz-cyb]`）；`state.selected` 恢复 `new Set(ALL_KEYS)`（表 10 行全显）。
- `renderGroup` / `syncSelection` 组显隐改判 `state.visibleGroups.has(g.id)`（与 `anySelected` 取或，空组仍 `:has(.chart-empty)` 隐整格）。
- `onGroupClick`（类别按钮）：改为切换 `visibleGroups` —— 点单组→仅显该组；再点已独占组→恢复默认两主板（`selSnapshot` 逻辑删除，字段一并移除）。
- `renderFilter` 类别按钮 active 改判 `visibleGroups.has(g.id)`；「全选」同步 `visibleGroups = 全 4 组`。
- 单点 symbol 过滤（chips）、排序、刷新等保留不变。

### 改动 2：删 header 右上主题按钮
- 删去 `<header>` 内 `id="theme-toggle"` 按钮（保留 数据截至 + 刷新）。
- 侧栏 footer 本用独立 `id="sidebar-theme"` 经 JS 委托 `themeBtn.click()`（`themeBtn` 原绑 `#theme-toggle`）。仅删 DOM 会让 `themeBtn` 变 null、侧栏失效 → 把主题 handler 直接改绑 `getElementById('sidebar-theme')`，并删除委托那两行。侧栏 footer 成为唯一主题入口。

### 验证
- node --check 整文件 OK（rfind 越过 `</script>` 字面量）。
- 浏览器（新端口 8031，tab.evaluate 主世界断言）：rowCount=10；headerTheme=false、sidebarTheme=true；默认 visibleGroups=[美股大盘,A股大盘]+自选图常显；点 sidebar-theme dark→light 无报错（sparkline 重绘）；点「波动率」→仅波动率组可见，再点→恢复两主板。
- pytest tests/test_web.py：49 passed（1 条既有 StarletteDeprecationWarning，无关）。

### 新坑（已补 docs/pitfalls.md 模块 web/前端重构 节）
- 表/图单源污染：state.selected 既管表格行又管趋势组可见 → 解耦 visibleGroups。
- 主题按钮委托陷阱：删 header #theme-toggle 须改绑 handler，否则侧栏失效。
- R-3 副作用说明更新：原「表格默认 5 行」已由 visibleGroups 解耦修正（保留原 R-3 行 + 新解耦说明，删重复旧行）。

## 任务 S P1（A股三行红底 bug 修复；纯前端，不动后端）

### 根因（renderOverview, index.html）
- L262 行级红底 `row-flash` 误配「连跌」：`/连[涨跌]\d+日/.test(st)` 命中趋势文本 → A股「连跌1日」整行染红。
- L257 `cls` 独立按 chg 算涨跌色、L268 `chgCell` 只换文案不换 cls → 周末/回填行（A股 chg≥0）显示 pos 绿字「休市」，与红底矛盾。

### 改法
- `row-flash` 仅保留 `st.indexOf("异动")>=0`，去掉 `/连[涨跌]\d+日/`；连跌趋势已由名称列 `trend-sub` 小字表达，不再行级红。
- `cls` 与 `chgCell` 同条件：`const cls = (isWeekend || srcDate) ? "" : (chg==null?"":(chg>=0?"pos":"neg"));` —— 周末休市 / 回填(未收盘) 用中性色，真实行情照常 pos/neg；`isWeekend` 上提到 cls 之前声明。

### 验证
- node --check 整文件 OK（rfind 越过 `</script>` 字面量）。
- 浏览器（新端口 8041；机器即周六 → 休市为真实渲染，tab.evaluate 主世界断言）：A股三行 chgCell="休市"、chgCls="num chg "（中性无 pos/neg）、row-flash=false、名称列仍含「连跌1日」小字。
- 强制 getDay=1(周一) 合成数据回归：SH +1.25%→pos、SZ -0.50%→neg、CYB 回填→"未收盘"中性且 flash=false、trend 仍显 → pos/neg 颜色无回归。
- pytest tests/test_web.py：49 passed（1 条既有 StarletteDeprecationWarning，无关）。

### 新坑（已补 docs/pitfalls.md 模块 web/前端重构 节）
- 趋势文本误染红底（row-flash 误配连跌）+ 休市绿字：row-flash 条件含 `/连[涨跌]\d+日/` 把连跌当异动整行染红；cls 涨跌色独立于 chgCell 文案 → 休市绿字。修法：row-flash 仅留「异动」；cls 与 chgCell 同条件（休市/未收盘中性色）。

## 任务 T（收盘价列不整齐修复；纯 CSS）

### 根因
- 带回填标注的 7 行（标普/纳指/VIX/VXN/MOVE/GLD/BTC）`td.val` 内联 `<span class="src-sub">（09-04收盘）</span>` 尾随数字，右对齐时把数字推离右缘 ~65px；A股 3 行纯数字贴右缘 → 两簇右缘参差。

### 改法（web/static/style.css）
- `.data-table td.num.val { position: relative; }`（合并进原 `td.val` 规则）。
- `.src-sub` 改绝对定位脱离数字流：`position:absolute; left:12px; top:50%; transform:translateY(-50%); white-space:nowrap; color:var(--text-muted); font-size:11px;`。数字成为唯一流内容 → 10 行右缘统一贴列右缘；标注左置格内垂直居中。

### 验证
- 浏览器（新端口 8051，tab.evaluate 主世界）：1280 下 10 行 td.val 数字文本右缘差 = 0（完全对齐）；7 个 src-sub 均在 td 左半区（subLeft=743 < 中点）且垂直居中（subCenteredY=true）；A股 3 行无标注、numRight 同样 1045。
- 375 窄屏：bodyOverflow=0（无横向溢出、布局不破坏）；10 行数字右缘差仍 =0；7 标注均在表左边界内（allSubWithinTable=true），无溢出到名称列。
- pytest tests/test_web.py：49 passed（1 条既有弃用告警，无关）。
- git status：仅 `web/static/style.css` 改动（代码范围正确）。

### 收尾
- 按指示跳过 pitfalls（纯 CSS 2 条、无新坑）。

## 任务 T2（去行内标注，纠正 T 方案；纯前端）

### 根因
- T 方案用 `.src-sub` 绝对定位把「（09-04收盘）」左置格内，虽对齐但仍属行内标注、语义冗余；用户纠正：收盘价列应恢复纯数字右对齐、零标注，来源语义上移标题 + title 提示。

### 改法（web/templates/index.html + web/static/style.css）
- renderOverview：删除 valCell 内 `src-sub` span；td.val 改为带 `title="数据回填自 {srcDate}"`（有回填时）。
- 收集本批 `srcDates` 集合；渲染后若非空，把 `#overview-sub` 文案更新为 `· 最新交易日（部分标的回填至 {join}）`；全当日数据保持 `· 最新交易日`。h2-sub 加 `id="overview-sub"`。
- style.css：删 `.src-sub` 规则（td.num.val 的 position:relative 保留，无副作用）。

### 验证
- grep：全仓无 `src-sub` 残留。node --check（rfind 越 `</script>` 字面量）：OK。
- 浏览器（新端口 8061，tab.evaluate 主世界）：10 行 td.val 内无 span；数字右缘差 = 0（完全对齐）；`#overview-sub` 文本 = `· 最新交易日（部分标的回填至 2026-09-04）`；7 行（标普/纳指/VIX/VXN/MOVE/GLD/BTC）td 带 `title="数据回填自 2026-09-04"`，A股 3 行无 title。
- pytest tests/test_web.py：49 passed（1 条既有弃用告警，无关）。
- git status：代码改动仅 `web/templates/index.html` + `web/static/style.css`（`plan.md` M 为既有、非本次）。

### 收尾
- 按指示删规则无坑、跳过 pitfalls。

## 任务 U（自选股加载慢优化：后端 TTL 缓存 + 前端渲染解耦）

### 改动
1. web/app.py `/api/watchlist` 加模块级 TTL 缓存（_WATCH_TTL=90s + _watch_cache + _watch_lock 防并发击穿）：命中且未过期直返；未命中取数。取数失败（_watch_failed：hidden=False 但 stocks 空）→ 有旧缓存回退旧缓存 + `stale:true`，无旧缓存回退降级空结构（与原端点一致，HTTP 200）。缓存仅存成功结果。
2. web/templates/index.html renderLede：watch 未到达 / 取数失败 → 第 4 格（自选）占位「—」/「加载中…」；watchlist 到达后由 success 分支 `renderLede(state.latest, data)` 补画真实值。概览/趋势仍由 /api/latest 先渲染、不被自选拖慢（watchlist 并行 fetch）。
3. tests/test_web.py 加 autouse fixture `_reset_watch_cache`：TTL 缓存是模块级状态，跨测试泄漏会污染端点断言（L714/L733），每个测试前清空。

### 验证
- 后端实测（8071）：cold 取数 4.50s → 缓存命中 0.008s → 62s 后 0.006s（TTL=90s 内仍命中）。body `hidden=False stocks=1 stale=None`。
- 受控 Python 证明：过期缓存 + 取数失败 → `stale=True` 且回退旧数据；无缓存失败 → 降级空结构（hidden=False, stocks=[], 无 stale）。命中路径不触发取数。
- 前端：`renderLede(latest,null)` 第 4 格 = `{自选, —, 加载中…}`；`renderLede(latest,state.watch)` → `{红利低波ETF, 1.33, +0.08%}`。运行时真实取数后自动补值。
- `node --check` 内联脚本 OK；`pytest tests/test_web.py` 49 passed（新增 reset fixture 后端点断言仍绿）。
- 范围：仅 web/app.py + web/templates/index.html + tests/test_web.py。

### 新坑（已补 docs/pitfalls.md 模块 web/前端重构 节）
- 模块级 TTL 缓存跨测试泄漏：缓存是模块级状态，pytest 单进程共享 → 污染端点断言。修法：autouse fixture 每测试前清空 `_watch_cache`。
- 前端解耦骨架：自选格首屏占位「—」避免布局跳动；watchlist 并行取数不阻塞概览/趋势，到达后单独补画第 4 格。
