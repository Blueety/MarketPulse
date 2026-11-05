# 上游缺陷报告：断链校验 / ADR 互指 / journal 校验（2026-11-05）

> 报告方：MarketPulse（`D:/AGENT/MarketPulse`，Python + 只读 Web 看板，Windows 10 + Git Bash）
> 脚手架版本：`f0a83d0`（模板 `templates/`，本项目从 `fe434d2` 同步上来）
> 触发场景：一次例行脚手架同步。同步后 `sh scripts/check-gates.sh` **385 项违规**，逐类核查后确认其中
> **313 项是校验器扫错文件、72 项是判定过宽**（第一轮结论：当时扫描范围里没有真实断链；第二轮用修好的校验器重跑后，在本仓抓出 **15 处真实的历史断链**，见文末补充报告）。
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

---

# 补充报告（2026-11-05 20:20，`115092e` 之后）：D1–D4 已确认修好，但缺一个「放行」机制

## 修复验收（本项目实跑）

`115092e` 之后把 `scripts/check-gates.{sh,awk}` 升到模板版。数字变化：**385 → 17 → 15 项修复 + 2 → 0**（17 = 新闸门在本仓的首次实跑；15 = 它抓出的真实历史断链，已逐条修文档；2 = 一条自写 README 的写法问题，见下；0 = 当前）：

```
$ sh scripts/check-gates.sh
检查文档内的相对引用（64 个文件）      # 之前是 477 个文件（含 venv/reports/.workbuddy）
  [x] web/static/vendor/liquid-glass/README.md: 引用的 dist/liquid-glass.esm.js 不存在
  [x] web/static/vendor/liquid-glass/README.md: 引用的 styles/liquid-glass.css 不存在
闸门检查失败：2 项。
```

- D1 ✅：`git ls-files -co --exclude-standard` 生效，扫描文件数 477 → 64，`venv/`(33)+`.venv/`(6)+`reports/`(210)+`.workbuddy/`(64) = 313 项一次性消失。
- D2 ✅：占位符（`YYYY`）、以点开头（`.card/.kpi-card`）、`:IDENT`（`web/app.py:_ASSET_FILES`）、模块属性（`x.KINDS`）、npm 包名（`@scope/pkg@1.2.0`）都不再报；`skin/tokens.css` 经 basename+后缀解析正确对上 `web/static/skin/tokens.css`。
- D3/D4 ✅：`tasks/_template/journal.md` 升回模板版后，本项目 T2 任务的 journal 直接通过（不再需要把 `→` 挪到同一行）。
- 首次实跑报的是 **17 项**：其中 **15 项是真实的历史断链**（`scripts/migrate_to_sqlite.py` 早已归档、新浪行情站 URL 里的 `hisdata_klc2` 被写成了仓库路径、`wecom_*` 模块 2026-09-20 已删、图标实际在 `web/static/icons/`），已按「指向归档真实路径 / 改成描述式」逐条修正；**2 项**是下面 D6 的写法问题。这条校验本身是有价值的，本项目留下了它，现在 0 违规。

## D6（建议，非本轮阻塞）：缺一个项目级的排除表

**本轮的 2 项不是上游的锅**，先把事实说清：`web/static/vendor/liquid-glass/README.md` 是**本项目自己写的
provenance 文档**（`bbe9023` 创建），不是上游包原样 vendored 的文件——上游包里那份是英文 README，
入库的只有 `liquid-glass.css` / `liquid-glass.esm.js` / `LICENSE-…` 三个文件（`docs/architecture.md`
2026-09-23 那条决策列的就是这三个，写的是「原样、禁改写」）。它表格的「来源」列写了包内布局
（`包内 dist/liquid-glass.esm.js`、`包内 styles/liquid-glass.css`），闸门按形状把这两个当真路径 ⇒ 2 项。
本轮把这两处改成「`dist` 目录下的 `liquid-glass.esm.js`」这种不带斜杠链的写法，闸门立即归零。**已解决。**

**但下面这个缺口是真的**：`check_links` 只有「精确匹配」和「basename 后缀匹配」两条放行路径，
**没有项目级排除表**。一旦某项目真的把第三方文档原样入库（vendored 的库 README/CHANGELOG 很常见，
它们里面的相对路径指的是**包内布局**，与宿主仓库无关），就只剩三条路，而每条都有代价：

1. 改第三方文件——破「原样 vendored」，`diff` 就无法判断上游升级了什么，且下次升级要手工重打；
2. 删掉它——丢版本/来源证据；
3. `.gitignore` 掉——已跟踪文件照样被 `ls-files --exclude-standard` 列出，无效。

同类工具早就有这个口子（`.markdownlintignore`、`.eslintignore`、`golangci-lint` 的 `skip-dirs`）。

### 建议 A：项目级排除表（推荐，约 15 行）

项目根放 `.gates-ignore`，每行一个 glob 或前缀，`#` 注释：

```
# 第三方 / vendored 文档：里面的相对路径指的是上游包内布局，不是本仓库
web/static/vendor/**
```

`check_links()` 在组装 `files` 的循环里加：

```sh
[ -f "$root/.gates-ignore" ] && ignore_globs="$(grep -v '^[[:space:]]*#' "$root/.gates-ignore" | sed '/^$/d')" || ignore_globs=""
# 每个文件名过一遍 case 匹配，命中则 continue
```

（也可以用 `git check-attr`/`.gitattributes` 标记，但新增一个 dotfile 比要求项目改 `.gitattributes` 更明确。）
建议**同时**对 `check_adr()` 与决策锚点提供同样入口——它们目前都不会误报，但一旦有人把 ADR 模板 vendored 进来就会再撞一次。

### 建议 B：内置跳过第三方目录（兜底，2 行）

不读配置文件，直接跳过路径中含 `vendor/` / `third_party/` / `node_modules/` 的 md：

```sh
case "$f" in */vendor/*|*/third_party/*|*/node_modules/*) continue ;; esac
```

优点：零配置；缺点：把「目录名叫 vendor」写死成规则，误伤面取决于命名习惯 ⇒ 建议 **B 打底 + A 兜精确**。

### 建议 C（不做也行，只是记录）

解析器可以把「首段不存在于任何已跟踪路径 + basename 恰好匹配一个文件」判为**提示**（`[!]` 而非 `[x]`）。
本项目这两条就属于这种：`dist/` 不存在、`liquid-glass.esm.js` 恰好唯一。
但提示仍然会让人去点开看，长期等于噪声，所以还是 A 更干净。

## 当前状态

本项目已经 0 违规（15 处真实断链修完，2 处写法改完），不阻塞同步与提交，所以 **A/B 都不做也不会挡路**——
它们只是「下一个真的 vendored 第三方文档的项目」会撞的墙。优先级由你定；本项目这边建议做 B（两行，
零配置），A 留作后续。

## D7（新，实测必现）`--staged` 看不到 gitignored 的产物 ⇒ 每次提交都被拦

**现象**：同一份文档在两种模式下结论相反：

```sh
$ sh scripts/check-gates.sh            # 全量
闸门检查通过。

$ sh scripts/check-gates.sh --staged   # 钩子跑的就是这个
  [x] AGENTS.md: 引用的 reports/backtest_report.md 不存在
  [x] docs/architecture.md: 引用的 reports/backtest_report.md 不存在
  [x] docs/commands.md: 引用的 reports/backtest_report.md 不存在
  [x] docs/pitfalls.md: 引用的 reports/backtest_report.md 不存在
闸门检查失败：4 项。
```

**根因**：`--staged` 把索引物化到一个临时目录再跑校验（`check-gates.sh` 的 `--staged` 分支），
而 `reports/` 是本项目 `.gitignore` 排除的**产物目录**（`backtest.py` 写出来的报告）。文件在真实工作区里存在，
所以全量模式 `[ -e "$ref" ]` 通过；临时目录里没有它，于是 `--staged` 恒红。

**为什么这不是「文档写错了」**：`reports/` 是本项目**规定要写**的产物目录（`backtest_report.md` 是脚本输出），
文档里提到它的产物路径是正当的；`.gitignore` 掉产物也是正当的。两者都对，冲突在校验器：**它把「仓库里有没有」
当成了「磁盘上有没有」，而 staged 模式的「磁盘」是合成出来的**。

**建议**（任一）：
1. `--staged` 分支里，`[ -e "$ref" ]` 失败时回退到**真实工作区**再判一次（只用于存在性，不读内容）；
2. 或对 `.gitignore` 命中的路径直接跳过（`git check-ignore -q -- "$ref"`）——副作用是「拼错名字的产物路径」也会被放过，
   所以推荐 1；
3. 顺带：`check_links` 的 `all` 列表在 staged 模式下应来自「索引 ∪ 工作区未忽略文件」，否则后缀解析也会漏。

**本项目当前对策**：把文档里的写法改成「`reports/` 下的 `backtest_report.md`」（不带斜杠链 ⇒ 不参与判定），
两种模式都绿。这不是好办法——它牺牲了可点击/可 grep 的路径形式来迁就 staged 模式的合成根。
