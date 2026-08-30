# Agent Instructions — MarketPulse

## Project Map

- `daily_report.py`: 收盘日报编排入口（取数 → 报告 + 趋势图 → 写历史/缓存 → context 上下文）。
- `snapshot_report.py`: 盘中快照独立入口（4 个 Hermes cron：A 股午盘 11:30 / A 股收盘 15:00 / 美股开盘 21:30 / 美股午盘 00:00；按 `--market a-share|us` + `--time open|midday|close|noon` 取市场子集，单板块渲染，仅存盘不推送；裸跑=美股午盘）。
- `scripts/backtest.py`: 独立回测脚本（十三期）：复用生产 `check_breach` 语义回放 `data/history.json` 触发事件，统计每标的告警次数 / 年化频率 / WARN-ALERT 分布 / 1·3·5·10 日平均后效 / 胜率 / 有效触发率；只读历史、仅写 `reports/backtest_report.md`，不联网、零副作用（`--history PATH` 指定只读输入）。
- `requirements.txt`: 依赖清单（requests / matplotlib / pytest）。
- `.env.example`: 环境说明（无需任何 API 密钥）。
- `config.json`: 用户阈值配置（项目根，gitignore 排除；缺失回退内置默认）。
| `reports/`: 报告输出（`YYYY-MM-DD.md` / `snapshots/YYYY-MM-DD-{market}-{time}.md` / `charts/YYYY-MM-DD{-trend,-us-trend,-cn-trend}.png`）。 |
- `data/`: 数据缓存（`last_values.json` 涨跌幅基准；`history.json` 近 90 日历史）。
- `context/`: Hermes 上下文（`YYYY-MM-DD.json`：indices + history_30d + breach + sector_heat + us_sector_heat + search_keywords + correlation（显著相关对 |r|>0.5），gitignore 排除）。
- `src/fetcher.py`: 数据获取层（Yahoo 取数 + SYMBOLS 注册表（8 指数：GSPC/IXIC/SH/SZ/CYB/VIX/VXN/MOVE，含创业板 399006.SZ）+ MARKETS 市场子集 + fetch_all(market) + fetch_sector_heat 概念板块领涨/领跌 Top5 元组（线程限时 10s，失败返回 ([], [])））。
- `src/analyzer.py`: 纯逻辑 + 持久化（分类/涨跌幅/history 读写 + check_breach/alert_threshold + CONTEXT_DIR/build_search_keywords + compute_correlation（指数对 Pearson 相关性，纯 Python 零依赖，输入为收益率））。
- `src/config.py`: 配置加载层（config.json + env 覆盖 + 内置默认，白名单校验，零依赖）。
- `src/alerter.py`: 告警层（告警文件渲染 + alerts.log 去重 + collect_breaches 纯计算 + run_alert_checks 编排）。
| `src/reporter.py`: 报告渲染（日报/快照/趋势图/分市场趋势图 + 相关性分析章节）+ generate_context 上下文 JSON 生成（含 sector_heat / us_sector_heat / correlation 键）。 |
- `tests/`: 单元测试（test_analyzer.py / test_reporter.py / test_alerter.py / test_context.py / test_config.py / test_phase6a.py / test_phase6b.py / test_phase7.py / test_phase8.py / test_backtest.py）。
- `alerts/`: 告警输出（`YYYY-MM-DD-{market}-{time}.md`（盘中快照复合名）/ `YYYY-MM-DD-close.md`（日报）；gitignore 排除）。
- `data/alerts.log`: 当日已告警标记（午盘触发则收盘跳过，gitignore 排除）。
- `docs/`: 项目知识和规则。
- `tasks/`: 任务目录和交接记录。
- `skills/`: 可复用流程。

## Required Reading

- 修改前先读 `docs/architecture.md`。
- 改行为前先读 `docs/commands.md`。
- 复杂任务先读当前 `tasks/` 下的任务文件。

## Commands（基于实际环境；所有命令在 venv 内执行）

- Activate (Windows): `venv/Scripts/activate`
- Install: `venv/Scripts/pip install -r requirements.txt`
- Run: `venv/Scripts/python daily_report.py`
- Test: `venv/Scripts/python -m pytest tests/ -v`
- Freeze: `venv/Scripts/pip freeze`
- Lint / Typecheck / Build: 无（纯 Python 脚本项目，暂未配置）

## Working Rules

- 复杂任务先只读分析，不要直接改。
- 每次制定完计划后，将计划保存到 `tasks/<日期>-<简述>/plan.md`（日期用当天 `YYYY-MM-DD`，简述用简短英文描述，如 `2026-08-29-marketpulse/plan.md`）。
  - 计划应包含：目标、涉及文件、实施步骤、验证命令。
- 保持 diff 最小，不重构无关代码。
- 不引入新依赖，除非先说明理由并等待确认。
- 不修改 `.env`、生产配置、生成文件。
- 需求不清楚时先问，不要猜。
- 每完成一个逻辑步骤后运行验证命令，不接受"应该可以"——必须实际运行验证命令。
- 如有失败，先解释原因再修复，不要绕过问题。
- 验证通过后，运行 `git diff` 检查改动范围。
- 任务完成后，提取可复用的规则（不是泛化建议），追加到 `docs/pitfalls.md` 或 `AGENTS.md`。
- 每次任务完成后，将日志保存到 `tasks/<日期>-<简述>/journal.md`，内容包括：目标、改动文件清单、验证结果、遇到的问题、下次注意什么。这样下次会话接手时能快速了解上下文。

## Done Means

- 验收标准已满足。
- 相关测试/checks 已运行或清楚标注未运行。
- diff 已摘要。
- 风险和后续工作已列出。
