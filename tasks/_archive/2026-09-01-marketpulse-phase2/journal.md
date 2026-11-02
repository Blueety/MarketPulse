# 任务日志 — MarketPulse 二期「盘中感知 + 可视化」

日期：2026-09-01（实施）；执行者按 `tasks/2026-09-01-marketpulse-phase2/plan.md` 实施（架构师 K2.7 已确认，未改架构）。

## 目标

1. 结构演进：`daily_report.py`（300 行）拆为 `src/fetcher.py` + `src/analyzer.py` + `src/reporter.py`，入口变约 70 行编排。
2. 盘中快照：`snapshot_report.py` 独立入口，仅取数 → 分类 → 渲染 → 落盘（不读缓存/不算涨跌幅/不写历史/不推送）。
3. 历史数据：`data/history.json` 按 date 键追加/覆盖、90 天滚动、原子写、损坏容错；`last_values.json` 不变。
4. 趋势图：matplotlib（Agg + 懒加载 + daemon 线程 join(3) 限时）渲染近 30 日图到 `reports/charts/YYYY-MM-DD-trend.png`，报告加「## 📉 近30日趋势」章节，标签全英文。
5. 依赖仅增 `matplotlib>=3.7.0`。
6. 测试迁移（32 → 49）+ 文档同步。

## 改动文件清单

**新增**
- `src/__init__.py`（空包标记）
- `src/fetcher.py`（82 行：SYMBOLS / TIMEOUT / RETRIES / _SESSION / fetch_with_retry / fetch_vix_vxn / fetch_all，纯搬移）
- `src/analyzer.py`（181 行：路径常量 / classify / compute / build_statuses / build_summary / fmt_* / last_values 缓存 / load_history / append_history）
- `src/reporter.py`（177 行：render_report（含趋势章节）/ render_trend_chart / save_report / render_snapshot / save_snapshot）
- `snapshot_report.py`（39 行）
- `tests/test_analyzer.py`（185 行，35 用例：原 27 个纯逻辑迁移 + 8 个 history 新增）
- `tests/test_reporter.py`（148 行，14 用例：原 5 个渲染迁移 + 5 趋势图 + 3 快照 + 1 引用路径）

**修改**
- `daily_report.py`：300 → 69 行编排入口
- `requirements.txt`：+ `matplotlib>=3.7.0`
- `docs/architecture.md`、`docs/commands.md`、`docs/pitfalls.md`、`README.md`、`AGENTS.md`

**删除**
- `tests/test_daily_report.py`（内容按函数归属迁入两个新测试文件）

## 验证结果（全部实际运行）

| 步骤 | 命令 | 结果 |
|---|---|---|
| 装 matplotlib | `pip install -r requirements.txt` | ✅ matplotlib 3.11.1（cp314 有 wheel，无需换版本） |
| Agg 可用 | `python -c "import matplotlib; matplotlib.use('Agg')"` | ✅ |
| 模块导入 | `python -c "from src.fetcher import ...; from src.analyzer import ...; from src.reporter import ..."` | ✅ |
| 全量测试 | `python -m pytest tests/ -v` | ✅ 49 passed（原 32 + 新增 17） |
| 收盘闭环 | `python daily_report.py` | ✅ 退出码 0；断网时报告标注获取失败、history 记 null、缓存不更新；网络恢复后三指数取到真实值（VIX 14.43 / VXN 19.92 / MOVE 70.97） |
| 趋势图 | 播种 30 天历史后重跑 | ✅ `reports/charts/2026-08-29-trend.png` 生成（1100×495 有效 PNG，像素校验含标题/图例/线条），报告含趋势章节引用 `./charts/2026-08-29-trend.png` |
| 快照 | `python snapshot_report.py` | ✅ `reports/snapshots/2026-08-29-noon.md` 生成（MOVE 70.97 取到，VIX/VXN 容错标注） |
| 90 天滚动 | 单测 + 独立脚本（95 条 → 90 条） | ✅ 最早 5 条被滚动掉 |
| 损坏容错 | 单测 + 独立脚本（写入非法 JSON） | ✅ 按空历史处理，可恢复 |
| 行数预算 | `wc -l` | ✅ 三模块 + 两入口 = 548 ≤ 600 |
| 依赖完整性 | `pip check` | ✅ 无 broken requirements |

## 遇到的问题

1. **Yahoo 网络限流（两次运行期间持续）**：首次运行三源全部 `ConnectionResetError(10054)`，第二次运行 VIX/VXN 仍失败但 MOVE 成功。属已知坑（docs/pitfalls.md 已有 429 记录，本次补充 10054 拒连同属限流表现）。脚本按设计容错，退出码恒 0。
2. **视觉模型不可用**：`inspect_image` 报当前模型不支持图像输入，趋势图改用像素级校验（标题区/图例区深色像素量）确认非空白图；标签英文由代码确定性渲染。
3. **验证播种数据的清理**：为验证趋势图端到端临时播种 30 天合成历史，运行后已恢复 `data/history.json` 为真实当日记录（VIX 14.43 / VXN 19.92 / MOVE 70.965）。当日报告与趋势图保留（运行时生成、gitignore 排除），次日真实运行会覆盖。

## 下次注意什么

- **首次/单条历史运行时无趋势图是设计行为**（`render_trend_chart` 排除当日记录且需 ≥2 条），不是 bug，验证趋势图需先积累历史。
- 测试里 monkeypatch 路径常量要打在**使用方模块**（`rep.CHARTS_DIR`），打在 analyzer 上不生效（reporter 导入时已绑定）。
- Hermes 侧配置尚未落地（本次不涉及仓库文件）：① 新增美东 12:30 cron 跑 `snapshot_report.py`；② 收盘 cron 推送时带上 `reports/charts/YYYY-MM-DD-trend.png` 附件。需向用户确认两条 cron 生效。
- `data/history.json` 现只有 2026-08-29 一条真实记录，趋势图要等 9 月积累数日数据后才会出现。
