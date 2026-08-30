# 十三期回测验证 — 执行日志

## 目标
按架构师计划实施独立回测脚本 `scripts/backtest.py`：复用生产 `check_breach` 语义回放
`data/history.json` 历史触发事件，统计每标的告警次数 / 年化频率 / WARN-ALERT 分布 /
1·3·5·10 日平均后效 / 胜率 / 有效触发率，生成 `reports/backtest_report.md`。只读历史、零副作用。

## 改动文件清单
- `scripts/backtest.py`（新增）：回测入口 + 纯函数（collect_triggers / forward_stats /
  effective_trigger_rate / annualized_frequency / render_report / print_summary / main）。
- `tests/test_backtest.py`（新增，10 条）：触发检测语义 / 缺口断开 / 字段齐全 / 前向收益 /
  胜率 / 有效触发率 / 年化频率 / 数据不足优雅退出。
- `docs/architecture.md`：模块表加 `scripts/backtest.py` 行。
- `docs/commands.md`：快速检查表加回测命令 + 验证要点加回测段落。
- `docs/pitfalls.md`：新增「模块 scripts/（十三期：回测验证）」纪律段。
- `AGENTS.md`：Project Map 加 `scripts/backtest.py` 行 + tests/ 列表补 `test_backtest.py`。

未触碰：`daily_report.py` / `snapshot_report.py` / `src/*` / `config.json` / `requirements.txt` /
`data/` / `alerts/` / `context/`。

## 验证结果
- `venv/Scripts/python -m pytest tests/test_backtest.py -v` → **10 passed**。
- `venv/Scripts/python -m pytest tests/ -v` → **258 passed, 6 failed**。
  6 failed 全部位于 `tests/test_web.py`（错误为 `ValueError: time data '2026-08-00' does not
  match format '%Y-%m-%d' 等日期解析问题），属计划已标注的既有失败、非本任务回归
  （基线 248 passed + 6 web 失败；本次 248+10=258 passed）。
- `venv/Scripts/python scripts/backtest.py` → 退出码 0，耗时 **0.008s**（<5s 约束），
  生成 `reports/backtest_report.md`；89 有效交易日、6 触发事件：
  - SZ 4 次 / 年化 11.87 / 有效触发率 100% / 1·3·5·10 日平均后效 -0.11/-0.26/-0.59/0.65
  - VIX 1 次 / 年化 2.97 / VXN 1 次 / 年化 2.97（均为严格大于阈值触发）
  - MOVE / GSPC / IXIC / SH：0 次（阈值未触及）
- 数据不足验证：`test_insufficient_data_exit` 用 10 行小文件跑 `main(["--history", ...])`
  → 退出码 0、无报告生成、`data/alerts/context` 无任何写入（REPORTS_DIR 被 monkeypatch 到
  tmp_path 佐证）。
- `git status --short` 仅显示 3 个新增未跟踪项（scripts/ / tasks 计划目录 / tests/test_backtest.py），
  确认回测未改动 `data/alerts/context/`（report 本身被 gitignore）。

## 遇到的问题
1. **测试期望误设（非代码 bug）**：初版 fixture 假设触发比较首行基准，实际 `check_breach`
   比较相邻日（prev=昨日、cur=今日）。修正：`test_collect_triggers_strict_greater` 改为
   100→120（=阈值 20% 不触发）→145.2（vs 120 = +21% 触发）；`test_annualized_frequency`
   跨度应为首个相邻可算行（Jan02）到末行（Jan11）= 9 天 → 365/9（非 365/10）。两处均为
   测试期望错误，代码语义正确。
2. **edit 多行替换误吞相邻代码**：一次 `PUT 103.=107:` 锚点错位把
   `test_effective_trigger_rate` 的尾部函数体替换成了 annualized 函数，导致文件损坏并出现
   重复函数。已用整块 `PUT 100.=121:` 重写修复（与 pitfalls 记载一致：多行编辑优先整块重写）。

## 下次注意什么
- 回测触发语义 = **相邻日比较**，构造 fixture 时触发日变化率须相对其前一日，不能直接用首行。
- 多行编辑优先整块 `write` / 整块 `PUT`，避免锚点漂移误吞相邻代码。
- 阈值实时性：报告"各标的当前阈值"表用 `alert_threshold(sym)` 实时值并注明"config/env 实时
  配置"；测试须 `monkeypatch.delenv("ALERT_THRESHOLD_<SYM>", raising=False)` 隔离宿主 env，
  否则断言默认阈值会失败。
- 单标的有效点 <30 时报告仅输出计数 + "样本不足"标注，不出后效/胜率/有效触发率，避免误导。
