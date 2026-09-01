# 任务日志：修复深色/浅色模式切换按钮 Bug

日期：2026-09-01

## 目标
按 `plan.md` 修复两个确认的回归缺陷，仅改 `web/templates/index.html`，CSS 不动：
1. FOUC 闪烁（主题应用太晚，body 末尾才切浅色）
2. localStorage 无异常保护（极端环境顶层脚本崩溃、整页卡「加载中…」、按钮死亡）

## 改动文件清单
- `web/templates/index.html`（唯一改动；`web/static/style.css` 未动）

### 改动 1 — 防 FOUC 预应用脚本（修复 1）
在 `<head>` 的 `<link rel="stylesheet">` **之前**插入内联脚本，CSS 生效前同步设置 `data-theme="light"`：
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
body 末尾原有 `applyTheme(getTheme())` 保留（负责按钮图标同步），两处幂等不冲突。

### 改动 2 — localStorage try/catch 防御（修复 2）
- `getTheme()`：`try { return localStorage.getItem('mp-theme') || 'dark'; } catch (e) { return 'dark'; }`
- 点击处理器：`try { localStorage.setItem('mp-theme', next); } catch (e) {}`（失败降级为会话内切换，不崩页）
- head 预应用脚本已自带 try/catch（改动 1 内）。

未触碰 Bug 3/4/5（修复方案明确本次不修：死代码路径或 UX 权衡）。

## 验证结果
- `venv/Scripts/python -m pytest tests/ -v` → **363 passed, 0 failed, 8 warnings**（warnings 为既有 matplotlib tight_layout / Starlette 弃用提示，与本次无关）。
- `git diff --stat`：`web/templates/index.html | 17 insertions(+), 3 deletions(-)`，仅 3 处精准改动。
- 浏览器实测（FOUC / 持久化 / file:// 极端环境）需人工在 Chrome DevTools 完成；本环境无法代跑浏览器交互，已按 plan 留待用户验证。

## 遇到的问题
无。编辑过程中 edit 工具对裸 body 行自动加 `+` 前缀的警告为工具提示，实际内容落盘正确（已二次 read 核对三处改动）。

## 下次注意什么
- 前端主题脚本必须 head 预应用防 FOUC；localStorage 任何访问必须 try/catch——顶层脚本任意一行抛异常都会杀死整块 `<script>`（含后续 fetch / 事件绑定 / 渲染）。
- 可复用规则建议后续追加到 `docs/pitfalls.md` / `AGENTS.md`（本任务用户要求停下审阅，未代写）。

## 后续 / 待办（非本次范围）
- Bug 3：切换时图表缩放/平移状态随 destroy 丢失（UX 权衡，plan 建议不做）。
- Bug 4：renderBarChart 硬编码深色涨跌色（死代码，启用柱状图时改读 CSS 变量）。
- Bug 5：折线 COLORS 双主题共用 + 白点边框在浅色下不可见（纯观感）。
