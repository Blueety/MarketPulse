# 首页趋势卡：跨组自选对比 + 单指数点位视图

## 档位

- **档位**: T3 — 5 文件 / 0 调用方 / 行为有变 / 有现存 UI 门禁兜底 / 预估 320 行

## Goal

首页趋势卡目前只能**按固定 4 个区域组**（美股大盘 / A股大盘 / 波动率 / 另类资产）组内叠加归一化曲线，既不能跨组比，也看不到任何一个指数的**绝对点位**。本次把这一张卡升级成双视图：`对比`（保留原有分组 + 新增「自选」可任意跨组组合）与 `点位`（单指数绝对点位走势，最大 10 年），**共用同一个 canvas，卡片高度不变**。

## Requirements

- 视图切换 `对比 | 点位` 放在趋势卡头（`.card-head`），默认 `对比`，切换记 localStorage。
- `对比` 视图：原有 4 个组 tab **顺序与语义不变**，末尾追加第 5 个 tab「自选」；「自选」激活时显示 10 个标的 chip，可任意跨组组合（含仅选 1 个）；**至少保留 1 个**（取消最后一个无效），选择记 localStorage。
- `点位` 视图：`标的下拉（10 个 SYMBOLS）+ 时间档 1Y/3Y/5Y/10Y/全部`；画**绝对点位**折线（不归一化），叠加 MA20 / MA60，卡片下 meta 行显示 `区间涨跌 / 最高 / 最低 / 数据起点`。
- 点位数据走 `GET /api/history?symbols=<单个符号>&days=<N>`（后端已支持，**零后端改动**）。
- `days` 映射：1Y=260、3Y=780、5Y=1300、10Y=2600、全部=3650（交易日条数，与既有 `state.days` 口径一致）。
- 两种视图共用 `#chart-main` / `#chart-main-wrap`（432px）与既有 `#chart-main-empty` 空态、`#home-fail-bar` 失败条、`#home-chart-skel` 骨架。
- 必须保持：`window.__chartFailed` 降级链、crosshair 插件（`chart-crosshair.js` 的 `makeHoverCrosshair`）、zoom 注册、主题变量取色（`cssVar`/`themeColors`）、移动端 375px 可用。
- 必须保持首页 `scrollHeight @1920 ≤ 1240` 与 `#trend-tabs button` 数量断言同步（4 → 5，见 plan §步骤 4）。

## 这一版要验证什么

- 无（需求已定：用户明确要「自由选指数对比」和「单指数点位图」）。

## User Stories

1. 作为看盘用户，我想把标普、上证、VIX 放在同一张图上比相对走势，以便判断跨市场的风险偏好。
2. 作为看盘用户，我想切到「点位」看单只指数自己的绝对价位曲线，以便判断它走到了什么位置。
3. 作为看盘用户，我想把点位窗口拉到 10 年，以便看长期形态（数据未回填前按实际起点显示）。
4. 作为手机用户，我想这两个视图都能在窄屏上正常显示，以便随时查看。

## 验收标准

1. Given 打开首页，When 默认加载完成，Then 趋势卡头有 `对比 / 点位` 两个按钮，`对比` 为激活态，且 `#trend-tabs button` 共 **5** 个（4 组 + 自选），当前图仍是「美股大盘」归一化叠加。
2. Given 处于「对比」，When 点击「自选」，Then 显示 10 个 chip；勾选 `GSPC` 与 `SH` 后，图表 dataset 数为 2 且两条线都从 100 起算（归一化口径不变）。
3. Given 处于「点位」，When 选择「上证」+ `1Y`，Then 发出 `GET /api/history?symbols=SH&days=260`，图线 y 值为**绝对点位**（不等于以 100 为基的归一化值），meta 显示区间涨跌 / 最高 / 最低 / 数据起点。
4. Given 处于「点位」，When 选 `10Y`，Then 请求 `days=2600`；若库内数据不足（<2600 个交易日），图仍正常渲染且 meta 的「数据起点」显示实际最早日期。
5. Given 任一视图，When 在两视图间来回切换，Then `#chart-main-wrap` 高度变化 ≤ 2px，且 console error 数为 0。
6. `venv/Scripts/python.exe scripts/verify/verify_ui.py` 全绿（除既有 `CS-8b` 已知临界项）。
7. `venv/Scripts/python.exe scripts/verify/verify_offline_assets.py` 全绿（脚本实报 **6 组**：3 页 × 2 视口；早期 PRD 写「8 组」是陈旧数字，以脚本输出为准，`/` 页仍出图）。
8. `venv/Scripts/python.exe -m pytest tests/ -q` 全绿（880 passed 基线不被破坏）。
9. Given 处于「对比 / 自选」，When 只剩 1 个 chip 时再点它取消，Then **无效**（chip 仍为激活、dataset 数仍为 1）——「至少保留 1 个」是不变量，因此不存在「一个都不选」的空态分支。
10. Given 1920×1080，When 量首页 `scrollHeight`，Then 默认态 **1216** / 点位态 **1216**（C3：`#point-bar` 放进 `.card-head`，与 `#trend-tabs`/`#range-bar` 二选一，不额外增高）/ 对比 + 自选态 **1250**（+34px，**接受**：自选是用户主动进入的临时态，长度预算保护的是默认看板布局）。

## Out of Scope

- 不新建页面、不新增路由、不新增 API 端点、不改 `/api/history` 的响应形状。
- 不在首页新增卡片/新行（高度预算只剩 24px）。
- 不做 A/B 比值曲线、不做分面小图、不做相关性矩阵。
- 不动 `#watchlist-section`、KPI、板块、告警、资讯等其它模块。
- **不做 10 年数据回填**（独立步骤，先 `--dry-run` 出报告，人工确认后才写库）。

## Not yet specified（雾区）

- 10 年回填后是否需要给点位图加「对数坐标」——等看到 10 年形态再定。
- 自选组合是否需要可命名/保存多套——先只存一套。

## Constraints

- 前端库一律用已 vendored 的 `web/static/vendor/chartjs/`（Chart.js 4.4.1 + zoom 2.0.1），**禁止引入任何外部 CDN**。
- 新增静态资源必须登记 `web/app.py` 的 `_ASSET_FILES`（本次只改既有 `app.js`，无需新增登记）。
- 首页是 450 条 `verify_ui` 断言盯着的页面：任何增高、任何选择器改名都会连带变红。
- `#trend-tabs` 的按钮顺序：`us, cn, vol, alt, 自选`（既有脚本 `verify_ui.py` 会 `click('#trend-tabs button[1]')`，必须仍指向 `cn`）。
- 命名：JS camelCase / id kebab-case；新 id 前缀 `trend-*` / `point-*`。

## Context Pointers

- `web/static/app.js`：`GROUPS`（47-52）、`state`（125-133）、`buildQuery`（159-161）、`renderMainChart`（750-880）、`renderTrendMeta`、`fmtNumSep`（148-153）、`fmtAxisPct`（156-158）
- `web/templates/index.html`：趋势卡 98-131
- `web/static/chart-crosshair.js`：`window.makeHoverCrosshair({formatter})` 与硬契约注释
- `scripts/verify/verify_ui.py`：450 处 `check(`；`tabCount` 探针 284 行、断言 4958 行；`#range-bar` 点击 5174 行
- `web/app.py:283-336`：`_resolve_symbols` / `_build_history_payload`（`values` 归一化 + `raw` 原始值）

## Testing Decisions

- **要测的 seam**: 纯前端，无 Python 单元 seam；seam 落在 `scripts/verify/verify_ui.py` 的新断言组 `TM-*`（Playwright 真实渲染）+ `verify_offline_assets.py`（回归）。
- **好测试的标准**: 断言**可观察的外部结果**（dataset 数量、y 值量级、请求 URL、容器高度、console error），不断言实现细节或 CSS 数值。
- **同库先例**: `verify_ui.py` 的 `CN-*` / `TL-*` / `BT-*` / `ST-*` 分组写法；探针写在 `FIDELITY_JS` 之外的独立 evaluate 里。

## Risks

- `.card-head` 是 `flex-wrap: wrap`：多加一个 seg 在 1920 下宽度仍够（实测 h2+tabs+range ≈ 770px，卡宽约 1024px），但必须在验收里实测 `scrollH` 未变。
- 点位模式请求参数若误用 `days` 之外的 `start_date`，会破坏「10Y 档」的明确语义 → 断言请求 URL。
- 数据现状只有 14 个月：10Y/5Y/3Y 三档在回填前会退化成同一长度，必须显示「数据起点」避免被当成 bug。

## 术语与决策

- **已排除的方案**: 新建「指数对比」独立页（用户明确改为优化首页）；新开一行卡片（高度预算不足）；用 popover 放自选 chip（发现性与移动端点击面积都更差）。
- **刻意偏离常规的地方**: 「自选」做成第 5 个 tab 而非在 4 个 tab 之外加控件——保持 `.card-head` 元素数不变，避免 `card-head` 换行导致增高；chips 行只在「自选」激活时出现（默认态不受影响，门禁测的是默认态）。

## Verification Plan

- [ ] `venv/Scripts/python.exe -m pytest tests/ -q`
- [ ] `venv/Scripts/python.exe scripts/verify/verify_ui.py`
- [ ] `venv/Scripts/python.exe scripts/verify/verify_offline_assets.py`
- [ ] 手工：390×844 移动视口截图，两视图各一张
