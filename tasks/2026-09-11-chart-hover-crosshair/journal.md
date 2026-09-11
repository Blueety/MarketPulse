# Journal — 图表悬停水平参考线（Crosshair）

- 日期：2026-09-12 执行（plan.md 落款 2026-09-11）
- 角色：编码执行者（Phase 3 Step 3.6-3.7），按 `plan.md` 全步骤实施
- 开工前置：按 plan §0 先 `git log` 确认 `verify_ui.py` 最新版（玻璃化已落地、纹理任务已回退，
  `verify_ui.py` 回到 672 行基线 `27bfa58`），无并发编辑冲突后开工

## 目标

`#chart-main`（唯一实例 `charts.main`）增加悬停水平参考线：鼠标进入绘图区 → 全宽虚线跟随
鼠标纵向位置（Q2：取鼠标 Y，非数据点 Y）+ Y 轴端涨跌幅百分比气泡（Q3/Q4）；移出即消失。
零新增依赖，内联插件，不 `Chart.register`。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/static/app.js` | 改（826 → 896 行，唯一代码文件） | ① 抽出 `fmtAxisPct(value)` 顶层函数，`scales.y.ticks.callback` 改引用（单一事实来源）；② 新增内联插件 `hoverCrosshair`（`afterEvent`：mousemove/touchmove 取 Y + 1px 节流 + `chart.draw()` 手动重绘，mouseout/touchend/移出绘图区清除；`afterDatasetsDraw`：全宽虚线 + 轴侧百分比气泡，动态读 `yScale.position`，垂直钳制，写 `$crosshairLabel` 可测挂钩）；③ `new Chart(...)` 加 `plugins: [hoverCrosshair]` |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 扩展（672 → 760 行，零覆盖） | 补回 `import re`（随纹理回退被移除）；新增 `assert_crosshair(page)`（CS-1~CS-7，独立小 evaluate 片段，不进 MEASURE_JS）；`main()` 在 1Y 档之后调用一次 |
| `docs/pitfalls.md` | 追加 3 条 | R1 同 x 纵移不自动重绘 / R2 插件禁乘 DPR + DPR=2 取证法 / 内联插件挂载点与顶层 function 声明 |
| `tasks/2026-09-11-chart-hover-crosshair/journal.md` | 新增 | 本文件 |

## 验证结果（全部实际运行）

| 步骤 | 命令 | 结果 |
|---|---|---|
| C-1 红跑 | `verify_ui.py`（app.js 未改） | **EXIT=1，恰 4 条 FAIL**：CS-1/CS-2/CS-4/CS-7b（测插件行为本身）；CS-3/CS-5/CS-6/CS-7a 与全部既有断言 PASS |
| C-2~C-5 静态门 | `node --check web/static/app.js` | SYNTAX OK |
| 绿跑 | `verify_ui.py` | **ALL PASSED / EXIT=0**：CS-1~CS-7 全绿（8 条），既有断言零破坏，scrollHeight@1920=1216 ≤1240 |
| R2 取证 | `%TEMP%/verify_crosshair_dpr2.py`（DPR=2 + 禁 tooltip + 像素定位） | 预期位置 **63% 列**有虚线特征（PASS）、误乘 DPR 的 ×2 位仅 1%（无线）；`$crossY=128` vs 鼠标目标 128.2；气泡 `+2.2%` |
| 回归 | `pytest tests/ -q` | **459 passed**（无 Python 变更） |

## 遇到的问题

1. **plan 行号/规模漂移**：plan 写 verify_ui.py 387→400 行、`measure():174`、`main():229`；
   实际开工时是 672 行（玻璃化任务后续又扩过）、`measure():423`、`main():478`。按 plan §0
   的要求以开工时最新版为准接线，结构锚点（`check()`/`assert_viewport`/`main()`）不变。
2. **CS-7 拆成 a/b（与 plan 红跑预期的小偏差）**：plan 预期「CS-5~CS-7 红跑 PASS」，但 CS-7
   的「重建后仍带 crosshair」本身就是插件行为，红跑必 FAIL。处理：拆为 CS-7a（实例存活且唯一
   ——纯回归，红跑 PASS）+ CS-7b（新实例仍带插件——红跑 FAIL、绿跑 PASS），journal 记偏差。
3. **CS-1 取值点修正**：plan 写 `chart.options.plugins.hoverCrosshair`；实测内联插件登记在
   `chart.config.plugins`（`options.plugins` 是选项解析结果，未必含内联条目）。CS-1 两者都查、
   以 config 为准。已记 pitfalls。
4. **DPR=2 取证脚本第一版坐标系错误**：把 canvas 内坐标直接当视口位图坐标扫描，扫到顶栏/KPI
   区全是卡片边缘（hits 106..796 全是假阳性）。修正：`位图 = (rectTop/Left + canvas 内坐标) × 2`，
   并把盲扫改为「预期位置带内验证虚线 + ×2 bug 位验证无线」的双向证明。教训已并入 pitfalls R2 条。
5. **verify_ui.py 无 `import re`**：纹理任务回退把上一任务加的 `import re` 一并带走了；本次
   CS-4 需要 `re.fullmatch`，补回（本任务的三处 verify 改动均为纯增量，回退风险已消）。

## 下次注意什么

- Chart.js 插件绘制类需求：先想清楚「谁触发重绘」——激活元素集合不变时必须 `chart.draw()`。
- 插件坐标 = CSS 像素（chartArea/event.y），DPR 由 Chart.js 的 setTransform 处理，人不能乘。
- 断言 canvas 内容用 `toDataURL()` 前后比对 + `$hook` 可测变量；截图像素比对是最后手段，
  且必须换算 `rect + ×DPR` 两级坐标。
- plan 里的行号/规模只是写作时快照，接线一律以开工时 `git log` + 实读为准。
