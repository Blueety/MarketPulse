# 闸门检查的判定逻辑。规则与消息的说明见 check-gates.sh 里的 check_*。
#
# 为什么判定在 awk 里而不是 bash：本机起一个外部进程约 27ms，而判定本身要做的
# 字符串扫描（一个任务目录 40 来次、每次上百行）在 bash 里约 13.7ms/120 行。
# 两者叠加让全量自查变成分钟级。搬进 awk 之后每个文件一次进程，循环在 C 里跑。
#
# 用法：
#   awk -v kind=plan|prd|journal|slice|review -v fpath=<路径> -f check-gates.awk <文件>
#       输出 `  [x] <路径>: <消息>` 行（没有违规就什么都不输出）
#   awk -v kind=tier -f check-gates.awk <plan.md> <切片...>
#       输出 yes / no —— 任务档位是否落在 T2/T3
#
# 注意：所有函数的局部变量都必须写在参数表里（awk 没有别的局部变量语法），
# 漏写会变成全局变量，在多次调用之间串味。

BEGIN {
    FS = "\n"

    JOURNAL_SECS[1]  = "目标"
    JOURNAL_SECS[2]  = "主要提交"
    JOURNAL_SECS[3]  = "改动文件清单"
    JOURNAL_SECS[4]  = "验证结果"
    JOURNAL_SECS[5]  = "遇到的问题"
    JOURNAL_SECS[6]  = "下次注意什么"
    JOURNAL_SECS[7]  = "涉及的 ADR"
    JOURNAL_SECS[8]  = "下一步"
    JOURNAL_SECS[9]  = "雾区变化"
    JOURNAL_SECS[10] = "一致性走查"
    JOURNAL_SECS[11] = "结束状态"

    REVIEW_SECS[1] = "审查范围"
    REVIEW_SECS[2] = "审查者原文"
    REVIEW_SECS[3] = "逐条处理"
    REVIEW_SECS[4] = "审查者明确未判断的"
    REVIEW_SECS[5] = "结论"

    # 断链检查只认这些扩展名。见 emit_link 里的说明。
    _n = split("md sh awk bash ps1 cmd py pyi js mjs cjs ts tsx jsx json jsonc yaml yml toml ini cfg conf css scss sass less html htm vue svelte astro go rs java kt kts c h cc cpp hpp cs fs rb php pl lua sql txt csv tsv lock xml svg png jpg ico", _e, " ")
    for (_i = 1; _i <= _n; _i++) LINK_EXT[_e[_i]] = 1
}

# ---------------------------------------------------------------- 读入

{
    line = $0

    # kind=adr / kind=links 要一次扫多个文件（互链要跨文件判、断链要一次跑完），
    # 记下每个文件的起止：L[] 是跨文件累积的，不留边界就会把 A 的行算到 B 头上。
    if ((kind == "adr" || kind == "links") && FNR == 1) {
        FIDX++; FSTART[FIDX] = NL + 1; FNAME[FIDX] = FILENAME
    }

    # 剥掉 markdown 注释（含跨行）。模板注释里会出现「应该可以」
    # 「（从 prd.md 提取）」这类字样，不剥掉的话会误报。
    while (1) {
        if (incom) {
            p = index(line, "-->")
            if (p == 0) { line = ""; break }
            line = substr(line, p + 3); incom = 0
        } else {
            p = index(line, "<!--")
            if (p == 0) break
            head = substr(line, 1, p - 1)
            rest = substr(line, p + 4)
            q = index(rest, "-->")
            if (q == 0) { line = head; incom = 1; break }
            line = head substr(rest, q + 3)
        }
    }
    gsub(/\t/, " ", line)

    L[++NL] = line
}

END {
    # 档位：plan.md / prd.md / 切片里**任何一处**声明了 T2/T3 就算。
    # 不能只看第一条声明：同一文件里先写 T1、后面补一条 T3 也算；多个切片里
    # 最后一个才是 T3 也算。只看第一条会让这类任务躲过 review.md 的强制检查。
    # （awk 的变量是全局的，`awk plan.md 01-a.md` 一次进程跑多个文件——
    #  所以这里不能有「找到就停」的状态，否则只有第一个文件会被看到。）
    # 放在 END 里而不是读行循环里：要等整个文件读完才能看「值换行写在下一行」。
    if (kind == "tier") {
        for (i = 1; i <= NL; i++) {
            if (L[i] !~ /^[[:space:]]*[-*+][[:space:]]+\*\*/ || index(L[i], "档位") == 0) continue
            v = field_value_of(L[i])
            if (v == "") {
                j = i
                while (++j <= NL) {
                    if (L[j] ~ /^[[:space:]]*[-*+][[:space:]]+\*\*/) break
                    if (L[j] ~ /^[[:space:]]*#/) break
                    if (L[j] !~ /^[[:space:]]*$/) { v = L[j]; break }
                }
            }
            if (token_of(v) ~ /^T[23]/) high = 1
        }
        print (high ? "yes" : "no"); exit
    }
    if (kind == "status")  { print md_token("结束状态"); exit }
    if (kind == "links")   { links_dump(); exit }
    if (kind == "adr")     { adr_check(); exit }
    if (kind == "modules") { modules_dump(); exit }
    if      (kind == "plan")    plan_check()
    else if (kind == "prd")     prd_check()
    else if (kind == "journal") journal_check()
    else if (kind == "slice")   slice_check()
    else if (kind == "review")  review_check()
}

# ---------------------------------------------------------------- 输出

function V(msg) { print "  [x] " fpath ": " msg }

# ---------------------------------------------------------------- 查询

# 标题级别（`## x` → 2，`### x` → 3）；不是标题返回 0。
# 只认 2 级及以上：`# 大标题` 在任务文件里当文档标题用，不当节。
function heading_level(s,   n) {
    if (substr(s, 1, 1) != "#") return 0
    n = 0
    while (substr(s, n + 1, 1) == "#") n++
    if (n < 2) return 0
    if (substr(s, n + 1, 1) !~ /[[:space:]]/) return 0
    return n
}

# 一个标题开一节（`### <标题>` 也算——模板不一定只用两级），
# 到下一个**同级或更高级**的标题为止。取第一个标题匹配 want 的（见 title_matches）。
# 这样 `### 步骤` 能被当成节，而节里更深的 `###` 子标题不会把它切断。
# 标题是否就是 want（或 want 后面紧跟括号/冒号/空格，如 `## 确认（可选）`）。
# 用「前缀 + 分隔符」而不是「含 want」：后者会让 `## 待确认事项` 顶替 `## 确认`，
# 一个已勾项的干扰节就能把真正的确认节挡在外面。
function title_matches(title, want,   rest) {
    if (title == want) return 1
    # 全程按**字节**比：`index` 是字节比较，`length(want)+1` 在两种 locale 下也都
    # 落在 want 之后（字节数一致）。用 substr(title, 1, length(want)) 那种字符切片
    # 在非 UTF-8 locale 下会把「确」字切一半，`## 确认（可选）` 就匹配不上了
    # （登录 shell 里 locale 正常，`env -u LANG` 才露馅）。
    if (index(title, want) != 1) return 0
    rest = substr(title, length(want) + 1)
    return (index(rest, " ") == 1 || index(rest, "（") == 1 || index(rest, "(") == 1 \
            || index(rest, ":") == 1 || index(rest, "：") == 1)
}

function md_section(want,   i, insec, lvl, hl, n, t) {
    n = 0; insec = 0; lvl = 0
    for (i = 1; i <= NL; i++) {
        hl = heading_level(L[i])
        if (hl > 0) {
            if (insec && hl <= lvl) break
            if (!insec) {
                t = L[i]
                sub(/^#+[[:space:]]+/, "", t)
                sub(/[[:space:]]+$/, "", t)
                if (title_matches(t, want)) { insec = 1; lvl = hl }
            }
            continue
        }
        if (insec) S[++n] = L[i]
    }
    return n
}

# 小节正文拼成一个字符串，尾部换行去掉（等价于 shell 里 `$( )` 的剥尾换行）。
function section_text(want,   n, i, out) {
    n = md_section(want)
    out = ""
    for (i = 1; i <= n; i++) out = out (i > 1 ? "\n" : "") S[i]
    sub(/\n+$/, "", out)
    return out
}

# 是否存在匹配 want 的标题行（任意级别，`## 步骤` 和 `### 步骤` 都算）。
# 和 md_section 用同一个 title_matches——两边口径不一致时，
# 「有没有这个节」和「这个节里写了什么」会各看各的。
function has_section(want,   i, hl, t) {
    for (i = 1; i <= NL; i++) {
        hl = heading_level(L[i])
        if (hl == 0) continue
        t = L[i]
        sub(/^#+[[:space:]]+/, "", t)
        sub(/[[:space:]]+$/, "", t)
        if (title_matches(t, want)) return 1
    }
    return 0
}

# 整份文件（剥掉注释后）里是否出现过这段字面文本。
function has_text(want,   i) {
    for (i = 1; i <= NL; i++) if (index(L[i], want) > 0) return 1
    return 0
}

# `- **标签**: 值` 行的原文（第一次出现）。没找到返回空串。
# `-` / `*` / `+` 三种列表符号都认：只认前两种的话，用 `+` 写的档位会被判「未声明」，
# 而 task_is_high_tier 也看不见它——T2/T3 任务就此躲过 review.md。
function field_raw(lbl,   i) {
    for (i = 1; i <= NL; i++)
        if (L[i] ~ /^[[:space:]]*[-*+][[:space:]]+\*\*/ && index(L[i], lbl) > 0) return L[i]
    return ""
}

# 字段行冒号后的值。全角冒号先归一化——**必须认**：认不出的话 `sub` 不生效，
# 整行被当成值返回，所有 field_filled 检查会一律判「已填」（fail-open）。
function field_value_of(r,   v) {
    v = r
    gsub(/：/, ":", v)
    sub(/^[^:]*:[[:space:]]*/, "", v)
    return v
}
function field_value(lbl,   i, v) {
    for (i = 1; i <= NL; i++) {
        if (L[i] !~ /^[[:space:]]*[-*+][[:space:]]+\*\*/ || index(L[i], lbl) == 0) continue
        v = field_value_of(L[i])
        if (v != "") return v
        # 同行是空的：值可能换行写在下一行（`- **档位**:` 换行再写 `` `T3` — … ``）。
        # 不认的话档位判「未声明」，而 task_is_high_tier 也就看不见它——
        # T2/T3 任务会因此躲过 review.md。遇到下一个字段行或标题行就停。
        while (++i <= NL) {
            if (L[i] ~ /^[[:space:]]*[-*+][[:space:]]+\*\*/) return ""
            if (L[i] ~ /^[[:space:]]*#/) return ""
            if (L[i] !~ /^[[:space:]]*$/) return L[i]
        }
        return ""
    }
    return ""
}

# 取值的 token：有反引号就取**第一对反引号里的第一个词**，没写反引号就取第一个词。
# 不回退的话 `- **档位**: T2`（忘了反引号）会被报成「档位未声明」，
# 而且 T2/T3 的任务会因此躲过 review.md 的强制检查。
# 反引号里再切一个词：模板给的形状是 `` `T1 — 2 文件 / 0 调用方 / …` ``
# —— 整段都在反引号里，不切的话整行都会被当成档位值。
# 切词用 [ \t] 而不是 [[:space:]]：本机 locale 下 0xA0 也算空白，
# 而中文（UTF-8 里含 0xA0 字节的字）会被从中间切坏。
function token_of(v,   s, p) {
    s = v
    sub(/^[ \t]+/, "", s)      # 值可能换行写在下一行，带着缩进进来
    if (substr(s, 1, 1) == "`" && index(substr(s, 2), "`") > 0) {
        s = substr(s, 2)
        s = substr(s, 1, index(s, "`") - 1)
        sub(/^[ \t]+/, "", s)
    }
    p = match(s, /[ \t]/)
    return p ? substr(s, 1, p - 1) : s
}
function md_token(lbl) { return token_of(field_value(lbl)) }

# 字段行及其后续块（到下一个 `- **` 标签行或标题行为止）。返回行数，存进 B[]。
function field_block(lbl,   i, n, found) {
    n = 0; found = 0
    for (i = 1; i <= NL; i++) {
        if (L[i] ~ /^[[:space:]]*[-*+][[:space:]]+\*\*/) {
            if (found) break
            if (index(L[i], lbl) > 0) { found = 1; B[++n] = L[i]; continue }
        } else if (L[i] ~ /^[[:space:]]*#/) {
            if (found) break
        }
        if (found) B[++n] = L[i]
    }
    return n
}
function field_block_text(lbl,   n, i, out) {
    n = field_block(lbl)
    out = ""
    for (i = 1; i <= n; i++) out = out (i > 1 ? "\n" : "") B[i]
    sub(/\n+$/, "", out)
    return out
}

# 字段块**去掉字段行本身**之后的部分。要数条目时用这个：字段行自己也是
# `- **…**`，混进去会被当成一条。
function field_block_body(lbl,   n, i, out) {
    n = field_block(lbl)
    out = ""
    for (i = 2; i <= n; i++) out = out (i > 2 ? "\n" : "") B[i]
    sub(/\n+$/, "", out)
    return out
}

# 整行只是「还没填」的标记。要精确，不能宽：
# `（npm test）` 这种全角括号里装着真内容是**合法值**，判成占位符会卡住用户；
# 反过来 `TODO` / `(待补)` / 单个 `-` 是最常见的偷懒写法，得算没填。
# 括号里的字用 `（` `）` 当字面量而不是塞进方括号——方括号是按字节比的，
# 多字节字符放进去会匹配到半个字。
function is_placeholder(s,   inner) {
    if (s == "（）" || s == "()") return 1
    # 括号里只有「占位符类」的字才算没填。**必须锚定整段**：
    # 用子串匹配的话 `（占位符长度计算）`、`（placeholder 属性生效）` 这种真内容
    # 会被判成空；反过来 `（TODO）` `（待办）` `（未填）` 这种偷懒写法又得算空。
    # 多字节字符用**分支**（`（|(`）而不是方括号——方括号是按字节比的，
    # 多字节字符放进去只能匹配到它的第一个字节。
    if (s ~ /^（.*）$/ || s ~ /^\(.*\)$/) {
        inner = s
        # 多字节字符只能用**字面量**匹配，不能进方括号：方括号是按字节比的，
        # `[（(]` 只会吃掉「（」的第一个字节，剩下的两个字节留在 inner 里，
        # 后面那条锚定的正则就永远匹配不上（C locale 下才露馅）。
        sub(/^（/, "", inner)
        sub(/^\(/, "", inner)
        sub(/）$/, "", inner)
        sub(/\)$/, "", inner)
        gsub(/[[:space:]]/, "", inner)
        inner = tolower(inner)
        return (inner ~ /^(占位|占位符|待补|待填|待定|待办|未填|未完成|placeholder|todo|tbd|xxx|na|n\/a|…|-+|这里写.*|填写.*)$/)
    }
    if (tolower(s) == "todo" || tolower(s) == "tbd" || s == "N/A" || tolower(s) == "na" || tolower(s) == "xxx") return 1
    if (s == "待办" || s == "未填" || s == "待补") return 1
    if (s == "-" || s == "--" || s == "—" || s == "…" || s == "...") return 1
    return 0
}

# 字段是否有实质内容：同行冒号后非空（或换行写在下一行），
# 或后续块里去掉注释/空行/纯符号后还有东西。
# 两种「看着有内容其实没有」的值也算空：
#   - 空反引号：模板里的 `- **X**: \`\``
#   - 只剩模板提示：`- **X**: （占位）`
function field_filled(lbl,   s, n, j, l, body) {
    s = field_value(lbl)
    gsub(/[[:space:]]/, "", s)
    gsub(/`/, "", s)
    if (s == "") { }
    else if (is_placeholder(s)) { }
    else return 1

    n = field_block(lbl)
    body = ""
    for (j = 2; j <= n; j++) {          # 跳过字段行本身（同 tail -n +2）
        l = B[j]
        gsub(/<!--.*-->/, "", l)
        sub(/^[[:space:]]*[-*+][[:space:]]*/, "", l)
        gsub(/[[:space:]]/, "", l)
        if (l == "") continue
        if (is_placeholder(l)) continue  # 整行只是模板提示（占位）→ 不算内容
        if (l ~ /^`+$/) continue         # 整行只是空反引号 → 不算内容
        body = body l
    }
    return (body != "")
}

# 表格数据行数（跳过表头与分隔行）。skip = 跳过前几个单元格再判断：
# 步骤表的 `#` 列是自动编号，不跳过的话「模板原封不动」也会被算成有内容。
function table_rows(text, skip,   n, i, seen, cells, nf, j, c, cnt) {
    n = split(text, ROWS, "\n")
    cnt = 0; seen = 0
    for (i = 1; i <= n; i++) {
        # 允许最多 3 个前导空格：CommonMark 里缩进 3 格的表格仍是表格。
        if (ROWS[i] !~ /^[[:space:]]*\|/) continue
        seen++
        if (seen <= 2) continue
        nf = split(ROWS[i], cells, "|")
        for (j = 2 + skip; j < nf; j++) {
            c = cells[j]; gsub(/[[:space:]]/, "", c)
            if (c != "") { cnt++; break }
        }
    }
    return cnt
}

# 未勾选的 `- [ ]`。跳过代码围栏内的行：把复选框包进 ``` 里就能同时骗过
# 「还有几项没勾」和「一条确认项都没有」——两条都只看行首，看不出那是个代码块。
# want: 0 = 只数没勾的，1 = 勾了没勾都数。
function count_checkboxes(text, want,   n, i, c, fence, marks) {
    n = split(text, ROWS, "\n"); c = 0; fence = 0; marks = 0
    for (i = 1; i <= n; i++)
        if (ROWS[i] ~ /^[[:space:]]*(```|~~~)/) marks++
    # 围栏数量是奇数说明**有一个没闭合**。这时不能把后面的行都当成代码块里的
    # ——那正好是一条「把没勾的项藏进未闭合围栏」的绕过路径。整份文档都不跳。
    if (marks % 2 == 0) {
        for (i = 1; i <= n; i++) {
            if (ROWS[i] ~ /^[[:space:]]*(```|~~~)/) { fence = !fence; continue }
            if (fence) { ROWS[i] = "" }      # 抹掉围栏内的行，下面的判定一视同仁
        }
    }
    for (i = 1; i <= n; i++) {
        if (want) { if (ROWS[i] ~ /^[[:space:]]*[-*+][[:space:]]+\[[ xX]\]/) c++ }
        else      { if (ROWS[i] ~ /^[[:space:]]*[-*+][[:space:]]+\[[[:space:]]?\]/) c++ }
    }
    return c
}

# 项目符号或编号列表项。编号同时认 `1.` 和中文顿号 `1、`——只认半角点的话，
# 用顿号编号的验收标准会被判成「没有条目」。
function count_listitems(text,   n, i, c) {
    n = split(text, ROWS, "\n"); c = 0
    for (i = 1; i <= n; i++)
        if (ROWS[i] ~ /^[[:space:]]*([-*+][[:space:]]+|(（|\()?[0-9]+([.]|、|\)|）)[[:space:]]*)[^[:space:]]/) c++
    return c
}

# 结果条目：列表项，但**不是标签行**——`- 未运行的检查及原因:` 这种以冒号结尾的是
# 让人去填的小标题，不是一条结果。只看「有没有列表项」会被模板里这一行骗过去。
function count_result_items(text,   n, i, c) {
    n = split(text, ROWS, "\n"); c = 0
    for (i = 1; i <= n; i++) {
        if (ROWS[i] !~ /^[[:space:]]*([-*+][[:space:]]+|(（|\()?[0-9]+([.]|、|\)|）)[[:space:]]*)[^[:space:]]/) continue
        if (ROWS[i] ~ /(:|：)[[:space:]]*$/) continue
        # 模板自带的固定字段不是「验证结果」：`- 返工: 0 次` 只要照抄模板就会出现，
        # 算进来的话这一节永远非空，「没有一行结果」这条检查就废了。
        if (ROWS[i] ~ /^[[:space:]]*[-*+][[:space:]]*(返工|被打回)[[:space:]]*[:：]/) continue
        c++
    }
    return c
}

# 列表条目数：编号（`1. xxx`）和项目符号（`- xxx`）都算。
# 排序假设那一栏只关心「写了几条」，不该因为用了项目符号就判成 0 条
# ——prd.md 的「验收标准」两种都收，两处口径要一致。
function count_items(text,   n, i, c) {
    n = split(text, ROWS, "\n"); c = 0
    for (i = 1; i <= n; i++)
        if (ROWS[i] ~ /^[[:space:]]*((（|\()?[0-9]+([.]|、|\)|）)[[:space:]]*|[-*+][[:space:]]+)[^[:space:]]/) c++
    return c
}

# ---------------------------------------------------------------- 模块表

# `## 模块划分` 表第 2 列声明的路径，去掉反引号与尾斜杠。
function modules_dump(   n, i, cells, nf, p, line, npaths, k, seg, prev_dir) {
    n = md_section("模块划分")
    for (i = 1; i <= n; i++) {
        if (S[i] !~ /^[[:space:]]*\|/) continue
        # markdown 表格里 `\|` 是**转义竖线**，不是列分隔。直接 split 会把它劈成两格，
        # 于是「模块名」里出现竖线时路径格整个前移：拿到的路径是个词，且真正的路径
        # 不再被检查。先用哨兵占住，切完再还原。
        line = S[i]
        gsub(/\\\|/, "\002", line)
        nf = split(line, cells, "|")
        if (nf < 3) continue
        p = cells[3]
        gsub(/\002/, "\\|", p)
        gsub(/`/, "", p)
        sub(/^[[:space:]]+/, "", p); sub(/[[:space:]]+$/, "", p)
        sub(/\/+$/, "", p)
        if (p == "" || p == "路径" || p ~ /^-+$/) continue
        # 一格可以写多个路径，用「空格 + 空格」分隔（`c++`、`a+b` 这类名字不能被切）。
        # 靠后的段如果自己不带 `/`，按**上一段所在的目录**解析——
        # `…/settings/lastSession.ts + closeToTray.ts` 的另一半在同一个目录里。
        npaths = split(p, PARTS, /[[:space:]]+\+[[:space:]]+/)
        prev_dir = ""
        for (k = 1; k <= npaths; k++) {
            seg = PARTS[k]
            gsub(/^[[:space:]]+/, "", seg); gsub(/[[:space:]]+$/, "", seg)
            sub(/\/+$/, "", seg)
            if (seg == "") continue
            if (index(seg, "/") == 0 && prev_dir != "") seg = prev_dir "/" seg
            print seg
            prev_dir = seg
            sub(/\/[^\/]*$/, "", prev_dir)
        }
    }
}

# ---------------------------------------------------------------- plan.md

function plan_check(   tier, type, n, filled, hy, t) {
    if (!has_section("任务概要")) { V("缺「## 任务概要」一节"); return }

    tier = md_token("档位")
    if (tier == "")                    V("档位未声明（找不到 `- **档位**:` 行）")
    else if (index(tier, "T?") > 0)    V("档位仍是模板占位符 T?")
    else if (tier !~ /^T[0-3]$/)       V("档位 '" tier "' 不是 T0–T3")

    type = md_token("类型")
    if (type == "") V("类型未声明（找不到 `- **类型**:` 行）")
    else if (type != "加功能" && type != "重构" && type != "bug-可复现" && type != "bug-不可复现")
        V("类型 '" type "' 不在 {加功能, 重构, bug-可复现, bug-不可复现}")

    if (!field_filled("目标")) V("「目标」为空")
    if (!field_filled("相关文件")) V("「相关文件」为空")
    if (!field_filled("验证命令")) V("「验证命令」为空")

    if (table_rows(section_text("步骤"), 1) == 0) V("「## 步骤」表里没有任何步骤")

    # 确认清单：这一节必须存在、里面至少有一条确认项、且不能有未勾的
    if (!has_section("确认")) V("缺「## 确认」一节")
    else {
        t = section_text("确认")
        if (count_checkboxes(t, 1) == 0)
            V("「## 确认」里一条确认项都没有（照模板抄 6 条；确实不需要就写明为什么）")
        n = count_checkboxes(t, 0)
        if (n != 0) V("「## 确认」还有 " n " 项没勾")
    }

    # 「（从 prd.md 提取）」这类模板提示现在放在注释里（读入时已被剥掉），
    # 所以「目标」只会因为真的没写才为空——上面那条 field_filled 就是这么来的。

    # 测试 Seam：要么整节不填，要么四行都填
    filled = 0
    if (field_filled("要测的 seam"))        filled++
    if (field_filled("公开接口是什么"))      filled++
    if (field_filled("错误与边界"))          filled++
    if (field_filled("为什么选这个 seam"))   filled++
    if (filled > 0 && filled < 4) V("「## 测试 Seam」只填了 " filled "/4 行")

    # 类型轴 = bug：闸门 A 必填。只卡下界——写超过 5 条假设不是缺陷。
    if (type ~ /^bug-/) {
        if (!field_filled("能变红的命令")) V("闸门 A —— 「能变红的命令」为空")
        if (!field_filled("已实跑的输出")) V("闸门 A —— 「已实跑的输出」为空")
        if (!field_filled("是否已最小化")) V("闸门 A —— 「是否已最小化」为空")
        hy = count_items(field_block_body("排序假设"))
        if (hy < 3) V("闸门 A —— 排序假设只有 " hy " 条（至少要 3 条）")
    }

    # 任务分级.md：bug 不可复现强制 T3
    if (type == "bug-不可复现" && tier !~ /^T3$/)
        V("类型 bug-不可复现 必须声明 T3（现在写的是 '" tier "')")
}

# ---------------------------------------------------------------- prd.md

# Spec 轴的基准。只卡两件机器能判的事：
#   1. 「## 验收标准」非空——AGENTS.md 的 Done Means 和 pre-review 的 Spec 轴
#      都拿它当指涉对象，缺了它 Spec 轴悬空。
#   2. 档位行填了就必须是 T0–T3。**不要求它必须填**——prd.md 在 Step 3.2 落笔、
#      档位在 3.3 才定，强制存在会在中途提交时误报。这里只抓「模板占位符没删」和写错值。
function prd_check(   tier, acc) {
    tier = md_token("档位")
    if (tier == "")                 { }
    else if (index(tier, "T?") > 0) V("档位仍是模板占位符 T?")
    else if (tier !~ /^T[0-3]$/)    V("档位 '" tier "' 不是 T0–T3")

    acc = section_text("验收标准")
    if (!has_section("验收标准")) V("缺「## 验收标准」一节（Spec 轴和 Done Means 都拿它当基准）")
    else if (count_listitems(acc) == 0 && table_rows(acc, 0) == 0)
        V("「## 验收标准」里没有条目（列表或表格都行；节里只剩注释不算）")
}

# ---------------------------------------------------------------- journal.md

function journal_check(   i, missing, end_state, verify, changed) {
    missing = 0
    for (i = 1; i <= 11; i++) {
        if (!has_section(JOURNAL_SECS[i])) {
            V("缺「## " JOURNAL_SECS[i] "」一节")
            missing++
        }
    }
    if (missing > 0) return

    # 「结束状态」没填 = 这个任务还没收尾（journal.md 按设计在 Step 3.11 才写，
    # 而 Step 3.9 的 `git add .` 会先把一份空模板扫进提交）。这时不查收尾字段——
    # 和 prd.md 的档位同理：填了才校验，没填不算违规。
    if (!field_filled("结束状态")) return

    # 「主要提交」与「结束状态」绑定：BLOCKED / NEEDS_CONTEXT 的任务可能一次提交都没有
    end_state = md_token("结束状态")
    if (end_state == "DONE" || end_state == "DONE_WITH_CONCERNS") {
        if (!field_filled("主要提交"))
            V("结束状态是 " end_state "，但「主要提交」没回填（写工作提交的 SHA，见 tasks/README.md）")
    } else if (end_state == "BLOCKED" || end_state == "NEEDS_CONTEXT") {
        # 卡住 / 缺信息的任务允许零提交
    } else {
        V("「结束状态」是 '" end_state "'，不在 {DONE, DONE_WITH_CONCERNS, BLOCKED, NEEDS_CONTEXT}")
    }

    verify = section_text("验证结果")
    if (table_rows(verify, 0) == 0 && count_result_items(verify) == 0)
        V("「## 验证结果」里没有一行结果（表格或项目符号列表都行）")
    if (index(verify, "应该可以") > 0) V("「## 验证结果」里出现「应该可以」——要贴实跑的命令与输出")

    changed = section_text("改动文件清单")
    if (table_rows(changed, 0) == 0) V("「## 改动文件清单」表里没有一行")
    # 只认「整个单元格就是一个占位符」的行。之前是「出现任何 <...> 就算」——
    # 那样 `Map<string, number>`、`<script>`、URL 里的尖括号都会被误判成残留占位符。
    if (changed ~ /src\/(\.|．)(\.|．)(\.|．)/ || changed ~ /src\/…/ \
        || changed ~ /\|[[:space:]]*`?<[^>]*>`?[[:space:]]*\|/)
        V("「## 改动文件清单」还留着模板占位符（src/... 或 <...>）")

    check_next_notes()
}

# 「下次注意什么」每条都要有去向。没有去向的提醒随任务归档就死了：`tasks/_archive/`
# 在全量自查里是跳过的，`self-audit` 走查的也是文档一致性、不读历史 journal。
# 这条只判**形式**（有没有写出口），不判内容质量——「写得对不对」机器管不了，
# 判质量只会退化成勾选表演。
#
# 按**条目**判，不按行判：一个条目可以写两行——先说要记住什么，箭头另起一行。
# 模板注释里给的就是这种排版，按行判会让模板自己的示例判红。
function check_next_notes(   n, i, l, txt, item, item_line, have_item) {
    if (!has_section("下次注意什么")) return
    txt = section_text("下次注意什么")
    n = split(txt, NN_LINES, "\n")
    have_item = 0
    item = ""; item_line = ""
    for (i = 1; i <= n; i++) {
        l = NN_LINES[i]
        gsub(/\r/, "", l)
        if (l ~ /^[ \t]*$/ || l ~ /^[ \t]*(```|~~~)/) continue

        if (is_bullet(l)) {
            flush_note(item, item_line, have_item)
            item = l; item_line = i; have_item = 1
        } else if (have_item) {
            item = item "\n" l            # 续行：并进上一个条目
        } else {
            item = item "\n" l            # 第一个条目之前就出现的注记
        }
    }
    flush_note(item, item_line, have_item)
}

# 条目符号。和 count_listitems 同口径：`-` `*` `+`、`1.` `1)`，以及中文的 `1、` `1）`。
# 只认半角点的话，用顿号编号的条目不被当成条目起始，整节会被并成一个条目，
# 只要其中任意一行有去向就全部放行——静默免检。
function is_bullet(l) { return l ~ /^[ \t]*([-*+][ \t]+|(（|\()?[0-9]+([.]|、|\)|）)[ \t]*)[^ \t]/ }

# 一个条目里只要**任何一行**写了去向就算数。
function flush_note(item, item_line, have_item,   l, n, i) {
    if (item == "") return
    n = split(item, NOTE_TMP, "\n")
    for (i = 1; i <= n; i++) {
        l = NOTE_TMP[i]
        gsub(/^[ \t]*([-*+]|(（|\()?[0-9]+([.]|、|\)|）))?[ \t]*/, "", l)
        sub(/[ \t]+$/, "", l)
        if (l == "无" || l == "无。" || l == "N/A") return
        if (index(l, "→") > 0 || index(l, "不沉淀") > 0) return
    }
    # 报错要能定位。条目可能以换行开头（前面是「第一个项目符号之前的散文」），
    # 直接剥前缀会剥空，消息就变成「没有去向:  —— …」，指不到任何东西。
    l = item
    while (substr(l, 1, 1) == "\n") l = substr(l, 2)
    sub(/^[ \t]*([-*+]|(（|\()?[0-9]+([.]|、|\)|）))[ \t]*/, "", l)
    sub(/\n.*/, "", l)
    V("「下次注意什么」这条没有去向: " l " —— 每条要么 `→ pitfalls` / `→ 任务分级阈值` / `→ skills/<名>`，要么写「不沉淀」")
}

# ---------------------------------------------------------------- NN-*.md 切片 / 决策条目

# 类型决定哪一节必填（同 plan.md 的「修 bug 时必填」）。
function slice_check(   type, tier, prio, st, n, t) {
    type = md_token("类型")
    if (type == "") { V("类型未声明（找不到 `- **类型**:` 行，值应为 切片 或 决策条目）"); return }
    if (type != "切片" && type != "决策条目") { V("类型 '" type "' 不在 {切片, 决策条目}"); return }

    if (type == "决策条目") {
        if (!field_filled("问题")) V("决策条目 —— 「问题」为空")
        if (!field_filled("结论")) V("决策条目 —— 「结论」为空")
        if (!field_filled("依据")) V("决策条目 —— 「依据」为空")
        return
    }

    tier = md_token("档位")
    if (tier == "")                 V("档位未声明（找不到 `- **档位**:` 行）")
    else if (index(tier, "T?") > 0) V("档位仍是模板占位符 T?")
    else if (tier !~ /^T[0-3]$/)    V("档位 '" tier "' 不是 T0–T3")

    prio = md_token("优先级")
    if (prio == "") V("优先级未声明（找不到 `- **优先级**:` 行）")
    else if (prio != "P0" && prio != "P1" && prio != "P2")
        V("优先级 '" prio "' 不在 {P0, P1, P2}")

    if (!field_filled("完成后可以看到什么")) V("「完成后可以看到什么」为空")
    if (!field_filled("完成标准"))           V("「完成标准」为空")
    if (!field_filled("文件范围"))           V("「文件范围」为空")
    if (!field_filled("被谁挡"))             V("「被谁挡」为空（没有前置就写「无」）")

    st = md_token("状态")
    if (st == "") V("状态未声明（找不到 `- **状态**:` 行）")
    else if (st != "pending" && st != "in_progress" && st != "completed")
        V("状态 '" st "' 不在 {pending, in_progress, completed}")

    # 标记完成却回填不了提交，说明这个切片的状态是假的
    if (st == "completed" && !field_filled("主要提交")) V("状态是 completed，但「主要提交」没回填")

    if (!has_section("确认")) V("缺「## 确认」一节")
    else {
        t = section_text("确认")
        if (count_checkboxes(t, 1) == 0)
            V("「## 确认」里一条确认项都没有（照模板抄；确实不需要就写明为什么）")
        n = count_checkboxes(t, 0)
        if (n != 0) V("「## 确认」还有 " n " 项没勾")
    }
}

# ---------------------------------------------------------------- review.md（裁决单）

# 只有 T2 / T3 需要。模板里那几段说明文字如果被当成内容，一个没填的裁决单会通过。
function review_check(   i, undecided) {
    for (i = 1; i <= 5; i++)
        if (!has_section(REVIEW_SECS[i])) V("缺「## " REVIEW_SECS[i] "」一节")

    if (!field_filled("固定点")) V("「固定点」为空")
    if (table_rows(section_text("逐条处理"), 1) == 0) V("「## 逐条处理」表里没有任何条目")

    undecided = section_text("审查者明确未判断的")
    gsub(/[[:space:]]/, "", undecided)
    if (undecided == "")
        V("「## 审查者明确未判断的」留空了（一条都没有就写「无」）——把「没判断」显式化，人才能看出盲区在哪")
}

# ---------------------------------------------------------------- 文档内的相对引用

# 输出 `文件<TAB>引用`，由 bash 逐个 stat。放在 awk 里是为了
# 「一个 markdown 解析器」——围栏代码块、行内代码、注释的剥离规则和别的检查同一套，
# 否则会出现「文档里贴了一段命令，闸门把命令里的路径当真」。
#
# 跳过的东西（都是模板里真实存在的写法）：
#   - 围栏代码块内的内容（示例命令、目录树）
#   - 带占位符的路径：`<日期>` `{x}` `*` `$`
#   - 外部链接、锚点、绝对路径
function links_dump(   i, j, end, l, fence, segs, n, k, s, r) {
    for (i = 1; i <= FIDX; i++) {
        end = (i < FIDX ? FSTART[i + 1] : NL + 1)
        fence = 0
        for (j = FSTART[i]; j < end; j++) {
            l = L[j]
            if (l ~ /^[ \t]*(```|~~~)/) { fence = !fence; continue }
            if (fence) continue

            # 行内代码：`path`
            n = split(l, segs, "`")
            for (k = 2; k <= n; k += 2) emit_link(FNAME[i], trim(segs[k]))

            # markdown 链接：[文字](path)
            r = l
            while (match(r, /\]\([^)]+\)/)) {
                s = substr(r, RSTART + 2, RLENGTH - 3)
                emit_link(FNAME[i], trim(s))
                r = substr(r, RSTART + RLENGTH)
            }
        }
    }
}

function trim(s) {
    sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s)
    sub(/^["']/, "", s); sub(/["']$/, "", s)
    return s
}

function emit_link(file, s,   last, t, ext) {
    if (s == "") return
    # 不是相对路径：外部 URL、锚点、绝对路径、带占位符/通配符的
    if (s ~ /^[a-zA-Z]+:\/\//) return
    if (s ~ /^#/) return
    if (s ~ /^\//) return
    if (s ~ /[<>{}*$|]/) return
    if (s ~ /\.\.\./) return
    if (s ~ /NNNN/) return
    # 日期占位符：`reports/YYYY-MM-DD.md`、`history_YYYY-MM.json`。
    # 命名约定不是路径，但它们的扩展名看着像文件，只能靠 YYYY 认出来。
    if (index(s, "YYYY") > 0) return
    # 以点开头的是类名/选择器列表（`.card/.kpi-card/.topbar`）。真正的相对路径
    # 只有 `./x` 一种写法，单独放行。
    if (substr(s, 1, 1) == "." && substr(s, 1, 2) != "./") return
    if (s ~ /[ \t]/) return
    # env 赋值 / shell 片段：`KEY=/path`、`--out=docs/x.md`。
    # 用「前缀 + =」而不是「整串含 =」：后者会漏掉 `src/a=b.py` 这种真文件名。
    if (s ~ /^[A-Za-z_][A-Za-z0-9_]*=/ || s ~ /^--[A-Za-z0-9-]+=/) return
    # 后缀不属于路径：pytest node id `path::test_x`、行号 `path:120`、
    # 模块属性 `web/app.py:_ASSET_FILES`。剥掉之后**只判文件那一段**。
    # 先剥 `::` 再剥 `:120` / `:IDENT`，复合写法 `x.md:12::foo` 需要这个顺序。
    sub(/::.*$/, "", s)
    sub(/:[0-9]+$/, "", s)
    sub(/:[A-Za-z_][A-Za-z0-9_]*$/, "", s)
    if (s == "") return
    if (index(s, "/") == 0) return

    # **只查认得扩展名的引用。** 这一条同时挡掉模块属性（`env_util.require_env`）、
    # 常量引用（`x.KINDS`）、npm 包名（`@scope/pkg@1.2.0`）、点号表达式（`.is_readonly(`）
    # ——它们的「扩展名」是标识符片段，不是文件类型。
    # 代价：项目用了列表外的后缀时查不到；加后缀比加特例便宜。
    last = s
    sub(/[\/]+$/, "", last)
    # 裸域名（`youtu.be/`）：去掉尾斜杠后没有内部 `/`，不是相对路径
    if (index(last, "/") == 0) return
    sub(/.*\//, "", last)
    ext = tolower(last)
    if (ext !~ /\./) return
    sub(/.*\./, "", ext)
    if (!(ext in LINK_EXT)) return
    # 去掉行尾的标点（中文句读紧跟在反引号外的情形）
    sub(/[，。；：、）)]+$/, "", s)
    if (s == "" || index(s, "/") == 0) return
    print file "\t" s
}

# ---------------------------------------------------------------- ADR

# 一次扫 docs/adr/*.md。检查两件事：
#   1. 任何 `ADR-<4 位数字>` 引用都要有对应的文件
#   2. 被取代必须互链：A 写 Superseded-By: ADR-0007，0007 就得写 Supersedes: ADR-0001
#
# 为什么必须互链：只说「这被取代了」而不说「被谁取代」，半年后读的人走到断头路；
# 只在新的那篇里写「我取代了旧的」，旧的那篇就会继续被人当成现行决定引用。
function adr_check(   i, j, end, l, id, ids, n, k, r, t, have) {
    for (i = 1; i <= FIDX; i++) {
        end = (i < FIDX ? FSTART[i + 1] : NL + 1)
        id = adr_id(FNAME[i])
        if (id == "") continue
        ADR_FILE[id] = FNAME[i]

        for (j = FSTART[i]; j < end; j++) {
            l = L[j]

            if (match(l, /Superseded-By:[ \t]*ADR-[0-9][0-9][0-9][0-9]/)) {
                t = substr(l, RSTART, RLENGTH); sub(/.*ADR-/, "", t)
                SUPER_BY[id] = SUPER_BY[id] " " t
            }
            if (match(l, /Supersedes:[ \t]*ADR-[0-9][0-9][0-9][0-9]/)) {
                t = substr(l, RSTART, RLENGTH); sub(/.*ADR-/, "", t)
                SUPERSEDES[id] = SUPERSEDES[id] " " t
            }
            if (match(l, /^Status:[ \t]*[A-Za-z-]+/)) {
                t = substr(l, RSTART, RLENGTH); sub(/^Status:[ \t]*/, "", t)
                STATUS[id] = tolower(t)
            }

            # 正文/小节里出现的所有引用
            r = l
            while (match(r, /ADR-[0-9][0-9][0-9][0-9]/)) {
                t = substr(r, RSTART + 4, 4)
                ALSO[id] = ALSO[id] " " t
                r = substr(r, RSTART + RLENGTH)
            }
        }
    }

    # 1. 引用存在性
    for (i = 1; i <= FIDX; i++) {
        id = adr_id(FNAME[i])
        if (id == "") continue
        n = split(ALSO[id] " " SUPER_BY[id] " " SUPERSEDES[id], REFS, " ")
        for (k = 1; k <= n; k++) {
            t = REFS[k]
            if (t == "" || t == id) continue
            if (!(t in ADR_FILE)) {
                if (index(SEEN[id ">" t], "x") == 0) {
                    SEEN[id ">" t] = "x"
                    print "  [x] " FNAME[i] ": 引用了 ADR-" t "，但 docs/adr/ 里没有这个文件"
                }
            }
        }
    }

    # 2. 互链
    for (i = 1; i <= FIDX; i++) {
        id = adr_id(FNAME[i])
        if (id == "") continue

        n = split(SUPER_BY[id], REFS, " ")
        for (k = 1; k <= n; k++) {
            t = REFS[k]
            if (t == "" || !(t in ADR_FILE)) continue
            if (index(" " SUPERSEDES[t] " ", " " id " ") == 0)
                print "  [x] " FNAME[i] ": 写了 Superseded-By: ADR-" t "，但 ADR-" t " 里没有 `Supersedes: ADR-" id "`"
        }

        n = split(SUPERSEDES[id], REFS, " ")
        for (k = 1; k <= n; k++) {
            t = REFS[k]
            if (t == "" || !(t in ADR_FILE)) continue
            if (index(" " SUPER_BY[t] " ", " " id " ") == 0)
                print "  [x] " FNAME[i] ": 写了 Supersedes: ADR-" t "，但 ADR-" t " 里没有 `Superseded-By: ADR-" id "`"
        }
    }

    # 3. 归档/取代过的 ADR 不该还写着 accepted
    for (i = 1; i <= FIDX; i++) {
        id = adr_id(FNAME[i])
        if (id == "" || SUPER_BY[id] == "") continue
        if (STATUS[id] != "" && STATUS[id] != "superseded")
            print "  [x] " FNAME[i] ": 已经写了 Superseded-By，但 Status 是 '" STATUS[id] "'（应为 superseded）"
    }
}

function adr_id(f,   b, id) {
    b = f; sub(/.*\//, "", b)
    if (b !~ /^[0-9][0-9][0-9][0-9]-/) return ""
    id = substr(b, 1, 4)
    return id
}
