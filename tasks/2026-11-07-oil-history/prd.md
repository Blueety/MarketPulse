# PRD · 原油（CLF）入册并回填 10 年历史

## 背景
2026-11-07 用户要求把原油接进首页趋势卡（另类资产组 / 自选 chip / 点位视图）。第一版把原油挂在
`/api/macro` 的 5 年深度序列上（`cl=f`）。用户追问「点位图 10Y 只能到 5 年，回填一下」——
macro 链路只取 5 年，无法满足 10 年。

## Goal
原油成为**一等 history 标的**：`SYMBOLS` 增加 `CLF`（`CL=F`），回填 10 年，三个消费点（另类资产组、
自选 chip、点位视图）共用同一份 EOD 序列；同时删掉上一步为 macro 分支写的临时路径。

## 验收标准
1. Given 点位视图选中「原油（WTI）」，When 切到 10Y，Then 起点 ≤ 2017-12-31 且点数 ≥ 2000（回填生效）。
2. Given 另类资产组，When 打开首页，Then 三条线顺序固定 btc → 黄金 → 原油，且都从可见窗口首值 = 100 起算。
3. Given 自选 tab，When 查看 chip，Then 11 个标的（含原油），勾选后刷新仍保留。
4. Given 日报/快照链路，When 运行，Then 原油作为另类资产入 history（不参与告警、不进波动率板块）。
5. Given 全量门禁，When 跑 `pytest` / `verify_ui.py` / `verify_offline_assets.py`，
   Then 除既有 `CS-8b` 临界项与 BLS 配额 SKIP 外全绿。
