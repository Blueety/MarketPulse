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
## 环境相关

- **FRED 公开 API 无 MOVE 序列**：勿再走 FRED 作为 MOVE 数据源。真实数据在 Yahoo `^MOVE`（标名错误但数值真实，与 Investing.com 一致）。
- **Hermes weixin 出站不可靠**：发送报告成功但对方收不到，用 QQBot 作为推送通道。

## 历史教训

| 日期 | 问题 | 根因 | 修复方式 |
|---|---|---|---|
| 2026-08-29 | FRED 无 MOVE 序列 | FRED 的 MOVE 指数未对公开 API 开放 | MOVE 迁至 Yahoo `^MOVE`，勿回退 |
| 2026-08-29 | yfinance 多请求触发 429 | 一次 history() 打多个子请求 | 改为单请求直连 chart REST |
| 2026-08-29 | 中文路径 `@架构师.md` 传参失败 | omp `@file` 不支持非 ASCII 路径 | 用 ASCII 临时文件中转 |
