# 命令说明

> 列出项目所有验证命令。Agent 完成修改后必须运行相关命令。
> 所有命令需先激活 venv（Windows: `venv/Scripts/activate`），或直接调用 `venv/Scripts/python`。

## 快速检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/python -m pytest tests/ -v` | 运行单元测试 | 改了函数逻辑 / 提交前 |
| `venv/Scripts/python daily_report.py` | 运行主脚本（完整闭环：取数→报告→写缓存） | 改了数据获取/报告生成/错误处理逻辑 |

## 完整检查

| 命令 | 用途 | 什么时候跑 |
|---|---|---|
| `venv/Scripts/pip install -r requirements.txt` | 安装/校验依赖 | 环境变更 / 提交前 |
| `venv/Scripts/python -m pytest tests/ -v` | 完整测试套件 | 提交前 |

## 何时跑什么

| 改动类型 | 必须运行 |
|---|---|
| 数据获取逻辑（VIX/VXN/MOVE） | 主脚本 + 相关单元测试 |
| 报告/模板生成 | 主脚本（检查输出内容） |
| 状态判断/涨跌幅计算 | 相关单元测试 |
| 错误处理/离线容错 | 主脚本（断网场景） |

## 验证要点（对应任务 prd 的 Verification Plan）

- 首次运行 `daily_report.py`，`reports/YYYY-MM-DD.md` 与 `data/last_values.json` 应自动生成。
- 删除 `data/last_values.json` 后运行，涨跌幅应显示"首次运行，暂无历史对比"。
- 断网时运行，脚本不崩溃、输出明确错误提示。

## 已知问题

<!-- 记录不稳定测试、环境依赖、跳过的检查等 -->
- （暂无）