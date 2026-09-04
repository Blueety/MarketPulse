# 诊断报告：自选股显示名称错误（红利低波 → 深证300）

日期：2026-09-04 ｜ 模式：只读排查（未改任何文件）

## 三问结论

### 1. web 端自选股显示名来自哪个字段
**来自配置条目自带的 `label`，全链路直通，无任何名称映射/改写。**

- `web/app.py:313` `_build_watchlist_payload`：`label = it.get("label", sym)`（缺省回退 symbol）→ 写入每行 `stocks_out[].label` 与趋势图 `trend.series[].label`。
- 配置来源 `web/app.py` `_load_watchlist`：**优先 `WATCHLIST_STOCKS` 环境变量（Railway 部署用），其次 `config.json`**；`src/config.py` `_valid_watchlist` 也原样保留 label。
- 前端 `web/templates/index.html:689/699`（`renderWatchlist`）：名称单元格 `escapeHtml(row.label)` 直出。自选股卡不查 SYMBOLS 注册表、无写死名称表（SYMBOLS 仅用于主看板 10 指数，且其中也没有「深证300」）。

### 2. config.json 中该自选股的代码与名称
- `config.json` `watchlist.stocks`（唯一一只）：
  `{ "symbol": "515300.SS", "label": "红利低波ETF" }`
- 实测运行中服务（127.0.0.1:8000）`/api/watchlist` 返回 `label: 红利低波ETF`，与配置一致。

### 3. 最可能的错位根因（一句话）
**不是代码映射错位，是配置层名称问题**：「深证300」字面量在本仓库任何地方（源码、web 模板、产物 reports/context、git 全历史 `git log -S`）均不存在，渲染链路只会原样显示配置的 label——若页面出现过「深证300」，唯一来源是运行实例读到的配置/`WATCHLIST_STOCKS` env 中该条目 label 被填成了「深证300」（代码、symbol、数值都对，只名称字段错），且本地当前 config 已被改为正确值、现象自愈。

## 支撑证据

- `git log --all -S "深证300"`：零命中 → 深证300 从未进入任何被提交文件。
- 产物演化显示 label 是「配置随手改、全链透传」的：reports/context 中 2026-09-01~09-03 为「沪深300ETF (515300.SS)」，2026-09-04 起为「红利低波ETF (515300.SS)」→ 说明 config label 近期被改过（今天才改成红利低波ETF），配置层名称与人无关的校验/联动。
- `tests/test_web.py` 契约同样只验证「配置 label 原样透传」。
- 前端历史上有两处不同错位 bug（`charts` 未声明致图空白 #42、watchlist 静默隐藏已修），均非名称错位；本次名称链路无代码缺陷。

## 严重度：低
数据/代码正确，仅配置 label 字段曾（或线上 env 仍）与真实标的名称不符；当前本地实例已正常。

## 复现步骤（供核验线上）
1. `curl http://127.0.0.1:8000/api/watchlist` → 期望 `label: 红利低波ETF`（本地已验，通过）。
2. 若线上（Railway）仍显示「深证300」：核对部署环境变量 `WATCHLIST_STOCKS` 的 JSON 中该条目 label，或线上 config 副本。
3. 浏览器硬刷新（避开旧模板缓存，见 pitfalls #FastAPI 模板缓存）。

## 预期 vs 实际
- 预期：自选股列表名称 = config 条目 `label`（红利低波ETF）。
- 实际（本地）：红利低波ETF，一致。
- 实际（用户报告）：深证300 → 仅当配置/env label 为「深证300」时成立；与代码渲染链路无关，属配置填写错误（已自愈或线上仍存）。
