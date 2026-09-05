# 前端优化计划（2026-09-05，范围 C：清理 + 去重 + JS 抽离）

## 目标
在**不改变任何视觉与交互行为**的前提下：修复 3 个真实小 bug、清除约 100 行死代码、合并重复定义、统一图表配色来源（CSS 变量单一事实源）、把约 1000 行内联 JS 抽成独立 `web/static/app.js`、对齐 railpack.json 启动命令。不引入新依赖，不触碰 `web/app.py`、`src/*`、`data/*`。

## 背景排查结论（问题清单，已逐条对源码核实）
- **A 真实 bug**：
  1. `index.html:347` sparkColor 读不存在的 CSS 变量 `--muted`（实为 `--text-muted`），KPI sparkline 中性色恒走 fallback。
  2. `style.css:494 vs 508` 移动端 `.lede-val` 先 `16px !important` 又 `22px`，后者无效。
  3. `renderSector`（板块名/领涨股来自 AkShare 外部源）与 `renderAlerts` 字段拼接 innerHTML 未走 `escapeHtml`，与 `renderOverview`/`renderWatchlist` 不一致。
- **B 死代码（约 100 行）**：`renderBarChart`（L594-649，GROUPS 全为 line，从未调用）、`renderLineChart` 未用的 `const ctx`；style.css 死规则 `.theme-toggle`、`.status-dot`/`.dot-*`、`td.st`、`.row-dim`、`.col-status`、`.container`（两处）、`--fs-num`、`--purple`。
- **C 重复定义**：`.topbar-right` ×2（L77/L136）、`.icon-btn:hover` ×2（L145/L147）、`.lede-accent/pos/neg` border-left-color 两遍（L230-235）、`:focus-visible` 1px（L49）被 2px（L518）覆盖；`renderLineChart` 与 `renderWatchChart` 约 130 行近乎逐行重复（交易日轴/前向填充/dataset/options/zoom）；颜色三处维护（JS COLORS_LIGHT/DARK、CSS token、柱图硬编码 hex、themeColors 又一套 tooltip/axis 色）。
- **D 结构/工程**：约 1000 行 JS 内联在模板（node --check 整文件假阴性，pitfalls.md #39）；内联样式残留 2 处（L120 display:none、L130 height:220px!important）；`.shell` 闭合 `</div>` 游离在脚本之后（L1151）；`railpack.json` startCommand `uvicorn app:app` vs Procfile/railway.toml `uvicorn web.app:app`（根 app.py 转发兜底，双入口易漂移）。

## 涉及文件
- `web/static/app.js`（**新建**，承接内联 JS）
- `web/templates/index.html`（瘦身：删内联脚本、修结构、内联样式改 class）
- `web/static/style.css`（删死规则/去重/新增图表色 token）
- `railpack.json`（startCommand 对齐）
- 本目录 `plan.md` / `journal.md`

## 实施步骤

**第 0 步**：本计划存盘。

**第 1 步 — JS 抽离（纯机械搬运，先做，后续改动都在 .js 上做）**
- `index.html:144-1150` 的 `<script>` 内容原样搬到 `web/static/app.js`；head 的 FOUC 主题预置脚本与 CDN 图表库引用保留在模板内。
- `index.html` 末尾改 `<script src="/static/app.js"></script>`（位置仍在 body 末尾，执行时机不变）；游离 `</div>` 归位到 `</main>` 后。
- `/static` 已挂载，`app.py` 零改动。

**第 2 步 — A 级修复（在 app.js）**
1. `--muted` → `--text-muted`。
2. `renderSector`/`renderAlerts` 全字段补 `escapeHtml`。
3. 删 `renderBarChart` + 未用 `const ctx`。
4. 内联样式转 class：`#watchlist-section` 显隐改 `.hidden` 类（JS 3 处 classList 切换）；`#chart-watchlist` 高度移入 CSS。

**第 3 步 — B 级去重（在 app.js）**
1. 公共构建器：`buildTradingAxis(dates, series)`、`buildLinePts(s, dates, dateIndexMap)`、`buildLineDataset(s, color)`、`buildLineOptions()`（含 zoom 门控）；`renderLineChart`/`renderWatchChart` 变薄壳。
2. 颜色单一来源：style.css 新增 10 个序列色 token（`--c-gspc` 等，Light/Dark 两套，取值 = 现 COLORS_* hex）+ 7 个图表 UI token（tooltip/axis/grid）；JS `cssVar(name, fallback)` 读取（带 fallback 保底）；删 COLORS_LIGHT/DARK；柱图硬编码改读 `--green/--red`。主题切换重渲染机制已有，pitfall #48 不受影响。

**第 4 步 — style.css 清理**
- 删死规则（见上 B）；去重（见上 C）；`.lede-val` 冲突保留现生效的 16px !important + ellipsis，删无效 22px。

**第 5 步 — railpack.json**：`startCommand` → `uvicorn web.app:app --host 0.0.0.0 --port $PORT`。

**第 6 步 — 收尾**：`git diff` 核对；写 `journal.md`。

## 验证命令（每步实际运行）
1. `node --check web/static/app.js`（抽离后整文件语法校验；此前内联脚本会因 `</script>` 截断假阴性）。
2. `venv/Scripts/python -m pytest tests/ -v`（含 50 个 web 契约测试）。
3. 换新端口起看板（防缓存假阴性）：`venv/Scripts/python -m uvicorn web.app:app --port 8021`，手动冒烟：双主题下 4 组趋势图 + 自选股图渲染与配色一致、KPI sparkline、排序/筛选/范围切换、板块与告警表、移动端宽度。

## 风险与边界
- 行为保持不变是硬约束；`.lede-val` 保留现状生效值。
- `renderBarChart` 可从 git 历史找回。
- 不动项：W（sparkline 观感，等 09-07 数据复查）、告警 md 正则解析（生产端契约）、GLD ×10、CDN 策略（既定决策）。
- 不新增依赖；`web/app.py` 零改动。
