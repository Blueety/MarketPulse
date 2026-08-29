# 易错点

> 记录反复出现的问题和坑。Agent 修改相关模块前必须先读。

## 通用

- （暂无）

### 模块 src/（三期新增：告警）
- **告警基准必须用开头加载的旧 `last_values`**（决策 G）：收盘入口在 `save_last_values` 之前调用 `run_alert_checks`，若基准误用当日新缓存会导致告警永远不触发/误触发；测试用时序断言锁定。
- **`alerts.log` 只保留当日行**（设计 C）：`_mark_alerted` 原子重写整个文件，旧日行自动清除——跨日运行天然重置去重状态，勿手工追加。
- **路径常量打补丁位置**：`alerter.py` 的 `ALERTS_DIR`/`ALERTS_LOG` 是导入时绑定，测试必须 `monkeypatch.setattr(al, "ALERTS_DIR", ...)`/`setattr(al, "ALERTS_LOG", ...)`；同理 `check_breach` 需 `monkeypatch.setattr(al, "check_breach", ...)`（导入绑定）。
- **阈值 env 变量泄漏**：测试必须 `monkeypatch.delenv("ALERT_THRESHOLD_VIX", raising=False)` 隔离宿主环境，否则 check_breach 边界断言受宿主 env 影响。
- **变化率"严格大于"才触发**：恰好等于阈值不告警（设计 A）；断言用 `pytest.approx` 避免浮点边界误判。
- **验证期模拟告警后必须恢复 `data/last_values.json`**：改缓存模拟 +22% 后运行入口，若取数成功缓存会被当日真实值覆盖（正常）；若取数失败（限流）模拟值会残留——验证前先备份。

### 模块 src/（四期新增：context）
- **`CONTEXT_DIR` 是 reporter 导入时绑定**：`generate_context` 测试必须 `monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path / "context")`；`load_history` 读 `an.HISTORY_FILE`（调用时查模块全局），测试补丁 `an.HISTORY_FILE` 即可。
- **context 原子写**：临时文件 `context/YYYY-MM-DD.json.tmp` + `os.replace`；断言无 `.tmp` 残留。Hermes 读取依赖"要么旧文件要么完整新文件"。
- **`generate_context` 必须在 `append_history` 之后调用**（决策 D）：history_30d 才含当日；`daily_report.py` 的调用点位于 append_history 与 save_last_values 之后、return 0 之前。
- **`search_keywords` 方向语义**（决策 C）：变化率 >=0 用 "surge"、<0 用 "drop"（0 归 surge）；这是 tavily 归因的输入，改词会直接影响 Hermes 搜索命中率，需同步 Hermes Prompt。
- **`breach.indices` 字段契约是 Hermes Prompt 的输入**（决策 B）：字段名 name/current/previous/change_pct/threshold/level 按 PRD 定稿，`level` 大写 WARN/ALERT；改字段必须先改 `_breach_item` 再同步 Hermes Prompt，单测锁定两者。
- **collect_breaches 纯计算无副作用**：不写告警文件、不改 alerts.log；context 的 `breach.triggered` 不受午盘去重影响（午盘已告警的指数，收盘 context 仍标记异动，归因针对市场异动本身）。

## 环境相关

<!-- 记录 Node/Python/系统/编码等环境坑 -->
- **Yahoo Finance 对本机 IP 限流（HTTP 429 "Too Many Requests"）**：2026-08-29 实测，`^VIX`/`^VXN` 通过 yfinance 取数连续 30+ 分钟返回 429，直连 `query1.finance.yahoo.com/v8/finance/chart` curl 同样 429（query2 返回 403），确认是 IP 级限流而非 yfinance 问题。现象：脚本日志反复出现 `获取失败(第1次/第2次): Too Many Requests. Rate limited. Try after a while.`。应对：等待限流解除（数分钟到数小时不等）、换网络出口，或在 yfinance 前加代理；脚本已按设计容错（单源失败不影响整体，退出码恒 0），但报告会缺 VIX/VXN 数据。
- **Yahoo 也会以 `ConnectionResetError(10054, '远程主机强迫关闭了一个现有的连接。')` 拒连**：2026-09-01 实测与 429 同属 IP 级限流表现，现象与应对同上，勿误判为脚本 bug。
- **matplotlib 在 Python 3.14（cp314）有 wheel**：2026-09-01 实测 `matplotlib>=3.7.0` 解析到 3.11.1 正常安装，无需降级或换源。
- **Windows 无 `signal.SIGALRM`**：趋势图 3 秒限时用 daemon 线程 + `join(3)` 实现；超时后线程继续在后台，进程退出即终止，不会拖慢主流程。

## 历史教训

<!-- 从 tasks/ 复盘中提炼的稳定教训 -->
| 日期 | 问题 | 根因 | 修复方式 |
|---|---|---|---|
| 2026-08-29 | FRED 公开 API 无 MOVE 序列（series 不存在），勿再走 FRED | FRED 的 MOVE 指数未对公开 API 开放；真实数据在 Yahoo `^MOVE`（标名错误但数值真实，与 Investing.com 一致） | MOVE 已迁至 Yahoo `^MOVE`（近月约 69-72）；改 MOVE 数据源时勿回退 FRED 方案 |

<!-- 按模块补充易错点 -->
<!--
格式:
### 模块名
- 修改 A 时必须同步 B
- 某测试需要特定环境变量
- 某函数有隐式依赖
-->

## 环境相关

<!-- 记录 Node/Python/系统/编码等环境坑 -->
- **Yahoo Finance 对本机 IP 限流（HTTP 429 "Too Many Requests"）**：2026-08-29 实测，`^VIX`/`^VXN` 通过 yfinance 取数连续 30+ 分钟返回 429，直连 `query1.finance.yahoo.com/v8/finance/chart` curl 同样 429（query2 返回 403），确认是 IP 级限流而非 yfinance 问题。现象：脚本日志反复出现 `获取失败(第1次/第2次): Too Many Requests. Rate limited. Try after a while.`。应对：等待限流解除（数分钟到数小时不等）、换网络出口，或在 yfinance 前加代理；脚本已按设计容错（单源失败不影响整体，退出码恒 0），但报告会缺 VIX/VXN 数据。

## 历史教训

<!-- 从 tasks/ 复盘中提炼的稳定教训 -->
| 日期 | 问题 | 根因 | 修复方式 |
|---|---|---|---|
| 2026-08-29 | FRED 公开 API 无 MOVE 序列（series 不存在），勿再走 FRED | FRED 的 MOVE 指数未对公开 API 开放；真实数据在 Yahoo `^MOVE`（标名错误但数值真实，与 Investing.com 一致） | MOVE 已迁至 Yahoo `^MOVE`（近月约 69-72）；改 MOVE 数据源时勿回退 FRED 方案 |
