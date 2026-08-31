# MarketPulse 二十二期 Journal — 趋势图数据密度优化

## 目标

按架构师计划精修 `web/templates/index.html` 的 `renderLineChart`，修正四个真实前端缺陷（D1–D5），不改动后端数据源/计算逻辑、不改变 7D/30D/90D 业务行为、零新依赖、2×2 布局与 340px 高度不动。

## 改动文件清单

仅 `web/templates/index.html`（全部位于 `renderLineChart` 或相邻纯函数）：

1. **D2 去虚构点**（核心）：删除 `let lastVal = null` 与 fill-forward 分支；null 日改为 `pts.push({ x: date, y: null, rawVal: null })`。Chart.js v4 默认 `spanGaps: false` → 断线，语义诚实，不虚构数据。
2. **D1 平滑度**：`tension: 0.15` → `0.08`。
3. **D3 X 轴标签**：ticks.callback 由 `String(tradingDates[index]).slice(8)`（纯日，跨月歧义）改为解析 `"YYYY-MM-DD"` → `"M/D"`（`Number(month)+"/"+Number(day)`，去前导零）；`maxTicksLimit: 6` 保留。
4. **D5 Hover**：`pointHoverRadius: 5` → `6`；新增 `pointHoverBorderWidth: 2`。
5. **D4 最新点**：`pointRadius` 末点 `4` → `3`。
6. **Tooltip 准确性补丁（计划外，必须）**：D2 让 null 日进入 tooltip 路径，`null - 100 === -100`（JS 数值强制）导致原 label 回调输出伪造的 `-100.00%`。两处修复：
   - `fmtPct(v)` 增加 `|| isNaN(v)` 守卫（防御性）；
   - label 回调在 `rv == null || ctx.parsed.y == null` 时直接返回 `label + " —"`，跳过涨跌幅计算。
   实测：null 日 → `黄金 ETF（GLD） —`；真实点 → `黄金 ETF（GLD） 3748.10 (+0.00%)`。

`web/app.py`、`style.css`、`src/*`、`tests/*` 零改动。

## 验证结果

- **后端契约回归**：`venv/Scripts/python -m pytest tests/ -q` → **324 passed, 0 failed**（8 个 matplotlib tight_layout / Starlette 弃用警告，与本次无关）。
- **浏览器实测（8001 端口，新进程规避 Jinja2 启动缓存 + `page.setCacheEnabled(false)` 硬刷新）**：
  - 4 张图 `tension` 全为 `0.08`；`pointHoverRadius=6`、`pointHoverBorderWidth=2`；末点 `pointRadius=3`，其余 `0`。
  - X 轴标签采样 `7/21 / 7/27 / 7/31 / 8/6 / 8/12 / 8/18 / 8/24 / 8/31`（跨 7–8 月，无歧义），`maxTicksLimit=6` 保留。
  - 各序列渲染点数：美股 29、A 股 30、波动率 29、另类 30（完整交易日），与计划实证一致。
  - `chart-gld-btc` 含 1 个真实 null 日（`dataLen=30, nullCount=1`）→ 该日断线、tooltip 显示 `—`，无伪造涨跌幅。
  - 未触发 `window.__chartFailed`（Chart.js CDN 正常加载）。
- **截图**：`charts-grid` 区域已截屏（vision 代理超时未能目视复核，但上述程序化探针已逐条确认配置与 tooltip 行为）。

## 遇到的问题

1. **Jinja2 启动期缓存**：模板改动必须新起 uvicorn 进程（或硬刷新）才生效；复用旧进程会误判改动未生效。本次每次修改后均重启 8001 进程 + `setCacheEnabled(false)` 重载。
2. **端口占用**：首次 `taskkill` 旧 PID 后新进程仍报 `10048`，因旧进程子进程未释放；需在 `netstat -ano` 中定位真正 LISTEN 的 PID 再 kill。
3. **Tooltip 伪造 -100%**（计划未预见）：D2 断线后，原 label 回调对 null 点算 `null-100=-100` 输出 `-100.00%`，违反「Tooltip 数据准确性」约束。已就地修复（见改动 6）。这是本期唯一超出 plan.md 修改清单的改动，但其动机正是满足 PRD 同一条约束。

## 下次注意什么

- 任何把数据显式置 `null`（断线/缺口）的前端改动，必须同步排查 tooltip/label 回调中对 `parsed.y` 的算术运算，避免 `null - N` 这类 JS 数值强制产生伪造值。
- 计划「不动 tooltip 回调」的前提是数据无 null 进入该路径；一旦引入 null 断点，该前提失效，应以约束（准确性）为准做最小修正。
- 验证模板改动务必：(a) 新进程避开 Jinja2 缓存；(b) 浏览器 `setCacheEnabled(false)` 绕过 HTTP 缓存；(c) 用 `tab.evaluate` 直接读取 `Chart.getChart(canvas)` 的配置与 tooltip 回调做断言，比肉眼截图更可靠。
