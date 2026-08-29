---
name: pre-review
description: 提交 PR 或请求人工审查前使用。只读检查当前变更的正确性、范围、测试、安全性和规范。
allowed-tools: Read, Grep, Glob
---

# 提交前审查

## Steps

1. **Diff Summary**: 检查变更文件列表和 diff 摘要。
2. **Context Read**: 阅读变更文件的周边上下文。
3. **Checklist**: 逐项检查以下维度。
4. **Findings**: 按严重程度排列发现。
5. **Summary**: 给出总体判断。

## Checklist

| 维度 | 检查项 |
|---|---|
| Correctness | 逻辑是否正确，边界是否覆盖 |
| Scope | 是否有无关改动，是否超出任务范围 |
| Tests | 相关测试是否已运行，是否缺少测试 |
| Security | 是否暴露敏感信息，是否有注入风险 |
| Conventions | 是否符合项目命名、风格和目录约定 |
| Docs | 是否需要更新 README、architecture 或 commands |

## Output Format

```
## Findings (按严重程度排序)

### Critical
- [文件:行号] 问题描述

### Warning
- [文件:行号] 问题建议

### Info
- [文件:行号] 可选优化

## Verification
- 已运行: <命令列表>
- 未运行: <命令列表及原因>

## Verdict
- [ ] 可以提交
- [ ] 需要修改后再审
```

## Rules

- 只读，不修改文件。
- 不把风格偏好当 bug。
- 不声称测试通过，除非真的运行了。
- 每条发现必须落到具体文件和行号。
