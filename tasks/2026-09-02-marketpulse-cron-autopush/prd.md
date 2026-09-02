# PRD：MarketPulse Cron 执行后自动提交推送

## 目标

每次 MarketPulse 的 cron 任务（daily_report / snapshot_report / opening_analyzer）执行完成后，自动将本次产生的文件变更（报告、数据缓存、context 等）commit 并 push 到 GitHub，确保 Railway 部署始终与最新数据同步。

## 背景

当前 MarketPulse 部署在 Railway，通过 GitHub auto-deploy 实现自动部署。但每次 cron 执行产生的新报告和数据缓存需要手动 commit + push 才能触发 Railway 更新。用户希望这个过程全自动。

## 需求

### 功能需求

| # | 需求 | 说明 |
|---|------|------|
| F1 | 自动 commit | cron 执行后，将变更文件 add + commit，commit message 包含日期和类型 |
| F2 | 自动 push | commit 后自动 push 到 origin/master |
| F3 | 代理支持 | push 通过 Clash 代理（http_proxy=http://127.0.0.1:7890） |
| F4 | 无改动不提交 | 如果 git diff 为空，跳过 commit/push |
| F5 | commit message 规范 | 格式：`auto: YYYY-MM-DD {报告类型}`，如 `auto: 2026-09-02 daily report` |
| F6 | 推送失败重试 | push 失败时 cron 重试，成功后取消重试 cron |

### 非功能需求

| # | 需求 | 说明 |
|---|------|------|
| NF1 | 最小改动 | 只修改 Python 脚本，不引入新依赖 |
| NF2 | 零侵入 | 自动提交逻辑作为可选步骤，不影响现有报告生成流程 |
| NF3 | 幂等 | 重复执行不会产生重复 commit |

## 涉及文件

| 文件 | 改动 |
|------|------|
| `daily_report.py` | 末尾添加 auto-commit/push 步骤 |
| `snapshot_report.py` | 末尾添加 auto-commit/push 步骤 |
| `opening_analyzer.py` | 末尾添加 auto-commit/push 步骤 |
| `src/` 可选 | 提取公共 git 操作函数（避免重复代码） |

## 不改动的文件

- `data/*`、`reports/*`、`alerts/*`、`context/*`（均为 git tracked 的生成物）
- `config.json`（用户配置，gitignore）
- `.env`（环境变量，gitignore）

## 实现方案

### 方案 A：每个脚本末尾独立添加 git 操作（简单直接）

每个脚本（daily_report.py / snapshot_report.py / opening_analyzer.py）末尾加：

```python
# Auto-commit and push
import subprocess
def auto_commit_push(date_str, report_type):
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=r"D:\AGENT\MarketPulse")
        if not result.stdout.strip():
            print(f"[auto-push] No changes, skipping.")
            return
        subprocess.run(["git", "add", "-A"], cwd=r"D:\AGENT\MarketPulse", check=True)
        subprocess.run(["git", "commit", "-m", f"auto: {date_str} {report_type}"], cwd=r"D:\AGENT\MarketPulse", check=True)
        env = os.environ.copy()
        env["http_proxy"] = "http://127.0.0.1:7890"
        env["https_proxy"] = "http://127.0.0.1:7890"
        subprocess.run(["git", "push", "origin", "master"], cwd=r"D:\AGENT\MarketPulse", check=True, env=env)
        print(f"[auto-push] Committed and pushed: {date_str} {report_type}")
    except Exception as e:
        print(f"[auto-push] Failed: {e}")
```

### 方案 B：提取公共模块 `src/git_ops.py`（DRY）

新建 `src/git_ops.py`，三个脚本共用。

## 验证

```bash
cd D:\AGENT\MarketPulse
venv\Scripts\python daily_report.py
git log --oneline -1  # 应看到 auto commit
git status            # 应为 clean
```

## 风险

| 风险 | 缓解 |
|------|------|
| push 失败（代理未开） | 失败只记日志不中断主流程；可配合 cron 重试 |
| 误提交敏感文件 | .gitignore 已排除 config.json / .env / data/ |
| 并发冲突 | cron 任务不并发执行（已有调度间隔） |
