# Journal · 原油（CLF）入册并回填 10 年历史

## 目标
原油从「macro 5 年序列」改为「history 10 年标的」，另类资产组 / 自选 chip / 点位视图三处同源。

## 主要提交
（见文末「提交」一节，完成后补）

## 改动文件清单
- 代码：`src/fetcher.py`、`src/storage.py`、`web/static/app.js`
- 门禁：`scripts/verify/verify_ui.py`
- 测试：`tests/{test_analyzer,test_reporter,test_web,test_phase6a,test_phase6b,test_phase7,test_phase8,test_phase12,test_phase14,test_phase24,test_phase25,test_phase26_snapshot,test_phase27,test_us_sector}.py`
- 文档：`docs/{pitfalls,commands,architecture}.md`
- 数据：`data/marketpulse.db`（+clf 2515 行）、`data/history.json`

## 验证结果
- `pytest tests/ -q` → 884 passed
- `verify_ui.py` → 762 PASS / 1 FAIL（既有 `CS-8b` 临界项）/ 2 SKIP（BLS 日配额耗尽，已直连确认）
- `verify_offline_assets.py` → ALL PASSED（6 组）
- 本地实测：点位原油 10Y = 2515 点（2016-11-07 起）、另类资产组 btc→黄金→原油、自选 chip 11 个且刷新保留

## 遇到的问题
1. **新增标的的连带面**：新增一个 SYMBOLS 标的会让 `render_report` 的另类资产表按 `SYMBOLS ∩ ALT_SYMBOLS`
   取行并直接 `values[sym]` 索引 ⇒ 12 处手写字面量夹具全部 KeyError（49 条红）。修法是给夹具补 CLF，
   并把 3 处 `== 10` 改成 `== len(SYMBOLS)` 派生（避免下次加标的再红一遍）。
2. **闸门预言机自身的两个 bug**（都是我这轮写出来的）：① 用 macro payload 的 `values`（整段首值 = 100）
   做窗口比值，得到假红；② 前端标签从「原油」变成「原油（WTI）」后，`label === '原油'` 的查找失效，
   预言机退化成拿 365 天首值当窗口基准（+32.5% vs 图上 −2.44%）。两处都改为按 raw 价 + `startswith('原油')`。

## 下次注意什么
- 往 `SYMBOLS` 加标的 = 一次**跨层**改动：注册表 → 存储键 → 报表板块 → 测试夹具 → 门禁计数。
  先 grep `SYMBOLS`/`len(...) == 10` 把消费点列全，再动手。
  → pitfalls
- 改前端标签文案时，同步检查门禁里所有按 `label ===` 精确匹配的地方（TM-13/TM-15 都踩过）。
  → pitfalls
- 回填 10 年属于不可逆数据写入：先 `wal_checkpoint` + 备份到仓库外，再跑脚本；脚本只写空位。
  → pitfalls

## 涉及的 ADR
无新增（既有 ADR 未被推翻；「黄金走 macro、原油走 history」的分工差异记在 `docs/pitfalls.md`）。

## 下一步
- 观察一次日报 cron 跑完后 `data/marketpulse.db` 的 clf 行是否继续追加（应随日报每日新增一行）。

## 雾区变化
- 解掉的雾区项：原油「10Y 只能到 5 年」——已由回填消除。
- 新增的雾区项：无。

## 一致性走查
- 未到触发条件（在飞任务 5 个 + `tasks/_archive/` 99 个）。

## 结束状态
- 完成（注册表 + 回填 + 前端切源 + 门禁 + 文档）。

## 提交
（提交后补 SHA）
