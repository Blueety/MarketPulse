# PRD：开盘/快照数据更新到 history.json 并自动推送

## 目标

让 `opening_analyzer.py` 每次运行时也将当日数据追加到 `data/history.json`，使 web 看板能显示最新的开盘/快照数据，而不仅仅是收盘日报的数据。

## 背景

当前 `data/history.json` 只有 `daily_report.py`（收盘日报）才会更新。`opening_analyzer.py`（开盘分析）和 `snapshot_report.py`（盘中快照）只更新 `context/` 和 `alerts/`，不更新 `data/history.json`。导致 web 看板在开盘/快照后仍显示旧数据。

## 需求

| # | 需求 | 说明 |
|---|------|------|
| F1 | opening_analyzer.py 追加 history | 每次运行时将当日 10 个指数的数据追加到 `data/history.json` |
| F2 | snapshot_report.py 追加 history | 每次运行时将当日数据追加到 `data/history.json` |
| F3 | 幂等 | 同一日多次运行不重复追加（按 date 去重，覆盖已有条目） |
| F4 | 90 天滚动 | 追加后仍保持 90 天滚动窗口 |
| F5 | auto-commit/push 生效 | 数据更新后自动 commit + push（已接线的 git_ops） |

## 涉及文件

| 文件 | 改动 |
|------|------|
| `opening_analyzer.py` | main() 中调用 `append_history()` |
| `snapshot_report.py` | main() 中调用 `append_history()` |
| `src/analyzer.py` | 确认 `append_history()` 可被复用（已有函数） |

## 不改动的文件

- `daily_report.py`（已更新 history）
- `web/*`（只读 history.json）
- `tests/*`（需新增测试）

## 验证

```bash
cd D:\AGENT\MarketPulse
venv\Scripts\python opening_analyzer.py --market a-share
cat data/history.json | python -c "import sys,json; d=json.load(sys.stdin); print(d['dates'][-1])"
# 应显示今天日期
```
