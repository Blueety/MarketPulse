# MarketPulse 二十一期 Plan — 趋势图视觉优化

> 架构师计划（只读产出，未改任何文件）
> 日期：2026-09-01 ｜ 范围：`web/templates/index.html` + `web/static/style.css`，零后端改动

## 待确认决策

| # | 决策 | 推荐 | 备选 | 理由 |
|---|---|---|---|---|
| D1 | Legend 去留 | **隐藏 legend**（`display: false`），保留 `chart-meta` 头部作序列标识，删除 legend onClick 死代码 | 保留紧凑 legend、删 meta | meta 已显示「label + 30D 涨跌幅」，legend 纯重复；金融终端惯例无图例；指标切换已由 chips / 类别按钮全量承接，图例点击交互不丢失（`syncSelection` 走 `ds.hidden`，与 legend 解耦） |
| D2 | 画布高度 | **桌面 340px**；平板(≤768px) 260px；手机(≤480px) 220px | 桌面 320px | 220px 是「扁平」主因；PRD 区间 320-350，340 与 2×2 网格在 1440px 宽的观感最稳；移动端按比例收敛不破坏宽屏布局 |
| D3 | 平滑度 | `tension 0.35 → 0.15`，`borderWidth 2.5 → 2.0` | tension 0.2 | 0.35 过度平滑会掩盖真实拐点；0.15 保留轻微曲线感但忠实数据；线宽 2 更锐利，贴合终端感 |
| D4 | 末端点 | 半径 `3 → 4`，新增 `pointHoverRadius: 5`；不做发光/阴影 | 维持 3 | 末端点是「当前值」锚点，加大半径高亮符合终端惯例；约束禁止用阴影/渐变堆特效，仅加大半径不越界 |
| D5 | 轴与网格 | y 网格 alpha `0.25 → 0.12`；y ticks `maxTicksLimit: 5`；x ticks 字号 12→11 + `maxTicksLimit: 6` | 仅改网格色 | 弱化辅助元素、突出数据线本身；90 日窗口 x 轴 tick 密度收敛，避免拥挤（`autoSkip` 之外再设上限） |

默认按推荐执行；实施若需偏离，在 journal 中记录原因。

## 影响分析

### 改动面

仅两个前端文件，改动全部集中在既有渲染路径，无新增文件、无依赖变更：

- `web/templates/index.html`（约 12 行）：
  - `renderLineChart`（243-340 行）内 datasets 配置（tension / borderWidth / pointRadius / pointHoverRadius）与 options 配置（legend / scales）；
  - 删除 legend onClick 块（隐藏后为死代码）。
- `web/static/style.css`（约 4 行）：`.chart-box canvas` 高度 3 处媒体断点 + `.chart-head` 间距微调。

### 不变更

- 后端：`web/app.py` / `src/*` / `daily_report.py` / `snapshot_report.py` 零改动；`/api/history` `/api/latest` `/api/alerts` 契约不动。
- 功能：7/30/90 切换、指标筛选（chips / 类别 / 全选清空）、排序、缩放平移（ctrl+滚轮）、告警/板块模块均不动。
- 2×2 布局：`charts-grid` 的 `grid-template-columns: repeat(2, 1fr)` 不变。

### 风险与对策

1. **legend 隐藏后图例点击切换失效**：切换能力由 chips（`symbol-filter`）+ 类别按钮（`group-bar`）+ 全选/清空完全承接，`syncSelection` 仅依赖 `ds.hidden`，与 legend 无耦合。验证阶段需实际点击 chips 回归。
2. **Chart.js 画布高度**：高度由 CSS `!important` 控制（现行机制，`responsive: true` 下 Chart.js 写内联高度、CSS 覆盖），340px 生效方式与当前 220px 完全一致，无新机制。
3. **Jinja2 模板缓存 + 端口占用**（pitfall 二十期）：旧进程不反映模板改动，验证必须另起端口（8001）。
4. **测试不受影响**：已 grep 确认 `tests/` 无任何模板/图表配置断言（test_phase6a 等仅断言 API 数据契约），无需改测试。

### 代码量

- index.html：约 12 行修改 + 约 8 行删除（legend onClick）。
- style.css：约 4 行修改。

## 修改清单

### `web/templates/index.html`（仅 `renderLineChart` 函数内）

1. datasets 配置：
   - `tension: 0.35` → `0.15`
   - `borderWidth: 2.5` → `2.0`
   - `pointRadius` 回调：末端点 `3` → `4`
   - 新增 `pointHoverRadius: 5`
2. `options.plugins.legend`：`display: true` → `false`；删除整个 `onClick` 回调块（含注释「全权接管图例点击…」）
3. `options.scales.y`：
   - `grid.color`：`"rgba(48, 54, 61, 0.25)"` → `"rgba(48, 54, 61, 0.12)"`
   - `ticks` 增 `maxTicksLimit: 5`，`font.size: 12` → `11`
4. `options.scales.x.ticks`：`font.size: 12` → `11`，增 `maxTicksLimit: 6`

### `web/static/style.css`

1. `.chart-box canvas`：`height: 220px !important` → `340px !important`
2. `@media (max-width: 768px)`：canvas `200px` → `260px`
3. `@media (max-width: 480px)`：canvas `180px` → `220px`
4. `.chart-head`：`margin-bottom: 8px` → `6px`（压缩非数据元素）

## 执行步骤

1. 确认 `renderLineChart` 当前内容（已读：index.html 243-340 行；编辑前如有疑点重读该段）。
2. 修改 `web/templates/index.html` 上述 4 处（优先整体 read 后定点 edit；同文件多处修改先用 grep 取真实行号，防行号漂移）。
3. 修改 `web/static/style.css` 上述 4 处。
4. 另起端口启动看板（避免 8000 占用 + 模板缓存）：`venv/Scripts/python -m uvicorn web.app:app --port 8001`。
5. 浏览器验证（见下），含回归项。
6. `git diff` 检查改动范围，确认仅两文件、无后端/测试变更；写 journal.md。

## 验证方法

### 启动

```bash
venv/Scripts/python -m uvicorn web.app:app --port 8001
```

### 浏览器逐项验收（browser 工具，viewport 1440 宽起）

1. 四张图 `.chart-box canvas` 计算高度 ≈ 340px（`tab.evaluate` 取 `getBoundingClientRect().height`）。
2. 无 legend；`chart-meta` 头部正常显示「label + 30D 涨跌幅」。
3. 曲线仅轻微弯曲（tension 0.15）；数据点仅末端一个（其余 0），末端点半径 4。
4. Hover 曲线任一点：tooltip 清晰显示日期（title）与数值 + 涨跌幅（label）。
5. y 网格线明显弱化；x/y 轴 tick 数量收敛（90 日下 x 轴 ≤6 个、y 轴 ≤5 个）。
6. 四张图视觉比例一致（同高、同配置）。

### 功能回归

7. 7 / 30 / 90 切换正常（`range-label` 与图同步更新）。
8. chips 增删指标、类别按钮隔离/恢复、全选/清空、概览表与图表同步。
9. ctrl+滚轮缩放 / ctrl+拖拽平移仍可用（zoom 插件降级不受影响）。
10. 概览表排序三态、板块热度、告警记录模块正常。
11. 视口 1440px+ 无扁平；响应式断点（≤768 / ≤480）高度按比例生效。

### 收尾

- `git diff` 仅含 `web/templates/index.html` 与 `web/static/style.css`。
- 全部验收通过后按 AGENTS.md 写 `tasks/2026-09-01-marketpulse-phase21/journal.md`（含改动清单、验证结果、遗留项）。
