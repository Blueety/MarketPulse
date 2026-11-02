# MarketPulse 十六期 Plan — 修复 19 个失败测试

> 实测命令：`venv/Scripts/python -m pytest tests/test_alerter.py tests/test_config.py tests/test_phase6a.py tests/test_phase6b.py tests/test_web.py tests/test_phase14.py tests/test_phase15.py -v`
> 结果：**19 failed, 129 passed**（阈值 8 + web 6 + phase14 3 + phase15 2）。

## 待确认决策

### D1. Phase15 `load_opening_refs` 修复方向（推荐：修 src/reporter.py，属 bug 修复）
- **现状双重损坏**：① 函数签名 `load_opening_refs()` 无参，但两处调用方（`daily_report.py:81` 与 2 个测试）都传 `date` → **TypeError**（daily_report 被 try/except 吞掉，🔔 开盘分析章节在生产中**从不渲染**——真实 bug）；② 函数体引用未定义的 `GET_MARKET_DATE`（reporter.py 从未导入/定义它）→ 即使无参调用也 **NameError**。
- **推荐**：`load_opening_refs(date: str)`——us 市场用 `date`（日报日期即美东日期），a-share 用 `get_market_date("a-share")`（从 `.analyzer` 导入，替换未定义名）。理由：匹配两处既有调用方零改动；PRD 允许"除非是 bug"修业务逻辑；函数当前 100% 不可用，修复是恢复十五期既有功能而非新增。
- 备选：函数保持无参、改 daily_report.py 与测试——NameError 仍须修（同样动 src/reporter.py），且要改 2 处调用方，diff 更大。

### D2. Phase14 超时/尺寸守卫测试处理（推荐：仅修测试，不恢复守卫）
- **现状**：a536888 用 playwright 替换 imgkit 时**删除了** 15s 限时（`_run_with_timeout`）、≤800KB 尺寸守卫与 zoom 重试；`RENDER_TIMEOUT`/`MAX_IMAGE_BYTES` 已成死常量。测试的 `_fake_playwright` 仍 mock `sys.modules["imgkit"]`，全部落空 → 测试实际驱动**真实 Chromium**。
- **推荐**：只改测试（PRD 失败分类明示"mock 不完整"，约束"不修改 src/ 业务逻辑"）：`_fake_playwright` 改 mock `playwright` + `playwright.sync_api` 双模块；timeout 测试改为 playwright 操作抛 `TimeoutError`（playwright 自带超时→异常→捕获→None 的真实路径）；size_guard 测试改为渲染输出验证（`_png_dimensions` + ≤MAX_IMAGE_BYTES）。
- 备选：在 src/image_renderer.py 回填 15s 限时 + 尺寸守卫 + zoom 重试（与架构文档一致，但超本期范围、违反 PRD 约束）。
- 无论哪种，守卫缺失与架构文档失实列为风险/后续工作（见 D5）。

### D3. Web 测试日期数据（推荐：测试改用连续工作日日期，保留周末过滤）
- **现状**：`_build_history_payload` 的周末过滤（34dc788 特意修复：多取 14 天→筛工作日→取 7）是当前行为；6 条归一化测试（fb03d8f 在过滤加入**之前**编写）用了非法日期 `2026-08-00`（strptime 抛 ValueError）与含周末的日期段（窗口漂移：`values[-1]=105.0` 应为 120.0 等）。
- **推荐**：测试数据全部改用连续工作日（`2026-08-03..07` + `2026-08-10..11` 共 7 个工作日；client fixture 用 8 个工作日 `08-03..07`+`08-10..12`），断言不变。理由：history.json 生产数据本就只有交易日，周末过滤线上无副作用，是刻意修复；动测试最小。
- 备选：删/改 web/app.py 的周末过滤——改业务逻辑，不推荐。

### D4. 阈值断言写法（推荐：引用 `DEFAULTS["alert"]`，防再次漂移）
- **现状**：src/config.py 当前默认 `move=12.0 / gspc=2.5 / ixic=3.5 / sh=2.5 / sz=3.5 / cyb=5.0`（`vix=20 / vxn=20` 未变）；测试仍断言旧值（MOVE 15.0、GSPC 4.0、IXIC 4.5、SH/SZ 4.0）。
- **推荐**：`test_alerter.py` / `test_phase6a.py` / `test_phase6b.py` 的实时阈值断言改为引用 `DEFAULTS["alert"][...]`（PRD 原则 2 原文要求）；`test_config.py` 两处（test_defaults_match_hardcoded / test_hermetic_defaults）本就是文档化默认值语义，用字面量 12.0。
- 备选：全部字面量——下次阈值变更还会再漂移。

### D5. 文档同步（推荐：pitfalls 追加 + architecture.md 一处修正）
- **现状**：`docs/architecture.md` 图片渲染行仍写 "imgkit(wkhtmltoimage) 转 PNG（…≤800KB、超时 15s、尺寸守卫 zoom 重试）"，与实际 playwright 实现不符，会误导后续 Agent。
- **推荐**：`docs/pitfalls.md` 追加 playwright 改写要点（mock 双模块落点、守卫已删、`sys.modules["playwright"]=None` 拦不住已缓存的 `playwright.sync_api`）；`architecture.md` 图片渲染行同步为 playwright 现状并标注守卫缺失。AGENTS.md 要求任务后提取规则。
- 备选：只追加 pitfalls，不动 architecture.md——最小 diff，但文档仍失实。

## 影响分析

### 分类 1：阈值变更未同步（8 个失败）
**根因**：三期/后续将阈值改入 `src/config.py` DEFAULTS（move 15→12、gspc 4→2.5、ixic 4.5→3.5、sh 4→2.5、sz 4→3.5），测试断言未同步。`an.alert_threshold` / `an.ALERT_THRESHOLDS` 均读当前配置（已核实 analyzer.py:42/122），是测试侧过期。

| 用例 | 失败断言 | 修复 |
|---|---|---|
| test_alerter.py::test_defaults | `alert_threshold("MOVE") == 15.0` | → `DEFAULTS["alert"]["move"]`（12.0） |
| test_alerter.py::test_nonpositive_env_falls_back | env MOVE=0 → 15.0 | → 同上 |
| test_config.py::test_defaults_match_hardcoded | `cfg["alert"]["move"] == 15.0` | → 字面量 `12.0` |
| test_config.py::test_hermetic_defaults | `ALERT_THRESHOLDS["MOVE"] == 15.0` | → `12.0` |
| test_phase6a.py::test_config_defaults_phase6a | GSPC 4.0 / IXIC 4.5 / SH 4.0 / SZ 4.0 | → DEFAULTS 引用（2.5 / 3.5 / 2.5 / 3.5） |
| test_phase6b.py::test_sh_triggers | `alert["threshold"] == 4.0` | → DEFAULTS["alert"]["sh"]（2.5）；数据 104.1 不动（4.1%>2.5% 触发 ✓） |
| test_phase6b.py::test_sh_exact_not_trigger | `check_breach("SH", 104.0, 100.0) is None` | 4.0%>2.5% 已触发 → 改精确边界 `check_breach("SH", 102.5, 100.0) is None`（恰好 2.5%，严格大于不触发） |
| test_phase6b.py::test_sz_independent_threshold | `check_breach("SZ", 104.0, 100.0) is None` | SZ=3.5 → 改精确边界 `103.5/100.0 is None`；104.1 触发断言保留（4.1%>3.5% ✓） |

涉及文件：tests/test_alerter.py、tests/test_config.py、tests/test_phase6a.py、tests/test_phase6b.py。不动 src/。

### 分类 2：Web API history payload（6 个失败）
**根因**：fb03d8f 新增的 6 条归一化测试用合成日期编写时，`_build_history_payload` 尚无周末过滤；34dc788 之后加入的过滤（多取 14 天→筛工作日→`[-7:]`）与非法日期 `2026-08-00`（strptime 抛 ValueError）叠加导致全部失败。具体：
- `test_build_history_payload_{normalized_base100,zero_base,single_value}`：`f"2026-08-{i:02d}" for i in range(7)` → 首日 `2026-08-00` 非法 → ValueError；且 08-01/02 为周末。
- `test_build_history_payload_null_preserved`：日期 08-24..30 含周末 08-29/30 → 窗口剩 08-24..28 → `values[-1]=105.0`（210/200）而非 120.0。
- `test_build_history_payload_change_7d_last_non_null`：同因 → change_7d=40.0 而非 50.0。
- `test_api_history`（client fixture）：08-29/30 为周末被过滤 → 窗口 08-24..28+08-31 → `vix["values"][1]=105.88` 而非 None。

**修复**（仅测试）：全部日期改为连续工作日——
- 5 条 payload 测试：`2026-08-03..07` + `2026-08-10..11`（7 个工作日，过滤后窗口仍 7 条）。
- client fixture：8 条日期改 `2026-08-03..07` + `2026-08-10..12`；注释「最后 7 条 = 08-04..08-12；08-05 的 vix 为 null，index 1」。api_latest/api_alerts 断言与日期无关（值/告警文件），不受影响。
- 断言数值全部不变（归一化语义正确）。

涉及文件：tests/test_web.py。不动 web/app.py（周末过滤为刻意修复）。

### 分类 3：Phase14 playwright mock 不完整（3 个失败）
**根因**：a536888 后 `render_report_image` 实际调用 `from playwright.sync_api import sync_playwright` 驱动真实 Chromium（`p.chromium.launch → browser.new_page → page.set_content/wait_for_timeout/query_selector_all → page.screenshot → browser.close`）；测试仍 mock `sys.modules["imgkit"]`，全部落空：
- `test_render_report_image_no_playwright`：`sys.modules["playwright"]=None` 拦不住**已缓存**的 `playwright.sync_api` 子模块（成功测试先真实导入）→ 真实渲染返回 Path 而非 None。
- `test_render_report_image_timeout`：mock 落空 + 代码已无超时机制（RENDER_TIMEOUT 死常量）→ 真实渲染成功返回 Path。
- `test_render_report_image_size_guard`：mock 落空（calls==0）+ 代码已无尺寸守卫/zoom 重试（a536888 删除）。

**修复**（仅测试，D2 决策）：
- `_fake_playwright` 重写为 mock `playwright` + `playwright.sync_api` 双模块：`sync_playwright()` 上下文管理器 → `.chromium.launch(headless=True)` → `.new_page(viewport=...)` → `set_content/wait_for_timeout/query_selector_all([])` → `screenshot(path=..., full_page=True)` 写 `png_factory()` 字节（记 calls）→ `close()`。`monkeypatch.setitem` 双模块。
- no_playwright：`sys.modules["playwright"]` 与 `sys.modules["playwright.sync_api"]` **都**置 None → import 立即 ImportError → 返回 None。
- timeout：mock `page.set_content` 抛 `TimeoutError`（playwright 自带超时→异常→外层 except→None 的真实路径）→ 断言 None。
- size_guard 更名 `test_render_report_image_png_output`：mock 产 600×800 PNG → out 存在、`ir._png_dimensions(out)==(600,800)`、`out.stat().st_size <= ir.MAX_IMAGE_BYTES`（输出契约验证）。

涉及文件：tests/test_phase14.py。不动 src/image_renderer.py（D2 决策）。

### 分类 4：Phase15 新测试（2 个失败）
**根因**：见 D1——`load_opening_refs` 双重损坏（调用传参 TypeError + 函数体未定义 `GET_MARKET_DATE` NameError）。测试按预期 API（传 date）编写，函数实现与之不符。

**修复**（bug 修复，PRD 允许）：
- `src/reporter.py`：`load_opening_refs(date: str)`；从 `.analyzer` 导入 `get_market_date`；us 用 `date`、a-share 用 `get_market_date("a-share")`；更新 docstring（保留「美股用美东日期、A 股用北京日期」语义）。
- `daily_report.py`：**无需修改**（已传 date；修复后 TypeError 消失，🔔 开盘分析章节恢复渲染）。
- `tests/test_phase15.py` TestLoadOpeningRefs：test_both_present 增加 `monkeypatch.setattr(rep, "get_market_date", lambda market: "2026-08-31")`（让 a-share 文件 `2026-08-31-a-share.md` 命中）；test_missing_returns_empty 保持（空目录 → []，签名修复后直接可用）。

涉及文件：src/reporter.py（bug 修复）、tests/test_phase15.py。

## 修改清单

| 文件 | 修改内容 |
|---|---|
| tests/test_alerter.py | 顶部加 `from src.config import DEFAULTS`；test_defaults / test_nonpositive_env_falls_back 的 `15.0` → `DEFAULTS["alert"]["move"]` |
| tests/test_config.py | test_defaults_match_hardcoded：`cfg["alert"]["move"] == 15.0` → `12.0`；test_hermetic_defaults：`ALERT_THRESHOLDS["MOVE"] == 15.0` → `12.0` |
| tests/test_phase6a.py | test_config_defaults_phase6a：4 个断言改 `DEFAULTS["alert"]["gspc"/"ixic"/"sh"/"sz"]`（加 import）；CYB 5.0、streak_days 3 不动 |
| tests/test_phase6b.py | test_sh_triggers：`pytest.approx(4.0)` → `pytest.approx(DEFAULTS["alert"]["sh"])`；test_sh_exact_not_trigger：104.0→102.5；test_sz_independent_threshold：104.0→103.5（加 import DEFAULTS） |
| tests/test_web.py | client fixture 8 条日期 → 08-03..07+08-10..12，更新注释；5 条 payload 测试日期 → 08-03..07+08-10..11；断言不变 |
| tests/test_phase14.py | `_fake_playwright` 重写（mock playwright/playwright.sync_api 双模块 + 调用链）；no_playwright 双 None；timeout 抛 TimeoutError；size_guard 更名 png_output 改输出验证 |
| src/reporter.py | `load_opening_refs(date)` 修复：导入 get_market_date、us=date / a-share=get_market_date("a-share")、docstring（bug 修复，D1） |
| tests/test_phase15.py | test_both_present 加 `monkeypatch.setattr(rep, "get_market_date", ...)` |
| docs/pitfalls.md | 追加 playwright 改写要点（D5） |
| docs/architecture.md | 图片渲染行同步 playwright 现状 + 标注守卫缺失（D5） |

不改：src/config.py、src/image_renderer.py、web/app.py、daily_report.py、opening_analyzer.py。

## 执行步骤

1. 改 4 个阈值测试文件（test_alerter / test_config / test_phase6a / test_phase6b），阈值断言对齐 DEFAULTS。
2. 改 tests/test_web.py 6 处日期数据（连续工作日）。
3. 改 tests/test_phase14.py（_fake_playwright 重写 + 3 个用例）。
4. 修 src/reporter.py `load_opening_refs(date)`（bug）+ 改 tests/test_phase15.py 两处。
5. 运行子集验证：`venv/Scripts/python -m pytest tests/test_alerter.py tests/test_config.py tests/test_phase6a.py tests/test_phase6b.py tests/test_web.py tests/test_phase14.py tests/test_phase15.py -v` → 0 failed。
6. 全量回归：`venv/Scripts/python -m pytest tests/ -q` → 0 failed。
7. 冒烟验证 phase15 修复：`venv/Scripts/python -c "from src.reporter import load_opening_refs; print(load_opening_refs('2026-08-31'))"` → 无 TypeError/NameError（返回 [] 或 refs）。
8. `git diff` 检查改动范围；更新 docs（D5）；写 journal.md。

## 验证方法

- 指定子集 + 全量 pytest 双跑全绿（0 failed），且各文件独立运行通过（PRD 要求）。
- `load_opening_refs` 冒烟命令无异常（确认 daily_report.py 生产路径不再被 TypeError 吞掉 🔔 开盘分析章节）。
- 周末过滤保持：`test_api_history` 断言 vix index1 None 通过即证明窗口=最近 7 个工作日。
- 阈值语义保持：test_sh/sz_exact_not_trigger 用「恰好等于阈值不触发」边界值验证严格大于语义。
- 风险记录：尺寸守卫/15s 限时已删（a536888）与架构文档不符 → 本期不恢复，建议后续任务回填或改文档；发现 `src/config.py` ENV_MAP 缺 `ALERT_THRESHOLD_SZ`（SZ 阈值无法 env 覆盖，与「ALERT_THRESHOLD_<SYM> 覆盖」文档不符）→ 列后续工作，不在本期修。
