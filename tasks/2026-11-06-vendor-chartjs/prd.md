# 手机端网页没有图表（Chart.js 走公网 CDN，移动网络取不到）

## 档位

- **档位**: `T2 — 12 文件（其中 4 个是 vendored 静态资源） / 0 调用方 / 行为有变 / 无覆盖测试 / 预估 80 行`

## Goal

手机浏览器打开看板时「市场趋势」卡恒为空白 + 「图表加载失败（离线 / CDN 不可达）」，因为 Chart.js 与 chartjs-plugin-zoom 从 `cdn.jsdelivr.net` 加载，国内移动网络取不到。把两个库 vendored 进 `web/static/vendor/chartjs/`，模板改吃同源静态资源，页面不再依赖任何第三方 CDN。

## 这一版要验证什么

- **假设**：移动端断图的唯一根因是第三方 CDN 不可达（而不是 Chart.js 版本 / 移动视口 / 皮肤脚本冲突）
- **值得继续的信号**：阻断 `cdn.jsdelivr.net` 后复现出 `window.Chart === undefined` + `__chartFailed === true` + canvas `display:none`（已实测，见 plan 闸门 A），改成同源资源后同一阻断条件下 3 个图页均有 Chart 实例
- **该停的信号**：同源资源加载后，阻断 CDN 仍然无图 ⇒ 假设错，回到根因排查

## Requirements

- 3 个出图页面（`/`、`/macro`、`/macro/cn`）的 Chart.js / zoom 插件全部改走 `/static/vendor/chartjs/…`
- 页面不再向任何第三方域发起子资源请求（断网/墙外不可达时图表照常渲染）
- 两个库的许可证文件随之入库（仓库是 PUBLIC）
- 新增静态资源登记 `web/app.py` 的 `_ASSET_FILES`，改动能换 `?v=` 指纹
- 保留既有降级链路（`window.__chartFailed` / `__zoomFailed` 与各页失败文案），不删不改语义

## 验收标准

1. Given 浏览器阻断 `*cdn.jsdelivr.net*`，When 加载 `/`、`/macro`、`/macro/cn`，Then 三页都满足 `window.Chart` 为真、`window.__chartFailed` 为假、对应 canvas 有 Chart 实例
2. Given 375×812 移动视口 + 同一阻断条件，When 加载 `/`，Then `#chart-main` 有实例且可见（`display` 非 `none`）
3. Given 正常网络，When 跑 `venv/Scripts/python scripts/verify/verify_offline_assets.py`，Then 退出码 0 且报告 3 页 × 2 视口全绿
4. Given 搜索 `web/templates/`，When 查 `cdn.jsdelivr.net`，Then 0 命中
5. Given 现有门禁，When 跑 `venv/Scripts/python -m pytest tests/ -q`，Then 全绿

## Out of Scope

- 不动 Chart.js 版本（保持 4.4.1 / plugin-zoom 2.0.1，与现网一致）
- 不引入 gzip 中间件（205KB 未压缩；如需再压另开任务）
- 不改任何图表业务逻辑（`app.js` / `macro.js` / `macro_cn.js` 零改动）
- 不改移动端布局/样式

## Not yet specified（雾区）

- 无

## Constraints

- vendored 文件禁止改写（与 `web/static/vendor/liquid-glass/` 同一纪律）
- 模板 head 里脚本顺序不变（chart.js → zoom → 业务脚本；`chart-crosshair.js` 仍必须在业务脚本之前）
- 不新增 Python 依赖

## Context Pointers

- `web/templates/index.html:57-61`（CDN 两个 script tag）
- `web/templates/macro.html:29-30`、`web/templates/macro_cn.html:28-29`
- `web/app.py:226-247`（`_ASSET_FILES` / `_asset_version`）
- `web/static/vendor/liquid-glass/`（vendored 先例：形如 `LICENSE-*.txt` + README 说明）
- `docs/frontend-structure.md:314`、`docs/pitfalls.md:98`（当前记录的是「走 CDN + onerror 降级」的旧事实）

## Testing Decisions

- **要测的 seam**: HTTP 层的页面自包含性 —— 阻断所有非 `127.0.0.1` 请求后页面仍能出图（真实浏览器 + 真实模板，不 mock）
- **好测试的标准**: 失败时能指出是哪一页哪个 canvas，不锁文案、不锁库版本号
- **同库先例**: `scripts/verify/verify_scroll_degrade.py`（独立起服 + Playwright + 断言，退出码非 0 判红）

## Risks

- 205KB 未压缩 JS 首次加载变慢（本地静态，无 CDN 缓存；比断图可接受）
- `_asset_version()` 对新增条目按文件取 mtime，必须写文件名而非目录（`vendor/chartjs`）

## 术语与决策

- **已排除的方案**: 保留 CDN + 同源兜底（两套代码路径、顺序不可控）；换第三方国内 CDN（换一个不可控的外部依赖）
- **刻意偏离常规的地方**: 无
