#!/usr/bin/env bash
#
# >>> usage
# 闸门检查器 —— 把「能机器判定的闸门」变成可执行检查。
#
#   scripts/check-gates.sh                 检查全仓库：tasks/ 下在飞的任务 + 全仓库的闸门 B
#                                          （tasks/_archive/ 跳过——见 tasks/README.md 的「归档」）
#   scripts/check-gates.sh --staged        检查索引内容（= 这次提交后的仓库状态；
#                                          任务目录只挑这次改动涉及的，pre-commit 钩子用）
#   scripts/check-gates.sh tasks/2026-08-04-add-login [...]
#
# 覆盖：
#   - 闸门 B：非 .md 文件里没有 [DEBUG- 残留（大小写不敏感；.md 是文档，会引用这个约定）。
#              排除 scripts/check-gates.sh 自身、node_modules/、二进制文件；
#              全量模式还排除 .gitignore 命中的本地文件（那是数据不是代码）
#   - plan.md：档位与类型已声明、相关文件 / 验证命令非空、步骤表非空、
#              确认清单至少一条且全勾、
#              没有残留模板提示「（从 prd.md 提取）」、测试 Seam 四行要么全填要么全空、
#              bug 任务的闸门 A 字段（含 ≥3 条排序假设）、bug-不可复现 必须声明 T3
#   - prd.md：验收标准非空且有条目；档位行填了就必须合法（不强制存在）
#   - journal.md：章节齐全（含雾区变化 / 一致性走查）、结束状态合法、验证结果有内容且不写「应该可以」、
#                 改动清单已填且没留模板占位符（src/... 或 <...>）、
#                 结束状态是 DONE / DONE_WITH_CONCERNS 时「主要提交」必须回填
#   - NN-*.md（切片）：类型与状态取值合法、档位与优先级取值合法、演示与完成标准非空、
#                      文件范围与被谁挡已填、确认清单至少一条且全勾、状态 completed 时必须回填主要提交；
#                      决策条目则要求问题 / 结论 / 依据三字段非空
#   - review.md（裁决单）：任务档位是 T2 / T3 时必须存在——plan.md / prd.md / 切片里
#                          **任何一处**声明了 T2/T3 就算，不依赖 plan.md 是否存在；
#                          章节齐全、固定点已填、逐条处理表非空、「审查者明确未判断的」不许留空
#   - 架构：docs/architecture.md 的模块表 vs 实际模块目录（双向，模块根默认 src）。
#          表里全是宽声明（模块根本身或它的祖先）时，全量自查会提示一句：新增子目录不会被检查。
#          模块目录 = 模块根下**非空**的直接子目录（含还没 git add 的），点目录和被
#          .gitignore 命中的除外；空目录不算——git 不跟踪空目录，声明它反而会卡住提交。
#          模块根本身不查存在性（空目录进不了 git，clone 之后它会消失）
#
#   - 规模底线（仅 --staged）：任务在模块根下**累计**改动的文件数 ≥ 4 时，必须有任务目录
#          声明 T2/T3。累计从 plan.md 进入历史的那次提交之前算起——按单次提交算的话，
#          把 T2 的活拆成两次提交就能溜过去。只查低报：T0 / T1 的档位声明不再等人确认，
#          这条是它的机械底线。只数模块根下的文件（文档、tasks/ 不计），阈值对齐 6 条信号。
#
# 不覆盖（判断性内容，留在 skills/ 里由人确认）：
#   双轴不合并、一次性脚本是否真删干净、命令是否真跑过、
#   档位**高报**（声明得比实际大），以及 6 条信号里的跨模块 / 动公开接口 /
#   行为变化 / 不可逆性四条——只有文件数一条两侧都查：≥ 4 必须在 T2/T3。
#   **任务是否真的收尾了**（journal.md 在提交之后才写，机器判断不了「这个任务结束了没有」）。
#
# 退出码：0 = 通过，1 = 有违规，2 = 用法错误。
# <<< usage

set -u

# 忽略 SIGPIPE。钩子是被 git 直接执行的：`git commit 2>&1 | head -1` 这类写法会让
# 读端提前退出，脚本写到第二行就吃 SIGPIPE，死在半路——实测 git 会**照常提交**
# （exit 0，闸门等于没跑）。把 SIGPIPE 改成写失败，脚本就能跑完并正常返回 1。
trap '' PIPE

violations=0

fail() { printf '  [x] %s\n' "$*"; violations=$((violations + 1)); }

# 提示，不是失败：计入输出，不影响退出码。用于「检查器当前覆盖不到」这类
# 需要人知道、但项目现状本身没错的情况。
note() { printf '  [!] %s\n' "$*"; }

# 用法说明就是文件头那段，用哨兵行圈出来 —— 写死行号会在加注释时漂移。
usage() {
    sed -n '/^# >>> usage$/,/^# <<< usage$/p' "${BASH_SOURCE[0]}" | sed '1d;$d' | sed 's/^# \{0,1\}//'
}

# ---------------------------------------------------------------- 各项检查
#
# 逐文件的判定逻辑整体在 check-gates.awk 里。为什么搬过去：本机起一个外部进程
# 约 27ms，而判定要做的字符串扫描（一个任务目录 40 来次、每次上百行）在 bash 里
# 约 13.7ms/120 行。两者叠加让全量自查变成分钟级；搬进 awk 后每个文件一次进程，
# 循环在 C 里跑。这里只负责挑文件、起进程、把违规行打出来并计数。

# 闸门 B：[DEBUG- 残留。
#   --staged：直接查索引（git grep --cached）。范围 = 这次提交后的仓库，和全量自查对齐；
#             不扫物化出来的临时树——那要先 checkout-index 把整棵树写到磁盘、再全扫一遍，
#             3000 文件 / 20MB 的仓库上 19s vs 0.67s。
#   全量：扫工作区（含未跟踪文件，那才是「全量」的意义）。
# -I 跳过二进制：grep 对二进制只会回一句「Binary file X matches」，没有行号也没有内容，
# 当成「调试标记残留」是误报（图片、fixture、快照都可能恰好含这几个字节）。
# 大小写不敏感：写 [debug-x] 同样是没清干净的调试埋点。
check_gate_b() {
    local staged="$1" root="$2" hits
    if [ "$staged" -eq 1 ]; then
        hits="$(git -C "$root" grep -I -i -n --cached -e '\[DEBUG-' -- \
            ':(exclude)*.md' ':(exclude)*check-gates.sh' \
            ':(exclude)node_modules/*' ':(exclude)*/node_modules/*' 2>/dev/null || true)"
    else
        # 全量扫工作区。优先用 git：`--untracked --exclude-standard` = 已跟踪 +
        # 未跟踪但**不含 .gitignore 命中的**。那些是本地数据/缓存，不是要提交的
        # 代码，扫出 [DEBUG- 只会误报（全量自查常年红，人就开始无视它）。
        # 不在 git 仓库里时退回 find。
        if git -C "$root" rev-parse --git-dir >/dev/null 2>&1; then
            hits="$(git -C "$root" grep --untracked --exclude-standard -I -i -n -e '\[DEBUG-' -- \
                ':(exclude)*.md' ':(exclude)*check-gates.sh' \
                ':(exclude)node_modules/*' ':(exclude)*/node_modules/*' 2>/dev/null || true)"
        else
            hits="$(find . -type f \
                ! -path './.git/*' ! -path '*/node_modules/*' \
                ! -name '*.md' ! -name 'check-gates.sh' \
                -exec grep -H -I -i -n '\[DEBUG-' {} + 2>/dev/null | sed 's|^\./||' || true)"
        fi
    fi
    if [ -n "$hits" ]; then
        printf '%s\n' "$hits" | while IFS= read -r line; do
            printf '  [x] 闸门 B: %s —— 调试标记残留\n' "$line"
        done
        violations=$((violations + $(printf '%s\n' "$hits" | wc -l)))
    fi
}

# 把 awk 的输出原样打印，并把行数计进 violations。
# 不用 wc：$() 会吃掉尾换行，「行数 = 换行数 + 1」容易写错；违规行本来就少，
# 循环数一遍最省事，也不起进程。
emit_violations() {
    [ -n "$1" ] || return 0
    printf '%s\n' "$1"
    local n=0 l
    while IFS= read -r l; do n=$((n + 1)); done <<< "$1"
    violations=$((violations + n))
}

# $1 = 判定种类（plan / prd / journal / slice / review），$2 = 文件
run_check() { emit_violations "$(awk -v kind="$1" -v fpath="$2" -f "$AWK_PROG" "$2")"; }

check_plan()    { run_check plan    "$1"; }
check_prd()     { run_check prd     "$1"; }
check_journal() { run_check journal "$1"; }
check_slice()   { run_check slice   "$1"; }

# 任务是否已经「开工」——决定 T2/T3 的裁决单要不要。
# 判据是「任务目录里除了 prd.md / journal.md / review.md 还有没有别的文件」，
# 而不是「有没有 plan.md 或 NN-*.md」：后者能被改名绕过去（切片叫 `01_a.md`、
# 或把档位只写在 prd 里再补一份 DONE 的 journal，就整条免检了）。
# journal 宣告 DONE 也算开工——任务都收尾了，不能再拿「还没写计划」当挡箭牌。
task_has_started() {
    local d="$1" p st
    # 目录里除了这三份「任何任务都可能有的」文件之外还有别的东西 → 已经开工。
    # 文件、目录、非 .md 都算：`handoff.md` 和 `research/` 同样说明这个任务在推进。
    for p in "$d"/*; do
        [ -e "$p" ] || continue
        case "${p##*/}" in prd.md|journal.md|review.md) ;; *) return 0 ;; esac
    done
    # 裁决单本身在（哪怕还空着）也算开工：它出现就说明任务已经走到 3.8 了。
    # 少了这一条，`prd + journal(状态空) + 空 review.md` 会因为「没开工」跳过
    # 整份裁决单检查——空裁决单直接放行。
    [ -f "$d/review.md" ] && return 0
    # journal 记了结束状态 → 任务至少跑到收尾了。任何非空状态都算，
    # 不能只认 DONE：`DONE_WITH_CONCERNS` / `BLOCKED` 同样是「跑过了」。
    [ -f "$d/journal.md" ] || return 1
    st="$(awk -v kind=status -v fpath="$d/journal.md" -f "$AWK_PROG" "$d/journal.md")"
    [ -n "$st" ]
}

# review.md（裁决单）：只有 T2 / T3 需要。
# 「文件在不在」的判断留在 bash —— 文件都不在的时候，awk 没机会开口。
check_review() {
    local d="$1" f="$d/review.md"
    # 还没开工的任务（3.2 落 prd、3.3 定档位与计划、3.8 出裁决单）不要求裁决单，
    # 否则 T2/T3 任务连「先把 prd 提交一次」都做不到。
    task_has_started "$d" || return 0
    if [ ! -f "$f" ]; then
        fail "$f: 这个任务的档位是 T2/T3，但缺 review.md（这两档的审查必须由独立子 agent 做，见 docs/agents/任务分级.md）"
        return
    fi
    run_check review "$f"
}

# 任务档位是否落在 T2/T3：plan.md / prd.md / 切片里任何一处声明了 T2/T3 就算。
# 不能只看 plan.md——档位也可能只写在 prd.md 或切片里；
# prd.md 的档位行也是同一个字段，只写在那里时同样得认。
task_is_high_tier() {
    local d="$1" f
    local files=()
    for f in "$d/plan.md" "$d/prd.md" "$d"/[0-9][-_]*.md "$d"/[0-9][0-9][-_]*.md; do
        [ -f "$f" ] && files+=("$f")
    done
    [ "${#files[@]}" -gt 0 ] || return 1
    [ "$(awk -v kind=tier -f "$AWK_PROG" "${files[@]}")" = "yes" ]
}

# 规模底线：声明的档位不能低于**数得出来**的改动量。
#
# 只查低报，不查高报：高报只是多一次审查，低报是拿「小改动」换免打扰——而 T0 / T1
# 的档位声明不再等人确认之后，低报就是「没人看」的唯一入口。
#
# 6 条信号里能机械化的只有文件数这一条：跨模块 / 动公开接口 / 行为变化 / 不可逆性
# 没有判据，仍然靠人看 diff。只数 $MODULE_ROOT 下的文件——量的是「改了多少代码」，
# 文档、tasks/ 不算。阈值对齐 docs/agents/任务分级.md 的 6 条信号表：文件数 ≥ 4 → T2 起。
#
# 只在 --staged 跑：全量自查没有「这次提交」这个基准。$3… = 本次改动涉及的任务目录。

# 数 $MODULE_ROOT 下从 $1（可为空 = 只看索引）到索引的改动文件数。
# -M：重命名算一次（和 `git diff --stat` 的文件数口径一致）；不认的话一次
# src/a → src/b 会被数成 2 个文件，小改动被误判成 T2。
count_code_changes() {
    local from="$1" root="$2" n=0 p range=()
    [ -n "$from" ] && range=("$from")
    while IFS= read -r p; do
        case "$p" in "${MODULE_ROOT%/}"/*) n=$((n + 1)) ;; esac
    done < <(git -c core.quotepath=false -C "$root" diff --cached --name-only -M \
             --diff-filter=ACMRD ${range[@]+"${range[@]}"} -- "${MODULE_ROOT%/}" 2>/dev/null)
    printf '%s' "$n"
}

check_scale() {
    local staged="$1" root="$2"; shift 2
    [ "$staged" -eq 1 ] || return 0
    local d base n max=0
    # 空树的 SHA：任务起点那个提交本身就是根提交时，`base^` 不存在，
    # 从空树算起才等同于「这个任务从零开始」。
    local empty_tree=4b825dc642cb6eb9a060e54bf8d69288fbee4904
    local cands=("$@")
    if [ "${#cands[@]}" -eq 0 ]; then
        # 这次提交没碰任何任务目录——最常见的是「计划先提交、代码后提交」。
        # 退回**所有在飞任务**（cwd 是索引物化的树，看到的就是提交后的状态）：
        # 不归属的话，一个纯代码提交就没人管，规模规则等于失效。
        for d in tasks/*/; do
            d="${d%/}"
            case "$d" in tasks/_template|tasks/_archive) continue ;; esac
            [ -d "$d" ] && cands+=("$d")
        done
    fi
    for d in ${cands[@]+"${cands[@]}"}; do
        task_is_high_tier "$d" && return 0
    done
    if [ "${#cands[@]}" -eq 0 ]; then
        # 一个任务目录都没有：只能量这次索引。够 T2 就是「连 plan 都没写」。
        n="$(count_code_changes "" "$root")"
    else
        # 按**任务**累计，不按单次提交：从 plan.md 进入历史的那次提交之前算起。
        # 只量本次 diff 的话，把 T2 的活拆成两次提交就能溜过去——而「一个任务
        # 对应一个主要提交」本来就是 tasks/README.md 的约定。
        for d in ${cands[@]+"${cands[@]}"}; do
            base="$(git -C "$root" log --diff-filter=A --format=%H -1 -- "$d/plan.md" 2>/dev/null)"
            if [ -n "$base" ]; then
                base="$(git -C "$root" rev-parse -q --verify "$base^" 2>/dev/null || printf '%s' "$empty_tree")"
            fi
            n="$(count_code_changes "$base" "$root")"
            [ "$n" -gt "$max" ] && max="$n"
        done
        n="$max"
    fi
    [ "$n" -ge 4 ] || return 0
    fail "这个任务的代码改动累计 $n 个 $MODULE_ROOT 下的文件，但没有声明 T2/T3 —— 按 docs/agents/任务分级.md 的 6 条信号，文件数 ≥ 4 就是 T2。把 plan.md 的档位升到 T2 并补 review.md（3.4 批准 + 3.8 独立审查）；如果这些文件分属别的任务，说明这个提交混了多个任务，按「一个任务一个提交」拆开"
}

# ---------------------------------------------------------------- 架构

# 模块根：这个目录的直接子目录就是模块。项目布局不同时改这里，
# 或用环境变量覆盖：MODULE_ROOT=app bash scripts/check-gates.sh
MODULE_ROOT="${MODULE_ROOT:-src}"

# `## 模块划分` 表第 2 列声明的路径，去掉反引号与尾斜杠。
# 表本身的解析在 check-gates.awk 的 kind=modules 里——和逐文件检查共用同一套
# 注释剥离，省得两处对「注释算不算内容」有不同看法。
declared_module_paths() {
    awk -v kind=modules -f "$AWK_PROG" "$1" | sort -u
}

# 目录与路径的**存在性**以工作区为准，不取索引：索引里没有「空目录」这个概念，
# 而 src/ 恰恰是空的 —— 只看索引会在首次提交时误报「src 不存在」。
# 表的内容取索引版本（见 check_architecture）。
# 模块根下的子目录。在**哪棵树**里找，由调用方决定：全量模式 cd 在仓库里，
# 暂存模式 cd 在索引物化出的临时树里 —— 各自看各自该看的那份内容。
# 只算**非空**目录：
#   - 空目录 git 根本不跟踪，声明它会被规则 1 判「声明了却不存在」，
#     不声明又违反规则 2 —— 两头堵死。它本来也不是模块。
# 点目录和被 .gitignore 命中的不算：src/.cache 既进不了提交，也不该进模块表。
arch_module_dirs() {
    local staged="$1" root="$2" d files
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        case "${d##*/}" in .*) continue ;; esac        # 点目录不是模块
        # 只算「clone 之后还会在」的目录：里面有 git 跟踪的、或者会被跟踪的
        # （未跟踪且没被 .gitignore 命中）文件。三类目录不算，它们声明不了：
        #   - 空目录：git 不跟踪空目录
        #   - 只装着被 ignore 的文件的目录（`src/logs/` 下只有 *.log）
        #   - 只含空子目录的目录
        # 声明它们会在 clone 里变成「声明了却不存在」，不声明又违反规则 2，两头堵死。
        # 目录列表来自 cwd（暂存模式是索引物化出的临时树），但「有没有内容」必须问
        # 真正的仓库：临时树不是 git 仓库，在那儿跑 git 会失败并静默返回空。
        if [ "$staged" -eq 1 ]; then
            files="$(git -C "$root" -c core.quotepath=false ls-files -c -- "$d" 2>/dev/null | head -n 1)"
        else
            files="$(git -C "$root" -c core.quotepath=false ls-files -co --exclude-standard -- "$d" 2>/dev/null | head -n 1)"
        fi
        [ -n "$files" ] && printf '%s\n' "$d"
    done < <(
        [ -d "$MODULE_ROOT" ] || exit 0
        find "$MODULE_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort -u
    )
}

arch_path_exists() { [ -e "$1/$2" ]; }

# 模块表 vs 实际目录，双向比对。防两件事：模块被改名 / 移动 / 删除而表没跟着改，
# 以及新加了模块目录却没进表。
#
# 覆盖语义：声明的路径覆盖它自己、它的祖先和它的后代。所以表里写 `src` 等于
# 「整个 src 当一个模块」，子目录不再逐个要求；写具体子目录，则新加的子目录必须进表。
check_architecture() {
    local staged="$1" root="$2"
    local doc="docs/architecture.md"

    if [ "$staged" -eq 1 ]; then
        # 暂存模式下 cwd 是索引物化出的整棵树，表进了索引就是索引版本
        # （所以「暂存了坏表」会被拦住）。没进索引（还没 commit 过、又没 add 过它）
        # 才退回工作区版本——否则会把「文件明明在仓库里」报成不存在。
        doc="$check_tree_tmp/docs/architecture.md"
        if [ ! -f "$doc" ]; then
            mkdir -p "$check_tree_tmp/docs"
            cp "$root/docs/architecture.md" "$doc" 2>/dev/null || rm -f "$doc"
        fi
    fi

    if [ ! -f "$doc" ]; then
        fail "docs/architecture.md 不存在"
        return
    fi

    local declared
    declared="$(declared_module_paths "$doc")"
    if [ -z "$declared" ]; then
        fail "docs/architecture.md 的「## 模块划分」表里没有声明任何模块"
        return
    fi

    # 规则 1：声明的路径必须真实存在。
    # 例外：模块根本身（及它的祖先）不查 —— `src/` 是空目录，git 不跟踪空目录，
    # clone 之后它就不在了，而 Phase 2 的模块表正要求写宽路径 `src`。
    # 这条要是报错，新 clone 的仓库会卡到「所有提交都过不去」。
    local p
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        case "$MODULE_ROOT/" in "$p/"*) continue ;; esac
        arch_path_exists "$root" "$p" \
            || fail "docs/architecture.md 声明了模块「$p」，但它不存在"
    done <<< "$declared"

    # 规则 2：$MODULE_ROOT 下的直接子目录必须被某个声明覆盖
    local d covered q
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        covered=0
        while IFS= read -r q; do
            [ -n "$q" ] || continue
            case "$q/" in "$d/"*) covered=1; break ;; esac
            case "$d/" in "$q/"*) covered=1; break ;; esac
        done <<< "$declared"
        [ "$covered" -eq 1 ] \
            || fail "「$d」是 $MODULE_ROOT 下的模块目录，但 docs/architecture.md 的模块表里没有它"
    done < <(arch_module_dirs "$staged" "$root")

    # 提示（不是失败）：表里全是宽声明时，规则 2 永远不触发——新增模块目录不会被检查。
    # 只在全量自查时报；--staged 每次提交都跑，不适合反复提示。
    if [ "$staged" -eq 0 ]; then
        local specific=0
        while IFS= read -r p; do
            [ -n "$p" ] || continue
            p="${p%/}"          # `src/` 与 `src` 是同一种声明，先去掉尾斜杠
            case "$p" in
                "$MODULE_ROOT"/*) specific=1; break ;;
            esac
        done <<< "$declared"
        if [ "$specific" -eq 0 ]; then
            note "模块表只声明了宽路径（$MODULE_ROOT 本身或它的祖先），所以「$MODULE_ROOT 下新增子目录」这条检查当前不会触发。"
            note "项目长大之后，把表拆成具体子模块（如 $MODULE_ROOT/auth、$MODULE_ROOT/billing），让这条检查生效。"
        fi
    fi
}

# ---------------------------------------------------------------- 主流程

main() {
    local staged=0
    local task_args=()

    while [ "$#" -gt 0 ]; do
        case "$1" in
            --staged) staged=1 ;;
            -h|--help) usage; exit 0 ;;
            --) shift; break ;;
            -*) printf '未知选项: %s\n' "$1" >&2; exit 2 ;;
            *) task_args+=("$1") ;;
        esac
        shift
    done
    while [ "$#" -gt 0 ]; do task_args+=("$1"); shift; done

    local root
    # 调用时的 cwd：命令行里点名的任务目录按它解析（脚本随后会 cd 到仓库根/临时树）。
    invoke_pwd="$(pwd)"
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    [ -n "$root" ] || root="$(cd "$(dirname "$0")/.." && pwd)"
    # git 给的是 `D:/…`，bash 的 pwd 给的是 `/d/…` —— 两种写法不能直接比前缀。
    # 统一成 bash 的写法，下面把点名路径折成仓库相对路径时才不会漏。
    root_pwd="$(cd "$root" && pwd)"

    # 判定逻辑在 check-gates.awk，与本脚本同目录。脚本自身始终取工作区版本
    # （钩子调的也是工作区的 scripts/check-gates.sh），所以要在 cd 进临时树之前解析。
    AWK_PROG="$(cd "$(dirname "$0")" && pwd)/check-gates.awk"
    if [ ! -f "$AWK_PROG" ]; then
        printf '找不到 %s —— 它与 check-gates.sh 必须放在一起\n' "$AWK_PROG" >&2
        exit 2
    fi

    if [ "$staged" -eq 1 ]; then
        # 内容必须取自索引。只拿 git diff --cached 的文件名、却读工作区，会在
        # 「已暂存的是坏内容、工作区已修好」时放行，反方向则误拦一次合法提交。
        #
        # 物化的是**整个索引**，不是这次改动的那几个文件：检查会问「某个这次没动的
        # 文件在不在」（T2/T3 的 review.md、plan.md 里的档位都是这种），只物化 diff
        # 会让这类问题一律得到「文件不存在」——该拦的漏掉，不该拦的拦住。
        #
        # 凡是**列文件名**的 git 调用都带 -c core.quotepath=false：这个设置存在
        # .git/config 里，不随 clone 走。少了它，clone 回来的仓库里中文名路径会被
        # 引号+八进制转义，case 匹配失配 —— 那些文件会静默逃过全部检查。
        #
        # 临时目录用全局变量：EXIT trap 在 main 返回之后才执行，那时 local 已经出作用域，
        # set -u 会把 "$check_tree_tmp" 当成未绑定变量，trap 失败 → 脚本整体非 0。
        check_tree_tmp="$(mktemp -d)"
        trap 'rm -rf "$check_tree_tmp"' EXIT
        # 物化失败必须硬停：否则会在一个空临时树里继续跑，每个任务目录都报
        # 「缺 plan.md / journal.md」——一堆假违规比一句报错难查得多。
        if ! git -C "$root" checkout-index -a --prefix="$check_tree_tmp/" 2>/dev/null; then
            printf '  [x] 无法把 git 索引物化到临时目录（checkout-index 失败），--staged 中止\n' >&2
            exit 2
        fi
        cd "$check_tree_tmp" || exit 2
    else
        cd "$root" || exit 2
    fi

    # 闸门 B：残留扫描。--staged 查索引，全量查工作区
    check_gate_b "$staged" "$root"

    # 架构：模块表 vs 实际目录。仓库状态不变量，两种模式都跑
    check_architecture "$staged" "$root"

    # 要检查哪些任务目录
    local dirs=()
    local d p rest
    if [ "${#task_args[@]}" -gt 0 ]; then
        # 参数按**调用时**的 cwd 解析。脚本后面会 cd 到仓库根，
        # 从子目录用相对路径点名（`cd docs && ../scripts/check-gates.sh ../tasks/x`）
        # 就会找不到——那时 ../tasks/x 是相对 docs 的，不是相对仓库根。
        local a rel
        for a in "${task_args[@]}"; do
            case "$a" in
                /*|[A-Za-z]:[/\\]*) rel="$a" ;;
                *) rel="$invoke_pwd/$a" ;;
            esac
            case "$rel" in
                "$root_pwd"/*) rel="${rel#"$root_pwd"/}" ;;
            esac
            case "$rel" in
                tasks/_template|tasks/_template/)
                    printf '%s\n' "跳过 $rel（模板，不是任务）"
                    continue ;;
            esac
            if [ -d "$rel" ]; then dirs+=("$rel"); else fail "找不到任务目录: $a"; fi
        done
    elif [ "$staged" -eq 1 ]; then
        # D 也要算：只删 review.md 的那次提交同样得查那个任务目录，
        # 不然「T2/T3 必须有 review.md」在删除路径上是空的。
        while IFS= read -r p; do
            case "$p" in
                # 归档过的任务在 tasks/_archive/<任务>/ 下，比在飞的深一层。
                # 改到它照样要查——「跳过」只针对全量自查，不是免检。
                tasks/_archive/*/*)
                    rest="${p#tasks/_archive/}"
                    dirs+=("tasks/_archive/${rest%%/*}") ;;
                # 归档**拍平**了（`git mv` 没先 mkdir 的后果）：文件直接躺在
                # `tasks/_archive/` 下面。全量自查会把它整个跳过，所以这里必须报
                # ——否则「把任务拍平」的那次提交正好是唯一能溜过去的提交。
                tasks/_archive/*.md)
                    fail "$p: tasks/_archive/ 顶层不该有文件——归档要 'mkdir -p tasks/_archive' 之后再 git mv，见 tasks/README.md 的「归档」" ;;
                tasks/*/*)
                    rest="${p#tasks/}"
                    d="tasks/${rest%%/*}"
                    case "$d" in tasks/_template) continue ;; esac
                    dirs+=("$d") ;;
            esac
        done < <(git -c core.quotepath=false -C "$root" diff --cached --name-only --diff-filter=ACMRD 2>/dev/null)
    else
        # `tasks/_archive/` 里**直接躺着 .md 文件**说明归档方式用错了：
        # `git mv tasks/x tasks/_archive/` 在 _archive 不存在时会把任务目录改名成
        # `_archive`，文件被拍平到这一层。拍平之后全量自查会把它整个跳过——
        # 那些文件从此不在任何全量检查的覆盖里（--staged 碰到才会查）。
        for f in tasks/_archive/*.md; do
            [ -f "$f" ] || continue
            fail "$f: tasks/_archive/ 顶层不该有文件——归档要 'mkdir -p tasks/_archive' 之后再 git mv，见 tasks/README.md 的「归档」"
            break
        done
        for d in tasks/*/; do
            [ -d "$d" ] || continue
            # _template 是模板；_archive 是已完成并归档的（tasks/ 只放在飞的）。
            # 归档目录不是一个任务目录，它的子目录也不在 tasks/*/ 这一层——
            # 但留着这句，免得以后有人往 _archive/ 顶层放文件时被当成任务。
            case "$d" in tasks/_template/|tasks/_archive/) continue ;; esac
            dirs+=("${d%/}")
        done
    fi

    # 规模底线：只在 --staged 有意义（要有「这次提交」这个基准）
    check_scale "$staged" "$root" ${dirs[@]+"${dirs[@]}"}

    # 去重后逐个检查
    local seen="|"
    for d in ${dirs[@]+"${dirs[@]}"}; do
        case "$seen" in *"|$d|"*) continue ;; esac
        seen="$seen$d|"
        local any=0
        if [ -f "$d/plan.md" ]; then
            printf '%s\n' "检查 $d/plan.md"
            check_plan "$d/plan.md"
            any=1
        fi
        if [ -f "$d/prd.md" ]; then
            printf '%s\n' "检查 $d/prd.md"
            check_prd "$d/prd.md"
            any=1
        fi
        # T2 / T3 的审查必须换人做，产出裁决单（见 docs/agents/任务分级.md）。
        # 独立于 plan.md 是否存在——档位也可能只写在切片里。
        if task_is_high_tier "$d"; then
            check_review "$d"
            any=1
        fi
        if [ -f "$d/journal.md" ]; then
            printf '%s\n' "检查 $d/journal.md"
            check_journal "$d/journal.md"
            any=1
        fi
        # 切片 / 决策条目：NN-*.md，NN 是 1–2 位数字（见 tasks/README.md）。
        # 同时认下划线分隔（`01_a.md`）——只认短横线的话，改个名字就整条免检了。
        # 两位数字的上限把 `2026-10-31-调研.md` 这类笔记排除在外（那是笔记不是切片）。
        local s
        for s in "$d"/[0-9][-_]*.md "$d"/[0-9][0-9][-_]*.md; do
            [ -f "$s" ] || continue
            printf '%s\n' "检查 $s"
            check_slice "$s"
            any=1
        done
        [ "$any" -eq 1 ] || printf '%s\n' "跳过 $d（还没有 plan.md / journal.md / NN-*.md）"
    done

    if [ "$violations" -eq 0 ]; then
        printf '闸门检查通过。\n'
        return 0
    fi
    printf '闸门检查失败：%d 项。\n' "$violations"
    return 1
}

main "$@"
