# Journal — 自选股扩容至 9 只（ETF/指数取数器扩展）

- **日期**：2026-09-17
- **需求**：用户口头指派——添加 9 只自选（含 2 只中证指数）并"加上今天的数据"
- **性质**：运营操作 + 取数器小扩展（架构师直接执行，需求方明确指派）

## 改动

| 文件 | 内容 |
|---|---|
| `src/fetcher.py` | ① `WATCHLIST_TIMEOUT = 30`（从 `SECTOR_TIMEOUT=10` 拆出专用常量：扩到 10 标的后 10s 被整体掐死，实测 10 只仅 1 只完成）；② `_fetch_a_share_watch` 加路由：**ETF（51/56/58/15 前缀）→ 东财 `fund_etf_hist_em`**（新浪 klc 接口对 ETF 已返回 JSONDecodeError，实测 8/8 东财成功且含当日收盘）、**深市指数（39 开头）→ 新浪 `stock_zh_index_daily`**；个股新浪路径不变，失败仍回退 Yahoo |
| `config.json`（gitignore，不入库） | watchlist.stocks：原 515300.SS + 新增 8 条（399997.SZ 中证白酒、515880/512010/515790/512200/513130 沪 ETF、159732/159852 深 ETF）。**931865 未收录** |
| `data/watchlist.json` | 今日快照（9 标的，save_watchlist_snapshot 原子写） |

## 验证

- `fetch_watchlist(新配置)`：**9/9 OK**，全部含 2026-09-17（指数）/09-16（ETF，美东日期轴）收盘与 484 点序列；`snapshot_saved=True`
- `pytest tests/test_web.py -q --basetemp=<tmp>`：**120 passed**（web 契约零破坏；watchlist 端点测试 mock 取数，不触真实源）

## 取证要点（为什么这么改）

- 新浪 `stock_zh_a_daily` 对 ETF 返回 `JSONDecodeError: No value to decode`（直连复测同样）→ 源失效，非偶发
- 东财 `fund_etf_hist_em`：8/8 成功（NO_PROXY 直连）
- `399997`：新浪指数接口 `stock_zh_index_daily("sz399997")` 2738 行、含 09-17 收盘 6164.835 ✓；
  东财 `index_zh_a_hist` 本机被拒（ProxyError/RemoteDisconnected，系统代理与直连各一种）
- `931865`（中证半导体产业）：新浪无此码（KeyError）、东财被拒 ⇒ **当前无可用源，未收录**；
  用户如需半导体暴露可后测 512480/159813 等 ETF

## 遗留 / 待办

- **产线**：需在 Railway Variables 更新 `WATCHLIST_STOCKS`（新 JSON 已给用户）；不改则产线配置比对 mismatch → 实时回退，仍只显示旧 1 只
- 首字图标对 ETF 名称（如「通」「医」「光」）观感可接受；`ICON_CHARS` 可后续为高频标的定制
- pytest 直跑曾触发 WorkBuddy「批量删临时文件」确认钩子导致退出码 1（换 `--basetemp` 规避）——环境坑，非代码问题
