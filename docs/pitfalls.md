# 易错点

> 记录反复出现的问题和坑。Agent 修改相关模块前必须先读。

## 通用

- **edit 工具多行替换容易误吞相邻代码**：Hy3 在多期实施中反复遇到——ASCII `+` 被当字面量、长 MATCH 块缺 `»` 导致误删相邻函数。多行编辑优先用 `write_file` 整体重写，避免 patch 锚点漂移。
- **验证期模拟数据后必须恢复**：改 `last_values.json` 模拟异动后运行入口，若取数成功缓存会被真实值覆盖（正常）；若取数失败模拟值会残留——验证前先备份、验证后恢复。
- **monkeypatch 路径常量要打在使用方模块**：`CHARTS_DIR`/`ALERTS_DIR`/`CONTEXT_DIR` 等在导入时绑定，测试必须 `monkeypatch.setattr(使用方模块, "XXX_DIR", tmp_path)`，打在定义方模块不生效。

## 模块 src/（一期：数据获取）

- **Yahoo Finance 对本机 IP 限流（HTTP 429 / ConnectionResetError 10054）**：连续取数会触发 IP 级限流，query1 返回 429，query2 返回 403。脚本按设计容错（单源失败不影响整体，退出码恒 0），但报告会缺数据。应对：等待限流解除、换网络出口、或在脚本前加代理。
- **yfinance 一次打多个子请求更易触发 429**：改为单请求直连 Yahoo chart REST（`query1.finance.yahoo.com/v8/finance/chart`），复用 Session + 退避，显著降低限流概率。
- **Yahoo chart 需 query1/query2 双主机轮换**：单主机（query1）遇 403/429 时，对同一主机的重试永远拿不到数据（主机级封锁，非瞬时限流）；`src/fetcher.py` 的 `_yahoo_chart_get` 逐 `YAHOO_HOSTS` 轮换，403/429/5xx/连接错误/超时切下一主机，404 等确定失败立即 `raise_for_status` 不浪费轮换。新增 Yahoo chart 调用点必须走 helper，不得再直连 `query1` 单主机（二十六期，2026-09-05）。
- **自选股 Yahoo 窗口过窄（任务 F）**：`src/fetcher.py` 的 `_fetch_yahoo_watch` 原 `range="1mo"` 仅含 ~20 交易日，`_series_tail(30)` 截不出 30 点 → 自选股图稀疏/被截短。改 `range="3mo"`（含 ~63 交易日）再交 `_series_tail(30)` 截最新 30；A 股源（70 自然日）与兜底接口不动。
- **新浪/AkShare 沪 ETF 日线停更（数据源缺口，任务 I/J）**：`515300/510300/512890` 等沪 ETF 自 09-03 起新浪 + `yfinance .SS` 日线均停更（个股正常），属外部数据源缺口非本地 bug；实时价 `meta.regularMarketPrice` 仍正常 → 表格价新、图序列旧的错位观感。应对：观察自愈或改走东财 `fund_etf_hist_em` 备源（须先验证 EM 可达）；勿误判为代码缺陷。
- **北京 00:00 = 美东前一日，00:00 槽位（us-noon）"报告日期==北京今天"检查必然失败**：美股午盘快照 cron 在北京 00:00 触发，此时美东为前一日，快照文件名永远用美东日期（analyzer.get_market_date 按市场时区），与北京"今天"差 1 天。Hermes 推送 prompt 校验快照必须用 `TZ=America/New_York date` 取美东日期，绝不能和"今天(北京)"比对，否则每晚必然跳过推送（二十六期，2026-09-05）。
- **半迁移状态会导致 NameError**：一期到二期过渡期间，`fetch_all()` 的 fred 分支引用了已删除的 `has_valid_fred_key`/`fetch_move`，直接运行会崩溃。改代码后必须跑完整闭环验证。

## 模块 src/（二期：拆分+趋势图+快照）

- **matplotlib 在 Python 3.14（cp314）有 wheel**：实测 `matplotlib>=3.7.0` 正常安装，无需降级或换源。
- **Windows 无 `signal.SIGALRM`**：趋势图 3 秒限时用 daemon 线程 + `join(3)` 实现；超时后线程继续在后台，进程退出即终止，不会拖慢主流程。
- **趋势图首次运行无数据是设计行为**：`render_trend_chart` 排除当日记录且需 ≥2 条历史，不是 bug。验证趋势图需先积累历史。
- **趋势图 matplotlib 警告 "categorical units"**：x 轴日期是字符串被当分类轴。改为用真实 `datetime` 作 x 轴（`datetime.strptime`）消除警告。
- **快照不写 history.json**：snapshot_report.py 只读 `last_values.json` 做告警基准，不写历史、不算涨跌幅，避免多时点写冲突。
- **趋势图标签用英文**：避免中文字体在各平台(QQ/macOS/Linux)渲染不一致。

## 模块 src/（三期：告警）

- **告警基准必须用开头加载的旧 `last_values`**（决策 G）：收盘入口在 `save_last_values` 之前调用 `run_alert_checks`，若基准误用当日新缓存会导致告警永远不触发/误触发。
- **`alerts.log` 只保留当日行**：`_mark_alerted` 原子重写整个文件，旧日行自动清除——跨日运行天然重置去重状态，勿手工追加。
- **路径常量打补丁位置**：`alerter.py` 的 `ALERTS_DIR`/`ALERTS_LOG` 是导入时绑定，测试必须 `monkeypatch.setattr(al, "ALERTS_DIR", ...)`。
- **阈值 env 变量泄漏**：测试必须 `monkeypatch.delenv("ALERT_THRESHOLD_VIX", raising=False)` 隔离宿主环境。
- **变化率"严格大于"才触发**：恰好等于阈值不告警；断言用 `pytest.approx` 避免浮点边界误判。

## 模块 src/（四期：context + AI 解读）

- **`CONTEXT_DIR` 是 reporter 导入时绑定**：`generate_context` 测试必须 `monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")`。
- **context 原子写**：临时文件 `context/YYYY-MM-DD.json.tmp` + `os.replace`；断言无 `.tmp` 残留。Hermes 读取依赖"要么旧文件要么完整新文件"。
- **`generate_context` 必须在 `append_history` 之后调用**（决策 D）：history_30d 才含当日。
- **`search_keywords` 方向语义**（决策 C）：变化率 ≥0 用 "surge"、<0 用 "drop"；这是 tavily 归因的输入，改词直接影响搜索命中率，需同步 Hermes Prompt。
- **`breach.indices` 字段契约是 Hermes Prompt 的输入**：字段名按 PRD 定稿，改字段必须先改 `_breach_item` 再同步 Hermes Prompt。
- **collect_breaches 纯计算无副作用**：不写告警文件、不改 alerts.log；context 的 breach.triggered 不受午盘去重影响。

## 模块 src/（五期：配置化）

- **conftest 隔离是测试不崩的前提**：`tests/conftest.py` 顶层 `os.environ["CONFIG_PATH"]` 指向不存在文件，collection 前生效；若无隔离，用户定制 config.json 会被 import 快照读入，classify 边界/90 天滚动/30 天窗口断言全崩。
- **reload 接线测试必须 finally 恢复**：用 `importlib.reload` 验证 config→常量后，finally 须恢复 CONFIG_PATH + 再次 reload，否则污染后续用例。
- **bool 是 int 子类**：`_valid_number` 须显式 `not isinstance(v, bool)`，否则 JSON `true` 被当 `1` 通过校验。
- **retention 裁剪只在 `append_history`**：`load_history` 不裁剪/不传参。
- **读时剔除 + merge_history 配套（二十七期）**：`daily_report.py`/`snapshot_report.py`/`opening_analyzer.py` 读 history 后均先剔除自身 date 行（趋势图/相关性/连涨/告警基准用），`merge_history` 写前同样剔除——保证同日多入口（开盘/快照/收盘）各自只更新本市场子集，末点引用最新定稿而非盘中残留。切勿在入口内对 history 整行覆盖（会吞掉其它市场当日数据）。
- **merge_history 不写 alt/VIX（二十七期）**：仅 a-share={SH,SZ,CYB}、us={GSPC,IXIC} 并入；GLD/BTC 走另类资产展示不进历史、VIX 已有美东前一日收盘值避免重复；取数全失败（values 空/全 None）→ 空操作，绝不写空行或抛异常。
- **CONFIG_PATH 解析顺序**：显式 `path=` > `CONFIG_PATH` env > 项目根 `config.json`。
- **优先级链**：env > config.json > 内置默认；config.json 缺键补默认（深合并）、未知键忽略。

## 模块 src/（六期B：A 股大盘）

- **`save_last_values` 键派生必须 `.upper()`**：扩 SYMBOLS 到小写 ticker（000001.SS/399001.SZ）后，`seed_history.py` 旧代码用 `("vix","vxn","move")` 字面量写 last_values，导致 SH/SZ 写入后 `load_last_values` 按大写 symbol 读不回。六期B 改为 `[s.lower() for s in SYMBOLS]` 全键派生。回填/重置历史后须跑 `daily_report.py` 验证 SH/SZ 出现在报告与 context。
- **A 股休市特判 ≠ 美股获取失败**：`build_statuses` 中 A 股（SH/SZ）值为 None 时状态为「休市」而非「获取失败」，避免与美股数据缺失混淆；A 股表行收盘价为「休市」、涨跌幅「—」。
- **大盘告警恒 WARN/异动**：`check_breach` 对 `STOCK_SYMBOLS`（含 SH/SZ）一律 level=WARN、state=异动，无恐慌区间；阈值严格大于才触发，恰好等于不告警。
- **末尾平坦日（去尾 0）不打断连涨/跌**：`compute_streaks` 仅裁剪序列末尾的 0（休市日 Yahoo 返回昨收 → 当日涨跌 0）；中间平坦日仍会打断 streak。复现休市场景须让最新一日为平坦。

## 模块 src/（七期：盘中快照扩展）

- **`fetch_all(market)` 只取市场子集**：`snapshot_report.py` 用 `fetch_all(market)` 取对应市场（a-share=SH/SZ/CYB，us=GSPC/IXIC），不取波动率；渲染 `render_snapshot(market=...)` 单板块，波动率章节只在日报出现。改 `MARKETS`/`render_snapshot` 分支须同步 `tests/test_phase7.py`。
- **市场日期不按市场区分**：`get_market_date(market)` 用交易所时区（上海/纽约）取当日日期，A 股快照按北京时间归档、美股按美东日期；同一次运行 a-share=2026-08-30、us=2026-08-29 是正常的（设计 B）。
- **快照文件名复合化防碰撞**：`save_snapshot(suffix="a-share-midday")` → `reports/snapshots/YYYY-MM-DD-{market}-{time}.md`；告警文件 `alerts/YYYY-MM-DD-{market}-{time}.md` 复合名，不与日报 `close` 文件碰撞（设计 C/G）。旧 `YYYY-MM-DD-noon.md` 命名退役（旧文件留盘不清理）。
- **`render_snapshot` 签名兼容**：新增 `market`/`time` 参数但保持 `values/statuses` 位置不变，裸调用（无 market）= 原三板块美东 12:30，日报 `generate_report` 不受影响（决策 D）。
- **单板块渲染兜底**：A 股取数失败（SH/SZ/CYB 全 None）时整块显示「休市」，不崩；验证单板块须构造 3 键 values（含 CYB）。
- **创业板 `399006.SZ` ≠ `399001.SZ`**：SYMBOLS 新增 `CYB`（创业板指），ticker 是 `399006.SZ`（深证成指是 `399001.SZ`，六期B 已用），勿混淆；阈值 `alert.cyb=5`，env `ALERT_THRESHOLD_CYB` 覆盖。
- **跨市场告警去重独立**：`alerts.log` 按 symbol 去重，A 股标记（SH）不阻塞美股（GSPC）；同一 symbol 午盘触发则收盘跳过。验证跨市场用 `_mark_alerted(date, {"SH"})` 后跑 us 入口。
- **入口编排 monkeypatch 点**：`snapshot_report.py` 整体编排，测试须 `monkeypatch.setattr(snap, "fetch_all"/"render_snapshot"/"save_snapshot"/"run_alert_checks", ...)` 才能验证参数透传。
- **周六休市日 cron 照跑污染历史（H.5）**：`snapshot_report.py` 原缺 `is_market_holiday` gate，周六仍生成快照/merge 历史/空转 commit，A 股无盘中数据照抄周五收盘进自然日行（见 web 端 A4 假涨跌）。修复：`src/analyzer.py` 新增 `is_market_holiday(market)`（`a-share`→`SHANGHAI_TZ`、`us`→`EASTERN_TZ`，`weekday>=5` 休市，`alt` 不拦）+ 三入口 `main` 开头 gate；GF 边界：A 股 `midday/open/close` 周末跳，`us open/noon` 按 ET 周末跳，**`us close`/daily 不跳**（北京周日早晨=ET 周五收盘后数据有效）。

## 模块 src/（八期：A 股板块热度）

- **AkShare 概念板块列名以实测为准**：`ak.stock_sector_spot(indicator="概念")` 实测列名为 `板块`/`涨跌幅`/`总成交额`/`股票名称`（PRD 记载的 `总成交额(元)` 实际为 `总成交额`，单位元）；解析前校验必需列存在，缺列视为失败返回 []，防止 akshare 版本升级改列名导致崩溃。
- **新浪源无 timeout**：akshare 内部 `requests.get` 对概念板块接口无 timeout 参数，网络异常可无限挂起；`fetch_sector_heat` 用 daemon 线程 + `join(SECTOR_TIMEOUT=10)` 限时（复用 render_trend_chart 的 Windows 无 SIGALRM 模式），超时/异常/缺列一律返回 []，不中断日报主流程；10s 余量覆盖 akshare 冷启动（实测 ~2-3s）。
- **板块热度不设阈值**：八期改为 Top5 按涨跌幅降序直接展示，不引入 `SECTOR_ALERT_PCT`；`build_search_keywords` 把全部 Top5 板块名按方向（change>=0 surge / <0 drop）注入 `search_keywords`（格式 `"{板块名} surge/drop {date}"`），不触发独立告警；无板块（取数失败/缺列）时回落既有 "market summary {date}"。
- **板块取数不参与 SYMBOLS 循环**：`fetch_sector_heat` 是独立单请求，在 `fetch_all()` 之后调用，失败不影响 8 指数主流程；板块数据不写 history/缓存，无持久化残留。
- **板块热度返回值是 (gainers, losers) 元组（补丁：领跌板块）**：`fetch_sector_heat()` 返回 `tuple[list[dict], list[dict]]`，一次取数两路排序——gainers 降序 TopN、losers 升序 TopN（升序 TopN 在板块稀疏时可能含低涨幅正板块，真实交易日数百板块不会重叠）；失败/超时返回 `([], [])`。`render_report` / `generate_context` / `build_search_keywords` 全部按元组契约消费：`generate_context` 落盘为 `sector_heat: {gainers: [...], losers: [...]}`；`build_search_keywords` 展平 `gainers+losers` 注入方向词。**改 fetch_sector_heat 返回结构或 context 契约前，先同步这三个消费点 + test_phase8.py**，否则既有断言（`== ([], [])` / 字典键 `gainers`/`losers`）立即崩。
- **十期：另类资产 GLD/BTC 在 SYMBOLS 但被多处分流**：`ALT_SYMBOLS = frozenset({"GLD", "BTC"})`；`collect_breaches` 跳过（不参与告警，决策 A）、`build_statuses` 走大盘趋势标签分支、`render_report` 单独「💰 另类资产」板块（A 股大盘后、热点板块前）、`render_snapshot` 仅 `--market alt` 渲染该单板块、`render_market_trend_chart` 注册表键 `alt` 渲染 GLD/BTC 双面板；`MARKETS["alt"] = frozenset({"GLD","BTC"})` 供 `fetch_all("alt")` 取子集。新增"不参与告警/不进波动率面板"的资产时，必须同步这 5 处 + 测试，否则告警或面板会错误纳入。

## 模块 src/（九期：分市场趋势图）

- **图表文本一律英文**：分市场趋势图占位文案用 "Insufficient Data"（灰 #999999），与波动率图同约束（中文字体跨平台渲染不一致）；配色直接复用既有柔和色系（GSPC 蓝 #2b6de8 / IXIC 绿 #1a9e6c / SH 红 #d1495b / SZ 橙 #e07600 / CYB 紫 #7b5ce0），勿改为中文标签。
- **matplotlib 串行渲染**：三图（波动率 + us + cn）各自 daemon 线程 `join` 独立限时，不并行起线程——matplotlib 非线程安全，并行绘图会竞争/崩溃；新图用 `MARKET_CHART_TIMEOUT=5`，既有 `CHART_TIMEOUT=15` 不动（改它会动波动率图，违反 PRD 约束 6）。
- **市场键 us/cn 与快照 MARKETS 键不同**：分市场趋势图文件名用 `-us`/`-cn`（图表自身注册表键 market∈{us,cn}），与 `snapshot_report.py` 的 `--market a-share|us` 互不引用；PRD 文件名定稿如此，勿混用。
- **history 单次加载复用**：`daily_report.py` 用一次 `load_history()` 供 `build_statuses` 与三张图共用，消除重复文件读取；该历史只读、不改写，无模拟数据残留。
- **整体跳过 vs 子图占位**：窗口内行数 <2 → `render_market_trend_chart` 返回 None（报告省略整张图，与 render_trend_chart 一致）；仅某序列有限点 <2 → 该子图中央 "Insufficient Data" 占位，其余子图正常绘制，不中断成图。
- **路径常量 patch 落点**：`web/app.py` 的路径常量（HISTORY_FILE/ALERTS_DIR/CONTEXT_DIR）从 analyzer 导入后在 web.app 重新绑定为模块级名字，解析函数一律引用本模块常量；测试必须 `monkeypatch.setattr(web.app, "HISTORY_FILE", tmp_path/...)`，打在定义方 analyzer 不生效（与 src/ 同纪律）。切勿在 web/app.py 内调用 `analyzer.load_history()` 等引用 analyzer 常量的函数，否则 monkeypatch 失效。
- **板块热度数据源在 context，不在 history**：history.json 无板块字段；`/api/latest` 的 sector_heat 来自最新 `context/*.json` 的 `sector_heat`（gainers/losers）；context 缺失 / 键缺失 → 降级空结构 `{gainers:[],losers:[]}`。PRD 字面「从 history.json 最新条目」不实。
- **alerts 空目录容错**：`alerts/` 目录缺失 / 空 / 含坏文件（无 frontmatter）→ `/api/alerts` 返回 `[]` 或跳过坏文件，绝不 500；告警文件名含日期，排序按文件名倒序取最近 10 条。
- **只读边界**：web 进程绝不写 data/alerts/context；`/api/latest` 涨跌幅由 history 相邻记录自算，不读 `last_values.json`（它是次日告警基准，读它违反只读语义）。
- **Chart.js CDN 降级**：图表库走 jsdelivr CDN，图区 `<script onerror>` 置 `window.__chartFailed`；`renderCharts` 在 `window.__chartFailed || !window.Chart` 时显示「图表加载失败」降级文案，页面其余模块（HTML 直渲）不受影响；无外网环境不白屏。
## 模块 src/（十二期：相关性分析）

- **相关性输入用收益率，非原始价格**：`compute_correlation` 从 history 收盘价相邻日推导日收益率（(p[t]-p[t-1])/p[t-1]），缺口行（None 或 prev 为 None）断开收益链不参与；窗口取 history 最后 `CORRELATION_DAYS=30` 行（与趋势图同语义，非自然日）。切勿对 history 提前 append 当日记录后才计算（report 阶段 history 未含当日，与趋势图一致）。
- **Pearson 边界**：每对有效样本 <`MIN_POINTS=10` 或任一序列零方差（常量收益率）→ r=None；分母除以零已钳制；`math.atan` 越界（浮点误差导致 >1）→ 钳制 [-1,1]；结果 `round(2)` 保留两位小数。r 排序：|r|>0.5 显著；渲染颜色 r>0.5 红 / r<-0.5 绿 / 否则灰，复用既有着色（#d1495b / #1a9e6c / #999999）。
- **context 与报告分离**：`generate_context` 仅写 |r|>0.5 显著对（决策 A）；报告表展示全部 5 对固定组合（含「数据不足」占位），两者消费同一份 `compute_correlation` 结果。`correlation` 键字段 a/b/pair/r/n；变更需同步 Hermes Prompt 契约（决策 D）。

## 模块 scripts/（十三期：回测验证）

- **复用 check_breach 不重写触发逻辑**：`scripts/backtest.py` 的 `collect_triggers` 直接调用生产 `check_breach(sym, cur, prev)`（严格大于阈值、实时 env/config 阈值、缺口断开），切勿在回测侧另写一套比较/阈值逻辑——否则回测与生产行为脱节（计划风险"触发语义漂移"）。改阈值语义必须同步改 `src/analyzer.check_breach`，回测随之生效。
- **历史键小写**：history 存 `gspc`/`vix`/`sh` 等小写键（六期B 纪律）；回测按 `sym.lower()` 取列，勿用大写 symbol 取 history 值（得到 None → 误判缺口）。`BACKTEST_SYMBOLS` 大写（VIX/VXN/MOVE/GSPC/IXIC/SH/SZ），CYB 不在内（PRD 表未列，决策 A）。
- **缺口断开**：相邻两行任一为 None 即跳过该日触发；前向后效为点对点收益（p[t+h]-p[t]），缺口不阻断但越界窗口不计入（n 透明展示）。
- **只读边界**：脚本只写 `reports/backtest_report.md`；`--history` 仅指定只读输入，不提供任何写回能力。`REPORTS_DIR` 若被测试 monkeypatch，须打在 `scripts.backtest` 模块（同 src/ 纪律：打在 analyzer 定义方不生效）。
- **阈值实时性**：报告内"各标的当前阈值"表用 `alert_threshold(sym)` 实时值，并注明"阈值来自 config/env 实时配置"——避免"配置已改、报告仍是旧值"误解。测试须 `monkeypatch.delenv("ALERT_THRESHOLD_<SYM>", raising=False)` 隔离宿主 env。
- **样本门槛**：全局有效交易日 <30 优雅退出（退出码 0、不写报告）；单标的有效点 <30 仅输出计数与"样本不足"标注，不出后效/胜率/有效触发率，防小样本误导。回测只给事实数字，不输出任何结论性评语。
- **history 排序**：`load_history` 返回存储顺序，回测前按 date 升序排序，避免乱序造成伪触发。

## 模块 src/（十四期：日报图片化）

- **解析严格依赖 `render_report` 的 Markdown 结构**：`src/image_renderer.py` 用正则解析 `reports/YYYY-MM-DD.md` 生成卡片（标题行 `## ...` / `| 指数 | 收盘价 | 涨跌幅 | 趋势 |` 表头 / `![...](charts/...)` 引用 / 标题含「解读」章节 / `alerts/{date}-close.md` 附录块）；改 `render_report` 输出结构（章节标题、表头文案、趋势图引用语法、AI 解读章节命名）会直接破坏图片解析，须同步回归 `tests/test_phase14.py`。
- **尺寸守卫 + zoom 重试（已删除）**：a536888 用 Playwright 替换 imgkit 时删除了 15s 限时（RENDER_TIMEOUT / MAX_IMAGE_BYTES 已成死常量）、≤800KB 尺寸守卫与 zoom 重试；如需恢复须回填 `src/image_renderer.py` 并重写对应单测。`--disable-local-file-access` 已开启，趋势图必须用 `file://` 绝对路径（相对路径渲染后空白）。
- **全链路容错、失败返回 None**：`render_report_image` 任意异常（playwright 未装 / 模板缺失 / 报告不存在）均捕获并返回 None；`daily_report.py` 调用方再包 try/except 仅记日志、退出码恒 0；图片是「锦上添花」，绝不阻断日报主流程与推送。
- **Playwright 渲染（替代 imgkit）**：`src/image_renderer.py` 经 `from playwright.sync_api import sync_playwright` 驱动 Chromium 截图 PNG；`requirements.txt` 须含 `playwright` 且本机装浏览器（`playwright install chromium`）。未装 / 导入失败 → 捕获返回 None，日报不受影响。
- **中文字体靠系统**：渲染 HTML 用系统无衬线栈（PingFang SC / Microsoft YaHei / 文泉驿），无中文字体环境会豆腐块；测试用 mock `playwright` + `playwright.sync_api` 双模块（见下），不依赖真实浏览器，仅验证解析 / 模板 / 输出契约。
- **AI 解读章节识别**：正则 `^##\s.*解读` 匹配标题含「解读」的章节（决策 A），仅取首个；日报本身不渲染解读区，Hermes 追加解读后由 `scripts/render_report_image.py --date` 独立重渲染含解读图（依赖已落盘的 md + 解读章节），与日报自动渲染解耦。
- **测试 mock 双模块落点**：`render_report_image` 在**函数内** `from playwright.sync_api import sync_playwright`，导入时查 `sys.modules["playwright"]` 与 `sys.modules["playwright.sync_api"]`。测试须**同时** `monkeypatch.setitem(sys.modules, "playwright", ...)` 与 `monkeypatch.setitem(sys.modules, "playwright.sync_api", ...)` 才能拦截；只置 `sys.modules["playwright"]=None` 拦不住**已缓存**的 `playwright.sync_api` 子模块（真实 Chromium 仍会被驱动）。playwright 自带超时抛 `TimeoutError`，mock 时让 `page.set_content` 抛 `TimeoutError` 即可走真实「超时 → 捕获 → None」路径。

## 模块 src/（十八期：板块聚合）

- **聚合必须发生在取数层**：`fetch_sector_heat` 内部 `_worker` 取全量概念板块后调用 `aggregate_sectors`，一次完成聚合；web `/api/latest` 的 `sector_heat` 只读 `context/*.json`（web 进程绝不写数据、也不持有聚合源），若把聚合留在日报/快照各自做，web 无聚合数据源且日报与看板展示不一致。
- **turnover 字符串需还原为元再加权**：行内 `turnover` 是本项目自产格式化字符串「X.X亿」（元÷1e8 保留 1 位），聚合权重需数值成交额，故 `_parse_turnover("13.7亿") → 1.37e9`（"X.X亿"→×1e8、"X.X万"→×1e4、纯数字原值、解析失败/空→0.0）；不在行内加 raw 键（避免破坏行契约与 `test_phase8` 精确 dict 断言）。
- **聚合行契约与概念行同构**：`aggregate_sectors` 输出仍是 `{name, change, turnover, top_stock}`，`turnover` 复用「合计元÷1e8 保留 1 位」；五个消费点（render_report / render_snapshot / render_opening_report / generate_context / build_search_keywords / web）零改动即可显示大类。
- **未匹配概念板块归「其他」兜底漏配**：SECTOR_MAPPING 精确匹配概念名，命中即归大类、未命中归「其他」；新浪实际板块命名与 PRD 字面大量不符（如「白酒概念」「券商重仓」「生态农业」「稀缺资源」「华为海思」「氢能源」），已据实跑 175 板块核对补全别名，提升大类覆盖率（仅「半导体/芯片」无新浪对应板块名而恒空）。
- **改 `fetch_sector_heat` 返回语义需同步契约测试**：聚合后返回行变为大类名，`tests/test_phase8.py` 的 `TestFetchSectorHeat` 契约测试须改用跨类别 mock 并断言加权值/类别数/ top_stock，否则原「生物育种」等概念名断言立即失效（注意：扩展别名后原 mock 用的「生物育种」会命中「农业」，须改用确未命中的名如「重组概念」）。
- **成交额全 0 类别走简单平均**：某大类子板块成交额合计为 0（含全 0 / 全缺失）时，加权分母为 0，按 PRD 约束改走 `mean(change)`；个别子板块 0 权重自然不贡献。
## 模块 web/（十七期：看板交互增强）

- **Chart.js 重渲染必须 destroy 旧实例**：刷新时若直接 `new Chart(canvas, ...)` 会报 `Canvas is already in use`。按 group id 维护 `charts` 注册表，重渲染前 `if (charts[g.id]) { charts[g.id].destroy(); delete charts[g.id]; }` 再重建（实测 90 点切换无此问题，但缺失 destroy 必然报错）。
- **FastAPI Query 参数越界自动 422**：`days: int = Query(30, ge=1, le=90)` 时前端传 `?days=0` / `?days=91` 由框架直接返回 422，前端无需自行校验，但测试必须覆盖这两个边界。
- **默认行为变更必同步测试**：`/api/history` 默认窗口 7→30 天后，既有 `test_api_history` 的 `len(dates)<=7` 与 vix null 索引（1→2）断言、以及 `test_api_history_series_shape` 的键集断言（`raw`）都要同步更新，否则旧断言锁死新行为。
- **新增 API 字段同步键集断言**：series 增 `raw` 等长原始值（GLD 已 ×10，与图线一致）后，`test_api_history_series_shape` 的 `set(s.keys())` 必须含 `raw`，否则键集漂移无人发现。
- **CDN 插件降级纪律**：chartjs-plugin-zoom 走 CDN，`<script onerror="window.__zoomFailed=true">`；插件缺失时图表照常渲染仅无缩放（zoom 配置仅在 `window.ChartZoom && !window.__zoomFailed` 时注入），与既有 Chart.js `__chartFailed` 降级同纪律，不白屏。
- **筛选/排序单一管线**：指标筛选（state.selected）与表格排序（state.sort）统一由 `refresh()` 驱动——历史请求带 `?symbols=`、概览表在 `renderOverview` 内先按 selected 过滤再排序；整组无选中时历史请求发空余串会退回全量，故前端对 `selected.size===0` 直接走空 payload 渲染「无选中指标」占位，避免与「全部」语义混淆。
- **浏览器自动化访问 DOM 走 `tab.evaluate`**：`browser` 的 `run` 顶层作用域无 `document`，必须在 `tab.evaluate(() => {...})` 内操作 DOM；模拟点击后需 `await setTimeout` 等 fetch 回调再断言。
## 环境相关

- **FRED 公开 API 无 MOVE 序列**：勿再走 FRED 作为 MOVE 数据源。真实数据在 Yahoo `^MOVE`（标名错误但数值真实，与 Investing.com 一致）。
- **Hermes weixin 出站不可靠**：发送报告成功但对方收不到，用 QQBot 作为推送通道。
- **星期错标根因在 Hermes 侧 cron prompt**：看板/报告「周X」标注错位（如周六标成周五）根因是 Hermes cron prompt 用北京时间算「今天/星期」而数据按美东日期归档；仓库脚本从不标星期、无时区转换逻辑，无法在代码层代改。应对：Hermes prompt 内统一用 `TZ=America/New_York date` 取美东日期与星期（关联 二十六期日期错位坑 L16）。

## 历史教训

| 日期 | 问题 | 根因 | 修复方式 |
|---|---|---|---|
| 2026-08-29 | FRED 无 MOVE 序列 | FRED 的 MOVE 指数未对公开 API 开放 | MOVE 迁至 Yahoo `^MOVE`，勿回退 |
| 2026-08-29 | yfinance 多请求触发 429 | 一次 history() 打多个子请求 | 改为单请求直连 chart REST |
| 2026-08-29 | 中文路径 `@架构师.md` 传参失败 | omp `@file` 不支持非 ASCII 路径 | 用 ASCII 临时文件中转 |

## 模块 web/（二十期：视觉升级）

- **同文件多 PUT 行号漂移**：edit 工具一次提交多个 `PUT`，各自按首次 `read` 的绝对行号；若两次 read 的窗口/编号不一致（如 155-215 窗口里的 204 ≠ 全量 read 的 211），会改错位置。本次把 renderSector 的 turnover `<td>` 误插入到 renderAlerts 内部，造成游离语句（运行时 ReferenceError 风险）。纪律：同文件多个定点修改前，先用 `grep` 取每个目标的真实行号再编辑；或优先整体 `write` 重写。
- **FastAPI 模板缓存 + 端口占用**：Jinja2 在启动时把 `index.html` 读入缓存，旧进程不会反映模板改动；且 8000 常被既有看板进程占用。验证模板/静态改动须另起未缓存端口（如 8001）或用 `tab` 硬刷新，否则会误以为改动未生效。
- **自动化 `每日数据更新` cron 会 `git add -A` 扫入未提交改动**：改完 `web/static/*`、`web/templates/*` 后若 cron 触发，改动会被一并提交，`git status` 显示 clean、`git diff` 为空；这是正常现象，改动已安全入仓库，无需手动提交。
- **renderOverview 预存 `section.style.display = ""` bug**：原 `index.html` 引用未定义的全局 `section` → `ReferenceError`，会让概览表永远停在「加载中」。视觉升级重写该函数时应一并删除该行；若仅改 CSS 不动 JS 则会暴露此旧 bug。

## 模块 web/（二十三期：趋势图视觉精修）

- **Chart.js 非交互降透明度须显式声明 hover 恢复**：dataset `borderColor` 用 8 位 hex（`COLORS[key] + "d9"`，85% 不透明）降低非交互视觉攻击性时，hover 不会自动变回全色——必须额外设 `hoverBorderColor: COLORS[key]`（全色）与 `hoverBorderWidth`（如 2.6）；只改 `borderColor` 则 hover 仍是 85% 灰。四图共用 `renderLineChart` 一处 dataset 配置，改一处即四图一致。
- **曲线平滑 `tension` 取值纪律**：金融/时序图轻微平滑用 `0.25`（Chart.js 文档常用值），`0.08` 几乎等同直线无效果、`0.4+` 是强 spline（PRD 否决）。保留真实局部拐点须 ≤0.3；改 tension 后必须用 `window.Chart.getChart(canvas).data.datasets[0].tension` 运行时复核四图一致。
- **验证 web 图表改动走 `tab.evaluate`**：浏览器 `run` 顶层无 `document`，DOM/Chart 实例访问必须包在 `tab.evaluate(() => {...})` 内；`window.Chart.getChart(canvas)` 可读取 `tension/borderWidth/borderColor/hoverBorder*/pointRadius` 等运行时值，比截图更可靠——本机未配视觉模型时尤其（inspect_image 直接报 "does not support image input"）。
## 模块 web/（二十五期：美股去重 + 浅色主题）

- **美股去重判定符号集必须排除 MOVE**：实测 MOVE 有浮点级抖动（70.965 → 70.9655，+0.0007%），若判定集含 MOVE，非交易日重复（如 08-30）不会被 `prev.get("move")==record.get("move")` 判为同值，去重失效；同时「全 10 键相等才跳过」方案在 08-30/09-01 这类「美股同、A 股/BTC 异」日永不触发（证据：08-30 有 gld/btc 实值、09-01 有 A 股三指数变动）。判定集取 `("gspc","ixic")`，与 PRD 示例（gspc）一致。
- **混合日（D2）A 股/BTC 数据不写 history 为 PRD 取舍**：09-01 类美股未交易但 A 股/BTC/GLD 变动的日，按 PRD「今天的美股数据与昨天相同则不写入」整条跳过 `append_history`（含当日 A 股涨跌幅跨日计算缺失，下一交易日 A 股涨跌幅基于再下一交易日算）；日报/context 当日仍完整生成，仅历史序列缺此日。
- **真正平盘日会被跳过**：美股真的收平（与最近记录 GSPC/IXIC 全同）时 `_is_us_duplicate_day` 返回 True → 跳过，与周末跳过同语义，接受。
- **history 已有重复行不清理**：08-30 等已在库的历史重复行不迁移，靠 90 天滚动自然淘汰；PRD 未要求迁移（~10 行范围）。
- **web 浅色主题——FOUC 预应用**：`index.html` `<head>` 最前的预应用脚本在首屏渲染前读 `localStorage["mp-theme"]`，为 `light` 则给 `<html>` 加 `light` 类，否则刷新闪烁（深→浅跳变）；脚本包在 `try/catch` 内（隐私模式 `localStorage` 抛错不阻塞）。
- **web 浅色主题——localStorage 校验**：`setTheme` 写 `localStorage` 同样包 `try/catch`；键名恒 `"mp-theme"`（值 `"light"`/`"dark"`），与预应用脚本一致。
- **web 浅色主题——uvicorn 模板缓存 / 端口占用**：Jinja2 启动把 `index.html` 读入缓存，旧进程不反映模板改动；且 8000 常被既有看板占用。验证模板/静态改动须另起未缓存端口（如 8001/8002）或用硬刷新；headless 浏览器会缓存 `style.css`，换端口（不同 origin）可强制重新拉取，否则 `:root.light` 规则看似「不生效」实为缓存旧 CSS（`tab.evaluate` 查 `document.styleSheets` 的 `:root.light` 规则可证伪）。
- **web 浅色主题——`tab.evaluate` 断言**：浏览器 `run` 顶层无 `document`，DOM/计算样式访问必须包在 `tab.evaluate(() => {...})` 内且 `await`；一次 `run` 内完成 初始→点击→刷新→再点击 全流程，避免跨 `run` 上下文重置 `localStorage` 导致持久化断言失真；验证三态：`html.light` 类、`localStorage["mp-theme"]`、computed `background-color`（深 `rgb(11,14,20)` ↔ 浅 `rgb(245,245,245)`）。



## 模块 web/（context 空壳回退，2026-09-03）

- **失败空壳 context 会遮蔽真实板块数据**：`context/YYYY-MM-DD.json` 由 `daily_report.py` 覆盖写入同名文件；当某次运行全源取数失败（如 09-03 停牌/网络中断），`generate_context` 仍会写出 indices 全 null、`sector_heat` 空结构（`{gainers:[],losers:[]}`）的空壳。`_load_latest_context` 原按文件名字典序严格取最末，空壳会盖掉前一日（09-02）真实板块数据，前端 `renderSector` 因 `gainers` 为空显示「数据暂缺」。
- **回退落到 `_load_latest_context` 整体**：`_load_latest_context` 语义升级为「最近有效 context」——按文件名倒序遍历，返回第一个 `sector_heat` 为 dict 且 `gainers` 非空的 context（= 最近一次板块取数成功的交易日）；全部无板块数据 → 返回倒序第一个可解析 context（状态列兜底下限）；目录缺失/全坏 → `None`。`_load_sector_heat` 与 `api_latest` 零改动，自动同源回退（板块列与状态列同来自该返回值）。
- **空壳判定用 `gainers` 非空**：前端唯一渲染字段是 `gainers`（losers 不参与渲染）；`generate_context` 恒同时写 gainers/losers 且同源，故 `gainers` 非空 ⇔ 该次板块取数成功，避免 losers-only 假阳性（后端有数据但前端仍「数据暂缺」）。
- **`_read_context_file` 逐文件容错**：倒序遍历时坏 JSON / 非 dict / IO 错误 → 记 warning 并 `continue`，跳过坏文件继续向前回退；不再像旧实现那样「最新文件坏 → 整体 `None`」阻断其后更旧的有效 context。
- **状态列回退的边界**：方案 A 下「仅板块取数失败日」状态列会随回退滞后一天（罕见，与当日数值错配）；全源失败空壳日状态列与数值列同源一致（本次场景，改善）。若此类错位日变多，切方案 C：`api_latest` 状态列按 history 最新日期精确取 context，板块列独立走「最近有板块数据」回退。

## 模块 web/（二十八期：自选股 watchlist）

- **`/api/watchlist` 是 web 看板第 4 个只读 JSON API**：实时取数 `config.json` 的 `watchlist.stocks`（A 股 AkShare / 美股 Yahoo），返回 `{stocks:[{symbol,label,value,change_pct}], trend:{dates,series:[{key,label,values,change_7d,raw}]}}`（trend 与 `/api/history` 同构、归一化基准 100）；配置为空 → 200 + 空结构（前端整卡隐藏），单标的取数失败 → 该行 `value=null`、前端显示「数据暂缺」、不 500；看板索引端点名是 `/api/latest`（**不是** `/api/overview`），验证别用错名字。
- **内联 `<script>` 不能直接 `node --check`**：`web/templates/index.html` 主脚本里含 `</script>` 字面量，用正则 `<script>(.*?)</script>` 提取会被提前截断，导致 `node --check` 报 `Unexpected end of input`（未改的原始文件也报同样错，非本次引入）。验证 JS 语法：① 用 `node --check` 校验只含本次新增片段（palette/render 函数）的临时文件；② 或浏览器 `tab.evaluate` 看 console 报错。整文件 node 校验是假阴性，勿据此判定「JS 坏了」。
- **真实数据落地后回退自然失效**：不改生产端；`daily_report.py` 覆盖写同名 context，09-03 真实数据落地后 `_load_latest_context` 取最新文件即命中板块数据，回退不再触发，无需清理逻辑。
- **自选股图过宽扁（任务 D）**：单标的时 `#chart-watchlist` 全宽 220px 高 → 极扁。修法 `style.css` 加 `#watchlist-section .chart-box{max-width:640px;margin:0 auto}` 限宽居中；多标的 640 仍合理。
- **Chart.js v4 maintainAspectRatio 压缩糊（任务 E）**：默认 `maintainAspectRatio:true`+`aspectRatio:2`，若 canvas 高被 CSS `!important` 钉死（如 220px），绘制高=宽÷2（640÷2=320）×DPR 被压到 220 显示 → 糊/扁。修法 `renderWatchChart` options 设 `maintainAspectRatio:false`，绘制高=容器实际高（≈220，1:1 清晰）。
- **周末历史行照抄假涨跌（任务 J）**：周六 A 股入口把周五收盘 `merge_history` 进自然日行 → 当日 change 算 0 → 前端显 `+0.00%`，语义错（A 股也休市）。展示层兜底：`renderOverview` 前端 `isWeekend` 统一显「休市」（与美股一致）；数据层根治靠 `is_market_holiday` gate（见 src 七期 B6），非交易日不再生成/merge 行。
- **`/api/latest` 的 indices 是 list 非 dict（任务 I）**：前端 lede/取值若 `idx[sym]` 把列表当 dict 按符号取 → 全 null（实测美股/VIX/A股格空）。修法：从 `indices` 列表遍历建 `symbol→item` 映射再按 symbol 取，勿当 dict 用。

## 模块 web/（前端重构 2026-09-05）

- **跨端口 CSS 缓存假阴性（验证陷阱）**：headless 对 `/static/style.css` 跨端口命中 304/陈旧副本，导致"菜单按钮仍显示""侧栏不 fixed"等误判。修法：每次验证用全新端口（8014→8015→8016 递进）强制重新拉取；勿用旧端口复测。
- **侧栏基础规则特异性（#sidebar vs .sidebar）**：基础用 `#sidebar{position:sticky}`（id），768 媒体用 `.sidebar{position:fixed}`（class）→ id 压过 class，移动端不 fixed、抽屉失效。修法：768 媒体选择器统一改 `#sidebar`，与基础同源特异性。
- **flex column 下 main 不拉伸溢出（align-items:flex-start）**：`.shell` 基础 `align-items:flex-start`，移动端 `flex-direction:column` 后 main 不横向拉伸→按内容（表格 nowrap）撑到 512 横向溢出。修法：768 媒体 `.shell` 加 `align-items:stretch`，main 强制满宽 375 无溢出。
- **图表色随主题：漏改即图例/线色违和**：切换 Light/Dark 若只改 UI token 不重渲染 Chart.js，线/柱/图例色与主题错位（P2 实测）。修法：theme-toggle 切换后 `if(state.history) renderCharts()` 重渲染；COLORS 拆 LIGHT/DARK 双数组 + `colors()` 取。
- **renderOverview 函数名误用（esc vs escapeHtml）**：重构误用 `esc()`，实际是 `escapeHtml()`→运行时 ReferenceError 表格卡"加载中"。修法：统一 `escapeHtml`；改动后用浏览器 `tab.evaluate` 看表格是否真正渲染（而非只看 200）。
- **sparkline 绘制循环守卫（单卡序列缺失即崩）**：KPI sparkline `paint` 遍历各 canvas，若某卡 series 为 `undefined`（如历史接口未就绪、watch 卡先渲染时 index 卡无序列），`drawOneSpark` 直接读 `values.length` 抛 TypeError，中断整个 forEach → 全部卡空白且后续 `withHist` 合并 history 永不执行。修法：`drawOneSpark` 顶部加 `if(!values||!values.length){clearRect;return}` 守卫；单卡缺失只清空该卡不阻断其余。

- **趋势图默认只显两图（任务 R-3）**：charts-grid 默认四组全显、50/50 反而挤扁。修法：`state.selected` 初值改为 `{gspc,ixic,sh,sz,cyb}` 仅两主板；空组（无选中指标）用 `.chart-box:has(.chart-empty){display:none}` 隐藏整格（不改 `renderGroup`/`:has()` 受现代 Chromium 支持）。该初值同时驱动表格行 → 表格默认也只显 5 行（副作用，已由下条 visibleGroups 解耦）。
- **表/图单源污染（state.selected 既管表格行又管趋势组可见）**：R-3 把 `state.selected` 收窄成两主板，表格跟着只剩 5 行。修法：解耦——新增 `state.visibleGroups`（趋势区分组可见集，默认两主板），表格行仍由 `state.selected`（默认 ALL_KEYS=10）决定；`renderGroup`/`syncSelection` 组显隐改判 `state.visibleGroups.has(g.id)`，`onGroupClick` 改为切换 `visibleGroups`（点单组→仅显该组，再点已独占组→恢复默认），全选按钮同步把 `visibleGroups` 置全 4 组。
- **主题按钮委托陷阱（删 header 按钮须改绑 handler）**：侧栏 `#sidebar-theme` 通过 JS 委托 `themeBtn.click()`（`themeBtn` 原绑 `#theme-toggle`）触发切换；若只删 header `#theme-toggle` 而不改绑，则 `themeBtn` 变 null、侧栏失效。修法：把主题 handler 直接绑到 `#sidebar-theme`（`getElementById('sidebar-theme')`），并删除委托那两行。
- **表格趋势文本单行（任务 R-1）**：trend-sub（连跌N日）移回名称列，若 `.data-table td.name` 为 `flex-direction:column` 会换行 → 行高参差（I.5/I.6 教训）。修法：`td.name` 改 `flex-direction:row; align-items:baseline; gap:8px; white-space:nowrap`，趋势文本内联单行。
- **移动端 KPI 卡高不一致（任务 R-2/R-5）**：375 屏 sparkline 占 64px + padding 挤压 info 列 → 值/标签换行 → 卡高参差；且 768 块 `.lede-val{22px}` 源序在 480 块后，覆盖 480 的 20px。修法：480 块 spark 改 40px、`.lede-val{font-size:16px !important; white-space:nowrap}`、`.lede-label/.lede-sub{nowrap+ellipsis}` → 卡高一致(84x4)。
- **nav active 须 var(--blue) 且 SVG 随 currentColor（任务 R-4）**：active 文字若用 text-primary 不显蓝；图标 `<svg>` 用 `stroke="currentColor"` 才能随 active 变蓝。修法：`.nav-item.active{color:var(--blue)}` + SVG currentColor。
- **趋势文本误染红底（row-flash 误配连跌）+ 休市绿字**：renderOverview 行级红底 `row-flash` 条件含 `/连[涨跌]\d+日/`，把 A股「连跌1日」当异动整行染红；且 `cls` 涨跌色独立于 `chgCell` 文案，周末/回填行（chg≥0）显示绿字「休市」与红底矛盾。修法：`row-flash` 仅留 `st.indexOf("异动")>=0`；`cls=(isWeekend||srcDate)?"":(涨跌色)` 与 `chgCell` 同条件（休市/未收盘中性色），连跌趋势已在名称列 `trend-sub` 小字表达。
- **模块级 TTL 缓存跨测试泄漏**：`/api/watchlist` 的缓存是模块级 `_watch_cache`，pytest 单进程跑多测试共享 → 前一测试缓存污染后一测试端点断言（hidden/空结构误判）。修法：test_web.py 加 autouse fixture `_reset_watch_cache` 每测试前清空。
- **自选格首屏占位避免布局跳变（任务 U 前端解耦）**：watchlist 取数慢/失败若直接留空白会让 KPI 卡第 4 格在「有/无」间跳动。修法：renderLede 在 watch 未到达 / 取数失败时渲染占位「—」/「加载中…」，watchlist 并行取数到达后由 success 分支 `renderLede(state.latest,data)` 单独补画真实值，概览/趋势不被拖慢。
- **CSS 缩进无语义→media 内规则全局生效**：以为 2 空格缩进代表"在媒体查询内"，其实 CSS 只认选择器、缩进不产生作用域。误把本应仅移动端的 `.data-table td.name{display:flex}` 写成全局 → 桌面端 flex 把指数列 td 变 flex 盒，破坏 border-collapse 共享 border，列交界出现横线断点（任务 V 实测）。修法：移动端专属规则必须真包进 `@media` 块；删除全局 flex、间距改 `.trend-sub{margin-left:8px}`。

## 模块 web/（Bento 栅格重构，2026-09-11）

- **canvas 位图 ≠ 显示尺寸的量化判据（C2）**：`.chart-box canvas{width:100%!important;height:340px!important}` 用 `!important` 覆盖 Chart.js 写入的行内尺寸，两边打架 → 1280 档纵向被拉 **1.405×**、1920 档压 **0.937×**（非等比，表现为"图糊/线变形"）。可直接进验收脚本的判据：`canvas.width === canvas.offsetWidth && canvas.height === canvas.offsetHeight`（DPR=1；DPR>1 时 `=== offset × DPR`）。修法三件套缺一不可：删 `!important` + 容器给**确定高度**（`#chart-main-wrap{height:clamp(300px,40vh,460px)}`）+ `maintainAspectRatio:false`。只删 `!important` 而容器无确定高度 → 高度塌 0、图不可见；只调 `clamp()` 而留 `!important` → 只是换一个错误的拉伸比。
- **星期/周末判定必须按「数据日」，不是「浏览器当天」**：`new Date().getDay()%6===0` 用的是运行日 → 工作日浏览历史数据永远不显示「休市」。同时 `new Date("2026-09-11")` 按 **UTC 午夜**解析，负时区会退到前一天。修法：`isWeekendDate(s)` 手动解析 `YYYY-MM-DD` → `Date.UTC(y, m-1, d)` + `getUTCDay()`；趋势轴过滤周末也复用同一函数。
- **context 有键 ≠ 端点暴露（C7）**：`us_sector_heat` 自十一期起就写在 `context/*.json`，但 `web/app.py` 只读 `sector_heat`、从未暴露 → 前端永远拿不到。排查「前端某模块无数据」时，先并列核对 **context 键集** 与 **端点返回键集**，不要只看前端。另注：`us_sector_heat.gainers` 实际恒为 **5 条**（取数层即 Top5），不是 11 只 SPDR ETF 全量。
- **`_load_latest_context` 会回退到前一有效日**：当日 context 为空壳（全源取数失败、`sector_heat.gainers=[]`）时，返回的是**最近一次板块取数成功**的交易日 → 前端展示的板块/状态数据日 ≠ history 末日，属既有语义不是 bug。断言"数据日==今天"必然失败。
- **auto-commit cron 会吞掉未提交改动、并把半成品写进仓库**：会话期间外部 Hermes「每日数据更新」cron 连做 4 次 `git add -A`（`cffe16f`/`9fc9b1d`/`9571bf5`/`2b980cd`），把**写到一半**的 `index.html`/`style.css`/`web/app.py`/`tests/` 直接提交，`git status` 变 clean、`git diff` 只剩零星几行，极易误判"改动丢了"。应对：先 `git log --oneline` 核对是否被 auto 提交；验证脚本落 `tasks/<task>/`（有意入库），截图/测量 JSON 落 `$env:TEMP`，仓库内不留临时产物。
- **`write_to_file` 大文件写入可能被空闲超时中断并把文件截断为 0 字节**：本次 `app.js`（≈700 行）一次写入被取消，落盘 `Length=0`（`LastWriteTime` 已更新，看起来"写过了"）。应对：单次写入控制体量；超长文件分块写（先写头部 + `// __PART2__` 占位，再用 `replace_in_file` 逐块续写）；被取消后先 `Get-Item Length` 核实是否被截断。
- **bento 栅格必须 `minmax(0,1fr)` + 卡片 `min-width:0`**：否则 grid item 的 min-content（表格 `nowrap`、canvas）会顶破容器产生**页面级横向溢出**（与 flex column 溢出同源）。判据：`document.scrollingElement.scrollWidth === window.innerWidth`，375 与 1280 两档最易踩。
- **`#lede{display:contents}` 让 4 张 KPI 卡与 promo 卡同处一行栅格**：JS 只需把 KPI 卡写进 `#lede`，它们便成为 `.row-kpi` 的直接 grid item → 1920 五列同排、1280 三列 3+2 自动成立，无需改 DOM 层级、无需 JS 感知栅格列数。
- **移动端顶栏是横向溢出的高发区**：375 档 brand（logo 24 + `MARKETPULSE` ≈110 + 副标 ≈48）+ 数据日 + 通知 + 头像 + 刷新 + 菜单 ≈ **447px > 375**。修法：`@media ≤768` 隐藏品牌副标、`≤480` 隐藏 `brand-mark`/头像/通知等装饰性占位，并给 `.brand{min-width:0}`。
- **z-index 只写在媒体查询里会漏掉桌面档**：`#sidebar` 基础规则原缺 `z-index`（仅 768 媒体内有 60）→ 桌面档 `getComputedStyle` 得 `auto`，sticky 侧栏可能被卡片盖住。判据：`.topbar`/`#sidebar`/`.nav-backdrop` 恒为 `100/60/55`，新增卡片层级必须 < 55。
- **验收脚本用 `document.querySelector('.card')` 取样会命中 promo 卡**：promo 卡背景是 `linear-gradient`（background-image），`getComputedStyle().backgroundColor` 恒为 `rgba(0,0,0,0)` → 主题色断言假失败。取样要指定有**纯色背景**的具体卡片（如 `#overview`）。
- **验收脚本首屏必须等异步取数落定**：自选股走 AkShare 冷启动（服务端限时 10s），首屏只 `wait_for_timeout(4.5s)` 会读到 `#watchlist-section.hidden`（height=0）→ 误判布局缺陷。修法：`page.wait_for_selector('#watchlist-section:not(.hidden)', timeout=25000)` 再短 settle 后测量。
- **动画态断言必须等过渡结束**：`el.click()` 后**同一帧**读 `getComputedStyle(el).transform` 得到的是过渡起始值（仍 -240px），会误判"抽屉没动"。修法：click 与读取拆成两次 evaluate，中间 `wait_for_timeout(≥过渡时长)`。
- **tab active 断言不要在切换后引用旧节点**：`renderTrendTabs()` 若在切换时重建 DOM，测试提前缓存的按钮引用已脱离文档，`classList.contains('active')` 恒 false（但图表其实已切换）。修法二选一：实现改为**原地** `classList.toggle`（不重建 DOM，也避免丢失焦点），或测试每轮重新 `querySelectorAll`。
- **`chart.data.labels` 为空 ≠ 图里没有数据**：本项目 x 轴用 `type:'category'` 且 labels 由 `options.scales.x.labels` 提供，故 `chart.data.labels` 恒为 `[]`；断言"渲染了多少交易日"必须读 `chart.data.datasets[].data.length`（每个点是 `{x,y}` 对象）。实测误用 `data.labels` 得到 `labels:0, datasets:[257,257]` 的假失败。

## 模块 scripts/（历史回填，2026-09-11）

- **`merge_history` 只在「每天追加今天」的前提下有序，回填历史日期必须重排**：`analyzer.merge_history` 对不存在的 date 直接 `records.append(row)`、**不做排序**。生产入口每天只写"今天"，末尾天然有序；但**回填历史日期会把整段旧数据 append 到数组尾部**（实测写入后打印出 `2026-05-14 ~ 2026-05-13`）。而 `/api/latest`、`_last_records(7)`、`_build_history_payload` 的 `records[-days:]`、`compute_correlation` 全部按**数组顺序**消费 → 会把最旧的回填日期当成"最新日"。**判据与修法**：`data/history.json` 的 date 必须 `dates == sorted(dates)` 且无重复；回填脚本收尾必须整体按 date 升序重排 + 原子写 + 断言（`scripts/backfill_history.py::ensure_sorted/finalize_and_report`）。
- **BTC 的 Yahoo 日线含周末（7×24），不能作为「交易日」依据**：`BTC-USD` 近 1y 返回 **366 个自然日** bar（比 `^GSPC` 的 252 个交易日多 114 个）。直接用会写出 ~110 个「只有 `btc` 有值」的纯周末行 → 超出 `HISTORY_MAX` 被裁、偏离既有行的交易日口径、切断 `compute_correlation` 的收益链、夸大 `scripts/backtest.py` 的样本计数。**修法**：某天若除 `NON_TRADING_CALENDAR_SYMBOLS = {BTC}` 之外无任何标的有值 → 判为非交易日、整行丢弃（`backfill_history.py::plan_fills`，实测丢弃 104 行）。
- **history 的日期口径是「按符号所属市场时区」，不是统一美东**：`analyzer.get_market_date` 中 `a-share → SHANGHAI_TZ`、`us → EASTERN_TZ`。Yahoo timestamp 转日期时若统一用美东，A 股（上证 09:30 北京 = 前一日 21:30 ET）会整体**早一天**、与既有行错位/重复。**抽查金标准**（回填后逐条核对）：`2025-12-25` 只有 `sh/sz/btc` 有值（美股圣诞休市）、`2026-01-02` 只有美股类有值（中国元旦假期延续）、`2026-02-17` 只有美股类有值（春节）、`2026-01-01` 整行不存在（中美双休，仅 BTC 有 bar 被丢弃）。
- **既有行的 `None` 有真实语义，回填不得"补全"**：实测 90 行里 `vix 85/90`、`gld 83/90` 非空——空值本身就是休市/未收盘的记录（`2026-05-25` 美股键全空 = 阵亡将士纪念日；`2026-09-11` 的 `vix/gld/btc` 空 = 美股未收盘）。用 Yahoo 历史 bar 去填空会造出"休市日却有 VIX 值"的假数据。**回填只新增 date 不存在的行**（`backfill_history.py` 默认行为，并报告刻意跳过的键数）。
- **`seed_history.py` 保留但勿再使用**：它的 `save_last_values` 用**小写键**整文件覆盖 `data/last_values.json`，而消费方按**大写 symbol** 取值 → 跑一次就让次日涨跌幅退化为"首次运行"、告警基准全部失效；其 `append_history` 整行覆盖还会抹掉既有行的非空值。回填请用 `scripts/backfill_history.py`（**不碰 `last_values.json`**）。`seed_history_market.py` 同类问题更粗糙，同样勿用。
- **CYB（`399006.SZ`）Yahoo 1y 覆盖缺口 → 改走 AkShare 补齐（已落地）**：同一条 `range=1y` 请求，`^GSPC`/`^IXIC` 各 252 天、`000001.SS`/`399001.SZ` 各 243 天，而 `399006.SZ` **只返回 1 天** → 回填段 CYB 全空（`cyb 86/259`）。属**外部数据源缺口**（非本地 bug）。修法：A 股标的 Yahoo 返回 < `AKSHARE_FALLBACK_MIN=30` 天时改走 `ak.stock_zh_index_daily`。**四条纪律**：① 新浪源无 timeout → 必须 daemon 线程 + `join(AKSHARE_TIMEOUT=15s)`（复用 `fetch_sector_heat` 范式）；② AkShare 返回**全历史**（2010 起，3956 行）→ 窗口须按 Yahoo 序列最早日期裁剪，且**基准必须排除 7×24 标的**（BTC 的自然日会把窗口提前一天，造出「SH/SZ 为空但 CYB 有值」的错位首行）；③ ticker 换算 `000001.SS → sh000001`、`399006.SZ → sz399006`；④ 单标的失败不回退成 0 行（保留 Yahoo 结果并打印）。补齐后 `cyb 243/259` == `sh 243/259` == `sz 243/259`。**口径交叉验证**：AkShare 对 `2026-09-09/10/11` 的 CYB 收盘 `3354.969 / 3338.422 / 3322.039` 与既有 history 行**逐值相同**，可作正确性判据。
- **补写既有行空缺的安全边界（仅限 AkShare 权威补数）**：通用回填**只新增 date 不存在的行**（既有 `None` 有休市/未收盘语义）；唯一例外是 AkShare 补的 A 股键，判据三条同时成立才写：① 该键当前为 `None`、② 该行有 `sh`/`sz` 同类非空（证明是 A 股交易日）、③ 只经 `merge_history` 写（只更新非 None 键、不整行覆盖、不新增日期行）。`--no-patch-existing` 可关闭。实测 157 个键补写：**非 cyb 键改动 0、非法覆盖 0、缺同类行的 0、`last_values.json` SHA256 未变**。
- **回填后必须核对「既有行零改动」与「`last_values.json` 未被动」**：用回填前备份逐键比对（`r.get(k) is not None and a.get(k) != r[k]` → 应为 0 条），并对 `last_values.json` 取 SHA256 前后比对。仅看"行数变多/无报错"不足以证明回填安全。

## 模块 web/（玻璃化 Glassmorphism，2026-09-11）

- **断言区间不能写成「宽松上界」—— 那是恒真断言（假绿）**：玻璃化的 light 档把区间放到 `kpiMax: 1.0` / `dataLo,Hi: 0.5, 1.01` / `border: (0.75, 1.01)` 后，`kpiMax 1.0` 等价于「**alpha < 1**」——即"只要不是完全不透明就通过"，`rgba(255,255,255,.99)` 也能过，**「展示型卡要足够通透」的语义完全丢失**；`1.01` 作为 alpha 上界是坏味道（alpha 不可能 >1，写 1.01 只是为了把 1.0 包进闭区间 → 应写 `≤1.0` 或"无上界"）。**纪律**：区间必须由 token 的**实测值 ± 容差**派生（如 light `--glass-bg=.66` → 断言 `0.5~0.8`），不要图省事放到 1.0。否则将来有人把 light 面板改成不透明白，断言会**静默通过**（与"不同步就是假绿"同类，见上一条）。
- **`@supports` 降级分支属「结构性不可测」，只能做存在性验证，必须记为接受风险**：`@supports not ((backdrop-filter: blur(1px)) ...)` 的求值发生在**解析期**，无法在运行时翻转 —— 而 Chromium 恒支持 `backdrop-filter`，所以该分支**永远不会在无头 Chromium 里激活**。断言 `hasFallbackRule === true` 只证明**规则被解析**，**从未证明降级分支的视觉效果可用**。**纪律**：验收记录里写「已声明、未行为验证」，不要写「已验证」。**可选补验**（比只查"规则存在"强）：用 `page.add_style_tag` 把降级包里的声明**原样注入为无条件规则**，再断言「卡片 alpha ≥ 0.9 + `backdropFilter === 'none'` + 文字可读」——能挡住"降级值写错/变量拼错"这类错。
- **视觉验收/复核必须用「像素差分」判定，不要靠缩略图目视**：本次实录 —— 面板 alpha 从 `.035` 提到 `.12`（3.4×），截图的缩略图上肉眼「看不出差别」，据此差点得出"强度不是杠杆"的错误结论；而 `ImageChops.difference` 差分显示 **32.6% 的像素变了**、卡片/背景对比从 `(9,14,14)` 升到 `(29,34,33)`（3.2×）。**纪律**：`cv2/PIL` 算 `均值差 + 变化像素占比 + 包围盒 + 最大差`，坐标框要先用「变化像素的包围盒」定位、不要凭版面估算（本次因取样框估错，一度误判为"某组无变化"）。另：像素差分的**包围盒**还是判断"影响面是否可控"的唯一客观手段（如光斑只影响 `y0–619` 上半页）。
- **`backdrop-filter: blur()` 在平滑渐变背景上是「空操作」—— 玻璃化的机制边界**：模糊一个平滑渐变，结果与不模糊**肉眼无法区分**（blur 只在背景存在**高频细节** —— 文字 / 边缘 / 纹理 —— 时才可见）。故 `blur` 从 14px 调到 28px **无任何可见效果**，这不是 bug、也不要继续加大 blur。**推论**：想让 blur 可见，唯一的办法是给背景加**细纹理/颗粒**（会带来"背景有纹路"的观感代价）；若拒绝纹理，就只能靠「背景局部对比 + 面板透光 + 亮边」来表达玻璃，**不要把预算花在 blur 上**。配套：`.card.promo` 因自身 `background` 渐变不透明，应显式 `backdrop-filter: none` —— 否则继承来的 blur 看不出效果、白跑一个合成层。
- **PowerShell 管道下 stdout 的中文会乱码/被截断 → 复核必须读「报告 JSON」，不要读控制台文本**：`python xxx.py | Select-Object -Last N` 时中文输出变乱码（GBK/UTF-8 解码错配），且行数被 `-Last` 截断。本次 `verify_ui.py` 的控制台尾部全是乱码，真正可靠的数字来自它落盘的 `%TEMP%\marketpulse-verify\verify-report.json`。**纪律**：验收脚本应**同时落一份结构化 JSON**（本项目 `verify_ui.py` 已落 `url/viewports/failures`）；复核时读 JSON 取值、只用 stdout 判 `退出码`。另：`Get-Content` 在 Windows 上须显式 `-Encoding UTF8`，否则可能触发编码守卫或静默解错。

- **玻璃三要素有严格顺序：不降 alpha 只加 `backdrop-filter` = 零变化（G1 因果链）**：① 背景要有可见内容（`body` 叠多层 `radial-gradient` 氛围）→ ② 面板必须半透明 → ③ 才轮到 `backdrop-filter: blur() saturate()` → ④ 最后才是亮边/内高光/外发光。反例（均实测）：只加 blur 而卡片 alpha=1 → 模糊层**根本不渲染**；alpha 改低但背景是纯色 → 模糊纯色 ≡ 同色 → **视觉零变化**。故实施顺序 **氛围层 → 降 alpha → blur** 不可颠倒（plan R15）。
- **氛围层必须用 `body` 的 `background-image`，不要新增 DOM 层（R16）**：背景不参与布局 → `scrollHeight` 绝不因氛围层变化（实测玻璃化前后 1920 均为 1235）。新增 in-flow 元素会直接顶破 `scrollHeight ≤1240` 验收。⚠️ `body::before{position:fixed;z-index:-1}` 会被 `body` 自身的不透明底色**盖住而完全不可见**（经典陷阱）。
- **CSS 变量未定义会让「整条声明」invalid，而不是只丢那一段（R21）**：`box-shadow: var(--glass-shadow), var(--glass-highlight)` 中任一变量名拼错/未定义 → **整条 `box-shadow` 被丢弃**，表现为「卡片突然没阴影/没底色」，极易误判为选择器写错。退役旧 token（`--card-glow`/`--card-shadow`）时必须先留**过渡别名**（指向新 token），确认无引用后再删。
- **纯 CSS `:checked` tab 的三个坑（G-9；现象是"点了没反应且 Console 干净"）**：① 两个 `input[type=radio]` **必须是 `.tab-panels` 的前置同级兄弟**，`~` 才生效 —— 放进 `.tab-panels` 内部或放到其后 → **tab 完全不工作且不报错**；② radio **不能** `display:none`（会让 label 点击与键盘焦点一起失效）→ 用 `position:absolute; opacity:0; pointer-events:none`；③ `.tab-panels > .panel{display:none}` 必须写在 `:checked ~` 规则**之前**（同特异性下后者胜出）。**必须写成断言**（`radio.compareDocumentPosition(panels) & Node.DOCUMENT_POSITION_FOLLOWING` 为真 + `radioDisplay !== 'none'`），否则该坑只能靠肉眼发现、且极易被误判成缓存问题（已固化在 `verify_ui.py::assert_g9`）。
- **grid 等高（`align-items: stretch`）下 `getBoundingClientRect()` 无法定位"谁把行撑高"**：`.row-3` 三卡等高 → 测量得到的都是同一个行高。**定位法**：累加各卡「非绝对定位子元素高度 + 其 margin + 自身 padding」得到**自然内容高**（本次据此定位 `#us-sectors` 299 > `#sectors` 246 > `#overview` 229 —— 前两轮改动都砍在了非最高卡上，只省 4px）。该探针已固化在 `verify_ui.py::G9_JS` 的 `row3ContentH`。
- **高度预算是"行内最高卡"决定，不是"最有价值卡"决定**：G-9 把两个占位卡搬进 `#sectors` 后，真正撑高 `.row-3` 的是**右卡默认激活 tab 里的 4 列表格**（A股面板），而非新加的 3 个子块。故收敛高度要按「最高卡」下手（本次只对 `#us-sectors` 面板内表格做紧凑化：`th/td padding 4px 8px` + `font-size 12px` → 299→246，总高 1268→1216）。
- **验收断言的区间必须与设计参数同源（本次 plan 内部冲突实录）**：plan §6 G-1 的断言 2/3/5/6（KPI alpha <0.2 / 数据卡 0.6~0.8 / 高光 ≥0.08 / 边框 0.08~0.14）是按 §4.2 **早期建议值**且只按 dark 写的；§4.6.2「效果图校准值」把 dark 改为高光 `.07`/边框 `.20`、light 改为 `.66/.88/.92` 后**只同步改了断言 4**（≥3 层→≥2 层），照原区间实现**必然恒 FAIL**。处置：断言改**分主题区间**（dark `highlight∈[0.04,0.15]`、`border∈[0.15,0.30]`；light `≥0.85`/`≥0.75`），并把测量主题固定为 dark（§7.2 基线本就是 dark 数值）。教训：**改设计参数时必须全量 grep 依赖它的断言**，否则"实施全对但验收不过"。

## 模块 web/（玻璃氛围纹理 2026-09-12）

- **背景层序决定纹理实际振幅**：`background-image` 列表**最前面的层画在最上面**（与 z-index 直觉相反）。纹理放最底层会被上面 3 层渐变按 `(1-α)` 逐层衰减（光斑最亮处实测只剩约 52% 振幅），alpha 调再高都事倍功半。MarketPulse 落法：纹理独占 `--ambient-1`（展开后在最前 = 最上层）、光斑 3 层合写进 `--ambient-2`，body 的 `var(--ambient-1), var(--ambient-2)` 写法不动。
- **背景层数断言用 `>=N` 测不出新增层**：加纹理后 `bodyLayers 4 >= 2` 恒过，纹理漏加/放错层照样全绿（假绿）。新增层必须同时断言三件事：层数 `== N`、第一段（最上层）内容匹配（`/repeating-linear-gradient/`，专防放错层）、alpha 区间；且先跑红（改 CSS 前新断言必须 FAIL）证明断言在测东西。多主题页面注意：light 未同步时新断言要按主题门控（`assert_glass` 里 `if theme == "dark"`），否则 light 档假失败。
- **任一 `--ambient-*` 变量置 `none` 会让背景全丢**：`background-image: <层>, none` 是非法值（`none` 不能作为多层背景列表中的一层）→ **整条声明被丢弃**，页面变纯色，不是只丢那一层；与 R21「CSS 变量未定义使整条声明 invalid」同属一类失效模式。要去掉某层就从列表里**删除**它。
- **verify_ui 基线假阴性：Clash 注册表系统代理劫持 localhost 探测**：`wait_ready` 的 `urllib.request.urlopen` 在无代理 env 时仍读 Windows 注册表代理（`getproxies()` → Clash `127.0.0.1:7890`），Clash 对 localhost 转发瞬时异常 → 40s 内探不到 uvicorn，报「服务未就绪」EXIT=1，与页面无关（本次基线首跑即中招，复跑即绿）。应对：复跑；要根治就在探测处改用 `build_opener(urllib.request.ProxyHandler({}))`。另：`probe_texture.py` 是**自注入式标定工具**（`add_style_tag` 覆盖 `--ambient-*`、光斑用旧位置），只能标定参数、**不能验证已落地的生产 CSS**——验生产页面须另写不注入样式的测量脚本（本次落在 `%TEMP%`，不进仓库）。
- **细纹理最终被用户目视否决（2026-09-12 收尾）**：alpha `.05→.04→.03` 两轮调淡仍「丑」→ 两文件整体回退 `26da86f` 纯光斑验收态，**当前生产 CSS 无纹理层**（上文「MarketPulse 落法」描述的是已回退的中间态）。教训：标定数据只保证「可辨」（.05≈峰谷差12、.022 不可见），不保证「好看」——观感取舍只能由用户看真页面定，且逐档调淡救不了「样式本身不喜欢」。若重提细纹：工具/数据在 `tasks/2026-09-11-glassmorphism-fix/`，先红后绿断言范式在 `git show 2b012d4`。
