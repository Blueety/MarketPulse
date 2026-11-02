# MarketPulse 二十三期 Plan — 趋势图视觉精修

> 只改两个文件：`web/templates/index.html`（图表配置）+ `web/static/style.css`（图表容器样式）。不触碰后端、不新增依赖、不改 7D/30D/90D 逻辑、不重构图表。

## 现状（已核实）

- 四张折线图由 `renderLineChart`（index.html ~249 行）统一绘制，dataset 配置：`tension: 0.08` / `borderWidth: 2.0` / 末点 `pointRadius: 3` / `pointHoverRadius: 6` / `pointBorderColor: "#fff"`。四图天然共用同一配置，改一处即四图一致。
- Chart Header：`.chart-head`（style.css 160 行）`justify-content: space-between; align-items: baseline`——标题在最左、meta 被推到最右，中间空白随容器宽度拉大；h3 12px/600 vs meta 11px/600，层级接近但未统一。
- 曲线颜色唯一事实来源 `COLORS`（index.html 98 行，10 键 hex）。

## 待确认决策

1. **tension 取值**：推荐 `0.25`。0.08 几乎等同直线、无平滑效果；0.4+ 是强 spline（被 PRD 否决过）；0.25 是 Chart.js 文档中金融/时序图常用轻微值，保留局部拐点。备选 0.2（更保守）或 0.3（更柔）。
2. **Header 布局**：推荐 `justify-content: flex-start` + `gap: 12px`——meta 紧随标题成紧凑组，彻底消除 space-between 造成的无意义空白（现代金融产品 header 风格）。备选：保留右对齐、仅统一字号——不消除空白，不满足 PRD 字面。
3. **非交互不透明度**：推荐 `85%`（`#RRGGBB` + `d9` 后缀）——明显低于 hover 的 100%，视觉攻击性下降且仍清晰可读。备选 90%（更保守，对比弱）。
4. **最新数据点**：推荐 `2.5px`（当前 3px，「保留但缩小」）。备选 2px（更小，辨识度略降）。
5. **y 轴 grid 不透明度**：推荐 `0.12 → 0.08`（顺手项，属视觉噪音范畴，一行改动，不算增加装饰）。备选：不动。

## 影响分析

| 功能 | 方案 | 涉及文件 | 代码量 |
|---|---|---|---|
| 曲线平滑 | dataset `tension: 0.08 → 0.25` | index.html | 1 行 |
| 线宽克制 | `borderWidth: 2.0 → 1.8` | index.html | 1 行 |
| 非交互降噪 | `borderColor` 追加 `"d9"`（85% 透明）；新增 `hoverBorderColor: COLORS[s.key]`（hover 恢复全色）+ `hoverBorderWidth: 2.6` | index.html | 3 行 |
| 末点缩小 + hover 强调 | `pointRadius` 3 → 2.5；`pointHoverRadius` 6 → 7 | index.html | 2 行 |
| Header 布局 | `.chart-head` `space-between→flex-start`、`baseline→center`、`gap 8→12px` | style.css | 3 行 |
| Header 层级统一 | `.chart-meta` `font-size: 11px → 12px`；`gap: 6px 12px → 6px 8px`（紧凑） | style.css | 2 行 |
| y 轴 grid 微降 | `rgba(48,54,61,0.12) → 0.08` | index.html | 1 行 |

- 无后端改动、无新依赖、无测试改动（`tests/test_web.py` 仅断言 status/content-type，不触碰图表 JS）。
- 8 位 hex（`#RRGGBBAA`）为 Chart.js 4.x / Canvas 标准格式，`COLORS[s.key] + "d9"` 字符串拼接即可，不新增颜色表。
- 风险：hover 时线宽 1.8 → 2.6 有轻微跳动，属预期交互反馈；header 改 flex-start 后右对齐视觉消失，需浏览器确认观感。

## 修改清单

### `web/templates/index.html`（renderLineChart dataset 配置，~277-283 行）

```
tension: 0.08            → tension: 0.25
borderWidth: 2.0         → borderWidth: 1.8
borderColor: COLORS[s.key]        → borderColor: COLORS[s.key] + "d9"
+ hoverBorderColor: COLORS[s.key]
+ hoverBorderWidth: 2.6
pointRadius: 末点 3 → 2.5
pointHoverRadius: 6      → 7
```

y 轴 grid（~371 行）：`rgba(48, 54, 61, 0.12)` → `rgba(48, 54, 61, 0.08)`。

其余（pointBorderColor/pointBorderWidth/pointHitRadius/tooltip/x 轴/动画/zoom/隐藏逻辑）不动。

### `web/static/style.css`（~160-177 行）

```css
.chart-head {
  justify-content: space-between → flex-start;  /* meta 紧跟标题，消除无意义空白 */
  align-items: baseline → center;               /* 内部垂直居中 */
  gap: 8px → 12px;
}
.chart-meta {
  gap: 6px 12px → 6px 8px;                      /* 指标项间更紧凑 */
  font-size: 11px → 12px;                       /* 与 h3 同字号，同一视觉层级 */
}
```

`.chart-box h3`（12px/600）、canvas 高度 340px、`.charts-grid` gap 16px 保持。

## 执行步骤

1. 备份两文件（`cp` 到临时路径）。
2. 改 `index.html`：dataset 五处配置 + y 轴 grid，逐行 `edit`。
3. 改 `style.css`：`.chart-head` 三处属性 + `.chart-meta` 两处属性。
4. 启动 uvicorn（用 8001 端口，避开 8000 既有进程 + 模板缓存）。
5. 浏览器验证（见下）。
6. `git diff` 检查改动范围仅限两文件；写 journal.md + 提取规则到 docs/pitfalls.md。

## 验证方法

- `venv/Scripts/python -m uvicorn web.app:app --port 8001` 启动，`browser` 打开 `http://127.0.0.1:8001/`。
- 截图四图：曲线平滑自然（无锯齿、拐点可辨）、header 标题与 meta 紧凑垂直居中、末点缩小仍可见、四图视觉重量统一。
- `tab.evaluate` 模拟 hover 一条曲线：线色恢复全色、线宽加粗、point 放大——交互强调生效。
- 切换 7D / 30D / 90D：数据窗口正确、无报错（业务逻辑未动）。
- 取消/全选指标：`dataset.hidden` 显隐正常、空组占位正常（隐藏机制未动）。
- 局部拐点抽查：取近 30 日一个明显高/低点，确认曲线仍过该点（tension 0.25 不抹平拐点）。
- Ctrl+滚轮缩放：zoom 插件不回归。
