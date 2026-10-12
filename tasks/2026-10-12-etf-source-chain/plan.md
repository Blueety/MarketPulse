# 自选股 ETF 数据源链（东财 → 新浪 → 腾讯）

## 目标

自选股 10 只 A 股 ETF 不再单点依赖 Yahoo（本机必须走 Clash 代理，见 `docs/pitfalls.md` 2026-10-06），
消除「10 行数据暂缺」的复现路径。

## 根因（2026-10-12 取证）

- `src/fetcher._fetch_a_share_watch` 的 ETF 分支主路 = 东财 `fund_etf_hist_em`，回退 = Yahoo。
- 东财 `push2his.eastmoney.com` 自 **2026-09-30** 起每次失败：直连 `RemoteDisconnected`、
  经 Clash `ProxyError`。回退 Yahoo 又需代理。
- 证据：`09-30 / 10-01 / 10-08 / 10-09 / 10-12` 各份 `data/watchlist.json` 的 ETF 序列长度
  一律 **483/484 点**（Yahoo `range_="2y"` 量级），且末点为**美东日期**（北京 10-12 → 10-11）；
  走新浪指数路的 `399997.SZ` 恒为 **45 点 / 北京日期** ⇒ 东财路长期静默失败（`except Exception:
  series = []`），Yahoo 是事实上唯一供数源。
- 15:16 快照只剩 1 只（`18db987`），15:22 cron 自述「10只行业ETF 因 Yahoo 连接被重置获取失败；
  GitHub 自动推送因本机网络 TLS 握手失败」⇒ Clash 抖动 = 自选股 10 行全空。
- 复现（红）：`fetch_watchlist(11)` 无代理 → `ok: 1, err: 10`；带代理 → `ok: 11, err: 0`。

## 涉及文件

| 文件 | 改动 |
|---|---|
| `src/fetcher.py` | 新增 `_etf_series()`：东财 → 新浪 `fund_etf_hist_sina` → 腾讯 `stock_zh_a_hist_tx` 逐个降级；ETF 分支改调它；更新 `_fetch_a_share_watch` docstring |
| `tests/test_phase24.py` | 新增 `TestAShareWatchSourceChain`（4 条，不联网） |
| `AGENTS.md` / `docs/architecture.md` / `docs/pitfalls.md` | 数据源与教训落盘 |

不改：`fetch_watchlist` 签名与返回形状、Yahoo 兜底、`_series_tail`/`_build_watchlist_payload`、
快照写入语义（`save_watchlist_snapshot` 的「部分成功覆盖」是另一件事，见「已知缺口」）。

## 实施步骤

1. `_etf_series(code, symbol, start, end)`：三源按序尝试，任一成功即返回
   `[(北京日期, 收盘), ...]`；全失败抛最后异常（由调用方 `except` → 回退 Yahoo，语义不变）。
   列名映射：东财 `日期/收盘`、新浪与腾讯 `date/close`；日期统一 `%Y-%m-%d`（北京交易日）。
2. 每源失败记一条 `log.warning`（东财静默失败是本次没被及早发现的直接原因）。
3. ETF 分支：`series = _etf_series(...)`（外层 `try/except → series = []` 不动）。
4. **实时行情覆盖 `_etf_quote`**（腾讯 `qt.gtimg.cn`）：新浪/腾讯/东财的**历史文件都是盘后才更新**
   （`hisdata_klc2/klc_kl.js`），盘中拿不到当日 bar ⇒ 不加覆盖的话 A 股午盘快照的「最新价」
   会退化成上一交易日收盘（改源前走 Yahoo 时是盘中实时价 —— 实测 11:45 快照 515300=1.354，
   既非 10-09 收盘 1.338 也非当日收盘 1.357）。同日以行情为准覆盖、行情日期更新则追加。
5. 补测试（见下）。

## 日期口径（有意变更）

三源均为**北京交易日**；Yahoo 回退序列是**美东日期**（日线时间戳取开盘时刻，差一天）。
改为北京口径后：
- 与 `stock_zh_index_daily` 路线（399997.SZ）一致，看板自选趋势图的日期并集不再错位一天；
- 相关性（`compute_portfolio_correlation` 按 date 并入 history）实测变好：11 只的 r 由
  `0.07/-0.23/…/-0.39`（n=13）变为 `0.13/0.61/…/0.94`（n=15），`399997.SZ` 恒 0.47/15 不变。

## 测试 seam

1. `ft._fetch_a_share_watch`（模块函数，akshare 打桩）：源链顺序与降级——东财挂→新浪数据出、
   新浪挂→腾讯数据出、三源全挂→回退 `_fetch_yahoo_watch`；日期对象归一化。
2. `ft._etf_quote`（模块函数，`_SESSION` 打桩）：腾讯报文解析（[3] 当前价 / [30] 时间戳）、坏报文返回 None。
3. `ft._fetch_a_share_watch`（`_etf_series`/`_etf_quote` 打桩）：行情覆盖语义——盘中追加当日 bar、
   同日覆盖、行情落后于历史则忽略。
4. `ft.fetch_watchlist`（公开边界，症状级）：akshare ETF 源可用 + `_fetch_yahoo_watch` 抛异常时，
   仍有值、`errors` 为空 —— 即「Yahoo/代理挂掉不再产生数据暂缺」。

## 验证命令

- `venv/Scripts/python -m pytest tests/test_phase24.py -q -k "SourceChain or EtfQuoteOverlay"`
- `venv/Scripts/python -m pytest tests/ -q`（全量）
- 真实取数（不联网断言）：`venv/Scripts/python -c "from src.fetcher import fetch_watchlist; …"`
  → 无代理环境也应 `ok=11`（ETF 走新浪，不再依赖 Clash）；核对 ETF 序列长度 45、末点北京日期。
- `curl -s localhost:<port>/api/watchlist`（本地看板 as_of/11 行有值）。

## 预估 diff

`src/fetcher.py` +~90/-12；`tests/test_phase24.py` +~150；文档 +~60。

## 已知缺口（本次不做）

`analyzer.save_watchlist_snapshot` 只在 values 全 None 时拒绝写盘 ⇒ 1/11 的部分成功会覆盖完整
快照，看板逐字渲染 ⇒ 仍可能出现「部分行数据暂缺」。修法见对话中的选项 A（部分成功时逐标的合并旧快照）。
