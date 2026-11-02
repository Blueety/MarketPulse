# PRD: 动态告警阈值

## 背景

当前 MarketPulse 的告警系统使用固定阈值判断指数异动（如 S&P500 ±2.5%、创业板 ±5%）。
这些阈值在市场波动率变化时表现不佳：
- 高波动期（VIX 30+）：日常波动就可能触发告警，信噪比低
- 低波动期：显著的异常波动可能被漏掉

## 目标

将固定阈值改为基于历史波动率的动态阈值，使告警灵敏度自适应市场环境。

## 具体需求

1. **滚动窗口计算**：基于过去 N 个交易日（建议 20-30 天）的日收益率标准差
2. **动态阈值公式**：阈值 = rolling_mean + k × rolling_std（k 可配置，默认 2.0）
3. **数据来源**：复用现有的 history.json 数据（已有历史收盘价）
4. **配置兼容**：
   - config.json 中保留原有 `alert` 配置作为 fallback
   - 新增 `alert.dynamic` 开关（默认 true）和 `alert.lookback_days`（默认 20）、`alert.k_factor`（默认 2.0）
   - 当历史数据不足 lookback_days 时，回退到固定阈值
5. **告警输出增强**：在告警 dict 中增加 `dynamic_threshold` 字段，标注本次使用的是动态还是固定阈值
6. **向后兼容**：所有现有测试必须通过，API 接口不变

## 非目标

- 不涉及告警推送渠道的改动
- 不涉及告警去重逻辑的改动
- 不涉及 UI 展示层改动（仅数据层）

## 参考

- 当前阈值定义：`src/config.py` DEFAULTS["alert"]
- 阈值使用处：`src/analyzer.py` check_breach() → alert_threshold()
- 历史数据：`data/history.json`（已有 90 天滚动数据）
