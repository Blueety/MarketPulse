# 实施计划

> 由 Agent 在只读分析后填写。T1 的档位声明是通知（不等确认），T2 / T3 要人批准后才实施；
> 实施一律交给执行者子 agent，它只读这份文件。

## 任务概要

- **档位**: `T1 — 3 文件 / 0 调用方 / 行为有变 / 有覆盖测试（TM-10 本次新增）/ 预估 40 行`
- **类型**: `bug-可复现` — 均线点数被共享日期轴上的 `null` 吞掉，曲线在缺口处被画成直线
- **目标**: 点位视图 MA20 / MA60 在每个有价格数据的交易日都出点，数值等于「最近 win 个有效观测」的算术均值
- **相关文件**:
  - `web/static/app.js`（`movingAvgPts`）
  - `scripts/verify/verify_ui.py`（新增 TM-10）
  - `docs/pitfalls.md`（模块 web/ 一节追加一条）
- **验证命令**:
  - `venv/Scripts/python.exe scripts/verify/verify_ui.py`
  - `venv/Scripts/python.exe scripts/verify/verify_offline_assets.py`
  - `venv/Scripts/python.exe -m pytest tests/ -q`

## 步骤

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | `movingAvgPts` 改为滚动维护最近 `win` 个非空值 | `web/static/app.js` | 低（单函数、唯一调用点是点位图） | 探针读 dataset 长度：MA20 262 / MA60 222（3Y 窗口） |
| 2 | verify_ui 增加 TM-10：点数契约 + 逐点对预言机 | `scripts/verify/verify_ui.py` | 中：预言机必须与 `buildTradingAxis()` 同轴（只收有值且非周末的日期） | 全量 gate 绿 |
| 3 | pitfalls 记录根因与判据 | `docs/pitfalls.md` | 无 | 闸门断链校验通过 |

## 测试 Seam

- **要测的 seam**: `movingAvgPts` 的输出点集（长度 + 每点 `x`/`y`），通过 `Chart.getChart(canvas).data.datasets[1..2]` 读取；期望值由 `verify_ui` 里**独立重算**的滚动均值提供。
- **公开接口是什么**: 页面上的 DOM（`#chart-main`）+ Chart.js 实例数据；无导出函数。
- **错误与边界**: 缺口（`null`）出现在窗口内；窗口不足 `win` 个有效观测（首段应无点）；周末日期不进轴。
- **为什么选这个 seam**（而不是更浅的那个）: 只看「线看起来平滑」验不出丢点（旧实现画出来也是一条平滑直线）；必须数点并逐点比对数值。

## 修 bug 时必填

- **能变红的命令**: `venv/Scripts/python.exe scripts/verify/verify_ui.py`（TM-10）
- **已实跑的输出**（脱敏后）:
  - 修前（`SH` / 3Y）：`sizes: [281, 154, 49]`，`ma60[0]={x:"2025-12-31"}`, `ma60[1]={x:"2026-07-29"}` ⇒ 一条 7 个月长弦；
  - 修后：`sizes: [281, 262, 222]`，`ma60head=[{2025-12-11},{2025-12-12}]`，最大相邻间隔 11 天（与价格线一致，属节假日）。
- **是否已最小化**: 是。最小复现 = 同一 `raw` 数组上「槽位窗口 vs 有效观测窗口」对比点数。
- **3–5 个排序假设**:
  1. 「窗口内允许 null、只要求 cnt ≥ win」⇒ 含 null 的窗口全部丢弃（实际：MA60 从 299 槽位只剩 49 点，成立）。
  2. 「`dateIndexMap` 缺日期导致跳点」⇒ 只影响轴外日期，不是主因（修后仍有 11 天间隔，与价格线同）。
  3. 「`raw` 与 `dates` 错位」⇒ 若成立，价格线本身会错位（未观察到）。

## 不做什么

- 不改均线颜色（MA60 紫与创业板主色仍撞色，已知，留作单独取舍）。
- 不新增 MA5/MA120 或「按周/月」均线。
- 不动对比视图（`buildLinePts` 的前值填充语义与均线无关）。
- 不做 10 年历史回填（独立步骤，需用户点头）。

## 预估 diff 范围

- 新增文件: `tasks/2026-11-06-fix-ma-gaps/{prd.md,plan.md,journal.md}`
- 修改文件: `web/static/app.js`、`scripts/verify/verify_ui.py`、`docs/pitfalls.md`
- 删除文件: 无

## 确认

- [x] 人已审阅计划（用户直接报告现象并要求「均线可以加上，但计算方法是不是错了」）
- [x] 档位声明与实际文件范围一致
- [x] 文件范围合理
- [x] 没有遗漏测试
- [x] 测试 seam 已写入本节
- [x] 没有引入不必要依赖
