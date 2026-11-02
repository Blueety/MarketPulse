# MarketPulse 十一期重设计 · Web 看板 UI — 执行日志

日期：2026-08-30
执行者：按 `plan.md` 实施（架构师只读分析产出）

## 目标

从「用户 3 秒内知道涨跌」出发重设计 Web 看板图表与布局：

- 7 日图改为相对涨跌（每序列首个非空值 = 100），Y 轴只显示百分比变化。
- 去面积渐变填充，纯线条；数据点只保留最后一个。
- 标题旁显示各序列 7D 涨跌幅（兼作图例，不占 Chart.js legend 行）。
- 另类资产改为横向条形图（7D 表现对比，按正负着色）；波动率独立框、各线独立基准。
- X 轴只显示日期数字；网格线/边框弱化；Tooltip 轻量化（相对基准百分比）。
- P2 调优：卡片 padding 20px、字体层级、边框亮度、圆角、整体间距。

## 改动文件清单

| 文件 | 改动 |
|---|---|
| `web/app.py` | 新增 `_normalize_series`（纯函数），`_build_history_payload` 加 `change_7d`、归一化到基准 100 |
| `web/templates/index.html` | `GROUPS` 加 `type`/`ALT_SHORT`；重写 `renderCharts` 为 `renderMeta`+`renderLineChart`+`renderBarChart`；图表头部加 `.chart-head`/`.chart-meta` |
| `web/static/style.css` | `--border` 变暗、`.card`/`.card h2`/`.charts-grid`/`.chart-box` P2 调优、`.chart-box h3` 提层级、新增 `.chart-head`/`.chart-meta`/`.meta-item` |
| `tests/test_web.py` | 导入 `_build_history_payload`/`_normalize_series`；新增 `_seed_history` 辅助 + 6 条归一化/形状测试 |

未改：`daily_report.py` / `snapshot_report.py` / `src/*` / `requirements.txt` / Chart.js CDN / `.env` / 生成物目录；`/api/latest`、`/api/alerts` 契约不动。

## 每步验证结果

- **Step 1（app.py 归一化）**：`pytest tests/test_web.py -v` → 20 passed（存量 `test_api_history` 的 `vix["values"][1] is None`、`len(series)==10`、空数据 `dates==[]` 断言均成立，归一化不改变这些语义）。
- **Step 2（renderCharts 重写）**：浏览器实跑（见下）确认 Chart.js 加载、`window.__chartFailed=false`、4 个 canvas / 4 个 Chart 实例；`chart-meta` 填充正确（如「标普500 +0.77% 纳斯达克 +1.63%」「黄金 ETF（GLD） -4.17% 比特币（BTC-USD） -0.93%」）；读取 Chart 实例配置确认：线图 `type:"line"`、`fill:false`、`pointRadius` 为函数（末点 3 / 其余 0）、首序列 Y 已归一化到 ~100 基准；条形图 `type:"bar"`、`indexAxis:"y"`、`barThickness:18`。CDN 降级分支原样保留（`window.__chartFailed || !window.Chart` → 图区显示降级文案）。
- **Step 3（style.css P2）**：改动均为声明级，无逻辑风险；浏览器目检（DOM/布局）通过。
- **Step 4（新增测试 + 全量）**：`pytest tests/ -q` → **237 passed**（231 + 6 新增）。6 条覆盖：基准 100/首尾值、`change_7d=10`、前导/中间 null 保留且基准取首个非空、base=0 防除零（全 None 列表 + change_7d None）、单点无 change_7d、末位 null 用最后非空计 change_7d、series 四键形状。
- **Step 5（实跑 + 只读回归）**：`uvicorn web.app:app --port 8002` 启动后浏览器访问；`git status --short` 确认仅 4 个源码文件修改 + `tasks/` 目录新增，**data/ alerts/ context/ 无新增写入**（web 只读语义保持）。

## 遇到的问题

1. **CSS 并行 edit hash 漂移**：同一消息内对 `style.css` 发多个 edit，前几个应用后文件 hash 变化，导致 `.card h2` / `.chart-box` 两处被拒。改为顺序补应用后通过。
2. **test_web.py 尾部 append 错位**：`PUT >309:` 末尾插入时行号偏移，把 `test_endpoints_empty_data` 最后两行断言（`sector_heat` / `alerts`）挤出函数体到模块级，造成缩进语法错误。用整段 `PUT 309.=384:` 重建尾部修正。
3. **renderMeta id 拼接不匹配**：原实现 `getElementById("meta-" + g.id)` 生成 `meta-chart-gspc-ixic`，而 HTML 的 meta `id` 是 `meta-gspc-ixic`（少 `chart-` 前缀），导致 meta 不渲染。改为按 DOM 父容器 `box.querySelector(".chart-meta")` 定位，彻底解耦。
4. **端口 / 模板缓存**：8000 被陈旧 uvicorn 占用（返回旧页面），改 8002 起新服务；Jinja 默认缓存模板，首启服务未含 renderMeta 修复，重启后生效。
5. **截图 vision 代理超时**：浏览器截图文件已生成（`%TEMP%/omp-sshots-*.webp`），但 vision 代理读取超时，未拿到视觉描述。以「DOM 结构 + Chart 实例配置」做行为级验证（更强的正确性证据）。

## 与 plan.md 的偏差（有意为之）

- `_normalize_series` 在 base 缺失/为 0 时返回 `[None] * len(raw)`（全 None **列表**）而非 `None`。plan 核心设计伪代码写 `values = None`，但「存量测试影响」表与新增测试描述均写「values 全 None」；且前端 `s.values.forEach` 在 `values` 为 `None` 时会抛 TypeError，返回同长列表可安全遍历。属前端安全性的必要修正。
- `renderMeta` 用 DOM 关系定位替代 id 字符串拼接（见问题 3）。

## 下次注意

- HTML/JS 文件 edit 工具无法解析 AST，`PUT N*:` 会失败，必须用 `PUT N.=M:` 显式行号（或整体重写）。
- 同一文件多 edit 并行会因 hash 漂移互相 reject，改顺序执行或整体 `write` 重写（CSS 多行改动优先整体重写，见 pitfalls.md）。
- 模板/前端字符串拼接 id 易错，优先 DOM 关系定位。
- 验证前端改动必须重启 uvicorn（Jinja 缓存模板），且先确认目标端口未被陈旧进程占用。
- 验证期手动写入 `data/` 属 gitignored 且会恢复，不影响只读边界；但起服务前确认端口干净。
