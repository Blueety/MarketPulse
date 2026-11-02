# 计划：fmt_value "获取失败" → "未开盘"

## 目标
将 `fmt_value` 函数在 value 为 None 时的显示文案从"获取失败"改为"未开盘"，与 `build_statuses` 的状态标签保持一致。

## 涉及文件
- `src/analyzer.py`：第 547-548 行 `fmt_value` 函数

## 实施步骤
1. 将第 547 行注释改为 `"""收盘价显示：保留两位小数；None 显示未开盘。"""`
2. 将第 548 行 `"获取失败"` 改为 `"未开盘"`

## 验证
1. 运行 `venv/Scripts/python -m pytest tests/test_analyzer.py -v`
2. 如有测试断言旧文案"获取失败"，同步更新为"未开盘"
3. 运行 `git diff` 检查改动范围
