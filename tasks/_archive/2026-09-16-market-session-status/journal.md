# Journal — 侧栏市场状态改为两行两市场（market session status，方案 C）

- **日期**：2026-09-16
- **任务目录**：`tasks/2026-09-16-market-session-status/`
- **计划**：`plan.md`（架构师实测后出具；需求方已裁定方案 C + 绿点语义 + 凌晨写「未开盘」）
- **性质**：前端 DOM + 三份 JS 副本 + 验收脚本断言改造 + 文档回填
- **执行角色**：编码执行者（Phase 3 Step 3.6–3.7）；未做架构决策、未扩大改动范围

---

## 1. 目标（已达成）

侧栏底部的市场状态必须**逐市场指名**并按**该市场真实交易时段**判定，而不是"今天是不是工作日"。

用户报场景（北京 20:4x）：A 股已收盘、美股未开盘 → 正确显示应为两行、双灰点：

```
● A股 已收盘          ← 点熄灭（灰，--text-muted）
● 美股 未开盘          ← 点熄灭（灰）
  北京时间 20:44
```

旧实现是单行 `● 市场已开盘`（绿点常亮）。**实测确认是缺陷**：旧代码 `wdIdx>=1 && wdIdx<=5` 只判工作日，取出的 `hh/mm` 只用于显示、**从不参与判定**。

---

## 2. 改动文件清单

| 文件 | 规模 | 内容 |
|---|---|---|
| `web/templates/_sidebar.html` | +7 / −2 | `.market-status` 内 1 行 → 2 行（`#market-dot-cn`+`#market-status-cn` / `#market-dot-us`+`#market-status-us`，各带 `data-market`，点加 `aria-hidden="true"`）；第三行 `#market-time` 原样保留；加 1 段 `{# #}` 注释写明点色新语义 |
| `web/static/app.js` | +103 / −21 | `MARKET_SESSIONS` 配置 + `marketHM/marketLocalParts/marketSessionOf/marketStateOf/marketBeijingHM` + `window.__marketSession(iso)` 同源钩子 + `updateMarketStatus` 重写（两行文案 + 逐点 `classList.toggle('open', …)`） |
| `web/static/macro.js` | +88 / −14 | 同口径逐字副本（IIFE + `var` 风格，`el()` 取值） |
| `web/static/macro_cn.js` | +88 / −14 | 同上 |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | +261 / −3 | MEASURE_JS 取 `#market-status-cn`/`-us`；`:2748` 写死文案断言 → **同源断言**；新增 `MS_CASES` / `MS_VIEWPORTS` / `MS_JS` / `_ms_js` / `_ms_labels` / `assert_market_session`（MS-0~MS-7）并挂入 `main()` |
| `docs/pitfalls.md` | +7 条 | 新段「模块 web/（侧栏市场状态两行两市场，2026-09-16）」 |
| `docs/architecture.md` | +1 行 | 决策表追加（append-only，`## 约束` 之前） |
| `tasks/2026-09-16-market-session-status/journal.md` | 新增 | 本文件 |

**零改动（已用 `git diff --quiet` 逐项核实）**：`web/static/style.css`（**与 HEAD 逐字节一致**）、`web/app.py`、`src/**`、`tests/**`、`data/**`。

> ⚠️ 计划 §R9 建议"在 `style.css:205` 附近写明点色新语义" 与 §5/§10「`style.css` 零改动」冲突 —— **按 §5/§10 执行**（保持 diff 最小、避免与"零改动"结论矛盾），新语义注释写在**三个 JS 的调用点**（真正 toggle 的地方）。**此项请需求方确认**。

---

## 3. 验证结果（全部实跑）

| # | 命令 | 结果 |
|---|---|---|
| V0 | `node --check web/static/{app,macro,macro_cn}.js` | 三个文件退出码 0 ✔ |
| V1 | `venv/Scripts/python -m pytest tests/ -q` | **663 passed**，零回归（与 plan §7 预期数字一致）✔ |
| V1b | `git status --porcelain`（pytest 后） | 无 `context/*` / `data/backup/*` 污染（conftest 隔离护栏生效）✔ |
| V3 | `venv/Scripts/python tasks/.../verify_ui.py` | **EXIT=1**：`MS-*` **47 条全 PASS**；12 条失败全在 `/macro` 数据组 + Firefox 专项（§5 已定责为基线既有/环境） |
| V4 | 改实现**前**跑 MS 组 | **红跑：32 条 FAIL**（清单见 §4）✔ 先红后绿成立 |
| V5 | 三页一致性 | `MS-5a` PASS：`/` · `/macro` · `/macro/cn` 在 9 例注入时刻**全表逐字一致** ✔ |
| V6 | 几何护栏 1920×1080 / 1280×720 / **769×720** | `footer.h == 63` ✔、`.market-status.h == 50` ✔、`#sidebar` 无纵向滚动条 ✔、两行零溢出 ✔、无横向溢出 ✔、贴底 ✔（三档全过） |
| V7 | 页面总高护栏 | `1920 scrollHeight ≤ 1240` PASS（方案 C 实测**不变**）✔ |
| V8 | 边界 / 覆盖表 | `MS-3` 9 例全 PASS（§6 详情）✔ |
| 可视取证 | 元素截图 `.sidebar-footer` | 真实时刻 **21:13** 渲染为 `● A股 已收盘` / `● 美股 未开盘`（双灰点 `rgb(156,163,175)`）+ `北京时间 21:13`，`footerH=63` / `msH=50` ✔ 截图落 `%TEMP%\mp-session-shot\` |

---

## 4. 红跑证据（改实现前，MS 组 32 条 FAIL）

| 断言 | 实测值 | 说明 |
|---|---|---|
| MS-1a | `hasHook = False` | 同源钩子未实现 |
| MS-2a | `rows = ['?']` | 旧 DOM 只有 1 行、无 `data-market` |
| MS-3（9 例） | 全部 `None` | 时段判定不存在 |
| MS-6a / 6b | `footerH=45` / `msH=32` | 旧单行结构（对照 plan §3.4 基线实测值，逐字吻合） |
| MS-0 / MS-4a / MS-5a / MS-6d | **首轮假绿** | ⚠️ 见 §5.2，本轮自己的断言缺陷，已修后复跑确认变红 |

---

## 5. 遇到的问题

### 5.1 plan 覆盖表有 2 格与 §4.1 判定规则冲突（已报告 + 按规范规则修正）

用临时探针（`%TEMP%\ms_expect.py`，Python `zoneinfo`）把整张表**独立算了一遍**，与 plan 表格对账：

| 注入 UTC | 北京 / 美东本地 | plan 写 | 按 §4.1 实算 | 处置 |
|---|---|---|---|---|
| `2026-09-16T04:00:00Z` | 12:00 Wed / **00:00 Wed** | 美股「已收盘」 | **未开盘**（`t < 09:30`，且 local weekday 还是周三） | 按实算 |
| `2026-09-19T04:00:00Z` | 12:00 Sat / **00:00 Sat** | Step 6 写美股「已收盘」 | **休市**（美东本地是周六） | 按实算 |

⇒ plan §4.1（规范性规则）与 §4.2 / Step 6（表格）自相矛盾；**表格是笔误**（§4.2 同一张表里「周六 12:00 → 美股 休市」是对的，与 Step 6 冲突）。已按 §4.1 落地并在 `MS_CASES` 注释 + 本文记录。**未擅自改 plan 文件**。

### 5.2 我自己写的"同源断言"里出现两处**假绿**（红跑实测抓到，已修）

| 断言 | 假绿机制 | 修法 |
|---|---|---|
| `MS-4a` | 取不到元素时 `openClass` 与 `exp_open` **同为 `None`** → `None == None` PASS | `isinstance(exp_open, bool) and row["openClass"] is exp_open` |
| `MS-5a` | `_ms_labels()` 过滤掉取不到的用例 → 两侧都成 `{}` → `len(0)==len(0)` PASS | 钉死条数 `len(lab2) == len(MS_CASES)`；新增 `MS-0` 要求用例结果**非空** |
| `MS-6d` | 只有 1 行（`'?'`）时"无溢出"平凡成立 | 同时要求 `rows.keys() == ['cn','us']` |

修完复跑：假绿的 3 条全部**转红**（红跑 FAIL 25 → 32），证明收紧后的断言有牙齿。

### 5.3 V3 整体 `EXIT=1`（12 条非 MS 失败）—— 根因已取证为**数据层 + 基线既有**

**取证（不是代码推理）**：

1. **端点直打**：自起 uvicorn 后 `curl /api/macro` → 4 个品种 `value` **全为 `null`**、`trend.dates = []`；`curl /api/econ` → `as_of = null`、4 序列 `latest` 全 `null`。
2. **出网探测**：`curl https://query1.finance.yahoo.com/v8/finance/chart/^VIX` → **`http=429`**（被限流）。⇒ `/api/macro` 的 null 值有直接外部原因；`/api/econ` 是 BLS 瞬时失败（验收脚本自己打印了 `[retry] /api/econ 首次返回空（外部 BLS 瞬时失败）`）。
3. **改动边界**：`git diff --name-only` = `verify_ui.py` + 3 个 JS + `_sidebar.html`；`git diff --quiet -- web/static/style.css web/app.py src/` 全部通过 ⇒ 数据链路与 CSS **零接触**。
4. **基线 A/B（决定性）**：`git archive HEAD` 到 `%TEMP%` 建隔离副本（venv 走目录联接），在同一环境跑**同一批断言组** →
   **基线 HEAD 失败 15 条：`MX-6, MX-6b, MX-9, MX-9b, MX-10, MX-11, MX-11b, MX-7, MX-8, MX-13, M-4, M-5, XC-0, N-12a, N-12b`**，
   而本轮失败 12 条 = 基线的**真子集** ⇒ **本轮新增失败 0 条**。
   基线多出的 3 条（`MX-6b/MX-9b/MX-10`）同样是 `/api/macro` 空数据所致（`hist=0` vs 本轮的 `hist=3`，Yahoo 抖动）。

⇒ **结论：12 条失败与本改动无关**；`N-12a/12b`（Firefox CSSOM `scrollbar-color`/`scrollbar-width`）在基线上同样红，且 `style.css` 与 HEAD 逐字节一致。

**⚠️ 未做的事（明确标注）**：未修复这 12 条（超出本任务范围：需 `src/`/`web/app.py` 或外部数据源侧处置，且属既有问题）；未在 Hermes 数据 cron 修好后重跑一次全量验收。

---

## 6. 覆盖表（§4.1 口径，MS-3 全绿）

| 注入 UTC | 北京 / 美东 | A 股 | 美股 | 点色 |
|---|---|---|---|---|
| `2026-09-16T12:44Z` | 20:44 / 08:44 EDT | 已收盘 | **未开盘** | 灰 / 灰 ← 用户截图场景 |
| `2026-09-16T13:30Z` | 21:30 / 09:30 EDT | 已收盘 | 交易中 | 灰 / 绿 |
| `2026-12-01T13:30Z` | 21:30 / **08:30 EST** | 已收盘 | **未开盘** | 灰 / 灰 ← DST 护栏 |
| `2026-12-01T14:30Z` | 22:30 / **09:30 EST** | 已收盘 | 交易中 | 灰 / 绿 ← DST 护栏 |
| `2026-09-16T04:00Z` | 12:00 / 00:00 | 午间休市 | 未开盘 | 灰 / 灰 |
| `2026-09-16T02:00Z` | 10:00 / 前一日 22:00 | 交易中 | 已收盘 | 绿 / 灰 |
| `2026-09-16T21:30Z` | 次日 05:30 / 17:30 | 未开盘 | 已收盘 | 灰 / 灰 |
| `2026-09-19T04:00Z` | 12:00 Sat / 00:00 Sat | 休市 | 休市 | 灰 / 灰 |
| `2026-09-18T19:00Z` | 09-19 03:00 Sat / 09-18 15:00 Fri | 休市 | 交易中 | 灰 / 绿 ← §4.1 点名的跨时区场景 |

**反向验证（Step 6 要求，已做）**：把美东时区故意改成定值 `Etc/GMT+4`（模拟"硬编码偏移"的 DST 炸弹）后跑 MS 组 → **只有** `2026-12-01T13:30Z` 变红（`美股 交易中` vs 期望 `未开盘`），9 月用例仍绿 → 证明护栏精确针对 DST、不是摆设；**且 `MS-5a` 连带在 `/macro`、`/macro/cn` 上报出三页分叉**（实际值 `A股 已收盘|美股 交易中` vs 期望 `…|未开盘`），顺带证明"三份副本一致性"断言也能抓到这类分叉。验证后已回退（`grep` 确认 `America/New_York` 复位、无 `Etc/GMT` 残留）。

---

## 7. 取证缺口（明确标注，未做）

- ❌ **节假日未验**：`plan §2.3 / R3` 已明确不做（需日历依赖）；"休市"只用于周末 ⇒ 未对国庆/春节/感恩节做断言。**已知取舍**。
- ❌ **分钟级刷新边界延迟 60s 未实测**：`setInterval(updateMarketStatus, 60000)` 保留（plan R10 有意接受）。`MS-1b` 为此留了一次"跨边界重读"，但**未构造服务器时钟跨 09:30 的真实跨越**。
- ❌ **触屏未验**：本次改动无触屏分支（纯文本/类名），`plan` 未要求。
- ❌ **Firefox 内核专项（`N-12a/12b`）未修**：基线上同样红（见 §5.3），属既有问题。
- ❌ **未在 `data/news.json` 之外核对 Hermes 侧行为**：`data/news.json` 现为 `M`（外部 5 分钟 cron 写入，**非本次改动**），提交时不得认领。

---

## 8. 下次注意

- **"表格式期望值"落进断言前，先跑一遍再用**：本次 plan 的 2 格笔误若照抄，会造成"去改正确实现"的假红。用 `zoneinfo`/独立探针核算，冲突按**规范性规则**（§4.1）修正，并把冲突写进代码注释与 journal。
- **同源断言 + 可选值 = 假绿高危**：凡"期望值也可能取不到"的断言，必须显式断类型（`isinstance(x, bool)`）与**条数**（覆盖度断言）。红跑阶段要专门看一眼"是不是所有新断言都红了" —— 本次 3 条假绿就是靠"FAIL 数偏少"发现的。
- **跨时区/跨市场的"时间"判定，一律用各自 IANA 时区**，禁止把"北京 21:30 / 22:30"写进代码或断言；DST 用例必须成对出现（夏令时档 + 冬令时档）。
- **基线 A/B 的零风险做法**：`git archive HEAD` → `%TEMP%` 副本 + `venv` **目录联接**，绝不在真实工作区回退（会与仓库外 Hermes 5min `git add -A` 抢提交）。⚠️ 回收**必须先非递归删联接**（`[System.IO.Directory]::Delete($j, $false)`）再 `rm -rf`，否则 MSYS 会顺着联接删真实 venv。
- **`white-space: nowrap` 容器优先"加行"而非"加字"**：加字会溢出并可能触发侧栏横向滚动条；加行（column flex）只增高。宽度预算 169px，新增行实测 73px。
- **`verify_ui.py` 是多会话共享文件**：本次改动前工作区为 clean（`git status --short` 空），故无归属冲突；仍应按 `git diff -U0` 逐 hunk 确认后再提交。
- **提交时不要认领 `data/news.json`**：它是外部 Hermes cron 的在途写入（`auto: 每日数据更新` 系列提交），非本任务产物。
