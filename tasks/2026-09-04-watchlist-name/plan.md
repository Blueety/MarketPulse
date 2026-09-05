# 实施计划 — 自选股名称/概览旧值问题三项修正（A 定稿保护 / B 展示标注 / C 调度核对）

> 日期：2026-09-04 ｜ 任务目录：`tasks/2026-09-04-watchlist-name/`
> 来源：2026-09-04 诊断（report.md）：① 自选股名称=线上 env label 配置问题（**无需代码改动**，见任务 A 建议段，本计划不重复）；② 概览旧值=daily_report.append_history 整行覆盖在美东盘中跑日报时抹掉快照美股盘中值。
> 模式：仅计划文档，**不改代码/配置**；实施由执行者按本计划操作。

## 1. 目标

| 项 | 做不做 | 决策理由 |
|---|---|---|
| A. 定稿保护 | **做（核心 bug）** | daily append 时本次 fetch 为 None 的美股键若当日行已有盘中值（GSPC/IXIC 非 None），保留盘中值，杜绝整行覆盖为 None → web 回退旧收盘 |
| B. 展示标注 | **做（最小方案）** | web 对前向回填值标注来源日期，避免「数据截至 2026-09-04」旁摆 09-03 收盘值的旧值观感 |
| C. 调度核对 | **只核对不改** | 22:30 档 cron 在 Hermes 侧，仓库内无配置表；给出核对清单与建议，不越权改调度 |

线上 env `WATCHLIST_STOCKS` 修正（label=红利低波ETF）为纯配置操作，见 report.md【任务 A】，不在本计划代码范围内。

## 2. 涉及文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `src/analyzer.py` | 修改 `append_history`（约 L618） | 加 `merge_existing: bool = False` 参数：append 前用当日既有行补全 record 中 None 键 |
| `daily_report.py` | 修改 1 行调用点（约 L198） | `append_history(record, merge_existing=True)` + 注释决策理由 |
| `web/app.py` | 修改 `_compute_latest`（约 L147-183） | 回填时记录来源日期，indices 项加 `source_date` |
| `web/templates/index.html` | 修改 `renderOverview`（约 L200-245） | value/涨跌幅格对回填行加来源标注 |
| `tests/test_merge_history.py` | 新增用例 | append_history merge_existing 语义（4 条） |
| `tests/test_web.py` | 更新/新增 | `_compute_latest` source_date 契约 |
| `docs/architecture.md` | +2 行 | append_history 参数语义、/api/latest source_date 字段 |
| `tasks/2026-09-04-watchlist-name/plan.md` + `journal.md` | 本文件/收尾 | 按 AGENTS 规范 |

不改：`src/fetcher.py` / `src/config.py` / `snapshot_report.py` / `opening_analyzer.py` / `merge_history`（语义已对）/ 任何配置与生成物。

## 3. 实现步骤（每步独立可验证）

### 步骤 1：`src/analyzer.py` — `append_history` 加 `merge_existing` 参数

现状（analyzer.py ~L618-628，实施前先 read 复核行号）：

```python
def append_history(record: dict) -> None:
    """追加当日记录（同日重复按 date 键覆盖），裁剪至最近 90 条；临时文件 + os.replace 原子写。"""
    records = load_history()
    records = [r for r in records if r.get("date") != record.get("date")]
    records.append(record)
    …裁剪 + 原子写…
```

改为：

```python
def append_history(record: dict, merge_existing: bool = False) -> None:
    """追加当日记录（同日重复按 date 键覆盖），裁剪至最近 90 条；临时文件 + os.replace 原子写。

    merge_existing=True（日报定稿用）：当日行已存在且本次 record 某键为 None 时，
    用当日行既有非 None 值补全（防盘中定稿把快照已写入的盘中值整行抹成 None；决策 X）。
    补全仅限 _HISTORY_KEYS 键、date 键除外；默认 False 保持既有覆盖语义（其余调用零影响）。
    """
    records = load_history()
    if merge_existing:
        prev = next((r for r in records if r.get("date") == record.get("date")), None)
        if prev is not None:
            for k, v in record.items():
                if (k != "date" and k in _HISTORY_KEYS and v is None
                        and prev.get(k) is not None):
                    record[k] = prev[k]
    records = [r for r in records if r.get("date") != record.get("date")]
    records.append(record)
    …
```

要点：`_HISTORY_KEYS` 已是小写集合（analyzer.py:62），record 键由 daily 构造为小写（daily_report.py:171 `{k.lower(): …}`），直接 `k in _HISTORY_KEYS`。补全在去重裁剪之前、对 `load_history()` 原始列表执行（不受调用方剔除当日行影响）。

**验证**：`venv/Scripts/python -m pytest tests/test_merge_history.py -v`（含步骤 2 新增用例）。

### 步骤 2：`tests/test_merge_history.py` — 新增 append 语义用例

新增 `TestAppendHistoryPreserve`（复用该文件既有 tmp_path + HISTORY_FILE 隔离模式）：
1. `merge_existing=True`：预置当日行 `{"date":"2026-09-04","gspc":7727.09,…}` → append `record gspc=None` → 读盘断言 gspc==7727.09（盘中值保留）。
2. `merge_existing=False`：同场景 → 断言 gspc is None（默认覆盖语义回归锁）。
3. record gspc 有值(7750.0) + True → 覆盖为 7750.0（fetch 成功时照常定稿）。
4. 无当日行 + True → 正常新建行、键值照写。

**验证**：`venv/Scripts/python -m pytest tests/test_merge_history.py -v`。

### 步骤 3：`daily_report.py` — 调用点传参

L198 `append_history(record)` → `append_history(record, merge_existing=True)`，上一行注释：`# 定稿保护：本次 fetch 缺失的美股键保留当日快照盘中值，防盘中运行整行抹空（决策 X）`。

注意：`main()` 中渲染用 history 已剔除当日行（daily_report.py:131-134），与 append 内部补全互不影响；`_is_us_duplicate_day` 判定在补全后的 record 上进行——record.gspc=盘中值 ≠ 前日收盘 → 正常 append，不误跳过。

**验证**：`venv/Scripts/python -m pytest tests/test_phase27.py tests/test_phase25.py -v`（daily 编排回归；conftest AUTO_PUSH=0 护栏已强制，无真实 commit）。

### 步骤 4：`web/app.py` — `_compute_latest` 加 `source_date`

现状（~L147-183，实施前 read 复核）：回填循环

```python
        if cur is None:
            for past in reversed(history[:-1]):
                if past.get(key) is not None:
                    cur = past[key]
                    break
```

改为捕获来源日期并随行输出：回填循环内 `src_date = past["date"]`（找到时）；循环外初始化 `src_date = None`；indices 项加 `"source_date": src_date`。`change_pct` 维持「raw 为 None 即强制 None」不动（决策 R5）。

**验证**：`venv/Scripts/python -c "…"` 或步骤 5 测试。

### 步骤 5：`tests/test_web.py` — source_date 契约

定位既有 `_compute_latest` 回填用例（末行某符号 None → 回填值 + change_pct None），断言追加 `source_date == 来源行 date`；新增：末行有值 → `source_date is None`；多日 None 链 → source_date=最近非空行日期。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v`。

### 步骤 6：`web/templates/index.html` — `renderOverview` 回填标注（最小观感）

`renderOverview(latest)` 内（~L228-242）：
- `const srcDate = it.source_date && it.source_date !== latest.date ? it.source_date : null;`
- 涨跌幅格：`srcDate` 非空 → 显示 `未收盘`（`<td class="num">未收盘</td>`，不走 fmtPct(chg) 的 "—"）；否则现状。
- value 格：`fmtNum(it.value, 2)` 后若 `srcDate` → 追加小字 `<span style="color:#8b949e;font-size:11px">（{srcDate.slice(5)}收盘）</span>`（09-03 收盘）。

名称/状态列不动。JS 语法验证按约束 #39：只对新增片段做 `node --check`（勿整段提取主脚本）。

**验证**：浏览器驱动（`tab.evaluate`/`tab.observe`，主 world 用 `tab.evaluate`，pitfalls #42）：当前 data 状态（9-04 行 US=None）下概览行应见「7747.71（09-03收盘）+ 未收盘」；构造末行有值场景（临时改 history 不可行——web 只读 data，可临时以测试断言代替 DOM 验证，或临时停 8000 服务替换 history 复刻后还原，**实施时以测试断言 + 截图二选一验收**）。

### 步骤 7：全量回归 + 文档 + journal

- `venv/Scripts/python -m pytest tests/ -v`（基线：既有 3 条失败与本次无关——`未开盘` vs `获取失败` 文案，涉及 build_statuses，不在范围）。
- `docs/architecture.md`：历史数据层补 `append_history(record, merge_existing=False)` 一句；Web API 补 `/api/latest` indices `source_date` 字段。
- 写 `tasks/2026-09-04-watchlist-name/journal.md`（目标/改动清单/验证结果/问题/下次注意）；改动可能被 auto-commit 扫入，用 `git log --oneline -3` 核对范围（约束 #40）。

## 4. 任务 C：调度核对（只核对，不改）

**现状**：Hermes 侧配置 cron（本仓库无配置表，二十六期起三入口脚本内置 auto_commit_push；commit 时间即真实运行时刻）。今日事实：21:45/22:19 两笔 `us open snapshot`（21:30 档双跑或重试）、22:32/22:38 两笔 `daily report`——22:30 档运行时刻 = 北京 22:32（美东 ET 10:32，**美股盘中**），daily_report 设计的运行时刻是美东收盘后（≈北京 04:30+，et 16:30 后）。

**核对清单（用户在 Hermes 侧执行）**：
1. 列出定时任务，确认是否存在 `22:30 前后指向 daily_report.py` 的档（当前 22:32/22:38 双跑疑似 21:30 档误配 daily 或重试）。
2. daily 档应改到 **北京 04:40-05:00（美东收盘后）**；22:30 档若意在美股开盘/盘中 → 指向 `snapshot_report.py --market us --time open`（注意 21:30 us-open 档已存在，两档重复则撤掉 22:30 档）。
3. 双跑同一类型（21:45 与 22:19 均为 us-open；22:32 与 22:38 均为 daily）→ 去重为一档，避免重复定稿/双 commit。

**建议**：在 A 修复落地前，若 daily 仍在盘中跑，会保留盘中值（不再抹空）；调度归位后该保护路径自然不再触发，仅作兜底。

## 5. 风险评估

1. **A 保留异常盘中值**：merge_existing 兜底只在 fetch 为 None 时启用，保留的是快照入口已写入的当日值；若快照取到坏值会一并保留——数据质量风险由 Yahoo/AkShare 承担，与既有 merge_history 语义一致；收盘后正常跑（fetch 有值）必覆盖，行为与现状完全相同。低风险。
2. **A 默认参数**：`merge_existing=False` 默认 → 除 daily 调用点外零行为变化（含测试直调 append_history 的存量用例）。低风险。
3. **B 契约加键**：`source_date` 向后兼容（旧前端忽略未知键）；`_compute_latest` 返回值仅 `api_latest` 消费。低风险。
4. **前端标注形态**：未收盘/（09-03收盘）文案与既有「—/未开盘」状态列可能并存——状态列来自 context 独立链路，value 列标注仅解释数值来源，不冲突。若观感重复可后续收敛（本次不扩大范围）。
5. **测试面**：web DOM 标注依赖浏览器验收；Python 契约由步骤 5 用例锁定。本环境未跑真实 uvicorn 冒烟（端口 8000 已有实例占用模板缓存，pitfalls #FastAPI 模板缓存），改动后浏览器验证须硬刷新或另起端口（如 8001）。

## 6. 影响范围（回归面）

- **日报正常路径（美股收盘后跑）**：fetch 全有值 → merge_existing 不触发 → append 行为与现状逐字节一致（回归锁=步骤 2 用例 ③）。
- **日报盘中跑（本次 bug 场景）**：美股 None → 保留快照盘中值，web 显示当日盘中而非 09-03 旧收盘（期望变化）。
- **快照/开盘入口**：不改 merge_history，盘中 merge 语义不变。
- **web /api/history /api/alerts /api/watchlist**：不涉及。
- **自选股链路**：不涉及（线上 env 修正属配置操作）。
---

## 【任务 D】单自选股图表过宽/扁扁的（只读方案，未改代码）

### 现象与根因
- 自选股卡 `#watchlist-section` 是 `.card` hairline 全宽分区（style.css:99-106，无边框透明、整行铺满），不在 `.charts-grid` 两列网格内。
- 其图表 canvas：`web/templates/index.html:109` `<canvas id="chart-watchlist" style="height:220px !important">` + style.css:215-220 `.chart-box canvas { width:100% !important; height:340px !important; }`（被内联 220 覆盖，即 commit 7101e47「调小」痕迹）。
- 结果：**高恒定 220px、宽=整卡全宽**（如容器 ~1160px → 比例 ≈5:1）。对比主趋势图区在 `.charts-grid repeat(2,1fr)`（style.css:177-181）内每图 ~半宽 + 340px 高 ≈1.6:1 协调。单只自选股只有 1 条折线，宽扁更显空旷不协调。
- 与自选股数量无关（本就单图多线），单只时观感最差。表格行同样全宽，但行高信息密度低、全宽无碍，抱怨集中在图。

### 推荐方案（最小改动，1 处 CSS）
`web/static/style.css` 在 `.chart-box canvas` 规则（L215-220）后追加：

```css
/* 自选股图：限宽居中，避免全宽 220px 过扁（单标的场景尤甚） */
#watchlist-section .chart-box { max-width: 640px; margin: 0 auto; }
```

- 图表（含其 h3/chart-meta 头）收窄至 ≤640px 居中，比例 ≈2.9:1，接近主图观感；220px 高与 7101e47 的协调意图不变。
- 移动端天然不受影响（容器 <640px 时 max-width 不生效，既有 260/220px 断点规则照旧）。
- 不改 index.html、不改 Chart.js options、不动主图区。
- 备选（不取）：把图表高度调回 340 —— 与 7101e47 意图相悖，且仍全宽仍扁；改 `maintainAspectRatio` —— 依赖 Chart 内部行为，不如 CSS 稳定。若浏览器实测 Chart.js responsive 接管高度导致非 220px，再在 `renderWatchChart` 的 options 对象（index.html ~L838 前）补 `maintainAspectRatio: false` 一行兜底——先验后补，不预埋。

### 改动前后对比
| | 前 | 后 |
|---|---|---|
| 桌面（容器 ~1160px） | 图 1160×220（≈5:1 扁条） | 图 640×220（≈2.9:1），居中，与主图观感协调 |
| 移动端（<640px） | 容器宽 ×220 | 不变 |

### 验证
1. 另起 8001 端口（8000 被占且模板/静态有缓存，pitfalls #FastAPI 模板缓存）起 `venv/Scripts/python -m uvicorn web.app:app --port 8001`，浏览器硬刷新。
2. `tab.evaluate`（主 world，pitfalls #42）量 `document.getElementById('chart-watchlist').getBoundingClientRect()` → 宽 ≈min(容器,640)、高 ≈220；截图对比改前后。
3. 视口 1280px 与 375px 各验一次（375 下应全宽无居中、高度 220 断点生效）。
4. 无 CSS/JS 单测基建 → 浏览器断言为准；本改动纯样式，Python 测试不受影响（可跳过 pytest 或跑 test_web.py 冒烟）。

### 风险
- 仅作用于 `#watchlist-section .chart-box`，其它卡（主图/板块/告警）零影响；纯 CSS 无 JS 行为变化，Chart.js responsive 不感知 max-width（重算基于实际容器宽）。低风险。
---

## 【任务 E】自选股图表分辨率低/模糊（只读分析，未改代码）

### 现象
任务 D（max-width:640 居中）上线后，自选股图在部分屏显糊/发扁。

### 根因（代码级，一行）
`renderWatchChart` 的 Chart.js 配置（`web/templates/index.html` ~L806-808 `const options = { responsive: true, … }`）**未设 `maintainAspectRatio`** → v4 默认 `true`、`aspectRatio=2`；而 canvas 高度被 CSS 钉死 `220px !important`（index.html:109 内联 + style.css:217 双重 !important）。

- Chart.js 4.4.1 responsive 在 `maintainAspectRatio:true` 下按「宽 ÷ 2」推逻辑高：容器 640px → 期望高 **320px**，canvas 物理像素 `heightAttr = 320×DPR`（DPR=1.25 时 ≈400px）。
- CSS `!important` 使 canvas 实际显示高恒为 **220px** → 320px 高的图被垂直压缩到 220px 显示（≈0.69×）→ 文字/曲线发糊发扁；宽度方向 1:1 无失真。
- DPR/高分屏维度**排除**：Chart.js v4 默认 `devicePixelRatio: window.devicePixelRatio`（实测 1.25），全文件 grep 无 `devicePixelRatio`/`Chart.defaults` 覆盖 → 横向已按 DPR 高清，不是"未开 DPR"问题。
- 主趋势图（`.charts-grid` 内半宽 + CSS 340px）同依赖默认 aspect，但半宽容器下期望高(≈280px)与 CSS 340 接近，失真轻微、用户未报；本次只改自选股图（不扩大范围，主图顺带核实即可）。

> 注：本次探测期间 `/api/watchlist` 取数暂失败，前端显示「数据暂缺」占位（canvas 被 innerHTML 替换，无法实测 heightAttr）；上述为渲染成功路径的确定性代码分析，验证步骤见下。

### 最小修复（1 行）
`web/templates/index.html` `renderWatchChart` 的 `options` 对象（`responsive: true` 之后）加：

```js
const options = {
  responsive: true,
  maintainAspectRatio: false,   // 高由 CSS 220px 决定，避免 aspect=2 画 320 高被压缩到 220 显示（糊）
  ...
```

改动前后对比：
| | 前 | 后 |
|---|---|---|
| 逻辑绘图高 | 宽÷2 = 320px | 容器实际高 ≈220px（CSS 决定） |
| canvas 物理像素 | 640×1.25 × 400px(320×1.25) | 800 × 275px（220×1.25，与显示 1:1） |
| 显示效果 | 400px 高内容压缩进 220px → 糊/扁 | 1:1 无压缩，锐利；高仍 220px（任务 D 意图不变） |

### 验证
1. 前置：确认 `/api/watchlist` 有数据（`curl http://127.0.0.1:8000/api/watchlist` 非空；若「数据暂缺」属取数临时失败，先恢复/换 8001 起服务）。
2. `tab.evaluate`（主 world）量渲染后 canvas：改前 `canvas.height / rect.height ≈ DPR×1.45`、改后 `≈ DPR`；`canvas.width / rect.width ≈ DPR`（前后不变，横向本就清晰）。
3. 截图对比锐度（改前后同一视口 1280、DPR 125%）。
4. 其它三图（renderLineChart 等）抽查 `canvas.height/rect.height`：若主图比值 >DPR×1.1 且观感糊 → 可同法补一行（另行小改，本次不含）。

### 风险
---

## 【任务 F】自选股图表数据点偏少（只读分析，未改代码）

### 实际点数（口径链）
| 层 | 位置 | 天数口径 |
|---|---|---|
| Yahoo 源（美股/ETF/A股回退） | `src/fetcher.py:515-517` `_fetch_yahoo_watch` `range="1mo"` | **自然月窗口 → 仅 ~19-22 个交易日** |
| A 股源（新浪 AkShare） | `src/fetcher.py:557-560` `_fetch_a_share_watch` `start=now-70 天` | 70 自然日 ≈ 45-50 交易日（不截） |
| 接口层截断 | `web/app.py:297-301` `_series_tail(points, n=30)`（`_build_watchlist_payload` L309 调用） | **统一截最近 30 点** |
| 前端 | `renderWatchChart`（index.html ~L712-855）dates=全部 pts 并集，无再截断 | 30（A股源）或 ~20（Yahoo 源） |

实测：`/api/watchlist` trend.series 长度——A 股源正常路径 **30**；Yahoo 源 **~20**；本次探测时段新浪/AkShare 临时失败（series 为空，前端「数据暂缺」占位），用户此前看到的应为 20-30 点区间。

对比：主趋势图 `/api/history` 默认 `days=30`（app.py:388-391 Query 默认 30），**自选股 30 点与主图基准一致**——不是相对异常；自选股不写 history.json（#31），数据每次实时拉取，与 history 90 日无关。

### 根因结论
1. **非 bug（主因）**：接口契约即「近 30 日」（fetch_watchlist docstring fetcher.py:577 + `_series_tail(30)`），与主图 30 点对齐，属设计基准。A 股源正常时给 30 点，不少。
2. **轻微口径偏差（次因，可修）**：Yahoo 源 `range="1mo"` 只含 ~20 个**交易日**（自然月窗口），A 股新浪失败回退 Yahoo 时（或美股/ETF 标的）点数比 30 少 1/3——"近 30 日"实为"近 1 月自然日"。
3. 与任务 D/E（CSS 限宽、maintainAspectRatio）无任何关系。

### 是否要调：**建议调 1 行（仅 Yahoo 窗口），非必须**
用户若认可 30 点基准可不改（与主图一致）；若要保证「30 个交易日」：

`src/fetcher.py:517`：
```python
params={"interval": "1d", "range": "1mo"}
```
→
```python
params={"interval": "1d", "range": "3mo"}   # 3mo 才含足量交易日，交给 _series_tail 截 30
```
同步改 `_fetch_yahoo_watch` docstring（L505-508「近 30 日收盘序列（range=1mo）」→ range=3mo 按最近 30 交易日截取说明）。

改动前后对比：
| 场景 | 前 | 后 |
|---|---|---|
| A 股源正常 | 30（48 截断） | 30（不变） |
| A 股回退 Yahoo / 美股 ETF | ~20 | 30（3mo≈63 交易日截 30） |

- A 股源（70 自然日≈48 交易日 >30）**无需改**；`_series_tail` 已兜底截断，内部不再加截。
- 数据量：Yahoo 单标的 63 点请求，与 SECTOR_TIMEOUT 并行限时兼容，开销可忽略。

### 验证
1. 修复后 `curl http://127.0.0.1:8000/api/watchlist` → `len(trend.series[0].values) == 30`（需新浪正常；若新浪失败则验证回退 Yahoo 路径也应 30）。
2. `tab.evaluate` 数 x 轴刻度/数据集长度 == 30；截图与主图点数视觉一致。
3. 回归：`venv/Scripts/python -m pytest tests/ -v`（涉及 fetcher 网络用例为 mock/本地，全量基线同前 3 条既有失败）。

### 风险
- 仅动 Yahoo range 参数 + docstring，纯数据源窗口扩大；前端/接口零改动。低风险。
---

## 【任务 G】非交易日显示「未开盘/未收盘」语义（只读分析，未改代码）

### 现象（2026-09-05 周六 11:09 实测）
- history.json **已存在 09-05 行**：sh/sz/cyb = 09-04 收盘值照抄（3930.11/13516.97/3286.55），美股/波动率/alt 全 None——周六 A 股入口把「最近交易日(09-04)收盘」merge 进了周六自然日行。
- context 最新（09-04）indices：GSPC/IXIC=「连涨1日」+ 值 7718.6（美股收盘已正常定稿）；但 VIX/VXN/MOVE/GLD/BTC=「未开盘」None、SH/SZ/CYB=「休市」None（context 生成时点未取到）。
- web 概览（数据截至 09-05 行）：美股回填 09-04 收盘 → 数值标「（09-04收盘）」、涨跌幅「未收盘」（index.html:240 写死）、状态列来自 context（09-04 的「未开盘」/「休市」）；A 股显示 09-04 值 +0.00% —— 用户截图所见，周末整屏「未开盘/未收盘」语义误导。

### 链路定位（文件+行号）
| 文案 | 位置 | 判定逻辑 |
|---|---|---|
| 涨跌幅「未收盘」 | `web/templates/index.html:240` | `srcDate ? "未收盘" : fmtPct(chg)` —— **写死**：只要该符号前向回填（最新行无当日数据）就显示「未收盘」，**无今日是否交易日判定** |
| 数值「（09-04收盘）」 | `index.html:239` | source_date 回填标注（任务 B 已上线），本身正确 |
| 状态「未开盘/休市」 | `src/analyzer.py:501-516` `build_statuses` | fetch 缺失/失败分支：A 股→「休市」(L514)、美股/alt→「未开盘」(L516) —— **只判取数结果，无当日是否交易日判定** |
| 状态进前端 | `web/app.py:405-418` api_latest | 从 `_load_latest_context()` 最新 context 合并（09-04 context 中 VIX 等即「未开盘」） |
| 09-05 行产生 | 周六 A 股入口（opening/snapshot）`merge_history` | 新浪返回最近交易日收盘 → 当日自然日行写入（无交易日语义） |

### 根因分类
**(a)+(b) 混合，主因 (a)**：
1. 前端 index.html:240 与后端 analyzer.py:516 都把「最新行该市场无数据」渲染成时间过程词（未开盘/未收盘），**缺「今天是否交易日（周末/节假日）」判定**——周六/周日这类「今天不开市」被说成「还没开/还没收」。
2. 叠加数据层：周六入口仍按自然日生成 09-05 行（A 股周五值照抄）→ 表头日期推到 09-05、A 股 +0.00%、美股回填 → 观感全错。非展示层问题，属入口调度/交易日语义，列独立建议。
3. 与 09-05 行同源的 context 美股状态「未开盘」是 09-04 生成时点旧值（当时 VIX 等未取到），非今日判定。

### 是否确需改：**需要**（周末每月必现，语义会误导「稍后开/今天将收盘」）；数据层 09-05 行问题同步建议

### 最小修复（3 处；前 2 处为展示核心，第 3 处独立建议）
1. **前端三态**（`web/templates/index.html` ~L233-240 renderOverview）：
```js
const isWeekend = (new Date().getDay() % 6) === 0;   // 0=周日 6=周六
...
const chgCell = srcDate ? (isWeekend ? "休市" : "未收盘") : fmtPct(chg);
```
   周六/周日 → 「休市」；周中盘中（未收盘回填）→ 保留「未收盘」。数值列（09-04收盘）标注不变。
2. **后端 build_statuses 周末判定**（`src/analyzer.py` ~L508 取数失败分支前）：
```python
# 周末（美股 TZ）直接休市，勿标"未开盘"（节假日无法全覆盖，以周末退化为准；六期 B 语义）
us_weekend = datetime.now(_EASTERN_TZ).weekday() >= 5
```
   失败分支前命中 → 美股/alt 状态 = ("休市", "周末休市。")；A 股同法用北京 TZ。既有「A 股失败→休市」误标不在此次范围（六期设计，另行评估）。节假日（如 12/25）仍会标「未开盘」——注释写明局限，可选后续接交易日历。
3. **（独立建议，非本次）非交易日不产生数据行**：三入口在「当日非交易日」时跳过 merge/不生成自然日行（周末判定同上）；否则每月 8-9 天出现周六行 + A 股 0.00% 假象。涉及 opening/snapshot/daily 三入口 + 调度，单列任务评估。

### 改动前后对比
| 场景 | 前 | 后 |
|---|---|---|
| 周六/周日 + 美股回填 | 涨跌幅「未收盘」、状态「未开盘」 | 「休市」+「（09-04收盘）」一致，无时间过程误导 |
| 周中盘中（美股未收） | 「未收盘」 | 「未收盘」（不变，语义仍准确） |
| 节假日 | 「未开盘」（局限，注释注明） | 同前，文档标注 |

### 验证
1. 周六实况：`curl http://127.0.0.1:8000/api/latest` 渲染截图断言美股行涨跌幅=「休市」、数值含（09-04收盘）。
2. `venv/Scripts/python -m pytest tests/ -v`：新增 build_statuses 周末用例（mock 时间或注入 now）；注意存量 3 条失败为「未开盘/获取失败」文案（constraint #45 相关）——若本次文案调整触碰其断言，纳入同步修正（实施前 read 相关用例确认断言面）。
3. 周中验证不可行（需真实盘中/改系统时间）→ 以单测 + 周末实测为准，风险注明。

### 风险
- 前端 isWeekend 用访问者本地时区：国内用户访问时周六判定正确；若部署跨时区访问者（罕见，看板面向国内）周末判定以本地周六为准仍可接受。
- 后端周末判定需注入现网时间（datetime.now）——现有函数已依赖 now（analyzer 内日期逻辑），保持一致；测试用 monkeypatch 隔离。
---

## 【任务 H】自选股最新数据停在 09-02（只读分析，未改代码）

### 现象与实测
- **实际最新 bar：2026-09-02**。实时探针（2026-09-05 周六）：
  - 新浪 AkShare `_fetch_a_share_watch` / Yahoo `_fetch_yahoo_watch` 对 515300.SS **两源一致**：最后 bar `('2026-09-02', 1.322)`，n=65（70 自然日窗口上限），缺 09-03/09-04 两天。
  - 表格当日 value 却是 **1.328**（≠09-02 收盘 1.322）——来自 `meta.regularMarketPrice` 实时价（fetcher.py:521-523），当日报价链路正常 → 表格显示较新、图表序列旧，观感错位。
- **对照（关键）**：新浪对沪**个股** 600000.SS 正常到 **09-04**（n=50）；对沪 **ETF 三只全停 09-02**（515300/510300/512890，均 n=65）；Yahoo 对 510300.SS 同停 09-02 → **沪 ETF 日线上游停更于 09-02，非 515300 特例、非周末/接口整体故障**。
- 东财备选源 `fund_etf_hist_em('515300')` 本环境代理不可达（ProxyError push2his.eastmoney.com），无法本地验证其 09-04 覆盖。

### 链路排除
- **无缓存**：watchlist 每次请求实时拉取——`web/app.py` `_load_watchlist` → `fetch_watchlist`（fetcher.py:575-622）无磁盘/内存 TTL，单标的线程+超时，失败仅置 errors 不落旧值。
- **失败回退**：新浪失败回退 Yahoo（fetcher.py:565-568）——本次两源同缺，回退路径不产生「旧值」，而是「同旧」。
- **与任务 F 无关**：range 1mo→3mo 未实施；即便实施也只扩窗口，Yahoo bar 本身停在 09-02（n=65 说明数据源对 ETF 已给足窗口内全部 bar，缺的是源端 09-03/09-04 记录）。

### 根因结论
**(a) 数据源侧**：新浪 AkShare（沪 ETF 日线）与 Yahoo（.SS ETF）上游对沪市 ETF 的日线序列自 2026-09-03 起停更（缺 09-03/09-04 两个交易日 bar）；当日实时价通道仍正常。非本仓库逻辑 bug、非缓存、非回退取旧。属外部数据源缺口（可能数据商对沪 ETF 日线分发变更/停更，或数日内自愈——需观察）。

### 是否需修：**本仓库不可修外部源**；给缓解/修复选项
1. **观察自愈（建议先做，零成本）**：09-07（周一）后复查新浪 bar 是否补回 09-03/09-04 或更新到 09-07；若源持续停更走选项 2。
2. **换/并东财 ETF 源（若确认永久缺）**：`_fetch_a_share_watch`（fetcher.py:553-568）对 `.SS` 且新浪末 bar 落后 ≥2 交易日时，改走 `ak.fund_etf_hist_em(symbol=code, period='daily', adjust='')`（东财 ETF 专用日线）；**前置**：需在可访问 push2his.eastmoney.com 的环境先验证其对 515300 给到 09-04（本环境代理不通，无法预验证）。
3. **（最小展示缓解，不动数据）**：图表尾部若最近 bar 与当日实时价日期相差 ≥1 交易日，在图下标注「行情源日线更新至 MM-DD」（renderWatchChart 或 trend 响应加 `as_of` 字段）——透明告知缺口，避免误读为本地故障。

### 最小修复对比（选项 2 落地形态）
| | 前 | 后 |
|---|---|---|
| 新浪 ETF bar 停更 | series 停在 09-02、value 1.328（错位） | 东财源 bar 至 09-04（待验证），series/value 一致 |
| 改动 | — | `fetcher.py` `_fetch_a_share_watch` 内：ETF 分支优先 EM 源 + 失败/无数据回退新浪；docstring 注明双源 |

### 验证
1. 复查探针（周一后）：`venv/Scripts/python -c "from src.fetcher import _fetch_a_share_watch as f; print(f('515300.SS')[1][-1])"` → 若 ≥09-07 且含 09-03/09-04 → 自愈，无需改。
2. 若走选项 2：先独立验证 EM 源 09-04 覆盖 → 改后 curl `/api/watchlist` series 尾 = 09-04+、value=bar 尾一致 → `pytest tests/ -v` 回归。
3. 选项 3（展示 as_of）：`tab.evaluate` 断言图表尾部标注文案与 09-02 一致。

### 风险
- 选项 2 引入东财源：其字段/除权口径与新浪不同（本函数 `adjust=""` 前复权一致），需对齐 close 取值与日期格式；EM 域名代理可达性在本环境未验证（当前 ProxyError），上线前必须在目标网络验证。中风险，前置验证可消。
- 选项 3 纯标注无数据风险；低。
