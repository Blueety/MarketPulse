# Agent Instructions — MarketPulse

## Project Map

- `app.py`: 🔴 **Railway 部署入口（勿删勿移）** —— 3 行转发 `from web.app import app`，线上服务的实际启动命令是 `uvicorn app:app`（仓库内 `railway.toml` / `Procfile` / `railpack.json` 是否生效取决于 Railway dashboard 的 config-as-code 开关，本地无从确认）。2026-09-24 曾把它当"误放的实验文件"移进 `tasks/2026-09-24-qa-bughunt/legacy/` ⇒ **每一次部署都失败**（线上 502 `Application failed to respond`），而本地 `uvicorn web.app:app` + 全部门禁全绿，**本地测试发现不了**。回归护栏：`tests/test_web.py::test_railway_entry_point_module_exposes_the_app`。
- `daily_report.py`: 收盘日报编排入口（取数 → 报告 + 趋势图 → 写历史/缓存 → context 上下文）。
- `snapshot_report.py`: 盘中快照独立入口（4 个 Hermes cron：A 股午盘 11:30 / A 股收盘 15:00 / 美股开盘 21:30 / 美股午盘 00:00；按 `--market a-share|us` + `--time open|midday|close|noon` 取市场子集，单板块渲染，仅存盘不推送；裸跑=美股午盘）。
- `scripts/backtest.py`: 独立回测脚本（十三期）：复用生产 `check_breach` 语义回放历史触发事件，统计每标的告警次数 / 年化频率 / WARN-ALERT 分布 / 1·3·5·10 日平均后效 / 胜率 / 有效触发率；只读历史、仅写 `reports/backtest_report.md`，不联网、零副作用（`--history PATH` 指定只读输入）。⚠️ 输入**实为 SQLite `data/marketpulse.db`**（三十一期起 `load_history()` 已迁移；`data/history.json` 只是 09-12 旧快照，仅供 `--history` 演练）—— 旧描述"回放 `data/history.json`"已过时。⚠️ **纯统计逻辑在 `src/backtest.py`**（2026-09-20 搬迁，**唯一实现**）：CLI 与看板 `GET /api/backtest` 共用同一份计算；本文件只留 `render_report`（md）/ `print_summary` / `main`，并 re-export 被搬迁的名字（`tests/test_backtest.py` / `test_phase27.py` 的 `bt.<name>` 用法不变）。
- `scripts/probe_cn_macro.py`: 中国宏观数据源回归探针（2026-09-14）：逐个跑 13 个在册 AkShare 接口，输出「可用性 / 最新数据月份 / 耗时 / 行数 / 列名」表；**退出码非 0 若任一在册接口不可用或最新月份落后 > 阈值**（季度 GDP 给 6 个月）；`--include-rejected` 附带 8 个已否决接口（东财报告族 `商品/日期/今值/预测值/前值`，实测停更 2025-09，**仅对照、不参与退出码**）；单接口 daemon 线程限时；只读零写盘，JSON 报告落 `%TEMP%`。
- `scripts/backfill_history.py`: 历史数据回填（补 1Y，2026-09-11）：`--dry-run` 只打印计划；走 `fetcher._yahoo_chart_get`（双主机轮换）；**A 股 Yahoo 覆盖不足时改走 AkShare**（`399006.SZ` Yahoo 仅 1 天 → AkShare 243 天；daemon 线程 15s 限时 + 窗口按 Yahoo 最早日期裁剪且排除 BTC 自然日）；按符号所属市场时区归档日期（A 股→上海 / 其余→美东）；**只新增 date 不存在的行**（既有 `None` 是休市/未收盘的真实语义）；**唯一例外**：AkShare 补的 A 股键可写进既有行中该键为 `None` 的位置（绝不覆盖非空值，`--no-patch-existing` 关闭）；丢弃「仅 BTC 有值」的非交易日（BTC 7×24 的周末 bar）；经 `analyzer.merge_history` 按 date 合并；收尾**按 date 升序重排 + 断言**（`merge_history` 只 append 不排序）；**不碰 `data/last_values.json`**。前置：`history.retention_days=365`。**执行前先备份 `data/marketpulse.db`**（先 `storage.wal_checkpoint()` 再复制，`-wal` 里的新行才算进去；`data/history.json` 只是 09-12 旧快照，备份它没有意义）。`seed_history.py` / `seed_history_market.py` 为早期脚本，**已删除**（危险：小写键覆盖 `last_values` + 整行覆盖 `history`，回填一律用本脚本）。
- `requirements.txt`: 依赖清单（requests / matplotlib / pytest）。
- `.env.example`: 环境说明（无需任何 API 密钥）。
- `config.json`: 用户阈值配置（项目根，gitignore 排除；缺失回退内置默认）。
| `reports/`: 报告输出（`YYYY-MM-DD.md` / `snapshots/YYYY-MM-DD-{market}-{time}.md` / `charts/YYYY-MM-DD{-trend,-us-trend,-cn-trend}.png`）。 |
- `data/`: 数据缓存（`last_values.json` 涨跌幅基准；`marketpulse.db` SQLite 行情/事件库——**入库、即线上数据源**；`history.json` 为 09-12 旧快照，仅供 `--history` 演练）。
- `context/`: Hermes 上下文（`YYYY-MM-DD.json`：indices + history_30d + breach + sector_heat + us_sector_heat + search_keywords + correlation（显著相关对 |r|>0.5））。⚠️ 2026-09-24 实测更正：**并非 gitignore 排除**（`git check-ignore` 未命中）⇒ 它**会被 auto-push 白名单 `context` 一起入库**，Railway 的 `/api/latest` 板块/相关性就是从仓库里这份读的 —— 因此生成物入库是有意设计，别照「已忽略」去理解。
- `web/templates/macro_cn.html` + `web/static/macro_cn.js`: 中国宏观页（2026-09-14）：五层模块（四象限 / 主图 / 核心变量+因子 / 利率+地产 / 经济数据）；趋势源 = `/api/history`（上证/深证/创业板）+ `/api/cn/quotes`（人民币/10Y国债）；**加载分两波**（先 price+growth 出四象限再其余组，⚠️ 6 组同时发无收益）；主题初始化与 `macro.html` head 内联脚本**同源**（改一处必须同步）。
- `src/fetcher.py`: 数据获取层（Yahoo 取数 + SYMBOLS 注册表（8 指数：GSPC/IXIC/SH/SZ/CYB/VIX/VXN/MOVE，含创业板 399006.SZ）+ MARKETS 市场子集 + fetch_all(market) + fetch_sector_heat 概念板块领涨/领跌 Top5 元组（线程限时 10s，失败返回 ([], [])）；十八期新增 SECTOR_MAPPING + aggregate_sectors 大类聚合，fetch_sector_heat 内部将 ~175 个概念板块聚合为 10+1 大类）。
- `src/analyzer.py`: 纯逻辑 + 持久化（分类/涨跌幅/history 读写 + check_breach/alert_threshold + CONTEXT_DIR/build_search_keywords + compute_correlation（指数对 Pearson 相关性，纯 Python 零依赖，输入为收益率）+ merge_history（盘中合并写当日 history 子集，按市场子集投影、不整行覆盖））。
- `src/config.py`: 配置加载层（config.json + env 覆盖 + 内置默认，白名单校验，零依赖）。
- `src/econ_fetcher.py`: 美国经济数据（BLS 官方 API，一次 POST 4 序列：CPI-U/PPI/失业率/非农）+ 四象限；增长轴用**就业替代 GDP/PMI**（如实标注，非 PMI）；零写盘。**`QUADRANTS` 与中国版共享**（改键/改文案前先 grep 两个消费点）。
- `src/cn_econ_fetcher.py`: 中国宏观（2026-09-14）：AkShare **13 序列**（CPI/PPI/PMI/GDP/M2/社融/新增信贷/失业率/社零/房价(北京·上海)/LPR/SHIBOR/10Y国债）并发取数 + **中国版四象限**（增长轴 = **PMI 水平与 50 比较**，非同比方向）+ `fetch_bond_yield_curves`（中债 3 条曲线 → 10Y + 信用利差）；**与 `econ_fetcher.py` 平行不共享取数**；`CN_ECON_GROUPS` 供 `/api/econ/cn?group=` 分组加载；任一接口失败降级空并记 `failed`；零写盘。
- `src/alerter.py`: 告警层（告警文件渲染 + alerts.log 去重 + collect_breaches 纯计算 + run_alert_checks 编排）。
| `src/reporter.py`: 报告渲染（日报/快照/趋势图/分市场趋势图 + 相关性分析章节）+ generate_context 上下文 JSON 生成（含 sector_heat / us_sector_heat / correlation 键）。 |
- `web/`: 只读看板（bento 栅格仪表盘，2026-09-11 重构；**3 个页面路由 + 9 个 JSON API**）：`app.py`（FastAPI，**9 个 JSON API**：`/api/history`（`days` 上限 **3650**）/ `/api/latest`（`sector_heat` + **`us_sector_heat`** + **`correlation`** 显著对直通）/ `/api/alerts` / `/api/watchlist`（/ `/api/news`（资讯，Hermes 落盘 `data/news.json` 只读消费）（**三十期文件化**：优先读 `data/watchlist.json` 快照（daily/snapshot 报告链路落盘）+ symbol 配置比对，mismatch/无快照才回退实时取数；响应带 `as_of` 数据时点）/ **`/api/macro`**（美元指数 / 10Y美债 / 原油 / 黄金COMEX，env `MACRO_STOCKS` > `config.json` `macro.stocks` > 内置默认）/**`/api/econ`**（美国 BLS 四序列 + 四象限，TTL 6h，**失败不缓存**）/**`/api/econ/cn`**（中国宏观，`?group=` 分组；TTL 6h，**仅全部失败才不缓存**）/**`/api/cn/quotes`**（CNY=X + 中债 10Y + 信用利差 bp，TTL 90s））；页面 `/` · `/macro`（全球） · **`/macro/cn`（中国宏观，2026-09-14 新增：模板 `macro_cn.html` + `static/macro_cn.js`，复用 `.mac-*` 仅补 ~16 行 `.cn-*`）**；`templates/index.html`（`.dash` + `.row-kpi/.row-main/.row-3/.row-news` 四视觉行、9 类模块、1 个 `data-placeholder="1"` 静态占位（资金流向；风险偏好/市场关系/最新资讯已分别于三十二/三十三期点亮：合成仪表、correlation pills、`/api/news` 资讯流））；`static/app.js`（趋势**四图合一 + 4 类别 tab**、KPI sparkline、自选迷你条）；`static/style.css`（卡片 token 双主题）。进程绝不写 `data/` `alerts/` `context/`。**UI 验收必须跑** `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（Playwright 三视口，自动挑空闲端口；截图/JSON 落 `%TEMP%`），不要以 `curl 200` 或肉眼看代替。
- `src/storage.py`: SQLite 存储层（三十一期）：history 长表读写/upsert 双模式/按月备份/空库恢复；`DB_PATH` 为测试单点 patch（有意例外）。
- `tests/`: 单元测试（test_analyzer.py / test_reporter.py / test_alerter.py / test_context.py / test_config.py / test_web.py / test_econ_fetcher.py / test_cn_econ.py / test_phase6a.py / test_phase6b.py / test_phase7.py / test_phase8.py / test_backtest.py）。
- `alerts/`: 告警输出（`YYYY-MM-DD-{market}-{time}.md`（盘中快照复合名）/ `YYYY-MM-DD-close.md`（日报））。⚠️ 2026-09-24 实测更正：**并非 gitignore 排除**，同 `context/`（在 auto-push 白名单内、会入库）。
- `data/news.json`: 资讯快照（三十三期；**Hermes 侧落盘**、web 只读（2026-09-20 收窄：web 进程**只可写 `config.json`**，且必须经 `src/settings_store.py` 的白名单路径；`data/` `alerts/` `context/` 仍然**绝不写**；Railway 上连 config.json 也不写——只读展示）（2026-09-20 收窄：web 进程**只可写 `config.json`**，且必须经 `src/settings_store.py` 的白名单路径；`data/` `alerts/` `context/` 仍然**绝不写**；Railway 上连 config.json 也不写——只读展示）；git 追踪随 auto-push 入库）。
- `data/marketpulse.db`（+ `-wal`/`-shm`）: SQLite 库（三十一期）：`history` 行情长表 + **`econ_events` / `econ_event_news` 事件表**（2026-09-18/19）。⚠️ **`.db` 是 tracked 文件 ⇒ 入库即线上数据源**（Railway 跑的就是仓库里这份；`git cat-file -e HEAD:data/marketpulse.db` 可验；`.gitignore` 对已跟踪文件无效，写进去的那行只对未跟踪路径生效）；**`-wal`/`-shm` 才是真排除** ⇒ 写库后 push 前必须 `storage.wal_checkpoint()`（防提交的副本漏掉新行；已由 `src/git_ops.py` 的提交前护栏在 `auto_commit_push` 内强制）。备份 = `data/backup/history_YYYY-MM.json`（按月）+ `data/backup/econ_events.json`（事件表单文件全量）（两者**均入库**，`storage.restore_if_empty` 在空库时按同一命名规则恢复）。
- `data/backup/`: 备份（**入库**，web 启动空库恢复链的唯一数据源）——`history_YYYY-MM.json`（行情，按月：当月覆盖 / 历史月冻结 / 缺失自愈）+ **`econ_events.json`**（事件表 `econ_events` / `econ_event_news`，**单文件全量**：2026-09-24 定档 — 这张表含未来日程且每个月都会变，按月的"历史月冻结"既产出 60 个 1 行文件、又会让未来月的备份长期停在旧值；空表时**不覆盖已有备份**）。
- `data/alerts.log`: 当日已告警标记（午盘触发则收盘跳过）。⚠️ 2026-09-24 实测更正：`.gitignore` 是 `*.log` + `!data/alerts.log`（**反排除**）⇒ 它**会入库**（旧描述「gitignore 排除」说反了）。
- `CONTEXT.md`: 领域词表。命名和描述一律用这里的词；术语冲突当场指出并更新它。
- `docs/`: 项目知识和规则。
- `docs/adr/`: 决策记录（为什么这么做）。
- `docs/agents/`: 角色提示词和流程细则（任务分级 / 架构师 / 执行者）。
- `tasks/`: 任务目录和交接记录。
- `skills/`: 可复用流程（bug-fix / pre-review / tdd 是脚手架 v2 的通用流程；hermes-cron-script / source-value-layer / ui-verify-assertion 是本项目专属）。

## Required Reading

- 任何任务开始前先读 `docs/agents/任务分级.md`，并在只读分析末尾按格式声明档位（一行）。
- 修改前先读 `docs/architecture.md`。
- 改行为前先读 `docs/commands.md`。
- 复杂任务先读当前 `tasks/` 下的任务文件。
- 修 bug：`skills/bug-fix/SKILL.md`（闸门 A）；写测试：`skills/tdd/SKILL.md`（seam 先确认）；提交前审查：`skills/pre-review/SKILL.md`（双轴）。
- 已有决策看 `docs/adr/`，遵守其中仍然生效的决定。

## Commands（基于实际环境；所有命令在 venv 内执行）

- Activate (Windows): `venv/Scripts/activate`
- Install: `venv/Scripts/pip install -r requirements.txt`
- Run: `venv/Scripts/python daily_report.py`
- Test: `venv/Scripts/python -m pytest tests/ -v`
- Freeze: `venv/Scripts/pip freeze`
- Lint / Typecheck / Build: 无（纯 Python 脚本项目，暂未配置）

## Working Rules

- 复杂任务先只读分析，不要直接改。
- 每次制定完计划后，将计划保存到 `tasks/<日期>-<简述>/plan.md`（日期用当天 `YYYY-MM-DD`，简述用简短英文描述，如 `2026-08-29-marketpulse/plan.md`）。
  - 计划应包含：目标、涉及文件、实施步骤、验证命令、测试 seam、预估 diff 范围。
- 保持 diff 最小，不重构无关代码。
- 不引入新依赖，除非先说明理由并等待确认。
- 不修改 `.env`、生产配置、生成文件。
- **自动提交范围白名单**：`src/git_ops.py` 的自动提交只允许 `data/` `context/` `alerts/`（`_DATA_PATHS`），**禁止** `git add -A` / `--all` / `.`；`_has_changes` 与 `_commit` 必须**同范围**（否则源码 WIP 时误报 `Failed`）。🔴 **`git commit` 也必须带 pathspec**（2026-09-20 补）：`git commit` 不带 `-- <paths>` 提交的是**整个暂存区**，`git add <白名单>` 只能添加、无法排除 index 里已有的内容 ⇒ 别处 `git rm` / `git mv` 造成的**已暂存删除/重命名会被无差别带走**（实测事故 `6ec1562`）。护栏：`tests/test_phase26.py::test_commit_pathspec_isolates_unrelated_staged_changes`。`reports/` 被 `.gitignore` 排除 → 不得入列（否则 `git add` 直接 fatal，三入口数据提交全挂）。⚠️ 仓库外 Hermes cron「MarketPulse 自动推送GitHub」（`*/5`）**已改为 script 模式**（wrapper `D:\hermes\scripts\marketpulse_autopush.py` → `scripts/auto_commit_data.py`），范围由代码强制；**临时文件/半成品仍建议尽快 `git add <具体文件>` 收尾**，别把写了一半的东西留在工作区。
- 需求不清楚时先问，不要猜。
- 每完成一个逻辑步骤后运行验证命令，不接受"应该可以"——必须实际运行验证命令。
- 如有失败，先解释原因再修复，不要绕过问题。
- 验证通过后，运行 `git diff` 检查改动范围。
- 任务完成后，提取可复用的规则（不是泛化建议），追加到 `docs/pitfalls.md` 或 `AGENTS.md`。
- 每次任务完成后，将日志保存到 `tasks/<日期>-<简述>/journal.md`，内容包括：目标、改动文件清单、验证结果、遇到的问题、下次注意什么、涉及的 ADR 编号。这样下次会话接手时能快速了解上下文。
- 只读分析末尾声明档位（一行，格式见 `docs/agents/任务分级.md`），等确认后再实施；用户一句话可覆盖档位（如「T3，我不确定根因」）。
- 修 bug 时：进入根因假设前，必须有一条已经实跑过、能对**这个** bug 变红的命令（`skills/bug-fix/SKILL.md` 闸门 A）；拿不出这条命令就先停下说明试过什么、缺什么。本地门禁全绿不代表线上没事（见 `app.py` 那条事故）。
- 写测试前：先书面列出要测的 seam 并等待确认（`skills/tdd/SKILL.md`）；修 bug 的回归测试只在存在正确 seam 时写。
- 调试日志统一加 `[DEBUG-xxxx]` 前缀，提交前 grep 清干净；一次性原型 / 临时脚本一并删除（闸门 B）。注意本项目有 auto-push 白名单（见上），临时文件进白名单就会被自动推上去。
- 提交前按 `skills/pre-review/SKILL.md` 出双轴报告（Standards / Spec 分别报告，不合并、不跨轴排序）。
- 任务结束后：同时满足三条准入（难以撤销 + 没有背景会让人困惑 + 是真实取舍）的决策写进 `docs/adr/NNNN-slug.md`（编号取现有最大值 +1）；三条不齐不写。

## Done Means

- 验收标准已满足。
- 相关测试/checks 已运行或清楚标注未运行。
- `[DEBUG-` 无残留，一次性脚本已删。
- 本次任务的经验/决策已落盘（`docs/pitfalls.md` / `docs/adr/`）。
- diff 已摘要。
- 风险和后续工作已列出。

- `config.json` 的 `watchlist.stocks[]`：每项 `{symbol(必填), label(必填), cost?(可选, >0)}`；`cost` 用于首页自选卡的「持仓盈亏%」（设置页录入，存储层透传、零改动）。
