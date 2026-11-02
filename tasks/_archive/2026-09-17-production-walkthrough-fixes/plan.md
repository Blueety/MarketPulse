# 实施计划：产线走查合理项整改（第二波，小改动）

> **需求来源**：用户提供的《MarketPulse 市场看板 · 前端体验走查报告》（走查对象 = **Railway 产线** marketpulse-blue.up.railway.app，2026-09-17）
> **前置**：上午的 `tasks/2026-09-17-frontend-ux-audit-fixes/plan.md` **已由执行者交付**（`1bbaa7a` 11:08：light 对比度 / 刷新反馈 / 主题初始化 / 抽屉焦点）——本计划只收**产线报告里经核实成立且尚未做**的项
> **基线**：2026-09-17 11:5x，`master` @ `a2224a4`，工作区 **clean**；前置文档均已入库（`frontend-structure.md`、三个任务档已 tracked）
> **本文性质**：方案文档，不含完整可运行代码

---

## 1. 产线报告逐项裁定（先分清「有意占位」与「真缺陷」）

| 报告项 | 裁定 | 依据 |
|---|---|---|
| P0-1 全球市场动态"未接入" | ❌ **不是故障** | `#promo-global` 是**静态占位卡**（有意设计，从无数据源，JS 不碰它）；骨架屏/重试对它无意义 |
| P0-2 趋势"获取失败" | 🟡 部分成立 | 根因是 **G8 上游断供**（Yahoo 403）在产线的表现，不是前端坏了；但"加载中 / 失败 / 无数据三态"确实没做全 → **G4 收** |
| P1-3 自选列表"多出一列红" | 🟡 **定性错了，但有可修点** | 列**不是错位**：表头本来就有 `<th class="col-ico"></th>`（`index.html:95`，留空 th）+ `<th class="col-bar">`；「红」是**图标字符**——无专用 `ICON_CHARS` 时取**名称首字**（`app.js:932-933`：「红利低波ETF」→「红」）。可修点 = 空表头无语义标注（G3） |
| P1-4 资金流向未接入 | ❌ 有意占位 | 全站**唯一** `data-placeholder="1"`，验收断言钉死计数=1 |
| P2-5 相关性文案太技术化 | ✅ 成立 → **G2 收** | `app.js:332` 原文「暂无显著相关对（近30日 \|r\|≤0.5）」——且 `≤0.5` 的写法本身有歧义（规则是"只列出 \|r\|>0.5 的对"） |
| P2-6 双表格无分组标题 | ⚠️ **与实现不符，先核实再动** | 板块是**纯 CSS 双 tab**（`:checked` + 兄弟选择器），同一时刻只显示一张表；"两张表上下紧邻"大概率是走查者把 `.row-3` 的 A 股表与 `#us-sectors` 面板当成并列。**未核实前不改**（改了会破坏 tab 结构与既有断言） |
| 告警"当前值 15.84 vs 顶部 17.71" | ✅ **非数据错误**（已答疑），但暴露措辞缺陷 → **G1 收** | 告警 = `alerts/2026-09-11-close.md`（09-11 收盘 15.84，对 09-10 的 17.84，−11.21%）；顶部 17.71 = 09-16 最新收盘。告警卡**有日期**（`app.js:308`）但「当前值：」措辞无时间锚点 |

---

## 2. 本轮做 4 项（都是小改动）

| 步骤 | 文件 | 内容 |
|---|---|---|
| **G1** 告警卡时间锚点 | `web/static/app.js:310` | 「当前值：」→「告警日收盘（{a.date}）：」；日期已在卡片头部（:308）保留不变。⚠️ `verify_ui` 若有断言读告警卡文本（`alert-meta/.alert-row`），改前 grep 一遍 |
| **G2** 相关性空态文案 | `web/static/app.js:332` | 改为「近 30 日未发现明显联动关系（相关系数 \|r\| 均低于 0.5）」，并给 `<p>` 加 `title` 解释"相关系数：衡量两个指数同涨同跌的程度，0.5 以上算明显"。⚠️ **数字 0.5 必须与过滤规则同源**：`correlation` 键由服务端只收 `\|r\|>0.5` 的对（`generate_context`）→ 代码注释注明来源，禁止出现两个各自为政的 0.5 |
| **G3** 自选列表空表头语义 | `web/templates/index.html:95` | `<th class="col-ico"></th>` → `<th class="col-ico" aria-label="标记"></th>`；`col-bar` 同理。**不改列结构、不改图标 fallback**（首字图标是有意设计；`verify_ui` 对 watchlist 的 colspan=5 断言必须保持） |
| **G4** 趋势卡三态补齐 | `web/static/app.js`、`index.html`、`style.css` | failed 已有（`#home-fail-bar`，昨晚 1bbaa7a）；补 **loading**（fetch 期间趋势卡显示 `.skeleton` 占位）与 **empty**（history 为空/全 null → 复用 `#chart-main-empty` 文案通道，写「暂无趋势数据」而非报错样式）。⚠️ 先**实测** `renderMainChart` 对空 history 的现状行为再动手 |

**明确不做**：P0-1 / P1-4 占位改文案（**需需求方先给接入计划**，前端无依据可写）；P2-6（核实前不动）；后端/数据逻辑。

---

## 3. 实施步骤

1. **Step 1**：G1 措辞（1 行）+ `grep -n "当前值" web/` 确认无第二处。验证：页面看告警卡首行。
2. **Step 2**：G2 文案 + `title`。验证：mock `correlation=[]` → 文案出现且含解释；mock 一条 `|r|=0.7` → pills 正常列出（**不得被新文案分支误伤**）。
3. **Step 3**：G3 两处 `th`。验证：`verify_ui` watchlist 相关断言全绿（colspan=5 不变）。
4. **Step 4**：G4 三态。**先实测**：`page.route` 三种 mock（延迟 / 异常 / `[]` 空数组）记录现状 → 补齐缺口。⚠️ loading 骨架不得改变 `#chart-main-wrap` 高度（`clamp(300px,40vh,460px)` 既有护栏，canvas 位图==显示尺寸断言不能破）。
5. **Step 5**：新增断言先红后绿；`docs/pitfalls.md` 追加一条：「走查报告先分清**有意占位**与**故障**——两者修法完全不同；引用 token/id 前先 grep 实证」。

---

## 4. 验证命令

| # | 命令 | 期望 |
|---|---|---|
| V0 | `node --check web/static/app.js` | 退出码 0 |
| V1 | `venv/Scripts/python -m pytest tests/test_web.py -v` | 全绿 |
| V2 | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **改前先跑**记当日基线；改后失败集 ⊆ 基线 |
| V3 | G1–G4 的 mock 断言 | 先红后绿，带完成标记（`ALL PASSED` / `FAILED: N 条`——**无标记 = 崩溃 = 无效**，`pitfalls` 已有专条） |

---

## 5. 风险

| # | 风险 | 处置 |
|---|---|---|
| R1 | 改告警卡文本撞既有断言 | 改前 grep `当前值`/`alert-row`；断言改**数据驱动**而非写死文案 |
| R2 | G2 文案与过滤规则漂移（D2 同款缺陷："标注写 X、行为做 Y"） | 数字 0.5 注明来源；断言校验文案含"0.5"且 pills 行为不变 |
| R3 | G4 loading 骨架改变主图容器高 → 撞 canvas 位图==显示尺寸断言 | 骨架放 `#chart-main-wrap` **内部**、容器高度不动 |
| R4 | 产线与本机差异被误判 | 本计划的 mock 均在本机验证；产线复核留给下次部署后人工走查 |

---

## 6. 预计影响范围

```
web/static/app.js          +12  −2   G1 措辞 + G2 文案 + G4 三态
web/templates/index.html   +2   −0   G3 aria-label（+G4 若需骨架节点）
web/static/style.css       +4   −0   loading 占位样式（#chart-main-wrap 内限定）
tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   +60  新增断言
docs/pitfalls.md           +4   −0   1 条踩坑
tasks/2026-09-17-production-walkthrough-fixes/           本任务档（plan/journal）
```

**零改动**：`web/app.py`、`src/**`、`tests/**`、`macro*.js`、`chart-crosshair.js`、`_topbar/_sidebar`。
**提交清单**：以上文件 + 本任务档；`git add <具体路径>`，不用 `-A`。
