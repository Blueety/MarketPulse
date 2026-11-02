# 方案：组合盈亏（自选列表的成本视角）

> **任务档**：`tasks/2026-09-20-portfolio-pnl/`
> **P1 第 3 个**（P1-1 回测 UI ✅ / P1-2 设置页 ✅ 均已交付；本任务被 P1-2 解锁）
> **角色**：Phase 3 Step 3.3 架构师（只读分析 + 方案，**不含完整实现代码**，不改任何项目文件）
> 实测条件：2026-09-20 21:5x，本机。
>
> ⚠️ 本文档作者是架构师，**不直接改项目代码**。
> ⚠️ 本 plan 已吸取 P1-1 的两处执行裁定教训：**涨跌色沿用全站既有口径（`.up=--green / .down=--red`）**，
> 不再写"红涨绿跌"；navCount 写死处按 `docs/frontend-structure.md` §7-18 的**四处**清单核对。

---

## 0. 结论先行

1. **被 P1-2 解锁**：组合盈亏的输入（成本价）需要一个录入界面——P1-2 的设置页 + `settings_store.py`
   白名单机制正好是现成的入口。本轮只差**扩一个字段**。
2. **数据链路几乎零改动**（实测）：`save_watchlist_snapshot` 存 `dict(s) for s in stocks_cfg`
   —— **原样透传** config 的字段 ⇒ `config.json` 的 `watchlist.stocks[]` 加 `cost` 后，
   快照自动携带，**存储层零改动**。
3. **口径的诚实边界（本 plan 最重要的产品判断）**：**只有成本价、没有份额（shares）**，
   就**只能算每只的盈亏百分比**，算不出盈亏金额、市值、组合加权收益。
   ⇒ MVP 只加 `cost`，汇总用「**有成本标的的等权平均**」并**显式标注**"未含份额"。
   要金额/市值 ⇒ 加 `shares` 字段（§10 D-1，默认本轮不做）。
4. **展示位置**：现有自选卡（`#watchlist-section`）加一列，**不新增页面** ⇒ **零 shell 副本成本**。
5. ⚠️ **`colspan=5` 是硬断言**（`index.html:101-102` P-4，"写 4 会错位"）——加列后**表头、
   数据行、骨架行**共三处都要同步 5→6，`verify_ui` 的 P-4 断言同步。
6. **无成本价的行显示 `—`**：**绝不允许显示 0.00%**（`TL-6`「不显示假 0.00%」同款纪律）——
   "没录成本"和"没亏没赚"是两回事。

---

## 1. 任务目标

**Goal**：自选列表支持录入成本价，展示每只的持仓盈亏（%），以及有成本标的的组合概览。

验收标准：

1. 设置页可为每只自选录入/修改/清除 `cost`（可选字段）
2. 自选卡新增「持仓盈亏」列：`(现价 − cost) / cost × 100%`，**涨跌色沿用全站既有口径**（§0-6）
3. 卡内组合概览：**有成本标的的等权平均盈亏 + 条数**（如「5/11 只已录成本 · 等权 +3.2%」）
4. 无 `cost` 的行显示 `—`（不算 0、不染色）
5. 快照链路（`data/watchlist.json`）自动携带 `cost`，`_load_watchlist` 的**配置比对逻辑不受影响**
6. `colspan` 5→6 三处同步；`pytest` 无新增失败；`verify_ui` 全绿（P-4 更新 + `PF-*` 组）

---

## 2. 实测取证（Step 0，已完成）

| 项 | 实测 | 影响 |
|---|---|---|
| `save_watchlist_snapshot`（analyzer.py:691-706） | `"stocks": [dict(s) for s in stocks_cfg]` **原样透传** | config 加 `cost` ⇒ 快照自动带，**存储层零改动** |
| `_build_watchlist_payload`（web/app.py:518） | 遍历 `stocks_cfg` 组行（symbol/label/value/change_pct） | `cost` 就在同一名 `stocks_cfg` 里，加字段/计算顺路 |
| `_load_watchlist` 配置比对 | 按 **symbol 集合**比对（mismatch → 实时回退） | 加 `cost` **不影响**比对键 ⇒ 无回归（Step 2 验证） |
| 自选卡列 | 5 列（图标/名称/最新价/涨跌幅/迷你条）；**colspan=5 硬断言**（index.html:101-102，P-4） | 加列 ⇒ **三处 colspan + P-4 断言**同步 |
| settings_store schema | `"watchlist.stocks": {"kind": "stocks"}`；`_validate_stocks` 只认 symbol/label | **schema 扩展**：cost 可选字段 |
| 设置页表单 | 已有自选表格（P1-2 交付） | 加「成本价」列 |
| 涨跌色 | 全站 `.up=--green / .down=--red`（绿涨红跌；P1-1 journal §4.1 裁定，无"红涨绿跌"决策记录） | **沿用**，plan 不再写反 |
| 汇总的数据基础 | 无 `shares` 字段 ⇒ **算不出金额/市值/加权收益** | §0-3：MVP 只做百分比 + 等权平均 |

---

## 3. 方案设计

### 3.1 字段与校验

```
watchlist.stocks[] 每项：{ symbol: str(必填), label: str(必填), cost?: number(>0，可选) }
```

- `settings_store._validate_stocks` 扩展：`cost` **可选**、数字、> 0、**清除 = 传 null 或省略**
- 兼容性：旧 config（无 cost）⇒ 读侧一律 `it.get("cost")`，缺失 = None = 不显示盈亏 ✓

### 3.2 盈亏计算放哪：**后端**（`_build_watchlist_payload`）

```
每行：pnl_pct = (value - cost) / cost * 100   # value/cost 任一缺失 → None
概览：covered = 有 cost 且 value 非空的行
      avg_pnl = mean(covered.pnl_pct)          # 等权
      → { covered_count, total_count, avg_pnl_pct }
```

理由：口径单源（前端只渲染）；`value` 在 payload 组装点现成；移动端/未来复用（QQ 推送侧）
都直接受益。**前端不做除法**。

⚠️ **value 的语义**：payload 的 `value` 是「当日收盘价（快照）或实时价（回退）」——
盈亏基于**这个 value**，页面 `#watchlist-asof` 已标注数据时点 ⇒ 盈亏列沿用同一时点，**不另造口径**。

### 3.3 展示

- **列**：第 5 列后加「持仓盈亏」列（`pnl_pct`，色沿用 `cls()` 既有口径；`None` → `—` 不染色）
- **概览**：卡头 `h2` 的 `.h2-sub` 追加（照 `#watchlist-asof` 的行内 span 模式，**零增高**）——
  ⚠️ 不要新增一行，`scrollHeight ≤1240` 护栏在
- **迷你条列保留**（它是涨跌幅分布，与盈亏正交）

### 3.4 设置页表单

- 自选表格加「成本价」输入列（number，空 = 未录）；保存走既有 POST（schema 扩展后自动支持）

### 3.5 快照时序（诚实边界，页面要说明）

`cost` 改动后：**本地看板**立即生效（`/api/watchlist` 读 config 实时回退或快照——快照是上次报告时点的，
**其 stocks 已含新 cost**（透传），但 `values` 是旧价格 ⇒ 盈亏用的是"上次时点价格 × 新 cost"，
`as_of` 已标注）**；Railway** 要等下次报告链路生成新快照（tracked 随部署）。
⇒ 口径区/失败条注明"盈亏基于 `as_of` 时点价格"。

---

## 4. 涉及文件清单

| 文件 | 改动 |
|---|---|
| `src/settings_store.py` | `_validate_stocks` 允许可选 `cost`（数字 > 0 / null） |
| `web/app.py` | `_build_watchlist_payload` 加 `cost` 透传 + `pnl_pct` 计算 + 概览三字段 |
| `web/templates/index.html` | 自选卡表头/骨架 **colspan 5→6**（三处）+ 概览 span |
| `web/static/app.js` | `renderWatchlist` 渲染新列 + 概览；**无 cost → `—`** |
| `web/static/style.css` | `.watchlist-table` 新列宽（窄屏横滚已有） |
| `web/templates/settings.html` + `settings.js` | 自选表格加成本价列 |
| `tasks/.../verify_ui.py` | **P-4 断言 5→6** + 新增 `PF-*` 组 |
| `tests/test_web.py` | payload 契约：有 cost / 无 cost / value 缺失 三态 |
| `tests/test_settings_store.py` | cost 校验用例（合法/负数/null/缺省） |
| `docs/commands.md` / `frontend-structure.md`（列数、§7-18 navCount 四处核对） / `AGENTS.md`（watchlist 字段） |

**不动**：`save_watchlist_snapshot` / `load_watchlist_snapshot`（透传，零改动）·
`_load_watchlist` 比对逻辑 · `fetch_watchlist` 取数 · 快照格式版本（无需 bump）

---

## 5. 实施步骤

1. **schema 扩展**（settings_store cost 校验）+ 单测（红→绿）
2. **payload 计算**（pnl_pct + 概览）+ 契约测试三态
3. **前端列 + 概览**（colspan 三处 5→6 + P-4 断言同步）
4. **设置页成本价列**
5. **`PF-*` 断言**：① 概览数 == 有 cost 行数（API vs DOM 对账）② 无 cost 行渲染 `—` 且**不含 "0.00%"**
   ③ 盈亏色与 `change_pct` 列**同色系**（同为 `cls()` 口径）④ colspan=6
6. **文档**

---

## 6. 验证命令

```bash
venv/Scripts/python -m pytest tests/test_settings_store.py tests/test_web.py -v
venv/Scripts/python -m pytest tests/ -q
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py            # 前台 + timeout 600000
```

**人工**：设置页给 2~3 只录成本 → 保存 → 首页自选卡出现盈亏列与概览；未录的行是 `—`；
把 cost 改成现价 ⇒ 该行盈亏 ≈ 0.00%（此时**允许**显示 0，因为是真实计算值）。

---

## 7. 风险评估

| # | 风险 | 对策 |
|---|---|---|
| R1 | `colspan` 三处漏改一处 ⇒ 骨架错位 | Step 3 点名 `index.html:100/102` 表头与骨架 + P-4 断言 |
| R2 | 无 cost 行被算成 0.00%（口径污染） | `PF-2` 断言 + 后端 None 透传 |
| R3 | `_load_watchlist` 把"加了 cost 的 config"判为 mismatch ⇒ 静默回退实时取数 | 比对键是 symbol 集合（实测确认）；Step 2 加一条回归用例锁死 |
| R4 | 盈亏基于快照旧价被误读为"实时盈亏" | 概览/口径注明 `as_of`；沿用既有标注 |
| R5 | 等权平均被误读为"组合总收益" | 文案显式"等权 · 未含份额"（§0-3） |
| R6 | 用户已有 config 无 cost ⇒ 全列 `—` 显得功能没生效 | 空态文案："在设置页录入成本价后显示" |

---

## 8. 预计影响

修改 ≈9（settings_store / web.app / index.html / app.js / style.css / settings.html / settings.js /
verify_ui / 3 文档）+ 测试 2 · **新增 0 文件** · **不动** 存储层（快照透传）/ 取数 / cron

---

## 9. 明确不做

- ❌ `shares`（份额）/ 金额 / 市值 / 加权收益 —— §10 D-1，默认本轮不做
- ❌ 新页面 / 新持久化 / 新 cron
- ❌ 成本价自动获取（券商 API = 新依赖，违反纪律）
- ❌ 盈亏曲线 / 历史盈亏（需要每日快照累计，另立项）
- ❌ 改涨跌色口径（P1-1 已裁定沿用既有）

---

## 10. 决策裁定（2026-09-20 22:0x，用户已确认：**D-1=A / D-2=A / D-3=A**，全采纳推荐项）

| # | 议题 | 裁定 | 落地 |
|---|---|---|---|
| **D-1** | 只做百分比 vs 加份额 | ✅ **A：只加 `cost`**（每只盈亏% + 等权平均，输入负担最小） | §3.1 |
| **D-2** | 列布局 | ✅ **A：加第 6 列「持仓盈亏」**（迷你条保留；colspan 5→6 三处同步 + P-4 断言更新） | §3.3 |
| **D-3** | 概览位置 | ✅ **A：卡头 `.h2-sub` 行内追加**（零增高，不动 scrollHeight 护栏） | §3.3 |

## 10-bak. 待你拍板（原始三项，已裁定如上）

### 10.1 D-1：只做百分比，还是加份额（shares）算金额

- **A（推荐）**：**只加 `cost`** ⇒ 每只盈亏% + 等权平均。输入负担最小（11 个数字），先验证"你会不会用"
- B：`cost` + `shares` 都加 ⇒ 有金额/市值/加权收益，但输入翻倍且份额会随买卖变动（维护成本高，易失真）

### 10.2 D-2：列布局

- **A（推荐）**：**加第 6 列「持仓盈亏」**（colspan 5→6，迷你条保留）
- B：盈亏替换迷你条列（列数不变、断言不动，但丢掉涨跌幅分布视图）

### 10.3 D-3：概览位置

- **A（推荐）**：卡头 `.h2-sub` 行内追加（零增高）
- B：卡底加汇总行（更醒目，但 +1 行高度，需复测 `scrollHeight` 护栏）
