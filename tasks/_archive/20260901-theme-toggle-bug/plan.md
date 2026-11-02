# 排查报告：深色/浅色模式切换按钮

> 诊断性质，未修改任何代码。日期：2026-09-01

## 结论先行

主切换链路（点击 → localStorage 持久化 → `data-theme` 属性 → CSS 变量切换 → 图标翻转 → 图表重建）**逻辑上是通的**，不存在"点击完全无响应"级别的故障。真正的可见问题有两个：

1. **FOUC 闪烁（最可能是用户感知的"有问题"）**：保存了浅色主题的用户每次加载/刷新页面，都会先以深色渲染、再切到浅色——闪一下。根因是主题应用脚本位于 `</body>` 末尾，而 CSS 深色默认值先行生效。
2. **localStorage 无异常保护**：存储访问被浏览器拒绝时（file:// 打开、隐私模式禁存储等），顶层 `applyTheme(getTheme())` 抛异常，**整个内联脚本块死亡**——页面卡「加载中…」、按钮无响应、所有渲染失效。

另有 3 个次要/潜在问题（见下）。排查过程通过 git 历史确认：当前实现是"实现 → 撤回 → 重新实现"的产物，**重新实现丢失了原版的防 FOUC 脚本与 try/catch 防御**，属回归缺陷。

## 涉及文件

- `web/templates/index.html`（主 HTML + 内联 JS）
- `web/static/style.css`（主题 CSS 变量）
- 不涉及 `web/app.py` / `src/*` / 测试（25 期约定浅色主题纯前端，测试注明"浏览器实测覆盖"）

## Bug 清单与根因分析

### Bug 1（确认，高）：FOUC 闪烁 — 主题应用太晚

- 现状：`applyTheme(getTheme())`（index.html 第 108 行）在 body 末尾的 `<script>` 中执行。CSS 深色 `:root` 默认值（style.css 第 2-17 行）在 head 中先行解析生效，浏览器首帧按深色渲染，body 解析完才切浅色。
- 证据链：git 历史 `6633ecf revert: 撤回浅色皮肤改动(保留美股去重)` 撤回的**原版**在 `<head>` 里有预应用脚本：
  ```js
  (function () {
    try {
      if (localStorage.getItem("mp-theme") === "light") {
        document.documentElement.classList.add("light");
      }
    } catch (e) {}
  })();
  ```
  重新实现（`ba8eb6c`/`85a9dc7`/`a71e57f`）改为 `data-theme` 属性方案，**但 head 预应用脚本没带回来**。`docs/architecture.md` 25 期条目明确记载「index.html 加预应用脚本（防 FOUC）」——文档描述的是原版，当前代码是回归。
- 放大因素：HTML 带 `Cache-Control: no-cache, no-store, must-revalidate`（第 9-11 行），每次刷新强制重取资源，闪烁每次必现。
- 表现：用户以为主题没记住 / 切换"坏了"。

### Bug 2（确认，中）：localStorage 无异常保护 — 极端环境整页脚本崩溃

- 现状：`getTheme()`（第 100-102 行）直接 `localStorage.getItem`，无 try/catch；脚本顶层立即调用 `applyTheme(getTheme())`。点击处理器（第 661 行）`localStorage.setItem` 也无保护。
- 原版对比：原版 `setTheme` 用 `try { localStorage.setItem(...) } catch (e) {}`，head 脚本整体 try/catch；重新实现**全部丢失**。
- 触发场景：Chrome 下 `file://` 直接打开模板抛 `SecurityError`；隐私模式/禁用存储同理。此时顶层抛异常 → 同一 `<script>` 块内后续所有代码（COLORS、渲染函数、fetch、事件绑定）全部不执行 → 页面静态「加载中…」、按钮死亡。
- 降级场景：存储写入被拒（不抛异常但静默失败）→ 点击有效但刷新后回深色，表现为"主题没记住"。

### Bug 3（确认，低）：切换时图表重建丢失缩放/平移状态 + 数据未就绪时图表不即时更新

- 现状：点击处理器 `if (state.history) renderCharts(state.history)`（第 665 行）——destroy 全部 4 张图重建。`renderCharts` → `renderGroup` → `charts[id].destroy()`，Chart.js zoom 插件记录的缩放/平移状态随实例销毁丢失。
- 数据未加载完成（`state.history === null`）时点击：本次不重建；数据到达后 `renderCharts` 执行，`themeColors()` 读 localStorage（已更新）→ 最终颜色正确。**无功能错误**，仅存在"点击后图表区颜色延迟生效"的感知窗口与缩放状态重置的 UX 缺陷。

### Bug 4（潜在，低）：renderBarChart 硬编码深色涨跌色

- 第 428 行 `bg.push(s.change_7d >= 0 ? "#3fb950" : "#f85149")`——GitHub 深色绿/红，浅色主题下与 Apple 色板（#34c759/#ff3b30）不一致。
- 现网不可见：当前 `GROUPS` 全部 `type: "line"`，`renderBarChart` 为死代码；`themeColors().gridLineBar` 同样未实际生效。若将来启用柱状图需一并修复（建议读取 CSS 变量或扩展 themeColors 增加 green/red 字段）。

### Bug 5（潜在，极低）：折线 COLORS 双主题共用 + 白点边框

- 10 条序列颜色（`COLORS` 常量）深/浅主题完全相同，浅色下偏暗色系观感；`pointBorderColor: "#fff"`（第 310 行）白底上不可见。纯观感，非故障。

### 排除项（已核查，非问题）

- `data-theme` 属性 + `[data-theme="light"]` 选择器：`document.documentElement` 即 `<html>`，属性选择器特异性 (0,1,0) 与 `:root` (0,1,0) 相同，靠后定义胜出 → 变量覆盖正常生效。
- 点击后 CSS 变量即时切换（背景/表格/文字/状态圆点全变）→ 主链路正常。
- 时序：点击处理器先 `setItem` 再 `renderCharts`，重建时 `themeColors()` 读到新主题 → 无时序 bug。
- 移动端按钮可见性：`.topbar` flex 三子项，按钮 `flex-shrink: 0`，480px 媒体查询下可见、无遮挡。
- 无 `[data-theme="dark"]` 块：暗色走 `:root` 默认，行为正常。
- 图标 emoji `☀️`/`🌙`：Windows 10（用户环境）Segoe UI Emoji 正常渲染。
- 注意：CSS 定义了 `.topbar-right`（style.css 第 71 行）但 HTML 未使用该包裹层——`subdate` 在 space-between 布局下居中，属布局观感问题，与主题故障无关。

## 修复方案（按优先级）

### 修复 1：恢复防 FOUC 预应用脚本（治本，改 index.html）

在 `<head>` 的 `<link rel="stylesheet">` **之前**插入内联脚本（CSS 尚未生效时同步设置属性，首帧即浅色）：

```html
<script>
  (function () {
    try {
      if (localStorage.getItem("mp-theme") === "light") {
        document.documentElement.setAttribute("data-theme", "light");
      }
    } catch (e) {}
  })();
</script>
```

body 末尾现有 `applyTheme(getTheme())` 保留（负责按钮图标同步），两处幂等不冲突。

### 修复 2：localStorage 存取加 try/catch 防御（改 index.html）

对齐原版 `setTheme` 风格：

- `getTheme()` 内 `try { return localStorage.getItem('mp-theme') || 'dark'; } catch (e) { return 'dark'; }`
- 点击处理器内 `try { localStorage.setItem('mp-theme', next); } catch (e) {}`（失败降级为会话内切换，不崩页）
- head 预应用脚本已有 try/catch（修复 1）

### 修复 3：图表切换行为（可选，改 index.html）

- 最小改动：保留 `if (state.history)` 守卫不动（无功能错误）。
- 若在意缩放状态丢失：在 destroy 前用 `charts[g.id].getZoomLevel()` 记录、重建后 `setZoom` 恢复——成本高收益低，建议**不做**，在文档标注该行为即可。

### 修复 4：renderBarChart 颜色（暂缓）

死代码路径，当前不触发。待有柱状图需求时改为读取 CSS 变量：
`getComputedStyle(document.documentElement).getPropertyValue('--green').trim()`。

## 实施步骤

1. 改 `web/templates/index.html`：head 插入防 FOUC 脚本（修复 1）+ localStorage try/catch（修复 2）。
2. `web/static/style.css` 不动（CSS 本身无缺陷）。
3. 手动验证（见下），通过后跑既有测试套件确认零回归。

## 验证命令

```bash
# 1. 启动看板
venv/Scripts/uvicorn web.app:app --port 8000

# 2. 浏览器实测（Chrome DevTools，Network 面板勾选 Slow 3G 放大闪烁窗口）
#    - 首次访问：默认深色，点按钮 → 切浅色，图标变 🌙，图表重渲染为浅色主题
#    - 刷新页面：全程无深色闪烁（首帧即浅色）→ 验证修复 1
#    - 刷新后主题保持浅色 → 验证持久化
#    - 再点按钮 → 切回深色，刷新无异常

# 3. 极端环境：file:// 直接打开 web/templates/index.html
#    - 页面不报白屏错误、按钮可点（fetch 失败属预期，其余脚本存活）→ 验证修复 2

# 4. 回归
venv/Scripts/python -m pytest tests/ -v
```

## 风险与后续

- 改动纯前端、零后端影响，25 期「浅色主题纯前端」约束保持。
- Bug 3/4/5 建议记录到 `docs/pitfalls.md` 或需求 backlog，本次不修（Bug 4/5 现网不可见；Bug 3 为 UX 权衡）。
- 可复用规则（任务完成后建议追加 AGENTS.md/文档）：**前端主题脚本必须 head 预应用防 FOUC；localStorage 访问必须 try/catch，顶层脚本任何一行抛异常都会杀死整块脚本**。
