# 自选股 ETF 数据源链（东财 → 新浪 → 腾讯）— 交接日志

日期：2026-10-12 ｜ 档位：T1（2 文件 / 调用方签名不变 / 行为有变 / 有覆盖测试）

## 目标

消除「自选股 10 行数据暂缺」：ETF 不再单点依赖 Yahoo（本机必须走 Clash 代理）。

## 改动文件

| 文件 | 改动 |
|---|---|
| `src/fetcher.py` | 新增 `_etf_series()`（三源链 + 每源失败 `log.warning`）与 `_etf_quote()`（腾讯实时行情）；ETF 分支改调两者；`_fetch_a_share_watch` docstring 更新 |
| `tests/test_phase24.py` | 新增 `TestAShareWatchSourceChain`（5 条）+ `TestEtfQuoteOverlay`（4 条），不联网（akshare / `_SESSION` 打桩） |
| `AGENTS.md` / `CONTEXT.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` | 数据源、日期口径、验证命令与教训落盘 |
| `tests/test_storage.py` | **顺手修**：`test_export_current_month_overwrites_history_month_frozen` 写死 `2026-08/2026-09` 当"历史月/当月"，2026-10 起必红 ⇒ 改用文件里既有的 `_month_str(-1)/_month_str(0)` |

## 根因（一句话）

ETF 分支主路 `fund_etf_hist_em`（东财 `push2his.eastmoney.com`）自 **2026-09-30** 起每次失败，
被 `except Exception: series = []` 静默吞掉；回退 Yahoo 在本机必须走 Clash（`docs/pitfalls.md`
2026-10-06）⇒ 10 只 ETF 实际全靠 Yahoo+代理，代理一抖（10-12 15:16）自选股整片空。

判据（反推数据源，不用猜）：各期 `data/watchlist.json` 的 ETF 序列长度恒 **483/484**（Yahoo
`range_="2y"`；东财路会被截成 45），走新浪指数路的 399997.SZ 恒 45；且 ETF 末点是**美东日期**。

## 验证结果

| 命令 | 结果 |
|---|---|
| `pytest tests/test_phase24.py -k "SourceChain or EtfQuoteOverlay"`（**改前**，`git stash push -- src/fetcher.py`） | **红 4**（另 5 条改前后都绿：3 条是「三源全挂→Yahoo」「行情解析」「坏报文」守卫/纯函数） |
| 同上（改后） | **绿 9**，3.95s |
| 无代理 `fetch_watchlist(11)`（**闸门 A 回路**） | 改前 `ok=1, err=10` → 改后 **`ok=11, err=0`，8.7s**，ETF 序列 45 点、末点北京 `2026-10-12`，值与腾讯/新浪行情一致 |
| `_etf_quote('515300.SS')` / `('159813.SZ')` | `('2026-10-12', 1.357)` / `('2026-10-12', 0.625)`，与腾讯行情一致 |
| `web.app._load_watchlist()`（快照读取打桩为 None，强制走实时回退；不碰 `data/`） | 11 行全有值，`value=None: []`，`trend.dates` 末点 `2026-10-12` |
| `pytest tests/ -q` | **869 passed, 0 failed**（0:02:16）—— 唯一曾红的 `test_storage` 跨月用例已顺手修（见下） |
| 相关性口径 A/B（真实数据） | ETF 用 Yahoo（美东日期）r = 0.07/-0.23/…/-0.39，n=13；改北京日期后 r = 0.13/0.61/…/0.94，n=15；399997.SZ 恒 0.47/15 |

## 遗留（未做，需用户决定）

1. ~~`tests/test_storage.py` 的跨月定时炸弹~~ —— **已顺手修**（见「改动文件」）：改用 `_month_str(-1)/_month_str(0)`；
   验证：`pytest tests/test_storage.py -q` → 45 passed；注入 `and False` 破坏冻结规则 → `- frozen + written` 1 failed（证明用例非空转）。
2. `analyzer.save_watchlist_snapshot` 只在 values 全 None 时拒绝写盘 ⇒ 1/11 的部分成功会覆盖完整快照，
   看板逐字渲染 ⇒ 仍可能出现「部分行数据暂缺」。修法：部分成功时按标的合并进旧快照（对话里的选项 A）。
3. 东财主路仍留在链首（3s 级开销 + 每次 10 条 warning）。保留原因：它在其它网络可能可用，
   且 warning 是这次能看见问题的关键；若确认长期不可用，可把东财降为第三源或摘掉。
4. 深市指数路（399997.SZ）**没有**实时覆盖 ⇒ A 股午盘快照里它仍显示上一交易日收盘（既有行为，
   本次未动：超出「ETF 换源」范围）。`_etf_quote` 对 `sz399997` 同样可用（实测有数据），要一并修
   只需在指数分支后加同样的 3 行。
5. 行情覆盖的**盘中追加**分支只有单测覆盖（验证时已收盘，历史文件里当日 bar 已存在 ⇒ 走的是
   「同日覆盖」分支）；下一个交易日的 11:30 A 股午盘快照是它的首个真实检验点（判据：ETF 行的
   「最新价」≠ 上一交易日收盘，且 `data/watchlist.json` 里该 ETF 末点日期 = 当天）。

## 下次注意

- 本机 `requests` 因 `NO_PROXY` 环境变量**不走 registry 代理**（`urllib.getproxies()` 只返回
  `{'no': ...}`）；要复现"cron 视角"的 Yahoo 取数得显式 `HTTPS_PROXY=http://127.0.0.1:7890`。
- 排查"数据暂缺"先看**快照文件本身**（`git show <rev>:data/watchlist.json`）与**序列长度/日期口径**，
  再看源端 —— 看板是逐字渲染快照的，源端状态与页面状态可能不同步（本次页面 15:16 空、21:47 已恢复）。
- `git stash push -- <path>` 单文件回退 + 新测试，是"先红后绿"在没有历史红命令时的低成本做法。

## 相关 ADR

无。本次是「换数据源 + 日期口径」的实现决策，三条准入里**「难以撤销」不成立**（`git revert` 即回到
Yahoo 口径，且没有跨会话/跨项目的既定契约被锁死），故按仓库惯例落在 `docs/architecture.md` 关键决策表
（+ `docs/pitfalls.md` 教训 + `CONTEXT.md` 词条），不另立 ADR。
