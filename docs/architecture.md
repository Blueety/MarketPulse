# 架构说明（MarketPulse — 波动率监控系统）

> 描述项目的模块边界、数据流和关键设计决策。
> Agent 修改架构相关代码前必须先读这份文档。

## 概览

Python 项目。每个交易日有多个运行点：

1. **收盘日报**：`daily_report.py`（美东收盘后运行），从 Yahoo Finance 拉取美股（GSPC/IXIC/VIX/VXN/MOVE）+ A 股（SH/SZ/CYB）+ 另类资产（GLD 黄金 ETF / BTC-USD 比特币）共 10 个标的，生成 Markdown 日报（含分市场近 30 日趋势图），追加历史数据并缓存当日值，生成 `context/YYYY-MM-DD.json` 上下文（供 Hermes 常规解读/异动归因），交由 Hermes 读取并推送到 QQ 机器人。另类资产仅纳入日报「💰 另类资产」板块与趋势图，不参与告警、不进入波动率/大盘面板。
2. **盘中快照**：`snapshot_report.py`（A 股午盘 11:30 / A 股收盘 15:00 / 美股开盘 21:30 / 美股午盘 00:00，北京时间），按 `--market {a-share,us,alt}` + `--time {open,midday,close,noon}` 取对应市场子集（alt = GLD/BTC 另类资产单板块），渲染单板块简报存盘 `reports/snapshots/YYYY-MM-DD-{market}-{time}.md`，检查告警阈值（只读缓存基准），不推送。
告警：两入口各自检查当日变化率是否超过阈值（默认 VIX/VXN ±20%、MOVE ±15%、GSPC/IXIC ±4/±4.5、SH/SZ ±4%、CYB ±5%，env 可覆盖），
触发则生成 `alerts/YYYY-MM-DD-{type}.md`（type = close / a-share-midday / a-share-close / us-open / us-noon），由 Hermes 检测并独立推送一条警报消息；
同一指数当日只告警一次（午盘触发则收盘跳过），去重状态记在 `data/alerts.log`。

**脚本自身不包含推送逻辑。** AI 常规解读与异动归因由 Hermes 读取 `context/` 后生成（交付配置项，非仓库文件）。

## 模块划分

| 模块 | 路径 | 职责 |
|---|---|---|
| 编排入口 | `daily_report.py` | 收盘流程编排：取数 → 读缓存/历史 → 算涨跌幅 → 渲染报告 + 趋势图 → 写报告 → 追加历史 → 写缓存 → 生成 context |
| 编排入口 | `snapshot_report.py` | 盘中快照流程编排：按 `--market`/`--time` 取市场子集 → 分类 → 渲染单板块快照 → 落盘 `reports/snapshots/YYYY-MM-DD-{market}-{time}.md`（只读缓存作告警基准，不算涨跌幅、不写 history、不推送）；4 个 Hermes cron 各传一组参数 |
| 告警 | `src/alerter.py` | 告警文件渲染（附录块格式）、alerts.log 去重状态读写、`collect_breaches` 纯计算导出、`run_alert_checks` 编排（逐指数容错） |
| 数据获取 | `src/fetcher.py` | Yahoo 取数（含重试/退避/源间节流），SYMBOLS 注册表；八期新增 fetch_sector_heat 概念板块热度 Top5（AkShare/新浪源，线程限时 10s，失败返回 []）；十八期新增 SECTOR_MAPPING + aggregate_sectors，fetch_sector_heat 内部将全量概念板块聚合为 10 大类 +「其他」（成交额加权，零成交额简单平均，未匹配归其他，行契约同构） |
| 纯逻辑 + 持久化 | src/analyzer.py | 状态分类、涨跌幅、格式化、路径常量（含 CONTEXT_DIR）、last_values 缓存、history 读写（90 天滚动、原子写、损坏容错）、build_search_keywords、compute_correlation（指数对 Pearson 相关性，纯 Python 零依赖，输入为收益率） |
| 报告渲染 | src/reporter.py | Markdown 日报 / 午盘快照渲染、趋势图（matplotlib 懒加载 + 15s 线程限时）、分市场趋势图（us 2×1 / cn 3×1 双图，5s 限时）、落盘、相关性分析章节与 context correlation 键（generate_context，原子写） |
| 配置加载 | `src/config.py` | 阈值配置：config.json + 环境变量覆盖 + 内置默认三级（DEFAULTS/ENV_MAP/env_float/load_config），白名单校验，零依赖 |
| 图片渲染 | `src/image_renderer.py` | 日报图片化：md 解析（日期 / 10 指数卡片 / 趋势图引用 / AI 解读章节）/ 告警附录块解析 / Jinja2 模板渲染 / Playwright 截图转 PNG（宽 600 自适应高、全链路容错，失败返回 None 不影响主流程；注意：15s 超时 / ≤800KB 尺寸守卫 / zoom 重试已在 a536888 删除，当前未实现） |
| 报告输出 | `reports/YYYY-MM-DD.md`、`reports/snapshots/YYYY-MM-DD-{market}-{time}.md`、`reports/charts/YYYY-MM-DD{-trend,-us-trend,-cn-trend}.png`、`reports/images/YYYY-MM-DD.png` | 生成的 Markdown / 图片（日报趋势图统一用美东日期；图片为图片化推送产物，保留 .md 同时生成 .png） |
| 告警输出 | `alerts/YYYY-MM-DD-{type}.md`（type = close / a-share-midday / a-share-close / us-open / us-noon）、`data/alerts.log` | 告警文件 / 当日去重标记（运行时生成，gitignore 排除） |
| 数据持久化 | `data/last_values.json`（涨跌幅基准）、`data/history.json`（近 90 日历史） | 运行时生成，gitignore 排除 |
| Web 看板 | `web/app.py`（FastAPI 应用 + 4 端点）、`web/templates/index.html`、`web/static/style.css`、`web/__init__.py` | 只读看板：解析 `data/history.json` / `context/*.json` / `alerts/*.md` 渲染单页（市场概览表 / 4 组独立 y 轴趋势图 / A 股板块热度 Top5 / 告警记录），提供 `/api/history` `/api/latest` `/api/alerts` 三个 JSON API；零侵入 `daily_report.py` / `snapshot_report.py` / `src/*`，进程绝不写任何数据文件 |
| 回测 | `scripts/backtest.py` | 独立回测脚本：复用生产 `check_breach` 语义回放历史触发事件，统计告警次数 / 年化频率 / WARN-ALERT 分布 / 1·3·5·10 日平均后效 / 胜率 / 有效触发率；只读 `data/history.json`，仅写 `reports/backtest_report.md`，不联网、零副作用 |

## 数据流

```text
Yahoo Finance (^VIX, ^VXN) ──┐
                             ├──> daily_report.py ──> reports/YYYY-MM-DD.md ──> Hermes ──> QQ 推送
                                        ├──> reports/images/YYYY-MM-DD.png（图片化推送产物；Hermes 追加 AI 解读后经 scripts/render_report_image.py 重渲染含解读图）
                                        ├──> reports/charts/YYYY-MM-DD-trend.png（报告中引用）
                                        ├──> data/history.json（按 date 追加/覆盖，90 天滚动）
                                        ├──> data/last_values.json（今日值，次日作涨跌幅基准）
                                        └──> context/YYYY-MM-DD.json（indices + history_30d + breach + search_keywords）
                                              └──> Hermes 常规解读 /（异动日）tavily 搜索归因 ──> 追加日报 ──> QQ 推送

两入口（收盘/午盘）另检查变化率告警（基准 data/last_values.json 旧缓存，只读）：

    daily/snapshot ──> src/alerter.run_alert_checks ──> alerts/YYYY-MM-DD-{type}.md ──> Hermes ──> QQ 独立推送
                                        └──> data/alerts.log（当日已告警标记，午盘触发则收盘跳过）

    snapshot_report.py ──> reports/snapshots/YYYY-MM-DD-{market}-{time}.md（仅存盘，不推送）
```

## 关键决策

| 决策 | 选择 | 原因 | 日期 |
|---|---|---|---|
| 模块拆分 | `daily_report.py` 300 行拆为 `src/` 三模块 + 约 50 行编排入口 | 二期新增快照与趋势图后单文件不可维护；`snapshot_report.py` 复用 fetcher | 2026-09-01 |
| 数据源 | 三指数均用 Yahoo：^VIX / ^VXN / ^MOVE | FRED 公开 API 无 MOVE 序列；^MOVE 标名有误但数值真实（与 Investing.com 一致） | 2026-08-29 |
| 时区 | 内部 UTC，报告显示美东日期 | 避免时区混淆导致日期错 | 2026-08-29 |
| 容错 | 单数据源失败继续运行，不整体崩溃；任一指数取数失败在 history 中存 null | 一个源挂了不能吞掉整个日报；趋势图按 NaN 断点处理 | 2026-08-29 / 2026-09-01 |
| 历史存储 | `data/history.json` 列表按 date 键追加/覆盖，仅保留最近 90 条，临时文件 + `os.replace` 原子写，损坏按空历史处理 | 趋势图数据来源；避免无限膨胀与半截写入 | 2026-09-01 |
| 趋势图 | matplotlib（Agg 后端 + 懒加载）；Windows 无 SIGALRM，用 daemon 线程 `join(3)` 限时，超时跳过绘图、报告不产生死链 | 无头环境渲染；冷启动/渲染超时不中断整体流程 | 2026-09-01 |
| 图表语言 | 趋势图标签一律英文（"VIX (30D)" / "VXN" / "MOVE" / "Date" / "Value"） | 中文字体跨平台渲染不一致（PRD 强制约束） | 2026-09-01 |
| 告警基准 | 统一用 `data/last_values.json` 旧缓存；快照只读不写 history；收盘告警检查置于 save_last_values 之前 | 避免误用当日新缓存；多时点不并发写（已确认决策 1/决策 G） | 2026-09-01 |
| 告警去重 | 当日已触发状态记 `data/alerts.log`（行式 "YYYY-MM-DD SYMBOL"，原子重写仅当日行）；午盘触发则收盘跳过同一指数 | 同一指数当日只告警一次（已确认决策 2/设计 C） | 2026-09-01 |
| 告警阈值 | 默认 VIX/VXN ±20%、MOVE ±15%；env `ALERT_THRESHOLD_<SYM>` 覆盖；触发条件为变化率**严格大于**阈值 | 默认值已确认；env 非法/非正回退默认（已确认决策 3/设计 A） | 2026-09-01 |
| 告警级别 | 触发即 WARN；当前值处于恐慌区间（classify 判定）升级为 ALERT | PRD 要求 WARN/ALERT，复用已确认 classify 区间，零新增配置（设计 B） | 2026-09-01 |
| 告警文件 | `alerts/YYYY-MM-DD-{type}.md`（type = noon / close），多指数各占一个附录块（frontmatter + 标题 + 字段） | PRD 固定文件名 {type}；多指数同日触发不冲突（设计 D） | 2026-09-01 |
| 告警容错 | run_alert_checks 内逐指数 try/except，调用方再包一层 try/except，仅记日志 | 告警逻辑失败不影响日报生成，退出码恒 0（决策 H） | 2026-09-01 |
| context 计算单一来源 | alerter 新增纯计算导出 `collect_breaches(values, last_values)`（遍历 check_breach，不写文件/不改 alerts.log，幂等）；`run_alert_checks` 重构为复用它（去重/写文件/标记逻辑原样） | breach 判断单一事实来源，context 生成不产生副作用；既有 23 条 alerter 测试行为等价锁定（决策 A） | 2026-09-01 |
| context 契约 | context/YYYY-MM-DD.json 八键：date / indices（value/change_pct/status）/ history_30d（dates + gspc/ixic/sh/sz/vix/vxn/move/cyb/gld/btc 等长数组，含当日）/ breach（triggered + indices 字段 name/current/previous/change_pct/threshold/level，level 沿用 WARN/ALERT）/ sector_heat（板块热度 Top5：name/change/turnover/top_stock）/ us_sector_heat / search_keywords / correlation（显著相关对：a/b/pair/r/n，|r|>0.5 才写入） | PRD 字段表定稿，Hermes Prompt 按此编写；_breach_item 纯映射单测锁定（决策 B）；八期新增 sector_heat 键（决策 H）；十一期新增 us_sector_heat 键；十二期新增 correlation 键（仅 |r|>0.5 显著对） |
| 搜索关键词 | `build_search_keywords(date, breaches)` 方向感知：异动指数变化率 >=0 用 "surge"、<0 用 "drop"，加 market volatility / economic data 定向词，异动日 3-5 个；常规日 1 个 "market summary {date}" | 方向感知直接服务归因搜索相关性（VIX 下跌时搜 "VIX drop" 才能命中下跌原因）（决策 C） | 2026-09-01 |
| context 生成时机 | `generate_context` 在 `append_history` 之后、`save_last_values` 之后调用（history_30d 含当日）；临时文件 + `os.replace` 原子写；仅收盘入口生成，snapshot 不动 | 含当日的 30 日趋势对 Hermes 参考更完整；原子写避免读到半截 JSON（决策 D/F） | 2026-09-01 |
| context 容错 | `generate_context` 不吞异常，`daily_report.py` 调用方 try/except 兜底仅记日志，退出码恒 0 | 失败路径可见可测；context 失败不影响日报主流程（决策 E） | 2026-09-01 |
| AI 解读/归因 | Hermes 侧 Prompt + tavily 搜索为交付配置项（非仓库文件）；Python 侧不引入 LLM/搜索 SDK | PRD 明确约束（决策 G） | 2026-09-01 |
| 阈值配置化 | 五期将硬编码阈值外置到 config.json + env 覆盖；优先级链 env > config.json > 内置默认，config 缺失/非法回退默认不崩溃 | 改配置不改代码；为加股票/新指标铺配置基建（设计 A-G 已确认） | 2026-09-01 |
| 盘中快照（七期） | 快照扩展为 4 个市场时点：A 股午盘 11:30 / A 股收盘 15:00 / 美股开盘 21:30 / 美股午盘 00:00（北京时间）；`--market a-share` 取 SH/SZ/CYB、`--market us` 取 GSPC/IXIC（不含波动率）；创业板 `399006.SZ` 入 SYMBOLS（8 键，阈值 ±5%）；快照存 `reports/snapshots/YYYY-MM-DD-{market}-{time}.md`，告警文件复合名 `alerts/YYYY-MM-DD-{market}-{time}.md` 防与日报碰撞；A 股快照按北京时间归档（设计 A-G） | 盘中快照原仅美东 12:30 三板块；现按市场/时段分档，波动率仅保留在日报，快照单板块；旧 `YYYY-MM-DD-noon.md` 命名退役 | 2026-08-30 |
| A 股板块热度（八期） | 日报新增「🔥 A 股热点板块 Top 5」：AkShare `stock_sector_spot(indicator="概念")` 取概念板块，按涨跌幅降序取 Top5（不设阈值）；`fetch_sector_heat` 线程限时 10s（新浪源无 timeout），超时/异常/缺必需列返回 [] 不中断日报；板块名注入 `search_keywords`（方向感知 surge/drop，不触发独立告警）；context 新增 `sector_heat` 键 | 丰富市场情绪感知；Top5 方案避免阈值主观设定；新浪接口挂起由线程限时兜底；板块热度非核心，失败降级为「数据暂缺」 | 2026-08-30 |
| 分市场趋势图（九期） | 日报新增美股 2×1（GSPC/IXIC）与 A 股 3×1（SH/SZ/CYB）趋势图：`render_market_trend_chart(history, date, market)`（注册表式，market∈{us,cn}，复用 render_trend_chart 绘图范式，独立 `MARKET_CHART_TIMEOUT=5` 限时，三图串行渲染）；`render_report` 加 `us_trend_chart`/`cn_trend_chart` 默认参数 + 两个章节（us 图在美股大盘后、cn 图在 A 股大盘后）；占位文案英文 "Insufficient Data"；市场键 us/cn 与快照 `MARKETS` 键 a-share/us 不同；`daily_report.py` 单次 `load_history` 复用 | 波动率图外补足分市场走势感知；图表文本英文是既有硬约束；整体行数<2 返回 None 省略章节（与 render_trend_chart 一致），部分序列缺数据子图占位不中断 |
| Web 看板（十一期） | 新增 `web/` 包：FastAPI 单页看板 + 3 个只读 JSON API（`/api/history` / `/api/latest` / `/api/alerts`）。路径常量复用 analyzer 单一事实来源，但在 `web/app.py` 重新绑定为模块级名字（解析函数一律引用本模块常量），测试 monkeypatch 落点严格打在使用方模块 `web.app`（打在定义方 analyzer 不生效）；板块热度数据源为最新 `context/*.json` 的 `sector_heat`（history.json 无板块字段，PRD 字面「从 history.json」不实，按「单独 JSON = context」落地）；`alerts/` 空目录 / 坏文件容错返回 `[]` 不 500；Chart.js 走 CDN，加载失败图区降级「图表加载失败」文案；新增运行依赖 fastapi/uvicorn/jinja2/httpx（决策 A，PRD 技术栈明确指定） | 浏览器展示最近 7 日市场数据，零侵入日报/快照主流程；只读语义（不读 `last_values.json`、不写任何生成物）保持与日报同一事实来源；量级悬殊（BTC 万级 vs VIX 十几）按市场分 4 图各独立 y 轴 | 2026-08-30 |
| 测试隔离 | tests/conftest.py 顶层强制 CONFIG_PATH 指向不存在文件，collection 前生效 | 用户定制 config.json 后跑 pytest 不破坏默认断言（PRD 风险表"测试混用生产配置"正解） | 2026-09-01 |
| 板块聚合（十八期） | `fetch_sector_heat` 内部单点聚合：SECTOR_MAPPING（10 大类 + 新浪实际别名）× `_parse_turnover` 还原成交额 + `aggregate_sectors` 纯函数加权；日报/快照/开盘分析/context/web 五个消费点零改动（web 只读 context 无聚合源，必须取数层聚合）；聚合公式 = Σ(子板块 change×成交额[元]) / Σ成交额[元]，Σ=0 走简单平均；未匹配概念板块归「其他」参与排序；聚合行契约 {name, change, turnover, top_stock} 与概念行同构；top_stock 取类别内成交额最大子板块 | 聚合在取数层一次完成，消费点自动全变大类，零 mock 签名破坏、零重复实现；精确匹配兜底漏配；大盘名替代概念名（超出 PRD 文件表字面，已确认） | 2026-08-31 |
| 美股去重 + 浅色主题（二十五期） | 美股去重：判定符号集取 GSPC+IXIC（排除 MOVE 浮点抖动 70.965→70.9655），`daily_report.py` 新增纯函数 `_is_us_duplicate_day(history, record)` 在 `append_history` 前加门，非交易日（美股值全同）整条跳过写历史（D1/D2）；混合日（美股未动但 A 股/BTC/GLD 变动，如 09-01）整条跳过、PRD 字面取舍、当日日报/context 仍完整；浅色主题：`web/static/style.css` 加 `:root.light` 变量覆盖 + `.card` 白底，前端在 `index.html` 加预应用脚本（防 FOUC）+ topbar 右上 `🌙/☀️` 切换按钮 + `setTheme(light)`（切 `html.light` 类 + 写 `localStorage["mp-theme"]` + 更新图标） | 美股重复特指 GSPC/IXIC（实测 08-30 与 08-29 全同、09-01 与 08-31 全同）；MOVE 浮点抖动会误判故排除；方案不引入交易日历依赖、不改 src/、零后端变更、web/app.py 不动；浅色主题纯前端、涨跌色（--green/--red/--blue/--orange）不变 | 2026-09-01 |


## 约束

- 不修改的模块/文件: `.env`，`reports/`，`data/`（均为运行时生成/用户配置）。
- 必须保持的兼容性: `python daily_report.py` / `python snapshot_report.py [--market a-share|us] [--time open|midday|close|noon]` 全程可手动运行（裸跑 = 美股午盘）。
- 依赖边界：运行依赖 `requests` / `matplotlib` / `pytest` / `fastapi` / `uvicorn` / `jinja2` / `httpx`（十一期 Web 看板引入后四项，PRD 技术栈明确指定 FastAPI + uvicorn + jinja2，httpx 为 TestClient 必需；Chart.js 经 CDN 不落盘，不计入 Python 依赖）。
- 五期起：阈值全部外置 `config.json`，`src/config.py`（约 122 行）+ `analyzer.py`/`reporter.py` 接线（约 +5 行）；`tests/test_config.py`（约 180 行）。优先级链 env > config.json > 内置默认，零新增依赖；`config.json` 入 gitignore（用户定制不入库）。

## 目录级规则

- `reports/`、`data/`、`alerts/` 与 `context/` 为生成物，默认 `.gitignore` 排除或运行时自动创建。
- 每个函数只做一件事，带 docstring。
