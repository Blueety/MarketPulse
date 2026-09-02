# 命令说明

> 列出项目所有验证命令。Agent 完成修改后必须运行相关命令。
> 所有命令需先激活 venv（Windows: `venv/Scripts/activate`），或直接调用 `venv/Scripts/python`。

## 快速检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/python -m pytest tests/ -v` | 运行单元测试 | 改了函数逻辑 / 提交前 |
| `venv/Scripts/python daily_report.py` | 运行主脚本（完整闭环：取数→报告→趋势图→写历史→写缓存） | 改了数据获取/报告生成/错误处理逻辑 |
| `venv/Scripts/python -m uvicorn web.app:app --port 8000` | 启动 Web 看板（只读展示最近 7 日数据） | 改了 `web/` 模块 / 提交前 |
| `venv/Scripts/python scripts/backtest.py [--history PATH]` | 运行独立回测脚本（验证告警阈值有效性）：复用生产 `check_breach` 语义回放 `data/history.json`，输出各标的告警次数 / 年化频率 / WARN-ALERT 分布 / 1·3·5·10 日平均后效 / 胜率 / 有效触发率，生成 `reports/backtest_report.md`；`--history` 指定只读历史文件（用于数据不足验证）；全程 <5s、不联网、零副作用 | 改了 `scripts/backtest.py` / 阈值逻辑后回归 |
| `venv/Scripts/python scripts/render_report_image.py --date YYYY-MM-DD` | 独立重渲染日报图片（Hermes 追加 AI 解读后重渲染含解读图）；依赖 imgkit + 本地 wkhtmltoimage（先 `pip install -r requirements.txt` 装 imgkit，再 winget 装 wkhtmltopdf）；失败仅退出码非 0，不影响日报 md | 改了 `src/image_renderer.py` / 模板 / 重渲染入口后 |

## 完整检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/pip install -r requirements.txt` | 安装/校验依赖 | 环境变更 / 提交前 |
| `venv/Scripts/python -m pytest tests/ -v` | 完整测试套件 | 提交前 |
| `venv/Scripts/python -c "import matplotlib; matplotlib.use('Agg')"` | 校验 matplotlib 可用（Agg 无头后端） | 环境变更 / 提交前 |

## 何时跑什么

| 改动类型 | 必须运行 |
|---|---|
| 数据获取逻辑（美股 + A 股 + 波动率 + 另类资产共 10 标的：GSPC/IXIC/VIX/VXN/MOVE/SH/SZ/CYB/GLD/BTC-USD，含创业板 399006.SZ） | 主脚本 + 快照脚本 + 相关单元测试 |
| 报告/快照/趋势图生成 | 主脚本 + 快照脚本（检查输出内容与 PNG，含 `--market`/`--time` 分档） |
| 状态判断/涨跌幅计算 | 相关单元测试 |
| history 读写/滚动 | 相关单元测试（test_analyzer.py TestHistory） |
| 错误处理/离线容错 | 主脚本（断网场景） |
| 日报图片化（`src/image_renderer.py` / 模板 / 重渲染入口） | 跑 `scripts/render_report_image.py --date` 验证 PNG 生成（宽 600、≤800KB、含解读章节）、相关单测 `tests/test_phase14.py` |
| cron 自动提交推送（二十六期） | 无需手动；daily_report / snapshot_report / opening_analyzer 末尾自动 commit+push；本地验证用 `AUTO_PUSH=0` 关闭（如 `AUTO_PUSH=0 venv/Scripts/python daily_report.py`）；真跑验证限一次（会 push 触发 Railway 重部署，且遗留 Hermes「每日数据更新」cron 可能抢先提交） |

## 验证要点（对应任务 prd 的 Verification Plan）

- 首次运行 `daily_report.py`，`reports/YYYY-MM-DD.md`、`data/last_values.json`、`data/history.json` 应自动生成；history 只有 1 条时无趋势图（数据不足 2 条跳过）。
- 删除 `data/last_values.json` 后运行，涨跌幅应显示"首次运行，暂无历史对比"。
- 断网时运行，脚本不崩溃、输出明确错误提示、报告标注获取失败、history 记录 null。
- 有 ≥2 条历史数据（不含当日）时运行 `daily_report.py`，应生成 `reports/charts/YYYY-MM-DD-trend.png`，且报告中含「## 📉 近30日趋势」章节引用 `./charts/YYYY-MM-DD-trend.png`。
-- 修改 `data/last_values.json` 模拟变化率超阈值（如 VIX 基准 = 当前值/1.22，即 +22%）后运行 `daily_report.py`，应生成 `alerts/YYYY-MM-DD-close.md`，内容含当前值/昨日收盘/变化率/阈值/状态/建议/报告路径，格式为 frontmatter + 标题 + 字段的附录块。
- 先跑 `snapshot_report.py --market a-share --time midday` 触发 A 股午盘告警再跑 `daily_report.py`（同一 +22% 模拟）：收盘不再生成含该指数的 close 文件（午盘触发则收盘跳过，`data/alerts.log` 记当日已告警）；跨市场互不影响（SH 标记不阻塞 GSPC）。告警文件名=复合名 `alerts/YYYY-MM-DD-{market}-{time}.md`，不与日报 close 文件碰撞。
- `ALERT_THRESHOLD_VIX=30 venv/Scripts/python daily_report.py`（+22% 模拟）：VIX 不再告警（22 < 30），env 覆盖默认 20 生效。
- 删除/移走 `data/last_values.json` 或断网时运行两入口：不崩溃、退出码 0、无告警文件（check_breach 对缺失数据返回 None）。
- 验证后必须恢复 `data/last_values.json` 原值（备份/恢复）。
- history.json 超过 90 条时自动滚动（仅保留最近 90 条）；同日重复运行按 date 覆盖，不产生重复条目。
- 趋势图渲染超过 15 秒（波动率图 `CHART_TIMEOUT`）/ 5 秒（分市场图 `MARKET_CHART_TIMEOUT`）时跳过绘图，报告趋势章节省略，不中断整体流程。
- 运行 `daily_report.py` 后应生成 `context/YYYY-MM-DD.json`；改 `data/last_values.json` 模拟 VIX +22% 后运行，`breach.triggered` 应为 `true` 且 `breach.indices` 含 VIX 明细（name/current/previous/change_pct/threshold/level），`search_keywords` 3-5 个含 "VIX surge/drop {date}"。
- 恢复正常基准后运行，`breach.triggered=false`、`breach.indices=[]`、`search_keywords == ["market summary {date}"]`。
- 断网/取数全失败时运行：日报正常生成、退出码 0；context 生成失败仅记日志（或生成 breach=false 的 context），不中断主流程。
- 连续两次运行同一场景：当日 context 被覆盖且 JSON 有效；`alerts/` 无新增文件、`data/alerts.log` 前后一致（collect_breaches 纯计算不触碰）。
- 验证后必须恢复 `data/last_values.json` 原值并清理验证期临时文件（context/ 为生成物可保留当日真实状态）。
- **阈值配置化（五期）**：`config.json` 缺失/损坏 → 回退内置默认、退出码 0、不崩溃；`ALERT_THRESHOLD_*` / `STATUS_THRESHOLD_*` / `TREND_CHART_DAYS` / `HISTORY_RETENTION_DAYS` 经 env 覆盖生效（调用时复核）；改 `config.json` 的 vix 为 22/35 后运行 `daily_report.py`，VIX 状态标签按新阈值输出（验证后恢复 20/30）；pytest 在 conftest 隔离下恒用默认，不读用户 config.json。
- **盘中快照扩展（七期）**：4 个 Hermes cron（A 股午盘 11:30 / A 股收盘 15:00 / 美股开盘 21:30 / 美股午盘 00:00，北京时间）分别传 `--market`/`--time`；`fetch_all(market)` 仅取对应子集（a-share=SH/SZ/CYB，us=GSPC/IXIC，不含波动率）；`render_snapshot` 单板块（a-share 只含 SH/SZ/CYB、us 只含 GSPC/IXIC，无波动率章节），A 股快照按北京时间归档、us 按美东日期；创业板 `399006.SZ` 入 SYMBOLS（8 键，阈值 `alert.cyb=5`），CYB 告警经 `ALERT_THRESHOLD_CYB` env 覆盖；快照存 `reports/snapshots/YYYY-MM-DD-{market}-{time}.md`；单测 `tests/test_phase7.py` 覆盖符号/市场日期/市场过滤取数/单板块渲染/suffix/创业板告警/复合名防碰撞/跨市场去重/入口编排（共 170 passed）。
- **A 股板块热度（八期）**：`daily_report.py` 日报「A 股大盘」下方新增「🔥 A 股热点板块 Top 5」表（板块/涨跌幅/成交额/领涨股，涨跌幅带正负号、成交额 "X.X亿"，按涨跌幅降序 Top5 不设阈值）；`context/YYYY-MM-DD.json` 新增 `sector_heat` 键（5 条 {name,change,turnover,top_stock}）；`search_keywords` 注入板块名（`"{板块名} surge/drop {date}"`，方向感知，不触发独立告警）；板块取数失败/超时（10s 线程限时）/缺必需列均降级为「数据暂缺」、退出码 0；单测 `tests/test_phase8.py`（16 条：取数成功/异常/缺列/超时、表格渲染/空态/负值、context 键、关键词注入/方向、入口透传）全绿，全量 `pytest` 186 passed。
- **分市场趋势图（九期）**：日报新增美股 2×1（`charts/YYYY-MM-DD-us-trend.png`）与 A 股 3×1（`charts/YYYY-MM-DD-cn-trend.png`）趋势图；`render_market_trend_chart(history, date, market)` 复用波动率图绘图范式、独立 `MARKET_CHART_TIMEOUT=5` 限时、串行渲染、部分序列缺数据显示灰色英文 "Insufficient Data" 占位、整体行数<2 返回 None 省略章节；`render_report` 加 `us_trend_chart`/`cn_trend_chart` 默认参数，报告新增「📈 美股大盘近30日趋势」「📈 A 股大盘近30日趋势」两章节（分别插在美股大盘 / A 股大盘板块后）；`daily_report.py` 单次 `load_history()` 复用供三图；单测 `tests/test_phase9.py`（15 条）全绿，全量 `pytest` 211 passed。
- **Web 看板（十一期）**：`venv/Scripts/python -m uvicorn web.app:app --port 8000` 启动后访问 `http://localhost:8000` 看完整看板（概览表 10 指数 / 4 组趋势图 / A 股板块热度 Top5 / 告警记录）；`pytest tests/test_web.py -v` 覆盖解析纯函数与 4 端点（20 条，全量 231 passed）；`/api/history` 末条 value 与 `data/history.json` 最后一条逐值一致、`/api/latest` 涨跌幅与相邻记录手算一致；`alerts/` 为空时页面显示「暂无告警记录」不崩；断网 / CDN 不可达时图区降级「图表加载失败」、其余模块正常；web 为独立模块，零侵入 `daily_report.py` / `snapshot_report.py` / `src/*`，不写任何数据文件。
- **回测验证（十三期）**：`venv/Scripts/python scripts/backtest.py` 终端输出每标的一行摘要（告警次数 / 年化 / 胜率@1d / 有效触发率）+ 总耗时 + `reports/backtest_report.md` 生成，耗时 <5s、退出码 0；`--history <临时小文件>`（有效交易日 <30）时优雅退出（退出码 0、提示信息、无报告文件、data/ 无任何写入）；回测仅读 `data/history.json`、复用生产 `check_breach` 语义（严格大于、实时阈值、缺口断开），不写 data/alerts/context，不联网；新增/修改 `scripts/backtest.py` 或阈值逻辑后跑 `venv/Scripts/python -m pytest tests/test_backtest.py -v`（10 条纯逻辑测试全绿）。
- **日报图片化（十四期）**：`daily_report.py` 末尾容错调用 `render_report_image(date)`（失败仅记日志、退出码恒 0）生成 `reports/images/YYYY-MM-DD.png`；Hermes 追加「AI 解读」章节后通过 `venv/Scripts/python scripts/render_report_image.py --date YYYY-MM-DD` 独立重渲染含解读图；依赖 imgkit（`requirements.txt` 已加）+ 本地 wkhtmltoimage（winget 装 wkhtmltopdf），解析严格依赖 `render_report` 的 Markdown 结构（标题行 `## ...` / `| 指数 | 收盘价 | 涨跌幅 | 趋势 |` 表 / `![...](charts/...)` 引用 / 标题含「解读」章节 / `alerts/{date}-close.md` 附录块）；单测 `tests/test_phase14.py`（17 条：解析/渲染/尺寸/容错/接线）全绿，全量 `pytest` 通过。
- **美股去重 + 浅色主题（二十五期）**：美股去重由 `daily_report.py` 的 `_is_us_duplicate_day(history, record)`（判定集 GSPC+IXIC，排除 MOVE 浮点抖动）在 `append_history` 前加门，非交易日（美股值与最近记录全同）整条跳过写历史；混合日（美股未动但 A 股/BTC 变动）按 PRD 字面整条跳过，当日日报/context 仍完整；`pytest tests/test_phase25.py -v` 覆盖纯逻辑 ×4 + 接线 ×2（既有断言零改动，全量 `pytest` 382 passed）；浅色主题：`venv/Scripts/python -m uvicorn web.app:app --port 8002`（另起未缓存端口防模板/静态缓存）启动后浏览器验证——初始深 `rgb(11,14,20)`、点击切 `html.light` + `localStorage["mp-theme"]=="light"` + 浅 `rgb(245,245,245)`、刷新保持、再点回深；`tab.evaluate` 查 `document.styleSheets` 含 `:root.light` 规则证伪 CSS 缓存。
- **cron 自动提交推送（二十六期）**：三入口 main() 末尾自动 `git add -A` + commit（`auto: {date} {type}`）+ push origin master（默认开启，`AUTO_PUSH=0` 关闭）；无改动（`git status --porcelain` 空）跳过、幂等（F4）；commit message 全 ASCII：daily→`auto: {date} daily report`、snapshot→`auto: {date} {market} {time} snapshot`、opening→`auto: {date} {market} opening analysis`（F5）；push 经 Clash 代理 `http://127.0.0.1:7890` 仅注入子进程 env 副本（F3）；失败仅 print `[auto-push] Failed`、退出码恒 0（F6 重试由 `scripts/push_retry.sh` + Hermes cron 承担）；pytest 在 conftest `AUTO_PUSH=0` 下恒跳过、无真实推送；单测 `tests/test_phase26.py`（11 条）覆盖门控 / message 格式 / 代理注入 / 失败不抛；本地反复跑务必 `AUTO_PUSH=0`，真跑验证限一次（会 push 触发 Railway 重部署，且遗留 Hermes「每日数据更新」cron 可能抢先提交）。


## 已知问题

<!-- 记录不稳定测试、环境依赖、跳过的检查等 -->
- （暂无）
