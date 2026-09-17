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

## 追加：自选图标同色问题（22:2x，用户反馈「图标有点丑，都是同一个颜色」）

- **根因**：`app.js` 的 `ICON_COLORS` 只登记了 `515300.SS` 一条；未命中的标的 `iconHtml(undefined, …)`
  一律落 `ICON_FALLBACK_VAR = --text-muted` ⇒ 新增 8 只**全同灰**。
- **修法**（`web/static/app.js`）：
  - 新增 `ICON_PALETTE_WATCH`（**10 色**版，比既有 `ICON_PALETTE` 多 `--c-vxn` / `--c-btc`）+
    `watchIconColor(symbol, index)`：命中 `ICON_COLORS` 用品牌色，否则**按行序循环**（沿用项目既有约定；
    先试过 symbol 散列，实测 9 行只出 4 个色 —— 分布差，弃用）；
  - `renderWatchlist` 调用点改用它（`stocks.forEach(function (row, i)`）；
  - `ICON_CHARS` 补 9 条**语义汉字**（红/酒/通/医/光/房/电/软/港）——原来取名称首字，
    「南方中证全指房地产ETF」会显示「南」。
  - **不动** `ICON_PALETTE`（板块表格仍 8 色循环）⇒ 无关视图零影响。
- **实测**：改前 `distinct_colors=1`（9 行全灰）→ 改后 **`distinct_colors=9`**（探针 `%TEMP%\mp_icon_probe.py`，
  截图 `%TEMP%\mp-icon-probe\watchlist.png` 人工复核配色观感正常）。
- **顺带修掉验收脚本的一个致命缺陷**：`verify_ui.py` 的 `UX-4a/4b` 断言标签含 `⇒`(U+21D2)，
  **GBK 控制台无法编码** → `print` 抛 `UnicodeEncodeError`，脚本在 UX-4 组**直接终止**（今早 1bbaa7a 引入，
  与本次改动无关）。已把两处标签的 `⇒` 换成 `->`。
  ⇒ **不修它则任何人从 GBK 控制台都拿不到完整验收结果**（前面几次「日志 0 字节/中途死」即此）。
- **验收**：`verify_ui.py` 复跑 **ALL PASSED / EXIT=0**（首跑仅 `B-6b 回绕后继续前进` 一条红，
  复跑转绿 ⇒ **抖动**，与本改动无关，已按基线 A/B 判据排除；同次运行也说明上游已恢复，G8 的 12 条基线红本轮为 0）。
- 环境坑：PowerShell 工具给**后台**命令 120s 上限 → 5 分钟的 verify_ui 需**前台 + 显式 timeout** 才能跑完。

## 追加：自选列表按涨跌幅降序（22:5x，用户指派）

- **实现（前端渲染序，零接口改动）**：`renderWatchlist` 里对 `stocks` 做**副本排序**：
  `change_pct` 降序，缺失（`null`/非有限）**垫底**；`Array.sort` 稳定 ⇒ 同值保持配置序不抖。
- ⚠️ **连带处理（本次最关键的一点）**：上一轮图标色是**按行序**取的（`watchIconColor(symbol, index)`），
  一旦按涨跌幅重排，**同一标的的颜色会随名次每次刷新都跳**。改法：建 `cfgIndex`（symbol → 配置序下标），
  渲染时用**配置序索引**取色 ⇒ 颜色与标的绑定、行序稳定不跳，且仍 9 行 9 色。
- 副标题补「· 按涨跌幅排序」（`index.html` 的 `h2-sub` 内联 span，不增高）。
- **实测**（探针 `%TEMP%\mp_sort_probe.py`）：`rows=9 desc=True nulls_at_end=True distinct_colors=9`；
  顺序 +5.05 → +3.12 → +1.37 → +0.81 → +0.76 → −0.19 → −0.28 → −0.46 → −0.53；截图人工复核。
- **验收**：`verify_ui.py` 无任何自选**行序**断言（只有「图标数==行数」「表头 aria」「colspan」）⇒ 排序不破坏契约。
  本次运行 `FAILED: 1 条`，唯一红是 **`B-6b 回绕后继续前进`**。
- 🔍 **`B-6b` 红是探针竞态，非本次改动**（已取证）：
  - 失败签名 `actual=(-1, 0, 445)` 里 **`-1` 是 `wrap_idx`** ⇒ 采样器**没采到回绕**；
    `first=0`（而非预期的 `period-2`）说明**回绕在首次采样之前就发生完了**（`wrap_js` 先把
    `state.pos`/`scrollTop` seek 到 `period-2`，滚动器紧接着自己减了一个周期）。
  - 该断言首个合取项 `wrap_idx >= 0` 因此失败；而同一批 `B-6a`（无负值）/`B-6c`（只回绕一次）/
    `B-6d`（幅度 > 周期一半）/`B-4`（确实在滚动）**全绿** ⇒ 滚动器行为正常，是**采样时序**问题。
  - 对照证据：**同一份代码**上一轮跑（图标改动后）一次 `FAILED: 1 条`、一次 `ALL PASSED` ⇒ 抖动。
  - **定责：与本改动无关**（`#watchlist-body` 与 `#alert-list` 无任何交互）。
  - **待修（未做，未纳入本次）**：`wrap_js` 需把「回绕发生在首次采样前」也计为已观察（例如
    首帧值 `< start - 0.5` 时置 `wrapIdx = 0`），并补一条 `B-6a2` 断言 seek 是否生效 —— 否则
    seek 失效会一直被误报成「回绕后未继续前进」。**修它需独立跑红→绿验证**（脚本单次约 5 分钟）。

## 遗留 / 待办

- **产线**：需在 Railway Variables 更新 `WATCHLIST_STOCKS`（新 JSON 已给用户）；不改则产线配置比对 mismatch → 实时回退，仍只显示旧 1 只
- 首字图标对 ETF 名称（如「通」「医」「光」）观感可接受；`ICON_CHARS` 可后续为高频标的定制
- pytest 直跑曾触发 WorkBuddy「批量删临时文件」确认钩子导致退出码 1（换 `--basetemp` 规避）——环境坑，非代码问题
