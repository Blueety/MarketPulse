# 易错点

> 记录反复出现的问题和坑。Agent 修改相关模块前必须先读。

## 通用

- （暂无）

## 模块: src/

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
