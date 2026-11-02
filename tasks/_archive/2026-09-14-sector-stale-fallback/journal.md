# 执行记录：板块热度陈旧数据回填（读取端回看 + as_of 标注）

- **日期**：2026-09-14
- **计划**：`tasks/2026-09-14-sector-stale-fallback/plan.md`
- **前置**：`tasks/2026-09-14-us-sector-table`（表格化 + 取数稳定性）已完成 → 本次在其上串行
- **结论**：单判据回看已改成**逐键独立回看**，`as_of` 只在读取端生成、**不落盘**。今天美股 tab **已显示 09-13 的 5 行真实数据**（不再是「数据暂缺」），且两个 `as_of` 实测不等。

---

## 1. 改动清单

| 文件 | 改动 |
|---|---|
| `web/app.py` | 新增 `SECTOR_LOOKBACK_MAX = 5` 与 `_find_context_with_key(key, max_lookback)`（按文件名倒序找第一个 `key.gainers` 非空者 → `(ctx, 日期 stem)`）；`_sector_payload` 签名 `(ctx, key)` → **`(key)`**，返回值增 `as_of`；`_load_sector_heat` 适配；`api_latest` 的两处调用与 `empty_sectors` 同步带 `as_of` |
| `web/templates/index.html` | `<h2>行业板块表现 <span class="h2-sub" id="us-sectors-asof"></span></h2>`（+3 行注释，说明必须留在 h2 内才零增高） |
| `web/static/app.js` | `state.latestDate`；`_sectorAsOf = {cn, us}` 缓存；`renderSectorAsOf()`（按当前 checked 的 radio 选键）；两个 render 里各写一次 `as_of`；`refresh()` 末尾调用；DOMContentLoaded 里给两个 radio 挂 `change` |
| `tests/test_web.py` | **8 处**读取端精确相等断言 → 子集断言（`_assert_sector_empty` 助手）；`test_sector_payload_variants` 改写成基于 `CONTEXT_DIR` 夹具的回看用例；**新增 6 条**用例 |
| `verify_ui.py` | 新增 `assert_sector_asof`（V-1~V-6）与 `assert_asof_narrow`（V-7，375 换行实测）+ 2 张目视截图 |

**未改**（按 plan §11）：`context.json` 的写入、`daily_report.py`、`src/fetcher.py`、`src/reporter.py`、`_load_latest_context()`。

---

## 2. 验证实测

### 2.1 T-1 核心效果（plan 给的命令，实跑）

```
US as_of= 2026-09-13 gainers= 5 losers= 5
  第一名: {'name': '科技 (XLK)', 'change': 1.32, 'turnover': '$1.2B', 'top_stock': 'XLK'}
CN as_of= 2026-09-14 gainers= 5
/api/latest: date=2026-09-14  cn.as_of=2026-09-14  us.as_of=2026-09-13  → 不相等: True
```

**两个 `as_of` 不相等 = 本任务要达成的效果**：A股 用今天（新鲜）、美股回看到 09-13（陈旧且有标注）。

### 2.2 测试

- `pytest tests/test_web.py -q` → **84 passed**
- `pytest tests/ -q` → **554 passed**（上个任务 549 → 净 +5 = 新增 6 条 − 合并 1 条）
- ⚠️ **T-0 缺项，如实记录**：`test_web.py` 的改动前通过数我**没有先取基线**就改了（T-0 只跑了 verify_ui）。事后靠「全量 549→554、0 failed、无新增红」反证无回归，但这不是严格的前后对照。

### 2.3 UI 验收

`FAILED: 5 → 4`（U-\* 12 条 + V-\* 9 条全绿），实测值：

| 测量点 | 实测 | 基线 | 判定 |
|---|---|---|---|
| `scrollH` 1920 / 1280 / 375 | **1216 / 1930 / 2505** | 1216 / 1930 / 2505 | **逐档完全一致** |
| `#us-sectors` 高度（三档） | 249 / 249 / 249 | 249 | 不变 |
| `.row-3` 高度（三档） | 249 / 512 / 821 | 249 / 512 / 821 | 不变 |
| `#us-sectors-body tr`（A股/美股） | **5 / 5** | 5 / 0 | **回填生效** |
| `#us-sectors-asof` 文案（A股 tab） | `''` | — | 数据新鲜→不标注 ✓ |
| `#us-sectors-asof` 文案（美股 tab） | `· 数据截至 2026-09-13` | — | ✓ |
| h2 高度（有标注/无标注） | **19 / 19** | 19 | **零增高** |
| `#us-sectors` 高度（有标注/无标注） | **249 / 249** | 249 | **零增高** |
| 375 档 h2 `clientHeight` / `line-height` | **17 / 17.4** | — | **未换行**（R1 风险未发生） |

**副产品**：上一任务遗留的 `F-1c 美股图标数 == 行数 (0,1)` **自愈**了 —— 回填让美股表格有了 5 行真实数据 + 5 个图标。

### 2.4 目视（`%TEMP%\marketpulse-verify\`）

- `shot-asof-us.png`：美股 tab → **5 行真实数据**（科技 XLK +1.32% / 工业 XLI +1.07% / 通信服务 XLC +0.99% / 可选消费 XLY +0.89% / 房地产 XLRE +0.86%），标题右侧 **「· 数据截至 2026-09-13」**。
- `shot-asof-cn.png`：A股 tab → 5 行今日数据，**标题右侧无标注**（`as_of == date`）。

---

## 3. 实施中与 plan 的差异（3 处，均已核对）

1. **`_find_context_with_key` 的判据写法**：plan 给的是 `if not (ctx.get(key) or {}).get("gainers")` —— 若键值存在但**不是 dict**（如 `"sector_heat": "bad"`），`.get` 会 `AttributeError` 抛出（破坏"永不 500"的容错契约）。已改为 `isinstance(val, dict) and val.get("gainers")`，语义（`gainers` 非空才算有效）不变。
2. **测试破坏清单是 8 处，不是 plan 列的 6 处**：`test_web.py:360`（`test_load_latest_context_all_corrupt`）与 `test_web.py:891`（`test_api_latest_us_sector_heat_degrades`）同为「精确 dict 相等」→ 会真红。已一并改子集断言。
   - 反向核对：plan **未列**的 `tests/test_phase8.py:191` 是同款写法，但它是**写入端**断言（`generate_context` 写出的 context.json），本任务不碰写入端 → **确认不需要改**。
3. **`renderSectorAsOf` 的日期来源**：plan 写 `state.latestDate`，原代码没有这个字段 → 已在 `state` 里新增并在 `refresh()` 里从 `data.date` 赋值（plan T-3 已预判这个缺口）。

---

## 4. 语义变化点（需知悉）

- **`gainers` 为空/None → 整个键降级**（不再单独保留 `losers`）。原因是回看的有效性判据是 `key.gainers`（与 `_load_latest_context` 同口径）。实测 `fetch_*_heat` 成功时两者必然同时非空（同一批结果），该组合只在手写/异常数据里出现；已用 `test_sector_payload_gainers_empty_means_no_data` 把这条语义**钉住**。
- **前端「显示陈旧 + 标注」 vs 报告侧「空则不渲染」是有意的不对称**（plan §3.4）：前端是持续看板（空白比陈旧更糟），报告是当天归档（必须忠实）。`src/reporter.py` 本次**未改**。

---

## 5. 仍未解决的问题（与本次改动无关）

`verify_ui.py` 里写死的日期断言 `check("2026-09-11" in topbarDate, ...)` 导致 **4 条假红**（三视口 + 重复一档），从上一任务起就在。建议改为读 `/api/latest` 的 `date` 前缀。**这是计划外改动，未动**。

---

## 6. 意外与教训

1. **一次 `replace_in_file` 静默丢失**：`test_web.py` 的 `:459-460` 那条编辑工具返回成功，但文件里仍是旧断言（疑似与 auto-commit cron 的 `git add -A` 竞态）。**是靠实跑 pytest 报红才发现的** —— 印证了「不接受'应该可以'，必须实跑」。
2. **程序化改 `radio.checked` 不会触发 `change` 事件**：标注更新依赖 `change` 监听，所以验收脚本里必须 `dispatchEvent(new Event('change'))` 才能测到真实行为（反过来，只改 `.checked` 会得到「标注没更新」的假红）。已写进 pitfalls。
