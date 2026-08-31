# MarketPulse 诊断 — 概览表格隐藏功能不生效

> 日期：2026-08-31 · 任务：`tasks/2026-09-01-marketpulse-phase19/`

## 结论

**当前代码（HEAD `a3e1017`）无此 bug，隐藏逻辑正常生效。** 用户遇到的现象是**浏览器缓存了旧版页面**（2026-08-31 18:15 之前、无隐藏逻辑的版本）——旧版在取消全部选中时只显示「无选中指标」行、不隐藏 section，与报告现象完全吻合。

## 实测证据（2026-08-31 对运行中的服务 PID 38584 实测）

服务：`venv\Scripts\python.exe -m uvicorn web.app:app --host 0.0.0.0 --port 8000`（用户自启，PID 38584，CreationDate 2026-08-31 18:35:10）。

浏览器驱动（Chromium headless）操作 `http://127.0.0.1:8000/`，两条路径均验证：

| 操作 | 结果 |
|---|---|
| 初始加载 | 10 行全渲染，10 个 chip 全选中，section `display: block` |
| 点击「清空」按钮 | section `display: none`（inline style），0 行，4 个图表占位 ✓ |
| 逐个点击 10 个 chip 取消 | 行数逐次 9→0；**最后一个取消后** section `display: none` ✓ |

`renderOverview` 调用链验证：chip `change` → `syncSelection()` → `renderOverview(state.latest)` → `rows.length === 0` → `section.style.display = "none"`。图例 onClick 与「清空」按钮走同一个 `syncSelection()` 入口，路径等价，无独立风险点。

## 根因分析

### 直接原因：浏览器缓存旧版 HTML

1. **git 时间线**（`web/templates/index.html`）：
   - `881bc09` 2026-08-31 18:15 —「概览表格为空时隐藏整个section（不显示空表格）」：rows 为空时 `section.style.display = "none"`（此前是 `tbody.innerHTML = '无选中指标'`，即不隐藏——**正是用户报告的现象**）。
   - `a3e1017` 2026-08-31 18:35 —「修复概览表格隐藏选择器（用closest精准定位）」：`document.querySelector(".card")` → `document.getElementById("overview-body").closest("section")`（`.card` 是通用类，首个匹配在当前 DOM 恰为概览 section，旧选择器碰巧有效；改为 closest 防模块顺序调整）。
2. **服务响应无缓存控制头**：`curl -D - http://127.0.0.1:8000/` 只返回 `date / server / content-length / content-type`，**无 `Cache-Control`**。浏览器对无显式缓存头的 GET HTML 采用启发式缓存——用户浏览器若在 18:15 前打开过页面（或缓存了旧响应），刷新（F5）仍可能命中旧 HTML，加载旧 JS（无隐藏逻辑）。
3. **服务端本身无问题**：Jinja2 `Environment` 未显式关闭 `auto_reload`，模板随文件变化重读；实测服务返回的 HTML 含 `section.style.display` 隐藏逻辑（浏览器实测行为正确即证明）。

### 排除项（prompt 中列的候选原因）

| 候选原因 | 判定 |
|---|---|
| `closest("section")` 选错元素 | 排除。`#overview-body` 的 tbody 位于模块 1 `<section class="card">` 内，实测选中正确（隐藏生效） |
| renderOverview 未被调用 | 排除。逐 chip 取消时行数实时变化，证明每步都调用了 |
| display 被其他代码覆盖 | 排除。无其他代码写 section 样式；CSS `.card` 无 `!important`；实测 inline style 生效 |
| **浏览器缓存问题** | **确认。这是根因** |

## 修复方案

### 立即（用户侧，无需改码）

- 硬刷新清除页面缓存：`Ctrl+F5` / `Ctrl+Shift+R`（或 DevTools → Network → Disable cache 后刷新）。

### 根治（服务端，建议实施）

- `web/app.py` 的 `/` 端点给 HTML 响应加 `Cache-Control: no-cache`（页面每次请求都重验证，杜绝旧模板残留）：

  ```python
  from fastapi.responses import HTMLResponse  # 已有

  @app.get("/", response_class=HTMLResponse)
  def index() -> HTMLResponse:
      template = _TEMPLATES.get_template("index.html")
      resp = HTMLResponse(template.render())
      resp.headers["Cache-Control"] = "no-cache"
      return resp
  ```

  说明：`/api/*` JSON 端点数据每日变化，同样建议加 `no-cache`，但概览隐藏问题只要求页面本身；改动范围最小化时先只改 `/`。

### 可选（防御，不必须）

- 静态资源 `style.css` 由 `app.mount("/static", StaticFiles(...))` 服务，默认带 `ETag`/`Last-Modified`，浏览器会做条件请求，无残留问题，无需处理。

## 复现验证方式（供后续回归）

```bash
# 起服
venv/Scripts/python -m uvicorn web.app:app --port 8000
# 浏览器打开 http://127.0.0.1:8000/ 后执行：
#   document.querySelectorAll("#symbol-filter label.chip").forEach(l => l.click())
#   → 最后一个 chip 点击后，getComputedStyle(document.getElementById("overview-body").closest("section")).display === "none"
```

## 风险与后续

- 若用户在别的浏览器/设备复现，优先怀疑该设备缓存而非代码——先硬刷新。
- 若实施 no-cache 头，注意 `web/app.py` 的 `test_api_*` 测试断言的是响应体/状态码，加头不影响既有测试（`test_web` 相关若有响应头断言需核对，本项目暂无）。
- 本次为纯诊断，未改动任何源码文件；工作区保持干净（`git status` 无变更）。
