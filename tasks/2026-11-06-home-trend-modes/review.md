# 审查裁决单 · 首页趋势卡双视图（对比 / 点位）

## 审查范围

- **固定点**：工作区未提交改动（`git diff`，base HEAD = `4cb6afc`；10 文件 +786/−27，另加任务目录三份文档）
- **审查者**：独立子 agent（`ReviewTrendModes`）——它**没有接触主线程的会话历史**
- **给了它什么**：`tasks/2026-11-06-home-trend-modes/prd.md`、`plan.md`、`git diff`、`AGENTS.md` / `docs/architecture.md` / `docs/pitfalls.md` / `CONTEXT.md` / `skills/pre-review/SKILL.md`、相关既有实现（`web/static/chart-crosshair.js`、`scripts/verify/verify_ui.py`、`web/app.py:283-336`）
- **轮次**：第 1 轮（发现 F1–F8 + 7 条「未判断」；第 2 轮为修复复核，结果写进「逐条处理」的验证列）

## 审查者原文

> 以下为独立审查者报告原文（逐字，未改写、未删减）。

## 实跑命令与结果（顶部）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `venv/Scripts/python.exe -m pytest tests/ -q` | **880 passed**, 12 warnings, 126.17s |
| 2 | `venv/Scripts/python.exe scripts/verify/verify_ui.py` | **PASS 723 / FAIL 1 / SKIP 0**，297.65s；唯一红 = `CS-8b`（`docs/pitfalls.md:1039-1042` 记载的既有临界项，实测 18.2 vs 判据 >20）。报告 JSON：`scrollH` 1920=**1216**、1600=1186、1280=2170、900=2404、375=2731；`tabCount=5`（5 个视口全对）；`scrollW==innerW`（无横向溢出）；`chartWrapH@1920=432` |
| 3 | `venv/Scripts/python.exe scripts/verify/verify_offline_assets.py` | **ALL PASSED（6 组）**，6.43s |
| 4 | `bash scripts/check-gates.sh` | **EXIT=1**，但输出在本机 bash 里被码页吞成 11 个 `?`（`wc -c` = 14 字节），**判据不可读 ⇒ 不作证据** |
| 5 | 自写 Playwright 探针 ×4（落 `%TEMP%`，`MP_AUTH_DISABLED=1` 起服） | 见下各节实测值 |
| 6 | 断言增量核对 | `check(` 调用点 HEAD=**450** → 工作区=**463**（+13 = TM 组 13 条） |

## 改动摘要

把首页趋势卡从「4 组 tab 单视图」扩成「对比 / 点位」双视图：`对比` 保留 4 组并在末尾追加第 5 个「自选」tab（chips 跨组任选，至少 1 个，默认 `gspc+sh`，落 localStorage）；`点位` 新增标的 `<select>`（10 个 `SYMBOLS` 镜像）+ 5 档时间（260/780/1300/2600/3650），走既有 `/api/history?symbols=X&days=N` 取 `raw` 画绝对点位 + MA20/MA60，meta 换「区间涨跌/最高/最低/数据自」。两个视图共用 `#chart-main` 与全部降级件（空态 / 失败条 / 骨架 / `__chartFailed` / crosshair / zoom），`renderMainChart` 被 `renderTrendChart` 包一层的分派器替换了所有刷新调用点。零后端改动、零新静态资源。影响面：首页最高热路径（`refresh` / 主题切换 / macro 晚到 / tab 点击全部改走新分派器），外加 13 条新门禁断言。

## Standards

### 硬违规

- **[docs/architecture.md:37、docs/commands.md:114] 两份活文档仍在描述「4 类别 tab」，与代码（5 个 tab + 第二视图）矛盾。** 证据：`docs/architecture.md:37` 写「趋势**四图合一 + 4 类别 tab**（单 `canvas#chart-main`，7D/30D/90D/1Y）」；`docs/commands.md:114` 写「趋势**四图合一**（4 类别 tab，7D/30D/90D/1Y）」；而 `web/static/app.js:47-52` 的 GROUPS 是 4，`renderTrendTabs()` 用 `GROUPS.concat([CUSTOM_GROUP])`（`app.js:778`）渲染出 5 个按钮，实跑 `verify-report.json` 五视口 `tabCount` 全 5。本 patch 同一句话的 AGENTS.md 版本已同步（AGENTS.md:26），architecture.md / commands.md 的同义句没跟着改 ⇒ 只有一半同步。依据：`AGENTS.md:116`（Done Means 四项之四「要改的文档已改」）、`AGENTS.md:46-47`（architecture.md / commands.md 是行为级必读活文档）。
  *判定说明：`plan.md` 把文档范围限定为 AGENTS.md + pitfalls.md，所以这是计划缺口而不是执行者擅自缩范围；但落地的客观结果仍是活文档写错事实。*

### 判断题（坏味道）

- **[web/static/app.js:132-143 ↔ src/fetcher.py:30-41] 重复代码 / 数据泥团：符号清单被抄了两份，而且两处消费者口径不同。** `POINT_SYMBOLS` 是 `SYMBOLS` 的逐条手抄（10 项、顺序、label 当前完全一致，注释也写了「改一处必须两边同改」）。但「自选 chip 的清单」取自 `trendChipCatalog()`（优先用 `/api/history` 的 `series`），而点位下拉取自 `POINT_SYMBOLS` —— 同一概念两个来源：新增一个符号时 chips 会自动出现，下拉却不会，表现为「可选但不可点位」。修法：把下拉的选项也改为 history 到达后按 `series` 填充，或反过来把 chip 目录固定用 `POINT_SYMBOLS`，二者取其一。
- **[web/static/app.js:901-904] 死代码：`请至少选择一个标的` 不可达。** chip 处理器（`app.js:825-828`）与 `loadCustomKeys()` 都守「至少 1 个」，所以 `keys.length` 在 custom 分支恒 >0。实测：取消到只剩 `gspc` 后再点 `gspc`，`chipActive` 仍 `["gspc"]`、`dsCount=1`。`plan.md` §测试 Seam 要求的「自选一个都不选 → 空态文案」因此既不可达也无断言——与 plan 自己的「至少保留 1 个」不变量互相矛盾，需要选一个删掉。
- **[web/static/app.js:1789 注释] 注释与行为不符。** 注释写「（点位视图下为空操作）」，实际 `renderTrendChart()` 在点位视图会走 `renderPointChart()`，而它第一件事就是 `charts.main.destroy()` 再重建 ⇒ macro 晚到会把点位图的缩放状态重置。影响小，但注释该改。
- **[scripts/verify/verify_ui.py:5100-5103 附近 / TM-4b] 测试口径：期望值取自被测实现自己的钩子。** `TM-4b` 用 `window.__mpPointRawFirst`（实现写的）去比 `dataset[0]` 首个非空 y（实现画的）——只能证明「实现等于实现」。建议改成与 `/api/history` 响应体同源比对。

### 各维度

**Correctness（含「点位失败路径」两条，见 F1/F2）**
- **[app.js:1086-1087] `renderPointChart()` 在 `!payload` 时早退，使 `fetchPoint` 的失败分支那行渲染调用恒为空操作。** `fetchPoint()` 入口就 `state.point.payload = null`，失败分支里不可能有 payload ⇒ 一行图都不画。实测（history 正常、点位请求注入 500）：面板仍是**对比图**与**对比 meta**，而控件已经显示「点位 / GSPC / 1Y」。
- **[app.js:1610] `refresh()` 成功路径无条件 `showHomeFailBar(false)`，会抹掉点位链刚写上的失败条。** 实测（localStorage 预置 `mp-trend-view=point` + 点位请求注入 500 + `/api/history?days=30` 正常）：`failShown=false`、`dsCount=0`、`emptyShown=false`、`canvasDisplay=""` ⇒ **点位视图下 432px 空画布，零提示**。这正是仓库明文禁止的「失败 ≠ 静默」。

**Performance** — 点位视图只取 `series[0]`；MA 为 O(n·win)（299 点 × 60 ≈ 1.8 万次加法，实测 <1s）。切视图复用 `state.point.payload`，不重复取数。未发现 N+1 / 无界缓存 / 未解绑订阅。

**Tests** — TM 组 13 条新断言全部实际执行并通过；TM-1b / TM-1c / TM-5a / TM-4a 对旧实现必红。缺口见判断题第 4 条。

**Security** — 无可利用面：符号来自 `<select>`（受 `POINT_SYMBOLS` 白名单约束），`days` 受 `POINT_RANGES` 约束；URL 走 `encodeURIComponent`；meta 全用 `textContent`。

**Conventions** — 命名符合 AGENTS.md:74；未新增静态资源（`?v=` 由 mtime 生成）；无 `[DEBUG-` 残留。

**Docs** — 见硬违规 1 条；`docs/pitfalls.md` 新增 5 条与代码一致。

**回归风险逐项核对**

| 风险点 | 结论 | 证据 |
|---|---|---|
| 首页高度门禁 | **未回归**（默认态） | 1920 `scrollH=1216`（与 patch 前基线一致）；`#trend-view` 未触发换行；`chartWrapH=432` |
| 既有 tab 轮询断言 | **未回归** | tab 循环 5 轮全 PASS；TM-1 复位 `tab[0]`，TM-7 再复位并清 localStorage；console error = 0 |
| 主题切换重画路径 | **未回归** | 改走 `renderTrendChart()`；「切主题后图表实例存活」PASS。点位视图下的主题重画未单独断言 |
| macro 晚到重画路径 | **行为有变但无害** | 点位视图下会 destroy+重建（缩放复位），与注释「空操作」不符 |
| `gcf` 取色 | **图线正确，meta 错误** | 图线 `rgba(212,160,23,0.85)`；meta 色 `rgb(139,148,158)` → F4 |

## Spec

- **缺失/部分实现 ×2**：点位下拉不随 `SYMBOLS` 自动对齐；plan 声明的「空选 → 空态」边界不可达。
- **范围蔓延 ×1**：点位 meta 的「最高/最低」固定 2 位小数，与 y 轴 `pointYDigits()` 不一致（BTC 档会出现轴 `108,000` 与 meta `108,000.00`）。
- **实现可疑 ×2**：失败分支两条渲染都不产生可见结果；点位视图的空态/失败态不复位 `#trend-meta`（会残留上一次的值）。

### 验收标准 → 证据

| # | 验收标准 | 证据 |
|---|---|---|
| 1 | 默认：两按钮、对比激活、5 tab、美股大盘归一化 | 探针 A + `verify-report.json` 五视口 `tabCount=5` ✅ |
| 2 | 自选 10 chip；勾 GSPC+SH → 2 线且从 100 起算 | 探针 `custom_default`：`chipCount=10`、`dsLabels=["标普500","上证指数"]`、`firstYs=[100,100]` ✅ |
| 3 | 点位+上证+1Y → `symbols=SH&days=260`；y 绝对点位；meta 四项 | 探针 C：`dataset[0]` 首 y=**3969.248**，末 3649.1774，max 4242.5718，min 3599.0166；meta 与 DB 手算逐位一致 ✅ |
| 4 | 10Y → `days=2600`；不足则仍渲染 + 显示实际起点 | 探针 D：`dsCount=3`、281 点、`数据自 2025-09-11` ✅ |
| 5 | 两视图切换高度 ≤2px、console error 0 | 1920：`432/432`；375：`280/280`；`console=[]`、`pageerrors=[]` ✅ |
| 6 | `verify_ui` 全绿（除 CS-8b） | PASS 723 / FAIL 1 ✅ |
| 7 | `verify_offline_assets` 全绿 | ALL PASSED（**6 组**：3 页 × 2 视口）。⚠️ PRD 写「8 组」与脚本实报不符（PRD 数字陈旧）；该门禁只跑默认对比视图，不覆盖点位视图 |
| 8 | `pytest` 全绿 | 880 passed ✅ |

## 独立期望值预言机

**方法**：绕开页面与 `/api/history`，直连 `data/marketpulse.db`（`mode=ro`）用 Python 重算「最后 N 个工作日 × `sh` 列」的首/末/极值/涨跌幅与 MA20/MA60 全集，再与浏览器实测逐例对打。

| 被测面 | 独立期望（DB 手算） | 页面实测 | 判定 |
|---|---|---|---|
| SH `days=260` 首点 | `3969.248046875` @ 2025-11-05 | `3969.248`（双处） | ✅ |
| SH `days=260` 末点/极值 | 3649.1774 / 4242.5718 / 3599.0166 | 一致 | ✅ |
| SH `days=260` 区间涨跌 | `-8.063760…%` | meta `-8.06%` | ✅ |
| SH `days=260` 非空点数 | 248 | 248 | ✅ |
| SH `days=2600` 首点/起点 | `3875.30908203125` @ 2025-09-11 | `3875.3091` | ✅ |
| SH MA20 @1Y | n=135，首值 `3939.3565` | 一致 | ✅ |
| SH MA20 @10Y | n=154，首值 `3933.4887` | 一致 | ✅ |
| SH MA60 @10Y | n=49，首值 `3926.1945` | 一致 | ✅ |
| 3Y/5Y/10Y/全部 退化 | 780/2600/3650 三档窗口都=299 个工作日 | 281 点（SH 非空数） | ✅ |
| 自选 2 条线基期 | 归一化 = 窗口首个非空值 → 100 | `firstYs=[100,100]` | ✅ |
| `gcf` 图线色 | `--c-gld` = `#D4A017` | `rgba(212,160,23,0.85)` | ✅ |
| `gcf` meta 色 | 应为同一 token | `rgb(139,148,158)`（兜底灰） | ❌ F4 |

## 发现清单

- **F1 [P1 · conf 0.85]** `refresh()` 抹掉点位取数失败条 → 点位视图静默空白卡（`app.js:1610` / `1023`）。
- **F2 [P2 · conf 0.9]** 点位取数失败时卡内留的是对比图 + 对比 meta（`app.js:1037-1041` / `1086-1087`）。
- **F3 [P2 · conf 0.95]** 点位视图下 `#range-label` 恒「近 30 日」（`index.html:105` / `app.js:1597-1598`）。
- **F4 [P3 · conf 0.9]** 自选勾黄金时 meta 文字色退回灰色（`app.js:856`）。
- **F5 [P3 · conf 0.8]** 点位下拉符号清单是 `SYMBOLS` 手抄副本，且与 chip 目录来源不一致。
- **F6 [P3 · conf 0.85]** `请至少选择一个标的` 为不可达死代码；plan 的「空选 → 空态」边界未实现。
- **F7 [P3 · conf 0.9]** `docs/architecture.md:37`、`docs/commands.md:114`（另 `docs/frontend-structure.md:65/172/180`、`docs/system-overview.md:73`）仍写「4 类别 tab」。
- **F8 [P3 · conf 0.8]** 点位 meta 极值恒 2 位小数，与 y 轴 `pointYDigits()` 不一致。

## 审查者明确未判断的

1. **点位 / 自选视图下首页总高超过 PRD 的 1240 上限是否接受**：实测 1920 默认 1216（门禁绿）、**点位 1254**、**对比+自选 1250**。建议若收回最小改法是把 `#point-bar` 移进 `.card-head`。
2. **`pointYDigits` 的取位阈值（≥1000→0 / ≥100→1 / <100→2）是否想要的口径**（PRD 只定义了 ≥1000 与 <100 两端）。
3. **3Y/5Y/10Y/全部 在当前数据下渲染完全相同，「数据自」是否足够区分**。
4. **点位视图下主题切换的视觉是否正确**（只验了代码路径，未断言点位视图配色）。
5. **点位取数失败 + 重试按钮的闭环**（`#home-retry` 绑 `refresh()`，代码上看不会重发点位请求）。
6. **`#trend-view` 进 `.card-head` 后四段的视觉分布**（尺寸门禁全绿，好看与否需人看截图）。
7. **`plan.md` 自相矛盾的两条**（chip「至少保留 1 个」vs 边界「一个都不选→空态」）哪个是本意。

## 小结

- **Standards：8 条**（1 硬违规 + 3 判断题 + 1 Tests 口径 + 3 各维度/文档），最严重 = F1（P1）。
- **Spec：8 项验收全部有代码/实测证据且一致**（独立预言机逐位吻合 DB），最严重缺口 = F2、F3。

---

## 逐条处理

> 处理只有三种：改 / 不改 + 理由 / 不接受 + 反证。「第 2 轮实测」列是**主线程独立复跑**的数值（探针落 `%TEMP%`，非执行者自述）。

| # | 审查者发现（原文摘要） | 处理 | 依据 / 落地 | 第 2 轮实测 |
|---|---|---|---|---|
| F1 | `refresh()` 成功分支抹掉点位失败条 ⇒ 点位视图静默空白卡 | 改 | `refresh()` 成功分支改为 `if (state.trendView !== 'point') showHomeFailBar(false)`；点位链失败条归 `fetchPoint` 所有 | 注入点位 500 后点 `#refresh-btn`：`fail_bar_after_refresh.shown = true`（修复前会被抹掉） |
| F2 | 点位取数失败时卡内留对比图 + 对比 meta | 改 | 新增 `showPointCardState(msg)`：destroy 实例 + canvas `display:none` + `#chart-main-empty` 去 hidden 写文案 + 清空 `#trend-meta`；`__chartFailed` 分支同样复位 meta | 注入 500：`#chart-main-empty` = **「点位数据获取失败」**、`canvas.display = "none"`、`#trend-meta` = `""` |
| F3 | 点位视图 `#range-label` 恒「近 30 日」 | 改 | 新增 `trendRangeLabel()` / `syncRangeLabel()` 作为**唯一来源**，`refresh()` 里的重复写入删除；`applyTrendViewUI()` / `#point-range` 点击 / 渲染后均调用 | 点位 1Y → `"1Y"`；对比 → `"近 30 日"` |
| F4 | 自选勾黄金时 meta 文字色退回灰色 `#8b949e` | 改 | `renderTrendMeta` 改用 `seriesColor(palette, s.key)`（自带 `gcf→gc=f` 映射与兜底） | 勾黄金后 meta 色 `rgb(212,160,23)` == 线色 `rgba(212,160,23,0.85)` |
| F5 | 点位下拉是 `SYMBOLS` 手抄副本，与 chip 目录不同源 | 改 | 新增 `pointSymbolCatalog()`：`state.history` 到达后按 `series`（`key.toUpperCase()` + `label`）重建 `<select>`，`POINT_SYMBOLS` 仅首帧兜底；`refresh()` 成功回调触发一次 | `<select>` 10 项，值与文案来自 `/api/history` 的 series |
| F6 | `请至少选择一个标的` 不可达；plan 的「空选 → 空态」边界无法触达 | 改 | 删死分支，保留「至少保留 1 个」不变量（门禁契约：既有 tab 轮询要求每个 tab 切后都有图 + meta ≥1）；`prd.md` / `plan.md` 同步改写 | 只剩 1 个 chip 时再点它：active 仍 = 1、dataset = 1 |
| F7 | 5 处活文档仍写「四图合一 / 4 类别 tab」 | 改 | 更新 `docs/architecture.md:37`、`docs/commands.md:14/114`、`docs/frontend-structure.md:65/172/180`、`docs/system-overview.md:73` | `grep "四图合一\|4 类别 tab" docs/*.md AGENTS.md` → 仅剩 `docs/architecture.md:150`（2026-09-11 的历史变更行，属史实，不改） |
| F8 | 点位 meta 极值恒 2 位小数，与 y 轴 `pointYDigits()` 不一致 | 改 | meta 极值复用 `pointYDigits(raw)` | 标普点位 meta：`区间最高 7,839` / `区间最低 6,344`（0 位，与 y 轴 `8,000/7,500` 同口径） |
| 未判断 1 | 点位 1254 / 自选 1250 超出 1240 预算 | 部分改 | `#point-bar` 移进 `.card-head`（点位下 tabs/range 已隐藏，一行放得下）⇒ 点位态回到 1216；**自选态 1250（+34px）接受**并写进 `prd.md`：预算用于保护默认看板布局，自选是用户主动进入的临时态 | `scrollHeight @1920`：默认 **1216** / 点位 **1216** / 自选 **1250** |
| 未判断 2 | `pointYDigits` 100~1000 区间补了 1 位小数 | 不改 | 该区间是标普/纳指/上证的量级；1 位小数避免 `3,649.2 → 3,649` 丢精度，≥1000 取 0 位是因 axis 宽度有限 | — |
| 未判断 3 | 3Y/5Y/10Y 在当前数据下退化，用户可能以为「点了没反应」 | 改 | `trendRangeLabel()` 在点位视图追加实际跨度（`pointSpanMonths()`，`Date.UTC` 手工拆日期，30.44 天/月，≥1） | 点位 10Y → `"10Y（实际 13 个月）"` |
| 未判断 4 | 点位视图主题切换未验证 | 改（主线程补测） | 探针：点位视图切 dark，读 dataset 线色与 axis tick 色 | `rgba(22,119,255,.85) → rgba(102,168,224,.85)`、`#86868b → #8492A6`、实例存活、`pageerror = 0` |
| 未判断 5 | `#home-retry` 不会重发点位请求 | 改 | 重试处理器：`refresh()` 后若 `trendView==='point'` 再 `fetchPoint()` | 失败后点重试：图恢复（`chart` 实例存在）、失败条隐藏、meta 回到 `标普500 1Y …` |
| 未判断 6 | `#trend-view` 进 card-head 的四段视觉分布 | 不改 | 1920 / 375 截图目视确认：四段不换行、无截断；「好看」属主观项，留给用户看线上效果 | 截图 `%TEMP%/tm_compare_mobile.png` / `tm_point_mobile.png` |
| 未判断 7 | plan 两条自相矛盾（「至少 1 个」vs「空选空态」） | 改 | 以「至少保留 1 个」为准（见 F6），`prd.md`/`plan.md` 同步 | — |

## 结论

- 第 1 轮 8 条发现 + 7 条「未判断」共 15 项，**无一条被静默跳过**：改 12 项、部分改 1 项、不改 2 项（均有理由）。
- 第 2 轮复核（主线程独立复跑，不采信执行者自述）：`pytest` **880 passed**；`verify_ui` **733 PASS / 1 FAIL（CS-8b 既有临界项）/ 0 SKIP**；`verify_offline_assets` **ALL PASSED（6 组）**；高度 1216 / 1216 / 1250；失败路径与重试闭环实测通过。
- 无未解决的 Critical / P1 项。
