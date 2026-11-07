# 审查裁决单

## 审查范围

- **固定点**：`git diff HEAD`（= 本任务全部改动，提交前的工作区快照，2026-11-07 11:51 前后）
- **审查者**：独立子 agent（`ReviewOilHistory`），**没有接触主线程的会话历史**
- **给了它什么**：`tasks/2026-11-07-oil-history/prd.md` + `plan.md`、工作区 diff、
  `AGENTS.md` / `docs/architecture.md` / 既有测试；并点名 6 个审查重点（数据源切换、order 重构、
  注册表连带面、测试夹具、闸门断言质量、数据写入）
- **轮次**：第 1 轮

## 审查者原文

### 实跑命令与结果（顶部）

| 命令 | 结果 |
|---|---|
| `git status --porcelain=v1` | 21 文件 staged；`src/reporter.py` 审查中途出现未暂存改动（11:51，另类资产趋势图补 CLF） |
| `node --check web/static/app.js` | exit 0 |
| `ast.parse`（src + scripts/verify + tests 共 43 文件） | 全部 OK |
| `git hash-object data/marketpulse.db` vs HEAD 同路径 | 相同（`2b97acc1…`）⇒ 回填后的 DB 已在 HEAD |
| sqlite 只读 `clf` 统计 | 2515 行、2016-11-07 ~ 2026-11-06、无 NULL；全库 2606 日期 / 27917 行 / 2,318,336 B |
| `_build_history_payload(days=2600, symbols=CLF)` | 2596 个 weekday、2515 有效点、首日 2016-11-07；`days=30` 窗口变化 −2.4406% |
| grep 死代码（`MACRO_CHIP_EXTRAS`/`fetchPointPayload`/`ensureMacro`/`pointMacroKey`/`macroPromise`） | app.js 无残留 |

### 改动摘要

注册表（SYMBOLS/ALT_SYMBOLS/MARKETS/HISTORY_KEYS）+ DB 回填 2515 行 + 前端切 history 源
（删 macro 原油分支、`order` 混排）+ 门禁 TM-5a/13/14/15 对齐 + 14 个测试文件夹具补 CLF + 3 份文档。

### Standards

- 命名 / 依赖 / 错误处理 / 测试隔离 / 禁止项：**无硬违规**
- 坏味道与旧注释（P3）：verify_ui 三处注释、`fetcher.py:46` 派生键说明、`backfill_history.py` 的
  「10 标的」、`CONTEXT.md:33` 的 GLD/BTC 漂移、app.js 删行后的空行

### Spec（对照 prd 验收标准）

1. 点位 10Y 起点 ≤2017-12-31 且 ≥2000 点 → **满足**（实测 2016-11-07 / 2515）
2. 另类资产组顺序 btc→黄金→原油 + 三条都从 100 起 → **满足**（`order` + 同循环 append）
3. 自选 11 chip + 刷新保留 → **满足**（`CUSTOM_KEY_SET` 含 clf）
4. 日报/快照：入 history、不告警、不进波动率板块 → **满足**；但**日报另类资产趋势图漏 CLF**（审查中途已补）
5. 门禁：762 PASS / 1 FAIL(CS-8b) / 2 SKIP → 与 PRD 预期一致（审查者未复跑）

### 独立期望值预言机

- DB 侧（sqlite 只读）与 API 侧（直接调 `_build_history_payload`）互证：2515 点 / 2016-11-07 起；
  `days=30` 窗口变化 −2.4406%（⇒ 图上 `y ≈ 97.5594`，与 TM-13e 对照一致）。
- 局限：TM-13e / TM-15c 的**窗口起点**仍取自图上首点 `x`，不是完全独立。

### 发现清单

| # | 级别 | 位置 | 内容 |
|---|---|---|---|
| 1 | P2 | `src/reporter.py` `history_30d` | context 的 `history_30d` 未含 `clf`，而 `indices` 已按 SYMBOLS 变 11 项 ⇒ 载荷不对称，消费方按 key 取原油静默 undefined（先例：十期加 GLD/BTC 时两处同改） |
| 2 | P2 | `scripts/verify/verify_ui.py` TM-15d | 断言「`symbols=CLF` 请求 ≥1」被**自己的预言机请求**满足 ⇒ 恒真，失去判定力 |
| 3 | P3 | `docs/pitfalls.md` | 本 patch 新增条目与紧邻三条旧规则互相矛盾，旧规则描述的实现均已在本次删除；另有两处数字过时 |
| 4 | P3 | `docs/architecture.md:11` | `alt = GLD/BTC` 过时（应为 GCF/BTC/CLF） |

## 审查者明确未判断的

- Railway 线上 DB 是否随镜像部署；`data/backup/history_*.json` 尚不含 clf（下次日报 `export_monthly_backups` 自愈）
- Hermes 是否真按 `history_30d` 取各标的序列（prompt 在仓库外）
- 曾勾过 macro 原油的用户 localStorage `'cl=f'` 会被新白名单丢弃（本地偏好，可重勾，未列发现）
- DB 数据本身（Yahoo 原始值、91 个无 clf 行是否为 NYMEX 休市）未逐点核对
- 门禁 PASS/FAIL 计数未复跑（审查角色不触发构建）

### 小结

- overall_correctness: **incorrect**（一功能遗漏 + 一门禁自证；主功能本身已实测通过）
- confidence: 0.75

---



## 逐条处理

| # | 审查者发现（原文摘要） | 处理 | 依据 |
|---|---|---|---|
| 1 | **P2** 「context 的 `history_30d` 没有随 SYMBOLS 增加 `clf`，使 context 载荷内部不对称：`indices` 自动变成 11 项，而 `history_30d` 仍是写死的 10 个数组……若确为刻意排除，请在文档写明；否则补一行 `"clf": [r["clf"] for r in history],`」 | **改** | `src/reporter.py` 补 `"clf"` 列 + 注释「手抄清单，新增 HISTORY_KEYS 标的必须补一行」；`tests/test_context.py` 新增不变量「`history_30d` 覆盖 `st.HISTORY_KEYS` 全集且各列与 dates 等长」。**红/绿已实测**：临时删掉该行 → `missing == ['clf']` 失败；恢复后 `tests/test_context.py` 15 passed |
| 2 | **P2** 「TM-15d『原油走常规 /api/history?symbols=CLF 链路』现在恒为真……同一个 `page.evaluate` 先在 `:5538` 自己请求了 `/api/history?symbols=CLF`……修法：在 await 之前先取一次 `historyReqs`（或改成只匹配实现请求的 `days=2720`），再在请求后比较增量」 | **改** | 基线改到「切到 CLF **之前**」取（`before15`），通过参数传进 evaluate；判据只认 `symbols=CLF&days=2720`（= 2600 + `MA_LOOKBACK` 120 的实现请求），断言 `implAfter > implBefore`。实测由 `(1,1)` 恒假变为通过（verify_ui 764 PASS） |
| 3 | **P3** 「本 patch 新增的『原油（CLF）2026-11-07 起是 history 标的』与紧随其上的三条旧规则互相矛盾，而旧规则描述的全部是本 patch 已删除的实现……建议删除或标注『已被取代』；同文件 `1231` 的长表行数/大小/点数也已过时」 | **改** | `docs/pitfalls.md` 删除 3 条旧规则（`macroExtras:["gc=f","cl=f"]` / `MACRO_CHIP_EXTRAS` 与「chip 10 或 11」/ `{value:'CL=F', macro:'cl=f'}`+`fetchPointPayload`/`ensureMacro`），替换为 4 条与现状一致的规则（CLF 入册+三处同源 / 加标的的连带面 / 标签文案与门禁精确匹配 / 门禁不能自证）；数字改为 27917 行、2.3MB、2515 点。grep 确认 `MACRO_CHIP_EXTRAS|ensureMacro|fetchPointPayload` 在 pitfalls 中已为 0 处 |
| 4 | **P3** 「`docs/architecture.md` 第 11 行仍写 `alt = GLD/BTC 另类资产单板块`。本 patch 把 `MARKETS["alt"]` 改为 `{GCF,BTC,CLF}` 后该描述双重过时」 | **改** | 改为 `alt = GCF/BTC/CLF 另类资产单板块`；同时 `CONTEXT.md:33` 的 GLD/BTC 漂移一并更正为 GCF/BTC/CLF |
| 5 | **P3（Standards 坏味道）** 「`verify_ui.py:5402/5461/5495` 三处注释仍写 btc 走 history、gc=f / cl=f 走 macro……描述的是本 patch 已删除的代码路径」「`fetcher.py:46` 应含 clf」「`backfill_history.py` 的『10 标的』」「app.js 空行」 | **部分改** | verify_ui 三处注释、`fetcher.py` 派生键注释、`backfill_history.py` 的「10 标的」与 `--symbols` help 全部改为现状口径；app.js 删行留下的空行**不改**（无行为影响，且下一轮 diff 噪声） |

## 审查者明确未判断的

1. **Railway 线上状态**：DB 是否真随镜像部署（`web/app.py` 旧注释与 AGENTS「`.db` 是 tracked」矛盾）；备份链是否丢 10 年原油。
   → 主线程结论：`.db` 是 tracked 文件、push 即线上数据源（AGENTS 明确，且已验 HEAD 内的 blob 含 2515 行 clf）；
   `data/backup/history_*.json` 缺 clf 由下次日报 `export_monthly_backups()` 自愈，本次不手写生成物。
2. **Hermes 是否真按 `history_30d` 取各标的序列**（prompt 在仓库外）。
   → 主线程结论：无法验证；按「载荷自洽」修复（发现 1）即可，不推测外部消费方行为。
3. **localStorage `'cl=f'` 迁移**：曾勾过 macro 原油的用户刷新后不会自动变成 `clf`。
   → 主线程结论：本地偏好、可重勾；不写只为极少数人生效的迁移分支。已记入 journal「下次注意」。
4. **DB 数据正确性**（Yahoo 原始值、91 个无 clf 行是否为 NYMEX 休市）只核行数/区间/空值。
   → 主线程结论：同 —— 未逐点对源。
5. **门禁 PASS/FAIL 计数**审查者未复跑。
   → 主线程结论：已复跑（见下「结论」）。

## 结论

- 发现 1–4 全部 **改** 并各有回归护栏（发现 1 有红/绿实测）；发现 5 部分改（仅 app.js 空行不改，已说明）。
- 复跑：`pytest tests/ -q` → **884 passed**；`verify_ui.py` → **764 PASS / 1 FAIL / 0 SKIP**
  （唯一 FAIL = 既有临界项 `CS-8b`，与本任务无关）；`verify_offline_assets.py` → ALL PASSED（6 组）。
- 审查者判定 overall_correctness=incorrect 的两条（发现 1、2）均已消除；无未解决的 Critical/P1。
