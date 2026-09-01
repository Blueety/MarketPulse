# MarketPulse 二十五期 Journal — 美股去重 + 浅色皮肤

## 目标
按 plan.md（D1-D4）实施：① `daily_report.py` 在 `append_history` 前加美股去重门（判定集 GSPC+IXIC，排除 MOVE 浮点抖动；混合日整条跳过，PRD 字面）；② web 看板加浅色主题（`:root.light` + `html.light` 类 + `localStorage["mp-theme"]`）；③ 新增 6 条测试（既有断言零改动）；④ 文档同步。

## 改动文件清单
- `daily_report.py`：`_US_GATE = ("gspc","ixic")` + 纯函数 `_is_us_duplicate_day(history, record)`；`main()` 在 `append_history` 前加门（跳过则仅记日志）。零后端变更，不动 `src/`、`web/app.py`、快照/回测/脚本。
- `web/static/style.css`：`:root.light` 变量覆盖块（深浅仅颜色变量，涨跌色不变）+ `:root.light .card { background: var(--bg-elevated); }` + `.topbar-right` / `.theme-toggle`（复用 range-bar 透明/边框/hover 范式）。
- `web/templates/index.html`：`<head>` 最前预应用脚本（防 FOUC，包 try/catch）+ topbar 右上分组与 `🌙/☀️` 切换按钮 + `setTheme(light)`（切 `html.light` 类 + 写 `localStorage` + 更新图标）+ `DOMContentLoaded` 绑定与图标初始化。
- `tests/test_phase25.py`：新增（纯逻辑 ×4 + 接线 ×2）。
- `docs/architecture.md` / `docs/pitfalls.md` / `docs/commands.md`：关键决策表 + web 易错点 + 验证要点同步。

## 验证结果
- `pytest tests/test_phase25.py -v`：6 passed（纯逻辑：同值/异值/空历史/混合日；接线：重复日跳过 load_history 仍 1 条、变动日追加 2 条）。
- 全量 `pytest tests/ -q`：**382 passed**（仅既有 matplotlib tight_layout / starlette 弃用告警，无失败、无回归）。
- 浏览器（uvicorn `:8002` 另起未缓存端口）：`document.styleSheets` 含 `:root.light` 规则；初始深 `rgb(11,14,20)`、点击切 `html.light` + `localStorage["mp-theme"]=="light"` + 浅 `rgb(245,245,245)` + 图标 `🌙`；刷新保持；再点回深 `rgb(11,14,20)` + `☀️`。三态 + 持久化全部通过。

## 遇到的问题
1. **edit 锚点漂移导致重复块**：第二处替换误把去重门插入到错误位置（删除了 `report_path = save_report(...)` 行），且遗留一份无条件的 `record = {...}; append_history(record)` 旧块，造成两个 record 块并存——门判 True（跳过）后仍被旧块无条件追加，测试 `test_dup_day_skips_append` 失败（history 变 2 条）。通过直接 `eval` 复现（gate 返回 True 却仍追加）+ 读源码定位，删去重复块与多余 `report_path` 行，恢复单门结构。
2. **headless 浏览器缓存 style.css**：初次在 8001 验证时 `html.light` 类已切换但 body 背景仍是深色，看似 `:root.light` 不生效；实为浏览器缓存了旧 `style.css`。换端口 8002（不同 origin 强制重新拉取）后用 `tab.evaluate` 查 `document.styleSheets` 含 `:root.light` 规则证伪，主题三态正常。

## 下次注意什么
- **edit 多行替换**：优先整体 `write` 重写或严格用唯一文本锚点；同文件多处定点修改前先 `grep` 真实行号，切勿凭已偏移的行号盲改（pitfalls 通用条已载）。
- **web 静态/模板改动验证**：一律另起未缓存端口（8001/8002）规避 Jinja2 模板缓存 + 浏览器静态缓存；断言用 `tab.evaluate` 读 computed style / `document.styleSheets`，不依赖截图（本机无视觉模型）。
- **去重语义边界**：混合日（D2）A 股/BTC 当日数据不写 history 是 PRD 明示取舍（日报/context 当日仍完整）；真正平盘日会被跳过（与周末同语义）；已有 08-30 类重复行靠 90 天滚动淘汰，不迁移。
