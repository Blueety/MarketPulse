# 命令说明

> 列出项目所有验证命令。Agent 完成修改后必须运行相关命令。
> 所有命令需先激活 venv（Windows: `venv/Scripts/activate`），或直接调用 `venv/Scripts/python`。

## 快速检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/python -m pytest tests/ -v` | 运行单元测试 | 改了函数逻辑 / 提交前 |
| `venv/Scripts/python daily_report.py` | 运行主脚本（完整闭环：取数→报告→趋势图→写历史→写缓存） | 改了数据获取/报告生成/错误处理逻辑 |
| `venv/Scripts/python snapshot_report.py` | 运行午盘快照（取数→快照→落盘） | 改了快照逻辑 |

## 完整检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/pip install -r requirements.txt` | 安装/校验依赖 | 环境变更 / 提交前 |
| `venv/Scripts/python -m pytest tests/ -v` | 完整测试套件 | 提交前 |
| `venv/Scripts/python -c "import matplotlib; matplotlib.use('Agg')"` | 校验 matplotlib 可用（Agg 无头后端） | 环境变更 / 提交前 |

## 何时跑什么

| 改动类型 | 必须运行 |
|---|---|
| 数据获取逻辑（VIX/VXN/MOVE） | 主脚本 + 相关单元测试 |
| 报告/快照/趋势图生成 | 主脚本 + 快照脚本（检查输出内容与 PNG） |
| 状态判断/涨跌幅计算 | 相关单元测试 |
| history 读写/滚动 | 相关单元测试（test_analyzer.py TestHistory） |
| 错误处理/离线容错 | 主脚本（断网场景） |

## 验证要点（对应任务 prd 的 Verification Plan）

- 首次运行 `daily_report.py`，`reports/YYYY-MM-DD.md`、`data/last_values.json`、`data/history.json` 应自动生成；history 只有 1 条时无趋势图（数据不足 2 条跳过）。
- 删除 `data/last_values.json` 后运行，涨跌幅应显示"首次运行，暂无历史对比"。
- 断网时运行，脚本不崩溃、输出明确错误提示、报告标注获取失败、history 记录 null。
- 有 ≥2 条历史数据（不含当日）时运行 `daily_report.py`，应生成 `reports/charts/YYYY-MM-DD-trend.png`，且报告中含「## 📉 近30日趋势」章节引用 `./charts/YYYY-MM-DD-trend.png`。
- 运行 `snapshot_report.py`，应生成 `reports/snapshots/YYYY-MM-DD-noon.md`（仅记录当前值与状态，无涨跌幅）。
- history.json 超过 90 条时自动滚动（仅保留最近 90 条）；同日重复运行按 date 覆盖，不产生重复条目。
- 趋势图渲染超过 3 秒时跳过绘图，报告趋势章节改为文字说明，不中断整体流程。

## 已知问题

<!-- 记录不稳定测试、环境依赖、跳过的检查等 -->
- （暂无）
