# 交给 Hermes 执行的提示词（plan 步骤 5 · 仓库外配置）

> 背景取证（2026-09-14 实测）：
> - 仓库内**没有任何文件**会写提交信息 `每日数据更新`；`~/.hermes/scripts/push_retry.sh` 与仓库 `scripts/push_retry.sh` 一致，**只做 push、不做 add/commit**。
> - ⇒ 那条 cron 的"全量提交"逻辑**完全在 Hermes 的 cron prompt 里**（`source=builtin` 的 agent 任务）。这解释了提交信息格式每次不同：`auto: 每日数据更新` / `auto: 每日数据更新 2026-09-14_23:10` / `... 22:45`（LLM 每次手写的）。
> - 可用子命令（已实测）：`hermes cron list` / `run <id>` / `edit <id> [--prompt ...] [--schedule ...] [--script ...] [--no-agent|--agent] [--workdir ...]` / `pause <id>` / `remove <id>`。**不存在** `ls` / `show`。

---

## A. 给 Hermes 会话的指令（在 Hermes 里粘贴这一段）

```text
请帮我收紧一条 cron 的提交范围（只改 cron 配置，绝对不要改仓库代码）。

仓库：D:/AGENT/MarketPulse（Windows，默认分支 master）
目标 cron：`MarketPulse 自动推送GitHub`（id 6f6e40a6f8b4，schedule */5，Deliver: local，source=builtin）

背景：它跑的是一个"把仓库改动提交并推送到 GitHub"的任务，提交信息形如 `auto: 每日数据更新` /
`auto: 每日数据更新 2026-09-14_23:10`。因为它用的是全量 `git add -A`，会扫走其它会话正在写的
源码/测试/文档半成品（已实测扫走过 web/static/style.css、tests/conftest.py、docs/pitfalls.md、
tasks/*/journal.md）。仓库内的 Python 侧已经收窄为路径白名单 data/context/alerts
（src/git_ops.py 的 _DATA_PATHS，提交 377a468），现在只剩这条 cron 没改。

【第 1 步 · 先取证并备份（不要跳过）】
1. `hermes cron list`，找到 6f6e40a6f8b4，把它的完整定义（schedule / prompt / script / deliver /
   workdir）原样贴出来。
2. 读出它当前的 `--prompt` 原文（`hermes cron edit 6f6e40a6f8b4` 的只读方式，或任何能显示原文的
   手段），并**把改动前的 prompt 原文完整记录在你的回复里**，作为回滚依据。
   读不到就明确说"读不到"，不要猜测内容。

【第 2 步 · 修改】
1. 用 `hermes cron edit 6f6e40a6f8b4 --prompt "<新提示词正文>"` 替换它的 prompt。
   新提示词正文见下方【新 cron prompt】区块，**原样使用**。
2. **频率保持 `*/5` 不变**（这条任务承担数据提交的新鲜度，不要降频、不要改成每天几次）。
3. 不改 name / deliver / workdir / model 等其它字段。
4. 如果读到的原文显示它是 `--script` 方式而非 prompt 方式：**不要**照抄上面的命令，
   改为把脚本里"提交范围"的那部分（`git add -A` 或 `git add .`）改成
   `git add data context alerts`，其它逻辑不动，并在报告里贴出改动前后的脚本片段。

【第 3 步 · 验收（必须实做，不许只推理）】
1. `hermes cron list` 复述改动后的定义，并给出改动前/后 prompt 对比。
2. 造一个源码 WIP：在 D:/AGENT/MarketPulse/web/static/app.js 末尾追加一行注释
   `// autopush-scope verify`。
3. `hermes cron run 6f6e40a6f8b4`，等它跑完（最多 3 分钟）。
4. 断言并贴出原始命令输出：
   - `cd /d D:/AGENT/MarketPulse && git status --porcelain -- web/static/app.js`
     → 期望仍是 ` M web/static/app.js`（**未被提交**）
   - `git log -1 --stat` → 输出里**不含** web/static/app.js
5. **必须恢复**：`git checkout -- web/static/app.js`，然后
   `git status --porcelain -- web/static/app.js` 应无输出。
6. 若断言失败：贴出原始输出，并用第 1 步记录的原文**把 prompt 回滚**，然后停下来告诉我，不要反复试。

【禁止（违反即视为执行失败）】
- 不修改 D:/AGENT/MarketPulse 里的任何文件（尤其 src/git_ops.py、.gitignore、web/、tests/、docs/）——
  仓库侧已经改完了，本次只是改 cron 配置。
- 不改 .env / 不改 data/ 内容。
- 不执行 `git reset --hard`、`git push --force`、`git stash`、`git checkout -- <非 app.js>`。
- 不动其它 cron（收盘日报 / A股午盘快照 / A股收盘快照 / 美股开盘快照 / 美股午盘快照 / 开盘分析推送 /
  数据同步到GitHub）。

【交付】
改动前 vs 改动后的 cron 定义对比 + 第 3 步的全部原始输出 + 一句话结论：还有哪条链可能提交源码
（期望答案："无"）。
```

---

## B. 新 cron prompt（第 2 步要写进去的正文）

```text
【MarketPulse 数据提交任务】

仓库：D:/AGENT/MarketPulse（默认分支 master）

只做下面这件事，不要做任何额外动作：

1. cd /d D:/AGENT/MarketPulse
2. 查看**白名单范围**内是否有改动：`git status --porcelain -- data context alerts`
   - 输出为空 → 本次什么都不做，直接结束（不产生任何提交、不推送）。
3. 有改动时，**只提交这三个目录**：
   git add data context alerts
   git commit -m "auto: 每日数据更新"
   git push origin master
   - 若 `git commit` 报 nothing to commit，说明判断失误，直接结束，不要改用其它 add 方式。
   - 若 push 失败（网络/代理），把原始错误打印出来即可结束，不要重试、不要回滚、不要 reset。

硬性禁止：
- 禁止 `git add -A`、`git add --all`、`git add .`、`git commit -a`。
  这会扫走其它会话正在写的源码/测试/文档半成品（web/、src/、tests/、docs/、tasks/），
  这是本任务被收窄的唯一原因。
- 禁止提交 `data/marketpulse.db` 及其 `-wal`/`-shm`（已被 .gitignore 排除）。
- 禁止 `git checkout` / `git restore` / `git stash` / `git reset --hard` / `git push --force`
  等任何会丢弃或改写他人改动的命令；工作区里的其它改动（含未跟踪文件）一律原样保留。
- 禁止修改仓库内任何文件（本任务只做 add / commit / push）。
- 禁止新增或用其它方式改动 cron。

完成后仅用一行汇报：`[data-commit] 改动=<有/无> 提交=<哈希或 none> 推送=<ok/fail>`
```

---

## C. 可选：如果再保留一条"兜底提交 Agent 产出"的链

plan §4.6 5b 的首选是**不再保留**（改为 Agent 收尾显式提交，事件式优于频率式）。若一定要兜底，建议：

- 频率：每天 1 次，`30 8 * * *`（在日线定稿 08:01 之后、其它会话高峰 18:00–23:00 之外）
- 提交范围：**限定 `docs tasks AGENTS.md`**（绝不含 `src/` `tests/` `web/` —— 那些只由 Agent 显式提交）
- prompt 正文把上述 B 段的 `git status --porcelain -- data context alerts` 换成
  `git status --porcelain -- docs tasks AGENTS.md`，`git add data context alerts` 换成
  `git add docs tasks AGENTS.md`
- 明确标注：**接受"可能撞上写了一半的文档"这一残余风险**（频率型方案无法根治）
