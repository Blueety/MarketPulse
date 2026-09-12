# Plan — 自选股看板文件化（快照落盘，web 读文件零延迟）

> 日期：2026-09-12 ｜ 角色：架构师 ｜ 状态：待用户确认后交执行者
> 本任务无独立 prd.md，Goal 由用户需求原文提炼，已确认方向为「方案 A：彻底文件化」。

## 0. 结论先行

**根因**：看板其他卡片（概览/趋势/板块/告警）读本地文件（`data/history.json` / `context/*.json` / `alerts/*.md`），毫秒级返回；而 `/api/watchlist`（`web/app.py:503`）在缓存过期（TTL 仅 90s，`web/app.py:44`）后走 `fetch_watchlist`（`src/fetcher.py:609`）**实时联网取数**——A 股走 AkShare/新浪（`ak.stock_zh_a_daily`，akshare 冷 import 1~3s + 网络请求），美股/ETF 走 Yahoo chart `range=3mo`，整体限时 10s。前端 `app.js:896` 因此设计了「加载中…」占位 + 12s 超时。**慢是 28 期"实时取数"设计的固有代价，不是 bug。**

**选型**（用户已确认方案 A）：

| 方案 | 思路 | 取舍 |
|---|---|---|
| A 文件化（**选定**） | 报告链路落盘自选股快照，web 只读文件，与其他卡片同源同语义 | 放弃盘中实时；需处理新鲜度标注与配置变更窗口 |
| B 旧值秒出+后台刷新（SWR） | 保留实时，先回旧缓存后台刷新 | 改动更小但保留实时复杂度；用户选了更彻底的 A |
| C 只调缓存 TTL+预热 | 90→300s + 启动预热 | 过期后仍有一次慢加载，不彻底 |

**方案 A 关键事实依据**（已核实）：
1. `context/*.json` **不能**作为持久化落点——`snapshot_report.py:82` 的 `generate_context` 不传 watchlist，快照运行会用空 watchlist 结构覆盖当日 context；且 context 是 Hermes 契约面，塞 30 点×N 标的的序列会膨胀契约。**必须用独立文件 `data/watchlist.json`**。
2. `.gitignore` **没有忽略 `data/`**（`history.json`/`last_values.json` 均随 auto-push 入库）→ `data/watchlist.json` 同样会被 `auto_commit_push` 提交并部署到 Railway，文件化在 Railway 上成立。
3. `daily_report.py:134` 已有现成的 `fetch_watchlist` 调用与原始序列（`wl_series`），落盘零新增取数。

---

## 1. 任务目标（Goal）

> 引用：无 prd.md；Goal 按用户需求提炼并经用户确认。

- **G1**：web 看板自选股卡片（表格 + 趋势迷你图 + KPI 第 4 卡）加载与其他卡片一致——打开即现，不再有数秒级「加载中…」等待。
- **G2**：实现方式为"文件化"：自选股数据由报告链路（daily_report 为主，snapshot 为新鲜度补齐）落盘快照，`/api/watchlist` 只读文件构建响应，请求路径**零联网**（回退路径除外，见 S3）。
- **G3**：用户已接受的语义变更：数据新鲜度从"实时"降为"最近一次报告运行时点"，前端须以数据时点标注防误读（先例：概览表 source_date「（MM-DD收盘）」小字）。

## 2. 要改的文件列表

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/analyzer.py` | 新增 `WATCHLIST_FILE` 常量 + `save_watchlist_snapshot()` / `load_watchlist_snapshot()` | 持久化归属模块（与 last_values/history 同居、同原子写纪律） |
| `daily_report.py` | 取数成功后 +1 次 `save_watchlist_snapshot` 调用（try/except 包裹） | 主写入点 |
| `snapshot_report.py` | main() 尾部（`auto_commit_push` 前）新增自选股快照刷新块 | 新鲜度对齐：用户当前持仓是 A 股 ETF（515300.SS），若无此步，A 股盘中（09:30–15:00）自选股显示昨收而概览表显示 11:30/15:00 盘中值，观感不一致 |
| `web/app.py` | `_load_watchlist` 重构为"读快照文件优先 + 配置比对 + 实时取数回退"；配置读取抽为 `_watchlist_config()` | 端点行为变更核心 |
| `web/templates/index.html` | 自选卡副标题「· 实时取数」→「· 数据时点 <span id=…>」；表头「现价」→「最新价」 | 文案随语义变更 |
| `web/static/app.js` | `renderWatchlist` 渲染 `as_of` 时点标注；空态文案「数据暂缺（实时取数失败）」→「数据暂缺」 | 同上 |
| `tests/test_analyzer.py` | 新增快照读写测试类 | |
| `tests/test_web.py` | 新增文件命中/回退/配置比对端点测试；既有 `_reset_watch_cache` fixture 适配 | |
| `docs/architecture.md` / `AGENTS.md` / `docs/pitfalls.md` | 完成后按 Working Rules 补决策行/项目地图/坑位记录 | 收尾步骤，不阻塞验收 |

不改动：`src/fetcher.py`（取数逻辑原样复用）、`src/reporter.py`、context 契约、Hermes 相关一切、`.env`、`config.json`。

## 3. 实现步骤（每步可独立验证）

### S1 analyzer 持久化层

`src/analyzer.py` 新增（与 HISTORY_FILE 同区）：

- 常量：`WATCHLIST_FILE = DATA_DIR / "watchlist.json"`
- `save_watchlist_snapshot(stocks_cfg, values, series) -> bool`
  - **守卫**：`stocks_cfg` 为空 或 `values` 为空（全标的失败）→ 不写、返回 False（沿用 merge_history「取数全失败→空操作，绝不制造空行」纪律，防止用垃圾覆盖昨日好快照）
  - 写入结构（**存原始数据，不做展示加工**——加工留在 web 层，避免把 web 函数搬进 src）：

    ```text
    {
      "saved_at": "<本地时间 ISO，仅展示用，不参与逻辑>",
      "stocks":   [ stocks_cfg 原样（symbol/label） ],
      "values":   { "515300.SS": 4.01, ... },            # 缺失标的即无键
      "series":   { "515300.SS": [["2026-07-01", 3.98], ...] }  # tuple→JSON 自动变 list
    }
    ```
  - 原子写：`tmp + os.replace`（复用 save_history 范式），断言无 `.tmp` 残留
- `load_watchlist_snapshot() -> dict | None`
  - 文件缺失 / 坏 JSON / 非 dict / 缺 `stocks|values|series` 任一键 / `stocks` 非列表 → 返回 `None`（容错纪律同 load_history）
  - **tuple→list 兼容**：JSON 反序列化后 `series` 内是 list-of-list；`web/app.py` 的 `_build_watchlist_payload` 只做解包（`for d, _ in pts`）与索引访问（`pts[-2][1]`），list 完全兼容，测试钉死此点

**验证（S1）**：`venv/Scripts/python -m pytest tests/test_analyzer.py -v`（新增用例全绿 + 既有用例零回归）

### S2 daily_report 写入接线

`daily_report.py` 在既有 `wl_values, wl_series, wl_errors = fetch_watchlist(stocks_cfg)`（约 ：134）成功路径内追加：

```text
try:
    save_watchlist_snapshot(stocks_cfg, wl_values, wl_series)
except Exception:
    log only   # 快照写入失败不影响日报主流程（决策 H 同款容错）
```

**验证（S2）**：`AUTO_PUSH=0 venv/Scripts/python daily_report.py` → ① 日报正常生成退出码 0；② `data/watchlist.json` 生成且内容含配置标的（515300.SS）；③ 连跑两次文件被覆盖不报错。

### S3 web 端点文件优先 + 回退

`web/app.py` 重构 `_load_watchlist`（既有 env `WATCHLIST_STOCKS` > `config.json` 的配置读取逻辑原样抽成 `_watchlist_config() -> list[dict]`）：

```text
def _load_watchlist():
    cfg = _watchlist_config()
    if not cfg: return {"hidden": True, **empty}          # 语义不变
    snap = load_watchlist_snapshot()                        # import 到 web.app 模块级绑定
    if snap and symbols(snap["stocks"]) == symbols(cfg):    # 配置比对：防改配置后展示旧标的
        payload = _build_watchlist_payload(snap["stocks"], snap["values"], snap["series"])
        payload["as_of"] = snap.get("saved_at")             # 新增字段，向后兼容
        return {"hidden": False, **payload}
    # 回退（文件缺失/损坏/配置已改）：走既有实时取数路径，原逻辑原样保留
    ... 既有 fetch_watchlist + try/except 降级空结构 ...
```

- **`_build_watchlist_payload` / `_normalize_series` / `_series_tail` 零改动**（测试锁定的纯函数）
- 90s TTL 内存缓存与 `_watch_failed`/stale 逻辑**保留不动**：对文件路径无感（命中缓存直接返回），对回退路径仍是保护
- **monkeypatch 纪律**：`load_watchlist_snapshot` 以模块级名字导入到 `web.app`，测试打 `web.app` 侧（pitfalls：打在定义方 analyzer 不生效）

**验证（S3）**：`venv/Scripts/python -m pytest tests/test_web.py -v`；新端点用例：
1. 文件命中：mock `_load_watchlist_snapshot` 返回样例 + mock `fetch_watchlist` 为「被调用即 fail」→ 端点仍 200 且数据来自文件（**证明请求路径零联网**）；
2. 配置比对失败（快照标的 ≠ 配置标的）→ 走实时回退；
3. 无快照文件 → 走实时回退（既有用例应原样通过，作为回归锚）。

### S4 前端时点标注 + 文案

- `index.html`：自选卡 `<h2>` 副标题「· config.json 配置 · 实时取数」→「· config.json 配置 · <span id="watchlist-asof">收盘快照</span>」；表头「现价」→「最新价」
- `app.js` `renderWatchlist`：`payload.as_of` 存在时把 `MM-DD HH:MM` 写入该 span（无则保持默认文案）；空态文案去掉「（实时取数失败）」
- 「加载中…」初始占位**保留**（现在毫秒级即被替换）

**验证（S4）**：UI 验收必须跑 `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（AGENTS.md 硬规定，Playwright 三视口）；另起未缓存端口手测（pitfalls：Jinja2 模板缓存 / CSS 跨端口缓存假阴性）。

### S5 snapshot_report 新鲜度对齐（推荐，与 S2–S4 解耦，可单独取舍）

`snapshot_report.py` main() 在 context 更新块之后、`auto_commit_push` 之前新增（try/except 包裹，失败仅记日志）：

```text
if 配置了 watchlist.stocks:
    wl_values, wl_series, _ = fetch_watchlist(stocks_cfg)   # 自带 10s 线程限时
    save_watchlist_snapshot(stocks_cfg, wl_values, wl_series)
```

- 效果：自选股数据随 4 个 cron（A 股 11:30/15:00、美股 21:30/00:00）刷新，与其他卡片的数据更新节奏一致
- 代价：每次快照运行 +2~8s（AkShare 冷 import 在进程内只付一次）
- `alt` 时段同样刷新（无害）

**验证（S5）**：真跑一次 `AUTO_PUSH=0 venv/Scripts/python snapshot_report.py --market a-share --time midday`（注意：会写当日 history/context/快照文件，AUTO_PUSH=0 防推送；交易日验证后无需清理——均为真实数据落地）→ `data/watchlist.json` 的 `saved_at` 更新。

### S6 全量回归 + 文档收尾

- `venv/Scripts/python -m pytest tests/ -v` 全绿
- `git diff` 核对改动范围仅限第 2 节清单
- 按 Working Rules 更新 `docs/architecture.md`（决策行：自选股文件化）、`AGENTS.md`（web/ 行 5 个 API 描述补 watchlist 数据来源）、`docs/pitfalls.md`（新增本任务坑位，见 §5）

## 4. 验证命令（引用 docs/commands.md）

| 步骤 | 命令 | 通过标准 |
|---|---|---|
| S1/S3/S6 | `venv/Scripts/python -m pytest tests/ -v` | 全绿，含新增用例 |
| S2 | `AUTO_PUSH=0 venv/Scripts/python daily_report.py` | 日报正常 + `data/watchlist.json` 生成 |
| S3 手测 | `venv/Scripts/python -m uvicorn web.app:app --port 8016`（未用过的端口） | 浏览器打开 `http://localhost:8016`：自选卡**即时出现**（体感与其他卡片无差）；`curl -w "%{time_total}" http://localhost:8016/api/watchlist` 热/t 均应 < 0.2s |
| S3 回退 | 备份并移走 `data/watchlist.json` → 重启 uvicorn | 端点仍 200（走实时回退，慢但正确）；**验证后必须恢复文件**（pitfalls：验证期数据必须恢复） |
| S4 | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 三视口通过，自选卡正常渲染、时点标注显示 |
| S5 | `AUTO_PUSH=0 venv/Scripts/python snapshot_report.py --market a-share --time midday` | 快照生成 + `data/watchlist.json` `saved_at` 刷新 |

## 5. 风险评估和注意事项

1. **新鲜度语义变更（用户已确认）**：自选股显示"最近报告时点"值而非盘中实时。缓解：`as_of` 时点标注（S4）。KPI 第 4 卡与迷你 sparkline 同源受此影响，属预期。
2. **配置变更窗口**：用户改 `config.json` watchlist 后到下次报告运行前，快照与配置不一致 → 端点自动回退实时路径（慢但正确，不会展示旧标的）。靠 S3 的 symbol 列表比对保证。
3. **Railway env 一致性**：若 Railway 用 env `WATCHLIST_STOCKS` 且与本地 `config.json` 写快照时的标的不一致 → 恒 mismatch → 恒走实时回退（等于回到现状，不坏但优化失效）。注意事项：env 与 config.json 保持单一来源；否则考虑后续把 stocks_cfg 一并存入快照并以其为准（本任务不做）。
4. **多入口写同一文件**：daily + 4 snapshot cron 写 `data/watchlist.json`——Hermes cron 错峰不并发，且原子写兜底；与 history/context 多入口写同先例。
5. **测试隔离**：`web.app` 模块级导入的 `load_watchlist_snapshot` 必须打使用方补丁；`_watch_cache` 跨测试泄漏沿用既有 autouse fixture；新增用例不得依赖真实 `config.json`（conftest 已隔离 CONFIG_PATH）。
6. **既有用例回归**：`test_web.py:612+` 现有 watchlist 用例基于"实时取数"路径（conftest tmp 环境无快照文件 → 自动走回退），理论上原样通过；若失败说明文件优先逻辑越界，先查 S3 实现。
7. **series tuple→list**：JSON 往返后 `_build_watchlist_payload` 的解包/索引访问兼容，但需测试钉死，防止未来改成 `pts` 结构化访问时悄悄破坏。
8. **`.gitignore`**：`data/` 未被忽略，`data/watchlist.json` 将随 auto-push 入库（与 history/last_values 同语义，Railway 可用）。如未来有人把它加进 gitignore，Railway 上的文件化自动失效（回退实时），属可接受的静默降级。
9. **快照跳过场景**：休市日 `_is_market_closed` gate 在 main 开头 return → 休市日不刷新快照（合理：无新数据）；若快照文件尚不存在（首次部署）且恰逢休市，web 走实时回退，自愈于下一交易日。

## 6. 预计影响的文件范围

- **直接改动**（7 个源文件 + 2 个测试文件）：`src/analyzer.py`（+约 50 行）、`daily_report.py`（+约 6 行）、`snapshot_report.py`（+约 10 行）、`web/app.py`（±约 30 行）、`web/templates/index.html`（±约 3 行）、`web/static/app.js`（+约 5 行）、`tests/test_analyzer.py`（+约 40 行）、`tests/test_web.py`（+约 60 行）
- **运行时新增**：`data/watchlist.json`（生成物，随 auto-push 入库）
- **文档收尾**：`docs/architecture.md`、`AGENTS.md`、`docs/pitfalls.md`
- **零改动**：`src/fetcher.py`、`src/reporter.py`、context 契约、`tests/test_phase7.py` 等其他测试
