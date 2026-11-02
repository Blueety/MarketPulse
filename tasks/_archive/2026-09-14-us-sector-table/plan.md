# 计划：行业板块表现「美股」tab 表格化（与 A股 同构）+ 取数稳定性修复

- **日期**：2026-09-14
- **任务目录**：`tasks/2026-09-14-us-sector-table/`
- **触发**：需求方截图反馈「美股 tab 显示『数据暂缺』，要与 A股 结构一样」
- **性质**：前端结构改造（主）+ 取数稳定性修复（根因）

---

## 1. 结论先行

截图里那个「数据暂缺」**有两个独立原因叠加**，必须分别处理，否则只做一半仍然看不到东西：

| # | 现象 | 真因 | 性质 |
|---|---|---|---|
| **R1** | 美股 tab 是**条形列表**，与 A股 表格不同构 | `renderUsSectors` 用 `.bar-row`，A股 用 `.data-table` | **确定性改造** |
| **R2** | 今天 `us_sector_heat` **是空的** | **不是取数坏了** —— 直接调用正常返回 5+5 条；是日报运行时**并发超时** | **偶发故障修复** |

**关键澄清**：`fetch_us_sector_heat()` **早就存在，且返回结构与 A 股完全一致**（docstring 与实测都确认）：

```text
实测调用：fetch_us_sector_heat() → gainers: 5, losers: 5
  {'name': '科技 (XLK)',     'change': 1.32, 'turnover': '$1.2B',   'top_stock': 'XLK'}
  {'name': '工业 (XLI)',     'change': 1.07, 'turnover': '$960.9M', 'top_stock': 'XLI'}
  {'name': '通信服务 (XLC)', 'change': 0.99, 'turnover': '$447.8M', 'top_stock': 'XLC'}
```

**所以数据层不用改结构，只需改前端渲染 + 修稳定性。**

---

## 2. 根因分析

### 2.1 渲染表现根因（用户实际看到什么）

点开「行业板块表现 → 美股」，看到居中的灰色「数据暂缺」，且**即使有数据，形态也跟 A股 完全不同**（A股 是紧凑表格，美股是带百分比条的横向条形列表）。

### 2.2 代码逻辑根因

| # | 机制 | 位置 |
|---|---|---|
| **R1** | 两个 panel 用**两套 DOM 结构**：`panel-cn` 是 `table.data-table`（5 列），`panel-us` 是 `div.bar-list`（图标+名称+条形+涨跌幅） | `index.html:170-193`；渲染 `app.js:220-240`（A股）vs `:265-286`（美股） |
| **R2a** | **美股侧请求数是 A股 的 11 倍**：A股 打 1 个新浪请求；美股要打 **11 个 Yahoo 请求**（11 个 SPDR ETF），且每个走**双主机轮换 + `sleep(1)`** | `src/fetcher.py:495-548`、`YAHOO_HOSTS=("query1","query2")`（`:93`） |
| **R2b** | **11 并发已超过 urllib3 默认连接池上限 10** —— 实测警告：`Connection pool is full, discarding connection: query1.finance.yahoo.com. Connection pool size: 10` | 全局 `requests` 默认 adapter |
| **R2c** | **`SECTOR_TIMEOUT = 10` 是最坏路径撑不住的**：11 个并发 ×（2 主机 × sleep(1) + 请求耗时）> 10s → `t.join` 到期 → `any(t.is_alive())` → 返回 `([], [])` | `src/fetcher.py:89`、`:536-544` |

### 2.3 历史证据（证明是偶发，非功能缺失）

```text
2026-08-30 ~ 09-02   us=5  a=5
2026-09-03 / 09-04   us=0  a=0    ← 整体网络故障
2026-09-05           us=0  a=5    ← 仅美股板块失败
2026-09-06 ~ 09-13   us=5  a=5    ← 连续 8 天正常
2026-09-14（今天）    us=0  a=5    ← 仅美股板块失败
```

→ 美股侧**明显比 A股 侧脆弱**（同样的网络环境下，A股 拿到 5 条、美股拿到 0 条）。这与 R2a~R2c 的机制解释吻合。

⚠️ **注意**：`fetch_us_sector_heat` 对超时/异常的契约是 **返回 `([], [])` 且不中断日报**（`:499`），所以这是**静默降级** —— 日报全绿、退出码 0，只有前端空着。这是本次故障能潜伏的原因。

---

## 3. 关键工程约束（决定改造可行性与边界）

CSS 里钉着一条**高度约束注释**（`style.css:453-455`）：

```text
G-9 关键高度约束：右卡默认激活的 A股 tab 里是 4 列表格（thead + 5 行），比美股条形列表高
→ 它决定 .row-3 的行高（stretch 等高）。实测自然内容高 299 → 会顶破 scrollHeight ≤1240 护栏，
故**只**对右卡面板内的表格做紧凑化（不影响其它表格）。
#us-sectors .data-table th { padding: 4px 8px; }
#us-sectors .data-table td { padding: 4px 8px; font-size: 12px; }
#us-sectors .data-table td.chg { padding: 3px 8px; }   /* P-3 零增高对冲 */
```

由此推出两条**硬边界**：

1. ✅ **好消息**：A股 表格已经是**较高的一侧**，且是决定 `.row-3` 行高的那一侧 → **把矮的一侧（美股）改成同构表格，不会增加行高**（`.row-3` 高度由较高者决定，没有变化）。
2. ⚠️ **坏消息**：**行数必须也是 5**。美股现在 `slice(0, 8)`（`app.js:269`）—— 若改成 8 行表格，它会**超过** A股 的 5 行 → 撑高 `.row-3` → **顶破 `scrollHeight ≤1240` 护栏**。必须同步改成 `slice(0, 5)`。

---

## 4. ⚠️ 假绿警告（必须先看这条）

`verify_ui.py` 有 **5 处断言依赖 `.bar-row` 选择器**。表格化之后这些选择器全部返回 **0** —— **不同步修改，`verify_ui.py` 会以"两个面板各自渲染出行数"失败的形式报错；而如果只把断言放宽/删掉，就会变成假绿。**

| 位置 | 现有断言 | 表格化后必须改成 |
|---|---|---|
| `verify_ui.py:149` | `#us-sectors-body .bar-row` 计数 | `#us-sectors-body tr` |
| `verify_ui.py:335` | 同上 | 同上 |
| `verify_ui.py:392` | `usSectorRows >= 1` | 沿用，但选择器换掉 |
| `verify_ui.py:521-522` | `usIcons: '#us-sectors-body .bar-row .ico'` / `usRows` | `#us-sectors-body tr .ico` / `tr` |
| `verify_ui.py:773` | `.data-table .pill, .bar-row .pill` 计数 | 去掉 `.bar-row .pill`（该选择器已无意义） |

**并且应新增一条增益断言**（`:782` 现在的对齐检查只覆盖了 A股）：

```text
['#us-sectors .panel-cn table.data-table', '#us-sectors .panel-us table.data-table', '.watchlist-table']
```

→ 让美股表格也进入「数字列右对齐」检查，否则新表格的对齐问题无人看守。

---

## 5. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/templates/index.html` | 改 `panel-us` 段（`:186-193`） | `.bar-list` → `.table-scroll > table.data-table`，5 列表头，`tbody#us-sectors-body`，骨架屏改 `.sk-row` + `colspan="5"` |
| `web/static/app.js` | 重写 `renderUsSectors`（`:265-286`） | 表格行渲染，`slice(0, 5)`，涨跌幅复用 `.chg-pill`（与 A股 完全一致） |
| `web/static/style.css` | 删约 5 条规则 | `.bar-list` / `.bar-row` / `.bar-name` / `.bar-track` / `.bar-val`（`:511-514`）+ 375 断点的 `.bar-row` 覆盖（`:633`）—— 已确认**只有 `renderUsSectors` 用它们**，可安全删除 |
| `web/static/style.css` | 确认 1 条 | `#us-sectors .data-table td.chg { padding: 3px 8px }`（零增高对冲）需对两个 panel 均生效 |
| `src/fetcher.py` | 改 2~3 处 | 稳定性修复（见 §6 S-1） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 改 5 处 + 加 1 条 | **见 §4，必做** |
| `tests/` | 可能新增 | 美股板块超时/并发相关用例 |
| `tasks/2026-09-14-us-sector-table/plan.md` / `journal.md` | 新增 | 本文件 / 执行记录 |
| `docs/pitfalls.md` | 追加 | 2 条 |

**不改**：`sector_heat`（A股）链路、`generate_context` 的字段契约、`#us-sectors` 的紧凑化 padding 值、tab 的 radio 机制。

---

## 6. 实现步骤（每步可独立验证）

### S-0 · 基线（必测）

```text
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
→ 记录 scrollH@1920 / .row-3 / #us-sectors / #overview / #sectors 高度 / console error
```
⚠️ 不要用历史数字（`frontend-polish` 之后基线已变）。

### S-1 · 取数稳定性修复（根因，R2）

**目标**：让 11 个 ETF 在 10s 内有更高概率全部返回。

| 选项 | 做法 | 评价 |
|---|---|---|
| **①（选）** | 给 Yahoo 请求的 `requests.Session` 挂 `HTTPAdapter(pool_maxsize=16)` | 直接解决"11 并发 > 池 10"的丢弃；改动小 |
| **②（选）** | 美股板块用**独立超时** `US_SECTOR_TIMEOUT = 20`，A股 保持 10 | 不动 A股 行为；最坏路径有足够余量 |
| ③ | 主机切换 `sleep(1)` → `0.3`（仅板块场景） | 进一步压缩最坏耗时 |
| ④ | 降并发（`ThreadPoolExecutor(max_workers=6)` 分批） | 有效但改动较大 |

**推荐 ① + ②**（两处小改，收益最大）。

**验证**：
```text
venv/Scripts/python -c "import logging,time; logging.basicConfig(level=logging.INFO); from src.fetcher import fetch_us_sector_heat; t=time.monotonic(); g,l=fetch_us_sector_heat(); print('ok', len(g), len(l), 'took %.1fs' % (time.monotonic()-t))"
```
→ 连续跑 5 次，应**每次 5+5**，且耗时明显 < 新超时值。

### S-2 · `index.html` — `panel-us` 表格化

把 `panel-us` 改成与 `panel-cn` **完全同构**（同样的 `table.data-table`、同样的 5 列表头、同样的骨架屏），**唯一区别是 `tbody` 的 id**：

```text
<div class="panel panel-us">
  <div class="table-scroll">
    <table class="data-table">
      <thead>
        <tr><th class="col-ico"></th><th>板块</th><th class="num">涨跌幅</th>
            <th class="col-turnover num">成交额</th><th>领涨股</th></tr>
      </thead>
      <tbody id="us-sectors-body">
        <tr class="sk-row"><td colspan="5"><span class="skeleton sk-line"></span></td></tr>
        <!-- ×3，与 panel-cn 一致 -->
      </tbody>
    </table>
  </div>
</div>
```

⚠️ **`colspan` 必须是 5**（与 A股 同构；沿用旧的 6 个 `.sk-bar` 形态会错位）。
⚠️ **不要动 radio / `.tab-labels` 的位置**（`style.css:475-479` 三个坑：radio 不能 `display:none`、必须是 `.tab-panels` 的前置同级兄弟）。

### S-3 · `app.js` — `renderUsSectors` 表格化

改成与 `renderSector` 逐行同构：

```text
function renderUsSectors(latest) {
  const tbody = document.getElementById('us-sectors-body');
  if (!tbody) return;
  tbody.innerHTML = '';
  const gainers = (latest && latest.us_sector_heat && latest.us_sector_heat.gainers) || [];
  if (!gainers.length) {
    tbody.innerHTML = '<tr><td colspan="5">数据暂缺</td></tr>';   // ← 与 A股 同款空态
    return;
  }
  gainers.slice(0, 5).forEach(function (g, i) {                    // ← 8 → 5（见 §3 边界 2）
    const tr = document.createElement('tr');
    tr.innerHTML =
      '<td class="col-ico">' + iconHtml(ICON_PALETTE[i % ICON_PALETTE.length], (g.name || '—').charAt(0)) + '</td>' +
      '<td>' + escapeHtml(g.name || '—') + '</td>' +
      '<td class="num chg"><span class="chg-pill ' + ((g.change || 0) >= 0 ? 'pos' : 'neg') + '">' +
        fmtPct(g.change) + '</span></td>' +
      '<td class="col-turnover num">' + escapeHtml(g.turnover || '—') + '</td>' +
      '<td>' + escapeHtml(g.top_stock || '—') + '</td>';
    tbody.appendChild(tr);
  });
}
```

**与 A股 的唯一差异**（可选、也可统一）：
- A股 `td.chg` 无 `pos/neg` class（只有 `.chg-pill` 带色）；上面写法把 `pos/neg` 放到 `td` 上会**多一层颜色继承**。**建议与 A股 完全一致**（`td.chg` 不带色），减少差异。
- `top_stock`：A股 是股票名（"美迪西"），美股是 **ETF 代码**（"XLK"）。表头「领涨股」对美股语义不准。
  → **建议**：美股 tab 的第 5 列表头改为「代码」，或保留「领涨股」但在 plan 里记录"美股侧实为 ETF 代码"。**推荐后者**（保持两 tab 表头完全同构，代价只是语义略松），若需求方要精确再用「代码」。

### S-4 · `style.css` — 删死代码 + 确认对冲

1. 删除 `.bar-list` / `.bar-row` / `.bar-name` / `.bar-track` / `.bar-val`（`:511-514`）与 375 断点里的 `.bar-row` 覆盖（`:633`）。
   - 已确认全仓库只有 `renderUsSectors` 用它们 → 删完无残留引用。
   - ⚠️ `:773` 的 `verify_ui.py` 断言也引用了 `.bar-row`，**必须同步改**（§4）。
2. 确认 `#us-sectors .data-table td.chg { padding: 3px 8px }` 对 `.panel-us` 也生效 —— 选择器是 `#us-sectors .data-table`，**两个 panel 都在 `#us-sectors` 内 → 自动生效** ✅
3. ⚠️ 检查 `.table-scroll` 是否需要：`panel-cn` 有它包着表格，`panel-us` 也应加上（横向溢出兜底）。

### S-5 · `verify_ui.py` 同步（**不做这步 = 假绿**）

按 §4 表格改 5 处选择器，并新增美股表格的对齐断言。

**新增断言建议**：

| # | 断言 | 期望 |
|---|---|---|
| **U-1** | `#us-sectors-body tr` 数 === 5（有数据时） | 5 |
| **U-2** | `#us-sectors-body` 的父链上是 `table.data-table` | true |
| **U-3** | 切换 tab 后 `.panel-us` 可见且表格行数 ≥1 | true |
| **U-4** | 美股表格 `td.num` 的 `text-align === 'right'` | true |
| **U-5** | `#us-sectors-body` 内**无** `.bar-row` 残留 | 0 |
| **U-6** | **回归**：`scrollH@1920 ≤1240`、`scrollWidth === innerWidth`、console error 0 | 全部成立 |
| **U-7** | 两 tab 表格**行数相同**（都是 5） | 相等（护栏关键） |

### S-6 · 今天的数据怎么办（需决策）

改完 S-1 后，**今天 `context/2026-09-14.json` 里的空值不会自动回填** —— 它是当天日报跑完时写下的。三个选项：

| 选项 | 做法 | 代价 |
|---|---|---|
| **①（保守）** | 不回填，等**明天日报**自然带上 | 今天前端仍显示「数据暂缺」（表格形态正确） |
| ② | **手动重跑** `AUTO_PUSH=0 venv/Scripts/python daily_report.py` | 会重写当日 history/report/context 并**重跑整条取数链**（含 Tavily 资讯）→ 有副作用，需先备份 `data/` |
| ③（治本，建议后续单独立项） | `generate_context` 在 `us_sector_heat` 为空时**沿用上一交易日值并写入 `as_of` 日期**，前端显示「美东 09-11 快照」 | 需改后端契约 + 前端标注；避免"偶发失败 = 整块空白" |

**建议：本次做 ①（结构对了就行），把 ③ 记入 journal 作为后续优化。** 不推荐 ②（副作用大，且 S-1 修好后明天自然恢复）。

### S-7 · 记录

- `tasks/2026-09-14-us-sector-table/journal.md`：S-0 基线数字、S-1 连跑 5 次结果、两 tab 表格截图对比。
- `docs/pitfalls.md` 追加：
  1. **"降级为空"的容错会掩盖故障**：`fetch_us_sector_heat` 超时返回 `([], [])` 且不中断日报 → 日报全绿、退出码 0，只有前端空白。**静默降级必须配可见信号**（日志已在，但需有人看）。
  2. **并发数 > 连接池上限会静默丢连接**：11 个 ETF 线程 vs urllib3 默认 `pool_maxsize=10`，实测警告 `Connection pool is full, discarding connection`。

---

## 7. 复现路径与关键测量点（UI 类必填）

### 7.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8021`（**换新端口**，防 CSS 缓存假阴性）
3. 打开 `http://127.0.0.1:8021/`，硬刷新 `Ctrl+Shift+R`
4. 滚到「行业板块表现」卡 → 点 **美股** tab
5. **现状**：居中的灰色「数据暂缺」；即使有数据也是**条形列表**（图标 + 名称 + 横向条 + 涨跌幅），与 A股 的紧凑表格观感割裂
6. **目标**：美股 tab 是与 A股 **完全一致**的 5 列表格，空态也是表格内一行「数据暂缺」

### 7.2 关键测量点

| 测量点 | 取法 | 基线 / 目标 |
|---|---|---|
| `#us-sectors` `offsetHeight` | DOM | **与改动前一致**（护栏关键） |
| `.row-3` 三卡 `offsetHeight` | `#overview` / `#sectors` / `#us-sectors` | 三者等高，**且不高于基线** |
| `#us-sectors-body tr` 数（美股 tab 激活时） | DOM | **5**（= A股 行数） |
| `#sector-body tr` 数（A股 tab 激活时） | DOM | 5 |
| 两个 `table.data-table` 的 `thead th` 文本 | DOM | **逐列相同** |
| 美股表格 `td.num` 的 `text-align` | `getComputedStyle` | `right` |
| 美股表格 `td` 的 `padding` | `getComputedStyle` | `4px 8px`（继承 `#us-sectors .data-table td`） |
| `#us-sectors-body` 内 `.bar-row` 数 | DOM | **0**（残留检查） |
| **回归：`scrollH@1920`** | `document.documentElement.scrollHeight` | **≤1240** |
| **回归：`scrollWidth === innerWidth`** | — | true |
| **回归：console error** | — | **0** |

### 7.3 box-sizing 说明

`style.css:51` 全局 `* { box-sizing: border-box }`，无例外。

1. **表格化会改变行高构成**：`.bar-row` 是 `grid` + `gap: 6px`（每行约 `18px 内容 + 6px gap`），而 `.data-table td` 是 `padding: 4px 8px`（border-box 下含 padding，行高 ≈ `17.4 + 8 = 25.4px`）。**两者行高不同** → 这是本任务唯一会动高度的机制。
2. **但有 §3 的边界保护**：A股 表格（较高侧）决定 `.row-3` 行高，把美股改成同构**不增加**行高。**前提是行数也必须是 5。**
3. **`.data-table td.chg { padding: 3px 8px }` 是零增高对冲**：`.chg-pill` 高 ≈19px > 12px 文字行高(≈17.4px) → 涨跌幅列上下 padding 从 4 降到 3 抵消。**美股表格的涨跌幅列必须同样是 `td.chg`**，否则该行多出 ~2px × 5 行 = +10px。
4. **`.table-scroll` 的横向溢出**：包上它可防长 ETF 名横向撑破；`overflow-x: auto` 在 border-box 下不改变高度。
5. **骨架屏 `sk-row`**：`.sk-row td { height: 30px }`（`style.css:671`）—— 与真实表格行高（≈25px）**不一致**，加载态→数据态会有 ~5px×5 的收缩。这是**既有行为**（A股 侧同样），本任务只需与新结构保持一致，不引入新偏差。

### 7.4 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | 美股 tab 为 5 行表格，与 A股 逐列同构；`#us-sectors` 高度**不高于基线**；`scrollH ≤1240`；`.row-3` 三卡等高 |
| **1280×720** | 表格列宽收缩但无横向溢出（`.table-scroll` 兜底）；`scrollWidth === 1280`；行数仍 5 |
| **375×812** | 卡片单列；表格在 `.table-scroll` 内可横向滚；删掉 `.bar-row` 的 375 覆盖后**不应出现布局变化**（该元素已无使用者，需目视确认） |
| **双主题** | 表格样式沿用既有 token，无新增颜色；`.chg-pill` 双主题自动生效 |

---

## 8. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **`verify_ui.py` 5 处 `.bar-row` 断言不修 → 假绿** | **高** | §4 逐条同步；U-5 断言 `.bar-row` 残留为 0 |
| **R2** | **美股表格行数 8 > A股 5 → 撑破 `scrollH ≤1240`** | **高** | `slice(0,8)` → `slice(0,5)`；U-7 断言两 tab 行数相等 |
| **R3** | 忘删 `.bar-*` CSS → 死代码累积 | **中** | 已确认无其他使用者；`grep` 复查 |
| **R4** | 新表格漏 `td.chg` → 每行 +2px → 总高 +10px | **中** | §7.3 第 3 点；实测 padding |
| **R5** | 破坏 tab 的 radio 兄弟选择器 | **中** | `style.css:475-479` 三个坑：radio 不能 `display:none`、必须是 `.tab-panels` 前置同级兄弟；`verify_ui.py:388-390` 已有断言看守 ✅ |
| **R6** | 今天数据仍空 → 用户以为没修好 | **中** | §6 S-6 明确说明；改完需**目视确认表格形态正确**，数据留待明日或按选项 ②/③ |
| **R7** | 并发修复不足（Yahoo 主机级封锁） | **中** | S-1 连跑 5 次验证；若仍不稳，追加选项 ③/④ |
| **R8** | 「领涨股」列语义在美股侧不准 | **低** | 已标注（**实为 ETF 代码**）；如需精确改表头为「代码」 |
| **R9** | 重跑 `daily_report.py` 产生副作用 | **中** | §6 S-6：默认不重跑；若重跑必须先备份 `data/` 且带 `AUTO_PUSH=0` |

---

## 9. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `web/templates/index.html` | +约 12 / −10 行 |
| 修改 | `web/static/app.js` | +约 14 / −12 行 |
| 修改 | `web/static/style.css` | −约 6 行（删死代码） |
| 修改 | `src/fetcher.py` | +约 8 / −2 行（连接池 + 独立超时） |
| 修改 | `verify_ui.py` | 改 5 处 / +约 20 行（U-1~U-7） |
| 新增 | `tasks/2026-09-14-us-sector-table/plan.md` / `journal.md` | 本文件 / 执行记录 |
| 追加 | `docs/pitfalls.md` | 2 条 |

**净代码变更估算**：约 **+34 / −30 行**（不含断言与测试）。

---

## 10. 不做什么

- 不改 A股 板块链路（`sector_heat` / `fetch_sector_heat` / `renderSector`）。
- 不改 `fetch_us_sector_heat` 的**返回结构**（已是 A股 同构，无需改）。
- 不改 `generate_context` 的字段契约（回填方案见 S-6 选项 ③，本次不做）。
- 不改 `#us-sectors` 的紧凑化 padding 值（它是护栏保障）。
- 不改 tab 的 radio / label 机制。
- 不重跑 `daily_report.py`（除非需求方明确要求，见 S-6 ②）。

---

## 11. 确认

- [ ] 已确认「数据暂缺」= **结构不同（R1）+ 今天取数偶发失败（R2）** 两件事
- [ ] 已确认**数据层不用改结构**（`fetch_us_sector_heat` 已与 A股 同构）
- [ ] 已确认 **`slice(0,8)` → `slice(0,5)`** 是护栏必需项（R2）
- [ ] 已确认 **`verify_ui.py` 的 5 处 `.bar-row` 必须同步改**，否则假绿（R1）
- [ ] 已确认美股表格的涨跌幅列用 `td.chg`（零增高对冲，R4）
- [ ] 已知悉今天的数据不会自动回填，需按 S-6 决策
- [ ] 已确认 S-0 基线需重测
- [ ] 已确认本地跑 `daily_report.py` 一律 `AUTO_PUSH=0`
