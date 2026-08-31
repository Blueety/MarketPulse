# Task Handoff：MarketPulse 第二十四期 — 持仓/自选股关联

> 复制到 `tasks/2026-09-02-marketpulse-phase24/prd.md`


## Goal

在日报中增加个人持仓/自选股板块,将"大盘监控"和"个人资产"打通。

## 核心功能

1. **自选股配置**:config.json 中新增 watchlist 字段
2. **数据获取**:复用 Yahoo/AkShare 获取自选股数据
3. **日报整合**:新增"📋 自选股/持仓"板块
4. **相关性计算**:计算自选股与大盘指数的相关性
5. **组合风险提示**:若相关性极高提示"组合集中度高"

## Context Pointers

### 需新增/修改的文件

| 文件 | 动作 | 说明 |
|------|------|------|
| `config/config.json` | 修改 | 新增 watchlist 配置 |
| `src/fetcher.py` | 修改 | 新增 fetch_watchlist() |
| `src/analyzer.py` | 修改 | 新增 compute_portfolio_correlation() |
| `src/reporter.py` | 修改 | 日报模板新增板块 |
| `tests/test_analyzer.py` | 修改 | 增加相关性测试 |


## Constraints

- 自选股使用 Yahoo 代码格式
- 优先使用 Yahoo(美股/ETF),A股使用 AkShare
- 相关性窗口:30 个交易日
- 容错:数据获取失败显示"数据暂缺"
- 数量限制:≤20 只


## Done When

- [ ] config.json 新增 watchlist 配置
- [ ] fetch_watchlist() 获取自选股数据
- [ ] compute_portfolio_correlation() 计算相关性
- [ ] 日报新增"📋 自选股/持仓"板块
- [ ] context.json 包含自选股数据
- [ ] AI 解读能引用自选股表现
- [ ] 测试通过
