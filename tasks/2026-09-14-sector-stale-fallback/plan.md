# 计划：板块热度陈旧数据回填（读取端回看 + `as_of` 日期标注）

- **日期**：2026-09-14
- **任务目录**：`tasks/2026-09-14-sector-stale-fallback/`
- **目标（需求方 2026-09-14 选定）**：`us_sector_heat` 为空时沿用上一交易日值 + 写入 `as_of` 日期，前端显示「美东 09-11 快照」，避免"偶发失败 = 整块空白"
- **关联任务**：`tasks/2026-09-14-us-sector-table`（结构表格化 + 取数稳定性）—— 见 §9 串行约束

---

## 1. 结论先行

**好消息：现成机制已存在一半，本任务只需把它从「单判据」改成「逐键独立回看」。**

`web/app.py:259-275` 的 `_load_latest_context()` 已经在做"回看最近一次取数成功的 context"：

```python
sh = ctx.get("sector_heat")
if isinstance(sh, dict) and sh.get("gainers"):
    return ctx                      # 最近一次板块取数成功的交易日
```

**问题**：它以 **A股 `sector_heat`** 作为唯一有效性判据 —— 但两个板块是**同一天同时取的**。今天 A股 成功（a=5）、美股失败（us=0）→ 判据成立 → 返回**今天**的 context → 美股那半边空。

**治本的核心决策：回填做在「读取端」，不做在「写入端」。**

| 方案 | 做法 | 评价 |
|---|---|---|
| 写入端 | `daily_report.py` 取数失败时读上期值，塞进 `context.json` | ❌ 污染 `context.json` 的"当天真实快照"语义；**对今天已写下的文件无效**（需重跑日报）；报告侧也会拿到假数据 |
| **读取端（选）** | `/api/latest` 按**每个板块键各自回看**，返回 `as_of` | ✅ `context.json` 保持诚实；**无需重跑日报即修好今天**；报告侧保持真实（见 §4.3）|

**第二个决策：`as_of` 放在读取端返回的 payload 里，不写回 context。**

---

## 2. 根因分析

### 2.1 渲染表现根因

美股 tab 显示「数据暂缺」，而 A股 tab 正常 —— 用户看到的是"同一个卡片、两个 tab，一个有数据一个没有"。

### 2.2 代码逻辑根因

| # | 机制 | 位置 |
|---|---|---|
| **S-G1** | **回看判据只有一个键**：`_load_latest_context()` 用 `sector_heat.gainers` 判"这份 context 有效"，把 `us_sector_heat` 当附属品一起带走 | `web/app.py:272-274` |
| **S-G2** | **两个板块是同日独立取数、独立失败**：A股 打 1 个新浪请求、美股打 11 个 Yahoo 请求（并发 + 双主机轮换）→ 失败不相关 | `src/fetcher.py:432` vs `:495` |
| **S-G3** | 失败契约是**静默降级**：超时/异常 → `([], [])`，不中断日报、退出码 0 | `src/fetcher.py:499` |
| **S-G4** | `context.json` 忠实记录当天真实值（空就是空）→ 读取端不做回看就必然空白 | `generate_context`（`src/reporter.py:976-979`）|

### 2.3 历史证据（证明两个键确实会各自失败）

```text
2026-09-03 / 09-04   us=0  a=0    ← 两者都失败
2026-09-05           us=0  a=5    ← 仅美股失败
2026-09-06 ~ 09-13   us=5  a=5
2026-09-14（今天）    us=0  a=5    ← 仅美股失败
```

→ **`us=0 a=0` 的行证明：A股 也会失败。** 所以回填**不能只修美股**，两个键都要做 —— 否则 09-03/09-04 那种日子 A股 也会整块空白。

---

## 3. 设计方案

### 3.1 后端：逐键独立回看 + `as_of`

```text
# web/app.py 新增
SECTOR_LOOKBACK_MAX = 5          # 最多回溯几个 context 文件（≈5 个交易日）

def _find_context_with_key(key: str, max_lookback: int = SECTOR_LOOKBACK_MAX):
    """按文件名倒序，找第一个 key.gainers 非空的 context → (ctx, date_stem)。
    超过 max_lookback 仍无 → (None, None)（诚实返回空，不展示过旧快照）。"""
    if not CONTEXT_DIR.exists():
        return None, None
    for i, path in enumerate(sorted(CONTEXT_DIR.glob("*.json"), reverse=True)):
        if i >= max_lookback:
            break
        ctx = _read_context_file(path)
        if ctx is None:
            continue                      # 复用既有坏文件容错
        if not (ctx.get(key) or {}).get("gainers"):
            continue
        return ctx, path.stem             # 文件名 stem 即日期
    return None, None

def _sector_payload(key: str) -> dict:
    """单键独立回看 → {gainers, losers, as_of}。as_of=None 表示无可用数据。"""
    ctx, as_of = _find_context_with_key(key)
    sh = ctx.get(key) if isinstance(ctx, dict) else None
    if not isinstance(sh, dict):
        return {"gainers": [], "losers": [], "as_of": None}
    return {"gainers": sh.get("gainers") or [],
            "losers":  sh.get("losers")  or [],
            "as_of":   as_of}
```

**关键点**：

1. **`_sector_payload` 签名从 `(ctx, key)` 改为 `(key)`** —— 因为 `ctx` 不再由调用方决定。
   ⚠️ 这会破 6 处既有测试（见 §6）。
2. **`_load_latest_context()` 保留不动** —— 它还被 `api_latest` 用于 `indices` 的 `status` 与 `correlation`（`web/app.py:593`），这两者仍该以"A股板块有效"的最近 context 为准（既有行为，不扩大改动面）。
3. **回溯深度受限**：`SECTOR_LOOKBACK_MAX = 5`。超过 → 返回空 + `as_of=None` → 前端「数据暂缺」。**理由**：展示两周前的板块涨跌是误导，宁可空白。

### 3.2 `/api/latest` 返回结构（新增 `as_of`）

```json
{
  "date": "2026-09-14",
  "sector_heat":    {"gainers": [...5], "losers": [...5], "as_of": "2026-09-14"},
  "us_sector_heat": {"gainers": [...5], "losers": [...5], "as_of": "2026-09-11"}
}
```

**判据约定（前端按此渲染）**：
- `as_of === date` → 数据新鲜，**不显示**快照标注
- `as_of !== date` 且 `as_of != null` → **显示**「美东 09-11 快照」
- `as_of == null` → 无可用数据 → 「数据暂缺」

### 3.3 前端：零增高的 `as_of` 标注（**本任务最大的技术约束**）

⚠️ `#us-sectors` 是决定 `.row-3` 行高的那一侧（`style.css:453-455` 钉的注释）。**任何新增行都会撑高 → 威胁 `scrollHeight ≤1240`。**

→ **必须零增高**：把标注放进 `.card-head` 的 `h2` 里作为 `.h2-sub`，与「市场概览 · 最新交易日」同款：

```html
<!-- index.html：现状是 <h2>行业板块表现</h2> -->
<h2>行业板块表现 <span class="h2-sub" id="us-sectors-asof"></span></h2>
```

`.h2-sub` 是行内 span，**不新增行高** ✅

⚠️ **但 `.card-head` 是两个 tab 共用的** —— 光放一个静态文本会误导（只有美股陈旧时，A股 tab 却显示"快照"）。→ 需要 **tab-aware**：

```text
// app.js：缓存两个键的 as_of，随 tab 切换更新文案
var _sectorAsOf = { cn: null, us: null };

function renderSectorAsOf() {
  var el = document.getElementById('us-sectors-asof');
  if (!el) return;
  var which = document.getElementById('sector-tab-us').checked ? 'us' : 'cn';
  var asOf = _sectorAsOf[which];
  var cur = state.latestDate;                     // /api/latest 的 date
  el.textContent = (asOf && cur && asOf !== cur) ? '· 数据截至 ' + asOf : '';
}

// 纯 CSS tab 没有事件 → 给两个 radio 挂 change（各 1 行）
['sector-tab-cn', 'sector-tab-us'].forEach(function (id) {
  var r = document.getElementById(id);
  if (r) r.addEventListener('change', renderSectorAsOf);
});
```

**文案（已定，中性版）**：`· 数据截至 2026-09-11`

位置 = 「行业板块表现」卡片标题右侧、**同一行内的小灰字**，与既有「市场概览 · 最新交易日」（`index.html:129`）同款同位置。**只在数据非当天时出现**：

```text
现状：   行业板块表现                                        查看全部 →
改后：   行业板块表现 · 数据截至 2026-09-11                   查看全部 →
```

为什么不照原话用「美东 09-11 快照」：**A股 也会偶发失败**（09-03/09-04 为 `us=0 a=0`）→ 若 A股 数据陈旧，标注里写"美东"就是错的。中性句式两个市场都成立，且与「市场概览 · 最新交易日」统一。

### 3.4 报告侧（markdown）：**有意保持不变**

`src/reporter.py:92-94`：

```python
us_gainers, us_losers = us_sector_heat or ([], [])
if us_gainers or us_losers:
    us_sector_block = ...        # 空 → 整个「美股板块领涨」章节不渲染
```

→ **报告在数据为空时不渲染该章节**（诚实，不显示假数据）。本任务**不改它**。

**这是有意的不对称**：前端是"持续展示的看板"，空白比陈旧更糟（用户会以为坏了）；报告是"当天快照归档"，必须忠实。**需在 plan 里记录此差异**，避免后人"统一"它。

---

## 4. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/app.py` | 新增 `_find_context_with_key` + `SECTOR_LOOKBACK_MAX`；改 `_sector_payload` 签名与实现；`_load_sector_heat` 适配 | 核心改动 |
| `web/templates/index.html` | 改 1 行 | `h2` 内加 `<span class="h2-sub" id="us-sectors-asof">` |
| `web/static/app.js` | 新增约 18 行 | `_sectorAsOf` 缓存 + `renderSectorAsOf()` + radio `change` 监听 |
| `web/static/app.js` | 改 2 处 | `renderSector(latest)` / `renderUsSectors(latest)` 里写入 `_sectorAsOf` |
| `tests/test_web.py` | **改 6 处** | 见 §6（**必做，否则真红**）|
| `tests/test_web.py` | 新增约 6 条 | 独立回看 + 回溯上限 + `as_of` 语义 |
| `tasks/2026-09-14-sector-stale-fallback/plan.md` / `journal.md` | 新增 | 本文件 / 执行记录 |
| `docs/pitfalls.md` | 追加 | 2 条 |

**不改**：`src/fetcher.py`（取数稳定性属另一任务）、`src/reporter.py`（报告侧有意保持）、`context.json` 的写入契约、`generate_context`、`_load_latest_context`。

---

## 5. 实现步骤

### T-0 · 基线

```text
venv/Scripts/python -m pytest tests/test_web.py -v        # 记录通过数
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
→ 记录 scrollH@1920 / #us-sectors / .row-3 / h2 高度
```

### T-1 · 后端独立回看

按 §3.1 实现。**注意保留 `_read_context_file` 的坏文件容错**（不要另写解析）。

**验证**：
```text
venv/Scripts/python -c "import web.app as w; print(w._sector_payload('us_sector_heat'))"
→ 期望 as_of == '2026-09-13'（最近一个有数据的 context），且 gainers 有 5 条
venv/Scripts/python -c "import web.app as w; print(w._sector_payload('sector_heat')['as_of'])"
→ 期望 '2026-09-14'（今天 A股 有数据）
```
→ **两个 `as_of` 不同，正是本任务要达成的效果。**

### T-2 · `_load_sector_heat` 适配

```text
def _load_sector_heat() -> dict:
    return _sector_payload("sector_heat")
```

### T-3 · 前端标注

按 §3.3 实现。⚠️ 必须确认 `state.latestDate` 存在（或从 `/api/latest` 的 `date` 缓存一份）；若不存在需一并加。

### T-4 · `tests/test_web.py` 同步（**见 §6，不做就是真红**）

### T-5 · 新增测试

| 用例 | 期望 |
|---|---|
| 今天 `us` 空、昨天有 → `_sector_payload('us_sector_heat')` 返回昨天的数据 + `as_of=昨天` |
| 两个键各自回看到**不同**日期 | `as_of` 不同 |
| 超过 `SECTOR_LOOKBACK_MAX` 个文件都空 → `{gainers:[], losers:[], as_of:None}` | 空 + None |
| 目录不存在 | 空 + None（不抛） |
| 最新文件坏 JSON | 跳过继续回看（复用既有容错）|
| `/api/latest` 的 `us_sector_heat` 含 `as_of` | 是 |

### T-6 · 记录

- journal：两个 `as_of` 的实测值、回溯上限的取值理由。
- `docs/pitfalls.md` 追加：
  1. **"整份 context 回看"会掩盖单键失败**：多个同源采集的键必须**逐键独立回看**，否则一个键成功就带回另一个键的空值。
  2. **回填必须在读取端**：写入端回填会污染"当天真实快照"语义，且对已写下的历史文件无效。

---

## 6. ⚠️ 测试破坏清单（必改，否则真红）

`_sector_payload` 签名由 `(ctx, key)` 改为 `(key)`，且返回值新增 `as_of` → **以下 6 处断言会失败**：

| 位置 | 现有断言 | 改成 |
|---|---|---|
| `tests/test_web.py:278` | `_load_sector_heat() == {"gainers": [], "losers": []}` | 允许 `as_of` 键（用子集断言，不整体相等）|
| `tests/test_web.py:283` | 同上 | 同上 |
| `tests/test_web.py:338` | 同上 | 同上 |
| `tests/test_web.py:459` | `lat["sector_heat"] == {...}` | 同上 |
| `tests/test_web.py:460` | `lat["us_sector_heat"] == {...}` | 同上 |
| `tests/test_web.py:826-837` | `test_sector_payload_variants`：5 条调用传 `(ctx, key)` | 改为 `(key)`，并用 `monkeypatch` 设置 `CONTEXT_DIR` 造夹具 |

⚠️ **不要用"去掉断言"来让它变绿** —— 那是把真红改成假绿。正确做法是**改用子集断言**（`assert sh["gainers"] == [] and sh["losers"] == [] and sh["as_of"] is None`）。

---

## 7. 复现路径与关键测量点

### 7.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8022`（**换新端口**）
3. 打开 `http://127.0.0.1:8022/`，硬刷新
4. `curl http://127.0.0.1:8022/api/latest` → 观察两个板块的 `as_of`
5. 滚到「行业板块表现」
   - **现状**：点美股 tab → 「数据暂缺」
   - **目标**：点美股 tab → 5 行**真实数据**（09-13 的值），h2 旁显示 `· 数据截至 2026-09-13`；切回 A股 tab → 标注消失（今天数据新鲜）

### 7.2 关键测量点

| 测量点 | 取法 | 目标 |
|---|---|---|
| `/api/latest` 的 `sector_heat.as_of` | JSON | `2026-09-14`（今天）|
| `/api/latest` 的 `us_sector_heat.as_of` | JSON | `2026-09-13`（最近有数据日）|
| 两个 `as_of` **不相等** | JSON | 是（本任务效果验证）|
| `#us-sectors-body tr` 数（切美股 tab） | DOM | **5**（回填生效）|
| `#us-sectors-asof` 文本 | DOM | A股 tab 空 / 美股 tab 非空 |
| `#us-sectors` `offsetHeight` | DOM | **与改动前一致**（护栏关键）|
| `.row-3` 三卡高度 | DOM | 等高且不高于基线 |
| **回归：`scrollH@1920`** | `document.documentElement.scrollHeight` | **≤1240** |
| **回归：console error** | — | **0** |

### 7.3 box-sizing 说明

`style.css:51` 全局 `* { box-sizing: border-box }`。

1. **`.h2-sub` 是行内 span 在 `h2` 内** → `h2` 高度由 `line-height` 决定，**新增文本不增加行高**（前提：不换行）。✅ 这是选择此位置的根本原因。
2. **⚠️ 换行风险**：`h2` 内有 `h2` 文本 + `.h2-sub` + `.card-head` 里还有「查看全部 →」按钮（`justify-content: space-between`）。文案变长可能在**窄屏（375）触发 h2 换行 → 高度 +~20px → 撑破护栏**。
   → **375 档必须实测**；若换行，降级为只在 `title` 属性里放（tooltip），或缩短文案（如 `· 09-13`）。
3. **`context.json` 与 `as_of` 无关**：`as_of` 只在 API 响应里生成，**不写盘** → 不改变任何文件大小/契约。

### 7.4 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | 美股 tab 5 行真实数据 + h2 旁 `· 数据截至 2026-09-13`；A股 tab 无标注；`scrollH ≤1240`；`#us-sectors` 高度不变 |
| **1280×720** | 同上；h2 与按钮仍同排不换行；`scrollWidth === 1280` |
| **375×812** | **重点验证**：h2 是否换行、标注是否挤压布局；若换行需降级（见 §7.3 第 2 点）|
| **双主题** | `.h2-sub` 沿用既有 token，无新增颜色 |

---

## 8. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **`.h2-sub` 在窄屏换行 → 撑破 `scrollH ≤1240`** | **高** | §7.3 第 2 点；375 实测；必要时缩短文案或改 `title` tooltip |
| **R2** | **改 `_sector_payload` 签名破 6 处测试 → 被"删断言"改绿** | **高** | §6 明确要求改子集断言，不允许删除 |
| **R3** | 回溯过深展示过旧数据（误导） | **中** | `SECTOR_LOOKBACK_MAX = 5`；超限返回空 + `as_of=None` |
| **R4** | 只修美股不修 A股 → 09-03/09-04 那种日子 A股 仍空白 | **中** | 两个键**都**走独立回看（§2.3 证据）|
| **R5** | `state.latestDate` 不存在 → 前端无法判断新鲜度 | **中** | T-3 先确认；不存在则从 `/api/latest` 缓存 |
| **R6** | tab 切换不更新标注（纯 CSS tab 无事件） | **中** | 给两个 radio 挂 `change` 监听（§3.3）|
| **R7** | 报告侧与前端表现不一致被误判为 bug | **中** | §3.4 已记录为**有意设计**，写入 pitfalls |
| **R8** | A股/美股 陈旧时措辞「美东」不对 | **低** | 建议中性文案「数据截至 YYYY-MM-DD」；待需求方确认 |
| **R9** | `_load_latest_context` 被"顺手统一"改动 | **低** | §3.1 第 2 点明确保留它用于 indices/correlation |

---

## 9. 与其他任务的串行约束

| 任务 | 状态 | 关系 |
|---|---|---|
| `2026-09-14-us-sector-table`（表格化 + 取数稳定性） | **未执行** | 两者都改 `renderUsSectors` 与 `#us-sectors`。<br>**顺序已定（需求方 2026-09-14）：先表格化 → 再本任务**。理由：表格化会重写 `renderUsSectors`；本任务在此基础上加 `as_of` 渲染，避免二次改写 |
| 取数稳定性修复 | 同上一任务 | 修好后失败概率降低，但**回填不能省** —— 网络偶发永远存在，且历史文件已存在（09-05/09-14）|

---

## 10. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `web/app.py` | +约 28 / −8 行 |
| 修改 | `web/templates/index.html` | +1 / −1 行 |
| 修改 | `web/static/app.js` | +约 20 / −2 行 |
| 修改 | `tests/test_web.py` | 改 6 处 / +约 55 行（新增用例）|
| 新增 | `tasks/2026-09-14-sector-stale-fallback/plan.md` / `journal.md` | 本文件 / 执行记录 |
| 追加 | `docs/pitfalls.md` | 2 条 |

**净代码变更估算**：约 **+105 / −11 行**（不含测试）。

---

## 11. 不做什么

- **不改 `context.json` 的写入**（保持"当天真实快照"语义；`as_of` 不落盘）。
- **不重跑 `daily_report.py`** —— 本方案在读取端解决，今天即时生效。
- 不改 `src/fetcher.py` 的取数逻辑（属另一任务）。
- 不改 `src/reporter.py` 的报告渲染（空则不渲染章节，**有意保持**）。
- 不改 `_load_latest_context()`（仍供 indices status / correlation 使用）。
- 不做"跨市场混用"（美股陈旧不影响 A股 标注，反之亦然）。

---

## 12. 确认

- [ ] 已确认根因是 **`_load_latest_context` 用单键判据回看**（A股 成功就带走美股的空值）
- [ ] 已确认回填做在**读取端**，不改 `context.json`、不重跑日报
- [ ] 已确认**两个键都做独立回看**（A股 也会失败，§2.3）
- [ ] 已确认 `as_of` **只在 API 响应**，不落盘
- [ ] 已确认**§6 的 6 处测试必须改子集断言**（不许删除断言）
- [ ] 已确认**375 档必须实测 h2 是否换行**（R1 护栏风险）
- [ ] 已知悉**报告侧有意不标注**，与前端不一致是设计（§3.4）
- [x] **文案已定**：中性版 `· 数据截至 2026-09-11`（位置见 §3.3）
- [x] **执行顺序已定**：先 `us-sector-table`（表格化）→ 再本任务
