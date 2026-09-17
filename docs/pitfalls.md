# 易错点

> 记录反复出现的问题和坑。Agent 修改相关模块前必须先读。

## 通用

- **edit 工具多行替换容易误吞相邻代码**：Hy3 在多期实施中反复遇到——ASCII `+` 被当字面量、长 MATCH 块缺 `»` 导致误删相邻函数。多行编辑优先用 `write_file` 整体重写，避免 patch 锚点漂移。
- **验证期模拟数据后必须恢复**：改 `last_values.json` 模拟异动后运行入口，若取数成功缓存会被真实值覆盖（正常）；若取数失败模拟值会残留——验证前先备份、验证后恢复。
- **monkeypatch 路径常量要打在使用方模块**：`CHARTS_DIR`/`ALERTS_DIR`/`CONTEXT_DIR` 等在导入时绑定，测试必须 `monkeypatch.setattr(使用方模块, "XXX_DIR", tmp_path)`，打在定义方模块不生效。
- **按 `CommandLine` 做模式匹配来杀进程 = 自匹配陷阱（2026-09-16 实测踩到）**：`Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn web\.app:app' }` —— **模式串本身就出现在执行这条命令的 shell/包装进程的命令行里**，于是它匹配到**自己**并把执行者杀掉：命令中途终止（后续输出全部消失，看起来像"只匹配到 1 个"），更糟的是误伤了**别的会话**用来起预览服务的那个 shell。**正确做法**：① 先只读列出监听端口→PID 映射，再**按显式 PID** `Stop-Process`；② 或用不可能自匹配的锚点（`$_.Name -eq 'python.exe'` + `ExecutablePath` 前缀）。**判据**：任何"列出要杀的目标"的筛选条件，都要先问"这个条件会不会命中正在跑它的我自己"。

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

## 模块 src/news_*（最新资讯，2026-09-12）

- **搜索 snippet 是硬截断的碎片，必须「按句切分」而不是砍字数**：Tavily 的 `content` 砍在 200 字处，直接 `summary[:80]` 会得到「…香山股份公告，拟…」这类读不通的碎片；更糟的是它**从不切句**，一条 summary 里可能塞了 3 家不同公司的公告。修法：落盘层（`news_saver._clean_summary`）按 `[。！？；!n]` 取首句、首句 <12 字补第二句、再截到 60 字；**展示层也要再切一次**（前端 `oneLine()` 取 42 字），两层都切才稳（落盘层给宽度余量、展示层兜底单行）。反例：只在前端隐藏标题（不改查询词、不切句）→ 剩下的碎片比加粗标题**更难读**。
- **`_is_junk` 只作用于 title，噪声会从 summary 侧漏出**：`JUNK_KEYWORDS` 里明明有「智通财经」「视野环球」，但过滤只写了 `if _is_junk(title): continue` → 实测第 3 条 summary 尾部残留「视野环球财经 315000 s…」（YouTube 频道名 + 播放量）。修法：新增 `TAIL_NOISE` + **50% 位置门槛**（`idx > len(summary) * 0.5` 才截断）——不加门槛会把正文前段的机构名（如「东方财富报道，…」）连带砍没。
- **snippet 首尾还带「发布时间/栏目名」元数据，切句管不到（已修）**：实测残留 `10 9月 2026, 09:13 情报报告称…`（首部）、`…揭开背后线索 09-09 08:22 9月9日财经早餐：…`（尾部）。另 `[1]`/`[1.3.3]` 参考文献标记会在截断后留下半截中括号（`…30% […`）。修法：`_strip_timestamps()`（4 类时间戳/栏目日期正则）+ 脚注正则 + **尾部悬空时间戳**（见下条）。
- **`snippet[:200]` 会把时间戳截成半截，导致「尾部时间戳」正则漏匹配**：取证得原始片段为 `…\n\n10 9月 2026, 08`（缺 `:MM`）—— 只写 `\d{1,2}:\d{2}` 的完整时间模式匹配不到。修法：尾部模式的时间部分要**可选**：`(?:\d{1,2}(?::\d{2})?)?`。教训：**正则要按"被上游截断后的真实形态"写**，不能按完整格式写。
- **列表型 Markdown 片段会被拼成一条长句（`###` 标题之间没有句末标点）**：实测原始片段 = 多条 `时间戳\n\n### 标题` 循环，按 `[。！？；]` 切句切不开 → 输出「情报报告称… 打击乌克兰… 全球气温再创新高…」三条标题粘连。修法：`## ≥2 个` 标题标记时**只取第一条标题**（单个 `###` 的散文片段保持原样，避免丢正文）。
- **Tavily 片段会把同一条标题连续重复两次**：如「原油飙升逾六周新高 原油飙升逾六周新高」→ 用 `re.sub(r'(.{8,60}?)\s*\1', r'\1', text)` 折叠。⚠️ **该规则会误伤"由重复片段构造的测试串"**：单测里用 `"x" * 20` 造超长文本会被折叠成短串、永不触发截断（本次实测踩到，改用无重复的长句构造）。
- **展示字数是"落盘上限 + CSS 行为"两级，改任一级都要同步断言**：需求方 2026-09-12 反馈「字数显示太少」→ 落盘 `MAX_SUMMARY_LEN` **60→120**、前端 `NEWS_MAX_LEN` **42→120**（两级对齐，不再二次截断）、CSS 由 `overflow:hidden + ellipsis` 改为 **`overflow-x:auto` 横向滚动**（省略号吞字 → 可滚动看全）。⚠️ 三个连带点：① `overflow-x:auto` 下必须显式 `overflow-y:hidden`（另一轴 `visible` 会计算成 `auto`，冒出竖滚动条）；② scroll 容器下 `text-overflow:ellipsis` 本就不渲染，留着是误导；③ 小屏（≤768px）改**完整换行**而非横滚（手机上逐行横滑体验差）。
- **放宽字数上限会同步放大既有的内容噪声**：60→120 后，原本"可容忍"的时间戳/多标题拼接立刻变成最显眼的瑕疵。**改长度上限时要把内容清洗一起纳入验证**，否则"显示更多"会变成净负收益。
- **`::-webkit-scrollbar` 与 `scrollbar-width`/`scrollbar-color` 在 Chromium 里互斥，不能"两套都写当兼容兜底"**：headed Chromium（Windows，1920×1080）逐变量隔离实测根滚动条宽度 ——

  | 写法 | 根滚动条宽 |
  |---|---|
  | 基线（无任何自定义） | 15px |
  | 仅 `::-webkit-scrollbar{width:6px}` | **6px** |
  | 仅 `scrollbar-width:thin` | 10px |
  | 仅 `scrollbar-color:…` | 15px |
  | webkit 6px **+** `scrollbar-width:thin` | **10px**（webkit 整块被丢弃） |
  | webkit 6px **+** `scrollbar-color` | **15px**（连 thin 都不生效，退化成系统色） |

  即 Chromium 只要看到 `scrollbar-width`/`scrollbar-color` 非 `auto`，就**忽略全部 `::-webkit-scrollbar`**。想要 6px 细滚动条：Chromium 分支**只能**用 webkit 伪元素；Firefox 不认 `::-webkit-*`，用 `@supports not selector(::-webkit-scrollbar) { * { scrollbar-width: thin; scrollbar-color: … } }` 路由（Chromium 恒跳过该块）。"两套都写"会得到比不写更丑的结果（15px 系统色）。
- **headless Playwright 测不出滚动条宽度（恒 0），别拿它当护栏**：headless Chromium 用 overlay 滚动条、不占布局宽 → `offsetWidth - clientWidth` 恒为 0，`≤8px` 这类断言在 headless 下**恒真（假通过）**。判滚动条外观必须 `launch(headless=False)`；headless 下改用**查 CSSOM**（遍历 `document.styleSheets` 找 `::-webkit-scrollbar` 的 `width`）作可验证代理。另：`#sidebar` 内容不溢出 → 永不出现滚动条，把它纳入宽度断言等于白测。
- **根滚动条（窗口右缘）不在截图内**：`page.screenshot()` 只截视口内容，浏览器自身滚动条属 chrome UI，截不到 → 只能靠 `window.innerWidth - document.documentElement.clientWidth` 数值判定（headed 才有意义）。
- **`@supports selector(::-webkit-scrollbar)` 在 Firefox 里也返回 `true` → 用它取反做「Firefox 门控」必然失效**：Firefox 出于 web 兼容把 `::-webkit-scrollbar` 当作「合法但未实现」的选择器，`selector()` 同样返回 **true**（Firefox 153 实测）。于是 `@supports not selector(::-webkit-scrollbar) { … scrollbar-width: thin … }` 在 Firefox 里**永不成立** → Firefox 一条规则都没吃到、落到 **17px 原生滚动条**（用户 2026-09-13 报「就 firefox 这样，其他浏览器没这样」）。正确门控用 **Firefox 专属属性** `@supports (-moz-appearance: none)`。同一份 CSS、Playwright 双内核实测对照：

  | 探测 / 结果 | Chromium | Firefox |
  |---|---|---|
  | `CSS.supports('selector(::-webkit-scrollbar)')` | true | **true（陷阱）** |
  | `CSS.supports('-moz-appearance','none')` | false | true |
  | 门控用 `not selector(...)`：实际 `scrollbar-width` / 宽度 | auto → **6px**（webkit 分支生效） | auto → **17px**（整块被跳过） |
  | 门控改 `-moz-appearance`：同上 | auto → **6px**（无回归） | thin → **8px**（Firefox thin 的下限） |

- **headless Firefox 完全不渲染滚动条**：实测 `getComputedStyle().scrollbarWidth === 'none'`、宽度恒 **0**（与 headless Chromium 的 overlay 同源，机制不同结论一致）→ **宽度类断言在 headless Firefox 下毫无意义**（恒真/恒假）。headless 可用的替代判据：① `scrollbar-color` 是否被主题色覆盖（能证明门控块**真的生效**）② CSSOM 里查 `CSSSupportsRule.conditionText` 是否含 `-moz-appearance` 且内部有 `scrollbar-width`。宽度必须 `headless=False` 测。
- **引擎专项 CSS 必须双内核验收**：本次「Chromium 全绿、Firefox 17px」的偏差，只跑 Chromium 的验收脚本**永远发现不了**（我此前 3 轮验收全绿却漏了它）。`verify_ui.py` 已加 `assert_firefox_scrollbar`（N-12，未装 FF 内核则 SKIP 不误报红）；凡涉及 `-webkit-`/`-moz-` 分支、`@supports` 门控、滚动条/表单控件原生外观的改动，都要跑双内核。
- **`StaticFiles` 默认不下发 `Cache-Control` → 启发式缓存导致「改了像没改」**：`web/app.py` 的 `/` 路由已带 `no-cache`，但 `/static/*` 走 `StaticFiles`，**只给 `ETag` + `Last-Modified`、不给 `Cache-Control`** → 浏览器按「(Date − Last-Modified) 的 10%」自行估算新鲜度（可达数小时/天）且**连协商请求都不发**，结果「页面是新的、CSS 是旧的」。2026-09-13 用户把 8021 旧标签页里的旧 CSS（15px 系统滚动条）当成「滚动条被改回去了」——而磁盘 / 线上 Railway / 无缓存浏览器三处实测都已是新的 6px。**排查纪律**：用户报「改动没生效」时，先并列核对 ①磁盘文件 ②服务实吐内容（直接匹配 `.../static/style.css` 里的关键字）③**无缓存浏览器实测**（Playwright 新实例，或 `launch(headless=False)` 看真实滚动条），三者一致则问题几乎必在缓存/另一份副本。**根治**：`_RevalidateStatic(StaticFiles)` 覆写 `file_response` 加 `Cache-Control: no-cache`（仍是 304 协商，不浪费带宽）+ 模板资源 URL 拼 `?v={{ asset_v }}`（`_asset_version()` 取 style.css/app.js 最大 mtime，改文件即换 URL）双保险。⚠️ 改 `web/app.py` 后**必须重启预览进程**，旧进程永远吐不出新逻辑（只有静态文件是随磁盘变的，这也正是"页面逻辑没更新、CSS 却更新了"的原因）。
- **查询词直接决定内容质量，调词前先做 A/B 实测**：同一 Tavily 账号、同一天，三个宏观词的返回是 **3 条（2 条同一标的）/ 1 条 / 8 条**，且内容从「纽元/美元汇率」到「CPI+美联储决议+地缘+原油」差异巨大。旧词 `"A股 美股 今日 重大新闻 政策 利好 利空"` 命中门户《操盘必读》栏目与个股公告拼盘（N-G1）。**结论：先跑 2~3 个候选词比条数与内容集中度，再定稿**，而不是只靠"改过滤规则"。
- **`topic:"news"` + `days:2` 会显著减少返回条数**：`max_results:8` 但实测只回 3 条（近 2 天匹配度高的新闻本就少，遇周末更少）。要「列表饱满」需靠查询词拓宽覆盖面，而不是调大 `max_results`。
- **并排卡片必须两侧都有高度约束，否则行高由"无约束侧"决定**：`.alert-list` 有 `max-height:132px`，而 `#news-body` **原本没有任何规则** → 资讯条数一多就把 `.row-news` 行高从 195 拖到 232，**直接把 `scrollHeight` 从 1216 顶到 1257、破了 ≤1240 护栏**（⚠️ 该破损在本次任务 N-0 基线时就已存在）。修法：`#news-body { max-height:132px; overflow-y:auto }` 与 `.alert-list` 取同值 → 两侧等高（实测 `#news == #alerts == 195`），行高不再随条数漂移。**只在一侧加约束 = 没加约束。**
- **`max_results` 与落盘条数上限是跨文件耦合**：`news_fetcher` 的 `max_results` 改 8 而 `news_saver` 仍 `valid[:5]` → 请求 8 条只存 5 条（静默丢数据）。改任一侧必须同步另一侧。

## 模块 web/（玻璃氛围纹理 2026-09-12）

- **背景层序决定纹理实际振幅**：`background-image` 列表**最前面的层画在最上面**（与 z-index 直觉相反）。纹理放最底层会被上面 3 层渐变按 `(1-α)` 逐层衰减（光斑最亮处实测只剩约 52% 振幅），alpha 调再高都事倍功半。MarketPulse 落法：纹理独占 `--ambient-1`（展开后在最前 = 最上层）、光斑 3 层合写进 `--ambient-2`，body 的 `var(--ambient-1), var(--ambient-2)` 写法不动。
- **背景层数断言用 `>=N` 测不出新增层**：加纹理后 `bodyLayers 4 >= 2` 恒过，纹理漏加/放错层照样全绿（假绿）。新增层必须同时断言三件事：层数 `== N`、第一段（最上层）内容匹配（`/repeating-linear-gradient/`，专防放错层）、alpha 区间；且先跑红（改 CSS 前新断言必须 FAIL）证明断言在测东西。多主题页面注意：light 未同步时新断言要按主题门控（`assert_glass` 里 `if theme == "dark"`），否则 light 档假失败。
- **任一 `--ambient-*` 变量置 `none` 会让背景全丢**：`background-image: <层>, none` 是非法值（`none` 不能作为多层背景列表中的一层）→ **整条声明被丢弃**，页面变纯色，不是只丢那一层；与 R21「CSS 变量未定义使整条声明 invalid」同属一类失效模式。要去掉某层就从列表里**删除**它。
- **verify_ui 基线假阴性：Clash 注册表系统代理劫持 localhost 探测**：`wait_ready` 的 `urllib.request.urlopen` 在无代理 env 时仍读 Windows 注册表代理（`getproxies()` → Clash `127.0.0.1:7890`），Clash 对 localhost 转发瞬时异常 → 40s 内探不到 uvicorn，报「服务未就绪」EXIT=1，与页面无关（本次基线首跑即中招，复跑即绿）。应对：复跑；要根治就在探测处改用 `build_opener(urllib.request.ProxyHandler({}))`。另：`probe_texture.py` 是**自注入式标定工具**（`add_style_tag` 覆盖 `--ambient-*`、光斑用旧位置），只能标定参数、**不能验证已落地的生产 CSS**——验生产页面须另写不注入样式的测量脚本（本次落在 `%TEMP%`，不进仓库）。
- **细纹理最终被用户目视否决（2026-09-12 收尾）**：alpha `.05→.04→.03` 两轮调淡仍「丑」→ 用户指令「只要把纹理去掉，其他不要改」→ **最终态 = 方案 H 三层光斑保留 + 纹理层移除**（dark 档 `--ambient-1`=首层光斑、`--ambient-2`=余下两层；verify_ui.py 回退基线版）。教训：①标定数据只保证「可辨」（.05≈峰谷差12、.022 不可见），不保证「好看」——观感取舍只能由用户看真页面定，逐档调淡救不了「样式本身不喜欢」；②用户「去掉 X」类指令要确认作用范围（本次「整体回退」一度连光斑也带回旧版，被用户纠正）。若重提细纹：工具/数据在 `tasks/2026-09-11-glassmorphism-fix/`，先红后绿断言范式在 `git show 2b012d4`。

## 模块 web/（图表悬停参考线 2026-09-12）

- **Chart.js 同 x 索引内纵向移动不会自动重绘（R1，"横线卡住"的头号原因）**：Chart.js 只在激活元素集合变化时重绘；`mode:'index'` 下鼠标在同一 x 内上下移动集合不变 → 无重绘。必须在插件 `afterEvent` 里手动 `chart.draw()`（**勿用 `update()`**——会重算布局/动画，还可能触发缩放插件重算），并用 1px 粒度节流（`Math.abs(e.y - chart.$crossY) < 1` 直接 return）防高频 mousemove 无谓重绘。`afterEvent` 里调 `draw()` 不会递归（draw 不派发事件）。
- **canvas 插件内坐标一律 CSS 像素，绝对不要乘 `devicePixelRatio`（R2）**：Chart.js 已对 ctx 做过 `setTransform(dpr,…)`，再乘一次在 DPR=2 屏上位置偏移一倍——而 verify_ui 跑在 **DPR=1 测不出来**。DPR=2 客观取证法（替代人工目视）：`device_scale_factor=2` 页面 + 禁用 tooltip（`chart.options.plugins.tooltip.enabled=false; chart.draw()`，消除大块干扰）→ 鼠标移到已知高度 → 截图，在 `(rectTop + $crossY) × 2` 位图行 ±4 内验证「>35% 列有高对比（虚线 4on/4off）」、同时在「×2 bug 位」验证无线。⚠️ 截图像素坐标 = **视口** 坐标 × DPR，canvas 内坐标必须先加 `canvas.getBoundingClientRect().top/left` 再乘。
- **内联插件挂在 `chart.config.plugins`，不在 `options.plugins`**：`new Chart(canvas, { plugins: [myPlugin] })` 后，断言要从 `chart.config.plugins` 里找 `p.id`；`chart.options.plugins` 是选项解析结果，未必含内联插件条目（verify_ui 的 CS-1 两个都查、以 config 为准）。另：给 evaluate 用的 helper（如 `fmtAxisPct`）要写成**顶层 `function` 声明**（进 window），`const` 顶层声明在部分取值路径下不可达。

## 模块 web/（视觉保真 2026-09-12）

- **给列表/网格「加列」必须三处同步，漏一处就错位或溢出**：① `<td colspan="N">` 空态/加载态（grep `colspan` 全仓库清点，本次 5 处 4→5）；② 网格 `grid-template-columns`（本次 `.bar-row` 有**两处**——主档 `:412` 与 375 断点覆盖档 `:521`，只改主档则移动端挤爆）；③ 表头 `<th>` 同步加列。表格溢出靠 `.table-scroll` 容器兜底，网格靠 `minmax(0,1fr)` + 固定图标列宽。
- **nav 照抄效果图会造出死链接（R3）**：效果图里有、页面无对应区块的项（宏观数据/市场日历/设置）必须渲染为 `<span class="nav-item is-disabled" title="未开放">`——**不带 `href` / `data-target`**（`href="#"` 会跳页顶；`data-target` 指向不存在 id 会被 F-5 类断言抓出）。既有 nav 点击 handler 对无 target 项天然安全（`if (!el) return`）。断言要用「总数 == 10 + disabled == 3 + target 全命中」三件套，只查 target 命中在 7 项旧结构上会假绿。
- **切主题不重渲染的列表，图标色必须走内联 `var(--c-*)`**：`iconHtml()` 输出 `style="background:var(--c-gspc)"` 让浏览器在绘制时解析 CSS 变量——主题切换即时生效；若在 JS 里 `cssVar()` 取实值写死，切主题后图标仍是旧主题色（渲染函数不在 theme handler 的重渲染名单里）。
- **Windows 的 Chrome 没有旗 Emoji**：🇺🇸🇨🇳 在 Windows 上渲染成 "US"/"CN" 字母（Segoe UI Emoji 不含区域指示符对），国旗只能 CSS 画（条纹 `repeating-linear-gradient` + 蓝角块 / 红底 + `★` 字符黄星）。**CSS 画旗的定位坑**：`::before{position:absolute}` 需要父级 `position:relative`——共享规则挂的公共类（`.ico.ico-flag`）必须真的出现在元素 classList 里（本次 helper 少拼了 `ico-flag`，皮肤类的渐变生效而定位类静默失效，图标看着「少了一块」）。**class 计数断言测不出这种失效**（类在、规则没命中）→ 旗标类改动必须补像素取证（按 icon 裁剪数旗色像素：蓝角块/黄星/条纹各有独立颜色可数）。

## 模块 web + 持久化/（自选股文件化 2026-09-12）

- **给既有"实时取数端点"加"文件优先"路径，测试隔离必须做在 autouse fixture 里**：`/api/watchlist` 改为快照文件优先后，本机真实 `data/watchlist.json`（随 cron 落盘）会劫持所有未打补丁的既有用例（conftest 只隔离 CONFIG_PATH，不隔离 DATA_DIR）。解法：`_reset_watch_cache` autouse fixture 请求 `monkeypatch` 并默认 `setattr(web.app, "load_watchlist_snapshot", lambda: None)`；快照路径用例在测试体内再覆盖同一名（后 setattr 者生效）。**逐个改既有用例是下策**。
- **monkeypatch 不了"测试环境差异"时先想"谁会读真实文件"**：`load_watchlist_snapshot` 以模块级名字导入到 `web.app` 后，补丁必须打 `web.app`（定义方 analyzer 不生效，同 CHARTS_DIR 纪律）；快照命中用例要同时 mock `fetch_watchlist` 为「被调用即 raise AssertionError」，才能证明"请求路径零联网"，只断言返回值测不出偷偷联网。
- **外部序列进共享趋势图，深度要「取数侧放宽 + 消费侧裁剪」双端配合（三十四期补全）**：macro 趋势默认 `_series_tail(30)` 只够 30D 视图，1Y 下金线只剩右端一小段。正解：fetcher 窗口放宽（3mo→2y）+ `_build_watchlist_payload` 加 `tail` 参数（/api/macro 传 400，/api/watchlist 保持 30）+ **前端按当前窗口起点裁剪并重归一化**（首个非空=100，与 history 系列同基准）——只改后端会把 7D 轴撑到 400 点，只改前端则基准漂移（gc 不从 100 起线）。meta 的 change 按可见窗口覆盖（tail 400 下后端算的是整窗变化）。
- **Playwright 读 Chart.js 轴长**：`c.data.labels` 恒空（labels 在 `options.scales.x.labels`）；且 range 点击后 fetch+重渲有竞态，等待 <1s 会读到旧轴——等待 ≥1.5s 或读 `state.days` 对照。
- **「画图缩放」不是「展示换算」，展示位禁继承图表缩放（三十四期）**：概览卡的 GLD×10 是为与 BTC 万级数值共图归一化的**画图缩放系数**（style/数据管线概念），却被当成"金价"展示（3,987 vs 现货 ~4,348，语义错位）。报价位一律用品种本身的实时报价链路（/api/macro），需要新展示位时先问"这个数是什么语义"，别拿现成缩放值凑。另：并行会话/多执行者环境下改共享文件（app.js 的 OVERVIEW_CARDS/GROUPS），动手前 grep 确认没有其他会话的未提交改动叠加。
- **资讯文件双写者边界（三十三期）**：`context/*.json` 只归 Python（generate_context 覆盖写）、`data/news.json` 只归 Hermes（Python 无搜索能力，决策 G）——Hermes 绝不写 context（会被快照运行覆盖），Python 绝不写 news。`/api/news` 读端逐层容错（坏 JSON/缺 title/url 非 http(s) 逐条过滤、cap 8）永不 500；`target=_blank` 必配 `rel="noopener noreferrer"`。**验证期样例 `data/news.json` 必须删除**（git 追踪范围内，不删会被 cron 提交成假资讯）。
- **grep `data-placeholder` 盘点占位会漏掉「未打标的的死块」**：`#market-relation` 有 4 个写死 disabled 胶囊但从未打占位标记（外表存在、无功能、盘点清单里消失）。点亮这类块要先在页面上人工过一遍「只有外表没有功能」的区块，别只信标记 grep。
- **周六跑 daily_report 会生成非交易日的 context/行工件**：ET 日期=当天（周六）→ `context/2026-09-12.json` 与 history 行落盘 → web `_load_latest_context` 选中它、顶栏/相关对都跟着变。验证后删工件（同 history 行处置），且「API 与 context 对照」必须取**最新日期**的 context 文件而非想当然的某个日期。
- **点亮占位块是「双点同步」操作**：`index.html` 摘 `data-placeholder="1"` 与 `app.js` 的 `PLACEHOLDERS` 注册表删同名项必须同一批改——只摘 HTML 会出现注册表渲染的「数据未接入」覆盖真值（renderPlaceholders 按注册表写 `.ph-note`），只删注册表则占位属性还在。verify_ui 的 G9/视口断言硬编码占位计数（3→2 需同步两处断言点）。
- **storage.DB_PATH 是「补丁打使用方」纪律的有意例外**：storage 函数内 `db_path or DB_PATH` 是调用时属性查找，`monkeypatch.setattr(storage, "DB_PATH", tmp)` 单点全局生效（analyzer/web 全部经 storage 走）；故 14 个测试文件的 patch 点统一迁到 conftest `tmp_db` fixture + `seed_db`（等价旧"写 tmp history.json"），无需逐模块打补丁。
- **NULL 是语义（休市/未收盘），三处必须保真**：迁移脚本 None→NULL、upsert preserve 模式 NULL 不抹（对应 merge_existing 定稿保护）、rows_to_records 全键补 None。change 列保留但一律 NULL（D3）——change_pct 一律读侧相邻收盘价派生，存时点值会引入基准分歧。
- **Railway 恢复链是主数据源不是兜底（D2）**：DB 入 gitignore + Railway 临时文件系统 → 每次部署 DB 必不存在 → web startup `restore_if_empty`（data/backup 按月合并 → 旧 history.json 兼容读 → 空库「数据暂缺」）。pytest 经 conftest `MP_SKIP_RESTORE=1` 跳过（防测试写真实 DB）。恢复只对空库触发（幂等）。
- **backtest 输入冻结（D8 已知缺口）**：`scripts/backtest.py --history` 仍读 data/history.json，切换后该文件冻结不再更新，回测基于截至 2026-09-11 的数据；后续任务加 `--from-db`。
- **北京周六午后跑 daily_report 会 append 非交易日行**：ET 已周六 → get_us_eastern_date=当天（周六）→ Yahoo 返回 None ≠ 最新行值 → 二十五期去重不触发 → 落一行全 None 的非交易日行，顶栏变「周六·休市」。生产 cron 无此窗口；本地验证踩到就删行（同 09-05/06 处置）。
- **迁移类任务的测试迁移必须与 analyzer 切换同批完成**：analyzer 切 SQLite 后、旧 `HISTORY_FILE` patch 变死补丁，未迁移的用例会向**真实 DB** 写测试数据（本期全量 pytest 注入 43 个垃圾日期）；切换后立即全量 pytest 并核对 DB 日期分布（`SELECT DISTINCT date` 畸形/周末日期 = 污点信号）。
- **休市日真跑验证会"静默不执行"**：周六跑 `snapshot_report.py --market a-share --time midday` 退出码 0、但 `_is_market_closed` 门在 main 开头就 return，任何 main 内新增逻辑都不会执行——日志只有一行"休市…跳过"。验证 S5 类"main 尾部新增块"要看日志确认到达了目标代码，退出码 0 ≠ 代码被执行；交易日在验证或走等价单测（S2 同款调用序列已双次真跑覆盖）。
- **"追加决策行/坑位"类编辑禁用"旧文本→新文本"整体替换**：architecture.md 决策表、pitfalls 分节都是 append-only 内容，用「末行锚点 + 旧文保留 + 新文追加」的 new_string 必须把旧文**完整包含**进去，否则静默覆盖历史记录（本任务 architecture.md 决策行被覆盖一次，靠 grep 计数发现并回补）。

## 模块 web/（前端评审落地 2026-09-12）

- **同名 class 承载相反语义时，新组件必须开独立命名空间（`.chg-pill` 而非 `.pill`）**：项目里 `.pill.pos`/`.pill.neg` 是**相关性**语义（正 r=红=同向联动=风险），而涨跌语义是 `.pos`=绿。若给涨跌幅直接套 `.pill pos`，「+0.38%」会变**红色**——涨跌语义反转，且**只查 class 是否存在的断言仍会全绿**（坏在其他地方）。⚠️ 更要命的第二层：全局 `.pos { color: var(--green) !important }` / `.neg{...red !important}` 会**压过** `.chg-pill.pos{color:var(--green)}`，所以「比 color 值」才是有效断言（本次 P-4 用 CSS 变量探针解析出参考色再逐元素比色）。
- **渐变不能写死像素范围**：`createLinearGradient(0,0,0,400)` 在容器高度随断点变化（1920→527 / 1280→395 / 375→439）时与真实绘图区错位 → 渐变截断或填充不满，与 C2「canvas 位图≠显示尺寸」同源。必须按 `chartArea.top/bottom` 动态取。外部评审给的示例代码常写死数值，**照抄即回归**。
- **20px 余量下的增高型改动：行高由「同行最高单元格」决定，别盲目削 padding**：`scrollHeight@1920` 只有 20px 余量（1220/1240），给表格行加 badge 前先算账。实测结论修正了 plan 的预设：在 `padding:7px` 的表（自选列表）里，兄弟单元格已贡献 7+7+行高，badge（≈19px）**没有超出**，行高不变 → 无需削 padding；真正会被撑高的是**全表已紧凑到 4px padding** 的 `#us-sectors` 表格（4+4+17.4 → 4+4+19.4，5 行 +10px）→ 只对该表 `td.chg` 做 4→3px 对冲即守恒。判据永远是**改完实测 `scrollHeight`**，不要按「行数×增量」纸面推算。
- **骨架屏尺寸要用「真实内容盒模型」对齐，而不是拍一个高度**：加载态 vs 数据态的 CLS 判据是「`.row-*` 高度差 ≤8px」。两个实操要点：① 表格骨架行用 `td { height:30px }`（border-box）表达，**不要靠 padding**——`#us-sectors .data-table td` 这类带 id 的紧凑规则特异性更高，会静默压掉 `.sk-row td{padding}`；② 概览 6 小卡骨架用固定 `height` 的独立 grid item（`.sk-card`），比在 `.mini-card` 里塞嵌套骨架更好对齐；③ `prefers-reduced-motion` 已有全局规则会关掉脉冲动画，骨架屏无需重复声明。
- **「加载态转瞬即逝」的断言要么走静态模板源，要么走运行时留存判据**：`colspan=5` 这类加载态属性在 Playwright 里抓不稳（数据到达即被替换），验证时改为读**首页 HTML 源码**正则断言；而「骨架是否被真实内容替换」用可见骨架计数 `offsetParent !== null` 的 `.skeleton` 必须为 0 来表达（两个方向一起测，才既有护栏又有行为）。
- **auto-commit cron 会在你写代码的过程中把改动提交掉**：本任务执行期间外部 Hermes「每日数据更新」cron 连做 3 次 `git add -A`（`0509c66`/`8f399c7`/`590d9df`），把**尚未审阅**的前端三文件与断言直接入库 → `git status` 变 clean、`git diff` 变空，极易误判「改动丢了」。应对：改动是否安全以 `git log --oneline -- <path>` / `git show --stat` 反查，不要只看 `git status`。**推论**：任何「先回退再验证（先红后绿）」的破坏性步骤，在 cron 活跃期都可能与提交竞态，优先改用**非破坏性**手段（运行时探针 / 独立 worktree）。
- **表头与数据格的对齐必须成对施加，且运行时实测才算数**：A 股板块表的「成交额」长期错位——`<th class="col-turnover">成交额</th>` **漏了 `num`**，而数据格是 `<td class="col-turnover num">`（右对齐）→ 表头贴列左缘、数值贴列右缘，实测错开约 49px（列宽 117px、数值文本仅 52px）。⚠️ 「数据格有 `num`」**不能反推表头也有**：`th.num`/`td.num` 是两条独立规则（`.data-table th.num` / `.data-table td.num`），只挂一边就只对齐一边。**断言写法**：逐列比 `thead th` 与 `tbody td` 的 `text-align`，但 ① `th` 被 `.data-table th{align:left}`、`td` 默认计算值是 `start` → **必须把 `start/end` 归一化成 `left/right`** 否则全是假不匹配；② 占位符 `.empty`（「数据暂缺」行）刻意 `center`，**必须排除**，否则自选表失败行会假红。
- **「某列没对齐」类反馈要用运行时几何取证，不要靠看截图**：探针实测 `td` 的 `text-align` 与**文本节点 Range 盒的左右边缘**（`document.createRange(); rng.selectNodeContents(td)`），才能区分「数据格没右对齐」与「表头没跟着对齐」这两种症状几乎一样的成因——本次缩略图上肉眼判断为「数值左对齐」是**错的**，实测右边缘逐行相同证明数据格是对的、错的是表头。

## 模块 src/rss_fetcher.py（RSS 宏观新闻流，2026-09-13）

- **搜索引擎 snippet ≠ 新闻摘要（这是数据源形态问题，调参修不好）**：搜索 API 返回「网页中**含关键词的任意窗口**」，窗口可能落在正文中段 → 碎片且常与标题无关（实测 8 条里 6 条缺陷：标题讲油价、摘要讲俄军；「在欧洲…」「该行进一步…」缺上文）。RSS 的 `description` 是**文章开头**（必定自含）、`title` 是编辑定的完整标题。**展示型新闻流必须用 RSS / 新闻 API；搜索 API 只适合喂给 AI 做归因**（本项目：链路 A 个股归因保留 Tavily、链路 B 新闻流换 RSS）。
- **`_is_junk` 与标题后缀的相互作用（不先剥后缀 = 整条被误杀）**：`news_saver.JUNK_KEYWORDS` 含站点名（东方财富/同花顺/雪球/腾讯证券/智通财经/鉅亨網），而 Google News 标题普遍带 ` - 媒体名`。`news_saver._clean_title` 只硬编码 7 个后缀且不含「财联社/新浪新闻」，因此剥离必须做在 **fetcher 侧**（`_split_source`），来源名填进 `source`。判据：`ns._is_junk("美国8月CPI超预期 - 东方财富") is True`，剥离后为 `False`。
- **标题后缀实测是「双层」，只剥一层会把站名留在标题里**：真实样本 `美国8月核心CPI月率意外高于预期！…90%-市场参考 - 金十数据`（内层 `-市场参考` 是**文章标题自带**的站名、外层 `-金十数据` 是 Google 追加的发布方）。修法：循环剥 `MAX_SOURCE_SUFFIX=2` 层、`source` 只记**最外层**。防误伤：正则要求尾段 ≥2 字且**不含数字**（`油价上涨 - 12.5%` 不会被剥）。
- **多源合并默认必须交错，否则「多源」等于只有一个源**：`RSS_FEEDS` 顺序拼接 + 按日期稳定排序时，第一源（华尔街见闻 55 条）会把 8 条名额**全部占满**（实测 Google News 一条都进不来，与「双源都接」的决策相反）。修法：单源先各取 `PER_FEED_CAP`，再交错合并（`A0,B0,A1,B1…`）后才去重/取前 N；同一天内稳定排序会保留这个交替顺序。
- **Google 侧 `description` 尾部带媒体名，会漏进摘要**：形态 `标题&nbsp;&nbsp;<font>来源</font>`。`_clean_summary` 按句切分时，标题带 `！`/`？` 会天然切掉来源，但**标题没有句末标点时来源就留在摘要里**（`美国8月CPI超预期 东方财富`）。修法：fetcher 侧按**已知来源名**精确剥尾部（`_drop_trailing_source`），不要依赖标点运气。
- **plan/文档里的前端数值可能已漂移，动手前先读代码与既有断言**：本期 plan §R-5 写「`oneLine` 42 字上限、必要时提到 50」，实际 `app.js` 早已是 `NEWS_MAX_LEN = 120` + 单行横向滚动（`overflow-x:auto`，不再用省略号吞字），`verify_ui` 的 N-2 断言口径是 ≤121。照 plan 字面去「调 42→50」会改错地方；同理，plan 里「`valid[:5]→[:8]`」「基线 459 passed」也都是旧版数字。

## 模块 web/（资讯自动滚动 2026-09-13）

- **「保留手动滚动」与 CSS `transform` 动画天然冲突 → 自动滚动必须与手动共用同一机制（`scrollTop`）**：用 `translateY` 卡通内层 track 时，手动滚改的是容器的 `scrollTop`、动画改的是 `transform`，两者叠加会跳变；且容器一旦 `overflow:hidden`，手动滚动就彻底没了；最严重的是 `reduce-motion` 关掉动画后**后面的条目永远不可达**（无障碍缺陷）。`scrollTop += rate*dt` + `requestAnimationFrame` 则让「向上匀速 / 保留手动滚动 / reduce-motion 退化为纯手动」三者共存。
- **`requestAnimationFrame` 必须成对清理，否则速度逐次变快**：重渲染（如 `/api/news` 重新拉取）时不 `cancelAnimationFrame` 会**叠加多个循环**，表现为「刷新几次后越滚越快」。纪律：渲染函数**开头**先 `stopNewsAutoScroll()`（cancel + 重置 `_newsHalf/_newsPaused`）再重建 DOM；`startNewsAutoScroll` 里也再 cancel 一次兜底。
- **`scrollHeight/2` 推导半程不可靠，要用「前一半元素的实测高度之和」**：删掉 `.news-item:last-child{border-bottom:none}` 后每条都带 1px 边框，双份不再严格 2 倍；且 `.news-item a` 的横向滚动条也只在各半出现一次。用 `Σ items[0..n-1].offsetHeight` 与规则是否删除无关，更稳。
- **内容渲染两遍后，既有的「DOM 计数 == 接口条数」断言会集体失效**：本项目 `verify_ui.py` 的 N-1 立刻变成 `(16, 8)`。克隆半必须 `aria-hidden="true"`（否则屏幕阅读器读两遍），**且断言取样要显式排除克隆半**（`clone.contains(el)` 过滤）才能保持原意；克隆半的存在性由单独断言（A-4）覆盖。
- **「某东西不动」类断言必须与「它本来在动」配对，否则是恒真断言（假绿）**：`A-5 悬停暂停（scrollTop 不变）` 在自动滚动**尚未实现**时也恒成立。正确写法是复合断言：先采到「有增长」（`moved=True`），再验证「hover 后 Δ≈0」——两条同时成立才算暂停有效。
- **并行跑重型验证脚本会互相制造假失败（本机实测）**：`pytest` 与 `verify_ui.py`（Playwright）同跑时 —— 图表测试因 `MARKET_CHART_TIMEOUT=5s` 在 CPU 争用下超时失败；rAF 帧间隔被拉长到 ~0.125s 导致滚动采样断言假红。**验证一律串行**；采样类断言要**按时间**（`performance.now()` 窗口）而非按帧数取样。
- **`el.scrollTop += 增量` 是「自吞噬」的：增量 <1px/帧时小数每帧被取整抹掉 → 看起来完全不动**（本项目「资讯滚动卡顿」的根因 A）。`scrollTop` **读回来是整数**（写入的小数不参与下一次读取），所以 16px/s ÷ 60fps = 0.27px/帧时：读到 0 → 加 0.27 → 存 0.27 → 再读回 0 → **永远停在原处**；低帧率下（0.1s/帧 → 1.6px）则取整成 **2px 一格一跳**（观感卡）。**修法**：用浮点累加器 `_pos += rate*dt`，只在 `el.scrollTop = _pos` 这一刻交给浏览器取整；并在**暂停恢复 / 用户手动滚过之后**用 `_pos = el.scrollTop` 重新对齐（否则会「跳回去」）。**反证数据**（0.4px/帧 × 60 帧）：旧实现 60 帧后 `scrollTop` 仍为 **0**，新实现为 **24**。**回归断言**：把速率降到 4px/s 再断言容器仍前进 —— 旧实现必红。
- **滚动重绘会带动全页 `backdrop-filter` 重合成（本项目「滚动卡顿」的根因 B）**：只要页面发生一次滚动重绘，**所有**玻璃卡的 backdrop-filter 都要重跑；无头软件光栅下实测 **8.8fps（滚动中）vs 60.5fps（关全部 blur）vs 59.4fps（不滚动）**。A/B 结论：**只关滚动卡片自己的 blur 无效**（8.6fps），`will-change: scroll-position` / `contain: paint` / `translateZ(0)` **均无效**。→ 排查这类「滚动卡」必须**整页**关 blur 做对照，别只关当前卡。
- **性能取证的三个方法纪律（本任务踩过）**：① 先做 **`about:blank` 对照**区分「环境节流」与「页面慢」——本机 `about:blank` 61fps 而真实页面 9.2fps，一步排除环境；② 采样指标要取**净增量**（`end - start`），别把「最后一帧增量」当净增量（我因此误读了一轮，得出「注入 CSS 后不滚」的错误结论）；③ 断言「不动」必须与「本来在动」配对，且**用 CDP `Performance.getMetrics` 的 `TaskDuration`/`LayoutCount` 判断是主线程忙还是绘制管线忙**（本次主线程仅 32ms/3s、Layout 0 → 直接指向合成/光栅而非 JS）。
- **无头软件光栅下的 fps 不能外推到用户真实浏览器**：GPU 合成下 blur 便宜得多。结论里必须区分「与环境无关的代码 bug」与「仅在本环境测得的绘制成本」，后者要明确写成**取证缺口**并请需求方在真实浏览器复测。
- **多个自动滚动容器必须各自独立状态**：把单容器的模块级全局（`_newsRaf/_newsHalf/_newsPaused/_newsPos`）复用到第二个容器上会互相踩（A 卡的速度/暂停写进 B 卡）。改为 `makeAutoScroller(bodyId, itemSel)` 工厂返回闭包状态，实例化 `newsScroller` / `alertScroller`，并暴露 `window.__scroll` 供验收脚本读内部量。
- **「一个循环周期」不能用条目高度求和**：flex `gap:4px` 的列表（`.alert-list`）求和方法会**少算 n×gap**（3 条差 12px）→ 回绕点可见跳动。用 `items[n].offsetTop - items[0].offsetTop`（克隆半首条相对第一半首条的偏移）对 border 分隔与 flex gap 两种布局都精确。
- **克隆半包一层时用 `display: contents`**：既能挂 `aria-hidden="true"`（防屏幕阅读器读两遍），又不产生盒子 → 父级 `gap` 与条目分隔线保持均匀；用普通块盒会让「第一半 → 克隆半」之间多/少一段间距，回绕点不齐。
- **「内容不足一屏」的判据是「周期」而不是 `scrollHeight`**：双份内容下 `scrollHeight ≈ 2×周期`，恒大于容器高（实测告警 1 条：`scrollHeight 242 > 132` 但 `period 121 ≤ 132` → 正确地不滚）。启动守卫与断言必须用同一口径，否则出现「功能对但断言红」。
- **动画容器的帧率成本不是线性叠加**：实测 1 个滚动容器 8.0fps、2 个 8.1fps、0 个 57.5fps —— 成本在**每帧重绘**（本案是 backdrop-filter 重合成），多一个滚动容器几乎免费（同一帧内一起重绘）。想提帧只治「重绘面」，别去治「几个容器」。

## 模块 src/fetcher.py + web/（美股板块表格化 2026-09-14）

- **「降级为空」的容错会掩盖故障**：`fetch_us_sector_heat` 超时/异常一律返回 `([], [])` 且**不中断日报** → 日报全绿、退出码 0、每日数据 cron 照常提交，只有前端那一块空着（本次截图反馈的「数据暂缺」就是这么潜伏的）。**静默降级必须配可见信号**：日志已有了，但要有人看；前端侧要么给空态加「取数失败」区分文案，要么在 `generate_context` 留 `as_of`/`error` 字段。判据：**失败路径的可见性要和成功路径一样设计**。
- **并发数 > 连接池上限会静默丢连接**：11 个 ETF 线程共用一个 `requests.Session`，超过 urllib3 默认 `pool_maxsize=10` → 实测告警 `Connection pool is full, discarding connection: query1.finance.yahoo.com. Connection pool size: 10`；被丢弃的连接要重建（TLS 握手）→ 最坏耗时被进一步拉长。修复是 `session.mount("https://", HTTPAdapter(pool_connections=16, pool_maxsize=16))`。**推论**：把「并发数」和「独立超时」一起算账 —— 本案最坏路径是 `11×(2 主机 × sleep(1) + 请求耗时)`，所以美股板块单独给了 `US_SECTOR_TIMEOUT=20`（A 股侧继续 10），用**独立超时而不要全局放宽**，避免顺手改坏 A 股链路。
- **把「条形列表」改成「表格」时，`verify_ui.py` 里的旧选择器会静默变 0 → 假绿**：5 处 `.bar-row` 断言（`:149 / :335 / :392 / :521-522 / :773`）表格化后全部返回 0。危险点在于它们**不会报错**：`>= 1` 类断言会变红（可发现），但 `.bar-row .pill == 0` 这类「应为 0」的断言会**直接变假绿**（选择器匹配不到任何东西，恒 0）。改结构时必须 `grep` 一遍被删掉的类名，逐个判断残留断言是「变红」还是「变假绿」——**后者更危险**。
- **改结构后「选择器变 0」还会顺手改掉断言的语义**：同一处 `usSectorRows` 从 `.bar-row` 改成 `tr` 之后，**空态那一行也被计入**，于是「有行」从红变绿——不是修好了，是口径变了。凡是这种顺带变化，都要在 journal 里写清「为什么这条基线红/绿会翻转」。
- **表格化是否增高，判据永远是「改完实测 `scrollHeight`」，不是「数行数×行高」**：`getBoundingClientRect` 看不到根因，「`.row-3` 三卡 stretch 等高 → 行高由**内容更高的一侧**决定」才是机制。本案把矮的一侧（条形列表）改成与高的一侧（A 股表格）**同构且同 5 行**，实测 `scrollH@1920` 从 1216 → 1216（零增高）；反之若沿用旧的 `slice(0, 8)` 就会反超 A 股 → 顶破 1240 护栏。
- **给表格加 `.chg-pill` 必须同时保留 `td.chg` 的 padding 对冲**：`.chg-pill`(≈19px) 高于 12px 文字行高(≈17.4px)，靠 `#us-sectors .data-table td.chg { padding: 3px 8px }` 上下各减 1px 抵消；漏 `chg` 就是每行 +2px × 5 行 = +10px（实测断言 `pad === '3px/3px'`，所以断言要**取 `td.chg` 而不是 `td.num`** —— 成交额列同为 `td.num` 但 padding 是 4px，混进来会误判）。
- **真实数据当天可能就是空的 → 结构断言必须能「无数据也能验」**：本案当天 `us_sector_heat` 为空（偶发超时），靠真实数据永远验不到「有数据时 5 行」。做法是用 `page.route` 把 `/api/latest` 换成**本地注入 5 条 mock 数据**的响应（另开 context，避免污染主页面），再断言 5 行 / 行数相等 / padding / `scrollHeight`；真实页面则单独验空态（表格内一行「数据暂缺」）。**两个方向都测，才既有行为又有护栏**。
- **Windows 控制台是 GBK：`print` 里的 emoji 会让验收脚本中途崩掉**：`print("  ⚠️ ...")` → `UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0'`，脚本在断言中途抛异常（前面的 PASS 已打印，看起来像「跑完了」）。中文能过是因为 GBK 有汉字，**emoji 不在 GBK 里**。写脚本时 `print` 只用 ASCII+中文，emoji 只放注释。自检一行：遍历 `print(` 行 `ch.encode('gbk')`。
- **UI 验收脚本里的硬编码日期断言会随时间变假红**：`check("2026-09-11" in topbarDate, "顶栏显示数据日")` 在日报日期前进后必然失败（本次实测 4 条红，纯噪声，会淹没真失败）。这类「数据日」断言要读 `/api/latest` 的 `date` 前缀来比，**不要写死日期**。

## 模块 web/app.py + 前端（板块陈旧回填 2026-09-14）

- **「整份 context 回看」会掩盖单键失败 → 多键必须逐键独立回看**：`_load_latest_context()` 用 `sector_heat.gainers` 当「这份 context 有效」的判据，而 `sector_heat`（A股，1 个新浪请求）与 `us_sector_heat`（美股，11 个 Yahoo 请求）是**同一天独立取数、独立失败**的 → A股 成功、美股失败的日子，判据成立 → 返回今天的 context → 美股那半边空（2026-09-14 实测就是 `us=0 a=5`）。**推论**：任何"从最近一份有效快照里顺带取走其它字段"的回看逻辑，只要这些字段是独立采集的，就必须**各自成为回看的主键**；历史证据 `2026-09-03/09-04 us=0 a=0` 还说明 A股 也会失败 → **两个键都得做，别只修一个**。
- **陈旧数据回填必须做在读取端，不要做在写入端**：写入端回填会污染 `context.json` 的"当天真实快照"语义（报告侧也会拿到假数据），而且**对当天已经写下的文件无效**（要重跑日报才能生效）。读取端回看 + 在 API 响应里生成 `as_of`（**不落盘**）可以立刻修好当天、且归档文件保持诚实。**代价是「同一份数据在报告里空、在看板里陈旧」的不对称 —— 这是有意设计**（看板：空白比陈旧更糟；归档：必须忠实），要么写进文档要么后人会"统一"它。判据约定：`as_of === date` 不标注 / `as_of !== date` 标注 / `as_of == null` 显示空态。
- **回看要设上限**：`SECTOR_LOOKBACK_MAX`（本案 5 个 context ≈ 5 个交易日），超过就返回空。展示两周前的板块涨跌是**误导**，宁可空白。上限还必须**有测试钉住**（造 `上限+1` 份文件、让第 `上限+1` 份才有数据 → 断言取不到），否则后人调大它没人拦。
- **纯 CSS tab（`:checked` + 兄弟选择器）没有切换事件**：不手动挂 `change` 监听，"随 tab 变化"的文案/状态就不会更新（现象是「A股 tab 上显示着美股的快照日期」）。**连带一个验收陷阱**：程序化设置 `radio.checked = true` **不会触发 `change`** → 验收脚本必须 `el.checked = true; el.dispatchEvent(new Event('change'))` 才能测到真实行为；只改 `.checked` 会得到"功能没生效"的**假红**，反之如果脚本只断言"切 tab 后 DOM 变了"而没派发事件，也可能**假绿**。
- **改函数签名时，「精确 dict 相等」断言的清单要靠 `grep` 穷举，别信计划/记忆里列的那几处**：本案计划列了 6 处，实际 **8 处**（漏了 `test_web.py:360`、`:891`）；同时计划**没列**的 `tests/test_phase8.py:191` 写法一模一样、却是**写入端**断言（断言 `generate_context` 写出的文件）→ 核查后**不该改**。方法论：`grep` 出全部候选 → **逐条判断是读端还是写端** → 只改读端，且一律改成**子集断言**（`assert sh["gainers"] == [] and ... and sh["as_of"] is None`）。**删掉断言让它变绿 = 把真红改成假绿**，明令禁止。
- **「零增高」的判据要就地做 A/B，而不是和历史数字比**：`#us-sectors` 决定 `.row-3` 行高，加任何一行都会撑高 → 新增文案必须放进 `h2` 内的行内 `.h2-sub`（靠 line-height 承载）。验证时**同一页面里**把标注文本写空再量一次（实测 h2 `19 → 19`、卡片 `249 → 249`），比"和上次记录的 249 比"更可靠；窄屏还要单独量 `h2.clientHeight` vs `line-height`（实测 375 档 `17 / 17.4` → 未换行，长文案没有触发 R1 风险）。**附带**：`line-height: normal` 时 `parseFloat(getComputedStyle().lineHeight)` 是 `NaN`，判据要回退到 `fontSize × 1.6`。

## 模块 src/econ_fetcher.py（经济数据源 BLS 2026-09-14）

- **算同比必须"按月份键取去年同月"，不能"取倒数第 13 个"**：官方月度序列**会缺月** —— 实测 BLS 的 `CUUR0000SA0`（CPI-U）与 `LNS14000000`（失业率）都缺 `2025-10`（43 条 vs 完整 44 条，PPI/非农不缺）。按位置取第 13 个会**静默把错月份当基准**：算出的同比是错的、格式也合法、**没有任何报错**，只能靠人工核对数据条数才能发现。正确做法：`"2026-08"` → 查 `"2025-08"`（按键查字典），去年同月缺失才返回 `None`。**推论**：任何"时间序列按位置对齐"的算法（同比、环比、滞后相关）在真实世界数据上都要先验证"位置 == 日期"这一前提。
- **免费 API 的限额要反推 TTL，不能沿用别的端点的 TTL**：BLS 无 Key 限 **25 次查询/日/IP**。若把 `/api/econ` 的 TTL 抄成 `/api/macro` 的 90s → 一天最多 960 次 → **必然超限**（BLS 会返回 `REQUEST_NOT_PROCESSED`，静默降级成空数据）。定 `_ECON_TTL = 6*3600`（≤4 次/日）。**判据：TTL ≥ 24h ÷ 限额次数**。而且**失败不能写缓存**——否则一次网络抖动会把"空数据"锁死一整个 TTL 周期。注释里要写清"为什么是 6 小时"，否则后人一定会把它"优化"成 90s 对齐。
- **"数据新鲜"≠"数据是当期的"：展示口径要用数据月份，不要用抓取时间**：经济数据有**发布滞后**（8 月 CPI 到 9 月中才公布），用 `date.today()` 当 `as_of` 会让前端把 8 月的数据标成"最新/实时"。`as_of` 一律取 BLS 返回的**数据月份**（`"2026-08"`），单序列各自的月份另放 `series[].date`；前端据此显示「2026年8月」而不是「刚刚」。
- **同一家的"同族接口"行为可能完全不一致，不要按家族假设**：AkShare 的 `macro_usa_cpi_yoy` 1.0s / 数据到 2026-08 可用，而 `macro_usa_ism_pmi` / `macro_usa_gdp_monthly` / `macro_usa_unemployment_rate` 等全部**停更在 2025-09**（一年前）且耗时 9.5~28s。探针证据：`cpi_yoy` 的列是 `时间/发布日期/现值/前值`，其余是 `商品/日期/今值/预测值/前值` —— **它们来自不同的上游数据源**。结论：选源必须**逐个接口实测**（数据月份 + 耗时），不能因为同属一个库就整族采用；**耗时超过项目最大超时预算（`US_SECTOR_TIMEOUT=20`）的源一律不能挂在 Web 请求路径上**。

## 模块 web/ 宏观页 + src/fetcher.py（/macro 2026-09-14）

- **「业界常识」必须实测，它会写出反向的转换规则**：`^TNX 是收益率×10` 是流传很广的说法（CBOE 的指数点位的确是 ×10），但 **Yahoo chart API 返回的就是百分数** —— 实测 raw 末值 `4.985`、5 年前 `1.277`（对应 2021-09 的真实 ~1.3% 历史事实）。若照"常识"写 `÷10`，会把 4.985% 显示成 **0.4985%**，即"为了防止某个错误而制造出那个错误"。**判据：任何换算规则都要给出实测首尾值 + 与已知历史事实对齐**（这里用"2021-09 的 10Y ≈1.3%"一步证伪）。配套做法：换算只放在**显示层单一函数**（`toYieldDisplay`）、量级越界时 `console.warn`（**不静默校正**）、并加断言把当前口径锁死（`4.985 → 4.979%`）；如果写成静默换算，上游改口径就永远没人发现。
- **共用取数函数的窗口参数必须参数化，不能改默认值**：`_fetch_yahoo_watch` 被**自选股（只要 30 天）与宏观（要 5 年）共用**。把 `range` 默认从 `2y` 改成 `5y` 会让 `/api/watchlist` 也多取 2.5 倍数据、变慢，而且**静默**（没人会为此报错）。正确做法：加 `range_="2y"` 参数、调用方显式传 `"5y"`，并**加一条透传断言**（`seen == ["2y","5y"]`）—— 否则将来有人"顺手"把默认值改大，测试也不会红。
- **改函数签名前必须 grep 所有 `monkeypatch.setattr` 的 lambda 桩**：plan 里"默认值不变 → 不应有任何失败"的推断是**错的** —— `tests/test_phase24.py` 的桩是 `lambda s: …`（单参），函数多一个参数后调用直接 `TypeError`。桩要 `lambda s, *a: …`、`def bad(s, *a): …`。**注意：是同步桩签名，不是删断言** —— 后者会把真红改成假绿。
- **同一份数据在两处的键风格必须统一（否则静默失效）**：`/api/macro` 的 `trend.series[].key` 是 **`sym.lower()`**（如 `"dx-y.nyb"` / `"^tnx"`），而相关性对若按**展示符号**写（`"DX-Y.NYB"` / `"^TNX"`）→ 每对都取不到值 → **6 对全部 `r=None`**，页面表现为「永远样本不足」，**不报错、不崩、也不一定被测试抓到**。这违反项目既有纪律（`analyzer._HISTORY_KEYS = frozenset(s.lower() …)`，history 一律小写键）。**判据：跨模块引用序列键时，先写出键的产生式（`sym.lower()`）再查表。**
- **利率类指标的变化要用「百分点」而不是「百分比」**：`4.00% → 4.30%` 的百分比变化是 **+7.5%**，而阈值是按**百分点**定的（0.10 / 0.25pp = 10 / 25bp）→ 量纲不符会让**任何变动都顶格**（该维度永远饱和，打分失真）。实现上要分开两个函数：`_chg_pct`（价格类，百分比）与 `_chg_abs`（收益率类，绝对值差）。
- **抽 Jinja include 后必须跑既有 UI 验收；失败先分清「方案不可行」还是「断言脆弱」**：本次抽 `_topbar/_sidebar` 后 `verify_ui` 只红了一条 `F-5`，实测值是 `navDisabled: 2`（原断言写死 3）+ `navBad: ['宏观数据']` —— **根因不是 include 破坏了渲染**（其余断言全绿），而是这条断言编码了旧产品决定（"非锚点导航项必须都是占位"），且其 `navBad` 规则把**合法的跨页链接**判成坏项。正确处置：**把失败断言的原文与实测值记进 journal**，然后按新意图**补强**断言（新增 `macroHref == "/macro"` 的正向断言 + 让 `navBad` 放行 `href` 以 `/` 开头的跨页链接），而不是删掉它。⚠️ 反例：若断言依赖的是 `#sidebar` 与 `.topbar` 的兄弟位置关系，那就是**方案不可行**，应按 plan 回滚改成"复制侧栏"。

## 模块 web/static（KPI 响应式断点 2026-09-14）

- **少数固定视口采样有"断点空档盲区"：`ALL PASSED` 可能正在掩盖真实缺陷**：`verify_ui` 原本只测 **1920 / 1280 / 375** —— 1920 与 1280 落在两个**正常区**、375 是单列也正常，**恰好全部避开** `1500–1919`（五列档无任何中间断点，卡宽从 314 缩到 230 而字号恒 26px）与 `769–1024`（侧栏仍内联 232px，三列卡宽只剩 152–237px）两个坏带 → 脚本报全绿，用户在小窗口看到数值被省略号吃成 `7,656…`。**判据**：凡是**响应式/断点类改动**，验收必须补「断点之间的中间宽度」采样，且**从区间下沿（断点-1px）比从区间中点更容易打到最差点** —— 实测 1500px 截断 **24px** 比 1600px 的 4px 严重得多。做法：**载入一次页面 + 逐宽度 `page.set_viewport_size()`**（媒体查询即时重算，不重载，12 个宽度只多 ~2.5s）。
- **`max-width` 缩元素 ≠ 释放空间：网格轨道要先改**：把 `.kpi-spark { max-width: clamp(48px,5vw,96px) }` 当成修复**完全无效** —— `.kpi-card` 的轨道是硬编码 `grid-template-columns: minmax(0,1fr) 96px`，`max-width` 只把**元素**缩窄、**轨道照样占 96px**，文本列一个像素都不会多（本次 plan §4.1 只写了 max-width，实测/读码后才发现，改为 `--kpi-spark-w` 自定义属性让**轨道与元素共用同一变量**才生效）。**推广**：凡是「固定轨道 + 内部元素被约束」的布局（grid/flex-basis），想释放空间必须改**容器侧**，只改子元素约束只会留下空白。
- **响应式断言只断「不变量」，不要断死字号/断点数值**：本次断言写的是「KPI（数值/副标题/标签）不得被省略号截断」（`scrollWidth > clientWidth + 1` 即判失败），**没有**断言任何具体 px 或列数 —— 所以后续调 `clamp()` 系数**不需要改断言**。反过来若断死「1500px 时字号必须是 21px」，调参一次就要改一次断言，最终必然退化成"改断言让它变绿"。**配套**：给扫描加一条"覆盖度断言"（本次 `KY-3` 断言确实扫满 12 个宽度），否则选择器/渲染一旦变化，扫描会**空跑并全绿**。
- **验收脚本里依赖外部 API 的断言要容忍一次瞬时失败**：`MX-11`（宏观页显示「YYYY年M月」）依赖 BLS，实测遇到 1 次**服务端调用瞬时失败** —— 表现为页面 200 + `console error = 0` + 该模块「数据暂缺」（端点按设计**不缓存失败结果**）。直接重载一次即可恢复。处置：断言前**重试一次**（**不放松判据**），否则外部网络抖动会被当成页面缺陷，久而久之没人再看这个脚本的红色。

## 模块 web/templates + web/static（/macro 专业化 refinement 2026-09-14）

- **`<html data-theme="…">` 硬编码 + 内联脚本只处理单一主题 → 另一主题静默失效**：`macro.html` 的 `<html data-theme="light">` 是**默认值**，内联脚本却写成 `if (localStorage.getItem("mp-theme") === "light") { setAttribute("data-theme", "light"); }` —— 存储为 `dark` 时**没有任何代码把 dark 写回**，属性停在 `light`。首页之所以正常，是因为 `app.js` 在模块顶层做了主题初始化；`macro.js` 里虽有 `getTheme()`，却只在**点击切换按钮**时才调用 → 首页深色 → 点进 `/macro` **突然变白**，且**不报错、不崩、测试也测不到**（原验收只在"点击切换"后断言，从未测"带偏好进入页面"）。**判据**：多页应用每个页面的主题初始化必须**同口径**（head 内联脚本负责"显式应用存储值"、页面 JS 负责"运行时切换"，两者共用同一函数），且验收必须**显式 `add_init_script` 写入 localStorage 再加载**，并**断言两页同偏好行为一致**（只看代码很容易漏）。
- **「标注」与「行为」必须同源，否则 UI 会静默造假**：页面写着「相关系数 \|r\| ≥ 0.5 才列出」，实际把 6 对**全部**列出（实测最大 0.47，无一条达阈值）—— 过滤根本没实现，后端也没有阈值参数（`compute_macro_correlation` 固定返回 6 对）。用户会**据此做出错误判断**（以为看到的是"强相关"），而页面既不报错也不为空。**判据**：凡是"我们只显示满足 X 的条件"这类文案，X 必须是**代码里的同一份常量**（本次 `REL_MIN/REL_TOP/REL_FALLBACK` 同时生成过滤逻辑与文案），并且**给容器挂可验收的状态属性**（`data-rel-mode`）让断言能校验口径，而不是仅校验文案字面。
- **界面"看起来空"≠知道空在哪：先量再改**：我先把 `.regime-score` 由右对齐改左对齐，理由是"右对齐造成双空档"——**改完看截图几乎没变化**（该列是 `auto`、宽 85px，对齐只挪 ~15px）。回去量列宽才发现真因是**左列被 `1fr` 拉到 587px 而 hero 文案只有 ~212px**（栅格 `[587, 85, 675]`）；改成 `max-content auto 1fr` 后为 `[212, 85, 1050]`，~380px 空档归零。**教训**：视觉类改动的第一步是**量化**（列宽/内容宽/间距），否则会按"看起来像"的假设改，改完还无法证明有效。同理：**"收紧 A 处"往往只是把留白搬到 B 处**（左列收窄后富余宽度全给右列，必须在右列内再分栏才真正用掉）。
- **把留白交给 `align-self: start`，别让 grid 的默认 stretch 制造空转**：`.mac-2col` 的 `align-items` 默认 `stretch` → 内容只要 133px 的 `mac-factors` 卡被拉到与兄弟等高 230px，**77px 完全空转**（且它看起来"就是设计成这样"，不会有人报 bug）。**判据**：并列容器里的"内容高不等"是常态，容器侧要么 `align-self: start`，要么让短的一侧承担信息密度（本次给因子加"市场影响"行），两者都要做。量化验收写成"额外留白 = 元素高 − 标题 − 内容 − padding ≤ 20px"即可长期锁住。
- **插件选项里的函数会被 Chart.js 当 scriptable option 立即调用（不是"存函数"的地方）**：把读数格式化器写进 `options.plugins.hoverCrosshair.formatter` 后，只是**读**
  `c.options.plugins.hoverCrosshair` 就抛 `TypeError: Cannot convert object to primitive value` —— Chart.js 对插件选项做了 scriptable 解析，读到函数值会**立即以 context 调用**它（期望 `(ctx) => value`），于是我们的 `formatter(v, chart)` 收到 context 对象、`isFinite(object)` 直接炸，**整页不可用**。正确做法：把函数挂在**实例级插件对象**上（`plugins: [makePlugin({ formatter })]`，`config.plugins` 是纯数组、不走选项代理），插件内部按 `id` 取回。**判据**：往 `options.plugins.<id>` 里放回调前，先确认它不会被当作"每帧求值的 scriptable 选项"；同理，**验收探针也不要读这个路径**（读一下就复现同一个异常）。
- **同一插件跨页复用时，读数格式化器必须可注入**：首页 crosshair 的 `fmtAxisPct(v) = (v-100)+'%'` 是"相对 100 的偏离"，而宏观页单变量模式的 y 轴是**真实价格** → 直接搬过去会把黄金 `4386.60` 读成 `+4286.6%`；反过来，宏观页的格式化器若再调一次 `displayValue(k, v)`（建数据集时已经调过）会把 10Y `4.987` 变成 `0.4987%`。两处都**不报错、console 干净，只是数字荒谬**。做法：插件本体共享 + 格式化器按实例注入 + 断言锁**不变量**（"单变量不得出现 `%`"、"读数必须等于该高度的轴值"），而不是锁具体数字（黄金 4500.87 这种值每天在变）。
- **`<script>` 顺序错 → `plugins: [undefined]`，Chart.js 静默忽略**：共享插件文件必须在各页业务脚本**之前**引入；顺序反了既没有异常也没有 console 输出，表现只是"横线没出来"，极易误判成插件 bug。验收要有一条**显式断言**（`config.plugins` 里含该插件 `id`）来区分这两种情况。
- **自动提交 cron 会让"`git stash` 取改动前基线"空跑**：本项目有几分钟一次的 `auto: 每日数据更新` 提交，`git stash push` 常常输出 `No local changes to save` → 你以为在跑"改动前"，其实跑的还是新代码（**假基线**）。可靠做法：`git log --diff-filter=A --format=%H -- <新文件>` 找到引入改动的那次提交，`git checkout <parent> -- <目标文件>` 临时回退、跑完 `git checkout HEAD -- <目标文件>` 恢复，并用 `git status --short` 核对已复原。
- **验收断言里写死日期/数据日 = 定时炸弹**：`check("2026-09-11" in topbarDate)` 这类断言在当时是绿的，**数据日一推进就必红**；`V-2`（A股 tab 必须为空）则隐含假设"今天数据一定新鲜"，周末/节假日/盘中都会让 `as_of != date` → 页面**正确地**显示"数据截至 …"，断言却判红。**判据**：期望值一律**从被断言的同源数据取**（本次取 `/api/latest.date` / `.as_of`，与 `V-3` 同款），只在取不到时退化为"格式校验"，**不放松不变量、不写死数值**。判断"红是不是我改出来的"也要有硬证据：`git log --name-only` 证明改动文件范围 + 失败值是否来自数据（而非代码）。

## 模块 src/reporter.py（context 同日合并 2026-09-14）

- **`generate_context` 是全量覆盖写，按市场子集取数的入口必须传 `merge=True`**：`snapshot_report.py` 的 `fetch_all(market)` 只返回本市场键（`--market us` → 只有 GSPC/IXIC），但 `generate_context` 从零重建 payload 后 `os.replace` 全量覆盖 `context/{date}.json` → **A 股快照与美股快照互相抹掉对方的数据**（日期口径还不同却撞同一文件：a-share 用北京日期、us/daily 用美东日期），且随后被 `auto_commit_push` 推送 → 损害持久。实测 `fd0602d`：一次 `us open snapshot` 把 `context/2026-09-14.json` 从 90 行砍到 12 行，删掉 10 条 A 股板块数据 + 5 条 `search_keywords`，并把 SH/SZ/CYB 写成 `null` + `"休市"`（当天是周一）。
- **合并必须做在「输入」而非「输出」**：`breach` 与 `search_keywords` 是从 `values` 派生的（`build_search_keywords(date, breaches, sector_heat)`）。只在 payload 层回填旧值 → `search_keywords` 仍退化成 `["market summary {date}"]`。正确顺序：**先合并 `values`/`changes`/`statuses`，再让派生字段自然重算**（合并点必须在 `collect_breaches` 之前）。判据：合并后 `search_keywords` 里是板块词（`医药 surge {date}`）而不是 `market summary`。
- **`values` 的键集就是「本次覆盖范围」，不是「值非空」**：`values["GSPC"] = None`（取数失败）要写 `null`（本次主题、诚实反映失败），而 SH/SZ/CYB **根本不在 `values` 里**（本次不管）必须保留旧值 —— 两者只有 `sym in values` 能区分。配套：**调用方不得把 `None` 转成 `[]`**（原 `sector_heat if sector_heat else []` 产生的 `[]` 会被判为"要覆盖"，修复整体失效）。`merge` 默认 **False**（daily_report 全量写、既有测试零改动），快照侧显式 `merge=True`。
- **`statuses` 只能回填 label**：context 只存 `statuses[sym][0]`（label），磁盘没有 `desc` → 合并时回填 `(旧label, "")`；`generate_context` 只读 `[0]` 故安全，但别把 context 里的 label 当完整状态元组用。
- **同日合并与跨日期回看是两件互补的事，不要"统一"**：`generate_context(merge=True)` 保证**同日**多市场互不抹除；`web/app.py::_find_context_with_key` 保证**空壳日**不空白。把合并改成"跨日期取旧值"会让归档文件不再忠实于当天（看板空白 vs 归档诚实的取舍见"板块陈旧回填"条）。
- **入口类测试（`dr.main()`/`sr.main()`）漏隔离 `reporter.CONTEXT_DIR` 会写真实 `context/`（改动前既有，2026-09-14 已修）**：`reporter` 在 **import 时绑定** `CONTEXT_DIR`（Path 对象），所以把补丁打在定义方 `analyzer` 上**完全不生效** → `generate_context` 写真实 `context/YYYY-MM-DD.json`。**主污染源是 `tests/test_phase27.py::test_snapshot_passes_history`**（`sr.main("a-share", "midday")`，未隔离）：它把 `context/2026-09-03.json` 覆盖成 `VIX 21.0 / change_pct null / 1 条 history / 空板块`（与该测试的桩数据逐项吻合），并被 `auto: 每日数据更新` cron 提交（`da152fe`，333 行删除）。同文件 `test_generate_context_excludes_today` 另有一处同类错位（`an.CONTEXT_DIR`/`an.load_history` 应为 `rep.*`）—— 它写的 `20.0/0.0` 版本被前者覆盖，且其断言**真空通过**（读的是真实 DB，其中本就没有 `2026-09-03`）。
- **同类漏隔离：`dr.main()` 末尾的 `export_monthly_backups()` 会写真实 `data/backup/`**：`storage.DEFAULT_BACKUP_DIR` 默认 `data/backup/`，而测试只 patch 了 `st.DB_PATH` → 用 tmp DB 的行**覆盖真实当月备份文件** `data/backup/history_2026-09.json`（Railway 恢复链的数据源）。逐个改用例是下策 —— 已在 `tests/conftest.py` 增加 autouse 护栏 `isolate_real_output_paths`（重定向 `rep.CONTEXT_DIR` + `storage.DEFAULT_BACKUP_DIR` 到 `tmp_path`，与 `isolate_watchlist_file` 同款纪律），测试体内显式 patch 仍在其后生效。
- **`generate_context` 的 `history` 入参必须是全键宽记录**：`history_30d` 是 `[r["vxn"] for r in history]` 这类**按键取值** → 修对 patch 目标后，原先的窄记录 fixture（只有 `date`/`vix`）立刻 `KeyError`。写 context 相关测试用 `{k: None for k in st.HISTORY_KEYS}` 补全，或走 `st.rows_to_records(...)`。
- **判据（不要靠读代码推理）**：跑入口类测试文件**前后**比 `git status --short` —— 跑前 clean、跑后出现 `M context/*.json` / `M data/backup/history_*.json` 即为铁证。修复后同一批 6 个文件（`test_phase27/25/24/8/12/14`，100 passed）跑完 `git status` 无这两类改动。
- **找回被反复污染的历史文件：不能取「上一个提交」，必须按内容筛选（与「cron 抢提交」同源）**：本仓库 cron 每几分钟 `git add -A`，被测试覆盖的 `context/2026-09-03.json` **连续 10+ 个提交都是污染版**（`gainers=0`、`history_30d` 尾日期 ≠ 文件 `date`、甚至出现 `20260903` 这种无分隔线的假日期）→ `git log -- <path>` 取到的"上一个版本"`bd2c3ff` 同样已被污染（一度被我误当成正常版）。**判据**：逐版本 `git show <h>:<path>` 校验**内容不变量**（`date` == `history_30d.dates[-1]`、板块非空、键集齐全）—— 实测唯一合格版本是 `c30e2131`（`auto: 2026-09-03 daily report`：9 键齐全、A 股板块 5+5、美股板块 5+5、关键词 5 条、correlation/watchlist 有值），已 `git checkout c30e2131 -- <path>` 恢复。

## 模块 src/git_ops.py（自动提交范围收窄 2026-09-14）

- **`_has_changes` 必须与 `_commit` 的 add 同范围，否则日志与返回值双重失真**：只把 `git add -A` 收窄成 `git add data context alerts`、却留着全量 `git status --porcelain` 判"有无改动"，会出现：只有源码 WIP 时 → status 非空 → 判"有改动" → add 无内容可暂存 → `git commit` 报 `nothing to commit` → `CalledProcessError` → 打印 `[auto-push] Failed`。**进程不崩，但返回值语义从「数据没变」错标成「提交失败」**，日志还会把人引向"push/网络有问题"的方向。判据：`status` 的 pathspec 与 `add` 的实参必须来自**同一个常量**，并断言两者 `"--"` 之后完全相等（`test_status_limited_to_paths`）。
- **`.gitignore` 命中的路径不能进 `git add` 白名单；白名单目录"整体不存在"会让提交链直接 fatal**：显式 pathspec 一旦被 ignore 规则命中，`git add` 立即报 `The following paths are ignored by one of your .gitignore files`（`reports/` 即此类，tracked=0，原本靠 `-A` 隐式跳过）。同源边界（实测）：`git add <paths>` 对**存在且为空**的目录 → `exit=0` ✓；对**根本不存在的**目录 → `exit=128 fatal: pathspec 'x' did not match any files` ✗ → 三个入口的数据提交全失败，且只打一行 `Failed`。本仓库 `data/` `context/` `alerts/` 均含 tracked 文件故不受影响；**不要**为"容错"改成动态过滤路径（那会让白名单失去唯一事实来源、测试也无法钉死实参）。
- **桩测试只能证明"参数传对了"，"半成品真的不会被提交"必须用真实 git 证明**：`subprocess.run` 全打的单测能验分流与实参，但验不了"提交后 `git log --stat` 里到底有没有那个文件"。做法：临时目录 `git init` → 造「数据改动 + 源码 WIP + 被忽略文件改动」三种脏状态 → 调 `auto_commit_push(root=<tmp>)`（无 remote → push 失败返回 False，**但 commit 已落盘，这正是要验的**）→ 断言 `git show --name-only HEAD` 只含数据文件、且 `git status --porcelain` 里源码 WIP 仍在。**不要在业务仓库真跑**（会 push → 触发 Railway 重部署 + 与外部 cron 抢提交）。

## 模块 src/cn_econ_fetcher.py（中国宏观 2026-09-14）

- **AkShare 的「列名」就是停更指纹（选源第一判据）**：列名 `商品/日期/今值/预测值/前值` = 东财报告族，**实测停更在 2025-09 且耗时 5~20s+**（`macro_china_pmi_yearly` 10.5s / `m2_yearly` 18.5s / `trade_balance` >20s）；中文语义列（`月份/全国-…`、`季度/…`、`TRADE_DATE/…`）= 统计局/央行族，**<1.2s 且新鲜到 2026-08**。与既有 `macro_usa_*` 同族结论一致 → 同一上游问题，不是偶发。**推论：选源必须逐个接口实测（数据月份 + 耗时），不能因为同属一个库就整族采用**；耗时超过项目最大超时预算的接口一律不能挂在 Web 请求路径上。
- **排序口径不统一 —— 一律按周期键排序后取尾，禁用 `iloc[-1]` / "取第 N 个"**：实测 `cpi`/`ppi`/`pmi`/`gdp`/`m2`/`credit`/`retail` 是**倒序**（`iloc[-1]` = 2008 年），而 `social_financing`/`unemployment`/`house_price`/`lpr`/`shibor`/`bond_10y` 是**正序**。探针第一版照 BLS 版"取尾"的写法实测把 cpi 的最新值读成 `2008-01`（滞后 224 个月）。**判据**：取最新前先 `_sort_rows()`，探针与生产侧同纪律。
- **季度键必须按「区间里较大的季度号」折算月份，否则滞后告警永远假红**：`2026年第1-2季度` → `2026Q2`（不是 `2026-01`）；算滞后月数时 Q2 → 6 月（Q×3）。若按第一个数字算，季度 GDP 会**永远**触发"落后 >3 个月"。
- **扩散指数（PMI）必须取「水平」与荣枯线比较，不能取同比方向**：PMI 49.8（< 50 = 收缩）与它的同比 +0.81%（方向 up = 扩张）**结论相反**。美股版 `_growth_axis` 用同比方向是因为拿不到 PMI 才用就业替代；照抄到有真 PMI 的中国版就会得出反向结论。**判据**：单测要构造"水平与方向相反"的用例（49.4/49.0/49.8 → 方向 up 但水平 contracting）。
- **「70 城房价」是错误先验**：`macro_china_new_house_price` 实测只有 **北京、上海 2 城**（374 行 = 2 城 × 187 月），且 `新建商品住宅价格指数-同比` 是**指数（上年同月 = 100）** → 同比% = 值 − 100（上海 103.0 = +3.0%、北京 97.7 = −2.3%）。⚠️ 文案校验断言（"不含 70 城"）会命中 `basis` 里的 `非 70 城` 这种否定写法 —— **basis 文案也别写这个字面量**（本项目改为"仅覆盖北京·上海两城"）。
- **长表接口必须显式过滤 item，且 item 带尾随空格**：`macro_china_urban_unemployment` 是长表（date/item/value），item 有 4 种且实测为 `'全国城镇调查失业率 '`（**末尾有空格**）→ 必须 `.str.strip()` 后再精确匹配。
- **`bond_china_yield` 区间敏感（1 年窗口返回 0 行）**：6 个月窗口 → 411 行；1 年窗口 → **0 行**（上游行为，非 bug）。固定 6 个月窗口 + 空结果守卫，并把它写进探针的"已知行为"（`PROBES_REJECTED` 里的 `bond_china_yield_1y`），否则后人会当 bug 去"修"。**副产品**：一次请求返回 3 条曲线 → 信用利差（商金债AAA − 国债）免费获得，补上了美股版因 FRED 不通而放弃的信用维度。
- **并发度不是"越小越礼貌"，实测并发 13 反而最快**：串行 22.2s / workers=3 → 15.2s / workers=6 → 13.6s / **workers=13 → 10.3s**。13 个接口都是等网络，排队只会把总时长摊长；墙钟由最慢的单接口（`bond_china_yield` 8s）决定。TTL 6h → 一天 ≤4 次，不会限频。
- **分组端点必须「分批」才有收益：6 个组同时发 = 没有收益**（13 个上游请求照样同时在飞，墙钟不变）。正确做法：先 `price`+`growth`（≈3.6s）出四象限，再其余组逐组填充。⚠️ 配套：四象限需要**跨组**的 cpi/ppi + pmi/gdp → 服务端要保留**跨组累积的 raw 缓存**，否则分组响应里永远拿不到 `quadrant`。
- **"部分失败照常缓存"与"失败不写 ts"是两件事，缺一都会出错**：13 个接口相互独立 → 只有全部失败（`as_of` 为空）才不缓存 payload；但**失败的 key 也不能写 raw 的 ts**（否则一次网络抖动把空数据锁死 6h）。只做前者会变成"失败被 ts 锁死"，只做后者会让成功的结果也每次重打。
- **mock akshare 时桩函数必须接受 `**kwargs`**：`bond_10y` 走 `AUTO_6M` 哨兵，会传 `start_date/end_date`；桩写成 `lambda: df` 会 `TypeError` → 被 `_fetch_one` 的 try/except 吞掉变成"返回空"，表现为**断言莫名其妙的 None**（不是取数失败）。
- **中文字符串排序不是"看起来那个顺序"**：`sorted(["北京","上海"])` = `["上海","北京"]`（按码点，上 U+4E0A < 北 U+5317）。断言城市集合用 `set()` 比较，别写字面顺序。
- **同一格里放两个口径 = 必然被读成 bug（2026-09-15 用户反馈）：一个单元格里「颜色+正负号」= 同比本身（本期 vs 去年同月），「箭头」= 同比较上期 ↑/↓** → 社融渲染成 `+21.20% ↓`（同比仍正增长、但增速回落），用户第一反应是"加号配下降箭头，矛盾"。⚠️ **修法不是把箭头改成跟随数值符号** —— 那样箭头退化成纯冗余装饰、还丢掉"增速回落"这层信息；正解是**补口径**：列说明（`.mac-note`）+ 单元格 `title` 写明"同比 = 本期 vs 去年同月；箭头 = 同比较上期"，并加验收断言钉住（`verify_ui` CN-4c/4d：所有同比单元格必须有含"去年同月"的非空 title）。**推广**：任何"两个独立口径共用一格"的展示，要么拆列、要么写标签，不能靠颜色/符号"心照不宣"。
- **缺失值不要拼单位**：`fmtSigned(null) + "% " + arrow` 渲染出 `—%`，看起来像格式化漏洞（10Y 国债的 `yoy` 恒为 `None`——中债接口只有 6 个月窗口、拿不到去年同期基数）。判据：`"—%" not in 容器文本`（`verify_ui` CN-4e）。
- **利率类的"变化"要用「与 6 个月前比的 bp」，不要用同比 %**（2026-09-15 用户反馈后落地）：① 利率是**点位**，百分比变化量纲失真（`4.00% → 4.30%` 是 `+7.5%` 而不是 `+30bp`）；② **10Y 国债源自中债接口、只有 6 个月窗口 → 永远取不到去年同期基数，同比恒 `None` → 页面上就是一格死数据**（`—`）；③ LPR 长期不动 → 同比恒 `0.00%`，看起来像坏数据，"没动"反而没表达出来。落地形态：`_chg_6m_bp`（`chg_bp: True` 的三条利率序列才有，其余序列该键恒 `None`，前端据此切换单位），现值 **0.0bp / +11.44bp / −8.96bp**（改造前分别是 `0.00%` / `+3.65%` / `—`）。
- **同一序列的发布频率会中途变化 —— "按位置回溯"一律禁止，必须按日期/月份定位**：实测 `macro_china_lpr` **2014-2018 是每日报价（249~250 点/年）、2020 起改为每月 20 日（12 点/年）** → `history` 的"最后 120 点"跨 **2019-07 ~ 2026-08 ≈ 6.6 年**，不是 6 个月。所以 `rows[0]` / `rows[-120]` 这类**按位置的"6 个月前"会算出 7 年累计（实测 −131bp）**。正确做法：日频取「月份 ≥ 目标月的第一行」、月频取「键 ≤ 目标月的最后一行」（目标月缺报自动退到最近可比月）。配套：`lpr` 的 `freq` 从 `day` 改成 `month`（history 深度 120→36，同比基准也从"同月末近似"变成"按月键精确匹配"）。
- **`wait_for_selector` 的判据必须覆盖**所有**分组，否则是竞态假红**：`/macro/cn` 分两波加载，原等待条件是 `#cn-econ ≥ 10 项 && #cn-estate ≥ 1 城` —— 而 price(2)+growth(2)+money(3)+labor(2)+estate(2) = **11 项**，**rate 组还在飞就能满足** → `#cn-rate-list` 只剩「社融」一行，利率三行缺失（端点侧实测 `failed=[]`、`bp=[0,11.44,-8.96]`，纯前端等待竞态）。修法：把 `#cn-rate-list .mac-var ≥ 4` 也写进等待条件；并给外部 API 依赖加**重载一次**的容错（不放松判据）。
- **`AbortError` 不应报成 `console.error`（有意重载会误伤 console-error 断言）**：`fetch` 被 `AbortController` 取消（超时或页面跳转/重载）时抛 `AbortError`；验收脚本的 `console error = 0` 断言只统计 `type === "error"`，于是**"重载一次再测"这个容错动作本身**会把页面判成有缺陷。修法：分级日志 —— `AbortError → console.warn`（且页面已用「数据暂缺」把失败可见化）、其余 `console.error`（`macro_cn.js::logFetchError`）。
- **断言里的"可选行"不要写死总数**：`#cn-rate-list` 的第 5 行「信用利差」来自另一个端点（`/api/cn/quotes`），它失败时该行**按设计不出现** → `len == 4` 会假红、`len >= 4` 才是正确判据（下限锁"利率三行 + 社融必须到"，上限交给可选行）。
- **并行会话会污染共享验收脚本的"提交边界"**：`verify_ui.py` / `chart-crosshair.js` 是多任务共用的文件。实测：本任务提交时它们的未提交改动分别是 **315 行 / 91 行**（另一个 crosshair-snap 会话在飞），`git add <文件>` 会把**别人的半成品**一起提交。**判据**：提交前 `git status --short` + `git diff --stat -- <文件>`，确认每个待提交文件的 diff **全部属于自己**；不属于的就**不要提交**（本次只提交自己的 4 个文件），并把这个事实写进 journal。
- **`destroy()` + `new Chart()` 会清空一切实例级自定义状态 —— 包括插件的吸附态（"重建最省事"是假优化）**：`/macro/cn` 的 `renderChart()` 原先每次调用都重建实例，而 `renderAll()` 被 6 个分组 + quotes + history 各调一次 → **实测加载期重建 8 次**（给实例打标记 + 120ms 轮询计数取证）。每次重建都把 `$crossY`/`$crossSource` 归零 → 悬停虚线**消失、不跟随**（用户原话："有吸附了，但是虚线没跟上去"）。修法：**同模式原地换数据**（`chart.data.labels/datasets = …; chart.update("none")`，保留吸附态），只有**选项变化**（单变量 ↔ 全部对比，图例显隐不同）才重建 → 重建 **8 → 1**；配套护栏：`window.__cnRecreate <= 1`（CN-12）+ 「悬停态跨一次程序化 refresh 存活，且实例 tag 不变」（CN-13）。**推广**：缩放状态、插件挂钩、选中态都属于实例级状态，凡是"重建一下最省事"的写法都要先问"哪些状态会丢"。
- **`resize` 后残留的吸附 y 是"陈旧像素"**：容器/视口尺寸变化 → scale 重算 → 旧的 `$crossY` 指向错误高度（线停在原处，直到下一次 mousemove）。修法：`options.onResize = (chart) => { chart.$crossY = null; chart.$crossSource = null; }` —— 宁可线消失，也不要画在错位置。
- **原地换数据后必须把"吸附态"重新对齐，否则正是"虚线不跟着点走"**（2026-09-16 用户反馈）：`chart.data.datasets = …; chart.update("none")` 之后元素坐标**已重算**，若沿用旧 `$crossY` → **圆点移到新位置、虚线冻在旧像素高度**（实测症状就是用户说的"虚线要跟着吸附在线上的那个点走"）。修法：`update()` 后按 `$crossSource` 取新 `meta.data[dataIdx].y` 回写 `$crossY`（取不到再清态）。⚠️ 这与"重建会清空吸附态"是**一对**：清空 → 线消失；沿用旧值 → 线冻住；只有**重新对齐**才对。不变量：`$crossY === meta.data[dataIdx].y`（`verify_ui` CN-14）。
- **像素取证的门槛必须低于被测线的"抗锯齿后 alpha"，否则得到假阴性**：1px 虚线画在**小数 y**（实测 `$crossY=368.0855`）上会被摊到两行，每行 `0.65 × 覆盖率` → 一行为 `97`、另一行为 `69`。用 `alpha > 100` 判定"线有没有画"会**把真实存在的线判成不存在**（我据此白查了一轮：`/macro` 那行恰好 114 越过门槛、CN 那行 97 被滤掉，看起来"一个页面有一条没有"）。**纪律**：先按目标色/覆盖率算一遍期望 alpha，再定门槛；或同时跑多档门槛（10/30/100）看变化。另：行内像素计数**必须排除网格线**（同行的网格线是 100% 覆盖的浅灰），否则"虚线覆盖率 ≈ 50%"会被网格线抬到 100% 而看不出问题。
- **偶数点的 category 轴：鼠标放在绘图区正中央 = 相邻两点 x 的"精确中点"（恒等，不是巧合）**：`x_i = left + (i+0.5)·step` 且 `W = N·step` → 中心恰好等于两个中心点的中点。于是"取最近点"在此处**必然并列**；而插件拿到的是浏览器给的**整数** `event.clientX`（→ px=668），验收探针用的是 rect 推算的**浮点** px（667.803）→ 各选一侧 → 期望 y 差 **25px**。⚠️ 这**不是功能缺陷**（实测 `$crossY === 圆点 y`，横线与圆点完全重合），而是**断言口径**问题。修法二选一：探针复刻浏览器取整（`Math.round(mx) - rect.left`）或把 `frac_x` 移开 0.5。**判据**：任何"最近点/吸附"断言在 `frac_x = 0.5` 上失败时，先算 `mid == px` 是否成立，再怀疑实现。
- **"提交范围"与"抓取频率"必须解耦：危险的是提交，不是抓取**：原诉求是"改 cron 时间避开开发时段"，但**时间不是根因** —— 数据 24 小时流动（A 股 09:30–15:00 / 美股 21:30–04:00 北京时间），不存在安静时段。把 add 收窄到数据路径后，外部高频抓取保持 `*/5` 也不再有半成品风险 → 不必为了安全牺牲数据新鲜度。反之，**任何"留一条全量兜底链"的方案都必然在某个"写了一半"的瞬间撞上**（事件触发才是正解）。

## 模块 web/（悬停横线吸附 crosshair snap，2026-09-15）

- **节流对象必须与「最终画出去的量」一致，否则重绘要么空转要么漏**：`chart-crosshair.js` 的 `afterEvent` 原节流是 `Math.abs(e.y - $crossY) < 1`（对象 = 鼠标 y）。横线改为**吸附到数据线**后：单数据集图（`/macro/cn`）里鼠标纵移而吸附 y 不变 → 绑 `e.y` 会**每帧 `chart.draw()` 空转**；多数据集图反而相反（目标换线而鼠标 y 可能没动 → 漏重绘）。修法：节流比较**吸附后的 y**（`targetY`），阈值同时由 1px 收到 **0.5px**（吸附点是离散像素值，1px 会吞掉真实的换点）。判据：改这种"跟随鼠标的量"时先问"最终画的是哪个量"，节流必须挂在它上面；早退分支**不要**顺手写派生状态（`$crossSource`），否则会出现 source 与已绘制的线不一致的隐蔽错位。
- **「同 x 不同 Y → 画布指纹必不同」这类断言，本质是在断言"跟手"；需求一旦改成"吸附"，它测的语义就反了**：`verify_ui.py` 的 CS-2（首页）与 XC-5（宏观页）都是这么写的（原语义正确：横线 = 鼠标 y 的镜像）。吸附后同 x 纵移会吸在**同一条线**上 → CS-2 **必红**（实测 y=0.3/0.7 两点都吸到 `297.63`）。⚠️ 更危险的是 **XC-5 实测仍绿**（两点恰好吸到不同的线）—— 绿的原因从"跟手"变成"**换了目标线**"，属**语义漂移**：绿 ≠ 测的是吸附。**处置**：一律按"补强"拆成 a/b 两条新语义断言（不同 x → 随数据走；同 x 同一目标线 → 吸住），**不删除、不放松**，并在 journal 里显式记"绿但语义已变"，否则后人复跑看到绿就以为这条已覆盖。
- **"最近点"必须确定性取索引；验收探针要与被测实现**同口径**（Chart.js 的事件坐标是取整后的整数）**：(a) 相邻采样点间距 ≈3.9px（968÷250），鼠标落在两采点正中即产生**并列**（实测 `colCount` 出现过 4）→ 实现不得"收集所有等距点"，必须 `tie → 取较小索引`，否则同一位置相邻两帧吸到不同索引、横线抖动。(b) 探针若自己重算"应该吸哪一点"，**必须复刻上游的坐标归一化**：Chart.js `getRelativePosition` 对事件坐标做 `Math.round`，探针不取整就会在并列处算出**不同索引**（实测 `mouse.x=667.803` → 探针 idx=32、插件 idx=33，差 25px = 一个采样点距）→ 表现为"实现错了"的**假红**。判据：探针与实现出现 1 个索引 / 1 像素级分歧时，先对齐**坐标口径**再怀疑实现。

## 模块 web/（侧栏市场状态两行两市场，2026-09-16）

- **跨市场"是否开盘"必须用各市场自己的时区判，代码里不得出现北京时间魔数**：原实现只判「今天是不是工作日」（`wdIdx>=1 && wdIdx<=5`，取出的 hh/mm 只用于显示、从不参与判定）⇒ 工作日任意时刻（20:40、凌晨 3:00）都亮绿点「市场已开盘」。改成"换算成北京时间再比 21:30 / 04:00"是**更坏的写法**：11 月夏令时结束后美东 09:30 = 北京 **22:30**，会**静默错一小时**（不报错、console 干净、肉眼看不出来）。正解：`Intl.DateTimeFormat(..., {timeZone:'Asia/Shanghai'|'America/New_York'})` 各取本地 `weekday/hour/minute`，DST 交给 IANA 数据。**验收必须带两个 12 月用例**（北京 21:30 → 美东 08:30 = 未开盘；北京 22:30 → 美东 09:30 = 交易中），并做一次**反向验证**（故意把时区写成定值 `Etc/GMT+4`，确认这两条变红）—— 否则"护栏"只是摆设（本次实测：注入定值时 MS-3 的 12 月用例变红、9 月用例仍绿，证明它精确针对 DST）。
- **"逐格期望值"的覆盖表必须用运行时独立核算，不能手算/照抄方案表格**：本任务的 plan §4.2 与 Step 6 表格有 **2 格与它自己的 §4.1 判定规则冲突** —— ①「北京 12:00」对应美东 **00:00**（local weekday 还是周三）⇒ 按 `t < 09:30` 是**未开盘**，plan 写「已收盘」；②注入例 `2026-09-19T04:00Z` 对应美东 09-19 **00:00 是周六** ⇒ **休市**，plan Step 6 写「已收盘」。手算/照抄会把错误期望写进断言，造成**假红**（去改本来正确的实现）或掩盖真错。做法：先用 `zoneinfo` 写临时探针把整张表算一遍，逐格与方案对账，冲突项按**规范性规则**（§4.1）修正并写进代码注释 + journal。⚠️ 判据：任何"表格式期望值"在落进断言前，先问"这格是人算的还是跑出来的"。
- **"同源断言"（期望值由页面内同一函数产出）会引入两种新假绿，必须显式堵**：把写死文案的断言改成 `DOM 文本 == window.__xxx()` 后，实测红跑出现两处**恒真** —— ① `None == None`：取不到元素时 `openClass` 与 `exp_open` **同为 `None`**，相等 → PASS（本次 `MS-4a` 红跑实测变绿）；② **空集 vs 空集**：`_ms_labels()` 会过滤掉取不到的用例，两侧都退化成 `{}` → `len(0)==len(0)` 且无差异 → PASS（本次 `MS-5a` 红跑实测变绿）。修法：断言里出现可选值时**必须显式要求类型**（`isinstance(x, bool)`、`x is True/False`）并**钉死条数**（`len(lab2) == len(MS_CASES)`，即"覆盖度断言"）。**推广**：任何"两侧都来自同一个可能失败的取数"的断言，都要额外断一条"值不是 None / 集合非空"。
- **侧栏文案：加字危险、加行安全（`nowrap` + 父级 flex 剩余宽度）**：`.ms-row` 是 `white-space: nowrap` ⇒ 文本永不换行、也不截断，超宽时**溢出到 `.market-status` 之外**（其 `overflow: visible`）；又因 `#sidebar{overflow-y:auto}` 使 `overflow-x` 计算值为 `auto` ⇒ 长文案会让侧栏冒出**横向滚动条**。宽度预算 = `207 − 28(主题按钮 flex-shrink:0) − 10(gap)` = **169px**。而 `.market-status` 是 `flex-direction: column` ⇒ **新增一行只增高**（实测 32→50，footer 45→63），每行只需 ~73px（余 96px）。**判据**：往这种容器里加信息时优先"加行"，加字必须先算父级 flex 剩余空间。配套护栏：`footer.h == 63` / `.market-status.h == 50` / 每行 `scrollWidth ≤ clientWidth + 0.5`（`MS-6a~6d`，1920/1280/**769** 三档 —— 769 是抽屉断点 `@media (max-width:768px)` 的下沿内联态，必采）。
- **"计划承诺但从未落地"的语义要先 grep 兑现情况**：`tasks/2026-09-11-frontend-bento-redesign/plan.md:297` 写明按 **`is_market_holiday`** 实现市场状态，但 `grep -r is_market_holiday web/` **零命中** —— 当时承诺的交易日语义从未写进代码，这才是"休市只在周末出现"的根因（不是文案偏好问题）。**判据**：改这类行为前先 `grep` 方案里点名的函数名/常量名，区分"实现漂移"与"需求变更"，否则会误判成需要新增功能。
- **第三方时区数据缺失要留占位而不是崩**：`Intl` 在缺少 ICU tz 数据时 `formatToParts` 会抛异常 —— 保留 `try/catch`，异常时**不清空**已有占位文案（`A股 —` / `北京时间 —`）直接返回。⚠️ 这会**故意**让"同源断言"变红（DOM 有占位、hook 返回 null），属预期：此断言测的是"ICU 正常"这一前提。
- **零风险基线 A/B：`git archive HEAD` 到 %TEMP% + venv 用目录联接（junction），绝不回退真实工作区**：本仓库外部 Hermes cron 每 5 分钟 `git add -A`，把工作区就地回退成"基线版本"去跑对照实验，等于**主动制造"写了一半的工作区"**（会被 cron 提交成一次假基线提交）。做法：`git archive HEAD | tar -x -C %TEMP%/baseline`（得到 HEAD 全量 tracked 文件，含 HEAD 版验收脚本）→ 补 `cp -r context/ data/` 保证与真实运行等价 → `New-Item -ItemType Junction` 把真实 `venv` 联进去 → 用真实 `venv/Scripts/python.exe` 跑副本里的脚本（脚本内 `ROOT = Path(__file__).parents[2]` 自动指向副本，`cwd` 也在副本）。⚠️ **回收时必须先非递归删除联接**（`[System.IO.Directory]::Delete($j, $false)`），**绝不能用 `rm -rf`** —— Git Bash/MSYS 会把目录联接当普通目录递归进去，**删掉真实 venv 的内容**。删完再核实 `venv/Scripts/python.exe -V` 与 `import playwright, fastapi, pytest` 正常。
- **12 条失败 vs 15 条失败的"超集"判据**：把"本轮失败的断言清单"与"基线失败的断言清单"做**集合比较**（本次：本轮 12 条 ⊂ 基线 15 条 ⇒ 新增失败 **0 条**）。这比逐条解释"这个失败与我无关"强得多，且能顺带发现**基线更差**的情况（本次基线多出 `MX-6b/MX-9b/MX-10`，根因是 Yahoo 429 抖动导致 `/api/macro` 返回空 `trend.dates`，属外部数据源波动）。判据：外部数据源相关的断言组出现零星红时，先 `curl` 打一次端点看 payload 是不是 `null`/空数组，再用基线 A/B 定责。

## 模块 web/（宏观页四态 + 因子 chip + Score 语义色，2026-09-16）

- **骨架屏（shimmer）只允许用于 loading，「取不到数」必须落到 `.mac-empty`**：把"缺失/失败"做成永久动画 = **用动画掩盖故障**（比现状更糟：现状至少是"确定的无数据"）。判据：取数一旦结算（成功或失败）就必须把骨架**撤掉**（`document.querySelectorAll('.skeleton').length === 0`），换成真实值或既有 `—` / `.mac-empty`。⚠️ 配套的**更硬**一条：**超时必须能从 loading 切到 failed**，否则上游挂掉（本项目 G8 常态 403）时页面会永远停在骨架屏。做法：把客户端超时做成**可注入钩子** `window.__macroTimeoutMs`（生产不设置 → 15000ms），验收才能在 2s 内真跑一遍 `AbortController` 分支；否则要么等 15s、要么只测到"永不结算"的假路径（本次两个场景都测了：悬挂 → 骨架在场；越过超时 → 骨架清零 + 失败态）。
- **给 grid 容器加"骨架包裹层"时必须先问：这个包裹层自己是不是一个 grid item**：`#mac-econ` 是 `grid-template-columns: repeat(4, …)`，把 4 条骨架塞进一个 wrapper `<div>` 后，该 wrapper **只占第 1 个列位**，再被内部 4 列切成 4 份 → 渲染成"4 个小方块缩在左上角"，与"四张整宽卡"的真实内容完全不符（截图实测确认）。修法：`#mac-econ [data-skel] { grid-column: 1 / -1; … }`。**判据**：任何"占位层"落进 grid/flex 容器时，先确认它会被当成一个 item 还是铺满；骨架的目的是"尺寸贴近真实内容、避免加载完成时行高突变（CLS）"，布局不符就等于没做到。
- **多个取数源各自结算时，"渲染后补挂的状态类"会被对方的 `renderAll()` 抹掉**：`/macro` 的 `/api/macro` 与 `/api/econ` 是两个独立 promise，各自 `.then/.catch` 都调 `renderAll()`，而 renderAll **重建容器 `innerHTML`** ⇒ 先结算的一方刚给 `.mac-empty` 加的 `is-failed` 被后结算的一方清掉（实测 `factorsFailed=False` 而 `econFailed=True`）。修法：把"失败态修饰"收进 `renderAll()` 内部、**在所有 render 之后**按 `failMacro/failEcon` 标志位统一补挂（幂等），**不要**散落在各个 catch 里。**推广**：任何"渲染完再补的类/属性"都要能扛住"下一次渲染"，否则它只在最后一次渲染里成立。
- **统计"修饰类数量"时必须排除模板里常驻的那一份**：失败条自身的 `<p class="mac-empty is-failed">` 是**模板静态常驻**（靠 `.hidden` 控制显隐，它的类名不随状态变化）⇒ `document.querySelectorAll('.mac-empty.is-failed').length` 在**成功态也 ≥ 1** → "成功态不残留 is-failed"这条断言**永远假红**（实测踩到，`actual=(False, 1)`）。修法：`.filter(n => !n.closest('#mac-fail-bar'))` 后再计数。判据：凡按类名计数，先自问"模板里有没有一份与状态无关的常驻同款元素"。
- **`.hidden{display:none}` 的特异性只有 (0,1,0) —— 给同一元素写 `#id{display:flex}` 会把它顶掉**：失败条要"隐藏时 display:none、显示时 flex"，若直接写 `#mac-fail-bar { display:flex }`（id 特异性 (1,0,0)）会**盖掉 `.hidden`**，失败条常显。修法：显示语义写在 `#mac-fail-bar:not(.hidden) { display: flex; … }`，让"显示"与"隐藏"同源、不互相打架。**判据**：任何"用 `.hidden` 切换显隐"的元素，新增样式时都不要在其**自身**选择器上写 `display`。
- **"颜色必须由 A 字段推导"这类约束，必须用"A 与 B 冲突"的输入来证伪**：N4 要求 `#regime-score` 的颜色由服务端 `level` 决定。若只喂"正常一致"的 mock（`risk_on` + `score100=68.8`），那么**错误实现"`score100 > 50` 就染绿"也会全绿** —— 因为真实数据里两者恰好同向（实测 `score100=68.8` 配 `Risk-On`）。正解：断言里加两组**矛盾输入** —— `level=risk_off + score100=80`（>50 必须**红**）与 `level=risk_on + score100=35`（<50 必须**绿**）。⚠️ 背景：`score100 = (normalized+1)/2*100` 是 **0~100、中性 50**（`web/app.py`），**不是 ±2 的分值区间**（±2 是四个因子的 `impact`）—— 把它当"正负分"上色会让 50 也偏绿、并与 `#regime-level` 文案可能相反。**推广**：任何"两字段应当同源"的断言，都要构造**两字段冲突**的输入，验证实现到底听谁的。
- **新增断言组前先确认标签前缀不与既有组撞名**：plan 让用 `N-*`，但 `N-*` 已被首页「最新资讯」断言占用（`N-1` / `N-7` / `N-11` / `N-12a`…）→ 改名 **`NA-*`**（同 `XC-*` 的先例，`verify_ui.py` 里有注释）。撞名会让失败报告无法定位是哪一处红。判据：加组前 `grep -oE '^  (PASS|FAIL)  [A-Z]+-' 报告/日志 | sort -u` 看一眼已占用的前缀。
- **红跑要"报红"而不是"崩溃"，并且要防"真空绿"**：把新断言跑在**改动前**的基线上时，基线没有新钩子/新元素 → 两类事故都会出现：① **崩溃**：`len(a2["blocks"])` 在 `blocks=None` 时直接 `TypeError`，整组中断，后面 20+ 条断言根本没跑（实测表现是"只有 4 条失败"，极具误导性）→ 所有下标/长度访问先判空、点按钮用"找不到就返回 false"的 JS。② **真空绿**：`all([]) == True`（`blocks=None` 时"所有块都 ok"恒真）、"无破图"（页面上没有图片时恒真）、"骨架已撤掉"（本来就没有骨架时恒真）→ 每条断言都要带上"前置状态确实存在"的合取项（`a1['skelVisible'] >= 8 and a2['skeletons'] == 0`、`bool(d['imgSrc']) and imgBroken == 0`）。判据：看红跑里"仍 PASS"的那几条 —— **它们要么是真的不变量护栏（基线也该绿），要么就是漏网**，逐条归类（本次 4 条 PASS 全部是不变量：`#mac-factors` 留白上限 + `/macro/cn` 零影响 ×3）。

## 模块 web/（宏观页因子「影响资产」的配对歧义，2026-09-17 用户反馈）

- **一个格子里放 ≥2 组「对象 + 状态」时，配对必须不可拆散：对象在前、状态在后、同组小间距 / 组间大间距**：`#macro-factors` 的「影响资产」格里，**一个因子会同时出现两个方向** —— 实测「利率 ↓偏空 → 黄金受益 · 长久期承压」。原实现按"每句出一个 badge、后面跟 N 个 chip"平铺 ⇒ 渲染成 `受益 🪙黄金 承压 长久期`，**中间的 chip 被两个 badge 夹心** ⇒ 用户直接读成"黄金又受益又承压"（2026-09-17 用户原话：「这什么意思，怎么又受益又承压的」）。⚠️ **这不是数据错、也不是文案错，是排版的配对歧义** —— 语义上两个 badge 本来属于两个**不同资产**。修法：`<chip><badge>` 同组 `.fr-grp`，且组间 `gap`(12px) > 组内 `gap`(5px)。**判据**：只要一格里有 ≥2 组"对象+状态"，就必须能靠**间距/分组**（或拆列、或写标签）判断谁配谁；靠元素顺序"心照不宣"必然被读成矛盾（与 2026-09-15「同一格放两个口径」同源，那条的教训也是"要么拆列、要么写标签"）。
- **"无方向"的分支不要套用"方向 Badge"模板**：`impact = 0` 时文案本身是「中性（不构成方向）」，若仍按 pos/neg 的模板出 badge，会渲染成 `中性` badge + `中性不构成方向` chip ⇒ **同一个词写两遍**，读起来像 bug（实测 4 行全中）。修法：flat 分支**不出 badge**、直接显示原文；但**仍要保留 chip**，否则会破坏"每行资产 chip ≥1"的既有验收。
- **"遍历组内关系"的断言必须同时断"组确实存在"**：本次新增的两条不变量是 `chipsOutsideGrp == 0`（每个 chip 都在 `.fr-grp` 内）与 `badgeNotAfterChip == 0`（组内 badge 在 chip **之后**）。后者是 `querySelectorAll('.fr-grp')` 上的**遍历**——改动前页面上一个 `.fr-grp` 都没有 ⇒ 空集 ⇒ **真空变绿**（实测踩到）。修法：断言里加 `grpCount >= rowCount` 作为前置。**判据**：任何"对集合的每个元素都成立"的断言，都要额外断"集合非空/规模达标"。

## 模块 web/（因子「影响资产」的符号口径，2026-09-17）

- **`inverse=True` 的维度，`impact` 的符号是"变量下行"而不是"变量上行" —— 跨界引用前先读被引用层的 docstring**：`web/app.py:685-695` 的 `_band_score(..., inverse=True)` 写明"数值上行 = 风险偏好下行（美元走强 / 利率上行），符号取反" ⇒ **美元**与**利率**两维：`impact > 0` = 该变量**下行**；`商品` 没有 inverse（`impact > 0` = 油价上行）。前端 `FACTOR_ASSETS` 却按"变量上行 = pos"写 ⇒ **这两支整体反了**，实测表现为「利率 ↓偏空（= 收益率上行）」那行写「**黄金 受益**」，而同一张截图里黄金就是 **−0.36%**、当天现货金 −0.69%（2026-09-17 FOMC 加息 25bp、10Y 破 5% 创 19 年新高、美元站上 100）。⚠️ **我第一遍解释时还把它讲反了**（说成"利率下行"）—— 教训：**解释一个符号之前，先读定义它的那一层的注释**，别按领域直觉推断。
- **判据（不要拿实现自证）**：断言必须**只读页面渲染出的"资产 + 方向"配对**（`.fr-grp` 的成对文本），**不读** `macro.js` 的映射表 —— 拿被映射的那张表去验自己等于没测。做法：用两个**方向相反**的 mock 夹具（美元 / 利率 的 `impact` 取 ±1），逐格对打"该行必须 / 不得出现「资产 方向」"（`NA-11`：红跑 9 条 → 修后 0 条）。**推广**：任何"数据表 × 上层语义"的映射，都要有一条**跨层一致性**断言，且期望值来自**需求口径**。
- **对调 pos/neg 常常不够，因为原文案可能"混向"**：本次 `美元` 两支**整句对调**即可（两句原文各自自洽）；而 `利率` 的旧 `neg` 句是**混向**的 —— "黄金 受益"按"利率上行"该是承压、"长久期 承压"按上行却是对的 ⇒ 必须**新写**下行那支 = 上行那支的镜像。**判据**：改这类映射时逐句问"这句描述的是变量上行还是下行"，不能只看支名整体搬运。

## 通用（验收判读：中途崩溃会被误读成"几乎全绿"，2026-09-17）

- **只数 PASS/FAIL 行判读验收结果 = 会被"中途崩溃"骗过去**：在断言组里做了一次变量名覆盖（把 route handler 函数 `ok` 覆盖成 bool），导致该组**末尾整段没跑**（NA-9 双主题截图 2 条从未执行），但因为抛异常前已经打印了几十条 PASS，当时只 `grep -c '^  FAIL'` 看到 **0** ⇒ 误报"47 PASS / 0 FAIL 全绿"。同一 bug 也让**整跑**在末尾崩溃：`N-12`（Firefox 专项）没跑、结尾的 `===== 结果 =====` 汇总也没打印，只留下 11 条早先记录的 FAIL —— 若不看 traceback，会误以为"套件跑完了、只是有 11 条环境红"。**判据**：任何一次验收都必须检查**完成标记**（套件尾部的 `ALL PASSED` / `FAILED: N 条` 汇总行，或探针自定义的 `NA-COMPLETE` 之类），**没有完成标记 = 崩溃 = 结果无效**，不能只数红。做法（本次落地）：① 探针把断言调用包进 `try/except`，崩溃时打印 `★ 断言组崩溃（未跑完）★` + traceback 并返回退出码 2（与"有失败"的 1 区分）；② 判读脚本先 `grep -c 完成标记`，为 0 就直接判无效。
- **调试提示：`Page.wait_for_timeout: 'bool' object is not callable` 这类"不像自己代码"的报错，往往是 route handler 抛错的**延迟表现**：`page.route(pattern, handler)` 的 handler 若不可调用（如被同名变量覆盖、或被 `None`），异常发生在**网络回调**里，Playwright 会在**之后某个 API 调用**处重抛并冠以该 API 的名字（实测就是这样：真正的犯人是我在断言循环里写的 `ok = _has_pair(...)`，报错却指向 `page.wait_for_timeout`）。**排查手法**：先从"报错点的前一个 `page.*` 调用之前有没有重名变量"入手，或直接找同名覆盖（本项目验证脚本里 `check()` 的形参也叫 `expect`，同样别拿来当循环变量）。

## 通用（断言的环境耦合：别把"假设数据一定陈旧/新鲜"写进判据，2026-09-17）

- **同一断言里出现"输出必须非空"与"输出必须等于某空值"两个合取项 = 逻辑不可能**：`verify_ui.py` 的 V-3 原为
  `d["usText"] == expected and (us_as_of is None or d["usText"] != "")`，其中
  `expected = "· 数据截至 <as_of>" if (as_of and date and as_of != date) else ""`
  ⇒ 当 `as_of == date`（数据**新鲜**）时第一个合取项要求"文案为空"、第二个却要求"文案非空" ⇒ **恒红**。
  **铁证**：同一次运行里 `date=cn.as_of=us.as_of=2026-09-16`、页面两条标注都为空 —— **V-2 绿、V-3 红**，
  两者输入与页面输出完全相同 ⇒ 差异只在断言。**判据**：写断言时若两个条件分别约束"同一输出的两种形态"，
  先代入极端值算一遍是否可同时成立。
- **"假设数据一定陈旧"与"假设数据一定新鲜"是同一类环境耦合**：本项目 2026-09-14 已把 V-2 从
  "A股今天一定新鲜 ⇒ 标注必须为空"改成**数据驱动期望值**（代码里有注释留档），但同族的 V-3 漏网，
  于 `as_of` 变新鲜的那天（2026-09-17）翻红。**判据**：凡是把 `as_of` / `date` / "今天" 这类快照字段
  写进期望值的断言，期望值必须**由数据推导**（"标注 == 陈旧与否对应的文案"），不能断言某一个固定形态。
- **想防"空期望 ⇒ 真空通过"，要用"输入前置"而不是"输出必须非空"**：V-3 的修法是把
  "as_of 非 None ⇒ 文案非空"改成前置 `check(bool(cur), "V-3a /api/latest 提供 date（陈旧判定基准）")` ——
  基准缺失时明确报红，而不再用一个与主判据打架的合取项。**判据**：真空通过是"输入不足"问题，
  治理点在输入，不在输出。
- **改判据必须自证"没放松"，用双方向夹具**：修完 V-3 后用 mock 造出"页面显示陈旧标注、而 API 说新鲜"
  的矛盾态 → **必须红**（证明还能抓不一致）；再把期望值来源同源换成同一份 mock → **必须绿**
  （证明"非空标注"分支真的被验到）。两个方向都跑过，才能说"只是去掉了矛盾、没有降低要求"。
