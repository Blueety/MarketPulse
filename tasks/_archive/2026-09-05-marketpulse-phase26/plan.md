# 实施计划：修复美股快照日期门 + Yahoo 403（二十六期任务文件夹）

> 由 Agent 在只读分析后填写，人确认后再实施。
> 结论先行：PRD 两个 bug 的**根因定位与 PRD 描述有偏差**——快照脚本的日期逻辑**没有**用北京时间，真根因是 Hermes cron prompt 的推送门 + Yahoo 单主机 403。改动面因此与 PRD「snapshot_report.py ~20 行」的估算不同（见「根因分析」证据）。

## 任务概要

- **目标**:
  1. 让「美股午盘快照」在 00:00 北京 cron 触发后能正确推送（不再因日期检查跳过）。
  2. Yahoo Finance 403 时自动重试/切主机，GSPC/IXIC 不再因单主机 403 全空。
- **涉及文件**:
  - Hermes cron「MarketPulse 美股午盘快照」prompt（job `4337889a4cc3`，非仓库交付配置，经 `hermes cron edit` 修改）
  - `src/fetcher.py`（Yahoo 主机轮换 helper + 4 个调用点 + UA 增强）
  - `src/reporter.py`（`render_snapshot` us/alt 分支 None 单元格 1 行真值化）
  - `tests/test_phase26_snapshot.py`（新增，避开已存在的 `tests/test_phase26.py`=git_ops 26 期）
  - `docs/architecture.md` / `docs/pitfalls.md` / `docs/commands.md`（本任务决策行）
- **验证命令**: 见「验证」节。

## 根因分析（证据链）

### Bug 1「日期检查跳过推送」— 根因在 Hermes cron prompt，不在脚本

- 快照脚本日期逻辑**已是按市场时区**：`analyzer.get_market_date(market)` 中 `tz = SHANGHAI_TZ if market == "a-share" else EASTERN_TZ`（`src/analyzer.py:80-83`，七期起，2026-08-30）。
- 运行物证：`reports/snapshots/2026-09-04-us-noon.md` 于北京时间 09-05 00:01 生成（mtime 实证），文件名/报告头「日期：2026-09-04（美东时间）」；git commit `ed2322c 09-05 00:01 auto: 2026-09-04 us noon snapshot`；前一晚 `d01447c 09-04 00:00 auto: 2026-09-03 us noon snapshot`。脚本每晚 00:00 cron 都正确执行并提交，**没有任何跳过**。
- 真根因：Hermes cron「MarketPulse 美股午盘快照」（job `4337889a4cc3`，schedule `0 0 * * *`）的 prompt 用**北京时间**取"今天"：
  - 第一步 `date +%Y-%m-%d` → 09-05；
  - 第三步「读取 `YYYY-MM-DD-us-noon.md`（用今天日期）…检查快照日期是否是今天。如果不是今天或只有'休市'/'数据暂缺'，则不推送，直接结束」。
- 北京 00:00 = 美东 12:00 **前一日**（夏令时 UTC-4），美东文件名永远是北京日期 −1 → 该门**每晚必然不匹配** → 09-05 00:01 的 cron 会话（session `cron_4337889a4cc3_20260905_000045`）实证：先 `File not found: ...2026-09-05-us-noon.md`，读到 09-04 文件后结论「快照日期不是今天（2026-09-05）…不推送，直接结束」。09-03 文件有真实数值的那晚（d01447c）同样会被此门跳过——**有数据也推不出去**。
- 附带确认：同一类跨日错位只发生在 00:00（us-noon）槽位（北京 00:00–11:59 均映射美东前一日；21:45 us-open 时北京/美东同日，无此问题）。A 股槽位全在北京时区日内，不受影响。

### Bug 2「Yahoo 403」— 单主机无轮换，重试逃不出封锁

- cron 会话日志实证（`2026-09-05 00:00:55–00:01:05`）：
  `GSPC 获取失败(第1次): 403 Client Error: Forbidden for url: https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1d&range=5d`，GSPC/IXIC 各 2 次全 403（`RETRIES=1` 共 2 次尝试，同一 `query1` 主机，退避仅 1s）。
- 影响链：values 全 None → 快照渲染「休市/未开盘」→ `merge_history` 空操作（commit ed2322c 只动了 context，history.json 09-04 行 gspc/ixic 恒 None）→ context 被空壳覆盖 → web 板美股列空。
- 403 是**瞬时限流/封锁**而非永久：本次分析时 01:2x 实测 `query1`/`query2` 均 200 且返回真实价（GSPC 7719.02）。既有 pitfalls（一期）已记录「query1 返回 429、query2 返回 403」——单主机重试无法规避主机级封锁，需要双主机轮换。
- 展示误报：`render_snapshot` 单市场分支对 None 值单元格一律写「休市」（`src/reporter.py:634`），美东午盘美股盘中显示「休市」是假陈述（该槽位永远在交易时段，None 必为取数失败），且恰好命中 Hermes prompt 的「只有休市…不推送」分支，放大了误判。

### PRD 估算偏差（须明示）

- PRD「原因：快照脚本用北京时间判断日期」与代码/产物不符（脚本已按美东）；「改动量 snapshot_report.py ~20 行、零后端变更」与根因不符——真改动落在 Hermes prompt（非仓库）+ `src/fetcher.py`。仅改 snapshot_report.py 无法修复推送跳过。

## 方案

### A. Hermes cron「美股午盘快照」prompt 改美东日期门（根因修复，非仓库）

经 `hermes cron edit 4337889a4cc3`（job 全 id 先 `hermes cron list` 取），将 prompt 改为按**美东交易日**定位并校验：

1. 第一步改：用 terminal `TZ=America/New_York date +%Y-%m-%d` 取美东日期（Hermes terminal 为 bash，支持 `TZ` 前缀；避免依赖北京机器时钟）。
2. 第三步改：读取 `reports/snapshots/<美东日期>-us-noon.md`；有效性检查 = 文件存在且行情列含真实数值（不含「休市」/「数据暂缺」）→ 推送；否则不推送。**删除「日期是不是今天(北京)」比较**——美东日期本身就是"报告所属交易日"，无需再与任何"今天"比对。
3. 其余步骤（新闻搜索/生成分析/输出）不动。

核查项（同模式排查，防止同类漏推）：导出并审阅「MarketPulse 收盘日报+AI解读」（job `148928e7be94`，北京 08:00 = 美东前一日 20:00，文件名同样是美东日期）最近一次运行的 prompt：若含同样的北京日期门 → 一并修复（方法同 A）；若无（如已用美东/glob 最新文件）→ 照抄其成熟做法到午盘 prompt。

### B. `src/fetcher.py`：Yahoo 双主机轮换 + 选择性重试（仓库根因修复）

1. 新增常量 `YAHOO_HOSTS = ("query1", "query2")`（注释引用 pitfalls 一期证据）。
2. 新增 helper `_yahoo_chart_get(symbol, params) -> requests.Response`：
   - 逐主机 GET `https://{host}.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}`，`params`/`TIMEOUT` 透传，复用 `_SESSION`；
   - 403/429/5xx/连接错误/超时 → `log.warning` + `sleep(1)` 切下一主机；
   - 404 等其余状态 → 立即 `raise_for_status()`（确定性失败，不浪费轮换）；
   - 全主机失败 → 抛最后一次异常（由既有 `fetch_with_retry`/调用方容错接管，语义不变）；
   - 状态码读取用 `getattr(resp, "status_code", None)`，兼容既有 fake-session 单测（`tests/test_us_sector.py` 的 stub 无 `status_code` 属性）。
3. 4 个 Yahoo chart 调用点全部改走 helper（params 各自不变）：
   - `fetch_vix_vxn`（GSPC/IXIC/VIX/VXN/MOVE 主路径——本次 403 现场）
   - `fetch_vix_realtime`（开盘分析 VIX）
   - `fetch_us_sector_heat` 的 ETF worker
   - `_fetch_yahoo_watch`（web 自选股）
4. `_SESSION.headers` 增强：UA 换浏览器串（如 `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36`）+ `Accept: application/json`。无测试锁定现 UA（已 grep 实证），新浪/AkShare 同 Session 不受影响（实测裸 UA/带 Referer 均可用）。
5. `RETRIES` 常量与 `fetch_with_retry` 不动（外层语义保留：每符号最坏 2 轮 × 2 主机 = 4 次尝试）。

### C. `src/reporter.py`：快照 None 单元格真值化（1 行 + 注释）

`render_snapshot` 单市场分支（line 634）None 单元格：`market == "a-share"` 保留「休市」，us/alt 改为「数据暂缺」。理由：us/alt 快照槽位均在交易时段运行，None = 取数失败，非休市；与 Hermes「数据暂缺→不推送」语义对齐，杜绝「盘中显示休市」的假陈述。legacy `market=None` 分支与 `build_statuses` 全市场语义**不动**（避免触碰六期断言锁定的 A 股「休市」与 be6d7cd「未开盘」行为）。

### D. 测试（新增 `tests/test_phase26_snapshot.py`）

命名注：docs 编号 26/27/28 已被 git_ops/日间合并/自选股占用（`tests/test_phase26.py` 已存在=git_ops），本文件按任务名取 `test_phase26_snapshot.py` 避免冲突；docs 决策行按「本任务（2026-09-05）」记，不与既有编号纠缠。

1. 主机轮换：fake `_SESSION.get`——query1 URL 抛 403 响应、query2 URL 返回 200 → `fetch_vix_vxn` 返回价格，断言调用 2 次且顺序 query1→query2。
2. 双主机全 403 → 经 `fetch_with_retry` 后返回 None、不抛异常。
3. 404 → 不切主机立即失败（调用次数不放大）。
4. `get_market_date` 时区锁：monkeypatch `analyzer.datetime` 固定 2026-09-05 00:00+08:00 → `a-share == "2026-09-05"`、`us == "2026-09-04"`（把 PRD 要求的「美股快照用美东时间判断日期」锁成既有正确行为防回归）。
5. `render_snapshot`：market=us 值 None → 单元格「数据暂缺」；market=a-share 值 None → 仍「休市」（回归保护）。

### E. 文档同步

- `docs/architecture.md` 关键决策表追加一行：美股快照日期门（Hermes prompt 按美东）+ Yahoo 403 双主机轮换（2026-09-05 本任务）。
- `docs/pitfalls.md`：追加——北京 00:00 = 美东前一日，任何"报告日期 == 北京今天"的检查在 00:00 槽位必然失败；Yahoo chart 需 query1/query2 双主机轮换（单主机重试逃不出主机级 403）。
- `docs/commands.md` 验证要点追加一行（本任务命令）。

## 步骤

| # | 步骤 | 文件范围 | 风险 | 验证 |
|---|---|---|---|---|
| 1 | 改 Hermes 午盘 prompt 日期门（方案 A）+ 核查收盘日报 prompt 是否同病 | Hermes cron（非仓库） | 低；edit 失败则用 recreate | `hermes cron list` 确认；`TZ=America/New_York date +%Y-%m-%d` vs `date +%Y-%m-%d` 对比 |
| 2 | fetcher 加 `YAHOO_HOSTS` + `_yahoo_chart_get`，4 调用点改走 helper，UA/headers 增强 | `src/fetcher.py` | 中；mock 兼容点已设计（`getattr` 状态码） | 单测（D1-D3）+ 全量 pytest |
| 3 | reporter 单市场分支 None 单元格真值化 | `src/reporter.py` | 低；us/alt 无既有锁定断言（已 grep） | 单测（D5）+ 全量 pytest |
| 4 | 新增 `tests/test_phase26_snapshot.py`（D1-D5） | 新文件 | 低 | `pytest tests/test_phase26_snapshot.py -v` |
| 5 | 真实闭环：`AUTO_PUSH=0 venv/Scripts/python snapshot_report.py --market us --time noon` | 运行时生成物 | 低；会覆盖 09-04-us-noon.md 并把 gspc/ixic 盘中值 merge 进 history 09-04 行（期望效果，恢复 web 美股列） | 快照文件出现真实数值；history 09-04 行 gspc/ixic 非 None；无 403 日志 |
| 6 | 全量回归 + diff 审阅 | 全仓 | — | `venv/Scripts/python -m pytest tests/ -v`（全绿）；`git diff`/`git status` 摘要 |
| 7 | 文档同步（方案 E） | `docs/*` | 低 | 通读一次 |

## 验证命令（汇总）

```bash
cd D:/AGENT/MarketPulse
venv/Scripts/python -m pytest tests/test_phase26_snapshot.py -v
venv/Scripts/python -m pytest tests/ -v
AUTO_PUSH=0 venv/Scripts/python snapshot_report.py --market us --time noon
TZ=America/New_York date +%Y-%m-%d        # 应为 09-04（与北京 09-05 错位实证）
hermes cron list                          # 确认 job 4337889a4cc3 存在
```

## 不做什么

- **不**改 `snapshot_report.py` 日期逻辑（已按市场时区正确，PRD 对该文件的改动量估算基于错误前提）。
- **不**改 `build_statuses` 全市场 None 语义（「未开盘」标签为 be6d7cd 既定行为，动它牵动日报/多期测试）；不在脚本里引入交易时段时钟判断。
- **不**动 A 股「休市」显示、legacy `market=None` 快照分支。
- **不**引入新依赖、不改 `.env`/代理/git_ops 逻辑。00:01 那次 push 的 SSL 失败已被每 5 分钟的「自动推送GitHub」cron 补偿（已实测 `git log origin/master..HEAD` 为空、工作树 clean），无需处理。
- **不**清理 09-04 历史空行——今晚 00:00 cron 起自然写入（或本任务验证步骤 5 已回填）。
- **不**动 `config.json`、生成物备份规则照旧。

## 预估 diff 范围

- 新增文件: `tests/test_phase26_snapshot.py`（~90 行）
- 修改文件: `src/fetcher.py`（+~40 行：helper + 4 调用点改写 + UA）；`src/reporter.py`（+1 行 + 注释）；`docs/architecture.md` / `docs/pitfalls.md` / `docs/commands.md`（决策行）；Hermes cron prompt（非仓库）
- 删除文件: 无

## 风险

- 403 若为**整段 IP 级封锁**（双主机同时 403 持续数小时）：重试耗尽仍 None → 快照显示「数据暂缺」（方案 C 后语义为真）→ Hermes 按规则不推送 → 需人工换出口/等解封（pitfalls 一期已有备注）。本方案不消除该极端场景，只把"单主机瞬封"从必然失败变成可自愈。
- 重试总耗时上限：单符号最坏 4 次尝试 + 退避 ~5s（403 快失败，通常 3-5s 内完成轮换）；10 符号日报最坏 +~30s，cron 无硬超时（00:00 实测单次 run ~45s 完成）。
- Hermes prompt 修改后需人工确认已保存（`hermes cron edit` 交互式）；改前先备份原 prompt 文本（本 plan 附录已留证据路径：session `cron_4337889a4cc3_20260905_000045` messages[0]）。

## 确认

- [ ] 人已审阅计划（尤其：根因与 PRD 偏差、改动面分布、Hermes prompt 修改属非仓库交付配置）
- [ ] 文件范围合理
- [ ] 没有遗漏测试
- [ ] 没有引入不必要依赖
