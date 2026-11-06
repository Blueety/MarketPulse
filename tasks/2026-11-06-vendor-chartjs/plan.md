# 实施计划 — Chart.js 自托管（手机端断图）

## 任务概要

- **档位**: `T2 — 12 文件（含 5 个 vendored 静态资源） / 0 调用方 / 行为有变 / 无覆盖测试 / 预估 80 行`
- **类型**: `bug-可复现`
- **目标**: 3 个出图页面的 Chart.js + chartjs-plugin-zoom 从 `cdn.jsdelivr.net` 改为同源 `/static/vendor/chartjs/`，消除移动端（国内网络取不到 jsdelivr）恒断图。
- **相关文件**:
  - `web/static/vendor/chartjs/chart.umd.min.js`（新增，205,399 B）
  - `web/static/vendor/chartjs/chartjs-plugin-zoom.min.js`（新增，12,854 B）
  - `web/static/vendor/chartjs/LICENSE-chartjs.txt`、`LICENSE-chartjs-plugin-zoom.txt`（新增，MIT）
  - `web/static/vendor/chartjs/README.md`（新增：来源 URL + 版本 + 禁改写）
  - `web/templates/index.html`（第 58-61 行为 CDN 两行）
  - `web/templates/macro.html`（第 29-30 行）
  - `web/templates/macro_cn.html`（第 28-29 行）
  - `web/app.py`（`_ASSET_FILES`，第 226-233 行）
  - `scripts/verify/verify_offline_assets.py`（新增验收脚本）
  - `docs/pitfalls.md`（第 98 行旧事实改写）、`docs/frontend-structure.md`（§表格静态资产行 + §9 第 7 条）、`AGENTS.md`（第 25 行脚本清单）
  - `docs/architecture.md`（实施中追加：第 138 行十一期决策行的「Chart.js 走 CDN」补日期更正，第 186 行「依赖边界」改为自托管 —— 同一文件内不能并存两条相反事实）
  - `scripts/verify/verify_ui.py`（实施中追加：1 处断言名 `Chart.js CDN 正常` → `Chart.js 可用（自托管，v4.4.1）`，只改文案不改判据）
- **验证命令**:
  - `venv/Scripts/python scripts/verify/verify_offline_assets.py`
  - `venv/Scripts/python -m pytest tests/ -q`
  - `venv/Scripts/python scripts/verify/verify_ui.py`（改动涉及 3 个模板 head，跑全量 UI 门禁）

## 步骤

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | 落 vendored 资源：两个 JS + 两个 LICENSE（已下载到 `web/static/vendor/chartjs/`，核对首行 banner 与字节数）+ 写 README（来源 `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js` 等、版本、MIT、禁改写） | `web/static/vendor/chartjs/*` | 下载不完整 → 语法错，运行期白屏 | `node -e` 不可用则用浏览器探针（步骤 4 的脚本即为验证）；`grep -c "Chart.js v4.4.1"` |
| 2 | 3 个模板 head：CDN `<script src>` 换成 `/static/vendor/chartjs/chart.umd.min.js?v={{ asset_v }}`（index 另有 zoom 插件同款），保留 `onerror="window.__chartFailed=true"` / `__zoomFailed` 与相对顺序 | `web/templates/{index,macro,macro_cn}.html` | 顺序错 → `plugins:[undefined]`，横线消失且不报错（已知坑） | `grep -rn "cdn.jsdelivr" web/templates` 零命中；浏览器探针 `window.Chart` 为真 |
| 3 | `web/app.py` 的 `_ASSET_FILES` 追加 `"vendor/chartjs/chart.umd.min.js"`、`"vendor/chartjs/chartjs-plugin-zoom.min.js"`（**必须是文件路径**，`_asset_version()` 按文件取 mtime） | `web/app.py` | 写目录名 → `stat()` 失败被 `if .exists()` 静默跳过 → 指纹不含该资源 | `venv/Scripts/python -c "import web.app as a; print(a._asset_version())"` 前后对比 |
| 4 | 新增 `scripts/verify/verify_offline_assets.py`：起本地服（复用 `free_port`/`wait_ready` 的写法）→ 对 3 个页面 × 2 视口（1440×900 / 375×812）**阻断所有非 127.0.0.1 请求** → 断言 `window.Chart`、`!window.__chartFailed`、页面指定 canvas 有 Chart 实例且 `display !== 'none'`；任一失败退出码 1 并打印哪页哪个 canvas | `scripts/verify/verify_offline_assets.py` | 阻断过宽（连 `127.0.0.1` 也拦）→ 假红 | 脚本前后各跑一次：现状红、修复后绿 |
| 5 | 文档与清单：`docs/pitfalls.md` 的「Chart.js CDN 降级」条目改写为「静态库一律自托管 + 依据」；`docs/frontend-structure.md` §9 第 7 条标记已解决；`AGENTS.md` 第 25 行 `scripts/verify/` 清单加入新脚本 | 3 个 md | 闸门检查文档里写的相对路径是否存在 | `sh scripts/check-gates.sh --staged` |
| 6 | 全量回归 + 收尾：pytest、verify_ui、`git diff` 复核范围 | — | verify_ui 需 Playwright/浏览器；本机 CDN 可用则不受影响 | 见上 |

## 测试 Seam

- **要测的 seam**: HTTP 自包含性 —— 真实浏览器 + 真实模板，**阻断一切第三方域请求**后页面仍能出图。测的是「页面不依赖外部 CDN」这个可观察事实，而不是模板里有没有某段字串。
- **公开接口是什么**: `GET /`、`GET /macro`、`GET /macro/cn` 三个 HTML 路由 + `/static/vendor/chartjs/*` 静态资源；浏览器断言读取 `window.Chart` / `window.__chartFailed` / `Chart.getChart(canvas)`。
- **错误与边界**: 任一页面失败 → 非 0 退出码 + 打印 `页面 / canvas / 失败原因`；阻断规则排除 `127.0.0.1` 与 `localhost`（否则连页面本身都拦掉，全部假红）；进程内起服，端口用 `free_port()`，结束后必关。
- **为什么选这个 seam**（而不是更浅的那个）: 更浅的做法是断言模板里没有 `cdn.jsdelivr` 字样 —— 那是源码文本测试，改个变量名/换别的 CDN 就漏，且无法证明「断网仍出图」。这个 seam 直接复现用户手机上的条件（第三方域不可达），失败信息落在「哪页哪个图表」。

## 修 bug 时必填

- **能变红的命令**: `venv/Scripts/python "%TEMP%/mp_cdn_probe.py"`（Playwright，390×844 移动视口 + `ctx.route("**cdn.jsdelivr.net/**", abort)`，读 `window.Chart` / `__chartFailed` / `#chart-main` 的 `display`）
- **已实跑的输出**（2026-11-06，修复前）:
  - `blocked: {"chart": false, "failed": true, "zoomFailed": true, "canvas": "none"}`
  - `ok     : {"chart": true, "failed": false, "zoomFailed": false, "canvas": "block"}`
  - 与用户手机截图一致（趋势卡空白 + 「图表加载失败（离线 / CDN 不可达）」）。
- **是否已最小化**: 是 —— 变量只有「jsdelivr 是否可达」，同视口下可逐次切换，结果稳定两态。
- **3–5 个排序假设**（每个带预测「若 X 是因，则改 Y 会让 bug 消失」）:
  1. 第三方 CDN 在移动网络不可达（已证实为主因）→ 预测：改成同源静态资源后，阻断 CDN 仍出图。
  2. Chart.js 版本与页面脚本不兼容 → 预测：若为真，同源加载后仍 `__chartFailed` 或实例报错；同源后实测可证伪。
  3. 移动视口下 canvas 高度塌成 0（`.chart-wrap` 高度未生效）→ 预测：若为真，桌面视口应正常而同视口 canvas 高度为 0；修复前桌面探针 `canvas: block` 已证伪（桌面同样依赖 CDN，断则同样空白）。
  4. 液态玻璃 `skin.js` 抢先操作 canvas → 预测：停用皮肤后仍空白；已由「桌面 OK / 仅断 CDN 空白」证伪。

## 不做什么

- 不动 `app.js` / `macro.js` / `macro_cn.js` 的业务逻辑与降级文案
- 不升级 Chart.js / plugin-zoom 版本
- 不引入 GZipMiddleware（205KB 未压缩可接受；需要再压另开任务并单测 `Content-Encoding`）
- 不改移动端布局、样式、断点
- 不新增 Python 依赖（验收脚本只用已有 Playwright）

## 预估 diff 范围

- 新增文件: `web/static/vendor/chartjs/`（5 个：2 JS + 2 LICENSE + 1 README）、`scripts/verify/verify_offline_assets.py`
- 修改文件: 3 个模板、`web/app.py`、`docs/pitfalls.md`、`docs/frontend-structure.md`、`AGENTS.md`
- 删除文件: 无

## 确认

- [x] 人已审阅计划（2026-11-06 批准：按计划全量实施）
- [x] 档位声明与实际文件范围一致
- [x] 文件范围合理
- [x] 没有遗漏测试
- [x] 测试 seam 已写入本节
- [x] 没有引入不必要依赖
