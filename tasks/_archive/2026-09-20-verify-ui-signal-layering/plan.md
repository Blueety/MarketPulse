# 方案：UI 验收脚本的信号分层（G8）

> **任务档**：`tasks/2026-09-20-verify-ui-signal-layering/`
> **P0 序列第 3 个**（① web 鉴权 ✅ → ② G1 凭据处置 ✅plan → ③ **本任务**）
> **角色**：Phase 3 Step 3.3 架构师（只读分析 + 方案，**不含完整实现代码**，不改任何项目文件）
> 实测条件：2026-09-20 11:4x，本机直连。
>
> ⚠️ 本文档作者是架构师，**不直接改项目代码**。`verify_ui.py` 的改动由执行者实施。
>
> **状态（2026-09-20 12:4x）：定稿，可交付执行者实施。** §10 三项已裁定（D-1=A / D-2=A / D-3=做）。
> 🔴 **范围已收窄**：架构师实测发现 **N-12a/12b 当前已 PASS**（G8 记录的 2 条 Firefox 红**已过时**）
> ⇒ 本任务**只做上游分层**，**不需要**去修 N-12（详见 §3.4 与 §10.1）。

---

## 0. 结论先行

1. **问题不是"断言写错了"，是"信号没有分层"**。`verify_ui.py` 把三类性质完全不同的失败
   混在同一个 `FAILURES` 列表里输出 `FAILED: N 条`：
   ① 代码回归（要立刻查） ② **上游数据源不可用**（与本项目无关，等它恢复） ③ 环境/引擎差异。
   三类同色 ⇒ **真回归被红色背景淹没**，脚本失去信号价值（G8 原话）。
2. **本任务 = 引入三态模型 `PASS / FAIL / SKIP`**，且**只把"上游确实不可用"的失败降级为 SKIP**。
3. 🔴 **最大的风险是"SKIP 变成掩盖 bug 的开关"** —— 如果"数据为空就 SKIP"，那么将来
   `web/app.py` 或 `src/fetcher.py` 真的坏了也会被 SKIP 掉，**比现在更糟**（现在至少是红的）。
   ⇒ 本方案用**两条硬约束**杜绝它（§3.3），这是整个设计的核心，**不许在执行时放松**。
4. **已确认现存的 SKIP 只是 `print` + `return`**（`assert_firefox_scrollbar`，因未装 FF 内核时触发），
   **不进任何结构化记录** ⇒ 汇总里看不到 SKIP 数、report.json 里也没有。本任务顺带把它纳入三态。
5. 🔴 **G8 记录的两条「Firefox 专项红」已经过时** —— 架构师实测（12:4x，Firefox 1538）：
   `N-12a` 与 `N-12b` **当前都成立**（证据见 §2.4②）。G8 那条是 2026-09-16 的快照，
   之后（09-17 起）已恢复。⇒ **本任务不修 N-12**，但仍**保留其判据作为回归护栏**（§3.4）。

---

## 1. 任务目标

**Goal**：让 `verify_ui.py` 的失败输出**能直接区分"代码回归"与"外部原因"**，恢复其信号价值。

验收标准：

1. 输出三态：`PASS` / `FAIL` / `SKIP`，且**汇总行同时给出三者计数**（SKIP 不得静默）
2. `report.json` 新增 `skipped` 键（含每条 label + 原因），与 stdout 同源
3. **上游不可用时**：依赖该源的断言记 `SKIP`（不计失败）；**上游可用时同样的失败仍是 `FAIL`**
4. **探测不确定时一律不算 SKIP**（保守优先，§3.3 约束②）
5. 退出码：有 `FAIL` → 1；仅 `SKIP` → 0，但打印醒目提示；新增 `--strict`（有 SKIP 即 1）
6. 既有断言语义**零放松**（不改阈值、不改期望值）
7. 全量跑通：既有断言无新增 FAIL

---

## 2. 实测取证（Step 0，已完成）

### 2.1 现有机制

```python
FAILURES: list[str] = []                    # 模块级，唯一的失败集合

def check(cond, label, actual=None, expect=None) -> None:
    if cond:  print(f"  PASS  {label}")
    else:     FAILURES.append(...); print(f"  FAIL  {label}...")

# main() 末尾（5005-5025）
report["failures"] = FAILURES
if FAILURES:  print(f"FAILED: {len(FAILURES)} 条"); return 1
print("ALL PASSED"); return 0
```

⇒ **二元模型，无第三态**；`FAILURES` 是唯一事实来源。

### 2.2 现有的 SKIP —— 只有一处，且不结构化

`verify_ui.py:4661-4665`：

```python
try:
    fb = p.firefox.launch()
except Exception as exc:
    print(f"  SKIP Firefox 内核不可用（需 `playwright install firefox`）: ...")
    return                      # ← 直接 return：不进 FAILURES，也不进任何 SKIP 记录
```

⚠️ 后果：**SKIP 只出现在 stdout 的滚动日志里**，汇总（`FAILED: N 条` / `ALL PASSED`）
与 `report.json` **都看不到** ⇒ 读者无法知道"这次有几条没验"。

### 2.3 断言清点（G8 点名的 + 实际扫到的）

**依赖 `/api/macro`（上游 Yahoo）**：

| 标签 | 行 | 内容 |
|---|---|---|
| `MX-6` | 1574 | 10Y 显示 ≈4.xx% |
| `MX-6b` | 1575 | 核心宏观变量 4 张 |
| `MX-7` | 1604 | 多变量对比 4 条线、起点归一 100 |
| `MX-8` / `MX-8b` | — | 主图相关 |
| `MX-9` / `MX-9b` | — | — |
| `MX-13` | 1617 | 主题切换生效**且图表存活** |
| `MX-14a/b` / `MX-15` | — | — |
| `M-1`…`M-10b` | — | 宏观页因子/变量组 |
| `M-4` | 2043 | 全部对比描边有主次 |
| `M-5` | 2045 | Y 轴贴合数据且不裁 |
| `XC-0` | 2134 | `#macro-chart` 实例可达 |
| `XC-1/5/6/9` | — | crosshair 相关 |

**依赖 `/api/econ`（上游 BLS）**：`MX-11` (1591)、`MX-11b` (1592)、`MX-11c` (1594)

### 2.4 🔴 两个必须注意的细节

**① 同一函数内对上游的依赖程度不同，不能整组 SKIP。**
反例（就在同一段里）：

| 标签 | 依赖上游？ | 理由 |
|---|---|---|
| `MX-11` | ✅ 依赖 | 要读 `as_of` 的月份才能断言 |
| `MX-11b` | ✅ 依赖 | 要 4 项数据 |
| **`MX-11c`** | ❌ **不依赖** | 「不含『最新/实时』字样」——**空态也必须满足**，上游挂了它照样该过 |

⇒ 设计必须支持**逐条标记**，整函数级标记会误伤。

**② Firefox 已安装且 N-12 当前通过（实测，推翻 G8 记录）**

`ms-playwright/firefox-1538` 存在 ⇒ `assert_firefox_scrollbar` **不走 SKIP 分支**，会真跑断言。
架构师用独立探针（复刻 `FF_SCROLLBAR_JS`，另加 Chromium 对照）实测结果：

| 浏览器 | `scrollbarColor` | `gateScrollbarWidth` | 结论 |
|---|---|---|---|
| **Firefox** | `rgb(213, 218, 225) rgba(0,0,0,0)` | `thin` | **N-12a ✓ / N-12b ✓（都成立）** |
| Chromium | `auto` | `thin` | 门控**正确地未命中**（证明门控有效） |

CSSOM 门控块（两浏览器都能读到规则文本）：
`conditionText = "(-moz-appearance: none)"` → 内部 `* { scrollbar-width: thin; scrollbar-color: var(--scroll-thumb) transparent }`

⇒ **G8 记录的「N-12a/12b 常红」是 2026-09-16 的快照，已过时**（与 `MEMORY.md` 记的
「09-17 晚复跑 12 条基线红全消失」一致）。**执行者不要再去修它。**

**③ 上游探测方案已实测可行**（约束①的可行性验证）：

| 上游 | 端点 | 实测 |
|---|---|---|
| Yahoo chart（`/api/macro` 的源） | `query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=5d&interval=1d` | **HTTP 200 / 0.48s** |
| BLS（`/api/econ` 的源） | `api.bls.gov/publicAPI/v2/timeseries/data/`（POST） | **HTTP 200 / 2.25s** |

⇒ 两者都需浏览器 UA（Yahoo）；BLS 用 POST。直连即可判定，**无需经过 `src/fetcher`**。

---

## 3. 方案设计

### 3.1 三态模型

| 态 | 含义 | 计入退出码 |
|---|---|---|
| `PASS` | 断言成立 | 否 |
| `FAIL` | **断言不成立，且无法归因于外部** | ✅ 是（return 1） |
| `SKIP` | **断言无法判定**，因为明确知道外部依赖不可用 | 否（但必须可见） |

新增模块级 `SKIPPED: list[dict]`（存 `label` + `reason`，便于写进 report.json）。

### 3.2 断言侧：给 `check` 加"依赖声明"

```
check(cond, label, actual=None, expect=None, deps=())
```

- `deps=()`（默认）⇒ **永不 SKIP**，行为与今天完全一致（保守默认）
- `deps=("macro",)` ⇒ **仅当** `upstream["macro"]` 为「已确认不可用」时，
  该条失败降级为 SKIP；否则照常 FAIL

伪代码：

```
def check(cond, label, actual=None, expect=None, deps=()):
    if cond:            → PASS
    elif 任一 dep 已确认不可用:
        SKIPPED.append({label, reason: f"上游 {dep} 不可用（已直连确认）"})
        print(f"  SKIP  {label}  ← 上游 {dep} 不可用")
    else:
        FAILURES.append(...)   # 含"上游可用但数据为空"= 我们的 bug ⇒ 必须 FAIL
```

> **逐条标记，宁少勿多**：漏标只会让该红维持 FAIL（安全）；
> **多标才是危险**，所以只标"确证依赖上游"的断言。

### 3.3 🔴 两条硬约束（本方案的核心，不许放松）

**约束①：上游探测必须独立于被测链路。**

探测**不得**复用 `src/fetcher.py` 或 `web/app.py` 的函数 —— 否则**如果这些代码坏了，探测也会失败**，
于是"我们的 bug"被误判成"上游挂了"而被 SKIP。

⇒ 探测函数里**直连上游 URL**（Yahoo chart / BLS API）。虽然与 `fetcher` 有 URL 重复，
但**这正是独立口径的价值**（本项目既有方法论：`MEMORY.md`「独立期望值预言机」——
不复用被测实现暴露的钩子算期望值）。

**约束②：探测不确定时，一律**不**降级为 SKIP。**

| 探测结果 | 判定 |
|---|---|
| 直连成功 | 上游**正常** ⇒ 失败算 `FAIL`（哪怕 API 返回空 = 我们的 bug） |
| 直连失败（明确拿到非 2xx / 连接错误） | 上游**不可用** ⇒ 带 deps 的失败降级 `SKIP` |
| 探测自身异常 / 超时 / 结果无法解读 | **视为"正常"** ⇒ 失败算 `FAIL` |

⇒ **SKIP 只在"明确知道上游挂了"时发生**。不确定时宁可报红（`fail-safe`，不是 `fail-open`）。

> 这两条合起来保证：**SKIP 不可能掩盖代码回归**。
> 因为"上游确实挂了"是**独立取证**的事实，而"我们代码坏了"必然伴随"上游直连是通的"。

### 3.4 N-12（Firefox 门控）—— **实测已通过，本任务不动它**

**裁定（D-1=A 的执行结果）**：架构师已按 A 路径「查清真因」，结论是 **N-12a/12b 当前都成立**
（证据见 §2.4②），**没有真因可修**。G8 里那 2 条红是 09-16 的历史快照。

⇒ 本任务的处置：**保持 `N-12a/12b` 判据原样**（`deps=()`，永不 SKIP），继续作为
「`-moz-appearance` 门控在 Firefox 命中」的回归护栏 —— 若将来有人改坏 `style.css` 的门控，
它仍会变红。**不改 `style.css`、不标注偏差、不塞进 SKIP 机制。**

> 为什么不能因为"现在通过"就把它做成 SKIP：它不是外部依赖，没有"上游不可用"这种状态。
> 塞进 SKIP 会让三态语义失真，且丢掉一个真实有效的护栏。

---

## 3.5 交付给执行者的前提修正（重要）

**G8 原文说「12 条常红」这个前提已经部分失效**。执行者开工前应知道：

| G8 说的 | 现状（2026-09-20 实测） |
|---|---|
| 10 条上游数据层红 | 取决于上游**当时**是否可用；今天 12:4x 上游 **Yahoo/BLS 都通** ⇒ 预期不红 |
| 2 条 N-12 Firefox 红 | ❌ **已不成立**（实测通过） |

⇒ 执行者的第一件事不是"照着 12 条去修"，而是**先跑一次基线拿到当前真实红集**
（这正是本任务存在的意义：让这个脚本每次跑都能自我说明）。

---

## 4. 涉及文件清单

| 文件 | 改动 |
|---|---|
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | ① 新增 `SKIPPED` 列表 + `probe_upstream()`（独立直连探测）；② `check()` 加 `deps` 参数与三态分支；③ 需要分层的断言逐条补 `deps=`（§2.3 清单）；④ `assert_firefox_scrollbar` 的 SKIP 改为走结构化 `SKIPPED`；⑤ 汇总段输出三态计数 + `--strict` 参数；⑥ `report.json` 加 `skipped` 键 |
| `docs/commands.md` | 该脚本的行内说明补三态语义 + `--strict` 用法；「什么时候跑」补一句"看到 SKIP 要查上游而不是查代码" |
| `docs/system-overview.md` | §9 **G8 状态更新**（说明已分层 + 剩余项）；§12 文档表若提到 G8 一并同步 |
| `docs/frontend-structure.md` | §7 硬约束区补一条"验收三态语义：SKIP 只表示上游不可用，不代表通过" |

**不动**：`web/**` · `src/**` · 既有断言的**阈值/期望值**（本次只加"归因"，不放松判据）· 其它测试

---

## 5. 实施步骤（每步可独立验证）

### Step 1 — 探测函数（独立口径）

新增 `probe_upstream()`，**直连**上游、返回可用性快照：

```
def probe_upstream() -> dict:
    """直连上游源判定可用性（**不经过 src/fetcher 与 web/app**，见 plan §3.3 约束①）。

    约束②：探测异常/超时/结果无法解读 → 一律返回 True（视为可用）⇒ 不降级为 SKIP。
    """
    # macro → Yahoo chart（GET，带浏览器 UA，超时 ~8s）
    # econ  → BLS publicAPI（POST）
    return {"macro": bool, "econ": bool, "detail": {...}}   # detail 落 report.json
```

- 在 `main()` 里**跑断言之前调用一次**（快照，避免运行中上游状态漂移）
- 打印一行 `上游探测: macro=OK econ=OK` + 写进 `report["upstream"]`
- ⚠️ 探测**失败不抛异常**（异常即视为可用，见约束②）

验证：单独跑探测（可临时加 `--probe-only` 便于手验），确认
① 直连拿到数据时返回 True；② 断网（或改探测 URL 为不可达主机）时返回 False。

### Step 2 — 三态改造

按 §3.2 改 `check()`：加 `deps` 参数 + `SKIPPED` 分支。
**先只改机制、不加 deps 标记** ⇒ 跑一遍，结果应与改动前**完全一致**（回归护栏）。

### Step 3 — 逐条补 deps

按 §2.3 清单给断言加 `deps=("macro",)` / `deps=("econ",)`。
⚠️ **逐条判断**：`MX-11c` 这类"空态也该成立"的断言**不加**。
⚠️ 加完后再跑一遍（上游正常时）：结果仍应与 Step 2 一致（**上游可用 ⇒ 不产生 SKIP**）。

### Step 4 — 汇总与退出码

```
probe 行 → 逐条 PASS/FAIL/SKIP → 报告段:
  ===== 结果 =====
  PASS:   N
  FAIL:   M        ← 有则逐条列出
  SKIP:   K        ← 有则逐条列出 + 原因
  上游探测: macro=DOWN econ=OK
  ⚠️ 有 K 条未判定（上游不可用），本次结果不代表代码回归
  FAILED: M 条          /  ALL PASSED (K SKIPPED)      /  ALL PASSED
```

退出码：`1` if FAILURES else `0`；`--strict` 时 `1` if (FAILURES or SKIPPED) else `0`。
另加**上限护栏**：若 `len(SKIPPED) > 总断言数 × 0.5`，打印醒目警告（提示环境不可信）——
**不改变退出码**，只提示（避免"大面积 SKIP 却报绿"被误读为通过）。

### Step 5 — Firefox SKIP 纳入三态（N-12 已定性，**无需再查**）

- `assert_firefox_scrollbar` 的 SKIP 分支改为写 `SKIPPED`（label + 原因），保持 `return` 语义
- `N-12a` / `N-12b` 的**判据保持原样**（`deps=()`）—— 已实测通过（§3.4），继续作回归护栏
- ⚠️ **不要**因为"G8 说它是红的"就去改 `style.css` 或放宽判据

### Step 6 — 验证（两轮，缺一不可）

```
① 上游正常时跑一遍      → 应无 SKIP；结果与改动前基线一致
② 模拟上游不可用跑一遍  → 带 deps 的断言应变 SKIP（而非 FAIL），退出码 0
```

②的模拟手法（**不联网改代码**）：把探测函数的上游 URL 指向一个不可达主机（临时改探针副本，
或加 `MP_VERIFY_UPSTREAM_DOWN=1` 之类的测试开关）—— 只要证明"探测判定 DOWN 时断言降级为 SKIP"即可。

> ⚠️ **②是必须的**：这是唯一能证明"分层真的生效"的验证。只做①等于没验证新功能。

---

## 6. 验证命令

```bash
# 全量 UI 验收（前台 + 显式 timeout；约 5 分钟）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py                 # 常规
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py --strict        # 有 SKIP 也判失败

# 单测（若后端契约有改动；本任务无后端改动时可跳过）
venv/Scripts/python -m pytest tests/ -q

# 基线 A/B（判"红是不是我改出来的"——不看绝对条数）
#   用 git archive HEAD 建隔离副本跑同一脚本；HEAD 失败集 ⊇ 本轮失败集 ⇒ 新增 0
```

> ⚠️ 关于**基线 A/B**（项目纪律）：本次改动**会改变失败集合的形状**（FAIL→SKIP），
> 所以 A/B 的比对口径要相应调整：**比较 "(FAIL ∪ 归因于上游的 SKIP)" 与旧基线 FAIL 集**，
> 而不是直接比条数。这条必须写进执行者的 journal，否则后人会误判。

---

## 7. 风险评估

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| **R1** | 🔴 **SKIP 掩盖真回归**（本任务头号风险） | **最高** | §3.3 两条硬约束：探测独立于被测链路 + 不确定时不 SKIP |
| **R2** | 🔴 **探测复用 `fetcher` 导致循环论证** | 高 | 约束①：直连上游 URL，**禁止** import `src.fetcher` / `web.app` 的函数 |
| **R3** | 探测本身成为新的不稳定源（超时/抖动） | 中 | 约束②：异常视为可用 ⇒ 最坏退化为今天的行为（报 FAIL），不会误 SKIP |
| **R4** | 逐条 deps 标错（多标） | 中 | 逐条判断 + §2.4① 的反例（`MX-11c`）；改完必须跑"上游正常"一轮确认无 SKIP |
| **R5** | 大面积 SKIP 却报绿被误读为"通过" | 中 | Step 4 的 50% 上限护栏 + 汇总醒目提示 + `--strict` |
| **R6** | N-12 与上游分层混在一起改 | 中 | §3.4 单列；不建议塞进 SKIP 机制 |
| **R7** | 改 `verify_ui.py` 影响第 1 个任务新增的 `AUTH-*` 组 | 中 | `AUTH-*` 不依赖上游 ⇒ 默认 `deps=()` 不受影响；改完复跑确认 `AUTH-*` 仍全绿 |
| **R8** | 该脚本同时是多个任务的验收工具（`TL-*` / `EV-*` / `QM-*` / `UX-*` / `MS-*`） | 高 | 三态改造是**机制级**改动 ⇒ **必须全量复跑**，确认所有断言组无新增 FAIL |

---

## 8. 预计影响的文件范围

| 类别 | 数量 |
|---|---|
| 主改动 | 1 文件（`verify_ui.py`）：新增约 120 行（探测 + 三态 + 汇总）+ 逐条 `deps=` 标记（约 20 处） |
| 文档 | 3 个（`commands.md` / `system-overview.md` / `frontend-structure.md`） |
| **不动** | `web/**`、`src/**`、其他 tests、所有既有断言的阈值与期望值 |

---

## 9. 明确不做

- ❌ **不放松任何判据**（不改阈值、不改期望值、不删断言）——本次只加"归因"，不改"标准"
- ❌ 不让探测复用 `src/fetcher` / `web.app`（约束①）
- ❌ 不做"数据为空就 SKIP"的宽松判定（那会掩盖真回归）
- ❌ 不把 N-12（Firefox 引擎差异）混进上游 SKIP 机制
- ❌ 不改 `web/app.py`（不为了给验收提供"失败原因"字段而改后端 —— 那会把探测变成非独立口径）
- ❌ 不解决 G8 建议①（给 Yahoo 走代理/换源）——那是独立的数据源任务

---

## 10. 决策裁定（2026-09-20 12:4x，用户已确认：**D-1=A / D-2=A / D-3=做**）

### 10.1 D-1 = A（查清真因再修）→ 执行结果：**无真因，N-12 已通过**

用户选 A。架构师按 A 执行了诊断（独立探针，§2.4②），结论：

- `N-12a` **成立**（`scrollbarColor = rgb(213,218,225) rgba(0,0,0,0)`）
- `N-12b` **成立**（`gateScrollbarWidth = thin`）
- Chromium 对照 `scrollbarColor = auto` ⇒ 门控**正确地只对 Firefox 生效**

⇒ **没有 bug 可修**。本任务对 N-12 的处置 = **保持判据不动**（作回归护栏），
**不改 `style.css`、不标注已知偏差、不塞进 SKIP**。

### 10.2 D-2 = A：退出码语义

- 仅 `SKIP`（无 `FAIL`）→ 退出码 **0**，但打印醒目提示（`ALL PASSED (K SKIPPED)`)
- 提供 `--strict`：有 `SKIP` 即退出码 1（供"我要全量验证"时用）
- 附带护栏：`SKIPPED > 总断言数 × 0.5` 时打印环境不可信警告（**不改退出码**）

### 10.3 D-3 = 做：SKIP 纳入结构化记录

现状 SKIP 只在 stdout 打一行（`verify_ui.py:4664`），汇总与 `report.json` 都看不到。
⇒ 纳入三态：新增 `SKIPPED` 列表 + `report["skipped"]` + 汇总计数。

### 10.4 本任务**不需要**用户再做的事

无。三项裁定已闭合，执行者可直接开工。（对比第 1 个任务需用户在 Railway 配 env、
第 2 个任务需用户去企业微信后台吊销 —— 本任务纯代码改动。）

---

## 11. 一句话

**这次改动的成败只取决于一条**：上游探测**能不能独立于被测代码**。
做不到这一点，SKIP 就会变成掩盖 bug 的开关，比现在更糟。
