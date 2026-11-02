# 计划：MarketPulse Web 看板浅色皮肤（Apple 风格）

## 目标

为 Web 看板添加 Apple 风格浅色主题，用户可通过顶栏按钮切换，偏好持久化到 localStorage。

## 涉及文件

| 文件 | 改动 |
|------|------|
| `web/static/style.css` | 新增 `[data-theme="light"]` 变量块 + 切换按钮样式 |
| `web/templates/index.html` | 顶栏添加切换按钮；JS 添加主题切换逻辑 + Chart.js 颜色动态读取 |

## 不改动的文件

- `web/app.py`（后端零改动）
- `web/templates/report_card.html`（图片模板保持深色）
- `src/*`、`data/*`、`reports/*`、`alerts/*`

## 分步实施

### 步骤 1：CSS — 添加浅色变量块

在 `style.css` 的 `:root` 块之后，新增 `[data-theme="light"]` 选择器，覆盖所有颜色变量：

```css
[data-theme="light"] {
  --bg-primary: #ffffff;
  --bg-elevated: #f5f5f7;
  --bg-hover: #ececec;
  --border: #d2d2d7;
  --text-primary: #1d1d1f;
  --text-secondary: #86868b;
  --text-muted: #aeaeb2;
  --green: #34c759;
  --red: #ff3b30;
  --blue: #007aff;
  --orange: #ff9500;
  --purple: #af52de;
}
```

**验证**：CSS 语法无误，无新增变量遗漏。

### 步骤 2：CSS — 添加切换按钮样式

在 `style.css` 末尾添加主题切换按钮样式：

```css
/* 主题切换按钮 */
.theme-toggle {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  width: 32px;
  height: 32px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s ease;
  flex-shrink: 0;
}
.theme-toggle:hover {
  color: var(--text-primary);
  border-color: var(--blue);
}
```

**验证**：样式文件语法正确。

### 步骤 3：HTML — 顶栏添加切换按钮

在 `index.html` 的 `<header class="topbar">` 内，`<span class="subdate">` 之前插入：

```html
<button class="theme-toggle" id="theme-toggle" title="切换主题">☀️</button>
```

### 步骤 4：JS — 主题切换逻辑 + localStorage 持久化

在 `index.html` 的 `<script>` 块开头（`const COLORS = ...` 之前）添加：

```javascript
// === 主题切换 ===
function getTheme() {
  return localStorage.getItem('mp-theme') || 'dark';
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'light' ? '🌙' : '☀️';
}
// 页面加载立即应用（避免闪烁）
applyTheme(getTheme());
```

在 `DOMContentLoaded` 事件监听器开头添加按钮点击事件：

```javascript
document.getElementById('theme-toggle').addEventListener('click', function() {
  const next = getTheme() === 'dark' ? 'light' : 'dark';
  localStorage.setItem('mp-theme', next);
  applyTheme(next);
  // 重建图表以更新硬编码颜色
  if (state.history) renderCharts(state.history);
});
```

### 步骤 5：JS — Chart.js 颜色动态读取

当前 `renderLineChart` 和 `renderBarChart` 中有硬编码颜色（tooltip 背景 `#161b22`、文字 `#e6edf3`、grid 颜色 `rgba(48,54,61,...)` 等）。

添加一个辅助函数获取当前主题颜色：

```javascript
function themeColors() {
  const dark = getTheme() === 'dark';
  return {
    tooltipBg: dark ? 'rgba(22, 27, 34, 0.95)' : 'rgba(255, 255, 255, 0.95)',
    tooltipTitle: dark ? '#e6edf3' : '#1d1d1f',
    tooltipBody: dark ? '#e6edf3' : '#1d1d1f',
    tooltipBorder: dark ? '#30363d' : '#d2d2d7',
    axisTick: dark ? '#8b949e' : '#86868b',
    gridLine: dark ? 'rgba(48, 54, 61, 0.08)' : 'rgba(0, 0, 0, 0.06)',
    gridLineBar: dark ? 'rgba(48, 54, 61, 0.25)' : 'rgba(0, 0, 0, 0.1)',
  };
}
```

然后在 `renderLineChart` 的 `options.plugins.tooltip` 和 `options.scales` 中，将硬编码颜色替换为 `themeColors()` 的对应字段。同理处理 `renderBarChart`。

**涉及替换的具体位置**：
- `renderLineChart` 第 311-315 行（tooltip backgroundColor/titleColor/bodyColor/borderColor）
- `renderLineChart` 第 341 行（x 轴 ticks color）
- `renderLineChart` 第 352 行（y 轴 grid color）
- `renderLineChart` 第 356 行（y 轴 ticks color）
- `renderBarChart` 第 393-397 行（tooltip 颜色）
- `renderBarChart` 第 410-411 行（x 轴 grid/ticks 颜色）
- `renderBarChart` 第 420 行（y 轴 ticks color）

### 步骤 6：验证

```bash
cd D:\AGENT\MarketPulse
venv\Scripts\python -m pytest tests/ -v
```

- 确认无回归
- 手动打开看板测试：默认深色 → 点击切换 → 浅色正确 → 刷新保持 → 再切回深色

## 风险和回退

| 风险 | 缓解 |
|------|------|
| Chart.js 颜色切换后图表不更新 | 切换时调用 `renderCharts(state.history)` 重建图表 |
| 浅色下某些文字看不清 | 所有文字颜色均通过 CSS 变量覆盖，无硬编码遗漏即可 |
| localStorage 写入失败（隐私模式） | `getTheme()` 兜底返回 `'dark'`，不影响功能 |
| 移动端按钮太小 | 按钮 32×32px，Apple HIG 最小点击区域 44×44pt 内可接受 |

回退：删除 `[data-theme="light"]` 块 + 切换按钮 + 相关 JS，恢复原状。
