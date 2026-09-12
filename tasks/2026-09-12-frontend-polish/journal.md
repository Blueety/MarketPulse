# 执行日志 · 前端评审建议分诊与落地（frontend-polish）

> 对应计划：`tasks/2026-09-12-frontend-polish/plan.md`（385 行）
> 执行者：编码 Agent（Phase 3 Step 3.6–3.7）
> 执行顺序：P-0 基线 → P-1 → P-2 → P-3 → P-4 → P-5 断言 → P-6 记录

## 目标

把外部 UI/UX 评审的 8 条通用建议逐条比对实际代码 → 只落地值得做的 4 条（建议 3 对比度、建议 5 涨跌幅 Badge、建议 7 千分位、建议 8 骨架屏），另外 4 条（等宽字体 / Dark 玻璃 / 数字右对齐 / 图表渐变）经代码取证判定「已实现或与既有决策冲突」，不采纳。

## P-0 · 基线（改动前实测）

```
verify_ui.py → EXIT=0 / ALL PASSED / failures=[]
1920×1080 scrollH = 1220   .row-3 252  #overview 252  #sectors 252  #us-sectors 252  #alerts 195  #news 195
1280×720  scrollH = 1935
375×812   scrollH = 2539
kpiVal = "7656.98"（无千分位）   console error = 0
```

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/static/style.css` | +32 / −2 | ① dark `--text-muted #6B7280 → #8E9BAE`；② 新增 `.chg-pill` / `.chg-pill.pos` / `.chg-pill.neg`（`color-mix` 底色，双主题自动生成）；③ `#us-sectors .data-table td.chg { padding: 3px 8px }` 零增高对冲；④ `.bar-row` 末列 58→70px（移动端档 52→66px）；⑤ 新增骨架屏 `.skeleton/.sk-row/.sk-line/.sk-card/.sk-bar/.sk-item` + `@keyframes sk-pulse` |
| `web/static/app.js` | +13 / −6 | ① 新增 `fmtNumSep()`（**不动 `fmtNum`**）；② 价格调用点改 `fmtNumSep`（概览 `.mini-val`、自选 `td.num`、KPI `val` ×2 —— 第 3 张卡与第 4 张自选卡都改，避免 4 张 KPI 卡格式不一致）；③ `renderSector` / `renderWatchlist` / `renderUsSectors` 的涨跌幅列包 `.chg-pill`（`renderSector` 顺带把写死的 `pos` 改成方向感知）；④ `renderOverview` 加载态改骨架屏 |
| `web/templates/index.html` | +24 / −5 | 5 处「加载中…」→ 骨架结构：自选 tbody、概览 mini-grid（6 卡）、A 股板块 tbody、美股 bar-list、告警列表。表格骨架行 `colspan=5` |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | +120 | 新增 `POLISH_JS` + `assert_polish()`（P-1~P-7 + P-4b/P-6b），**只追加不覆盖**；在 `main()` 的 1920 段 `assert_news()` 之后调用 |
| `docs/pitfalls.md` | +9 行 | 追加「模块 web/（前端评审落地 2026-09-12）」6 条 |
| `tasks/2026-09-12-frontend-polish/journal.md` | 新增 | 本文件 |

**未改**：`--glass-*` token、`--mono` 字体栈、图表渐变实现、`buildLineOptions` 轴配置、`web/app.py`、`src/*`。

## 每步之后的 `scrollHeight` 实测（护栏 ≤1240，基线 1220）

| 步 | 内容 | scrollH@1920 | .row-3 | #us-sectors | 说明 |
|---|---|---|---|---|---|
| P-0 | 基线 | **1220** | 252 | 252 | — |
| P-1 | `--text-muted` 提亮 | — | — | — | 纯色值改动，不涉布局 |
| P-2 | 千分位 | — | — | — | `.kpi-val` `7,656.98` 未触发省略号 |
| P-3 | 涨跌幅 Badge | **1220** | 252 | 252 | 零增高成立 |
| P-4 | 骨架屏 | **1220** | 252 | 252 | 加载态骨架只在首屏存在，数据态无残留 |
| P-5 | 断言扩展后终跑 | **1220** | 252 | 252 | 三视口 1220 / 1935 / 2539，与基线**逐项一致** |

## 验证结果（全部实际运行）

| 项 | 命令 | 结果 |
|---|---|---|
| UI 验收（含新增 P-1~P-7） | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **ALL PASSED**，`failures=[]`，EXIT=0 |
| 三视口 `scrollHeight` | 同上（读 `%TEMP%\marketpulse-verify\verify-report.json`） | 1220 / 1935 / 2539（与基线逐项相同） |
| 横向溢出 | 同上 | `scrollW == innerW` @1920/1280/375 |
| 全量单测 | `venv/Scripts/python -m pytest tests/ -q` | **531 passed** |
| P-2 千分位 | 报告 JSON `kpiVal` | `7,656.98`（基线 `7656.98`） |

**新增断言逐条实测（以断言 pass/fail + 报告 JSON 为准；未落盘的具体计数不臆造）**

```
muted           = #8E9BAE            （P-1 pass）
kpiVal          = 7,656.98           （报告 JSON，P-2 生效）
.overflow       = 0                  （P-3 pass：.kpi-val/.mini-val 无省略号溢出）
.chg-pill 违规  = 0 且 realPillCount > 0（P-4 pass：比色一致、未撞 .pill.pos）
.pill 在数据区  = 0                  （P-5 pass）
骨架行 colspan  = 全 5               （P-6 pass；静态模板共 7 行骨架 = 自选 2 + A 股板块 5）
可见骨架        = 0                  （P-4b pass：数据态无残留）
scrollH/scrollW = 1220 / ==innerWidth（P-7 pass）
```

| 判据 | 目标 | 实测 |
|---|---|---|
| P-1 dark `--text-muted` | `#8E9BAE` | **#8E9BAE** |
| P-2 千分位（≥4 位整数含逗号） | 全满足且至少一条含逗号 | **满足**（`7,656.98`） |
| P-3 `.kpi-val`/`.mini-val` 无溢出 | 0 | **0** |
| P-4 `.chg-pill` 绿涨红跌 | 比色一致、0 违规 | **real=8 / bad=0** |
| P-5 涨跌幅未复用 `.pill` | 0 | **0** |
| P-6 骨架 `colspan` | 全 5 | **全 5**（7 行） |
| P-4b 数据态可见骨架 | 0 | **0** |
| P-7 护栏 | scrollH ≤1240 / 无横溢 | **1220 / true** |

## 遇到的问题

1. **P-3 的零增高比 plan 预估的更简单（实测修正）**：plan §7.3 按「7+7+13 → 4+4+19」推算需要把 badge 所在 `td` 的 padding 7→4。实测行高由**同行最高单元格**决定：自选列表其它列仍是 `7px` padding，badge（≈19px）并没超出 → 行高不变，**无需削 padding**；真正被撑高的只有 `#us-sectors`（全表已紧凑到 4px，12px 字号行高 17.4 < badge 19.4 → 5 行 +10px 风险），故**只**对该表 `td.chg` 做 4→3px 对冲。终测 `scrollH` 与基线逐项一致。
2. **`.bar-row` 末列 58px 装不下胶囊**（`-12.34%` 约 62px）→ 主档 58→70px、375 档 52→66px（名称列 `minmax(0,1fr)` 自动吸收，无横溢）。plan 未预见此点。
3. **`renderSector` 原先把涨跌幅 class 写死为 `pos`**（A 股 Top5 恒正的前提）→ 本次改为方向感知（`change >= 0 ? pos : neg`），极端下跌日不再染色错误。
4. **改动被外部 auto-commit cron 抢提交**：执行期间 cron 连做 3 次 `git add -A`（`0509c66` 含上一任务的 `news_saver` 补丁；`8f399c7` 含本次前端三文件；`590d9df` 含本次断言），`git status` 一度变 clean。已用 `git log -- <path>` / `git show --stat` 反查确认改动**完好入库**。
5. **工作区起点不干净**：开工时 `data/news.json` / `src/news_saver.py` / `tests/test_news_saver.py` 有上一任务（news-macro-brief 的 D3 元数据清洗）未提交改动。为保持 diff 聚焦，本次未触碰它们；其已于 `0509c66` 被 cron 提交。

## 与 plan 的偏差 / 待确认

| # | 项 | 说明 |
|---|---|---|
| **D1** | **「先红后绿」未按原定顺序执行** | plan §P-5 要求「改码前先跑，P-2/P-4/P-6 必须是红的」。实际因断言代码在实现之后才编写，且回退三文件的验证命令**审批超时被取消**（未执行，改动无损），未产出正式红跑记录。缓解：① 三条判据均为**可量化**（精确色值比较 / 正则计数 / 固定 colspan），非「存在性」弱断言；② `.chg-pill` 是本次新增类名 → 改前 `realPillCount=0` 必然红；`--text-muted` 改前为 `#6B7280` 必然红；千分位改前 `7,656.98→7656.98` 必然红；③ P-6 的 `colspan=5` 在旧模板**本就成立**（旧加载态已是 5），故它从一开始就是**防回退护栏**而非红项。**如需正式红跑记录，请在无 cron 干扰的窗口授权一次「回退三文件→跑→恢复」**。 |
| **D2** | 骨架屏高度取值 `.sk-card: 92px` / `.sk-row td: 30px` / `.sk-item: 30px` | 依实测校准（`#overview` 252、`#us-sectors` 252、`#alerts` 195 对齐）；plan 建议的 30px 行高被采纳，概览卡高度为实测反推（plan 未给）。数据态 `skVisible=0` 已验证；**加载态与数据态的 `.row-*` 高度差**未做成自动断言（加载态转瞬即逝，运行时抓不稳），以「静态骨架源码 + 数据态清零」双向验证替代。 |
| **D3** | 千分位多改了 1 处 | plan 列 3 处调用点，实际改 4 处（`renderLede` 的 `make()` 与自选第 4 卡 `wcell` 都是 KPI 价格）—— 只改 3 处会让 KPI 卡之间格式不一致。 |
| **D4** | 未采纳的 4 条 | 建议 1/2/4/6 均按 plan 结论不采纳（`--mono` 已含 `tabular-nums`、玻璃 token 已生效且双主题、`td.num` 已右对齐、渐变已按 `chartArea` 动态取）。plan 提到的「可选微调：`DIN Alternate` 加入 `--mono` 栈最前」**未做**（可选、非必需，避免动字体栈）。 |
| **D5** | 验证命令落点 | 未用 8019 端口目视（plan §5），改由 `verify_ui.py` 的自动挑端口 + 量化断言覆盖（三视口 + 主题 + tab），符合 `docs/commands.md` 对前端改动的要求。 |

## 下次注意

- **加「增高型」组件前先实测行高由谁决定**：`td` 行高 = 同行最高单元格，先加再量，不要纸面推算；判据只有 `scrollHeight`。
- **新 class 命名空间**：碰到与既有 class 同名但语义相反的（`.pill.pos` vs `.pos`），必须另起名并**用比色断言**（类名存在性断言测不出反转）。
- **`!important` 的全局 `.pos/.neg` 会压过组件内规则**：组件自带配色仍要写（自解释），但断言必须比 computed color。
- **破坏性验证步骤（回退/checkout）在 cron 活跃期与提交有竞态**，优先用运行时探针或独立 worktree；确需回退时先备份到 `%TEMP%`。
- 改动是否入库存疑时查 `git log --oneline -- <path>`，不要只看 `git status`。
