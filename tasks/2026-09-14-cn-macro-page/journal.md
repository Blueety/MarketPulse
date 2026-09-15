# 任务日志：中国宏观独立页 `/macro/cn`（2026-09-14）

> 按 `tasks/2026-09-14-cn-macro-page/plan.md` 实施（Phase 3 Step 3.6-3.7）。

## 目标

新增中国宏观独立页 `/macro/cn`：13 个 AkShare 官方序列（CPI/PPI/PMI/GDP/M2/社融/新增信贷/失业率/社零/房价(北京·上海)/LPR/SHIBOR/10Y国债）+ 中国版四象限 + 人民币汇率/信用利差行情；侧栏同级入口；与 `/macro`（BLS 美国版）平行、互不污染。

## 改动文件清单

**新增（5）**

| 文件 | 说明 |
|---|---|
| `src/cn_econ_fetcher.py`（562 行） | 13 序列注册表 + 解析纯函数 + daemon 线程并发取数（限时 25s）+ 中国版四象限 + `fetch_bond_yield_curves`（中债 3 曲线 → 10Y/信用利差）；零写盘 |
| `web/templates/macro_cn.html` | 五层模块骨架（`.mac-*` 复用；主题预应用脚本与 `macro.html` 同源） |
| `web/static/macro_cn.js`（653 行） | 分组两波加载；主图（上证/深证/创业板/人民币/10Y国债）；四象限 + 核心变量 + 因子 + 利率/地产 + 经济数据；shell 行为（主题/抽屉/市场状态）与 `macro.js` 同口径 |
| `tests/test_cn_econ.py`（14 条） | 不联网：mock DataFrame + mock akshare + TestClient 缓存语义 |
| `scripts/probe_cn_macro.py` | 数据源回归探针（13 在册 + 8 否决接口） |

**修改（12）**

- `src/econ_fetcher.py`：`_QUADRANTS` → **`QUADRANTS`**（公开，中国版复用）+ 同文件 1 处引用改名。
- `web/app.py`（+148）：`GET /api/econ/cn`（`?group=` 分组 + **跨组累积 raw 缓存**）、`GET /api/cn/quotes`、`GET /macro/cn`；`_ASSET_FILES` 登记 `macro_cn.js`；`_CN_ECON_TTL=6h` / `_CN_QUOTES_TTL=90s`。
- `web/templates/_sidebar.html`：新增同级项「中国宏观」（跨页链接）→ navCount 10→11。
- `web/static/style.css`（+16）：`.cn-*` 最小补充（`.cn-dual` / `.cn-city*` + 480 断点堆叠）。
- `tests/test_web.py`（+87）：6 条（页面渲染 / 侧栏双链接 / `/api/econ/cn` 降级 / quotes 降级 + 形状 / TTL 防回退）+ `_reset_watch_cache` 扩为中国宏观缓存隔离。
- `tests/test_econ_fetcher.py`：`ef._QUADRANTS` → `ef.QUADRANTS`（**同步引用，非删断言**；plan 只列了 2 处引用，实际第 3 处在此文件）。
- `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（+151）：F-5 由单值 `macroHref` **补强**为数组 `macroHrefs`（navCount 10→11）+ 新增 `assert_macro_cn_page`（CN-1~CN-11）。
- 文档：`docs/architecture.md`（决策行）、`docs/pitfalls.md`（新分节 12 条）、`docs/commands.md`（5 行命令 + 1 行"何时跑什么"）、`docs/system-overview.md`（路由表 6→12、模块清单 +2、规模统计）、`AGENTS.md`（项目地图 5 处）。

## 验证结果

| 验证 | 结果 |
|---|---|
| `scripts/probe_cn_macro.py` | **13/13 可用且新鲜，EXIT=0**（串行 22.2~30.7s；`cpi` 3.4~6.3s、`bond_10y` 7.4~8.4s 为最慢） |
| `pytest tests/test_cn_econ.py` | **14 passed** |
| `pytest tests/test_web.py` | **120 passed**（基线 114） |
| `pytest tests/`（全量） | **659 passed**（基线 659 = 639 + 20 新增，其中 4 条为既有 `_QUADRANTS` 引用同步） |
| `verify_ui.py`（Playwright） | **ALL PASSED，EXIT=0**，`failures=0`（新增 CN-1~CN-11 全绿；F-5 实测 `navCount=11`、`macroHrefs=['/macro','/macro/cn']`） |
| `node --check web/static/macro_cn.js` | EXIT=0 |
| `git status --short` | 无意外生成物（`data/` `context/` `alerts/` 未被本次改动触碰） |

**实测数据（2026-09-14/15）**：`as_of=2026-08`；CPI 0.8% / PPI 3.8% / PMI 49.8 / GDP 4.7%(2026Q2) / M2 7.5% / 社融 3314 亿 / 新增信贷累计同比 −20.92% / 失业率 5.2% / 社零 0.6% / 房价 上海 +3.0%·北京 −2.3% / LPR 3.0% / SHIBOR 1.412% / 10Y 国债 1.6888%；信用利差 26.28bp；CNY 6.6977。
四象限 = **滞胀（stagflation）**：通胀 up（CPI/PPI 同比回升）× 增长 contracting（PMI 3M 49.77 < 50）；GDP 交叉校验一致（`conflict=false`）。

## 遇到的问题与处置

1. **AkShare 排序口径不统一（探针第一版读错最新值）**：`cpi`/`ppi`/`pmi`/`gdp`/`m2`/`credit`/`retail` 是**倒序**返回，`iloc[-1]` 读到 **2008-01**（滞后 224 个月）。修法：探针与生产侧统一 `_sort_rows()` 后取尾；探针新增 `ord` 列把口径可视化。
2. **`bond_china_yield` 区间敏感**：6 个月 → 411 行，1 年 → **0 行**（上游行为）。固定 6 个月窗口，并把 "1y=0 行" 写进探针已知行为，防后人当 bug 修。
3. **mock akshare 的桩函数必须接 `**kwargs`**：`bond_10y` 走 `AUTO_6M` 会传 `start_date/end_date`；`lambda:` 桩直接 `TypeError` → 被 `_fetch_one` 吞成"返回空"，表现为断言莫名 None。单测两处踩到并修正。
4. **中文字符串排序**：`sorted(["北京","上海"])` = `["上海","北京"]`（按码点）→ 城市集合断言改用 `set()`。
5. **`failed` 列表顺序**：`sorted(["cpi","ppi","pmi"])` = `["cpi","pmi","ppi"]`（字母序）→ 断言按实际字母序写。
6. **并发实测推翻预设**：串行 22.2s / workers=3 → 15.2s / workers=6 → 13.6s / **workers=13 → 10.3s**（墙钟由最慢的 `bond_china_yield` 8s 决定，不是并发度）→ `_CN_ECON_WORKERS` 定为 **13**。
7. **R1 分支判定为「分组端点」**：全量 10.3s > 8s 判据 → 启用 `?group=`。**但实测发现 6 个组同时发没有收益**（13 个上游请求照样同时在飞）→ 前端改为**分两波**（先 `price`+`growth` 出四象限，再其余组）。
8. **四象限在分组响应里拿不到（真实缺陷，已修）**：分组只取本组 key → 轴永远缺一半。修法：`web/app.py` 保留**跨组累积的 raw 缓存**，`build_cn_econ_payload(raw_all, ..., only=group)` 用**整个累积 raw 算四象限**、只用 `only` 过滤输出的 `series`。实测 `group=growth` 响应能带上 `quadrant=stagflation`。
9. **"失败不缓存"只做一半也是错的**：只做"全失败不缓存 payload"不够 —— raw 的 ts 若在失败时也写入，一次抖动仍会把空数据锁死 6h；只做后者又会让成功结果每次重打。最终语义：**payload 部分成功即缓存 6h；raw 的 ts 只在成功时写**（失败的 key 下次请求重试）。
10. **PowerShell `Add-Content` 把 `\|\|` 吞成 `;`**：追加的 JS 断言字符串 `t === "light" || t === "dark"` 落盘成 `;`，断言假红。**纪律：追加含 `||`/`&&` 的代码一律用文件编辑工具，不要用 PowerShell here-string。**
11. **plan 漏列的 `_QUADRANTS` 第 3 处引用**：全量 pytest 红在 `tests/test_econ_fetcher.py::TestQuadrants`。处置：同步改名为 `QUADRANTS`（不删断言、不放松判据）。
12. **F-5 属"断言脆弱"而非"方案不可行"**：侧栏多了一个**合法跨页链接**，`navCount == 10` 是写死的旧产品决定。处置：**补强**（`macroHref` 单值 → `macroHrefs` 数组 + 两个链接都纳入判据），并把原因写进断言注释。

## 与 plan 的偏差（需知悉）

- **`_CN_ECON_WORKERS` 6 → 13**：plan 给的 6 是估算；按实测（6→13.6s，13→10.3s）改为 13，理由写进代码注释。
- **前端分组加载改为"两波"**：plan 只说"分组懒加载"，未说明必须分批；实测证明"6 组同时发 = 无收益"，故显式分批。已记入 pitfalls。
- **`verify_ui` F-5 判据变更**：`navCount 10 → 11`、`macroHref` → `macroHrefs`。属**补强**（新增链接也纳入判据），非放松。
- **`basis.price_note` 不写"70 城"**：plan 附A 原文是「非 70 城」，但验收断言会检查房价模块文案**不含**「70 城」字面量（basis 会被渲染）→ 改为"仅覆盖北京·上海两城"。同一约束写进单测 `test_basis_states_pmi_level_rule`。
- **`tests/test_econ_fetcher.py` 有 1 行改名**（plan 声称"既有断言零改动"，实际该文件引用了私有名）。

## 追加修复（2026-09-15，用户反馈）

**反馈**：利率与流动性里「社会融资规模增量 3316 亿元 `+21.20% ↓`」——"为什么这个加号，然后右边又是下降的箭头"。

**根因（代码取证）**：`macro_cn.js::varRow` 一个单元格里混了两个口径且**无标签** ——
- 颜色 + 正负号 ← `cls(s.yoy)` / `fmtSigned(s.yoy)`：**同比本身**的符号（本期 vs 去年同月）→ `+21.20%` 是绿的，正确；
- 箭头 ← `s.direction` = `_direction(yoy, prev_yoy)`：**这个同比相对上期同比**的方向。
→ `+21.20% ↓` 的完整含义 = "同比仍正增长，但增速比上月回落"。**两句都对、不矛盾，问题在没写口径。**

**顺带发现**：10Y 国债渲染 `—%`（`fmtSigned(null) + "%"`）—— `yoy` 为 `None`（中债接口仅 6 个月窗口，拿不到去年同期基数），`—` 后多一个 `%` 像格式化漏洞。

**改动（3 文件）**：
- `web/static/macro_cn.js`：新增 `yoyTitle(s)`（缺失时说明原因，否则"同比 X%（本期 vs 去年同月）· 较上期回升/回落/持平"）；`varRow` 与 `renderEcon` 的同比单元格挂 `title`；`yoy == null` 时只渲染 `—`（不拼 `%`）。
- `web/templates/macro_cn.html`：核心宏观变量列说明改为「同比 = 本期 vs 去年同月（颜色/正负号）；箭头 = 同比较上期 ↑/↓」。
- `verify_ui.py`：新增 **CN-4c**（所有同比单元格必须有非空 `title`）/ **CN-4d**（title 含"去年同月"，防空壳）/ **CN-4e**（容器内不得出现 `—%`）。

**验证**：`node --check` EXIT=0；`pytest tests/test_web.py tests/test_cn_econ.py` **134 passed**；全量 `pytest tests/` **659 passed**；`verify_ui.py` **ALL PASSED / EXIT=0**（CN-4c/4d/4e 全绿，即**在真实浏览器 + 真实 AkShare 数据上**确认口径 title 已生效）。
**未走"删箭头"方案**：箭头承载的"增速回落"是有效信息，删掉是净损失；口径混淆的正确解法是补标签（已记入 `docs/pitfalls.md`）。

## 追加改造（2026-09-15，用户确认后实施：利率类改 Δ6M(bp)）

**决定的依据**：用户问"改了有什么区别" → 用真实数据量化后确认要改（10Y 从死格变有值 / SHIBOR 量纲纠正 / LPR 语义更准）。

**改动（4 文件，184+/20−）**
- `src/cn_econ_fetcher.py`：新增 `_shift_month` + `_chg_6m_bp`（**按日期/月份定位**基准点）；三条利率序列标 `chg_bp: True`；`lpr` 的 `freq: day → month`；series 新增 `chg_6m_bp` 键（非利率序列恒 `None`）；模块 docstring 约束 5 → 6 条。
- `web/static/macro_cn.js`：新增 `chgCell(s)`（利率 → `±X.Xbp`，自带单位、不配箭头；其余 → `同比 % + 箭头`）；`varRow`/`renderEcon` 共用；`spreadRow` 补 `title`（信用利差是第 5 行，原先缺 title）；新增 `logFetchError`（`AbortError → console.warn`，其余 `console.error`）；quotes/history 超时 20s → 30s。
- `web/templates/macro_cn.html`：利率列说明改为「Δ = 与 6 个月前相比（bp，1bp = 0.01 个百分点）」。
- `tests/test_cn_econ.py`：新增 4 条（按日期定位 / 月频与缺目标月 / lpr 月频与深度 36 / 只有利率带 `chg_6m_bp`）→ 14 → **18 条**。

**真实值（2026-09-15）**：LPR `0.0bp`、SHIBOR `+11.44bp`、10Y 国债 `−8.96bp`（改造前：`0.00%` / `+3.65%` / `—`）。

**验证**：`node --check` EXIT=0；`pytest tests/` **663 passed**；`verify_ui.py` **CN 段全绿（CN-4a~CN-4h + CN-11）**。

**过程中修掉的 3 个我自己的问题（都是验收抓出来的）**
1. **CN-4f 假红（断言竞态）**：等待条件 `#cn-econ ≥ 10 项` 在 rate 组到达前就满足（2+2+3+2+2=11）→ `#cn-rate-list` 只剩「社融」。修法：等待条件加 `#cn-rate-list .mac-var ≥ 4` + 外部 API 重载一次的容错（不放松判据）。
2. **CN-4c 假红（信用利差行没有 title）**：`spreadRow` 的 `.v-chg` 只有「走阔/收窄」文字、无 `title` → 补上。
3. **CN-11 假红（abort 被报成 error）**：**我自己加的"重载一次"容错**会 abort 在飞的 fetch → `console.error` → 被 console-error 断言抓到。修法：`AbortError` 降级为 `console.warn`（页面已用「数据暂缺」表达失败），真错误仍 `console.error`；顺带把 quotes 超时 20s→30s（含中债 8s 取数，冷启动偏紧）。

**⚠️ 提交边界（并行会话）**：`tasks/2026-09-15-crosshair-snap/` 是**另一个会话正在进行**的 crosshair 吸附任务，它已在共享文件里留下未提交改动 —— `web/static/chart-crosshair.js`（91 行）、`tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（315 行，其中含**我的** CN-4f/4g/4h 与 CN 等待修正）。因此本次提交**只含我自己的 4 个文件 + 文档**，`verify_ui.py` 与 `chart-crosshair.js` **不提交**（避免把别人的半成品入库）。`verify_ui` 里唯一剩余失败 `CNC-2` 属该会话的吸附功能（本页 `#cn-chart` 的吸附误差 25px），**不是本次改动引入**（本轮 CN 段其余断言全绿）。

## 下次注意什么

- **改 `src/cn_econ_fetcher.py` 任一解析分支后，先跑 `scripts/probe_cn_macro.py`**（退出码非 0 = 接口停更）再跑单测。
- **新增 AkShare 接口前先实测三件事**：列名（是否属"东财报告族"）、最新数据月份、耗时。耗时 > 20s 的一律不上 Web 路径。
- **`QUADRANTS` 是两个页面共享的常量**：改键或改文案前 grep `build_econ_payload` 与 `build_cn_econ_payload`。
- **`macro.html` / `macro_cn.html` / `macro.js` / `macro_cn.js` 的主题初始化是四份同源代码**：改一处必须改四份（pitfall「主题初始化分叉」）。
- **本页 `#cn-chart-wrap` 的高度由 `.mac-chart-wrap` 的 `clamp()` 提供**：验收 `_expect_chart_wrap_h()` 是从 CSS 定义推导期望值，改 CSS clamp 系数**不需要改断言**；但改容器 class 必须同步。
- **验证一律串行**：`pytest` 与 `verify_ui.py` 同跑会让图表超时/滚动采样假红。
- 本次会话期间外部 auto-commit cron 仍会扫入改动（会话开始时 `docs/pitfalls.md`、`tasks/2026-09-14-context-merge/journal.md` 的既有改动已消失，即被其提交）；核对改动请用 `git log --oneline -- <path>`。
