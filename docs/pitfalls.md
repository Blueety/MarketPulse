# 易错点

> 记录反复出现的问题和坑。Agent 修改相关模块前必须先读。

## 通用

- （暂无）

### 模块 src/（二期新增）
- 修改 `src/analyzer.py` 的路径常量（CHARTS_DIR / SNAPSHOTS_DIR / HISTORY_FILE）时，注意 `src/reporter.py` 与入口脚本是**导入时绑定**：`reporter.py` 的 `CHARTS_DIR` 是 `from .analyzer import CHARTS_DIR` 的模块级引用，测试里 `monkeypatch.setattr(an, "CHARTS_DIR", ...)` 不会影响 reporter——必须 `monkeypatch.setattr(rep, "CHARTS_DIR", ...)` 才生效。
- `render_trend_chart` 会**排除当日记录**（同日重复运行不重绘当日点）且需 ≥2 条历史才绘图：**首次运行（history 只有 1 条）不产生趋势图是设计行为**，不是 bug；验证趋势图必须预先积累 ≥2 条历史。
- `append_history` 按 date 键覆盖当日记录——同日重复运行 `daily_report.py` 不会产生重复条目；但若手动改写 `data/history.json` 验证后需恢复，避免真实数据被临时播种数据污染。

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
