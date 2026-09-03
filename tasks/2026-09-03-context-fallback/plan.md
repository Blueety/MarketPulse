# 实施计划 — context 空壳回退（web 看板板块数据兜底）

> 日期：2026-09-03 ｜ 任务目录：`tasks/2026-09-03-context-fallback/`
> 来源：诊断结论（本次会话前置排查）——`context/2026-09-03.json` 为一次全源取数失败运行的产物（indices 全 null、`sector_heat` 空），`_load_latest_context` 按文件名严格取最末，失败空壳遮蔽了 `09-02` 的真实板块数据，前端 `renderSector` 因 `gainers` 为空显示「数据暂缺」。

## 目标

`_load_latest_context` 增加回退机制：最新 context 文件是失败运行的空数据（`sector_heat` 无数据）时，回退到最近一个 `sector_heat` 有数据的 context 文件，使 web 看板板块面板显示最近真实板块数据而非「数据暂缺」。前端、`api_latest` 其余字段、数据生产端（`generate_context`）一律不改。

## 验收标准

1. 目录存在 `2026-09-03.json`（空壳）+ `2026-09-02.json`（有板块数据）时，`_load_sector_heat()` 返回 `2026-09-02` 的 gainers/losers，而非空结构。
2. 最新文件本身有板块数据时，行为与现状完全一致（不误回退）。
3. 所有 context 均无板块数据（或键缺失 / 旧格式）→ 回退返回最新的可解析 context（状态列仍有值），板块降级空结构（现状语义下限不变）。
4. 目录缺失 / 全坏 → `None` / 空结构，容错不变。
5. 前端零改动；`/api/latest` 的 `date`/`indices` 仍来自 history.json，不受影响。
6. 既有 `tests/test_web.py` 全绿 + 新增回退用例绿。

## 现状盘点（只读结论）

- `web/app.py` 消费链：`api_latest` → `_load_latest_context()`（状态列来源）与 `_load_sector_heat()`（板块来源）；`_load_sector_heat` 内部先调 `_load_latest_context` 再取 `sector_heat` 键。
- `_load_latest_context`：`sorted(glob("*.json"))[-1]` 严格取文件名字典序最末；坏 JSON → 记 warning 返回 `None`（不回退）。
- 前端 `renderSector` 仅渲染 `sector_heat.gainers`，空 → `colspan=4`「数据暂缺」降级行；losers 不参与前端渲染。
- 实证：`09-01`/`09-02` context 的 `gainers` 均非空（可含负值，如 09-02 军工 -0.28%）⇒ **`gainers` 非空 ⇔ 该次板块取数成功**，是空壳判定的可靠标记。
- `_load_latest_context` 同时服务 `api_latest` 状态列：失败空壳日（09-03）其 indices 为占位「平静」，状态列与所显示的 09-02 数值不同源（既有行为，见风险 2）。
- 既有测试（`tests/test_web.py`）：`test_load_sector_heat_present / missing_key / no_context_dir`、`test_api_latest`、`test_endpoints_empty_data` 均为单文件或空目录夹具，回退实现（向后兼容语义下限）不会破坏其断言。

## 设计决策

### 决策 1：回退落点 —— 改 `_load_latest_context` 本身（默认采纳）

**方案 A（推荐）**：`_load_latest_context()` 语义升级为「最近有效 context」——按文件名倒序遍历：

1. 返回第一个 `sector_heat` 为 dict 且 `gainers` 非空的 context（= 最近一次板块取数成功的交易日）；
2. 若所有文件都无板块数据 → 返回倒序第一个**可解析**的 context（兼容无板块键的旧格式 context / 全空壳场景，状态列不落空）；
3. 目录缺失 / 全部坏 / 空 → `None`（现状不变）。

`_load_sector_heat()` **零改动**（仍取返回值中的 `sector_heat` 键）。改动集中在用户点名的函数，`api_latest` 状态列与板块列自动同源回退。

| | 方案 A：`_load_latest_context` 整体回退 | 方案 B：仅 `_load_sector_heat` 内回退 |
|---|---|---|
| 实现 | `_load_latest_context` 倒序遍历 + 判定；`_load_sector_heat` 不动 | `_load_latest_context` 保持「最新文件」字面语义；`_load_sector_heat` 自建倒序遍历 |
| 全源失败空壳日（今日 09-03 场景） | 板块 + 状态列都回到 09-02，与数值（09-02）完全同源 | 板块回 09-02 ✓；状态列仍为空壳占位「平静」（维持现状错配） |
| 仅板块取数失败日（indices 正常） | 状态列随回退滞后一天，与当日数值错配（罕见） | 状态列保持当日真实值 ✓，仅板块滞后 |
| diff / 语义 | 一个函数语义升级（docstring 同步），改动最小 | 需新遍历逻辑 + 保留旧函数 |
| 测试影响 | 既有测试全兼容（见盘点） | 同左 |

选定 A：与任务字面一致（回退机制落在 `_load_latest_context`），且精确修复本次观测到的全源失败场景；B 的差异仅体现在「板块单独失败日」的罕见情形，已在风险 2 记录，若后续此类日子变多再切方案 C（状态列按 history 最新日期取 context，两列各自独立取源）。

### 决策 2：空壳判定标准 —— `sector_heat.gainers` 非空

- 前端唯一渲染字段是 `gainers`；losers 空不影响渲染。
- `generate_context` 恒同时写 gainers/losers 且同源（同一 `fetch_sector_heat` 返回）⇒ 用 `gainers` 非空判定即等价于「该次板块取数成功」，且避免 losers-only 假阳性（后端返回了数据但前端仍「数据暂缺」）。
- 用 `or []` 归一化保证输出结构恒为 `{gainers: [...], losers: [...]}`。

### 决策 3：坏文件处理 —— 倒序遍历时跳过，继续向前回退

现状：最新文件坏 JSON → 整体 `None`（整个链降级）。回退遍历天然逐文件容错（记 warning、跳过），坏文件不再阻断其后更旧的有效 context。

## 涉及文件

| 文件 | 改动 | 说明 |
|---|---|---|
| `web/app.py` | 修改 | `_load_latest_context` 改为倒序遍历回退（含 `sector_heat.gainers` 非空判定 + 逐文件容错）；`_load_sector_heat` 与 `api_latest` 不动 |
| `tests/test_web.py` | 修改 | 新增回退用例 5 条（见下） |
| `docs/pitfalls.md` | 追加 | 新坑：失败空壳 context 遮蔽、`_load_latest_context` 回退语义、`gainers` 非空作有效标记 |
| `docs/architecture.md` | 追加 | web 层职责/数据流注记：板块来源回退到最近有效 context（决策记录一行） |

不改：`daily_report.py`、`snapshot_report.py`、`src/*`（数据生产端不感知）、前端 `index.html`（渲染契约不变）。

## 实施步骤

### 步骤 1：`web/app.py` 改 `_load_latest_context`

新增私有辅助 `_read_context_file(path)`（单文件解析容错：坏 JSON / 非 dict / IO 错误 → `None` + 既有 warning 文案），`_load_latest_context` 改为：

```python
def _load_latest_context() -> dict | None:
    """最近有效 context：按文件名倒序返回第一个 sector_heat 有数据（gainers 非空）的
    context；全部无板块数据 → 返回最新的可解析 context；目录缺失/全坏 → None。"""
    if not CONTEXT_DIR.exists():
        return None
    files = sorted(CONTEXT_DIR.glob("*.json"), reverse=True)
    fallback = None
    for path in files:
        ctx = _read_context_file(path)
        if ctx is None:
            continue
        if fallback is None:
            fallback = ctx                     # 语义下限：最新的可解析文件
        sh = ctx.get("sector_heat")
        if isinstance(sh, dict) and sh.get("gainers"):
            return ctx                         # 最近一次板块取数成功的交易日
    return fallback
```

`_load_sector_heat` 保持原样（对返回值取 `sector_heat`，缺失 → 空结构）。

验证：`venv/Scripts/python -c "from web.app import _load_sector_heat; print(len(_load_sector_heat()['gainers']))"` —— 在当前真实目录（09-03 空壳 + 09-02 有数据）应输出 >0（真实板块条数），修复前输出 0。

### 步骤 2：`tests/test_web.py` 新增回退用例

1. `test_load_latest_context_falls_back_from_empty_shell`：`2026-09-03.json`（sector_heat 空、indices 全 null，镜像真实空壳）+ `2026-09-02.json`（gainers 军工）→ `_load_latest_context()["date"] == "2026-09-02"` 且 `_load_sector_heat()` 的 gainers 为 09-02 数据（端到端回归本次 bug）。
2. `test_load_latest_context_prefers_newest_with_sector`：两文件都有板块数据 → 返回最新（09-03），不误回退（正常日行为不变）。
3. `test_load_latest_context_no_sector_anywhere`：所有文件无 `sector_heat` 键（旧格式）→ 返回最新的可解析 context（状态列兜底）；`_load_sector_heat()` == `{"gainers": [], "losers": []}`。
4. `test_load_latest_context_skips_corrupt_newest`：最新文件坏 JSON + 更旧文件有板块数据 → 跳过坏文件回退到旧有效 context。
5. `test_load_latest_context_all_corrupt`：全部坏 JSON → `None`（容错下限不变）。

验证：`venv/Scripts/python -m pytest tests/test_web.py -v` —— 新增 5 条 + 既有全绿。

### 步骤 3：全量回归 + 文档

验证：`venv/Scripts/python -m pytest tests/ -v` 全绿；追加 `docs/pitfalls.md`（上下文/web 小节：空壳遮蔽 + 回退语义 + gainers 标记）与 `docs/architecture.md`（web 板块数据流一行）。任务完成后按 AGENTS 规范写 `journal.md`。

## 验证命令

1. `venv/Scripts/python -m pytest tests/test_web.py -v`（步骤 2 后）
2. `venv/Scripts/python -m pytest tests/ -v`（全量回归）
3. 实况 smoke（当前仓库即复现现场）：`venv/Scripts/python -c "from web.app import _load_sector_heat; print([g['name'] for g in _load_sector_heat()['gainers']])"` —— 修复前 `[]`（空壳遮蔽），修复后为 09-02 真实大类（如军工/农业…）。
4. （可选）另起未缓存端口起服务核对 `/api/latest`：`venv/Scripts/python -m uvicorn web.app:app --port 8001`（pitfalls：8000 常被占用 + Jinja 模板缓存，须硬刷新）。

## 风险与边界

1. **板块面板时效**：失败日板块面板展示的是「最近有板块数据」的那一天（旧值），与当日指数数值并列但无日期标注——属需求本意（宁可旧数据不可「数据暂缺」）；如需标注可在前端表头加数据日期（另行决策，本期不做）。
2. **状态列回退（方案 A 伴生效应的边界）**：全源失败空壳日状态列与数值列同源一致（本次场景，改善）；但「仅板块取数失败日」状态列会随回退滞后一天（罕见）。若后续此类情况出现频率升高，切方案 C：`api_latest` 状态列改为按 history 最新日期精确取 context，板块列独立走「最近有板块数据」回退。
3. **遍历开销**：context 为 ~12KB 小文件、按交易日增长（当前 6 个），每次 `/api/latest` 最坏全量遍历可忽略。
4. 不改生产端：数据仍由 `daily_report.py` 覆盖写入同名 context，真实 09-03 数据落地后回退自然失效、无需清理。
