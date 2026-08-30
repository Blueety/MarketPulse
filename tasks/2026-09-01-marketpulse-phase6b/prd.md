# Task Handoff：MarketPulse 第六期 B — A 股大盘监控

> 复制到 `tasks/2026-09-01-marketpulse-phase6b/prd.md`


## Goal

在六期 A(美股大盘)基础上,增加 A 股(上证指数、深证成指)大盘指数的日度监控,生成包含"美股大盘 + A 股大盘 + 波动率指数"三个板块的合并日报。

## 已确认的设计决策

1. **仅加 A 股** — Yahoo 数据已验证可用(`000001.SS`/`399001.SZ`)。
2. **零新依赖** — 继续走 Yahoo Finance。
3. **复用六期 A 的 streak 趋势机制** — A 股同样用连续涨跌天数。
4. **告警独立** — A 股告警和美股/VIX 告警分开记录。
5. **向下兼容** — 在六期 A 的两板块日报上加第三板块。

## 新增监控标的

| 市场 | 指数 | Yahoo 代码 | 告警阈值 |
|------|------|-----------|---------|
| A 股 | 上证指数 | `000001.SS` | ±4% |
| A 股 | 深证成指 | `399001.SZ` | ±4% |

## 现有标的(保持不变)

| 指数 | Yahoo 代码 | 告警阈值 |
|------|-----------|---------|
| 标普500 | `^GSPC` | ±4% |
| 纳斯达克 | `^IXIC` | ±4.5% |
| VIX | `^VIX` | ±20% |
| VXN | `^VXN` | ±20% |
| MOVE | `^MOVE` | ±15% |

## 报告结构(三板块)

```
# 📊 全市场情绪日报
## 🌏 美股大盘 (标普500 + 纳斯达克)
## 🇨🇳 A 股大盘 (上证指数 + 深证成指)
## 📈 波动率指数 (VIX/VXN/MOVE)
## 🤖 AI 市场解读 (扩展上下文,含7个指数)
```

## Requirements

### 数据获取层
- `src/fetcher.py` — SYMBOLS 5→7(加 `000001.SS`/`399001.SS`), `STOCK_SYMBOLS` 扩展
- 单次运行从 5→7 指数,源间 sleep(2s) 共 12s,仍可接受

### 分析层
- `src/analyzer.py` — A 股趋势复用 `compute_streaks()`/`trend_label()`
- `build_statuses()` 需区分 A 股和美股(都用趋势标签,不走 classify_vix)
- `load_history()` 投影补 `sh`/`sz` 字段
- `build_summary()` 文案扩展

### 报告层
- `src/reporter.py` — 日报增加"A 股大盘"板块(位于美股和波动率之间)
- 趋势图仍保持 VIX/VXN/MOVE 三面板(A 股/美股不入趋势图)

### 告警层
- `src/alerter.py` — A 股告警阈值:SH ±4%, SZ ±4%
- `check_breach()` 大盘分支已支持,只需在 config 中配置阈值

### Config 扩展
```json
{
  "alert": {
    "gspc": 4, "ixic": 4.5,
    "sh": 4, "sz": 4
  }
}
```
env: `ALERT_THRESHOLD_SH`/`ALERT_THRESHOLD_SZ`

### Context 与 AI
- `generate_context()` 扩展,indices 包含 7 个指数
- history_30d 增 `sh`/`sz` 数组
- Hermes prompt 同步(交付清单)

## Constraints

- 零新依赖
- 向下兼容(六期 A 的两板块内容不变)
- A 股休市时显示"休市"(简单规则:值为 None → 显示休市)

## Done When

- [ ] SYMBOLS 扩展为 7 个指数
- [ ] fetcher 获取 7 个指数数据
- [ ] analyzer 大盘趋势复用 streak
- [ ] reporter 日报包含三个板块(美股/A 股/波动率)
- [ ] alerter A 股告警阈值生效
- [ ] history.json 包含 sh/sz 数据
- [ ] context JSON 包含 7 个指数
- [ ] 所有测试通过

## Verification

- [ ] 运行 daily_report.py,检查日志输出 7 个指数
- [ ] reports/*.md 包含三个板块
- [ ] 模拟 A 股休市(值为 None),报告显示"休市"
- [ ] pytest tests/ -v 全绿

## Risks

| 风险 | 应对 |
|------|------|
| Yahoo 对 A 股数据延迟 | 已实测可用(上证 3952/深证 13953),日频够用 |
| A 股节假日判断 | 简单规则(值为 None → 休市),暂不做复杂日历 |
| 报告信息量增大(7 指数) | 保持表格格式简洁 |
| 7 指数拉取超时 | 源间 sleep(2s) 共 12s+请求时间,预计 15-18s,可接受 |