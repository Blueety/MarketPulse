# MarketPulse 十九期 Plan — Web 看板混合筛选模式

## 目标

为 Web 看板增加混合筛选交互：顶部全局筛选器（类别批量按钮 + 全选/清空 + 指标标签）与各图表图例点击双向同步，共享同一个 `state.selected` 单一数据源。纯前端改造，`web/app.py` 零改动。

现状核对（与 PRD「Current Understanding」的两处出入，已据实修正）：

- **图例当前是 `display: false`**（`renderLineChart` 的 `legend: { display: false }`），PRD 称"图例默认显示"不实——本期需开启图例并接管其 onClick。
- **`chart-gld-btc` 组无 `type` 字段**，实际走 `renderLineChart`（4 组全是 line 图），`renderBarChart` 是既有死代码，本期不动。

## 待确认决策

1. **类别按钮二次点击语义**（PRD 只定义"点击仅显示该类"，二次点击未定义）
   - 推荐：**toggle + 快照恢复**。点击未激活类别 → 快照当前选中集，仅保留该类；再次点击同一激活类别 → 恢复快照。理由：保留用户此前的图例/标签精细微调结果，提供自然的"返回"路径，代码量小（`state.selSnapshot` 一个字段）。
   - 备选：二次点击 = 全选（更简单，但丢失精细状态）；no-op（最贴近 PRD 字面，但用户只能靠"全选"返回）。
2. **历史请求策略：显隐是否仍走 `?symbols=` 服务端过滤**
   - 推荐：**前端不再传 `?symbols=`，`/api/history` 恒返回全量 10 序列；显隐纯客户端管理**（`dataset.hidden` + `chart.update()`）。理由：图例要能重新启用被隐藏的序列，该序列的 dataset 必须常驻图中——若按 selected 过滤掉，图例项随之消失，无法再点开，双向同步不成立（硬约束）。10 序列 × 90 点 payload 极小，无性能顾虑。`/api/history` 的 `symbols` 参数**保留**（向后兼容，既有 `test_api_history` 断言不动）。
   - 备选：维持 `?symbols=` 过滤 + destroy 重建——图例重启用不了，违反 PRD 双向同步，且违反"update() 而非 destroy()"性能约束。已否决。
3. **类别按钮 active 判定**
   - 推荐：**组内全部成员已选中即 active**（与 chips 的 `.on` 状态同构，`selected ⊇ group.keys`）。理由：用户隐藏 VIX 后波动率按钮应失亮，但额外选中其他类别指标时按钮不应闪烁；语义最直观。
   - 备选：`selected` 精确等于组集合才 active——用户跨类别多选时按钮失亮，状态闪烁感强，已否决。
4. **空组行为**（组内全部隐藏，如图例逐个关掉 3 个波动率指标）
   - 推荐：**沿用现有机制**——销毁该组 chart 实例、隐藏 canvas、显示「无选中指标」占位；图例随之消失，恢复只能走顶部标签。理由：与「清空」语义一致、复用 `chart-empty` 既有样式与 17 期占位逻辑；常驻空图渲染（保图例）需要保留空 y 轴网格，改动大且收益低。
   - 备选：组内全隐藏时保留空图与图例（可原地点开）——需处理 `chart.resize()` 与空数据集渲染，超出本期范围。若你要求"图例必须常驻"再采纳。

## 影响分析

核心设计：**显隐是纯客户端状态**。`state.selected` 仍是唯一数据源，驱动四路视图——图例（`dataset.hidden`）、顶部标签（chips `.on`）、概览表（既有过滤）、meta 行。数据获取只在首载/时间范围切换时发生。

- **类别批量切换**：新增 `.group-bar`（4 个类别按钮）。GROUPS 增加 `name` 字段作单一来源，`renderFilter()` 统一渲染按钮 + 全选/清空 + chips。点击 → 快照 + 改写 `state.selected` → `syncSelection()`。涉及 index.html（+25 行 JS）、style.css（+20 行）。
- **图例点击**：`renderLineChart` 开启 `legend.display: true`，深色主题 labels（`#8b949e` / `usePointStyle` / `boxWidth: 8`）；dataset 增加自定义字段 `key`；自定义 `onClick` 全权接管（**不调用 Chart.js 默认 toggle**，否则 state 与 hidden 双写不一致）：翻转 `state.selected` → `syncSelection()`。约 +20 行。
- **双向同步中枢 `syncSelection()`**（新函数，约 +35 行）：对每组——组内无选中 → destroy + 占位；有选中且 chart 存在 → 仅改 `dataset.hidden` + `chart.update()`（性能路径，无网络请求）；chart 不存在（首载/范围切换后/空组恢复）→ 用缓存的 `state.history` 重建（hidden 一并应用）。随后重渲染 meta（仅选中序列）、概览表（用缓存的 `state.latest`，`renderOverview` 内既有 selected 过滤 + 排序逻辑原样生效）、刷新按钮/chips 类。
- **全选/清空**：改走 `syncSelection()`，不再触发 `refresh()` 重新请求（payload 已在缓存中）。净删约 8 行。
- **时间范围切换保留筛选**：`refresh()` 重建 chart 时按 `state.selected` 应用 `dataset.hidden`，筛选状态天然保留。既有的 destroy 旧实例纪律（17 期 pitfall）仅在重建路径保留。
- **空图表占位**：复用既有 `.chart-empty`「无选中指标」机制，零新增。
- **移动端适配**：`.group-bar` 与 `.symbol-filter` 同纪律（flex-wrap + 间距收敛），style.css 768/480 两档补充。

涉及文件与量级：`web/templates/index.html` 约 +70/-15 行；`web/static/style.css` 约 +25 行；`web/app.py` **零改动**（API 契约、既有测试不动）。

## 修改清单

### web/templates/index.html

1. `GROUPS` 常量每条增加 `name` 字段（美股大盘 / A 股大盘 / 波动率 / 另类资产，与 h3 文案一致；PRD 的「另类」= 另类资产）。
2. 静态 HTML：`.symbol-filter` 上方新增 `<div class="group-bar" id="group-bar"></div>`（按钮由 JS 渲染，与 range-bar 同模式）。
3. `state` 增加：`history: null`（最近一次 `/api/history` payload）、`latest: null`（最近一次 `/api/latest` payload）、`selSnapshot: null`（类别点击前的 `Set` 快照）。
4. `buildQuery()`：去掉 symbols 拼接，只返回 `/api/history?days=` + `state.days`。
5. 新增 `syncSelection()`：见影响分析，为 chip / 类别 / 图例 / 全选清空四类交互的统一入口，**不发起网络请求**。
6. `renderFilter()`：渲染类别按钮（`data-group` 绑定 GROUPS 序号；active 判定按决策 3）+ 全选/清空 + chips；chips `change` 监听由 `refresh()` 改为 `syncSelection()`；全选/清空同改。
7. `renderLineChart`：`legend` 开启 + 深色主题 + 自定义 `onClick`（决策 2 前提：dataset 常驻，hidden 序列以划线样式保留在图例中，可点击恢复）；dataset 增加 `key: s.key`；图例 label 用 `s.label`（与 tooltip 一致）。
8. `renderCharts`：series 过滤条件去掉 `state.selected.has(s.key)`（隐藏交给 `dataset.hidden`，重建时按 selected 应用）；`renderMeta` 保持仅渲染选中序列。
9. `refresh()`：fetch 全量 history + latest → 写入 `state.history` / `state.latest` → 重建图表 + 概览表 + 板块；删除 `selected.size === 0` 跳过 fetch 分支（payload 恒全量，无此必要）。

### web/static/style.css

1. `.group-bar`：flex + `flex-wrap: wrap` + `gap: 8px` + `margin-bottom: 12px`；按钮复用 `.range-bar button` 视觉族（`--bg-hover` 底 / `--border` 边 / `--text-secondary` 字 / hover 蓝边）；`.active` 蓝底白字加粗。
2. 响应式两档（768 / 480）：按钮 padding 与字号收敛（参照 `.symbol-filter` 同款收敛），保证换行不溢出。

### web/app.py

不改。`symbols` 查询参数保留（前端不再使用，测试与向后兼容不受影响）。

## 执行步骤

1. `web/templates/index.html`：GROUPS 加 `name`；HTML 加 `.group-bar` 容器。
2. `web/templates/index.html`：`state` 加缓存字段；`buildQuery` 去 symbols。
3. `web/templates/index.html`：`renderLineChart` 开图例 + 自定义 onClick + dataset.key；`renderCharts` 调整过滤与 hidden 应用。
4. `web/templates/index.html`：新增 `syncSelection()`；`renderFilter` 渲染类别按钮、chips/全选/清空改调 `syncSelection`；`refresh` 写缓存、删空选分支。
5. `web/static/style.css`：`.group-bar` 样式 + 768/480 响应式。
6. 验证（见下）：pytest 回归 → uvicorn 起服 → browser 驱动逐条验证 PRD 清单 + 双向同步 + 移动端。
7. `git diff` 检查改动范围（应只含 index.html / style.css）；写 `tasks/2026-09-01-marketpulse-phase19/journal.md`。

## 验证方法

- **回归**：`venv/Scripts/python -m pytest tests/ -v` 全绿（app.py 未动，API 契约无回归；`test_api_history` 的 symbols 断言原样通过）。
- **起服**：`venv/Scripts/python -m uvicorn web.app:app --port 8000`，浏览器打开 `http://127.0.0.1:8000`。
- **browser 驱动逐条**（操作走 `tab.evaluate` + `await setTimeout` 等 fetch 回调后断言，17 期纪律）：
  1. 点击「波动率」类别按钮 → 仅波动率图有曲线，其余三图显示「无选中指标」占位；再点一次 → 恢复点击前状态（快照语义，若确认决策 1）。
  2. 波动率图点击图例 VIX → VIX 曲线消失（图例项划线）、顶部 VIX 标签变灰、meta 行与概览表不再含 VIX；再点图例 → 恢复。
  3. 顶部标签点击隐藏上证 → 对应图曲线消失、图例该序列同步划线（双向同步，方向 2）。
  4. 点击「全选」→ 全部恢复；「清空」→ 四图占位 + 概览表「无选中指标」。
  5. 切换 7/30/90 天 → 之前隐藏的序列保持隐藏（筛选状态保留）。
  6. 组合态：隐藏 VIX + 仅选 A 股 → 波动率按钮失亮、A 股按钮亮、其余灰。
  7. 移动端 viewport 390×844：`.group-bar` 换行不溢出、按钮可点击。

## 风险与注意

- **图例 onClick 必须全权接管**：Chart.js 默认 handler 会自行 toggle `dataset.hidden` 并 update——自定义 handler 里若仍走默认行为会与 `state.selected` 双写冲突；handler 内只改 state，再统一调 `syncSelection()`。
- **勿配 `labels.filter` 排除 hidden dataset**：图例能重新启用隐藏序列的前提是 hidden 序列的图例项常驻（4.x 默认以划线样式保留），这是双向同步成立的关键，不要"优化"掉。
- **zoom 插件 `limits.y: "original"`**：`chart.update()` 后 original 边界按当前可见序列重算，隐藏部分序列后缩放范围随之变化——低风险视觉细节，不影响功能，本期不处理。
- **空组恢复路径**：组内全隐藏 → chart 销毁、图例消失，恢复只能走顶部标签（决策 4 已确认）；若实施中发现用户强烈需要图例常驻，再评估空图渲染方案。
- **概览表排序不受影响**：`syncSelection` 复用 `renderOverview`（缓存 latest），`state.sort` 三态逻辑原样生效。
