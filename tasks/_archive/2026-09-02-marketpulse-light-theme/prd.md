# PRD：MarketPulse Web 看板浅色皮肤

## 目标

为 `web/` 模块的单页看板添加浅色（Light）主题，与现有深色（Dark）主题并存，用户可通过顶栏按钮手动切换，偏好持久化到 `localStorage`。

## 背景

当前 `web/static/style.css` 全局使用 CSS 变量（`:root`）定义深色配色，所有颜色通过 `var(--xxx)` 引用。深色主题适合暗光环境，但在白天/明亮环境下对比度不足、可读性差。

## 需求

### 功能需求

| # | 需求 | 说明 |
|---|------|------|
| F1 | 浅色配色方案 | 在 CSS 中定义 `[data-theme="light"]` 选择器，覆盖 `:root` 中的所有颜色变量 |
| F2 | 主题切换按钮 | 在顶栏（`.topbar`）右侧添加切换按钮（☀️/🌙 图标），点击切换 `data-theme` 属性 |
| F3 | 持久化偏好 | 切换后将主题存入 `localStorage`，页面加载时读取并应用，避免闪烁 |
| F4 | 默认主题 | 默认深色（与当前一致），不改变现有用户体验 |
| F5 | 图表颜色适配 | Chart.js tooltip/axis/grid 颜色需随主题变化（通过 CSS 变量或 JS 读取当前主题） |
| F6 | 响应式兼容 | 浅色主题在移动端/平板端表现正常 |

### 非功能需求

| # | 需求 | 说明 |
|---|------|------|
| NF1 | 零后端改动 | 纯前端实现，不修改 `web/app.py` 或任何 Python 文件 |
| NF2 | 最小 diff | 仅修改 `web/static/style.css` 和 `web/templates/index.html` |
| NF3 | 不引入新依赖 | 不引入第三方 CSS 框架或 JS 库 |
| NF4 | report_card.html 不变 | 日报图片模板保持深色（截图产物，不受主题切换影响） |

## 浅色配色方案

**设计风格：Apple 风格**——干净白底、#f5f5f7 浅灰卡片、极细边框、柔和文字层级。参考 macOS/iOS 的系统浅色模式。

| 变量 | 深色（当前） | 浅色（Apple 风格） |
|------|-------------|-------------|
| `--bg-primary` | `#0b0e14` | `#ffffff` |
| `--bg-elevated` | `#11161f` | `#f5f5f7` |
| `--bg-hover` | `#11161f` | `#ececec` |
| `--border` | `#1f252d` | `#d2d2d7` |
| `--text-primary` | `#e6edf3` | `#1d1d1f` |
| `--text-secondary` | `#8b949e` | `#86868b` |
| `--text-muted` | `#4a525c` | `#aeaeb2` |
| `--green` | `#3fb950` | `#34c759` |
| `--red` | `#f85149` | `#ff3b30` |
| `--blue` | `#58a6ff` | `#007aff` |
| `--orange` | `#d29922` | `#ff9500` |
| `--purple` | `#bc8cff` | `#af52de` |

设计要点：
- 背景纯白 `#ffffff`，非纯白灰（如 GitHub 的 #f6f8fa）
- 卡片区用 Apple 标志性浅灰 `#f5f5f7`（非白色卡片，有层级感）
- 边框用 `#d2d2d7`（Apple 系统灰色，极柔和）
- 涨跌颜色用 Apple 系统色（绿 `#34c759`、红 `#ff3b30`），比深色版更鲜艳
- 蓝色主色 `#007aff`（Apple 标准蓝）
- 文字三级：标题 `#1d1d1f`（近黑）、正文 `#86868b`、辅助 `#aeaeb2`

## 涉及文件

| 文件 | 改动 |
|------|------|
| `web/static/style.css` | 新增 `[data-theme="light"]` 变量块；按钮样式 |
| `web/templates/index.html` | 顶栏添加主题切换按钮；JS 添加切换逻辑 + localStorage 读写；Chart.js 颜色动态读取 |

## 不改动的文件

- `web/app.py`（后端零改动）
- `web/templates/report_card.html`（图片模板保持深色）
- `src/*`（所有 Python 源码）
- `data/*`、`reports/*`、`alerts/*`

## Chart.js 适配方案

Chart.js 的 tooltip 背景色、axis tick 颜色、grid 颜色在 `index.html` 的 JS 中硬编码。方案：

1. 在 JS 中添加 `getThemeColors()` 函数，读取当前 `data-theme` 返回对应颜色映射
2. `renderLineChart` / `renderBarChart` 中引用该函数获取颜色
3. 切换主题时调用 `syncSelection()` 重建图表（已有重渲染机制）

## 验证

1. 打开看板，确认默认深色主题与改动前一致
2. 点击切换按钮 → 变为浅色，所有文字/背景/边框/表格/图表正确
3. 刷新页面 → 浅色主题保持（localStorage 持久化）
4. 再次切换回深色 → 正常
5. 移动端视口（≤480px）浅色主题无异常
6. 运行现有测试 `venv/Scripts/python -m pytest tests/ -v` 确认无回归
