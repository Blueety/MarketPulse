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

## 环境相关

- **FRED 公开 API 无 MOVE 序列**：勿再走 FRED 作为 MOVE 数据源。真实数据在 Yahoo `^MOVE`（标名错误但数值真实，与 Investing.com 一致）。
- **Hermes weixin 出站不可靠**：发送报告成功但对方收不到，用 QQBot 作为推送通道。

## 历史教训

| 日期 | 问题 | 根因 | 修复方式 |
|---|---|---|---|
| 2026-08-29 | FRED 无 MOVE 序列 | FRED 的 MOVE 指数未对公开 API 开放 | MOVE 迁至 Yahoo `^MOVE`，勿回退 |
| 2026-08-29 | yfinance 多请求触发 429 | 一次 history() 打多个子请求 | 改为单请求直连 chart REST |
| 2026-08-29 | 中文路径 `@架构师.md` 传参失败 | omp `@file` 不支持非 ASCII 路径 | 用 ASCII 临时文件中转 |
