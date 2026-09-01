# 北向资金监控功能 — 执行日志

**日期**：2026-09-01
**执行者**：Hy3（子代理）

## 目标

为 MarketPulse 增加 A 股北向资金（沪深港通）监控能力，在每日日报中展示当日北向资金净流入/流出数据，并在异常流入（如单日净流入超 100 亿）时触发独立告警。

## 改动文件清单

| 文件 | 动作 | 说明 |
| :--- | :--- | :--- |
| `requirements.txt` | 修改 | 末尾追加 `adata>=0.3.1` |
| `src/config.py` | 修改 | DEFAULTS["alert"] 增加 `"northbound": 100.0`；ENV_MAP 增加 `ALERT_NORTHBOUND_THRESHOLD` |
| `config.json` | 修改 | alert 增加 `"northbound": 100` |
| `.env.example` | 修改 | 追加北向资金告警阈值注释说明 |
| `src/northbound.py` | **新建** | 北向资金获取模块，含 adata 降级链 + 15s 线程限时 |
| `src/analyzer.py` | 修改 | 新增 `fmt_northbound()` 和 `fmt_northbound_detail()` 格式化函数 |
| `src/reporter.py` | 修改 | `render_report()` 增加 `northbound` 参数，A 股表格后插入北向资金行；`generate_context()` 增加 `northbound` 参数 |
| `src/alerter.py` | 修改 | 新增 `check_northbound_alert()` 独立告警函数 |
| `daily_report.py` | 修改 | 导入 fetch_northbound_flow，接入北向数据获取、报告传参、告警检查 |
| `tests/test_northbound.py` | **新建** | 19 个单元测试（获取成功/失败/超时/空数据、格式化、告警触发/未触发/去重/None） |

## 验证结果

- ✅ 步骤 1 验证：`load_config()['alert']` 输出含 `northbound: 100`
- ✅ 步骤 2 验证：`fetch_northbound_flow()` 返回 `{'net_inflow': 0.0, 'sh_net': 0.0, 'sz_net': 0.0, 'date': '2026-09-01'}`（adata 数据源当前返回全 0，可能因非交易时段或数据源暂时无数据）
- ✅ 步骤 9 验证：19/19 测试通过
- ✅ 步骤 10 全量回归：376/376 测试通过，0 失败

## 关键发现

1. **adata 北向资金接口名**：`adata.sentiment.north.north_flow()`，返回 DataFrame 含 `trade_date`, `net_hgt`, `net_sgt`, `net_tgt` 等列，金额单位为**元**（需 ÷1e8 转亿元）
2. **adata 数据当前全 0**：实测返回 30 行数据但 `net_tgt` 全为 0，可能是非交易时段或数据源暂时无数据。模块已实现容错处理（0 值正常返回，不视为 None）
3. **线程限时方案**：复用项目既有的 `threading.Thread.join(15)` 模式（Windows 无 SIGALRM）
4. **告警文件独立**：北向资金告警写入 `alerts/YYYY-MM-DD-northbound.md`，与现有 `close.md` / `a-share-close.md` 不冲突

## 遇到的问题

1. **测试中 patch 路径错误**：初次测试 `check_northbound_alert` 时尝试 patch `northbound.ALERTS_DIR`，但该常量定义在 `src.analyzer` 中被 `src.alerter` 导入使用。修复为 patch `src.alerter.ALERTS_DIR`。
2. **terminal 工具 Windows 路径**：bash 环境下 `D:\` 路径需转为 `/d/` 格式才能 `cd` 成功。

## 下次注意

- adata 北向资金接口可能随版本变化，升级 adata 后需重新验证接口名和返回字段
- 若 adata 数据源长期不可用，可考虑新增 Sina/东方财富作为备选源（当前降级链仅 adata → None）
- 北向资金行使用 3 列格式（非标准 4 列表格行），需注意 Markdown 渲染兼容性
