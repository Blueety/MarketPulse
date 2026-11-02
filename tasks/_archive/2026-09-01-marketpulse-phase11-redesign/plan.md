# MarketPulse 十一期重设计：Web 看板 UI — 实施计划

> 架构师只读分析产出。目标、涉及文件、核心设计、实施步骤、验证命令、待确认决策。
> 分析基线：`web/app.py` / `web/templates/index.html` / `web/static/style.css` / `tests/test_web.py`（20 条，全量 231 passed）/ `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` / PRD。

## 目标

从「用户 3 秒内知道涨跌」出发重设计 Web 看板图表与布局：

- 7 日图改为相对涨跌（每个品种首个非空值 = 100），Y 轴只显示百分比变化。
- 去掉面积渐变填充，纯线条；数据点只保留最后一个。
- 标题旁显示各序列 7D 涨跌幅（兼作图例，不占 Chart.js legend 行）。
- 另类资产改为横向条形图（7D 表现对比）；波动率独立框基准化显示。
- X 轴只显示日期数字（24/25/26…）；网格线/边框弱化；Tooltip 轻量化。
- P2 调优：卡片 padding 20px、字体层级、边框亮度、圆角、整体间距。

## 涉及文件

| 文件 | 改动类型 |
|---|---|
| `web/app.py` | `_build_history_payload` 归一化 + `change_7d`（约 +15 行） |
| `web/templates/index.html` | `renderCharts` 重写 + 图表头部 meta 行 + 条形图分支（约 +40 / -60 行） |
| `web/static/style.css` | P2 调优 + `.chart-head` / `.chart-meta` 新样式（约 +25 / -5 行） |
| `tests/test_web.py` | 新增归一化/change_7d 纯函数与 payload 形状测试（约 +6 条） |

不改：`daily_report.py` / `snapshot_report.py` / `src/*` / `requirements.txt` / Chart.js CDN / `.env` / 生成物目录。`/api/latest`、`/api/alerts` 契约不动。

## 现状（分析基线）

- `/api/history` 返回 `{dates, series}`，series 元素 `{key, label, values}`，`values` 为 7 日**绝对价格**，含 null。
- 消费方仅两处：`index.html` 的 `renderCharts`（已 grep 确认）+ `tests/test_web.py`。契约改动在 web/ 内闭环，不触及其他模块。
- 前端 4 组图（美股大盘 / A 股大盘 / 波动率 / 另类资产）均为 line + 渐变填充 + pointRadius 3 + 顶部 legend + 大 tooltip + 原始值 Y 轴。
- 测试关键断言：`test_api_history` 的 `vix["values"][1] is None`（null 保留）；`test_endpoints_empty_data` 的 `dates == [] and len(series) == 10`。归一化后两项仍成立（见「存量测试影响」）。

## 核心设计

### 1. API 契约：`/api/history` 归一化（web/app.py）

`_build_history_payload` 每个序列：

```python
raw = [r.get(key) for r in records]
base = next((v for v in raw if v is not None), None)   # 首个非空值 = 基准
values, change_7d = None, None
if base not in (None, 0):
    values = [None if v is None else v / base * 100 for v in raw]
    last = next((v for v in reversed(raw) if v is not None), None)
    non_null = sum(1 for v in raw if v is not None)
    if last is not None and non_null >= 2:
        change_7d = (last - base) / base * 100
series.append({"key": key, "label": ..., "values": values, "change_7d": change_7d})
```

- 基准 = 窗口内**首个非空值**（不是固定首条记录）——首日取数失败时仍能归一化，前导 null 位置原样保留。
- base 缺失或为 0 → `values` 全 None、`change_7d` None（防除零；VIX 类恒 >0，0 仅理论防御）。
- 非空值 <2 个 → `change_7d` None（单点无 7D 变化可言，meta 显示「—」）。
- 返回 dict 顶层不变：`{dates, series}`。`/api/latest` 不动（概览表仍显示绝对收盘价）。

### 2. 前端渲染（index.html `renderCharts` 重写）

**线图（美股大盘 / A 股大盘 / 波动率 三组）**：

- `fill: false`（去渐变）；`tension: 0.35`；`borderWidth: 2.5`；`pointRadius: 0` + scriptable 末点 `(ctx) => ctx.dataIndex === ctx.dataset.data.length - 1 ? 3 : 0`（PRD P0.6 只留最后一个点）；`pointHitRadius: 10`。
- `plugins.legend.display = false`（图例移出 canvas，见 meta 行）。
- Tooltip 轻量：`titleFont 11 / bodyFont 12 / padding 8 / cornerRadius 4 / boxWidth 8`，label 回调 `"标普500 +2.41%"`（相对基准百分比，与 Y 轴语义一致），title 显示完整日期。
- Y 轴弱化：ticks 回调 `(v) => (v >= 100 ? "+" : "") + (v - 100).toFixed(1) + "%"`；grid 色 `rgba(48, 54, 61, 0.25)`（原 0.5 减半）；border 不显示；字号 10、次要色。
- X 轴缩短：ticks 回调 `String(ctx.tick.label).slice(8)`（"2026-08-30" → "30"）；`maxRotation: 0`；grid 不显示。

**另类资产（横向条形图）**：

- `type: "bar"` + `indexAxis: "y"`；数据 = `series.map(s => ({x: s.change_7d, y: 短名}))`，短名映射 `{gld: "黄金", btc: "比特币"}`（全标签「黄金 ETF（GLD）」过长）。
- 每根 bar 颜色按正负：≥0 绿 `#3fb950` / <0 红 `#f85149`（`backgroundColor` 数组）；`borderRadius: 4`、`barThickness: 18`。
- value 轴（x）ticks `"±x.x%"`，grid 半透明留基线；category 轴（y）不显示 grid、字号 12。
- `change_7d` 为 null 的资产跳过该 bar（数据不足时不渲染假值）。
- Tooltip label：`"7D 涨跌幅: +2.41%"`。

**图表头部 meta 行（兼作图例，P0.3 + P1.11）**：

```html
<div class="chart-head">
  <h3>美股大盘</h3>
  <div class="chart-meta">
    <span class="meta-item" style="color:#58a6ff">标普500 +2.41%</span>
    <span class="meta-item" style="color:#3fb950">纳斯达克 +3.10%</span>
  </div>
</div>
```

- 从 history payload 动态渲染：每序列 `label + fmtPct(change_7d)`，颜色取既有 COLORS；不占额外行（与标题同行、右对齐）。
- 值缺失显示「—」。4 个框统一此结构；另类资产框标题「另类资产（7D 涨跌幅）」，meta 与条形图数值一致（同一 `change_7d` 来源）。

**波动率独立处理（P1.9）**：保留独立第 3 框（不与大盘混），每条线独立归一（各序列自己的 base=100，天然满足「每条线独立基准」）；颜色语义保留（VIX 红 / VXN 橙 / MOVE 紫，上升=恐慌加剧），不做正负反转——数据展示诚实，语义由颜色承担。

**CDN 降级**：`window.__chartFailed || !window.Chart` 分支原样保留。

### 3. 样式（style.css，P2）

- `.card` padding `24px → 20px`、border-radius `12px → 10px`。
- `--border: #30363d → #2a3038`（变暗，统一作用于全部边框；P2 边框亮度）。
- `.card h2` font-size `16 → 15px`、margin-bottom `16 → 12px`（字体层级）。
- 新增 `.chart-head { display:flex; justify-content:space-between; align-items:baseline; gap:8px; margin-bottom:12px }`；`.chart-box h3` 提为 14px/600/主色（标题层级）；`.chart-meta` 12px 次要色、右对齐、`white-space: nowrap`；`.meta-item` 复用 `.pos`/`.neg` 语义色（内联 color 已带色，pos/neg 仅备选）。
- `.charts-grid` gap `16 → 12px`；`.chart-box` padding `16 → 14px`、radius 保持 8px（卡片 10px 内嵌 8px 层次）。canvas 高度保持 200px（条形图 2 根 bar 足够）。
- 概览表 / 板块 / 告警模块仅受 `--border` 变暗影响，结构不动。

## 实施步骤

| # | 步骤 | 文件 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | `_build_history_payload` 归一化 + change_7d | web/app.py | 契约变更影响 test_api_history | `venv/Scripts/python -m pytest tests/test_web.py -v` |
| 2 | renderCharts 重写（线图配置 / meta 行 / 条形图分支 / 轴与 tooltip 回调） | index.html | JS 回调笔误；CDN 降级分支保持 | 步骤 4 全量 + 浏览器目检 |
| 3 | P2 样式 + chart-head/chart-meta | style.css | 无逻辑风险 | 浏览器目检 |
| 4 | 新增测试（见下） | tests/test_web.py | — | `venv/Scripts/python -m pytest tests/ -v` 全绿 |
| 5 | 实跑验证（见验证命令 2-3） | — | — | 浏览器截图 + CDN 降级回归 |

## 存量测试影响

| 断言 | 现状 | 归一化后 |
|---|---|---|
| `test_api_history`：`vix["values"][1] is None` | vix 窗口 `[18, None, 19, 20, None, 21, 22]` | base=18 → values `[100, None, …]`，index 1 仍 None ✓ |
| `test_api_history`：`len(series) == 10` / `len(dates) <= 7` | — | 不变 ✓ |
| `test_endpoints_empty_data`：`dates == [] and len(series) == 10` | 空窗口 → raw=[] → base=None → values=[] | 仍成立 ✓（series 新增 change_7d=None 键，不破坏断言） |
| `/api/latest` 系列断言 | 未动 | 不受影响 ✓ |

无需改存量断言；`test_api_history` 可在步骤 4 顺手补 `change_7d` 键形状断言。

## 新增测试（tests/test_web.py，约 6 条）

- `test_build_history_payload_normalized_base100`：构造 7 日 gspc 100→110，断言 values 首尾 `[100, …, 110]`、`change_7d == 10.0`。
- `test_build_history_payload_null_preserved`：序列中间/前导 null 原样保留，首值 None 时用首个非空作基准。
- `test_build_history_payload_zero_base`：base=0 → values 全 None、change_7d None（不除零）。
- `test_build_history_payload_single_value`：仅 1 个非空值 → values `[100]`、change_7d None。
- `test_build_history_payload_change_7d_last_non_null`：末位 null → change_7d 用最后非空值计算。
- `test_api_history_series_shape`：series 元素含 key/label/values/change_7d 四键（补进既有 test_api_history 或独立用例）。

## 验证命令（对应 PRD Verification）

1. `venv/Scripts/python -m pytest tests/test_web.py -v` — 步骤 1 后跑，目标全绿。
2. `venv/Scripts/python -m pytest tests/ -v` — 全量回归（预期 231 + 6 左右，全绿）。
3. `venv/Scripts/python -m uvicorn web.app:app --port 8000` → 浏览器访问 `http://localhost:8000`：
   - 4 组图：3 组线图基准 100、无渐变、仅末点圆点；另类资产为横向条形图；Y 轴百分比、X 轴仅日期数字、网格半透明；标题旁 7D 涨跌幅带色小字；tooltip 轻量。截图存档到 tasks 目录作验收证据。
   - 无外网/CDN 拦截场景：图区显示「图表加载失败」降级文案，其余模块正常（既有行为回归）。
4. 只读回归：看板运行后 `git status` 确认 data/ alerts/ context/ 无新增写入（web 零侵入约束）。

## 待确认决策

- **A（建议默认）**：标题旁 7D 涨跌幅按**每序列**展示（"标普500 +2.41% · 纳斯达克 +3.10%"），兼作图例。PRD 例「美股大盘 +2.41%」为单数字表述，但本看板每组 2-3 序列，单数字无意义；每序列彩色小字信息量完整且不占行。
- **B（建议默认）**：另类资产条形图数值 = `change_7d`（7D 涨跌幅），与标题 meta 同一来源，两处永不打架。
- **C（建议默认）**：波动率线图正负不反转（VIX 涨显示红线上行），恐慌语义由颜色承担；「独立处理」= 独立框 + 各线独立基准，不并入大盘图。
- **D（建议默认）**：tooltip / Y 轴显示**相对基准百分比**（±x.xx%），不显示绝对指数值（与「3 秒内知道涨跌」一致；绝对价概览表仍有）。

## 风险与边界

- **归一化改变 /api/history 语义**：消费方仅 index.html + test_web.py（已 grep 证实），闭环无外溢；概览表绝对价不受影响。
- **首日缺数**：首值 None → 用首个非空作基准，前导 null 保留；多日缺数导致非空值 <2 → 图只渲染单点/空、meta「—」，不崩。
- **条形图 null**：change_7d 为 null 的资产跳过 bar；双资产都无数据时条形图区空 + meta「—」，页面不白屏。
- **Chart.js 4.4.1 能力**：`indexAxis: "y"`、scriptable `pointRadius`、category scale tick callback 均为 4.x 原生支持，CDN 版本不动。
- **Y 轴 % 刻度**：基准 100 附近的数值跨度小（如 +10%），tick 回调 `(v-100).toFixed(1)` 输出连续；autoSkip 保留防重叠。

## PRD Done When 对照

- 7 日图相对涨跌（基准 100）→ 核心设计 1 + 2（线图）
- 标题旁 7D 涨跌幅 → 核心设计 2（chart-meta 行）
- 另类资产横向条形图 → 核心设计 2（bar 分支）
- 波动率基准化显示 → 核心设计 2（独立框 + 独立基准）
- Y 轴百分比 → 核心设计 2（tick 回调）
- X 轴日期数字 → 核心设计 2（slice(8)）
- 去渐变 / 末点圆点 / 网格弱化 / Tooltip 轻量 / 图例简化 → 核心设计 2
- 卡片 padding 20 / 字体层级 / 边框亮度 / 圆角 / 间距 → 核心设计 3
- 3 秒内知道涨跌 → 验证命令 3（浏览器目检 + 截图）
