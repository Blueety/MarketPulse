# MarketPulse 二十二期 Plan — 趋势图数据密度优化

> 架构师产出。基于对 `web/templates/index.html`、`web/app.py`、`data/history.json` 的代码审查 + 8001 端口浏览器实测。

## 0. 实证结论（先看这里）

任务卡核心观察「30D 只有约 6 个数据点」与当前代码**不符**，十七期（`/api/history?days=` 窗口化）已解决。实测证据：

| 指标 | 实测值 |
|---|---|
| history.json 总量 | 90 条（含 2 条周末行，API 已过滤） |
| 30D 窗口工作日 | 30 条；各标的非空值 29-30/30（数据完整） |
| 30D 实际渲染点数 | 美股 29、A股 30、波动率 29、另类 30（每序列） |
| 7D 实际渲染点数 | 6-7（完整交易日序列） |
| 90D 实际渲染点数 | 85-88（周末过滤后完整序列，880 点渲染无性能问题） |
| X 轴标签数 | 6-7 个（`maxTicksLimit: 6` 已满足「5-7 个标签」） |
| 图例 | 已隐藏（`legend.display: false`），由 chart-head meta 彩色标签替代 |
| 数据点 | 默认全隐藏，仅最新点 4px 圆点（已克制） |

**因此本期不是「加数据点」，而是四个真实缺陷的精修**，全部集中在 `renderLineChart`，`web/app.py` 零改动。

## 待确认决策

| # | 决策 | 推荐 | 理由 |
|---|---|---|---|
| D1 | 曲线平滑度：`tension: 0.15` → ? | **0.08** | 30+ 点曲线仍自然，相对 0.15 平滑感明显降低；0 会在 90D（88 点）产生锯齿抖动，违背「走势自然」 |
| D2 | null 日处理：当前 fill-forward 把前值虚构为当日点 → ? | **断线（`y: null`，spanGaps 默认 false）** | 「不通过虚构数据增加数据点」约束的诚实实现；数据仅 1/30 缺失，视觉影响极小但语义正确 |
| D3 | X 轴标签格式：当前纯日 `slice(8)`（"04"）跨月歧义 → ? | **"M/D"（如 "8/4"）** | 30D 跨 7-8 月、90D 跨 5-8 月，纯日标签无法区分月份；保持 `maxTicksLimit: 6` 不动底层数据 |
| D4 | 最新点半径 4px → ? | **3px**（可选微缩） | 已克制；4→3 差异甚微，若追求 PRD 字面「缩小」可改，成本零 |
| D5 | Hover 反馈增强 | **采纳**：`pointHoverRadius 5→6` + `pointHoverBorderWidth: 2` | 低成本强化「Hover 明确反馈」，不改变 tooltip 数据准确性 |

## 影响分析

| 功能 | 方案 | 涉及文件 | 代码量 |
|---|---|---|---|
| 曲线平滑度降低 | `tension` 常量调整 | index.html | 1 行 |
| null 断线（去虚构点） | 删 `lastVal` carry-forward 逻辑；null 日推 `{x, y: null}` | index.html | 改 ~8 行 |
| X 轴标签消歧义 | ticks.callback 改 "M/D" 格式 | index.html | 改 ~5 行 |
| Hover 反馈 | pointHoverRadius / pointHoverBorderWidth | index.html | 改 ~2 行 |
| 最新点尺寸 | pointRadius 4→3 | index.html | 1 行 |
| 后端数据完整性 | **无需改动**（已实测完整） | web/app.py | 0 |

约束核对：不碰数据源/计算逻辑 ✓；7D/30D/90D 业务行为不变（纯前端展示层）✓；零新依赖 ✓；2×2 布局与 340px 高度不动 ✓；不插值/不虚构（D2 反而移除虚构）✓；涨跌颜色语义不动 ✓；tooltip 仍读 `raw` 原值 ✓。

测试影响：`tests/test_web.py` 全部为 API/纯函数契约（`test_index_html` 仅断言 200 + content-type，`test_api_history_series_shape` 锁定 series 键集），**不解析 HTML JS 内容 → 零影响**。无前端 DOM 测试框架。

## 修改清单

仅 `web/templates/index.html` 内 `renderLineChart`（约 L238-285）：

1. **去虚构点**（核心）：
   - 删除 `let lastVal = null;` 与 `else if (lastVal != null) { pts.push({x, y: lastVal, rawVal: null}); }` 分支
   - null 日改为 `pts.push({ x: date, y: null, rawVal: null });`（Chart.js v4 默认 `spanGaps: false` → 断线；`tradingDates` union 集合逻辑保留，保证 x 轴域完整）
2. **平滑度**：`tension: 0.15` → `tension: 0.08`
3. **X 轴标签**：callback 由 `String(tradingDates[index]).slice(8)` 改为解析 `"YYYY-MM-DD"` → `"M/D"`（`Number(month) + "/" + Number(day)`，去前导零）；`maxTicksLimit: 6` 保留
4. **Hover**：`pointHoverRadius: 5` → `6`；新增 `pointHoverBorderWidth: 2`
5. **最新点**：`pointRadius` 末点 `4` → `3`（按 D4 确认）

不动的部分：`allDates`/`tradingDates` 集合逻辑、`renderMeta`、GROUPS 注册表、state/syncSelection、zoom 插件、tooltip 回调、`web/app.py`、`style.css`。

## 执行步骤

1. 确认 D1-D5（默认采纳推荐值；D4 默认 3px）
2. 修改 `web/templates/index.html` 的 `renderLineChart` 5 处（用 edit 工具，单函数范围内小改）
3. 启动/复用 8001 端口服务器（`venv/Scripts/python -m uvicorn web.app:app --port 8001`，避开 8000 常占）
4. 浏览器验证（见下）
5. 全量 pytest 回归

## 验证方法

```bash
# 1. 后端契约零回归
venv/Scripts/python -m pytest tests/ -v

# 2. 浏览器实测（8001 端口，browser 工具）
#    - 30D：每图每序列点数 == 29-30（完整交易日）
#    - X 轴标签 == 6-7 个且格式 "M/D"（如 "8/4"），无跨月歧义
#    - 仅最新点可见圆点（3px），其余无点
#    - hover 曲线：圆点放大至 6px + tooltip 显示 raw 原值与涨跌幅
#    - 切 7D（6-7 点）/ 90D（85-88 点）视觉一致，渲染 < 1s
#    - null 日（如有）曲线断口而非平台
# 3. 截图 before/after 对比（shot-before.webp 已存档于本目录）
```

## 风险与备注

- **数据完整度假设**：当前 30D 缺失日仅 1 天/序列，断线几乎不可见；若未来某序列缺失增多，断线会比平台更诚实地暴露缺口（符合约束，非缺陷）。
- **浏览器缓存**：Jinja2 启动时缓存模板，验证须用新起进程或硬刷新（项目已知陷阱，已用 8001 新进程规避）。
- **90D 性能**：实测 880 点渲染流畅，无需 decimation 采样（加了反而违背「不删底层数据」）。
