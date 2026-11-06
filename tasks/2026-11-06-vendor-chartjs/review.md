# 审查裁决单

## 审查范围

- **固定点**：工作区未提交改动（`git diff` + 3 个未跟踪路径）。任务目录本身随本次一并提交，故以工作区为准。
- **审查者**：独立子 agent（`reviewer`）——它**没有接触主线程的会话历史**
- **给了它什么**：`prd.md`、`plan.md`、`git diff` 与未跟踪文件内容、`AGENTS.md`、`docs/architecture.md`、`CONTEXT.md`、`docs/pitfalls.md`；另告知「模板可能处于为取基线而回滚的中间态，判据是 `grep vendor/chartjs web/templates/*.html`」
- **轮次**：第 1 轮

## 审查者原文

## Standards 轴

- **建议** — `docs/pitfalls.md:98`：新条目写「首页 `renderMainChart()` 与 `macro`/`macro_cn` 的 `renderChart()` 在 `window.__chartFailed || !window.Chart` 时显示『图表加载失败』降级文案」，但 `web/static/macro.js:435` 实际只判 `if (!canvas || !window.Chart)`，从未读 `__chartFailed`（读该标志的是 `web/static/macro_cn.js:521` 与 `web/static/app.js:762`）。行为上等价（`__chartFailed` 只可能伴随 `window.Chart` 缺失），但这条是「坑记录」，描述与代码不符；将来有人想在宏观页依赖 `__chartFailed` 分流会按文档写出不生效的代码。建议把这句拆成三页各自的真实判据（macro 页 = `!window.Chart`）。

- **建议** — `docs/architecture.md:138`：十一期决策行仍写「Chart.js 走 CDN，加载失败图区降级」，而同文件 `docs/architecture.md:186` 已被本次改成「自托管于 `web/static/vendor/chartjs/`（2026-11-06 起不再走 CDN）」。同一份文档内对同一依赖给出相反事实，读者按 138 行会以为 CDN 仍在用。建议在 138 行补「（2026-11-06 起改为自托管，见依赖边界）」。

- **仅记录** — `docs/frontend-structure.md:17` 的「静态资产」行仍写「`style.css` 1 份 + 业务 JS 6 份 + 共享插件 1 份 + SVG 素材 6 个」，未计入本次新增的 2 个 vendored JS（218 KB）；同文档 §2 文件表（`docs/frontend-structure.md:46-60`）与 §11.1 vendored 表（`docs/frontend-structure.md:347-351`，仅 liquid-glass）也没有 chartjs 段。这与既有结构一致（liquid-glass 同样只在 §11 单列），但按该表盘点静态资产会漏掉两个第三方运行时文件。

- **仅记录** — `tasks/2026-11-06-vendor-chartjs/plan.md` 的「相关文件 / 预估 diff 范围」未列 `docs/architecture.md`，实际改了 1 行（内容正确、且是本次改动所必需）。AGENTS.md Working Rules 把 `plan.md` 当实施契约（「实施由执行者子 agent 做，它只认 `plan.md`」），实际文件范围比计划多 1 个。

- **仅记录** — `web/static/vendor/chartjs/chart.umd.min.js` 末尾是 `//# sourceMappingURL=chart.umd.js.map`，`.map` 未入库 ⇒ 开着 devtools 时会多一个同源 404（不影响出图）。另该文件首行是 jsdelivr 的 `Skipped minification…` 头（即 jsdelivr 转写版，非 npm tarball 原始字节），与 `web/static/vendor/chartjs/README.md` 记录的来源 URL 一致，但与「包内 LICENSE.md」这类 npm 侧描述混在一起；升级比对时应按 README 的「从上面两个 URL 原样下载」来，别拿 npm 字节比对。

- **仅记录** — `scripts/verify/verify_ui.py:4931` 的断言名仍是 `"Chart.js CDN 正常"`（该文件不在本次 diff 内，断言内容 `m["chartFailed"] is False` 仍然正确且应继续绿），但语义已被本次改动改掉，红/绿的报错文案会误导排查方向。

## Spec 轴

- **建议** — `scripts/verify/verify_offline_assets.py:164`（配合 `:126`）：`/macro` 与 `/macro/cn` 的「canvas 上有 Chart 实例」判据实际经由页面取数链路，上游没数据时页面会**合法地**不出图，而脚本会把它报成 `canvas 上没有 Chart 实例` 并退出 1 —— 即「自托管资源没取到」与「上游没数据」两类失败被合并。具体触发链：`web/static/macro.js:920` 用 15 s 客户端超时取 `/api/macro`，失败/超时走 `:931 state.macro = {}` ⇒ `:435` 之后的 `:437 showChartFail("数据暂缺")`，canvas 上无实例；服务端 `web/app.py:762` 在 `data/macro.json` 的 symbol 序列与 `load_macro_stocks()` 不一致（改过 `MACRO_STOCKS` 或 `config.json` 的 `macro.stocks`）或快照构建抛异常时会 `:773` 回退实时 Yahoo 取数，403/超时即返回空 trend。当前仓库快照（`data/macro.json`，4 symbols，1257 点）与默认一致，所以现在不会红；一旦有人改宏观标的配置，这个门禁就会以「图表资源失败」的措辞变红。建议把页面自身的降级文案（`#chart-main-empty` / `#macro-chart-fail` / `#cn-chart-fail` 的 `textContent`）读进失败信息，并在起服后先对 `/api/macro` 发一次请求预热，使 A1/A2 判资源、实例缺失带上数据原因。

- **建议** — `scripts/verify/verify_offline_assets.py:133`：轮询的提前退出口 `if state["chart"] and state["failed"]: return state` 不可达 —— `window.__chartFailed` 只由 Chart.js 的 `<script onerror>` 置位（`web/templates/index.html:62`、`web/templates/macro.html:31`、`web/templates/macro_cn.html:30`），而该情形下 `window.Chart` 必为 `undefined`，条件恒假，注释「已是确定失败态，无需等超时」的意图没有落地。后果：回退到 CDN（或两个静态文件 404/损坏）时每个「页面 × 视口」用例都白等 `CHART_TIMEOUT = 20.0`（`scripts/verify/verify_offline_assets.py:52`），6 组 ≈ 2 分钟才吐出结果，正是这条门禁最需要快速变红的场景。可改为 `if state["failed"]: return state`。

## 审查者明确未判断的

- 没有重跑 `scripts/verify/verify_offline_assets.py` / `verify_ui.py` / `pytest`（派发方要求避免抢资源），因此「脚本当前退出码是否 0」「`tests/` 是否全绿」两条验收标准未判定；只核对了它们所依赖的代码路径与数据前提（`data/macro.json`、`data/marketpulse.db` 均存在且新鲜）。
- 两个 vendored JS 只核对了版本 banner（`Chart.js v4.4.1` / `chartjs-plugin-zoom v2.0.1`）、字节数（205,399 / 12,854，与 plan 一致）、尾部完整性（均正常收尾，无截断）与许可证文本（两份 MIT），**未**与上游做逐字节比对。
- `chartjs-plugin-zoom` 的 UMD 全局分支依赖 `window.Hammer`（`_web/static/vendor/chartjs/chartjs-plugin-zoom.min.js`:7，`ChartZoom=t(e.Chart,e.Hammer,...)`），仓库未加载 hammerjs；这是改动前走 CDN 时完全相同的行为（同一文件），未进一步判断 pinch/pan 是否曾经可用。
- 审查开始时工作区模板处于中间态（3 个模板短暂回滚为 CDN 版本）；按派发方指示等待后重读，`web/templates/{index,macro,macro_cn}.html` 均已是同源版本（`grep -rn "vendor/chartjs" web/templates/*.html` 三条命中），故未把中间态计入任何发现。

## 逐条处理

| # | 审查者发现（原文摘要） | 处理 | 依据 |
|---|---|---|---|
| 1 | `docs/pitfalls.md:98` 声称三页都判 `__chartFailed \|\| !window.Chart`，`macro.js:435` 实际只判 `!window.Chart` | 改 | 该句拆成三页真实判据并注明「行为等价但别在宏观页依赖该标志」；`macro.js:435` 复核确认只判 `!window.Chart`。重跑 `grep -n "macro.js:435" docs/pitfalls.md` 命中新句 |
| 2 | `docs/architecture.md:138` 与同文件 `:186` 对 CDN/自托管给出相反事实 | 改 | 138 行补「（**2026-11-06 起改为自托管** `web/static/vendor/chartjs/`，见下方「依赖边界」）」，保留该行其余历史描述 |
| 3 | `docs/frontend-structure.md` 静态资产口径未计入 2 个 vendored JS | 改（部分） | 「静态资产」行补 `vendored 第三方运行时` 两个目录及体积；**未**新增 §11.x 表格 —— vendored 第三方在本文档一律只在 §11 单列（liquid-glass 同款口径），为 chartjs 再造一节属重复结构 |
| 4 | `plan.md` 的相关文件/预估范围未列 `docs/architecture.md`，实际多改 1 文件 | 改 | `plan.md` 的「相关文件」补 `docs/architecture.md` 与 `scripts/verify/verify_ui.py` 两条并注明「实施中追加」及理由 |
| 5 | `chart.umd.min.js` 尾部 `sourceMappingURL` 指向未入库的 `.map`；首行是 jsdelivr 转写版 banner | 不改 | vendored 文件**禁改写**（`web/static/vendor/chartjs/README.md` 与 `web/static/vendor/liquid-glass/` 同纪律），为消 404 去改第三方字节反而破坏「原样入库」；README 已把来源写成 jsdelivr URL 并说明「升级按该 URL 原样下载」，比对的参照与入库字节一致 |
| 6 | `verify_ui.py:4931` 断言名仍写 `Chart.js CDN 正常` | 改 | 文案改为 `Chart.js 可用（自托管，v4.4.1）`，判据 `m["chartFailed"] is False` 未动 |
| 7 | `verify_offline_assets.py` 把「资源没取到」与「上游没数据」合并报错，建议读页面降级文案 / 预热 `/api/macro` | 改（部分） | 采纳「读页面降级文案」：`STATE_JS` 采集 `.chart-empty / .mac-fail / .mac-empty` 的可见文本，实例缺失时拼进失败原因（实测输出见下）。**不采纳**「起服后预热 `/api/macro`」：门禁测的是用户真实冷路径，预热会把「上游冷启超时」这一档次失败人为掩盖掉；分类已由降级文案解决，另加预热只降低门禁的判别力 |
| 8 | `_wait_chart` 的提前退出口 `chart and failed` 恒假，红时每例白等 20s | 改 | 改为 `if state["failed"]: return state` 并就地注释为何旧条件恒假。实测反证：把 `chart.umd.min.js` 临时改名后整轮 **4.3s** 出 18 条红（原 ~2 分钟），并把 6 行 `页面降级文案：…` 带出来；改名还原后复跑 `ALL PASSED（6 组）` EXIT=0 |

## 审查者明确未判断的（处理说明）

- 「脚本退出码 / pytest 是否全绿」——由主线程实跑补齐：`verify_offline_assets.py` → `ALL PASSED（6 组）` EXIT=0；`pytest tests/ -q` → `880 passed, 12 warnings`。
- 「vendored JS 未与上游逐字节比对」——按 jsdelivr 原样下载，`README.md` 记录来源 URL、首行 banner 版本与字节数；未做 npm tarball 比对（确认：两者本就不是同一份字节，见 #5）。
- 「hammerjs 缺失是否影响 pinch/pan」——改动前后是同一个文件、同样的缺失状态；本次不引入新行为，也不扩大范围（`wheel`/`pan` 需 `ctrl` 修饰键，触屏手势本就未启用）。
- 「审查期间的模板中间态」——已确认为执行者取基线所致，最终态三条 `vendor/chartjs` 命中，未计入发现。

## 结论

1 轮结束：**Critical 0 条**，应改项全部落地（4 改 / 1 部分改 + 说明 / 1 不改 + 反证），验证已重跑（离线自包含门禁 6 组绿、pytest 880 通过、`verify_ui` 709 PASS / 1 条既有临界 `CS-8b`）。无阻塞项。
