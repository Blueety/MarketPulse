# MarketPulse 二十期 Plan — Web 看板视觉升级

> 目标：首页从「普通 SaaS / Admin Dashboard」升级为现代、专业、紧凑的金融市场终端（Bloomberg / TradingView 的信息密度与数据感 + Apple 的克制与层级）。
> 约束：不动 app.py / src / daily_report / tests 的 API 契约；只改 `web/templates/index.html` + `web/static/style.css`；涨跌色体系沿用；无构建步骤，Railway 兼容。

## 待确认决策

| # | 决策点 | 推荐 | 理由 | 备选 |
|---|---|---|---|---|
| D1 | 市场概览形态 | **保留可排序表格**，数字放大 + 表格扁平化 | 排序/过滤是既有交互（PRD 约束「不改变核心业务功能」）；数字字号 18-20px + tabular-nums 已足够终端感，零 JS 重构风险 | 改为指数单元格网格（更 Bloomberg，但丢失表头排序，需重写 renderOverview + 排序逻辑，风险高） |
| D2 | 卡片容器策略 | **去掉 .card 边框/背景，改为 hairline 分隔分区** | PRD 明确「减少不必要的卡片边界」；分区用 1px 底边线 + 标题间距即可分层 | 保留细卡片仅收敛内边距（改动小但「不像终端」） |
| D3 | 板块热度范围 | **保持仅领涨 Top5** | 最小改动；加领跌属新增展示（数据虽已由 /api/latest 返回 gainers+losers，但非本期要求） | 领涨/领跌双列对称展示（数据现成，改动约 10 行 JS + 表头，可作后续） |
| D4 | 图表高度/密度 | **canvas 桌面 260→220px，移动 200→180px** | 提高密度；90 点窗口 220px 仍可读 | 保持 260px（密度提升有限） |
| D5 | 概览「状态」列呈现 | **文本 + 前置圆点**，圆点颜色按关键词归类（休市→灰 / 获取失败→橙 / 异动→红 / 其余→绿） | 信息零损失；status 值来自 context 文本（如「连涨1日」），用 `includes` 前缀匹配三类 + 默认，脆弱度可控；测试用真实 context 值验证 | 纯文本不改（最保守，但状态视觉权重不足） |

## 影响分析

### 视觉系统方向

1. **排版层级（数字优先）**：
   - 全局数值启用等宽数字：`font-variant-numeric: tabular-nums;` + 数字字体栈 `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`，作用于概览数值、meta、涨跌幅、告警数值。
   - 概览表：收盘价 18px/600、涨跌幅 14px/600 带正负号着色；指数名 13px secondary；状态列次级小字 + 圆点。
   - 章节标题改为终端风：12px uppercase + `letter-spacing: 0.8px` + secondary 色（如 `市场概览 · 最新交易日`），替代当前 15px 常规标题。
2. **布局扁平化**：`.card` 去背景/边框/圆角 → `section + padding + border-bottom hairline` 分区；`.chart-box` 去掉内层边框背景，仅保留 chart-head 行 + canvas；topbar 收窄（padding 16→10px、标题 20→18px、日期右对齐）。
3. **颜色体系**：保留语义变量与 `.pos/.neg`（绿涨红跌约束不动）；加深 `--bg-primary: #0d1117 → #0b0e14`，边框 `--border: #2a3038 → #1f252d`（更淡 hairline）；删除 `--bg-card` 或仅作 hover 用。
4. **无横向溢出**：≤480px 概览表隐藏「状态」列、板块表隐藏「成交额」列（`.table-scroll` 的 overflow-x 保留兜底但不触发）；320px 视口验证 `scrollWidth <= innerWidth`。
5. **状态色克制**：WARN=橙、ALERT=红、休市=灰、加载失败=橙，均降饱和、不抢数字权重。

### 改动面

| 文件 | 动作 | 代码量 | 风险 |
|---|---|---|---|
| `web/static/style.css`（339 行） | 全量重构视觉层：变量 / topbar / 分区 / 概览表数字排版 / 图表扁平化 / 筛选条收敛 / 告警紧凑化 / 状态点 / 三档响应式 | ~380-420 行 | 纯 CSS，无逻辑风险 |
| `web/templates/index.html`（661 行） | 4 个 section 结构调整（去 card class、标题改 span 结构）；`renderOverview` 数值单元格加 `num` class + 状态圆点（~15 行 JS）；`renderAlerts` 行结构微调（~10 行） | ~+30/-25 行 | JS 仅渲染片段，不动状态机/事件 |
| `web/app.py` / `src/*` / `daily_report.py` | **零改动** | — | — |
| `tests/test_web.py` | **零改动**（`test_index_html` 仅断言 200 + content-type；`test_api_*` 锁 API 契约，与 DOM 无关） | — | — |

### 数据契约（消费方，不改）

- `/api/latest` → `{date, indices[{symbol,label,value,change_pct,status}], sector_heat{gainers,losers}}`
- `/api/history` → `{dates, series[{key,label,values,change_7d,raw}]}`
- `/api/alerts` → `[{level,symbol,date,type,state,current,last,change_pct,threshold,suggestion,report}]`

## 修改清单

### `web/static/style.css`

1. `:root` 变量：`--bg-primary:#0b0e14`、`--border:#1f252d`、`--bg-elevated`（hover）、新增 `--mono` 字体栈、间距/字号 token（`--fs-num: 18px` 等）。
2. `body`：`font-variant-numeric: tabular-nums`（或逐模块应用）；背景加深。
3. `.topbar`：收窄、标题 18px、日期次级色；可选加 1px 底部 hairline。
4. 卡片 → 分区：`.card` 去背景/边框/圆角，改 `padding: 20px 4px` + `border-bottom: 1px solid var(--border)`（末节无）；`.card h2` → 终端风小标题（12px uppercase + letter-spacing + secondary）。
5. 概览表：`.data-table` 收敛 padding（td 14px16px → 8px 12px）、`td.num` 等宽数字 + 字号阶梯（value 18px/600、change 14px/600）、`.status-dot`（6px 圆点 + 灰/橙/红/绿四态）、表头 11px uppercase。
6. 图表区：`.chart-box` 去边框背景（透明），chart-head 与 meta 同行 baseline；canvas 220px（移动 180px）；Chart.js legend/tooltip 字号已在 JS 内联，如需收敛同步改 `renderLineChart`/`renderBarChart` 的 options（仅字号，不动逻辑）。
7. 筛选条：range/group/chip 按钮收窄 padding、字号 12px、active 用主题蓝保持。
8. 告警：`.alert-card` 去背景仅左 3px 色条 + 紧凑行式（padding 10px 12px、字段 12px）。
9. 响应式：768px/480px 两档收敛间距 + 列隐藏规则（见 D5/溢出方案）。

### `web/templates/index.html`

1. 4 个 `<section class="card">` → `<section class="panel">`（或保留 card 名仅换样式，视 D2 结论）；标题改 span 结构（如需小标题内嵌副文本）。
2. `renderOverview`：数值单元格 `'<td class="num">'`；状态单元格加 `.status-dot` + 关键词归类（`includes("休市")→灰 / includes("失败")→橙 / includes("异动")→红 / 默认→绿`），文本原样保留。
3. `renderAlerts`：结构微调（badge 小一号、字段行合并），类名沿用 `.alert-card .alert/.warn` 契约。
4. 其余 JS（状态机 / 筛选 / 排序 / 图表渲染 / CDN 降级）**一字不动**。

## 执行步骤

1. 确认 `git status` 工作区干净；备份当前 `index.html` / `style.css`（`git stash` 或临时副本，供视觉对比）。
2. 重写 `web/static/style.css`（先变量 + 排版层，再逐模块：topbar → 分区 → 概览表 → 图表 → 筛选 → 告警 → 响应式）。
3. 修改 `web/templates/index.html` 结构 + `renderOverview` / `renderAlerts` 渲染片段。
4. 起服务：`venv/Scripts/python -m uvicorn web.app:app --port 8000`（TestClient 亦可），用 browser 打开验证。
5. 验证（见下）通过后跑 `venv/Scripts/python -m pytest tests/test_web.py -q` 回归。
6. `git diff --stat` 摘要 + 按 AGENTS.md 写 journal.md。

## 验证方法

- **测试回归**：`venv/Scripts/python -m pytest tests/test_web.py -q` 全绿（API 契约不破；`test_index_html` 仅断言 200/content-type，DOM 改动安全）。
- **视觉验证**（browser 驱动，桌面 1440×900 与移动 375×812 两视口）：
  1. 无横向滚动：`document.documentElement.scrollWidth <= window.innerWidth` 为 true（两视口）。
  2. 四模块全部渲染：概览 10 行、4 图、板块表、告警列表非「加载中」。
  3. 交互回归：7/30/90 天切换、组按钮隔离/恢复、chips 筛选、表头排序三态、图例点击、告警与板块数据加载。
  4. 截图前后对比：确认第一眼不再像 SaaS Admin 面板（数字主导、无卡片堆叠、密度提升）。
- **降级路径**：临时清空 `data/history.json`/`context/`/`alerts/` 重启看板 → 页面仍渲染占位文案不破版（验证后恢复文件）。
- **Railway 兼容**：无构建步骤、无新依赖、CDN 脚本原样，仅静态资源变更即满足。
