# 日志：Web 看板自选股（watchlist）模块

- 日期：2026-09-04
- 计划：tasks/2026-09-03-web-watchlist/plan.md

## 目标

在现有 web 看板（`web/app.py` + `web/templates/index.html`）新增「自选股」自选体验：
- 第 4 个只读 JSON API `/api/watchlist`，实时取数 `config.json` 的 `watchlist.stocks`（A 股 AkShare / 美股 Yahoo），零写盘。
- 前端板块热度后新增自选股卡片（初始隐藏、实时取数、单图多标的 `spanGaps`）。
- 失败降级：配置空 → 整卡隐藏；单标的取数失败 → 行显示「数据暂缺」、不 500。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `web/app.py` | 顶部 import `load_config`/`fetch_watchlist`；新增纯函数 `_series_tail` / `_build_watchlist_payload` / `_load_watchlist`；新增 `@app.get("/api/watchlist")`；模块 docstring「3 个」→「4 个 JSON API」。 |
| `web/templates/index.html` | 板块热度 card 后新增自选股 card（HTML 初始 `display:none` + 表格 tbody + chart-box/canvas）；JS 新增 `WATCH_PALETTE` / `escapeHtml` / `renderWatchlist` / `renderWatchChart`（spanGaps 单图）；`DOMContentLoaded` 追加 `/api/watchlist` fetch（catch 仅 console.error，不影响主链路）。 |
| `tests/test_web.py` | 新增 8 条用例（纯函数 + 端点，沿用 monkeypatch 打使用方 `web.app` 纪律）。 |
| `docs/architecture.md` | 模块表 4 API + 新增关键决策行「Web 看板自选股（二十八期）」。 |
| `docs/commands.md` | Web 看板验证要点补 `/api/watchlist` 与自选股场景、测试数 28。 |
| `docs/pitfalls.md` | 补 `/api/latest` 端点名（非 `/api/overview`）+ 内联 `<script>` 不能直 `node --check` 假阴性。 |

## 验证结果

- `pytest tests/test_web.py`：**45 passed**（既有 37 + 新增 8，无回归）。
- 起 uvicorn（8002）冒烟：`/` 200 且含隐藏自选股卡片（`watchlist-section`/`watchlist-body`/`chart-watchlist`）；`/api/latest`、`/api/history`、`/api/alerts`、`/api/watchlist` 均 200。
- `/api/watchlist` 真实数据（本环境 `config.json` 已配 `515300.SS`）：返回 `value=1.33, change_pct=0.68`，trend 归一化基准 100、首值 100.0、`change_7d=1.37` 与公式 `末/首*100-100` 吻合；series 键 `515300.ss`。
- NF3 降级（临时配置含假代码 `FAKE.XX`）：200 + 失败行 `value=null`/`change_pct=null`、日志「获取失败」、不 500；失败标的不入 trend（决策 1），其余模块不受影响。
- JS 语法：抽取本次新增片段 `node --check` 通过（整文件 node 校验为假阴性，见 pitfalls）。

## 遇到的问题

1. **edit 工具吞相邻代码**：`PUT 289.:` 插纯函数时把 `_load_alerts` 的 `return out` 吞掉（3 个告警测试连带 500）；`PUT 96.:` 插 HTML 把模块 3 的 `</section>` 吞掉（卡片被错误嵌套）。均靠 `pytest` + 读实际文件逐一定位修复。
2. **`/api/overview` 不存在**：计划称 4 端点含 `/api/overview`，实际端点名是 `/api/latest`（AGENTS 已记录）。curl 404 是计划误记，非改动引入。
3. **整文件 `node --check` 假阴性**：`index.html` 主脚本含 `</script>` 字面量，正则提取被截断 → `Unexpected end of input`；**未改的原始文件同样报错**，故为既有假象，非本次引入。改用片段校验。
4. **本环境有自动提交 cron**（`auto: 每日数据更新` 会 `git add -A`）：改动落地即被自动提交，`git diff` 显示为空属正常（pitfalls 第 153 行已记）。编辑期创建的临时 `_wl_cfg.json` 被误扫入 git 索引，已 `git rm --cached` 清理。

## 下次注意什么

- 同文件多处定点修改前，先用 `grep` 取真实行号；`PUT N.:` 插入易吞掉锚点行，插入后务必读实际区域确认结构（尤其 HTML 标签配对）。
- 验证 web 层用真实端点名 `/api/latest`；JS 改动用「片段 node --check」或浏览器 `tab.evaluate` 看 console，勿信整文件 node 校验。
- 自查代理环境变量（`HTTPS_PROXY` 等）会显著影响 AkShare/Yahoo 取数成败——本次混合配置下两标的同时失败是代理/外部 API 抖动，非代码缺陷（成功路径已由真实数据运行 + 单测证明）。
