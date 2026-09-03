# 易错点

> 记录反复出现的问题和坑。Agent 修改相关模块前必须先读。

## 通用

- **edit 工具多行替换容易误吞相邻代码**：Hy3 在多期实施中反复遇到——ASCII `+` 被当字面量、长 MATCH 块缺 `»` 导致误删相邻函数。多行编辑优先用 `write_file` 整体重写，避免 patch 锚点漂移。
- **验证期模拟数据后必须恢复**：改 `last_values.json` 模拟异动后运行入口，若取数成功缓存会被真实值覆盖（正常）；若取数失败模拟值会残留——验证前先备份、验证后恢复。
- **monkeypatch 路径常量要打在使用方模块**：`CHARTS_DIR`/`ALERTS_DIR`/`CONTEXT_DIR` 等在导入时绑定，测试必须 `monkeypatch.setattr(使用方模块, "XXX_DIR", tmp_path)`，打在定义方模块不生效。

## 模块 src/（一期：数据获取）

- **Yahoo Finance 对本机 IP 限流（HTTP 429 / ConnectionResetError 10054）**：连续取数会触发 IP 级限流，query1 返回 429，query2 返回 403。脚本按设计容错（单源失败不影响整体，退出码恒 0），但报告会缺数据。应对：等待限流解除、换网络出口、或在脚本前加代理。
- **yfinance 一次打多个子请求更易触发 429**：改为单请求直连 Yahoo chart REST（`query1.finance.yahoo.com/v8/finance/chart`），复用 Session + 退避，显著降低限流概率。
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
- **真实数据落地后回退自然失效**：不改生产端；`daily_report.py` 覆盖写同名 context，09-03 真实数据落地后 `_load_latest_context` 取最新文件即命中板块数据，回退不再触发，无需清理逻辑。
