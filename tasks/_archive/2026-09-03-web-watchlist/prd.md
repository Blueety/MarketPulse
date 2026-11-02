# PRD：Web 看板添加自选股模块

## 目标

在 web 看板中新增「自选股」模块，显示用户在 config.json 中配置的自选股实时数据和近30日趋势图。

## 背景

用户在 config.json 的 `watchlist.stocks` 中配置了自选股（如 515300.SS 沪深300ETF）。`src/fetcher.py` 已有 `fetch_watchlist()` 函数可以获取自选股数据和近30日序列。但 web 看板目前没有展示自选股的模块。

## 需求

### 功能需求

| # | 需求 | 说明 |
|---|------|------|
| F1 | 自选股数据表格 | 显示每只自选股的：名称、当前价、涨跌幅、近30日趋势 |
| F2 | 自选股趋势图 | 可选：与现有趋势图类似的折线图 |
| F3 | 配置驱动 | 从 config.json 读取 watchlist.stocks，无需改代码即可添加/删除自选股 |
| F4 | 无配置时隐藏 | watchlist 为空或不存在时，模块不显示 |
| F5 | 实时取数 | 每次刷新页面时调用 fetch_watchlist() 获取最新数据 |

### 非功能需求

| # | 需求 | 说明 |
|---|------|------|
| NF1 | 最小改动 | 只改 web/app.py 和 web/templates/index.html |
| NF2 | 不引入新依赖 | 复用现有 fetch_watchlist() |
| NF3 | 容错 | fetch_watchlist 失败时显示"数据暂缺"，不影响其他模块 |

## 涉及文件

| 文件 | 改动 |
|------|------|
| `web/app.py` | 新增 `/api/watchlist` 端点 |
| `web/templates/index.html` | 新增自选股模块 HTML + JS |
| `src/config.py` | 确认 watchlist 配置可读 |

## 不改动的文件

- `src/fetcher.py`（已有 fetch_watchlist）
- `config.json`（用户配置）
- `tests/`（需新增测试）
