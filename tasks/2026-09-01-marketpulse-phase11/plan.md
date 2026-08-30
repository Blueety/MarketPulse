# MarketPulse 十一期：Web 看板 — 实施计划

> 架构师只读分析产出。目标、涉及文件、核心设计、实施步骤、验证命令、风险与待确认决策。
> 分析基线：`data/history.json`（10 键小写序列，含 gld/btc）、`context/2026-08-30.json`（indices / history_30d / sector_heat / us_sector_heat）、`src/alerter.py`（告警文件 frontmatter + 字段格式）、`tests/conftest.py`（CONFIG_PATH 隔离）、`requirements.txt`（web 依赖均未安装）。

## 目标

- FastAPI Web 看板：浏览器展示最近 7 天市场数据（趋势图 / 指数表格 / 板块热度 / 告警记录）。
- 只读：直接解析现有 JSON/Markdown 生成物（`data/history.json`、`context/*.json`、`alerts/*.md`），无数据库、不写任何数据文件。
- 单页 + 响应式（桌面/手机），Chart.js CDN 渲染多条折线。

## 涉及文件

| 文件 | 改动类型 |
|---|---|
| `requirements.txt` | +4 依赖：fastapi / uvicorn / jinja2 / httpx（理由见「待确认决策 A」） |
| `web/__init__.py` | 新增（空文件，使 `web.app` 成为常规包模块，uvicorn 无歧义加载） |
| `web/app.py` | 新增：FastAPI 应用 + 4 端点 + 数据解析纯函数 |
| `web/templates/index.html` | 新增：单页模板（Chart.js CDN，内联 JS 调 3 个 API） |
| `web/static/style.css` | 新增：响应式样式（media query 移动端单列） |
| `tests/test_web.py` | 新增（约 18-22 条，TestClient + tmp_path 夹具） |
| `AGENTS.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` | 文档同步 |

不改：`daily_report.py`、`snapshot_report.py`、`src/*`、`config.py`、`config.json`、`.gitignore`（web/ 为源码，本就入库；生成物目录已排除）。

## 核心设计

### 1. 数据源与解析（全部纯函数，可单测）

| 端点 | 数据源 | 解析 |
|---|---|---|
| `/api/history` | `data/history.json` | `load_history()` 复用 analyzer 既有解析（损坏 → 空列表）；取**最后 7 条**记录，展开为 Chart.js 友好结构 `{dates, series: [{key, label, values}]}` |
| `/api/latest` | `data/history.json` 末两条 + 最新 `context/*.json` | value 取最后一条；change_pct = 相对前一条非空基准计算（`(cur-prev)/prev*100`，基准 null/缺失 → null）；status 从最新 context 的 `indices[SYM].status` 复用（context 缺失 → null，不崩） |
| `/api/alerts` | `alerts/*.md` | 解析 frontmatter（type/date/symbol/level）+ 正文字段（级别/当前值/昨日收盘/变化率/阈值/市场状态/建议/相关报告）；按文件名日期倒序取**最近 10 条**；目录缺失/空 → `[]` |
| `/` | — | 渲染 `index.html`（jinja2） |

- **路径常量在 web/app.py 内定义并引用**（`HISTORY_FILE = analyzer.HISTORY_FILE` 等，从 analyzer 导入复用单一事实来源）：测试按既有纪律 `monkeypatch.setattr(web.app, "HISTORY_FILE", tmp_path / ...)` 打在使用方模块。
- **板块热度**（模块 3）：PRD 数据来源表「从 history.json 最新条目或单独 JSON」——实测 history.json **无**板块数据；板块数据唯一存在于 `context/*.json` 的 `sector_heat`（含 gainers/losers，八期契约）。设计：读**最新日期** context JSON 的 `sector_heat`，随 `/api/latest` 一并返回；context 缺失/键缺失 → 降级「数据暂缺」空结构。A 股板块 Top5（gainers）为默认展示，`us_sector_heat` 可选（见「待确认决策 B」）。
- **涨跌幅一致性**：`/api/latest` 用 history 相邻记录自算 change_pct（不读 `last_values.json`——该文件是次日告警基准，读它违反只读语义且可能含未更新值）；status 复用 context（与日报同一事实来源）。

### 2. 响应结构（前端零加工）

```jsonc
// /api/history
{ "dates": ["2026-08-24", ..., "2026-08-30"],           // 最近 7 交易日
  "series": [ { "key": "gspc", "label": "标普500", "values": [7120.5, ..., 7138.8] }, ... 10 组 ] }
// /api/latest
{ "date": "2026-08-30",
  "indices": [ { "symbol": "GSPC", "label": "标普500", "value": 7138.8,
                 "change_pct": 0.25, "status": "..." | null }, ... 10 组 ],
  "sector_heat": { "gainers": [...], "losers": [...] } }   // 无则 { "gainers": [], "losers": [] }
// /api/alerts
[ { "date": "2026-08-30", "type": "close", "symbol": "VIX", "level": "WARN",
    "current": 26.1, "last": 21.4, "change_pct": 22.0, "threshold": 20.0,
    "state": "警惕", "suggestion": "...", "report": "2026-08-30.md" }, ... 最多 10 条 ]
```

- 指数顺序/label 用 `fetcher.SYMBOLS` 注册表（10 键：GSPC/IXIC/SH/SZ/CYB/VIX/VXN/MOVE/GLD/BTC）——看板与日报同序同标签，零重复定义。
- history 值含 `null`（休市/获取失败，样本 2026-08-29 vix=null）：series 保留 null，Chart.js `spanGaps: false` 断点显示，不插值。

### 3. 趋势图分组（Chart.js）

- 10 序列量级悬殊（BTC ~78000 vs VIX ~15），**单图 10 折线会被波动率压扁**。按 SYMBOLS 语义分 4 图，各图独立 y 轴：
  - 美股大盘（GSPC/IXIC）、A 股大盘（SH/SZ/CYB）、波动率（VIX/VXN/MOVE）、另类资产（GLD/BTC）。
- 前端 fetch `/api/history` 后按 series.key 归组生成 4 个 canvas；颜色沿用九期趋势图既有色系（GSPC 蓝 / IXIC 绿 / SH 红 / SZ 橙 / CYB 紫 / VIX、VXN、MOVE 沿用日报波动率色 / GLD 金 #d4a017 / BTC 橙 #f7931a）。
- 图例/工具提示走 Chart.js 默认；`responsive: true` 自适应容器宽度。

### 4. 页面布局（index.html + style.css）

- 单页四模块，自上而下：市场概览表（最新日 10 指数收盘/涨跌幅/状态）→ 4 张趋势图 → 板块热度（领涨 Top5 表，可选加领跌/美股）→ 告警记录（最近 10 条卡片式列表）。
- 响应式：`grid-template-columns` 桌面多列 / `@media (max-width: 768px)` 单列；表格横向滚动容器防手机溢出。
- 状态着色：change_pct 正绿负红；告警 level WARN 橙 / ALERT 红。
- Chart.js 经 CDN（jsdelivr）加载；`onerror` 时图区显示「图表加载失败」降级文案（无外网环境不白屏）。
- 页面 JS 内联于模板（单文件、无构建）；CSS 独立 `web/static/style.css`（PRD 文件结构预留 static/ 实际启用）。
- 模板/静态目录定位用 `Path(__file__).resolve().parent` 显式解析，不依赖 cwd。

### 5. 依赖（新增 4 个，`requirements.txt`）

```
fastapi>=0.115.0
uvicorn>=0.30.0
jinja2>=3.1.0
httpx>=0.27.0
```

- httpx 是 FastAPI TestClient 的传递必需依赖（starlette 依赖），必须显式声明。
- uvicorn `--reload` 在无 watchfiles 时用内置 StatReload（轮询），满足 PRD「uvicorn web.app:app --reload 能启动」，不额外加 watchfiles。
- 与既有风格一致：固定版本（requests==/pytest==）与下限版本（matplotlib>=/akshare>=）混用，新增走下限风格。

## 实施步骤

1. **requirements.txt** +4 依赖；`venv/Scripts/pip install -r requirements.txt`。验证：`venv/Scripts/python -c "import fastapi, uvicorn, jinja2, httpx"` 无错。
2. **web/app.py**：路径常量（复用 analyzer 的 HISTORY_FILE/ALERTS_DIR/CONTEXT_DIR/DATA_DIR 引用）→ 解析纯函数（`_last_records(n)` / `_compute_latest(history)` / `_parse_alert_file(path)` / `_load_alerts(limit=10)` / `_load_sector_heat()`）→ FastAPI 实例 + 4 端点（模板渲染用 `Jinja2Templates`，静态挂 `/static`）。验证：`venv/Scripts/python -c "from web.app import app"` 无错。
3. **web/templates/index.html** + **web/static/style.css**：布局 + 分组图 + API 接线。验证：见下（浏览器实测）。
4. **web/__init__.py** 空文件。
5. **tests/test_web.py** 新增（见下）→ `pytest tests/test_web.py -v` 绿。
6. **全量回归**：`venv/Scripts/python -m pytest tests/ -v`（既有 211 + 新增全绿；存量测试不触碰——web 为独立模块，conftest 隔离不受影响）。
7. **实跑验证**（见下验证命令 2-3）。
8. **文档同步**：architecture.md 加「Web 看板」模块行与数据流、commands.md 加启动命令与验证要点、pitfalls.md 加 web 易错点（路径常量 patch 位置 / 板块热度数据源在 context / alerts 空目录容错）。

## 新增测试 tests/test_web.py（约 18-22 条，TestClient + monkeypatch 路径常量到 tmp_path）

- **解析纯函数**：`_last_records` 取最后 7 条 / 空文件 → []；`_compute_latest` 相邻变化率、基准 null → change_pct null、历史仅 1 条 → change_pct null、历史空 → None；`_parse_alert_file` frontmatter + 字段完整解析、缺字段容错；`_load_alerts` 按日期倒序 limit=10、目录缺失 → []。
- **板块热度**：有 context（gainers/losers 契约）→ 返回结构正确；context 缺失 / 键缺失 → 空结构（降级）。
- **API 端点**（monkeypatch 路径常量指向 tmp_path 夹具后走 TestClient）：`GET /` → 200 + text/html；`GET /api/history` → 200、dates 长度 ≤7、series 10 组、null 保留；`GET /api/latest` → 200、indices 10 键含 value/change_pct/status；`GET /api/alerts` → 200、≤10 条、字段完整；全部端点空数据（无 history/alerts/context）→ 200 + 空结构不崩。
- **夹具**：手写小 history.json（含 null 值）+ 1-2 个告警 md（按 render_alert 真实格式）+ 1 个 context json。

## 验证命令（对应 PRD Verification）

1. `venv/Scripts/pip install -r requirements.txt` — 新依赖安装成功。
2. `venv/Scripts/python -m pytest tests/ -v` — 全量全绿（既有 211 条不回归 + 新增）。
3. 启动：`venv/Scripts/uvicorn web.app:app --reload --port 8000`（或 `venv/Scripts/python -m uvicorn web.app:app --reload`）— 无报错、监听 8000。
4. 浏览器访问 `http://localhost:8000` — 页面完整：概览表 10 指数、4 张趋势图多条折线、板块热度 Top5、告警区（当前 alerts/ 为空 → 显示空态文案「暂无告警记录」）、无 JS 控制台错误。
5. 数据一致性：`/api/history` 返回的末条 value 与 `data/history.json` 最后一条逐值一致（curl + python 断言）；`/api/latest` 涨跌幅与相邻记录手算一致。
6. 手机自适应：DevTools 设备模拟（375px 宽）— 单列布局、表格横向可滚、图表不溢出。
7. 断网/无 CDN：Chart.js 加载失败 → 图区降级文案，页面其余模块正常。

## 待确认决策

- **A（必须）**：新增 4 个运行依赖（fastapi/uvicorn/jinja2/httpx）。违反 AGENTS.md「不引入新依赖除非先说明理由」——理由：PRD 技术栈**明确指定** FastAPI + uvicorn + jinja2（Chart.js CDN 不落盘），httpx 为 TestClient 必需。无备选实现路径。
- **B（建议默认）**：板块热度仅展示 A 股领涨 Top5（`sector_heat.gainers`，PRD 字面「当日热点板块 Top5」）。备选：加 A 股领跌（losers）表与美股板块（`us_sector_heat`）——数据现成（context 已含），纯前端加一张表。默认保守范围，选 B 备选可一行扩展。
- **C（建议默认）**：趋势图分 4 组（按市场/量级）而非单图 10 折线。理由：量级悬殊（BTC 万级 vs VIX 十几）单轴无法同时看清；4 组与日报板块语义一致。备选：Chart.js 多 y 轴单图——交互复杂且小屏难读，不推荐。

## 风险与边界

- **新依赖安装**：fastapi 依赖 pydantic-core（Rust 扩展），venv 为 Python 3.14（cp314 有 wheel，实测环境可装）；若安装失败需先报障再推进（不绕过）。
- **板块热度数据源偏离 PRD 字面**：PRD 写「从 history.json 最新条目或单独 JSON」但 history.json 无板块字段；实际唯一来源是 context JSON。实现按「单独 JSON = context」落地并写进 architecture.md 备忘，避免后续误读。
- **alerts/ 当前为空**（gitignore 生成物）：空态必须友好（「暂无告警记录」），解析器对目录缺失/坏文件容错，不 500。
- **Chart.js CDN 依赖外网**：页面降级文案兜底；核心数据表（HTML 直渲）不依赖 JS 可读。
- **只读边界**：web 进程绝不写 data/alerts/context；`/api/latest` 不读 `last_values.json`（它是次日告警基准，非展示数据源）。
- **中文渲染**：浏览器侧无 matplotlib 字体问题；模板/API 均 UTF-8。
- **uvicorn --reload**：Windows 下 StatReload 轮询即可满足 PRD，无需 watchfiles。

## PRD Done When 对照

- `uvicorn web.app:app --reload` 能启动 → 实施步骤 1-4 + 验证命令 3
- 浏览器访问 localhost:8000 看完整看板 → 验证命令 4
- 趋势图多条折线 → 核心设计 3（4 组 10 序列）+ 验证命令 4
- 手机浏览器布局自适应 → 核心设计 4（media query）+ 验证命令 6
- pytest 全绿 → 实施步骤 5-6
- API 端点四件套（/、/api/history、/api/alerts、/api/latest）→ 核心设计 1-2
