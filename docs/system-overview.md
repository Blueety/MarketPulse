# MarketPulse 系统总览

> **本文档定位**：系统**现状快照** —— 让人（或新接手的 Agent）在 5 分钟内建立完整心智模型。
>
> **与 `docs/architecture.md` 的分工**：那份是**决策台账**（30+ 条「选了什么、为什么、什么时候」，按迭代期编号，只增不改）；本文是**当前状态的结构化描述**。两者互补，**改动架构时两份都要看**。
>
> **最后核对**：2026-09-14（按实际代码与文件规模核对，非文档转述）

---

## 1. 系统定位

**市场波动率监控 + 日报推送系统。** Python 项目，核心链路是「**定时取数 → 渲染报告 → 落盘 → 由外部 AI 代理（Hermes）读取并推送**」。

**两条贯穿全局的硬边界**：

1. **脚本自身不含推送逻辑** —— 推送由 Hermes 承担（交付配置项，非仓库文件）。
2. **Python 侧不引入 LLM / 搜索 SDK** —— AI 解读与异动归因在 Hermes 侧完成。

这两条边界决定了 `context/*.json` 是**整个系统的枢纽**：Python 把计算结果写进去，AI 读出来后自己决定怎么归因、怎么推送。

---

## 2. 功能清单

### 2.1 运行点

| 运行点 | 入口 | 触发（北京时间） | 产出 | 推送 |
|---|---|---|---|---|
| **收盘日报** | `daily_report.py` | 美东收盘后 | 日报 md + 趋势图 ×3 + 图片 png + history + context | 经 Hermes |
| **A股午盘快照** | `snapshot_report.py --market a-share --time midday` | 11:30 | `reports/snapshots/*.md` | ✗ 仅存盘 |
| **A股收盘快照** | 同上 `--time close` | 15:00 | 同上 | ✗ |
| **美股开盘快照** | `--market us --time open` | 21:30 | 同上 | ✗ |
| **美股午盘快照** | 同上 `--time noon` | 00:00 | 同上 | ✗ |
| **开盘分析** | `opening_analyzer.py [--market a-share\|us]` | 开盘后 15-30 分钟 | `reports/opening/{date}-{market}.md` | 经 Hermes |

**开盘分析的特殊性**：只读新浪实时行情 + 只写自己的报告文件，**零持久化**（不写 history / last_values / context / alerts.log）。

### 2.2 监控标的（10 个）

| 分类 | 标的 |
|---|---|
| 美股大盘 | `GSPC` 标普500 · `IXIC` 纳斯达克 |
| 波动率 | `VIX` · `VXN` · `MOVE` |
| A股大盘 | `SH` 上证 · `SZ` 深证 · `CYB` 创业板(399006.SZ) |
| 另类资产 | `GLD` 黄金 ETF · `BTC-USD` |

另类资产**仅进日报「💰 另类资产」板块与趋势图**，不参与告警、不进波动率/大盘面板。

> 注：概览卡「黄金」与趋势图黄金线已改用 **`GC=F` COMEX**（三十四期），`GLD` 仅保留在 history 作 EOD 历史，UI 不再消费。

### 2.3 告警

| 项 | 内容 |
|---|---|
| 阈值默认 | VIX/VXN ±20% · MOVE ±15% · GSPC/IXIC ±4%/±4.5% · SH/SZ ±4% · CYB ±5% |
| 覆盖方式 | env `ALERT_THRESHOLD_<SYM>` > `config.json` |
| 触发条件 | 变化率**严格大于**阈值 |
| 级别 | 触发即 WARN；当前值处于恐慌区间 → 升级 ALERT |
| 基准 | `data/last_values.json` 的**旧缓存**（不用当日新值） |
| 去重 | 同一指数当日只告警一次，状态记 `data/alerts.log`（午盘触发则收盘跳过） |
| 产出 | `alerts/YYYY-MM-DD-{type}.md`，type = `close` / `a-share-midday` / `a-share-close` / `us-open` / `us-noon` |
| 推送 | Hermes 检测到文件后**独立推送**一条告警消息 |

**`check_breach` 是告警语义的单一事实来源** —— 日报、快照、context、回测全部复用，不重写。

### 2.4 Web 看板

FastAPI 单页看板，**bento 栅格仪表盘**，**只读、零写盘**。

- 骨架：`.dash > .row-kpi / .row-main / .row-3 / .row-news` 四视觉行
- 断点：1920 档 5/2/3/4 列 · 1280 档 KPI 3 列 + 主区堆叠 · 375 档单列 + 抽屉
- 模块：4 张 KPI 卡（含 sparkline）· 趋势**四图合一 + 4 类别 tab**（单 `canvas#chart-main`，7D/30D/90D/1Y）· 自选列表 · 市场概览 6 小卡 · A股板块 Top5 · 美股行业板块（双 tab）· 告警记录 · 最新资讯 · 市场情绪/资金流向/风险偏好 · 3 个静态占位卡
- 双主题：Light `#F7F8FA` / Dark `#0B0F14`，玻璃化（`backdrop-filter` + 氛围层）

**4 个页面路由 / 11 个 JSON 端点**（10 个业务 API + `/healthz` 健康检查）
⚠️ 2026-09-19 实测订正：此前写「3 页 9 API」（`architecture.md` 也是），且漏了 `/timeline` 一页
与 `/api/timeline` 一个 API。`frontend-structure.md` §1/§2 一直是准的。

🔒 **全站 HTTP Basic Auth**（2026-09-19，见 §9 G9）：除 `/healthz` 外全部端点需凭据
（`MP_AUTH_USER` / `MP_AUTH_PASS`）；未配置 ⇒ **fail-open**（放行 + 启动 WARNING）；
`MP_AUTH_DISABLED=1` ⇒ 本地开发/自动化验收免鉴权。

| 端点 | 说明 |
|---|---|
| `GET /` | 看板页面 |
| `GET /macro` | 全球（美国）宏观数据独立页（research terminal 风格，7 模块） |
| `GET /macro/cn` | **中国宏观独立页**（2026-09-14 新增，与 `/macro` 平行：四象限 + 13 序列 + 行情） |
| `GET /timeline` | **市场日历**（2026-09-18 上线；用户可见名「市场日历」，内部名 timeline） |
| `GET /healthz` | **无鉴权**健康检查 → `{"status":"ok"}`；`railway.toml` 的 `healthcheckPath` 指向它（🔴 指到 `/` 会因 401 触发部署重启循环） |
| `GET /api/timeline` | 事件时间线（日历 × 行情影响 × 新闻叙事 + **结果值层** actual/forecast/previous）；TTL 6h，**不联网** |
| `GET /api/history` | 历史序列；`days` 上限 365，另支持 `start_date`/`end_date` |
| `GET /api/latest` | 最新日 10 指数概览 + `sector_heat` + `us_sector_heat` + `risk_appetite` + `correlation` |
| `GET /api/alerts` | 最近告警（10 条） |
| `GET /api/news` | 最新资讯（读 `data/news.json`，Hermes 落盘） |
| `GET /api/watchlist` | 自选股（快照优先 + 实时回退，含 `as_of`） |
| `GET /api/macro` | 宏观品种（美元指数/10Y美债/原油/黄金）；三级回退 env > config > 内置，TTL 90s |
| `GET /api/econ` | 美国经济数据（BLS：CPI-U/PPI/失业率/非农）+ 四象限；TTL 6h，**失败不缓存** |
| `GET /api/econ/cn` | **中国宏观**（AkShare 13 序列 + 中国版四象限）；`?group=` 分组（R1：全量 ≈10s > 8s 判据）；TTL 6h，**仅全部失败才不缓存** |
| `GET /api/cn/quotes` | **中国行情**（CNY=X + 中债 10Y 国债 + 信用利差 bp）；TTL 90s |

**零侵入**：不读 `last_values.json`、不写任何数据文件，与日报共用同一事实来源（`data/marketpulse.db` / `context/` / `alerts/`）。

---

## 3. 架构分层

```
┌─ 编排入口层 ─────────────────────────────────────────────────────┐
│ daily_report.py · snapshot_report.py · opening_analyzer.py       │
│ app.py（Railway 入口，仅 from web.app import app）                │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌─ 核心逻辑层 src/ ──────────┴──────────────────────────────────────┐
│ fetcher.py        取数：Yahoo 双主机轮换 / AkShare / 板块聚合      │
│ analyzer.py       纯逻辑 + 路径常量（状态·涨跌幅·history·相关性）  │
│ reporter.py       渲染：日报 / 快照 / 开盘 / 趋势图 / context      │
│ alerter.py        告警渲染 + alerts.log 去重 + collect_breaches    │
│ config.py         三级配置 env > config.json > 内置默认            │
│ news_fetcher.py   个股归因搜索（Tavily）                          │
│ rss_fetcher.py    新闻流 RSS 双源（华尔街见闻 + Google News）      │
│ news_saver.py     资讯落盘（清洗 + 切句 + 原子写）                 │
│ storage.py        SQLite 长表存储（31 期替换 history.json）        │
│ image_renderer.py 日报图片化（Jinja2 + Playwright 截图）           │
│ git_ops.py        cron 后自动 commit + push                        │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌─ 持久化 ───────────────────┴──────────────────────────────────────┐
│ data/marketpulse.db       SQLite 长表 (date, symbol, value, change)│
│ data/last_values.json     涨跌幅基准（次日用）                     │
│ data/news.json            资讯（**所有权归 Hermes**）              │
│ data/watchlist.json       自选股快照                               │
│ data/alerts.log           当日已告警标记                           │
│ data/backup/history_YYYY-MM.json   按月归档备份                    │
│ context/YYYY-MM-DD.json   ★ 给 Hermes 的机器可读上下文            │
│ alerts/ · reports/        告警与报告生成物                         │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌─ 接入层 ───────────────────┴──────────────────────────────────────┐
│ web/app.py  FastAPI 只读看板（6 API，零写盘）                     │
│ src/git_ops.py  cron 后自动 push（经 Clash 代理 127.0.0.1:7890）  │
└───────────────────────────┬──────────────────────────────────────┘
                            │
┌─ 通知层（仓库外）──────────┴──────────────────────────────────────┐
│ Hermes → QQ 机器人（读 context/ 生成归因，读 reports/ 推送）      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 核心数据流

```
Yahoo Finance (GSPC/IXIC/VIX/VXN/MOVE/GLD/BTC) + AkShare (SH/SZ/CYB/概念板块)
   │
   ├─→ daily_report.py
   │      ├─→ reports/YYYY-MM-DD.md ─────────────→ Hermes ─→ QQ 推送
   │      ├─→ reports/images/YYYY-MM-DD.png（图片化推送产物）
   │      ├─→ reports/charts/YYYY-MM-DD{-trend,-us-trend,-cn-trend}.png
   │      ├─→ data/marketpulse.db（merge_history 按 date 合并，NULL 是语义）
   │      ├─→ data/last_values.json（次日涨跌幅基准）
   │      └─→ context/YYYY-MM-DD.json ★
   │             ├─ date / indices(value,change_pct,status)
   │             ├─ history_30d（含当日）
   │             ├─ breach(triggered + indices 明细)
   │             ├─ sector_heat / us_sector_heat
   │             ├─ correlation（仅 |r|>0.5 显著对）
   │             ├─ search_keywords（方向感知）
   │             └─ watchlist
   │                    │
   │                    └─→ Hermes：常规解读 /（异动日）搜索归因 → 追加日报 → QQ
   │
   ├─→ snapshot_report.py ─→ reports/snapshots/YYYY-MM-DD-{market}-{time}.md
   │                          （只存盘，不推送、不算涨跌幅、不写 history）
   │
   ├─→ opening_analyzer.py ─→ reports/opening/{date}-{market}.md（零持久化）
   │
   └─→ run_alert_checks（两入口各自调用）
          ├─→ alerts/YYYY-MM-DD-{type}.md ─→ Hermes ─→ QQ 独立告警推送
          └─→ data/alerts.log（当日去重标记）

cron 收尾：三入口 main() 末尾 → src/git_ops.auto_commit_push(date, type)
          → git add -A + commit("auto: {date} {type}") + push origin master
          → 保证 Railway 部署与最新数据同步

Web 看板（独立进程，只读）：
   data/marketpulse.db + context/*.json + alerts/*.md + data/news.json
          → web/app.py 6 个 JSON API → 前端渲染
```

---

## 5. 模块清单（src/）

| 模块 | 行数 | 职责 |
|---|---|---|
| `reporter.py` | 993 | Markdown 日报/快照/开盘渲染、趋势图（matplotlib 懒加载 + 线程限时）、`generate_context` 原子写 |
| `cn_econ_fetcher.py` | 562 | **中国宏观**（2026-09-14）：AkShare 13 序列并发取数（daemon 线程 + 整体限时）+ 中国版四象限（PMI 水平口径）+ 中债收益率曲线/信用利差；零写盘 |
| `econ_fetcher.py` | 257 | 美国经济数据（BLS 官方 API，一次 POST 4 序列）+ 四象限（增长轴用就业替代，**非 PMI**）；零写盘。`QUADRANTS` 为两页共享常量 |
| `analyzer.py` | 698 | 状态分类、涨跌幅、格式化、路径常量、history 读写、`build_search_keywords`、`compute_correlation`（纯 Python 零依赖） |
| `fetcher.py` | 668 | Yahoo 取数（双主机轮换）、SYMBOLS 注册表、`fetch_sector_heat`（AkShare + 聚合）、`fetch_us_sector_heat`（11 SPDR ETF）、`fetch_watchlist` |
| `storage.py` | 280 | SQLite 建表/upsert（preserve\|overwrite）/范围查询/按月备份/空库恢复；WAL |
| `image_renderer.py` | 263 | 日报图片化：md 解析 → Jinja2 模板 → Playwright 截图 |
| `rss_fetcher.py` | 240 | 新闻流 RSS 双源（华尔街见闻 + Google News 中文检索），HTML 清洗 + 去重 + 宏观白名单 |
| `news_saver.py` | 209 | 资讯落盘：清洗（去平台噪声）→ 按句切分 → 原子写 |
| `config.py` | 186 | 三级配置加载 + 白名单校验，零依赖 |
| `alerter.py` | 107 | 告警文件渲染、alerts.log 去重、`collect_breaches` 纯计算导出 |
| `news_fetcher.py` | 99 | 个股归因搜索（Tavily 单源） |
| `git_ops.py` | 90 | cron 后自动 commit + push |

---

## 6. 关键设计决策（速记）

| 决策 | 内容 |
|---|---|
| **告警单一来源** | `check_breach` 被日报/快照/context/回测复用；`collect_breaches` 是纯计算（无副作用），供 context 取 breach 明细 |
| **history 合并语义** | `merge_history` 只并本市场子集、**不整行覆盖**；NULL 是语义（休市/未收盘），读取侧必须保留 |
| **读时剔除自身行** | 三入口读 history 均先剔除自身 date 行，避免同日多入口重复叠加 |
| **时区分离** | A股按北京时间归档、美股按美东日期归档（`get_market_date`）；北京 00:00 = 美东前一日 |
| **配置三级链** | env > `config.json` > 内置默认；`config.json` 入 gitignore，缺失/损坏回退默认不崩 |
| **monkeypatch 纪律** | 补丁一律打**使用方**模块，不打定义方；唯一例外 `storage.DB_PATH`（有意设计） |
| **原子写** | 所有 JSON 落盘走 `临时文件 + os.replace`，避免读到半截 |
| **图表标签英文** | 中文字体跨平台渲染不一致 |
| **fetcher 侧放规则** | 板块聚合、语言过滤等在**取数层**一次完成，5 个消费点零改动 |
| **资讯所有权** | `context/*.json` 只归 Python；`data/news.json` 只归 Hermes —— 双写者互不越界 |
| **Web 零写盘** | 看板进程绝不写任何数据文件 |
| **cron 自动提交** | 默认开启（`AUTO_PUSH=0` 关）；无改动跳过；失败仅记日志、退出码恒 0 |
| **自动提交范围** | **路径白名单** `data/` `context/` `alerts/`（`src/git_ops._DATA_PATHS`）；**禁 `-A` / `--all` / `.`**；`_has_changes` 与 `_commit` 必须同范围；`reports/` 因 `.gitignore:40` 排除而不得入列（否则 `git add` 直接 fatal） |

---

## 7. 部署与运维

| 项 | 内容 |
|---|---|
| 部署平台 | **Railway**（`Procfile` / `railway.toml` / `app.py`，nixpacks + Python 3.11，healthcheck `/`）；另有 `render.yaml` |
| 启动命令 | `uvicorn web.app:app --host 0.0.0.0 --port $PORT` |
| 数据同步 | cron 入口跑完自动 commit + push → Railway 重部署拿到最新数据 |
| push 代理 | 经 Clash `http://127.0.0.1:7890`（仅注入 push 子进程 env 副本，不改 git config） |
| 备份恢复 | `scripts/backup_db.py` 按月归档；web startup `restore_if_empty` 三级恢复（备份合并 → 旧 JSON 兼容读 → 空库）；**Railway 临时文件系统下备份链是主数据源** |
| 失败重试 | `scripts/push_retry.sh` + Hermes cron |

---

## 8. 命令速查

> 完整清单见 `docs/commands.md`。

```bash
# 主流程
venv/Scripts/python daily_report.py                    # 完整闭环
venv/Scripts/python snapshot_report.py --market a-share --time midday
venv/Scripts/python opening_analyzer.py --market us
AUTO_PUSH=0 venv/Scripts/python daily_report.py        # 本地开发关自动推送

# 测试与验收
venv/Scripts/python -m pytest tests/ -v                # 全量（27 个测试文件）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
                                                       # Web UI 验收（Playwright，三视口，改前端必跑）

# Web
venv/Scripts/python -m uvicorn web.app:app --port 8000 # 启动看板（改前端后必须换新端口验证）

# 鉴权（2026-09-19 起全站 HTTP Basic Auth；未配 env 时 fail-open 并打 WARNING）
MP_AUTH_USER=demo MP_AUTH_PASS=demo123 venv/Scripts/python -m uvicorn web.app:app --port 8011
curl -s -o /dev/null -w "%{http_code}\n" localhost:8011/                  # 401
curl -s -o /dev/null -w "%{http_code}\n" localhost:8011/healthz           # 200
curl -s -o /dev/null -w "%{http_code}\n" -u demo:demo123 localhost:8011/  # 200
venv/Scripts/python -m pytest tests/test_web.py -v -k auth                # 鉴权单测

# 维护脚本
venv/Scripts/python scripts/backfill_history.py [--dry-run]
venv/Scripts/python scripts/backtest.py
venv/Scripts/python scripts/migrate_to_sqlite.py [--db PATH]
venv/Scripts/python scripts/backup_db.py
venv/Scripts/python scripts/render_report_image.py --date YYYY-MM-DD
```

---

## 9. ⚠️ 已知缺口与待处理

| # | 问题 | 影响 | 建议 |
|---|---|---|---|
| **G1** | **（2026-09-20 已处置）** 硬编码凭据：`src/wecom_channel.py` / `wecom_sdk.py` / `wecom_ws.py` 三处硬编码企业微信 `BOT_ID` + `SECRET`（同一组值抄了 3 遍，共 6 行） | 🔴 **实测比原描述严重一个量级**：原写「仓库会 push 到远端 → 凭据泄露」，实际仓库是 **PUBLIC**（`gh repo view --json visibility` → `PUBLIC`）⇒ 凭据**在公网可克隆的仓库里暴露 19 天**（首次提交 `9e414df`，2026-09-01；已确认远端 HEAD 含它） | **处置（先止损、后改码）**：① 🔴 **企业微信后台吊销/轮换旧凭据（用户侧，唯一真止损）** —— 删代码挡不住别人拿旧凭据调用；② 三处改为 `src/env_util.require_env("WECOM_BOT_ID" / "WECOM_SECRET")`，凭据只放本机 `.env`（`.gitignore:14` 已覆盖）；③ **新增防再犯守卫** `tests/test_wecom_env.py::test_no_hardcoded_credentials_in_source`（扫描随仓库发布的 Python，命中即红、**只报位置不报值**）；④ 缺 env 时**开局 raise 明确报错**（不静默空串）。⚠️ **平台不会替你兜底**：实测 GitHub Secret Scanning 对该凭据类型 **0 条告警**。⚠️ **未做**：清理 git history（公开 19 天大概率已被爬取，收益有限，且需 force push；单独立项）。**2026-09-20 后续**：用户决定**不再使用企业微信通道** ⇒ 三个模块与 `scripts/wecom_service.bat` **已删除**（`git rm`；顺带消掉下面的 G2/G3），`src/env_util.py` 与守卫保留（非 wecom 专属；守卫保护整个仓库）。详见 `tasks/2026-09-20-wecom-cred-revoke/journal.md` |
| **G2** | **（2026-09-20 已解决）** 依赖清单缺口：`wecom_sdk.py` 导入 `wecom_aibot_sdk`、`wecom_channel/ws.py` 导入 `websockets`，两者都不在 `requirements.txt` | 三个模块已删除 ⇒ 缺口消失（实测本机 venv 其实早已装了这两个包，所以从未暴露） | ✅ 无需动作。⚠️ 若将来重新引入需要这两个包的模块，**必须**同时补进 `requirements.txt` |
| **G3** | **（2026-09-20 已解决）** 孤儿模块：`wecom_*` 三模块在仓库内无任何引用，只能手动启动；与「Hermes → QQ」是两条并行推送路径 | 三个模块已删除 ⇒ 职责边界不再有歧义：**当前唯一的推送路径是「Hermes → QQ」** | ✅ 无需动作 |
| **G4** | `src/image_renderer.py` 的 **15s 超时 / ≤800KB 尺寸守卫 / zoom 重试已在 `a536888` 删除，当前未实现** | 图片化推送缺乏超时与体积保护 | 按需恢复（见 `docs/architecture.md` §模块划分注） |
| **G5** | 板块热度偶发取数失败（`us_sector_heat` 更脆弱） | 前端「数据暂缺」，静默降级不中断日报 | 已在任务队列中（见 §10） |
| **G6** | 仓库根目录有开发残留：`_dbg_hist.json`、`_phase5_run.log`、`web_uvicorn.log`、`task brief.md`、`依赖初始化.md`、`初始prd.md` | 噪声；且外部 cron 的 `git add -A` 会把临时文件提交进仓库 | 清理并确认 `.gitignore` 覆盖 |
| **G7** | **（2026-09-14 曾标记已解决；2026-09-20 复发 → 当日彻底修复）** 仓库外 cron「MarketPulse 自动推送GitHub」（`*/5`）把仓库里**已暂存的**非数据改动一并提交：2026-09-20 16:35 提交 `6ec1562 auto: 每日数据更新`，内含 4 个源码删除 + 1 个测试重命名（`src/wecom_{channel,sdk,ws}.py`、`scripts/wecom_service.bat`、`tests/{test_wecom_env.py => test_env_util.py}`）—— 那是架构师当时**刚 staged、尚未 commit** 的改动。 | 别处未提交的改动被「顺手」提交，`git status` 失真、「改动像丢了」 | 🔴 **真根因（2026-09-20 实测更正；此前把根因写成「prompt 模式不可靠」并不准确）**：`git commit` **不带 pathspec 时提交的是整个暂存区（index）**，而不是「刚 `git add` 的那些」；`git add <白名单>` 只能**添加**、无法**排除** index 里已有的内容。该 cron 的 prompt **明确禁止了** `git add -A` 且被忠实执行 —— 漏洞是「范围只写在 `git add` 上」。**修复（两处，缺一不可）**：① `src/git_ops.py::_commit` 改为 `git commit -m <msg> -- <paths>`（**三个报告入口原本有同一个洞**，只是平时在干净工作区跑所以没暴露）；② 该 cron 由 prompt 模式改为 **script 模式**（`--no-agent`；wrapper `D:\hermes\scripts\marketpulse_autopush.py` → `scripts/auto_commit_data.py` → 复用 `git_ops` 路径白名单），使范围**由代码强制**而非靠 LLM 照做。护栏：`tests/test_phase26.py::test_commit_pathspec_isolates_unrelated_staged_changes`（真临时仓库）+ `test_commit_uses_pathspec`。详见 `tasks/2026-09-20-autopush-pathspec-fix/journal.md` |
| **G9** | **（2026-09-19 已解决）** web 层**零鉴权**：`web/app.py` 无任何 auth（grep `auth\|login\|token\|password\|API_KEY\|Secret` 零命中），线上 `marketpulse-blue.up.railway.app` 的 `/`、`/api/timeline`、`/api/watchlist` 全部 200 可读 ⇒ 任何人拿到 URL 即可读全部数据，`/api/watchlist` 实质暴露自选股方向 | **P0**：数据全网可读（含自选配置） | **已解决**：全站 **HTTP Basic Auth**（`web/app.py` 中间件；零新依赖 `base64` + `hmac.compare_digest`）+ 无鉴权的 `/healthz` + `railway.toml` 的 `healthcheckPath` 改为 `/healthz`（🔴 不改会让部署因 healthcheck 401 陷入重启循环）。env：`MP_AUTH_USER` / `MP_AUTH_PASS` / `MP_AUTH_DISABLED`；**未配置 ⇒ fail-open**（与项目"失败降级不中断"纪律一致，已裁定）⇒ 公网部署**必须**配并 curl 验 401。验收 `AUTH-*` 7 条 + 单测 9 条（见 `tasks/2026-09-19-web-basic-auth/journal.md`） |
| **G8** | **（部分解决 2026-09-20 → 见下）** **UI 验收的 12 条常红断言**（2026-09-16 21:44 独立重跑 `verify_ui.py`：`EXIT=1`，`FAILED: 12 条`）。其中 **10 条是上游取数被拒导致的"数据层红"**：`/api/macro` 4 个品种 `value` 全 `null`、`trend.dates=[]`（→ `MX-6` / `MX-7` / `MX-8` / `MX-9` / `MX-13` / `M-4` / `M-5` / `XC-0` 红）；`/api/econ` `as_of=null`（→ `MX-11` / `MX-11b` 红，页面显示「数据暂缺」）。**自测到的上游状态（2026-09-16 21:5x）**：Yahoo chart 直打 `query1` 与 `query2` **均 `HTTP 403`** —— 三十四期的「双主机轮换」已**无法自愈**（两台同时被拒，轮换没有逃生口）；同一时刻 BLS 亦取不到 `as_of`；`/api/cn/quotes` 的 `cny` 同样 `failed`（同一个 Yahoo 403）。另 **2 条与数据无关**：`N-12a` / `N-12b`（Firefox `scrollbar-*` CSSOM 门控专项） | 验收脚本**常年 `EXIT=1`** ⇒ 真回归会被"红色背景"淹没（本项目已有"红色被当噪声"的先例，见 G5）；`/macro` 与 `/macro/cn` 上报价与宏观数据大面积显示「数据暂缺」，功能实际不可用 | ✅ **2026-09-20 已完成「判据分层」（`tasks/2026-09-20-verify-ui-signal-layering/`）**：`verify_ui.py` 改为三态 `PASS / FAIL / SKIP` —— **只有上游被独立直连探测确认不可用**时，带 `deps=` 的断言才记 `SKIP`（不计失败）；上游可用时同样的失败**仍是 `FAIL`**（保证 SKIP 不会掩盖代码回归，见该 plan §3.3 两条硬约束）；汇总同时给三计数 + `上游探测` 行 + `report.json` 的 `skipped`/`upstream` 键；`--strict` 让 SKIP 也判失败。上线当日实测：上游正常时 `PASS 679 / FAIL 0 / SKIP 0`；死代理模拟上游不可用时那 10 条**全部降级为 SKIP 且 `FAILURES` 为空**。**未做**（仍开放）：① 给 Yahoo 链路走代理或换源（数据源任务）；② 那 2 条 `N-12` **已不是红**（2026-09-20 实测通过，G8 原文是 09-16 快照），本任务保持其判据作回归护栏 |

---

## 10. 进行中的任务队列

| 顺序 | 任务 | 内容 | 计划 |
|---|---|---|---|
| 1 | `2026-09-14-us-sector-table` | 美股板块 tab 表格化（与 A股 同构）+ 取数稳定性 | `tasks/2026-09-14-us-sector-table/plan.md` |
| 2 | `2026-09-14-sector-stale-fallback` | 板块热度逐键回填 + `· 数据截至 …` 标注 | `tasks/2026-09-14-sector-stale-fallback/plan.md` |
| 3 | `2026-09-13-rss-macro-news` | 新闻流改 RSS 双源（**已执行**，`src/rss_fetcher.py` 已存在） | `tasks/2026-09-13-rss-macro-news/plan.md` |
| 4 | `2026-09-13-news-autoscroll` | 最新资讯自动循环滚动 | `tasks/2026-09-13-news-autoscroll/plan.md` |

**串行约束**：1 → 2（都改 `renderUsSectors`）；3 → 4（3 改资讯条数，4 的基线要按最终条数测）。

---

## 11. 规模统计

| 部分 | 规模 |
|---|---|
| `src/` | 17 模块 ≈ **5159 行** |
| `web/` | `app.py` 1198 · `app.js` 1235 · `macro.js` 约 860 · `macro_cn.js` 653 · `style.css` 881 · `index.html` 235 · `report_card.html` 160 · 模板 `macro.html` / `macro_cn.html` / `_topbar.html` / `_sidebar.html` |
| `scripts/` | 6 个 |
| `tests/` | 31 个测试文件（约 659 条用例） |
| `docs/` | `architecture.md`（决策台账）· `commands.md`（验证命令）· `pitfalls.md` 473 行（踩坑记录）· `architecture-diagram.html` · **本文** |
| 迭代 | 35+ 期 |

**其它目录**：
- `skills/` — 2 个 Agent 工作流技能（`bug-fix/SKILL.md`、`pre-review/SKILL.md`）
- `tasks/` — 按 `<日期>-<简述>/` 组织，每任务含 `prd.md` / `plan.md` / `journal.md`

---

## 12. 相关文档

| 文档 | 内容 | 何时读 |
|---|---|---|
| `AGENTS.md` | 项目规范与命令 | 每次开工前 |
| `docs/architecture.md` | **决策台账**（选了什么 / 为什么 / 何时） | 改架构相关代码前 |
| `docs/commands.md` | 验证命令与「何时跑什么」 | 改完代码后 |
| `docs/pitfalls.md` | 踩坑记录（402 行） | 改相关模块前 |
| **本文** | 系统现状总览 | 首次接触 / 需要全局视角 |
