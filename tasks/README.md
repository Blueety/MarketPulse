# 任务目录

## 任务子目录

每个复杂任务创建一个子目录：

```
tasks/<日期>-<简述>/
  prd.md          需求文档
  plan.md         实施计划
  journal.md      执行日志
```

## 模板目录

`tasks/_template/` 里有 prd.md、plan.md、journal.md 的空白模板。
新建任务时从这里复制：

```bash
cp tasks/_template/prd.md tasks/2026-08-04-add-login/prd.md
cp tasks/_template/plan.md tasks/2026-08-04-add-login/plan.md
cp tasks/_template/journal.md tasks/2026-08-04-add-login/journal.md
```

## 什么时候建任务目录

- 改动涉及多个文件。
- 需求尚未完全确定。
- 工作可能跨越多个会话。
- 多个 Agent 或多人协作。

## 什么时候不需要

- 单文件小改。
- 明确的一行修复。
- 文档更新。

## 命名规范

```
tasks/2026-08-04-add-login/
tasks/2026-08-05-fix-null-pointer/
```

用 `日期-简短英文描述`，不要用中文或空格。
