# 上游缺陷报告：断链校验 / ADR 互指 / journal 校验（2026-11-05）

> 报告方：MarketPulse（`D:/AGENT/MarketPulse`，Python + 只读 Web 看板，Windows 10 + Git Bash）
> 脚手架版本：`f0a83d0`（模板 `templates/`，本项目从 `fe434d2` 同步上来）
> 触发场景：一次例行脚手架同步。同步后 `sh scripts/check-gates.sh` **385 项违规**，逐类核查后确认其中
> **313 项是校验器扫错文件、72 项是判定过宽**，0 项是本项目的真实断链（ADR 那条校验本身 **0 违规**，很干净）。
> 结论：本次只落地了升级的文件，`scripts/check-gates.{sh,awk}`、`tasks/_template/journal.md`、
> `docs/agents/任务分级.md` 在本项目记了 `keep-local`（机制文件不本地 fork），等下面 D1–D4 修掉再解除。

| # | 缺陷 | 严重度 | 影响面 |
| :-- | :--- | :--- | :--- |
| D1 | `check_links()` 用 `find` 扫盘，不尊重 `.gitignore` ⇒ 虚拟环境 / 生成物 / agent 记忆全被当活文档 | **High** | 任何仓库里带 gitignored 目录的项目（本项目 313/385） |
| D2 | `emit_link()` 仍把占位符、CSS 类名串、点号表达式、npm 包名、子目录相对路径当真路径 | **High** | 本项目 72 项 |
| D3 | `check_next_notes()` 逐行判「下次注意什么」，而 `tasks/_template/journal.md` 示范「条目一行 + `→` 写下一行」⇒ 照模板写必被拦 | **High** | 所有 T1+ 任务 |
| D4 | `count_result_items()` 把模板自带的 `- 返工: 0 次` 算成一条验证结果 ⇒ 「验证结果为空」的 journal 能过闸门（假阴性） | Medium | 所有任务 |
| D5 | `--keep-local` 的裁决有一次没写回 `.scaffold-version`（未能复现，附完整命令序列） | Low（待复现） | 同步流程 |

---

## D1 `check_links()` 扫的是磁盘，不是仓库

**位置**：`templates/scripts/check-gates.sh:161-171`

```sh
files+=("${f#./}")
done < <(find . -name '*.md' -type f 2>/dev/null | sort)
```

函数自己的注释（同文件 150-160 行）写的是「只查**活文档**：根目录的 md、`docs/`、`skills/`、`tasks/README.md`」，
但实现是整盘 `find`，于是：

- `.gitignore` 里的目录一样被扫：本机 `venv/`（33 项）、`.venv/`（6）、`reports/`（210，运行产物）、
  `.workbuddy/`（64，编辑器/agent 记忆）合计 **313 项**，全是第三方包自带的 skill README 与历史报告；
- 这类目录往往有几千个 md，扫描时间也会明显变长（本项目 477 个文件被纳入，其中只有约 100 个是仓库里的）。

**复现**（最小）：

```sh
mkdir -p /tmp/probe && cd /tmp/probe && git init -q
printf 'venv/\n' > .gitignore
mkdir -p venv/Lib/site-packages/pkg && printf '`missing/x.md`\n' > venv/Lib/site-packages/pkg/README.md
printf '# t\n\n- 见 `docs/nope.md`\n' > README.md
sh <scaffold>/scripts/check-gates.sh    # ⇒ 两条违规，其中 venv/... 那条是噪声
```

**建议修法**：把 `find` 换成 git（保留现有的 `./tasks/*` 过滤与 `./tasks/README.md` 特例）：

```sh
while IFS= read -r f; do
    f="./$f"
    case "$f" in
        ./tasks/README.md) ;;
        ./tasks/*) continue ;;
    esac
    files+=("${f#./}")
done < <(git -C "$root" ls-files -co --exclude-standard -- '*.md' 2>/dev/null | sort)
```

顺带一个相关问题：`.workbuddy/` 这类「不在 `.gitignore` 里但也不该算活文档」的目录，修完 D1 后仍会被扫
（本项目那份在 `.gitignore` 里，所以 D1 修完就干净）。若想更稳，建议给校验器加一个跳过清单，
见 D2 末尾的 `.gates-ignore` 建议。

---

## D2 `emit_link()` 判定仍过宽（f0a83d0 修了四类，还差五类）

**位置**：`templates/scripts/check-gates.awk:726`（`emit_link`）

`f0a83d0` 已挡掉 env 赋值、pytest node id、`path:120` 行号、裸域名——都对。剩下的误判（本项目 72 项，抽样如下，
全是**有意为之的文档写法**，不是断链）：

| 类型 | 实例（文件） | 实际含义 |
| :--- | :--- | :--- |
| 日期/编号占位符 | `` `reports/YYYY-MM-DD.md` ``（`docs/commands.md`）、`` `data/backup/history_YYYY-MM.json` ``（`AGENTS.md`、`docs/architecture.md`）、`` `context/YYYY-MM-DD.json` `` | 命名约定；模板自己的 `tasks/_template/*` 里也有同款 |
| CSS 选择器串 | `` `.card/.kpi-card/.topbar` ``（`docs/architecture.md`）、`` `.row-kpi/.row-main/.row-3/.row-news` ``（`AGENTS.md`） | 斜杠分隔的类名列表 |
| 点号表达式 | `` `src/econ_calendar.KINDS` ``、`` `web/app.py:_ASSET_FILES` ``、`` `src/env_util.require_env` ``、`` `src/settings_store.is_readonly(` `` | 模块属性引用（`:` 已剥，`.` 没剥） |
| npm 包名 | `` `@avenra/liquid-glass@1.2.0` ``（`docs/architecture.md`、`docs/frontend-structure.md`） | 依赖标识 |
| 子目录相对路径 | `` `skin/tokens.css` ``（真实路径 `web/static/skin/tokens.css`）、`` `static/app.js` ``（真实 `web/static/app.js`） | 文档里的简称，读者按上下文能定位 |
| 只读 vendored README | `web/static/vendor/liquid-glass/README.md` 里的 `` `dist/liquid-glass.esm.js` ``、`` `styles/liquid-glass.css` `` | 上游包自带示例，本项目按约定**禁改写** vendored 文件 |

**复现**：在任意 md 里写

```md
- 产物：`reports/YYYY-MM-DD.md`；样式：`.card/.kpi-card`；入口：`src/x.MODULE`；依赖：`@scope/pkg@1.2.0`
```

再跑闸门 ⇒ 四条违规。

**建议**（任选，按投入从小到大）：

1. 占位符：跳过含 `YYYY` / `MM` / `DD` / `HH` / `NNNN` 的串（`NNNN` 已经在挡了）。
2. 点号表达式：`:` 已剥，再补一条「最后一段含 `.` 但第一段是目录且该目录存在」→ 判为模块引用；
   或简单点：`s ~ /\.[A-Z_][A-Z0-9_]*/`（`.CONST` / `.func_name`）直接返回。
3. npm 包名：`s ~ /^@[^/]+\/[^/]+(@[^/]+)?$/` 返回。
4. **`.gates-ignore`（推荐）**：项目根放一组 glob / 前缀模式，`check_links` 与 `check_adr` 读它跳过。
   这是唯一能同时解决「vendored 只读文件」「子目录简称」「本项目有意不建的产物目录」的办法，
   而且不会逼项目去改写有信息量的文档。没有该文件时行为不变。
5. 兜底：`emit_link` 已经跳过围栏代码块，可以在文档侧把「命名约定」写进围栏块，但**这属于让文档迁就校验器**，
   多数项目不会愿意做。

---

## D3 journal「下次注意什么」：模板示范的写法过不了闸门

**位置**：`templates/scripts/check-gates.awk:574`（`check_next_notes`）与
`templates/tasks/_template/journal.md`（示范）、`templates/tasks/README.md:117`（说明）

- 模板示范（`tasks/_template/journal.md`，`## 下次注意什么` 注释）：

  ```
   - 改 A 必须同步 B
     → pitfalls
  ```
- 说明（`tasks/README.md`）：「**查**：按**条目**判（`→` 写成下一行也算），条目里含 `→` 或「不沉淀」」
- 实现（`check-next-notes`）：把整节 `split(…, "\n")` 后**逐行**判，每条非空行必须自带 `→` 或「不沉淀」。

**复现**（本项目实跑，用一份完整的 journal）：

```sh
cat > /tmp/p1/journal.md <<'EOF'
…（其余节齐全）
## 下次注意什么

- 改 A 必须同步 B
  → pitfalls
EOF
awk -v kind=journal -v fpath=tasks/p1/journal.md -f <scaffold>/scripts/check-gates.awk tasks/p1/journal.md
# ⇒ [x] 「下次注意什么」这条没有去向: 改 A 必须同步 B
```

**本人踩到**：本项目同步后按新模板写 journal，`git commit` 被自己的钩子拦了 5 条，只能把 `→` 全部挪回同一行。

**建议**：让实现追上文档——遍历行时记住「上一个条目行」，续行出现 `→`/「不沉淀」时回填给上一条；
或者退一步，把模板示范与 `tasks/README.md` 改回「同一行写去向」。两者只能有一个是对的，现在是错配。

---

## D4 `- 返工: 0 次` 会被当成一条验证结果（假阴性）

**位置**：`templates/scripts/check-gates.awk:387`（`count_result_items`）与 `:552`（判定处）

```
if (table_rows(verify, 0) == 0 && count_result_items(verify) == 0)
    V("「## 验证结果」里没有一行结果")
```

而 `tasks/_template/journal.md` 的「## 验证结果」**自带**一行 `- 返工: 0 次`，`count_result_items` 把它数成 1 条
⇒ 只要模板没被删空，就永远判不出「验证结果为空」。

**复现**：

```sh
# journal 的「验证结果」只留「- 未运行的检查及原因: 无」和「- 返工: 0 次」，其余节齐全
awk -v kind=journal -v fpath=tasks/p1/journal.md -f <scaffold>/scripts/check-gates.awk tasks/p1/journal.md
# ⇒ 无违规
# 删掉 `- 返工: 0 次` 那一行后再跑 ⇒ [x] 「## 验证结果」里没有一行结果
```

**建议**：`count_result_items` 跳过 `返工` / `被打回` 这两类计数字段（或在模板里把这行移出「## 验证结果」节）。
另外模板注释里那句「闸门不会把它算成一条验证结果」与实际相反，需要一并改。

---

## D5 `--keep-local` 的裁决有一次没写回 `.scaffold-version`（未复现，供排查）

**现象**：`--write --keep-local X --keep-local Y` 打印了 `[!] 记下裁决: keep-local X/Y`，但跑完 `.scaffold-version`
里**没有**这两行（文件其余字段被更新，`gate_violations` 也刷新了）。之后用同样参数再跑一次（此时项目已无待升级文件），
仍然没有这两行；而手工补写 `decision …` 行后，`--refresh-gate-count` 与后续预览都能正确读到并「跳过」。

**未能复现**：项目完成同步后，用 `--write --keep-local tasks/README.md`（本项目等于模板、无任何文件动作）
再试一次，裁决**正常写回**了。所以更可能是「某次运行在写版本文件之前中断」（`set -e` 下 `git merge-file` /
`gate_report` 的某一步返回非零）。当时没有保留完整输出。

**建议**：
1. `record_decisions` 之后立刻落盘一次（或把裁决写入 `trap EXIT`），别等到汇总前的 `write_version_file`；
2. 收尾打印一行「已写入 N 条裁决」，让「打印了但没落盘」这种状态不可能静默；
3. 若确实是 `set -e` 提前退出，`record_decisions` 的 `note "记下裁决"` 应该改成「待写盘」，避免误导。

---

## 顺带确认：`check_adr` 没问题

本项目 14 个 ADR、`docs/adr/README.md` 全部通过（0 违规），互指格式也是本项目想要的。
上面四条之外，本次同步升级进来的其他文件（`docs/adr/README.md` 新增的「被否决方案先写最强理由」「两边都要写」、
seam 措辞改成「写进 `plan.md` 而不是等确认」）都已落地并生效，没有问题。

---

## 本项目当前的 `keep-local` 状态（解除条件）

| 文件 | 模板 sha | 解除条件 |
| :--- | :--- | :--- |
| `scripts/check-gates.sh` | `93b1feff…` | D1 修复 |
| `scripts/check-gates.awk` | `d37357ac…` | D2（+D3 实现侧）修复 |
| `tasks/_template/journal.md` | `9433342…` | D3、D4 修复（模板示范与实现对齐） |
| `docs/agents/任务分级.md` | `b18e60a…` | `check_scale` 的空索引短路 / 在飞任务累计随 D1 一起升级 |

四个文件修好后的验证路径（本项目会重跑）：预览应显示这四个文件「升级」，随后
`sh scripts/check-gates.sh` 必须仍为 0 项（本项目 100 个历史任务、约 100 篇活文档，正好是回归样本）。
