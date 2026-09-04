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
- **全量测试**：净增 ~6 条用例；存量 3 条失败（未开盘文案）不在范围、不动。
