# 动态告警阈值（二十七期）实现日志

## 目标
为 8 指数告警引入基于历史波动率的滚动窗口动态阈值：样本充足时阈值 = 近 `lookback_days=20` 个相邻日收益均值 + `k_factor=2.0`×样本标准差，样本不足/零方差/负漂移时回退固定阈值。生产（日报/快照/context）与回测均复用同一 `check_breach` 语义。

## 改动文件清单
- `src/config.py`：DEFAULTS.alert 新增 `dynamic=True` / `lookback_days=20` / `k_factor=2.0`；`_merge_valid` 新增 bool 叶值分支（非法值回退默认，不中断加载）。
- `src/analyzer.py`：新增 `_trailing_returns`（最近→最旧相邻日收益，遇 None 中断，截断到 `lookback_days`）、`dynamic_alert_threshold`（纯函数，零方差/样本不足/阈值≤0 → None）；`check_breach(sym, current, last, history=None)` 扩展：history 非空且 `ALERT_DYNAMIC` 时优先动态阈值，`threshold_mode`/`dynamic_threshold` 标注。
- `src/alerter.py`：`collect_breaches` / `run_alert_checks` 新增 `history=None` 透传（默认 None = 全固定，向后兼容）。
- `src/reporter.py`：`generate_context` 调用 `collect_breaches` 前剔除当日行（`[r for r in load_history() if r["date"] != date]`）。
- `daily_report.py`：第 6 参传入 `run_alert_checks`（L122 的 `history` 内存变量，取数后、写历史前，天然不含当日）。
- `snapshot_report.py`：提升 `history = load_history()` 变量并传入 `run_alert_checks`。
- `scripts/backtest.py`：`collect_triggers` 改为窗口化（`history[:i]` 等价于生产「昨日收益是分布最新成员」），触发记录加 `threshold_mode`；`render_report` 新增「动态阈值参数」块、回退阈值表标注、每标的阈值模式分布（dynamic/fixed）。
- `tests/test_phase27.py`：新增 29 条测试（config 新键 + bool 合并 / 纯函数 / 模式标注 / 消费点接线 / 回测窗口化）。
- `docs/commands.md`：追加「动态告警阈值（二十七期）」验证要点。

## 验证结果
- `pytest tests/test_phase27.py -v` → 29 passed。
- 全量回归命令见 Step 9。

## 遇到的问题
1. `test_single_index_failure_isolated`（test_alerter）原 monkeypatch 的 `flaky` 仅接受 3 参；`collect_breaches` 现传第 4 参 `history` → TypeError 被兜底吞掉。按 plan 步3「参数增加不破」原则，将 `flaky` 改为接受 `history=None` 并透传给真 `check_breach`。
2. 编辑 `scripts/backtest.py` 的 per-symbol 块时，`PUT 248-256` 误将 `small = n_points < MIN_SYMBOL_POINTS` 一并覆盖删除，导致 `render_report` 报 `NameError: 'small'`。已补回该行。
3. 测试文件多次因 edit 范围错位产生重复方法 / 错挂 mock（collect_breaches 在 alerter 而非 analyzer；mock 误返回 history 而非 `[]` 导致 generate_context 迭代 history 行触发 `KeyError: 'symbol'`）。最终逐个核对修正。

## 下次注意
- `check_breach` 增加参数后，所有 `monkeypatch` 替身必须同步签名（加 `history=None`），否则被调用点吞异常、测试静默失真。
- 编辑 reporter/backtest 的「变量定义 + 渲染块」相邻区域时，不要用行范围覆盖包含变量定义的块，避免误删局部变量。
- 零方差判定依赖 `statistics.stdev` 抛 `StatisticsError`；浮点近似相等的序列（如精确 +5% 步长）std 非 0，不会触发该分支——测试用例须用全相等价格或真实低方差序列。
- `_trailing_returns` 遇首个 None 即从最新侧截断；「缺口在窗口外」的测试须把 None 放最旧行，而非中间行。
