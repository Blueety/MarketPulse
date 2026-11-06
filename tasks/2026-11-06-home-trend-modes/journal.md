# 执行日志

## 目标

把首页趋势卡从「4 组固定分组、只能组内比、只能看归一化走势」升级成双视图：`对比`（保留 4 组 + 第 5 个「自选」tab，跨组任意组合）与 `点位`（单指数绝对点位 + MA20/MA60，时间档 1Y/3Y/5Y/10Y/全部），两视图共用同一 canvas，默认态零增高。**后端零改动**（`/api/history` 的 `symbols` / `days` 早已够用）。

## 主要提交

- **主要提交**: `fd77fac`

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `web/templates/index.html` | 卡头加 `#trend-view`（对比/点位）；`#trend-chips`（独立行，默认 hidden）；`#point-bar` 移进 `.card-head`（与 tabs/range 互斥显示） |
| `web/static/app.js` | `state` 增 `trendView/customKeys/point{symbol,days,payload}` + 4 个 localStorage 键；`renderTrendTabs` 追加「自选」；`renderTrendChips` / `renderTrendChart` 分派 / `fetchPoint` / `renderPointChart`（绝对点位 + MA + meta）/ `showPointCardState` / `syncRangeLabel`（`#range-label` 唯一来源）/ `pointSymbolCatalog`（下拉与 chip 同源）/ `seriesColor`（`gcf→gc=f` 取色）；`renderMainChart` 支持 custom 组；3 处重画调用点改走 `renderTrendChart`；重试按钮在点位视图重发点位请求 |
| `web/static/style.css` | `.trend-chips/.trend-chip/.point-bar/#point-symbol`（+22 行）+ `#trend-tabs.hidden,#range-bar.hidden{display:none}`（`.hidden` 特异性收口） |
| `scripts/verify/verify_ui.py` | `tabCount` 4→5；新增 `TM-1..TM-9`（13→26 条断言）：按钮/显隐、请求 URL、绝对点位与 `/api/history` 响应体**同源**比对、chip 不变量、高度稳定、失败注入 500 的卡内文案与失败条归属、`#range-label` 跟随档位、重试闭环 |
| `AGENTS.md` / `docs/{architecture,commands,frontend-structure,system-overview}.md` | 「趋势四图合一 + 4 类别 tab」→「对比（4 组 + 自选）/ 点位双视图」（`architecture.md:150` 的历史变更行保留原文） |
| `docs/pitfalls.md` | +9 行：共用 canvas 的高度/位图护栏、`#trend-tabs` 顺序契约、「自选默认非空是门禁契约」、`.hidden` 特异性被 `.seg{display:flex}` 反压、`gcf ≠ gc=f` 取色、10Y 档依赖回填 |
| `tasks/2026-11-06-home-trend-modes/{prd,plan,review}.md` | 需求 / 计划 / 审查裁决单 |

## 验证结果

| 命令 | 结果 |
|---|---|
| `venv/Scripts/python.exe -m pytest tests/ -q` | **880 passed**，12 warnings（主线程独立复跑两次：112s / 106s 同结果） |
| `venv/Scripts/python.exe scripts/verify/verify_ui.py` | **PASS 733 / FAIL 1 / SKIP 0**（305s，主线程独立复跑）；唯一红 = `CS-8b 横线不再跟手`（`docs/pitfalls.md` 已登记的既有临界项，18.2 vs 判据 >20） |
| `venv/Scripts/python.exe scripts/verify/verify_offline_assets.py` | **ALL PASSED（6 组）**：3 页 × 2 视口阻断第三方后仍出图 |
| `sh scripts/check-gates.sh` / `--staged` | 通过（注：本机 `sort` 被 `C:\WINDOWS\system32\sort.exe` 抢先时会误报「模块划分表里没有声明任何模块」，必须 `PATH=/d/Claude/Git/usr/bin:/usr/bin:$PATH`） |
| 自写 Playwright 探针（`%TEMP%`，主线程） | 点位失败注入：`#chart-main-empty` =「点位数据获取失败」、canvas `display:none`、meta 清空、刷新后失败条仍在、点重试后图恢复；`#range-label`：对比 `近 30 日` / 点位 `1Y` / `10Y（实际 13 个月）`；高度 1920：默认 **1216**、点位 **1216**、自选 **1250**；点位视图切 dark 线色 `rgba(22,119,255,.85)→rgba(102,168,224,.85)`、实例存活、`pageerror=0`；自选勾黄金后 meta 色 == 线色 `rgb(212,160,23)` |
| 移动端截图（390×844） | 对比 / 点位 / 自选三态目视通过（`%TEMP%/tm_compare_mobile.png`、`tm_point_mobile.png`、`tm_custom_mobile.png`） |

- 未运行的检查及原因：`lint` / `typecheck`（本项目未配置，见 `AGENTS.md` Commands）。
- 被打回: 1 次（独立审查 1 轮，F1–F8 + 7 条「未判断」全部逐条处理，见 `review.md`）

## 遇到的问题

1. **点位视图的失败路径两条腿都被踩断**（审查 F1/F2）：`fetchPoint()` 入口把 `payload` 置空 ⇒ 失败分支里的 `renderPointChart()` 恒早退（一行不画）；而 `refresh()` 成功又无条件 `showHomeFailBar(false)` 把失败条抹掉 ⇒ 「点位模式 + 点位接口 500 + history 正常」会得到一张 432px 的**空画布且零提示**。修法：失败分支改为 `showPointCardState(msg)` 显式写卡内文案 + 清 meta；`refresh()` 成功时只在非点位视图清失败条。实证：注入 500 后 `emptyText="点位数据获取失败"`、`canvas.display="none"`、刷新后 `failBar.shown=true`。
2. **`#range-label` 曾有 3 个写入点**（`refresh()` / 点位档位切换 / 视图切换），导致点位视图恒显示「近 30 日」。收敛成 `syncRangeLabel()` 单一来源。
3. **`.hidden` 压不过 `.seg{display:flex}`**：`#trend-tabs` / `#range-bar` 本身就是 `.seg` 节点，隐藏必须用 id 特异性规则（`.hidden` 只有 (0,1,0) 且规则位置更靠前）。已写入 `docs/pitfalls.md`。
4. **执行者第一轮把 chips 的 `className` 只写了 `active`**，DOM 有按钮但选择器取不到 ⇒ `TM-5a` 首跑红，且 Playwright 的 `click` 等 30s 才超时，真错被埋在超时栈里。第二轮给 chip 计数加了前置守卫。
5. **`#point-bar` 单独一行会让点位态 scrollHeight = 1254（超 1240 预算 14px）**：把它移进 `.card-head`（点位视图下 tabs/range 已隐藏，一行放得下）后回到 1216。自选态无法避免 +34px（1250），已在 `prd.md` 记录取舍。
6. **本机 gate 的 `sort` 被 Windows `sort.exe` 抢先**：`sort -u` 报「The system cannot find the file specified」并输出空 ⇒ 假报「`docs/architecture.md` 的模块划分表里没有声明任何模块」。判据：`which -a sort | head -1` 是 `/c/WINDOWS/system32/sort`；修法：`PATH=/d/Claude/Git/usr/bin:/usr/bin:$PATH`。

## 下次注意什么

- 改 `#trend-tabs` 的数量/顺序必须同步三处：`verify_ui.py` 的 `tabCount`（多视口）、tab 轮询断言（要求每个 tab 切后都有图 + `#trend-meta .meta-item ≥1`）、`docs/pitfalls.md` 的顺序契约 → pitfalls
- 新增趋势卡控件一律默认 `hidden`，显示用 `:not(.hidden)` 或 id 特异性；`.hidden` 会被同文件更靠后的 `display:flex` 类规则反压 → pitfalls
- 首页高度预算只剩 24px（默认态 1216 / 上限 1240）：任何新增常驻元素都要先量 `scrollHeight`，或塞进既有行/互斥显示 → pitfalls
- 修 `verify_ui` 的失败注入类断言要用**独立 browser context**：注入的 500 会让浏览器记一条 console error，污染主页面「全流程 console error = 0」 → pitfalls
- 三点位视图的档位退化（3Y/5Y/10Y 同长度）靠 `#range-label` 的「（实际 N 个月）」暴露，回填 10 年后会自动消失，别把它当死代码删掉 → pitfalls
- 本机门禁必须在 `PATH=/d/Claude/Git/usr/bin:/usr/bin:$PATH` 下跑（Windows `sort.exe` 抢 `sort -u`）→ pitfalls（已由本任务补写进「部署到自有 ECS」之外的下一节？没有 → 记在此，下次并入 pitfalls）

## 涉及的 ADR

- 无

## 下一步

- **10 年回填（待用户确认）**：`scripts/backfill_history.py --range 10y --dry-run` 已跑，结论：GSPC/IXIC/VIX/VXN/MOVE/GCF 各 ~2500 天（2016-11-07 起）、SH 2427 / SZ 2425 / CYB（Yahoo 仅 1 天 → AkShare 2428 天）/ BTC 3653 天；**待新增 2297 个交易日行**（2016-11-07 ~ 2025-09-10），既有 309 行不动；DB 预计 348 KB → ~2.5 MB。写库属不可逆数据动作 + 会改变线上数据源，需用户点头。
- 回填后点位图的 3Y/5Y/10Y 档才会真正拉长；在此之前「数据自 2025-09-11」是诚实降级。
- `docs/pitfalls.md` 里可再补一条「门禁需 PATH 修正」的条目（本次只写进 journal）。

## 雾区变化

- **解掉的雾区项**: 无
- **新增的雾区项**: 10 年后是否给点位图加对数坐标（等回填后看形态决定）

## 一致性走查

- **本次是否走查**: 做了限定范围的走查（T3 触发）
  - 触发条件：T3 任务结束（`tasks/` 在飞 4 + `_archive/` 99 = 103 个任务目录）
  - 范围：本任务触及的 6 份活文档 + 全仓 `docs/` 的模块表/相对链接/ADR 互链（`sh scripts/check-gates.sh` 全量通过）
  - 发现：5 处「趋势四图合一 / 4 类别 tab」过期描述（已随本任务修掉，见 `review.md` F7）；`docs/architecture.md:150` 的同名文字属 2026-09-11 的历史变更行，保留
  - 未做：全量 `skills/self-audit/SKILL.md` 清单（下次专任务做）

## 结束状态

- **结束状态**: `DONE_WITH_CONCERNS`
  - 关注点 1：10 年回填未执行（等用户确认），3Y/5Y/10Y 三档暂时退化
  - 关注点 2：自选态 `scrollHeight` 1250（超 1240 预算 10px），已记录取舍
  - 关注点 3：`verify_ui` 唯一红项 `CS-8b` 是既有临界项，与本任务无关
