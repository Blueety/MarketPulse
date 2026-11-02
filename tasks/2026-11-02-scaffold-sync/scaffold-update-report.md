# 脚手架更新器（scaffold-update.sh）使用评估报告

- **报告对象**：`D:/Obsidianhouse/AISTUDY/project-scaffold/project-scaffold/scripts/scaffold-update.sh`（commit `6eb5ee9`）
- **被试项目**：MarketPulse（生成于 2026-09-26，无 `.scaffold-version`，含 100 个任务目录、877 条测试）
- **观测期**：2026-11-02，一次完整同步 + 后续三轮结构治理（归档 94 个任务、迁移 5 个验证脚本、清零闸门债）
- **结论**：工具的核心机制（三路合并、冲突现场、裁决记忆、基线自检）**可用且可靠**；3 个缺口让它把一个本可 1 次交互的同步变成 5 次往返（约 105 秒纯扫描 + 数十分钟人工裁决），另有 3 条闸门侧缺陷是在本项目上暴露的。

---

## 1. 事实：这次同步做了什么

| 阶段 | 命令 | 耗时 | 结果 |
|---|---|---|---|
| 预览 | `bash scripts/scaffold-update.sh <项目>` | 22.9s | 9 冲突 / 9 升级 / 8 新增 / 1 保留 / 1 跳过 |
| 带内容预览 | `… --diff` | 27.5s | 1203 行 diff（`sed` 报 broken pipe） |
| 落盘 | `… --write` | 54.5s | 写冲突标记 + 生成 `.scaffold-version` + 跑目标仓库闸门 |
| 人工裁决 | — | 数十分钟 | 9 个冲突逐个读 ours/base/theirs 三元组 |
| 闸门自检 | — | — | 存量违规 **914** 条 |

同一 commit 上，工具自己报的基线是 `36d0751（按内容比对，一致率 52%）`，而项目真实生成时间（2026-09-26）对应的模板版本**已不在脚手架历史里**（该仓库 2026-10-29 重写过历史）。

---

## 2. 做得好的部分（建议保持）

1. **三路合并前把本地文件归一为 LF** 再 `git merge-file` —— 项目锁 `eol=lf`，不归一的话每个 CRLF 文件都会被判"每行都变了"。
2. **冲突现场留 `.ours / .base / .theirs`** —— 9 个冲突的裁决全靠这三份快照对照，没有它无法安全合并。
3. **裁决记进 `.scaffold-version`**，且模板再变时提示"请重新判断" —— 第二次同步能免掉已裁决的文件。
4. **`git archive | tar` 展开整棵树**，而不是逐文件 `git show` —— 28 个文件量级下差 7 倍。
5. **只碰 `templates/` 里出现过的路径**，`src/`、`tasks/<任务>` 一概不动 —— 这次零误伤。
6. 退出码语义清楚（0 完成 / 1 有冲突 / 2 用法错误），落盘后明确提示"脚本不做提交"。

---

## 3. 问题清单

### P0 —— 会导致错误合并（本次实际发生）

**P0-1 基线按内容猜中即用，无阈值、无来源记录**

- 证据：`基线: 36d0751（按内容比对，一致率 52%）` 之后**直接进入三方合并**；9 个"冲突"里大部分是"模板演进 vs 本地改动"，并非真冲突。
- 代码位置：`autodetect_base`（`scaffold-update.sh:266-268` 取最高一致率）、`:275-279` 只在一处 `note` 提示低一致率。
- 影响：用错的 base 做三路合并，会把"模板新增内容"和"本地改写"混成同一批冲突，人工必须逐行判断；更糟的情况是静默取错方向。
- 建议：一致率 < 80% 时**拒绝自动合并**，要求 `--from <sha>` 或显式 `--accept-guess`；无论如何把 `baseline_source=content-guess:52%` 写进 `.scaffold-version`，让下一次同步知道"这条基线是猜的"。
- 工作量：S（约 20 行）

**P0-2 生成器不写基线文件**（P0-1 的根因）

- 证据：`grep -n 'scaffold-version' init.sh init.ps1` → 0 命中。
- 影响：所有在更新器之前生成的项目，第一次同步必然走"猜基线"路径。
- 建议：init 生成时写 `commit=<templates 的 HEAD>`；对老项目提供 `--adopt-baseline`（只写文件、不合并）。

### P1 —— 可读性/可自动化性

**P1-1 无机器可读输出**：`grep -n 'json\|--report' scaffold-update.sh` → 0 命中。父进程/CI 只能解析人类文本。建议 `--json <path>`（`{baseline, baseline_source, files:[{path,action}], gate:{count,histogram}}`）+ `--report <path>` 出一份可直接贴进任务 journal 的 Markdown。

**P1-2 裁决只能在 `--write` 时落盘**：`:325` 的 `note "裁决只在 --write 时写入 .scaffold-version；这次是预览，只展示"`。本次为了试 `--keep-local` 的效果多跑了 2 次全量扫描（每次 20–30s）。建议预览时把裁决写入 `$WORK/decisions.pending` 并就地重算，`--write` 才落正式文件。

**P1-3 闸门自检只给绝对数与头 5 条**：`:548+` 的 `gate_report` 输出 `存量违规 914 条` + 前 5 条。真实构成（5 个目录 × 12 条，全是缺新模板章节）是我们自己 `grep | sed | uniq -c` 算出来的，这决定了后续治理路线。建议增加：**按文件类型/按目录的直方图** + **与 `.scaffold-version` 记录的 `gate_violations` 比较增减**；再加 `--refresh-gate-count`（只更新计数、不做合并），因为清零常跨越多个工作日。

**P1-4 平台工具链假设未自检**：`:227 / :543-544 / :622` 三处 `find`。本机 PATH 中 Windows 的 `find.exe` 抢在 MSYS `find` 前，输出 `FIND: 参数格式不正确`，随后被判成"找不到能对上的版本"。建议启动时自检 `find --version | grep -q GNU`（或直接改用 `git ls-tree -r`），失败时给出可执行提示。

**P1-5 `--diff` 在管道下吐 `sed: couldn't flush stdout: Broken pipe`**（本次两次）。`show_diff` 里 sed 直写 stdout；改成先收进变量再 `printf`，或 `2>/dev/null`。

**P1-6 "跳过"的文件不给差异**：本次 `.gitattributes` 被 `跳过（项目已有同名文件，不是模板来的）` 一行略过，但它和模板的 eol 规则**可能冲突**。建议打印"模板版 N 行 / 本地 M 行，`--show-skipped` 看差异"。

### P1 —— 结构性缺失（收益最大）

**P1-7 不区分"机制文件"与"内容文件"**

- 事实：`docs/agents/*`、多数 `skills/*`、`scripts/check-gates.*`、`.githooks/pre-commit` 必须**整份取模板**（本地改了下次必冲突，且这类 bug 应报上游）；`AGENTS.md`、`README.md`、`docs/{architecture,commands,pitfalls}.md`、`skills/pre-review` 必须**人工并集**（含本项目独有的「独立期望值预言机」一节）。
- 现状：这条规则只存在于使用者脑中，工具把两类摆在一起，9 个冲突全部需要人工分类。
- 建议：模板侧加标记（文件头 `<!-- scaffold:mechanism -->` 或 `templates/.scaffold-kinds` 清单）⇒ mechanism 自动 `theirs`、content 自动报 `union` 并标注"需人工"。可把每次同步的人工判断从 9 个文件压到 0–2 个。
- 工作量：M（模板侧标注 + 合并分支各 10 行）

### P2 —— 健壮性

**P2-1 写盘非原子**：逐文件 `cat > "$o"`，中途失败留下半合并的树；脚本自己注释里承认"半路退出比报错更糟"。建议先写 `$WORK/staged` 再整体落地，或在冲突现场旁边落 `MANIFEST`（每条动作一行）+ `--rollback <时间戳>`。

**P2-2 退出后无"我改了什么"清单**：写盘后只提示 `git diff` / `git status`。建议直接打印 `N 升级 / N 新增 / N 冲突` 的路径清单（可 `--quiet` 关闭）。

---

## 4. 闸门侧缺陷（随工具一起装进项目的 `scripts/check-gates.*`）

| # | 位置 | 问题 | 影响 |
|---|---|---|---|
| G1 | `check-gates.sh:228` | 规模底线按「**任一**候选任务声明 T2/T3」短路；候选为空时退回**所有在飞任务** | 一个纯代码提交，只要仓库里有任意 T2 任务就放行；而这道闸门正是「T0/T1 不等人确认」的唯一机械兜底 |
| G2 | `check-gates.awk:453` | 注释称 `field_filled` 管住「目标」，`plan_check` 里没有这条调用 | 计划不写目标也能过闸门 |
| G3 | `check-gates.sh`（`--staged` 口径） | `--staged` **不跳过** `tasks/_archive/`，纯 rename 的归档提交被判 60 项 | 工具自己在 `tasks/README.md` 推荐"归档已收尾任务"，但归档动作过不了自己的闸门（本次靠"先提交归档、后启用钩子"绕过） |

G3 建议：对 `git diff --cached --diff-filter=R100`（纯重命名、内容未变）不计违规。

---

## 5. 优先级与工作量

| 优先级 | 条目 | 工作量 | 预期收益 |
|---|---|---|---|
| 1 | P0-1 基线阈值 + 来源记录 | S | 消除"用错 base 合并"这一最危险行为 |
| 2 | P0-2 init 写 `.scaffold-version` | S | 让 P0-1 不再触发 |
| 3 | P1-7 机制/内容分类标记 | M | 每次同步的人工判断 9 → 0–2 |
| 4 | G3 纯重命名豁免 | S | 归档动作不再自相矛盾 |
| 5 | P1-3 闸门直方图 + 计数刷新 | S | 存量债治理可排期，不用每次现算 |
| 6 | P1-1 `--json` / `--report` | S | 可进 CI / 可贴 journal |
| 7 | G1 规模判据改"本任务自身" | M | 兜底不再可绕 |
| 8 | P1-2 / P1-4 / P1-5 / P1-6 | S | 每次省 1–2 轮往返、少一类环境误判 |
| 9 | P2-1 / P2-2 / G2 | S–M | 失败可回滚、输出更完整 |

---

## 6. 复现命令（附录）

```bash
# 本次同步（Windows 上必须显式用 Git Bash，且 /usr/bin 前置）
D:/Claude/Git/usr/bin/bash.exe -c \
  'export PATH="/d/Claude/Git/usr/bin:/usr/bin:$PATH"; \
   bash scripts/scaffold-update.sh /d/AGENT/MarketPulse --diff'

# 基线猜测证据
grep -n '一致率\|autodetect_base' scripts/scaffold-update.sh

# 生成器不写基线
grep -n 'scaffold-version' init.sh init.ps1     # 0 命中

# 平台假设
grep -n 'find ' scripts/scaffold-update.sh      # :227 :543-544 :622

# 闸门构成（本次手工算的，正是 P1-3 想省掉的活）
cd /d/AGENT/MarketPulse && sh scripts/check-gates.sh 2>&1 \
  | grep '^  \[x\]' | sed 's/^  \[x\] tasks\///; s/\/.*//' | sort | uniq -c
```
