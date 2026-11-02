# 计划：`generate_context` 加合并语义（修复盘中快照清空当日 context）

- **日期**：2026-09-14
- **任务目录**：`tasks/2026-09-14-context-merge/`
- **触发**：需求方在「美股开盘」收到「Yahoo 连接失败，GSPC/IXIC/515300.SS 均无数据」，追查后发现**连接错误只是触发器**，真损害是盘中快照把当天 context 清空
- **性质**：后端数据层（`src/reporter.py` + `snapshot_report.py` + 测试）
- **方案**：需求方已选定 **A · 合并语义**（读旧文件，本次未提供的键保留原值）

---

## 1. 结论先行

**`generate_context` 是全量覆盖写，而盘中快照只取本市场子集 → 每次快照都会把当天其它市场的数据抹掉。**

实测证据（`git show --stat fd0602d`，`auto: 2026-09-14 us open snapshot`）：

```text
 context/2026-09-14.json | 90 +---------------------------------------
 1 file changed, 12 insertions(+), 78 deletions(-)
```

被删掉的不是日志，是**当天的真实 A 股数据**：

| 字段 | 删前（真实） | 删后 |
|---|---|---|
| `sector_heat.gainers` | 医药 +3.23 / 光伏 +0.38 / 资源 +0.09 / 金融 +0.08 / 其他 −0.12 | `[]` |
| `sector_heat.losers` | 地产 −2.3 / 农业 −1.87 / 通信 −0.59 / 军工 −0.46 / 消费 −0.14 | `[]` |
| `search_keywords` | 医药 surge / 光伏 surge / 资源 surge / 金融 surge / 其他 drop | **`["market summary 2026-09-14"]`** |
| `indices.SH/SZ/CYB` | 有值，status="下跌趋势" | `null`，status=**`"休市"`**（09-14 是周一，A 股开市，**这是错的**）|
| `correlation` | 有 | `[]` |
| `watchlist.stocks` | 有 | `[]` |

且已 `auto_commit_push` 提交并推送 → **损害是持久的**。

---

## 2. 根因（三处叠加，缺一不可）

### 2.1 `generate_context` 从零重建、原子全量覆盖，**从不读旧文件**

```936:992:src/reporter.py
    payload = {
        "date": date,
        "indices": {sym: {...} for sym in SYMBOLS},
        ...
        "sector_heat": {"gainers": (sector_heat or ([], []))[0], ...},
        ...
    }
    ...
    tmp.write_text(json.dumps(payload, ...))
    os.replace(tmp, path)          # ← 全量覆盖
```

### 2.2 快照只取本市场子集

```55:56:snapshot_report.py
    values, errors = fetch_all(market)
    sector_heat = fetch_sector_heat() if market == "a-share" else None
```

`fetch_all(market)` 按 `MARKETS` 过滤（`fetcher.py:217-225`）→ `--market us` 的 `values` **只有 `{GSPC, IXIC}`**，A 股 3 键、VIX/VXN/MOVE、GLD/BTC **根本不在里面**。

### 2.3 快照把 `None` 转成了 `[]`，并漏传 3 个参数

```83:84:snapshot_report.py
        generate_context(date, values, changes, statuses, last_values,
                         sector_heat=sector_heat if sector_heat else [])
```

- `sector_heat if sector_heat else []` → us 市场下 `None` 被转成 **`[]`**，语义从"未取数"变成"取到空"
- 另外 `us_sector_heat` / `correlations` / `watchlist` **三个参数根本没传** → 全部落成 `[]` / 空结构

### 2.4 上游隐患：**日期口径不同却撞同一文件**

| 入口 | 日期口径 | 北京 2026-09-14 当天写哪个文件 |
|---|---|---|
| `daily_report.py:125` | `get_us_eastern_date()` | `09-13`（北京 08:00 时美东还是 13 日）|
| `snapshot --market a-share` | `get_market_date("a-share")` = 北京 | **`09-14`** |
| `snapshot --market us` | `get_market_date("us")` = 美东 | **`09-14`** |

→ A 股午盘/收盘快照与美股开盘快照**写同一个 `context/2026-09-14.json`**。这意味着冲突是**每天必然发生**，不是偶发。本次不改日期口径（影响面过大），由合并语义吸收。

---

## 3. 合并语义设计（核心）

### 3.1 总体原则

> **合并「输入」，重算「派生」。**

不能只合并输出 payload —— 因为 `breach` 与 `search_keywords` 是从 `values` 算出来的（`reporter.py:943` / `:980`）。若只在输出层回填，`search_keywords` 仍会退化成 `["market summary …"]`。所以**必须把旧值合并回 `values`/`changes`，再让派生字段自然重算**。

### 3.2 逐字段规则

| 字段 | 判定 | 理由 |
|---|---|---|
| `indices` | **`sym in values` → 覆盖；否则保留旧条目**（`value` + `change_pct` + `status` 整条）| `fetch_all(market)` 天然只放本市场子集的键 → **`values` 的键集本身就是"本次覆盖范围"**，无需额外参数 |
| `sector_heat` / `us_sector_heat` | **`is None` → 保留旧值；非 `None`（含 `[]`、`([], [])`）→ 覆盖** | 区分「本次未取数」与「取了但无数据」 |
| `correlation` / `watchlist` | **`is None` → 保留旧 payload 值；否则重建** | 避免对已过滤/已映射的结构二次加工 |
| `history_30d` | **始终从 `history.json` 读** | 与 market 无关，`merge_history` 已保证同日多市场共存 |
| `breach` / `search_keywords` | **用合并后的 `values` 重算** | 关键：这样才会恢复「医药 surge」这类板块词 |
| `date` | 不变 | —— |

### 3.3 为什么用「键存在」而不是「值非空」

`values["GSPC"] = None`（取数失败）时：

- **用「键存在」** → GSPC 写 `null`（诚实反映本次失败）
- 用「值非空」 → GSPC 保留 08:00 的旧价

选**「键存在」**，因为 GSPC/IXIC **正是本次快照的主题**，报 null 是合理语义；而 SH/SZ/CYB **根本不在 `values` 里**，属于"本次不管"，必须保留。两者能被 `in` 精确区分，这就是选它的原因。

### 3.4 新增开关 `merge`，默认 `False`

```python
generate_context(..., merge: bool = False)
```

- `daily_report.py` → **不传**（`merge=False`）→ **行为逐字节不变，既有测试零改动**
- `snapshot_report.py` → `merge=True`

⚠️ **默认必须是 `False`** —— `tests/test_phase8.py:183-192 TestGenerateContextSector::test_none_falls_back` 直接断言「不传 `sector_heat` → `sector_heat == {"gainers": [], "losers": []}` 且 `search_keywords == ["market summary …"]`」。默认改 `True` 会破坏它。默认 `False` 时**所有既有调用与测试完全不受影响**。

### 3.5 必须同时改 caller

```python
# snapshot_report.py:84  —— 去掉 `if sector_heat else []`
        generate_context(date, values, changes, statuses, last_values,
                         sector_heat=sector_heat, merge=True)
```

`sector_heat is None`（us/alt 市场）→ 合并时保留旧板块数据 ✅
`sector_heat == ([], [])`（a-share 取了但为空）→ 覆盖为空 ✅

**漏了这一步修复就是无效的** —— `[]` 不是 `None`，会被判为"要覆盖"。

### 3.6 旧文件不存在 / 损坏时

`merge=True` 但 `context/{date}.json` 不存在 → **等价于全量写**（不报错、不抛异常）。
旧文件 JSON 损坏 → 记 `log.warning`，退化为全量写（复用 `web/app.py` 的容错精神，不因旧文件坏掉而让快照失败）。
旧文件字段缺失（如无 `indices`）→ 逐字段 `get` 兜底，缺失即不保留。

---

## 4. 要改的文件

| 文件 | 动作 | 说明 |
|---|---|---|
| `src/reporter.py` | +约 55 行 | `generate_context` 加 `merge` 参数 + `_load_prev_context(date)` 容错读 + 逐字段合并 |
| `snapshot_report.py` | −0 / +1 / 改 1 行 | `sector_heat=sector_heat`（去 `if … else []`）+ `merge=True` |
| `daily_report.py` | **不改** | 走默认 `merge=False` |
| `tests/test_context_merge.py` | 新建 | 合并语义专项（见 §5）|
| `tests/test_phase24.py`（或就近） | 可选增 1 条 | us 快照端到端不抹 A 股 |
| `docs/pitfalls.md` | 追加 1 条 | 见 §8 |
| `tasks/2026-09-14-context-merge/journal.md` | 新增 | 执行记录 |

**不改**：`web/app.py` 的 `_find_context_with_key`（它是跨日期兜底，与本次同日合并互补，保留）；`analyzer.py` 的日期口径；`fetch_all` / `MARKETS`。

---

## 5. 实现步骤

### C-0 · 基线
```text
venv/Scripts/python -m pytest tests/ -v          # 记录条数与全绿
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   # 记录 EXIT
```

### C-1 · `reporter.py` 加 `merge`

1. 新增 `_load_prev_context(date) -> dict | None`：读 `CONTEXT_DIR/{date}.json`，不存在 → `None`；`json` 解析失败 → `log.warning` + `None`。
2. `generate_context` 签名加 `merge: bool = False`，函数体开头：
   ```text
   prev = _load_prev_context(date) if merge else None
   if prev:
       values   = _merge_indices(values, prev)     # 键不在 values → 取旧 value/change_pct/status[0]
       changes  = _merge_changes(changes, prev)
       statuses = _merge_statuses(statuses, prev)  # 只回填 status 标签（desc 不入 context）
       sector_heat    = _prev_sector(prev, "sector_heat")    if sector_heat is None    else sector_heat
       us_sector_heat = _prev_sector(prev, "us_sector_heat") if us_sector_heat is None else us_sector_heat
   ```
3. `payload` 里 `correlation` / `watchlist` 改为：
   ```text
   "correlation": <新值> if correlations is not None else (prev.get("correlation", []) if prev else []),
   "watchlist":   _watchlist_context(watchlist) if watchlist is not None else (prev.get("watchlist") or _watchlist_context(None)),
   ```

⚠️ **合并必须在 `collect_breaches` / `build_search_keywords` 之前** —— 否则派生字段拿不到合并后的 `values`。

⚠️ `statuses[sym]` 是 `(label, desc)` 二元组，但 **context 只存 label**。合并时只能回填 label，`desc` 无法从旧文件恢复（不入 context）。文档里写明；`generate_context` 内部只读 `[0]`，安全。

### C-2 · `snapshot_report.py` 改 2 处
```text
generate_context(date, values, changes, statuses, last_values,
                 sector_heat=sector_heat, merge=True)
```
（只动这一行：去 `if sector_heat else []`，加 `merge=True`）

### C-3 · 新增测试 `tests/test_context_merge.py`

| # | 用例 | 期望 |
|---|---|---|
| **M-1** | `merge=True`，先写全量（含 SH 值 + 板块），再用 `values={"GSPC":..,"IXIC":..}` 覆写 | `indices.SH/SZ/CYB` **仍是旧值**、`status` 不再是 `"休市"` |
| **M-2** | 同 M-1，检查 `search_keywords` | **含「医药 surge …」**，不含 `market summary`（← 本任务的核心价值）|
| **M-3** | `merge=True` + `sector_heat=None` | `sector_heat` 保留旧 gainers/losers |
| **M-4** | `merge=True` + `sector_heat=([], [])` | `sector_heat` **被覆盖为空**（"取了但空"必须能覆盖）|
| **M-5** | `merge=True` + `values={"GSPC": None}` | `indices.GSPC.value is None`（**键存在即覆盖**，见 §3.3）|
| **M-6** | `merge=False`（默认）+ 旧文件存在 | **全量覆盖**，与改动前一致 |
| **M-7** | `merge=True` + 旧文件不存在 | 不抛异常，等价全量写 |
| **M-8** | `merge=True` + 旧文件是坏 JSON | 不抛异常，退化为全量写 + 有 warning |
| **M-9** | `merge=True` + `correlations=None` / `watchlist=None` | 保留旧 `correlation` / `watchlist.stocks` |
| **M-10** | a-share 子集反向验证：`values={"SH","SZ","CYB"}` + `merge=True` | `indices.GSPC/IXIC/VIX/VXN/MOVE/GLD/BTC` **保留旧值**（现在这些也会被抹掉）|

⚠️ **先红后绿**：M-1/M-2/M-10 在改动前必须 FAIL。
⚠️ 所有用例用 `monkeypatch.setattr(rep, "CONTEXT_DIR", tmp_path/"context")` 隔离，**不得写真实 `context/`**。
⚠️ M-6 是**回归护栏**：它证明默认路径没被动过。

### C-4 · 端到端：真实快照不抹 A 股
```text
# 在临时目录造一份「全量 context」，再跑 us 快照的等价链路
venv/Scripts/python -c "…generate_context(全量) → generate_context(us子集, merge=True)…"
```
断言：A 股 3 键 + `sector_heat` + `search_keywords` 全部存活。**不允许跑真实 `snapshot_report.py`**（会 `auto_commit_push` 推仓库）。

### C-5 · 验证与记录
```text
venv/Scripts/python -m pytest tests/ -v                                # 全绿（含新增 M-1~M-10）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   # EXIT=0，后端改动不应影响前端断言
```

---

## 6. 风险

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | 默认值改成 `True` 会破 `test_phase8.py:183` 等既有断言 | **高** | `merge` 默认 **`False`**，`daily_report` 不传（§3.4）|
| **R2** | 只在输出层回填 → `search_keywords` 仍退化成 `market summary` | **高** | §3.1「合并输入、重算派生」；**M-2** 断言 |
| **R3** | 漏改 `snapshot_report.py` 的 `if sector_heat else []` → `[]` 被判为"要覆盖"，修复失效 | **高** | §3.5；**M-4** 断言"`([], [])` 能覆盖" |
| **R4** | 合并点放太晚（在 `collect_breaches` 之后）→ breach 与 keywords 仍基于残缺 values | **高** | C-1 明确标注顺序 |
| **R5** | 旧文件损坏导致快照整体失败 | **中** | `_load_prev_context` 全量 try/except → `None`；**M-8** |
| **R6** | 保留旧值 → 展示过期数据（盘面误导）| **中** | 属**同日**保留（与 `web/app.py` 反感的**跨日期**回看不同）；且 `--market us` 时保留的正是当天已取到的 A 股值，比 `null` + `"休市"` 更准确 |
| **R7** | `statuses` 合并丢 `desc` | **低** | **desc 不进 context**（payload 只存 label），无法恢复；`generate_context` 只读 `[0]`；文档写明 |
| **R8** | 测试污染真实 `context/` | **中** | 全部 `monkeypatch CONTEXT_DIR` 到 `tmp_path` |
| **R9** | 顺手跑真实 `snapshot_report.py` 触发 `auto_commit_push` | **中** | C-4 明确禁止；只跑等价函数链路 |

---

## 7. 顺带处置（需需求方确认）

**今天的 `context/2026-09-14.json` 已被破坏并推送**，A 股 10 条板块数据 + 5 条 keywords 只在 git 历史里。两个选项：

- **恢复**：`git show fd0602d^:context/2026-09-14.json` 取回删前版本，再叠加 `411f8f8` 之后的改动 —— ⚠️ 取回的版本也缺 `us_sector_heat`/`correlation`/`watchlist`（那是 A 股快照写的，它本来就没传这三个）
- **不恢复**：等下一次 `daily_report` 自然重写

另有一个**独立异常**待确认：`data/watchlist.json`（21:44）是 `AAPL / 苹果`，而 `config.json:13-15` 是 `515300.SS 红利低波ETF` —— 两者不一致，且 series 只有 2 天（`08-28: 200` → `08-29: 210`），像占位数据。**本计划不处理**，但需要确认是否有人手动改过配置，或存在测试污染真实数据文件。

---

## 8. 待写入 `docs/pitfalls.md`

> **`generate_context` 是全量覆盖，盘中快照必须传 `merge=True`（2026-09-14）**
> `snapshot_report.py` 按 `--market` 只取本市场子集（`fetch_all` 过滤 `MARKETS`），但 `generate_context` 从零重建 payload 后 `os.replace` 全量覆盖 `context/{date}.json` → **A 股快照与美股快照会互相抹掉对方的数据**（日期口径不同却撞同一文件：a-share 用北京日期、us 用美东日期、daily 用美东日期）。
> 实测 `fd0602d`：一次 `us open snapshot` 把 `context/2026-09-14.json` 从 90 行砍到 12 行，删掉 10 条 A 股板块数据、5 条 `search_keywords`，并把 SH/SZ/CYB 写成 `null` + `"休市"`（当天是周一）。
> 修复：`generate_context(..., merge=True)` —— `indices` 按「键是否在 `values` 中」保留旧条目，`sector_heat`/`us_sector_heat`/`correlation`/`watchlist` 按「是否为 `None`」保留旧值，`breach`/`search_keywords` 用合并后的 `values` 重算。**新增调用点若只取市场子集，必须传 `merge=True`，且不得把 `None` 转成 `[]`**（`[]` 会被判为"要覆盖"）。

---

## 9. 不做什么

- 不改 `get_market_date` / `get_us_eastern_date` 的日期口径（§2.4 只记录，影响面过大）
- 不改 `daily_report.py` 调用（默认 `merge=False`，行为零变化）
- 不改 `web/app.py` 的 `_find_context_with_key`（跨日期兜底，与本次互补）
- 不改 `fetch_all` / `MARKETS` / `_yahoo_chart_get` 的双主机轮换
- **不动 `RETRIES`** —— 连接抖动是**另一个独立问题**，不应与本次数据覆盖修复混在一起
- 不引入新依赖、不改 context 的对外契约（键名/结构对 Hermes 保持不变）

---

## 10. 确认

- [ ] 已知悉**根因是覆盖写**，不是 Yahoo 连接错误（连接错误只是触发器）
- [ ] 已知悉 `values` 的**键集**就是"本次覆盖范围"（§3.3），故用 `in` 而非"值非空"
- [ ] 已知悉合并必须发生在 `collect_breaches` / `build_search_keywords` **之前**（R4）
- [ ] 已知悉**必须同时改 `snapshot_report.py` 的 `if sector_heat else []`**，否则修复失效（R3）
- [ ] 已知悉 `merge` 默认 **`False`**，`daily_report` 不传（R1）
- [ ] 已知悉 `statuses` 合并只能回填 label（desc 不入 context）（R7）
- [ ] 已知悉测试必须 `monkeypatch CONTEXT_DIR`，且**禁止跑真实 `snapshot_report.py`**（会 push）（R8/R9）
- [ ] 待确认：今天的 `context/2026-09-14.json` 是否需要恢复（§7）
- [ ] 待确认：`data/watchlist.json`(AAPL) 与 `config.json`(515300.SS) 不一致的来源（§7，独立问题）
