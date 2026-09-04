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
---

## 【任务 A】线上 Railway env 修正建议（只建议，未改动）

- **环境变量名**：`WATCHLIST_STOCKS`（确认：`web/app.py:355-356` 注释「Railway 部署用」+ `os.environ.get("WATCHLIST_STOCKS")`，优先级高于 config.json）。
- **正确值**：JSON 数组，条目带 label 字段：
  `[{"symbol": "515300.SS", "label": "红利低波ETF"}]`
  （label 缺省会回退显示 symbol 本身，如 `515300.SS`，观感不佳；且旧 env 若 label 为 深证300/沪深300ETF 均需一并改为上值。）
- **生效方式**：Railway 修改 env 保存即触发自动 redeploy，无需手动重启；即便不重启，`os.environ` 每次请求实时读（`web/app.py` `_load_watchlist` 每次调用现读），无进程内缓存——但注意 FastAPI 模板无缓存问题仅限 HTML，label 走 `/api/watchlist` JSON 与模板无关。
- **env 非法 JSON 容错**（已读代码确认，`web/app.py:358-385`）：`WATCHLIST_STOCKS` 存在但 `json.loads` 抛 `JSONDecodeError/TypeError` → 记 warning「解析失败」+ 返回 `hidden:true`（视同无配置，前端整卡隐藏）；空数组 `[]` → 同样 `hidden:true`；解析成功但结构非法（非 list，如 dict）→ 进入 `fetch_watchlist` 逐条容错失败 → 返回 `hidden:false` + 空 stocks（前端显示「数据暂缺」占位），不会 500。即：env 配错最坏表现为卡片隐藏或占位，不会崩溃。
- **验证**：`curl https://<railway-host>/api/watchlist` 断言 `"label":"红利低波ETF"`；`curl /` 页面名称列同名。

## 【任务 B】市场概览标普/纳指显示旧值

### 数据链路（文件+行号）
1. 概览无独立实时取数，**每次请求实时读盘**：`web/app.py` `api_latest` → `_last_records(7)`（L375-377，读 `data/history.json`）→ `_compute_latest`（前向回填见 memory #36：末行符号 None → 回填最近非空行值、change_pct 强制 None）→ 状态列取 context。
2. 数据源写入：GSPC/IXIC 由 Yahoo `src/fetcher.py:29-40` SYMBOLS 注册表 fetch_all 获取；三入口（daily/snapshot/opening）写同一 `data/history.json`——快照走 `merge_history`（按市场子集合并不覆盖，analyzer.py:630+），日报走 `append_history`（**按 date 整行覆盖定稿**，analyzer.py:618+，daily_report.py:170-198）。

### 现场证据（实测）
- history 尾部：`2026-09-03` 行 gspc=7747.71/ixic=26584.06（完整）；`2026-09-04` 行 **gspc=None、ixic=None**，仅 A 股+btc 有值。
- `curl /api/latest`（运行中 8000 服务）：date=2026-09-04；标普 value=7747.71、纳指 26584.06、change_pct=None、status=「未开盘」。
- 开盘快照 `reports/snapshots/2026-09-04-us-open.md`（21:45/22:19 两次运行，commit 7c99367/86a9385）：**当日盘中真值已取到**——标普 7727.09、纳指 26562.28。
- daily report 22:32/22:38（commit b1830f7/ad2e325）在 **ET 10:32（美股盘中、未收盘）** 运行，report/context 均记美股「未开盘」、收盘价 None → 其 `append_history` 把 9-04 行 **整行覆盖**，抹掉快照已写入的盘中值 7727.09/26562.28 → gspc/ixic=None → web 前向回填显示 9-03 收盘 7747.71。

### 根因结论（分层）
1. **直接机制（非 bug）**：web 无缓存/TTL，展示的就是 history.json 最新行；9-04 行美股列为空 → 按既有回填设计显示最近收盘（9-03），change 为 —。
2. **真正缺陷（bug）**：`daily_report.append_history` 的全量定稿语义假定日报恒在美股收盘后运行；本次 22:32/22:38（ET 盘中）的日报运行在 fetch_all 美股值缺失（None）时仍执行 append 整行覆盖，**销毁了当日快照已 merge 的盘中真实值**——不是 Yahoo 失败/缓存/节假日，是「非收盘时点跑日报 → 定稿写空」。
3. **观感放大**：value 列对回填值无来源日期标注，与「数据截至 2026-09-04」并列 → 读作"标普/纳指数据陈旧"。

### 修正建议（只建议）
1. **调度**：daily_report 只在美东收盘后运行（≈北京 04:30 后）；22:30 档若配的是 daily_report 应改走 snapshot_report（--market us --time open）或撤掉，避免盘中定稿。
2. **定稿保护**：append 前美股列缺失时（`values["GSPC"]/["IXIC"] is None` 且当日 history 行已有美股盘中值）改为保留盘中值（按市场子集 merge 或跳过 append 等收盘后定稿），别整行覆盖为 None。
3. **展示**：web 对前向回填值标注来源日期（如「09-03 收盘」），或 change_pct=None 且非当日有效收盘时以「—/未收盘」呈现，避免旧值观感。

### 复现/验证步骤
1. `venv/Scripts/python -c "import json;print(json.load(open('data/history.json',encoding='utf-8'))[-1])"` → 见 9-04 行 gspc/ixic=None（已验）。
2. `curl http://127.0.0.1:8000/api/latest` → 标普 value=7747.71（9-03 回填）、status=未开盘（已验）。
3. 对照 `reports/snapshots/2026-09-04-us-open.md` 当日盘中 7727.09 → 证明盘中值曾被写入又被日报覆盖。
4. 修复后验证：下一次美股收盘后日报（≈北京 04:30）运行完，curl /api/latest 应显示 9-05 行真实收盘值、change_pct 非 None。
