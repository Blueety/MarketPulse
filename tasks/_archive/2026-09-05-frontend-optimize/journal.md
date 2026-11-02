# 任务日志：前端优化（清理 + 去重 + JS 抽离），2026-09-05

## 追加：概览表收盘价列居中（同日晚间用户反馈）
- 用户反馈「收盘价列不够居中」。**实测排查**：文字在单元格内已精确居中（偏差 ≤1px），真因是**列在表格中偏右 114px**——auto 表格布局把富余宽度大半分给指数列（内容 ~150px 却占 402px/近半表宽）。
- 修复：`#overview .data-table` 宽屏（≥769px）改 `table-layout: fixed` + 三列 33/34/33；移动端不受影响（media 外无全局改动）。
- 验证（8023 本地 + 用户同视口 1158px）：三列 285/293/285，收盘价列中心 = 表格中心（偏差 **-0.2px**），截图目视对称。
- 教训：用户说「不居中」未必是 text-align 问题；先量列几何（th/td Range rect vs 列 rect vs 表 rect），再定性。
- IAB 截图 surface 卡死一次：同标签反复超时提示"previous screenshot still completing"，关标签重开解决。
- 未手动 push；cron 自动机制扫入推送后线上生效。

## 追加：默认四图全显（同日晚间用户需求）
- `app.js` `DEFAULT_GROUPS` 从 `["chart-gspc-ixic","chart-sh-sz-cyb"]` 改为 `GROUPS.map(g=>g.id)`（推翻此前 R-3「默认两图」决策，用户定夺）。
- 顺手修：`.chart-box h3` 加 `white-space:nowrap + flex-shrink:0`——四图全显后波动率组 meta 最长，把「波动率」标题挤成竖排；修复后单行。
- 验证：`node --check` 过、`pytest tests/test_web.py` 49 passed、新端口 8022 浏览器断言（4 Chart 实例 + 4 组按钮 active + 概览表仍 10 行未被牵连）+ 截图目视。
- **重踩坑**：同端口 reload 后 CSS 304 假阴性（computed style 仍是旧值），换 `?v=timestamp` 破缓存后确认生效——pitfalls 已有此条，验证 CSS 改动必须破缓存或换端口。
- 未手动 push（用户未要求）；cron 自动机制会扫入推送。

## 目标
不改变任何视觉与交互行为的前提下：修 3 个真 bug、清 ~100 行死代码、去重、图表颜色统一 CSS 变量单一来源、约 1000 行内联 JS 抽成 `web/static/app.js`、railpack.json 启动命令对齐。范围 C（用户经 AskUserQuestion 选定）。

## 改动文件清单
| 文件 | 改动 |
|---|---|
| `web/static/app.js` | **新建**（1005 行）：承接 index.html 全部内联 JS；随后 A 级修复 + B 级去重 |
| `web/templates/index.html` | 1153 → 148 行：内联脚本移出、`</div>` 归位、2 处内联样式转 class |
| `web/static/style.css` | 删死规则（.theme-toggle/.status-dot 系/td.st/.row-dim/.col-status/.container×2/--fs-num/--purple）、去重（.topbar-right/.icon-btn:hover/.lede-* border 重复段/旧 :focus-visible）、删无效 `.lede-val{22px}`、新增 `.hidden` 类 + 17 个 `--c-*` 图表 token（Light/Dark 两套） |
| `railpack.json` | startCommand `uvicorn app:app` → `uvicorn web.app:app`（对齐 Procfile/railway.toml） |
| `tasks/2026-09-05-frontend-optimize/plan.md` | 本任务计划 |

## A 级修复明细
1. `sparkColor` 读不存在的 `--muted` → `--text-muted`（KPI sparkline 中性色此前恒走 fallback 硬编码）。
2. `renderSector` / `renderAlerts` 全字段补 `escapeHtml`（板块名/领涨股来自 AkShare 外部源）。
3. 删从未被调用的 `renderBarChart`（56 行，GROUPS 全为 line）。
4. `#watchlist-section` 显隐 `style.display` → `.hidden` 类（JS 3 处）；`#chart-watchlist` 行内 height 移入 CSS（`maintainAspectRatio:false` 语义随 `buildLineOptions` 的 extra 参数保留）。

## B 级去重明细
- 公共构建器：`buildTradingAxis` / `buildLinePts` / `buildLineDataset` / `buildLineOptions(extra)`；`renderLineChart` 与 `renderWatchChart` 变薄壳，消除约 130 行逐行重复（交易日轴/前向填充/dataset/options/zoom 门控）。
- 颜色单一来源：JS 删 `COLORS_LIGHT/DARK` 与 `themeColors()` 内联三元，新增 `cssVar(name, fallback)` 读 style.css 的 `--c-*` token（10 序列色 + 7 图表 UI 色）；fallback 保底 = 原 Dark 值。**Chart.js 不随 CSS 变量自动变色，切主题重渲染机制不变（pitfall #48）**。

## 验证结果（全部实际运行）
1. `node --check web/static/app.js` → 通过（抽离后才可能整文件校验；此前内联会因 `</script>` 截断假阴性）。
2. `venv/Scripts/python -m pytest tests/ -q` → **449 passed**（与重构前基线一致，含 50 个 web 契约测试）。
3. 新端口 8021 冒烟（项目纪律防缓存假阴性）+ 内嵌浏览器真实渲染断言：
   - 首页/静态资源/API 均 200；`/static/app.js` 外链加载、body 内联脚本清零。
   - 默认双主板图实例存在、KPI 4 卡 + 4 sparkline、概览 10 行、板块 5 行、告警卡正常、自选股卡显示且图高 220px（CSS 接管成功）、VIX/另类图按 R-3 设计默认隐藏。
   - **主题切换（最高风险点）**：dark→light 后 CSS token 换色（`--c-gspc` #66A8E0→#1677FF），图表 dataset borderColor 实测变为 `#1677FFd9`/`#13C2C2d9` —— 证明 Chart.js 成功从 CSS 变量取新色重渲染。
   - 截图目视：light 双主题下 KPI 卡/表格/趋势图/图例 chips 渲染正常；「未开盘」卡 sparkline 中性灰即 `--text-muted` 修复生效。
   - 移动端 375px：汉堡按钮出现、抽屉滑出 + 遮罩正常。

## 遇到的问题
- **cron `git add -A` 把进行中改动分段扫入 3 个 `auto: 每日数据更新` 提交（22:55/23:00/23:05）**：pitfalls.md L159 已记录的既有行为。最终入库树 = 本地已验证的最终版本（验证均在最终代码上跑通），无需回滚；但中间态曾短暂入库。**下次注意**：长任务期间可设 `AUTO_PUSH=0` 跑本地 cron，或接受该机制并在收尾时核对最终树。
- 内嵌浏览器 evaluate 首次返回空对象：IAB 通道对字符串形式 pageFunction 兼容差，改传真函数 + `JSON.parse(JSON.stringify(...))` 解决。

## 下次注意 / 遗留
- `.lede-val` 移动端冲突按「保留现生效的 16px !important + ellipsis」处理；如需 22px 需显式决策。
- 未动项（按计划）：W（sparkline 观感，等 09-07 ETF 数据自愈复查）、告警 md 中文冒号正则解析（涉生产端契约）、GLD ×10、CDN 策略、`web/app.py` 零改动（本次确实零改动）。
- 图表 CSS token 化后，**新增序列须同时加 `--c-*` token 与 `SERIES_VAR/SERIES_FALLBACK` 两处键**（或后续把 token 名直接按 key 拼接简化）。
