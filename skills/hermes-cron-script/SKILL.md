---
name: hermes-cron-script
description: 诊断和修复 Hermes cron「Script not found」类失败。覆盖 HERMES_HOME/scripts 定位、cron doctor/runs 取证、修复与实跑验证。适用于 --no-agent --script 模式的定时任务。
---

# Hermes cron 脚本模式故障排查

## 何时用

- Hermes cron 报 `Script not found: <path>` 或 `script resolves outside HERMES_HOME/scripts`
- 报 `Cannot run .sh/.bash script ...: bash not found on PATH`
- 新建了 `--no-agent --script` 模式的 job，不确定 wrapper 该放哪

## 🔴 核心事实（最容易踩的一条）

**wrapper 必须放 `$HERMES_HOME/scripts`，不是 `~/.hermes/scripts`。**

Hermes 自己的 docstring 写的是 `~/.hermes/scripts/` —— 那是 **Linux/macOS 默认值**，
在 Windows 上会误导。真实解析链（读源码确认）：

```
_scripts_dir_for_cron()  →  CRON_DIR.parent / "scripts"
CRON_DIR                 =  get_hermes_home() / "cron"
get_hermes_home()        =  上下文覆盖 → HERMES_HOME env → 平台默认
平台默认(win32)          =  %LOCALAPPDATA%\hermes     ← 不是 ~/.hermes
```

**动手前先打印真实值**，不要猜：

```bash
echo "HERMES_HOME=[${HERMES_HOME:-未设置}]"      # env 覆盖优先
hermes cron status                                 # 确认 Gateway 在跑
```

⚠️ 为什么这个坑特别隐蔽：`~/.hermes/` 目录**通常真实存在**（历史遗留，含 plans/scripts/state.db），
把脚本放进去**不会立刻报错**，要等 cron 真正触发才暴露 ⇒ **延迟暴露**。
新建 job 时务必用 `hermes cron doctor` 立刻验证，不要等第二天。

## Steps

1. **取默认位置**：`echo $HERMES_HOME`。未设则 Windows 下是 `%LOCALAPPDATA%\hermes`。
   job 的 `Script:` 字段只写**文件名**（相对路径）时，就解析到 `<HERMES_HOME>/scripts/<文件名>`。
2. **证明文件在哪**：`ls -la <HERMES_HOME>/scripts/` 与 `ls -la ~/.hermes/scripts/` 对比。
   找参照物 —— 正确位置上**往往已经躺着别的能跑的脚本**。
3. **读 doctor 定性**：
   ```bash
   hermes cron doctor          # 列出 script not found / last run failed 等
   hermes cron runs <job_id>   # 历史；只有一条记录 = 首次运行，不是环境漂移
   ```
   ⚠️ 区分两种 doctor 报错：`script not found`（当前配置问题，可修）vs `last run failed: ...`
   （**历史记录**，位置修好后仍会显示，必须成功跑一次才消失）。
4. **修**：`cp <错位置>/<脚本> <HERMES_HOME>/scripts/` + `chmod +x`。
   ⚠️ **不能靠给 `Script:` 写绝对路径绕过** —— `_script_health_issue()` 有
   `path.relative_to(scripts_dir)` 校验，越界直接报 `script resolves outside HERMES_HOME/scripts`。
5. **验 bash**（`.sh`/`.bash` 才需要）：调度器用 `shutil.which("bash")`，找不到会 fallback `/bin/bash`，
   两者都无则报 `bash not found on PATH`。Windows 上依赖 Git Bash 在 PATH 中。
6. **实跑**（同时验证「位置对 + 解释器可用」）：
   ```bash
   hermes cron run <job_id>    # 标记为下次 tick 执行
   sleep 70 && hermes cron runs <job_id>
   ```
   ⚠️ 安全性：**失败无副作用**（解释器找不到时脚本根本不执行）；成功则完成该 job 的正常业务
   （可能含 `auto_commit_push` ⇒ 会 commit + push，属设计行为）。

   🔴 **但 `hermes cron run`（direct）成功 ≠ 定时（builtin/ticker）成功 —— 必须再等一轮真实定时运行**（2026-09-20 实测）：
   两条路径的执行环境不同（bash 解析 / PATH 可能不一样）。实测 `.sh` 包装器手动跑成功、
   `cron run` 成功，**builtin 每轮稳定失败**（`exit 1` + 11 个非 ASCII 字节的 stderr 被 UTF-8+replace 吃成 `?`；
   判别实验证明 builtin 根本没在执行该文件）。**修法：改用 `.py` 包装器**（Hermes 对 `.py` 走
   `_windows_cron_python_invocation`，绕开 bash 分支；同目录既有 `.py` 长期正常即为先例）。
   验证 builtin 的两个入口：`hermes cron runs <job_id>`（看 `source=builtin` 的记录）
   与 `D:\hermes\cron\output\<job_id>\<时间>.md`（实际 stdout/stderr）。
   排查工具：`D:\hermes\cron\executions.db`（持久化执行记录）。

7. **存量排查（修一个必须查全部）**：修好一个 `.sh` 后立刻
   `ls D:\hermes\scripts\*.sh` —— **builtin 的 bash 环境问题对每条 `.sh` 都成立**，
   凡 `.sh` wrapper 都建议迁 `.py`（哪怕它"一直跑得好好的"：`hermes cron run` 的 direct 成功
   会掩盖 builtin 的失败，直到下一次真实定时触发才爆，最长可能隔一天）。
   2026-09-20 修 autopush 时没查存量，`marketpulse_econ_calendar.sh` 次日 09:00 才爆
   （同一 `???????` 签名）—— 别让下一条 `.sh` 再等一天。
8. **builtin 快速验证技巧**：`hermes cron edit <id> --schedule "* * * * *"` 临时改每分钟，
   等 1–2 轮看 `cron runs` 的 `source=builtin` 记录，验证后**立即改回**。
   （前提：脚本幂等 + auto_commit_push 无改动跳过，多跑几轮无副作用。）
7. **终检**：`hermes cron doctor` 应报 `✓ found no issues`；`cron list` 的 `Last run` 应为 `ok`。

## 执行语义（供对照）

- `.sh` / `.bash` 经 **bash** 执行；**其余扩展名一律走 Python**（`.py` 不需要 shebang）。
- `no_agent=True` 时脚本 **stdout 直接投递**；**空 stdout = 静默不投递**（不是失败）。
- job 的 `workdir` 字段（绝对路径、**不受** scripts_dir 限制）会作为脚本 cwd ⇒
  有它就不必在脚本里写 `cd <repo>`。

## Stop Conditions

- `HERMES_HOME` 指向的目录里**没有** `cron/` 子目录 ⇒ 先停下确认是不是两套 home 并存。
- 需要改 `HERMES_HOME` 本身时停下（会搬走整个 cron 存储，影响所有 job）。
- 实跑会 push 且用户未预期时，先问。

## Output

- 一句话根因（含「hermes 找 X，文件实际在 Y」）。
- 受影响的 job 数与范围（`cron list | grep Script:` 数出 script 模式的 job）。
- 修复动作 + `doctor` 前后对比 + 实跑结果。
