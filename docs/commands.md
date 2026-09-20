# 命令说明

> 列出项目所有验证命令。Agent 完成修改后必须运行相关命令。
> 所有命令需先激活 venv（Windows: `venv/Scripts/activate`），或直接调用 `venv/Scripts/python`。

## 快速检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/python -m pytest tests/ -v` | 运行单元测试 | 改了函数逻辑 / 提交前 |
| `venv/Scripts/python daily_report.py` | 运行主脚本（完整闭环：取数→报告→趋势图→写历史→写缓存） | 改了数据获取/报告生成/错误处理逻辑 |
| `venv/Scripts/python -m uvicorn web.app:app --port 8000` | 启动 Web 看板（bento 栅格；只读展示 history / context / alerts，5 个 JSON API） | 改了 `web/` 模块 / 提交前 |
| `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **Web UI 验收（Playwright，改动前端后必跑）**：自动挑空闲端口起 uvicorn → 1920×1080 / 1280×720 / 375×812 三视口断言（页面总高 / 零横向溢出 / **canvas 位图 == 显示尺寸** / 栅格列数 5·2·3·4 / 卡片 token / 模块行数 / 4 类别 tab 切换 / 主题切换 / 移动端抽屉 / console error=0）；截图与 JSON 报告落 `%TEMP%\marketpulse-verify\`（不落仓库）。**三态输出（2026-09-20 起）**：`PASS` / `FAIL` / `SKIP`，汇总同时给三个计数 + `上游探测: macro=OK econ=OK`。`SKIP` = **该条未判定，原因是上游不可用（独立直连探测确认）**，**不等于通过** —— 看到 SKIP 先查上游状态，不要先查代码；`--strict` 让 SKIP 也判失败（`MP_VERIFY_UPSTREAM_DOWN=1` 可强制判 DOWN，仅供验证分层机制本身）。退出码：有 FAIL → 1；仅 SKIP → 0（`--strict` 时 1） | 改了 `web/templates` / `web/static` / `verify_ui.py` 后 |
| `venv/Scripts/python scripts/backfill_history.py [--dry-run] [--symbols SH,SZ] [--no-patch-existing]` | 历史数据回填（补 1Y）：走 `_yahoo_chart_get` 双主机轮换；**A 股 Yahoo 覆盖不足时改走 AkShare**（`399006.SZ` Yahoo 仅 1 天 → AkShare 243 天，daemon 线程 15s 限时）；按符号所属市场时区归档日期；**只新增 date 不存在的行**；丢弃「仅 BTC 有值」的非交易日；AkShare 补的 A 股键**只补既有行中为 `None` 的位置**（绝不覆盖非空值，`--no-patch-existing` 关闭）；经 `merge_history` 按 date 合并；收尾按 date 升序重排并断言；**不碰 `last_values.json`**。`--dry-run` 只打印计划不写盘。**执行前必须先备份 `data/history.json`**；前置：`history.retention_days=365` | 需要补齐 1Y 历史 / 改了回填逻辑后 |
| `venv/Scripts/python scripts/backtest.py [--history PATH]` | 运行独立回测脚本（验证告警阈值有效性）：复用生产 `check_breach` 语义回放 `data/history.json`，输出各标的告警次数 / 年化频率 / WARN-ALERT 分布 / 1·3·5·10 日平均后效 / 胜率 / 有效触发率，生成 `reports/backtest_report.md`；`--history` 指定只读历史文件（用于数据不足验证）；全程 <5s、不联网、零副作用 | 改了 `scripts/backtest.py` / 阈值逻辑后回归 |
| `curl http://localhost:<port>/api/news` | 最新资讯端点（`data/news.json` 只读；缺失/坏文件 → 200 空结构） | 改 `web/app.py` 资讯链路 / Hermes 接入后 |
| `venv/Scripts/python scripts/migrate_to_sqlite.py [--db PATH]` | 一次性迁移 history.json → SQLite（幂等重跑；`--db` 可演练） | 存储层切换 / 数据校验 |
| `venv/Scripts/python scripts/backup_db.py [--db] [--backup-dir]` | 按月导出 history 备份（当月覆盖/历史月冻结） | daily 后自动执行；手动补备份 |
| `venv/Scripts/python scripts/render_report_image.py --date YYYY-MM-DD` | 独立重渲染日报图片（Hermes 追加 AI 解读后重渲染含解读图）；依赖 imgkit + 本地 wkhtmltoimage（先 `pip install -r requirements.txt` 装 imgkit，再 winget 装 wkhtmltopdf）；失败仅退出码非 0，不影响日报 md | 改了 `src/image_renderer.py` / 模板 / 重渲染入口后 |
| `venv/Scripts/python -m pytest tests/test_phase26.py -v` | 自动提交（`src/git_ops.py`）行为单测（**16 条**）：env 门控 / 无改动跳过 / commit message 格式 / 代理注入不污染 env / 失败不抛异常 / **路径白名单实参 + status 同范围 + 源码 WIP 不触发提交 + `reports` 不入列 + 忽略文件不触发** | 改了 `src/git_ops.py` 后 |
| `git status --porcelain -- data context alerts` | 与 `git_ops._has_changes` **同口径**：查看"哪些改动会被自动提交"（源码/测试/文档改动**不该**出现在输出里） | 排查"改动没进 commit" / 核对自动提交范围 |
| `venv/Scripts/python scripts/probe_cn_macro.py [--include-rejected] [--show-cols]` | 中国宏观数据源回归（AkShare 13 个在册接口：可用性 / 最新数据月份 / 耗时 / 行数 / 列名）；退出码非 0 若任一在册接口变为不可用或最新月份落后 > 阈值（季度 GDP 给 6 个月）。`--include-rejected` 附带跑 8 个已否决接口（东财报告族，仅作对照、不参与退出码）。JSON 报告落 `%TEMP%\marketpulse-cn-macro-probe\` | 改了 `src/cn_econ_fetcher.py` / 怀疑接口停更 / 定期回归 |
| `venv/Scripts/python -m pytest tests/test_cn_econ.py -v` | 中国宏观单测（14 条，不联网）：`_parse_ym` / 缺列守卫 / 失业率长表 / 房价双城 / credit 主列 / **增长轴取 PMI 水平** / GDP 冲突上报 / 同比按键找去年同月 / 部分失败缓存 / 全失败不缓存 / bond 空结果 / 零写盘 | 改了 `src/cn_econ_fetcher.py` 或 `/api/econ/cn` 后 |
| `curl -s "localhost:<port>/api/econ/cn?group=price"` | 中国宏观分组端点（group ∈ price/growth/money/rate/labor/estate；省略 = 全量 ≈10s）；非法组名 → 422。**利率三条序列（lpr/shibor/bond_10y）带 `chg_6m_bp`**（与 6 个月前比的 bp，基准点按日期/月份定位），其余序列该键为 `null` | 改了 `/api/econ/cn` / 前端分组加载后 |
| `curl -s localhost:<port>/api/cn/quotes` | 中国行情（CNY=X + 中债 10Y 国债 + 信用利差 bp）；失败降级 200 + `failed` 列出三项 | 改了 `/api/cn/quotes` 后 |
| `venv/Scripts/python -m pytest tests/test_econ_values.py -v` | 事件结果值层单测（**25 条，不联网**，固定 JSON fixture）：ET 转换（含跨日与夏令时两侧）/ 按月分段 / 标题精确匹配（同族兄弟不得被收编）/ GDP 按期次锁 / `forecast:0` 与 `None` 不可混 / 同日双非农择优与歧义告警 / PCE 首选标题优先 / 只 enrich 既有行 / unit 键缺失不补单位 / 整源失败降级 / preserve 语义 / 只 UPDATE 不 INSERT / 8 列迁移 | 改了 `src/econ_values.py`、`src/storage.py` 的值层或 `/api/timeline` 后 |
| `venv/Scripts/python -c "import sqlite3;c=sqlite3.connect('file:data/marketpulse.db?mode=ro',uri=True);print(c.execute('select count(*) from econ_events where actual is not null').fetchone())"` | 值层落库**独立核算**（绕过 API 与 storage 代码路径；窗口内计数）+ `curl -s "localhost:<port>/api/timeline?days=90&future_days=30"` 里事件对象须含 `actual` 键（值可 null） | sync 真跑后核对落库结果 |
| `venv/Scripts/python -m pytest tests/test_web.py -v -k auth` | web 访问控制单测（**9 条**）：无凭据 401 + `WWW-Authenticate`、4 页 10 API 与 `/static` 全覆盖、错密码 401、`/healthz` 无凭据 200、`MP_AUTH_DISABLED=1` 全站 200、未配置时 fail-open 且有启动 WARNING、畸形头 401 不 500、`Basic` 前缀大小写不敏感 | 改了 `web/app.py` 的鉴权中间件 / `/healthz` / `railway.toml` 后 |
| `curl -s -o /dev/null -w "%{http_code}\n" localhost:<port>/` 三连（401 / 200 / 200） | 鉴权三连：`/` 无凭据 **401** · `/healthz` 无凭据 **200** · `-u user:pass` 访问 `/` **200**（线上验收同样三连，`/` 必须 401） | 配好 `MP_AUTH_USER`/`MP_AUTH_PASS` 后（本地与线上都要验） |

## 完整检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/pip install -r requirements.txt` | 安装/校验依赖 | 环境变更 / 提交前 |
| `venv/Scripts/python -m pytest tests/ -v` | 完整测试套件 | 提交前 |
| `venv/Scripts/python -c "import matplotlib; matplotlib.use('Agg')"` | 校验 matplotlib 可用（Agg 无头后端） | 环境变更 / 提交前 |

## 何时跑什么

| 改动类型 | 必须运行 |
|---|---|
| **看到 `verify_ui.py` 报 `SKIP` 时**（2026-09-20 起） | **先看那行 `上游探测: macro=? econ=?`，再去查上游** —— `SKIP` 表示"该条无法判定，因为上游不可用（独立直连探测确认）"，**不是通过也不是回归**。要"一条都不许未判定"就加 `--strict`（有 SKIP 即退出码 1）。⚠️ 别把 SKIP 当绿灯，也别因为 SKIP 去改前端代码 |
| 数据获取逻辑（美股 + A 股 + 波动率 + 另类资产共 10 标的：GSPC/IXIC/VIX/VXN/MOVE/SH/SZ/CYB/GLD/BTC-USD，含创业板 399006.SZ） | 主脚本 + 快照脚本 + 相关单元测试 |
| 报告/快照/趋势图生成 | 主脚本 + 快照脚本（检查输出内容与 PNG，含 `--market`/`--time` 分档） |
| 状态判断/涨跌幅计算 | 相关单元测试 |
| history 读写/滚动 | 相关单元测试（test_analyzer.py TestHistory） |
| 错误处理/离线容错 | 主脚本（断网场景） |
| 日报图片化（`src/image_renderer.py` / 模板 / 重渲染入口） | 跑 `scripts/render_report_image.py --date` 验证 PNG 生成（宽 600、≤800KB、含解读章节）、相关单测 `tests/test_phase14.py` |
| 中国宏观页 `/macro/cn`（2026-09-14） | `scripts/probe_cn_macro.py`（数据源回归，退出码非 0 即停更）+ `pytest tests/test_cn_econ.py` + `pytest tests/test_web.py`（新增 6 条）+ `curl` 两个新端点（含空态）+ **`verify_ui.py`（新增 `assert_macro_cn_page` 与 F-5 补强，改了模板/静态/侧栏必跑）** |
| 事件日历同步 cron（2026-09-19 交接，**待接入**） | 每天一次 `venv\Scripts\python -m scripts.sync_econ_calendar`（落盘后自动 commit+push，消息 `auto: {date} econ-calendar`）。判据：stdout 的 `[1/3]` 事件条数、`[values]` 值层命中数、`[news]` 写入条数、`[git] 自动提交推送` 四行；退出码 0/1/2 分别=正常/有源失败/两源全失败。`--skip-values` 可只跳过结果值层。提示词全文见 `tasks/2026-09-18-event-timeline-page/journal.md` §14.4 |
| 事件结果值层（2026-09-19） | ① 单测 `pytest tests/test_econ_values.py`；② sync `--dry-run`（看命中率且**不写库**）→ 真跑 `AUTO_PUSH=0 ... --skip-news`（**限一次**；`--skip-news` 只为缩范围，值层照样跑）⇒ 判据 `[values] 值层：命中 N/M 条，写入库 K 组`（**N==K**，差即"骨架里没该行"）+ 独立核算 `actual is not null` 计数；③ **`verify_ui.py`（必跑）**：新增 `EV-*` 组（键透传 / 三方对账 sqlite vs API vs DOM / 真实数据锁死 / 无 0-None 混淆 / unit 缺失不加后缀 / 待公布 / 768-375 两态断点），既有 `TL-*` 16 条复跑仍绿。前置：`storage.init_db()` 的 8 列迁移必须已跑（`PRAGMA table_info(econ_events)` 含 `actual`），否则 UPDATE 会 `no such column` |
| web 访问控制（2026-09-19，HTTP Basic Auth） | ① `pytest tests/test_web.py -v -k auth`；② 本地三连（`/`=401、`/healthz`=200、`-u user:pass` `/`=200）；③ **`verify_ui.py`（必跑）**：新增 `AUTH-*` 7 条（自带带鉴权实例；含 Playwright `http_credentials` 打开 `/` 证明静态资源在鉴权下正常送达）。⚠️ `main()` 起的主实例已注入 `MP_AUTH_DISABLED=1` ⇒ 既有 700+ 条断言零改动；**给 `new_context` 逐个加凭据会与既有信号耦合，不要那样做**。🔴 改 `railway.toml` 的 `healthcheckPath` 后必须确认线上部署不进重启循环 |
| cron 自动提交推送（二十六期） | 无需手动；daily_report / snapshot_report / opening_analyzer 末尾自动 commit+push；本地验证用 `AUTO_PUSH=0` 关闭（如 `AUTO_PUSH=0 venv/Scripts/python daily_report.py`）；真跑验证限一次（会 push 触发 Railway 重部署，且遗留 Hermes「每日数据更新」cron 可能抢先提交）。🔴 **范围白名单由 pathspec 强制（2026-09-20）**：`_commit` = `git add <paths>` + `git commit -m <msg> -- <paths>`；只收窄 `git add` 不够 —— 不带 pathspec 的 `git commit` 会提交**整个暂存区**，把别处已 staged 的删除/重命名一起带走（事故 `6ec1562`）。护栏 `pytest tests/test_phase26.py -v` |
| 仓库外数据同步 cron（2026-09-20 改 script 模式） | Hermes job `6f6e40a6f8b4`（`*/5`）：**script 模式**，wrapper `D:\hermes\scripts\marketpulse_autopush.py` → `scripts/auto_commit_data.py` → 复用 `git_ops` 白名单（data/context/alerts）。判据：`hermes cron runs 6f6e40a6f8b4` 显示 `completed`，输出一行 `[data-commit] 改动=<有/无>…`；`hermes cron doctor` 无 issue。⚠️ **wrapper 用 `.py` 不用 `.sh`**：本机实测 `.sh` 在**定时（builtin）路径**下稳定 `Script exited with code 1`，而 `.py` 正常（详见 `docs/pitfalls.md`） |

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
- **Web 看板（十一期 / 二十八期 / Bento 重构 2026-09-11）**：`venv/Scripts/python -m uvicorn web.app:app --port 8000` 启动后访问 `http://localhost:8000` 看完整看板（bento 栅格：4 KPI 卡 + 趋势**四图合一**（4 类别 tab，7D/30D/90D/1Y）+ 自选列表迷你条 + 市场概览 6 小卡 + A 股板块 Top5 + 美股行业板块横幅条 + 告警记录 + 3 个静态占位卡）；**改动 `web/templates` / `web/static` 后必须跑 `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`**，不要以 `curl 200` 或肉眼看代替——它自动挑空闲端口（规避 Jinja2 模板缓存 + 跨端口 CSS 缓存假阴性）并量化断言页面总高 ≤1240@1920、三视口零横向溢出、**canvas 位图 == 显示尺寸**（C2 回归护栏）、栅格列数、4 tab 切换、主题切换、移动端抽屉、console error=0；`pytest tests/test_web.py -v` 覆盖解析纯函数与 **5 个端点**（**59 条**：含 `us_sector_heat` 暴露 / `/api/macro` 三级回退（env > config > 内置默认）/ `days` 边界 91→200、366→422，全量通过）；`/api/history` 末条 value 与 `data/history.json` 最后一条逐值一致、`/api/latest` 涨跌幅与相邻记录手算一致；`/api/watchlist` 默认（无 watchlist.stocks）返回 200 + 空结构（前端整卡隐藏），配置后返回 200 + 实时 stocks/trend（失败行 value=null、前端显示「数据暂缺」，不 500）；`alerts/` 为空时页面显示「暂无告警记录」不崩；断网 / CDN 不可达时图区降级「图表加载失败」、其余模块正常；web 为独立模块，零侵入 `daily_report.py` / `snapshot_report.py` / `src/*`，不写任何数据文件。
- **回测验证（十三期）**：`venv/Scripts/python scripts/backtest.py` 终端输出每标的一行摘要（告警次数 / 年化 / 胜率@1d / 有效触发率）+ 总耗时 + `reports/backtest_report.md` 生成，耗时 <5s、退出码 0；`--history <临时小文件>`（有效交易日 <30）时优雅退出（退出码 0、提示信息、无报告文件、data/ 无任何写入）；回测仅读 `data/history.json`、复用生产 `check_breach` 语义（严格大于、实时阈值、缺口断开），不写 data/alerts/context，不联网；新增/修改 `scripts/backtest.py` 或阈值逻辑后跑 `venv/Scripts/python -m pytest tests/test_backtest.py -v`（10 条纯逻辑测试全绿）。
- **日报图片化（十四期）**：`daily_report.py` 末尾容错调用 `render_report_image(date)`（失败仅记日志、退出码恒 0）生成 `reports/images/YYYY-MM-DD.png`；Hermes 追加「AI 解读」章节后通过 `venv/Scripts/python scripts/render_report_image.py --date YYYY-MM-DD` 独立重渲染含解读图；依赖 imgkit（`requirements.txt` 已加）+ 本地 wkhtmltoimage（winget 装 wkhtmltopdf），解析严格依赖 `render_report` 的 Markdown 结构（标题行 `## ...` / `| 指数 | 收盘价 | 涨跌幅 | 趋势 |` 表 / `![...](charts/...)` 引用 / 标题含「解读」章节 / `alerts/{date}-close.md` 附录块）；单测 `tests/test_phase14.py`（17 条：解析/渲染/尺寸/容错/接线）全绿，全量 `pytest` 通过。
- **美股去重 + 浅色主题（二十五期）**：美股去重由 `daily_report.py` 的 `_is_us_duplicate_day(history, record)`（判定集 GSPC+IXIC，排除 MOVE 浮点抖动）在 `append_history` 前加门，非交易日（美股值与最近记录全同）整条跳过写历史；混合日（美股未动但 A 股/BTC 变动）按 PRD 字面整条跳过，当日日报/context 仍完整；`pytest tests/test_phase25.py -v` 覆盖纯逻辑 ×4 + 接线 ×2（既有断言零改动，全量 `pytest` 382 passed）；浅色主题：`venv/Scripts/python -m uvicorn web.app:app --port 8002`（另起未缓存端口防模板/静态缓存）启动后浏览器验证——初始深 `rgb(11,14,20)`、点击切 `html.light` + `localStorage["mp-theme"]=="light"` + 浅 `rgb(245,245,245)`、刷新保持、再点回深；`tab.evaluate` 查 `document.styleSheets` 含 `:root.light` 规则证伪 CSS 缓存。
- **cron 自动提交推送（二十六期）**：三入口 main() 末尾自动 `git add -A` + commit（`auto: {date} {type}`）+ push origin master（默认开启，`AUTO_PUSH=0` 关闭）；无改动（`git status --porcelain` 空）跳过、幂等（F4）；commit message 全 ASCII：daily→`auto: {date} daily report`、snapshot→`auto: {date} {market} {time} snapshot`、opening→`auto: {date} {market} opening analysis`（F5）；push 经 Clash 代理 `http://127.0.0.1:7890` 仅注入子进程 env 副本（F3）；失败仅 print `[auto-push] Failed`、退出码恒 0（F6 重试由 `scripts/push_retry.sh` + Hermes cron 承担）；pytest 在 conftest `AUTO_PUSH=0` 下恒跳过、无真实推送；单测 `tests/test_phase26.py`（11 条）覆盖门控 / message 格式 / 代理注入 / 失败不抛；本地反复跑务必 `AUTO_PUSH=0`，真跑验证限一次（会 push 触发 Railway 重部署，且遗留 Hermes「每日数据更新」cron 可能抢先提交）。

- **动态告警阈值（二十七期）**：`check_breach(sym, current, last, history=None)` 在 `alert.dynamic=true`（默认）时按历史波动率计算滚动窗口阈值：取 `history`（剔除当日、取最近 `lookback_days=20` 个相邻日收益）的均值 + `k_factor=2.0`×样本标准差作为动态阈值；样本不足 20 / 零方差 / 漂移为负（阈值≤0）时回退固定阈值（`alert.{sym}`）。返回 dict 新增 `threshold_mode`（`dynamic`/`fixed`）与 `dynamic_threshold`（动态时为滚动值、否则 None）。日报/快照/context/回测均透传 `history`（取数后、写历史前的内存变量，天然不含当日）；回测 `collect_triggers` 回放第 i 对时用 `history[:i]`（窗口含到 prev 为止，等价于生产「昨日收益是分布最新成员」）。验证：`pytest tests/test_phase27.py -v`（29 条：config 新键 + bool 合并 / 纯函数 / 模式标注 / 消费点接线 / 回测窗口化全过）；`config.json` 的 `alert.dynamic=false` 强制固定阈值，`alert.lookback_days`/`alert.k_factor` 调整窗口与灵敏度。
- **美股午盘日期门 + Yahoo 403 双主机轮换（本任务 2026-09-05）**：`pytest tests/test_phase26_snapshot.py -v`（5 条：Yahoo 主机轮换 query1→query2、双主机全 403 经 fetch_with_retry 返回 None、404 不轮换、get_market_date 时区锁 a-share=北京/us=美东、render_snapshot 单市场 None 单元格 us/alt→数据暂缺 & a-share→休市）全绿；`TZ=America/New_York date +%Y-%m-%d` 应比 `date +%Y-%m-%d` 早 1 天（北京 00:00=美东前一日，根因实证）；`AUTO_PUSH=0 venv/Scripts/python snapshot_report.py --market us --time noon` 真实闭环应取回 GSPC/IXIC 真实值（非 None），history 当日行 gspc/ixic 非 None；Hermes cron「美股午盘快照」prompt 已改按美东日期定位（hermes cron edit 4337889a4cc3），删"日期==北京今天"比对。


## 已知问题

<!-- 记录不稳定测试、环境依赖、跳过的检查等 -->
- （暂无）
