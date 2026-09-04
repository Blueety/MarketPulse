# 实施计划 — 自选股卡片静默隐藏修复（hidden 语义 + 超时兜底 + 失败占位）

> 日期：2026-09-04 ｜ 任务目录：`tasks/2026-09-04-watchlist-fix/`
> 来源：2026-09-04 诊断结论（实时取数抖动 1.4~10.2s 撞 SECTOR_TIMEOUT + payload 空结构双义 → 前端静默隐藏）

## 1. 任务目标

修复「自选股卡片不显示且无任何提示」：当前 `payload.stocks=[]` 一词两义（无配置应隐藏 / 有配置但取数失败应显示"数据暂缺"），加上实时取数 1.4~10.2s 抖动与前端无超时，失败被设计性静默。

三处修复：

1. **后端 hidden 语义区分**：`/api/watchlist` 响应增加 `hidden` 键——`true` = 无配置（前端整卡隐藏，F4 原样）；`false` = 有配置（前端**必显示卡片**，取数失败也显示占位）。
2. **前端超时兜底**：fetch 挂 12s 超时（`Promise.race`），超时走失败占位而非无限静默。
3. **失败占位可见**：取数失败 / 整体异常 / 超时 / 网络错 → 卡片显示「数据暂缺」行，不再因初始 `display:none` 而无痕消失。

### 验收标准

1. 无配置（`watchlist.stocks=[]` 或 config 缺失）：页面无自选股卡，与现状完全一致（零闪现）。
2. 有配置 + 取数正常：卡片显示（表格 + 图），与现状一致。
3. 有配置 + 取数整体失败（模拟 `fetch_watchlist` 抛异常 / 断网）：卡片**显示**且表格行显示「数据暂缺」，不再隐藏。
4. `GET /api/watchlist` 响应含 `hidden` 键（无配置 `true`，有配置 `false`）。
5. `pytest tests/test_web.py -v` 全绿（含更新断言 + 新增用例）；全量 `pytest tests/ -v` 无回归。

## 2. 要改的文件列表

| 文件 | 改动 | 说明 |
|---|---|---|
| `web/app.py` | 修改 | `_load_watchlist()` 重构：`load_config` 异常与 `fetch_watchlist`/payload 异常分离处理，返回结构加 `hidden` 键（仅 ~15 行） |
| `web/templates/index.html` | 修改 | DOMContentLoaded 尾部 watchlist fetch 链整段替换（hidden 判断 + 12s 超时 + 失败占位）；`renderWatchlist` 微调（空 stocks 不再自行隐藏，由调用方按 hidden 决定） |
| `tests/test_web.py` | 修改 | 4 条既有 watchlist 用例断言更新（hidden 键）+ 新增 2 条（load_config 抛 / fetch 抛的 hidden 语义） |
| `docs/architecture.md` | 修改 | Web API 段补 `/api/watchlist` payload `hidden` 语义一行 |
| `tasks/2026-09-04-watchlist-fix/journal.md` | 新增 | 完成后按 AGENTS 规范记录 |

**不改**：`src/config.py` / `src/fetcher.py` / `src/analyzer.py` / 三入口脚本 / `style.css`（复用既有 `.empty` 类）/ `requirements.txt`（零新依赖）/ 生成物目录。

## 3. 关键设计决策

### 决策 1：payload 契约 — 加 `hidden` 键，消除空结构双义

```jsonc
// 无配置（watchlist.stocks 空 / load_config 不可读）
{ "hidden": true, "stocks": [], "trend": { "dates": [], "series": [] } }
// 有配置（取数正常或整体失败，均返回此形态）
{ "hidden": false, "stocks": [ /* 失败行 value:null 或空数组 */ ], "trend": { ... } }
```

- `hidden: true` 仅两种来源：`watchlist.stocks` 为空、`load_config()` 抛异常（配置不可读视为无配置——保守隐藏，避免误报"有配置"）。两分支在 `fetch_watchlist` 之前返回。
- `hidden: false` 恒伴随有配置；即使 `fetch_watchlist` 抛异常 / payload 构建异常，也返回 `hidden:false` + 空 stocks（`log.warning` 记录）→ 前端显示占位。
- 向后兼容：同源部署前后端同批上线；旧前端忽略未知键、仍按 stocks 空自行隐藏，无破坏。

### 决策 2：前端 — 显示决策由 `hidden` 单一驱动，超时设 12s

```js
fetch("/api/watchlist").then(r => r.json())
  → hidden ? 隐藏（不闪现）: 显示卡片
  → stocks 空（hidden:false 且无行）→ tbody 写「数据暂缺（实时取数失败）」
  → renderWatchlist(data)
```

- `Promise.race` 12s 超时（12s > 服务器最坏 10.25s，实测 SECTOR_TIMEOUT=10s + 网络裕量；8s 会误杀 10s 级成功响应，故不采用诊断初稿的 8s）。
- catch（网络错 / JSON 解析错 / 超时）→ **无条件显示卡片** + 「数据暂缺」占位行。理由：正常无配置路径 API 快速返回 `hidden:true`，根本走不到 catch；走到 catch 必是异常态，异常态展示失败卡比隐藏更诚实。无配置 + 网络故障的边角场景会短暂误显失败卡——可接受（取舍注明）。
- 超时后 `Promise.race` 已 settle，迟到的成功响应不再覆盖占位（自动恢复不做，下轮刷新自愈）——取舍注明，触发概率低（12s 内服务器几乎必返回）。
- `renderWatchlist` 内 `if (!payload.stocks.length) return`（自行隐藏）删除/上移到调用处按 `hidden` 统一判断，避免两处逻辑打架。

### 决策 3：`_load_watchlist` 异常分层（config 异常 ≠ 取数异常）

`load_config` 抛 → `hidden:true`（配置不可读=视同无配置）；`fetch_watchlist` / payload 抛 → `hidden:false`（有配置取数失败）。两异常语义不同，不能用单一 `except` 合并——这是与现状（一个 try 全包 → 有配置失败被误判为无配置）的本质差异。

## 4. 实现步骤（每步可验证）

### 步骤 1：`web/app.py` — `_load_watchlist` 重构 + hidden

现状（单一 try/except，全包）：

```python
def _load_watchlist() -> dict:
    try:
        cfg = load_config()
        stocks = (cfg.get("watchlist") or {}).get("stocks") or []
        if not stocks:
            return {"stocks": [], "trend": {"dates": [], "series": []}}
        values, series, _errors = fetch_watchlist(stocks)
        return _build_watchlist_payload(stocks, values, series)
    except Exception as exc:
        log.warning("自选股取数失败，降级空结构: %s", exc)
        return {"stocks": [], "trend": {"dates": [], "series": []}}
```

改为（锚点：`def _load_watchlist` 全函数替换）：

```python
def _load_watchlist() -> dict:
    """实时取数自选股。hidden=true 仅=无配置（前端隐藏）；有配置时取数失败
    仍返回 hidden=false + 空 stocks（前端占位可见，不静默隐藏，NF3）。"""
    empty = {"stocks": [], "trend": {"dates": [], "series": []}}
    try:
        cfg = load_config()
    except Exception as exc:
        log.warning("自选股配置读取失败，视为无配置: %s", exc)
        return {"hidden": True, **empty}
    stocks = (cfg.get("watchlist") or {}).get("stocks") or []
    if not stocks:
        return {"hidden": True, **empty}
    try:
        values, series, _errors = fetch_watchlist(stocks)
        return {"hidden": False, **_build_watchlist_payload(stocks, values, series)}
    except Exception as exc:
        log.warning("自选股取数失败，降级空结构: %s", exc)
        return {"hidden": False, **empty}
```

docstring（模块头部「4 个 JSON API」说明）同步补 hidden 语义一句。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v`（配合步骤 2 测试更新）；`curl http://localhost:8000/api/watchlist` 响应含 `"hidden": false`（本机有配置）。

### 步骤 2：`tests/test_web.py` — 断言更新 + 新增

更新 4 条（锚点 `tests/test_web.py:629-690`）：

1. `test_load_watchlist_empty_config`：断言改 `out == {"hidden": True, "stocks": [], "trend": {...}}`。
2. `test_load_watchlist_partial_failure`：行断言不变，追加 `assert out["hidden"] is False`。
3. `test_load_watchlist_fetch_raises`：断言改 `hidden is False` + stocks/trend 空（语义变更：取数异常≠无配置）。
4. `test_api_watchlist_no_config_hidden_semantics`：追加 `assert r.json()["hidden"] is True`。

新增 2 条（同区追加）：

5. `test_load_watchlist_config_raises`：monkeypatch `web.app.load_config` 抛 RuntimeError → `hidden is True` + 空结构（配置不可读=无配置）。
6. `test_api_watchlist_fetch_raises_endpoint`：monkeypatch `web.app.load_config` 返回有配置 + `web.app.fetch_watchlist` 抛 → `GET /api/watchlist` 200 + `hidden is False` + `stocks == []`（NF3：不 500、不静默隐藏）。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v` 全绿。

### 步骤 3：`web/templates/index.html` — fetch 链重写 + renderWatchlist 微调

现状链（锚点 `fetch("/api/watchlist")` 至对应 `.catch` 块）整体替换为：

```js
      // 自选股实时取数：hidden=false（有配置）才显示卡片；取数失败/超时占位可见，不静默
      var wlTimer = null;
      var wlFetch = fetch("/api/watchlist").then(function (r) { return r.json(); });
      var wlTimeout = new Promise(function (_, reject) {
        wlTimer = setTimeout(function () { reject(new Error("watchlist 取数超时（12s）")); }, 12000);
      });
      Promise.race([wlFetch, wlTimeout])
        .then(function (data) {
          clearTimeout(wlTimer);
          var sec = document.getElementById("watchlist-section");
          if (!sec) return;
          if (data && data.hidden) { sec.style.display = "none"; return; }  // F4：无配置不闪现
          sec.style.display = "";
          if (!data || !data.stocks || !data.stocks.length) {
            var b = document.getElementById("watchlist-body");
            if (b) b.innerHTML = '<tr><td colspan="4" class="empty">数据暂缺（实时取数失败）</td></tr>';
            return;
          }
          renderWatchlist(data);
        })
        .catch(function (err) {
          console.error("[watchlist] fetch failed:", err);
          var sec = document.getElementById("watchlist-section");
          if (!sec) return;
          sec.style.display = "";  // 异常态：失败占位可见（网络/解析/超时）
          var b = document.getElementById("watchlist-body");
          if (b) b.innerHTML = '<tr><td colspan="4" class="empty">数据暂缺（取数失败）</td></tr>';
        });
```

`renderWatchlist` 微调（锚点：函数体首三行）：删除空 stocks 自行隐藏逻辑（调用方已按 hidden 决策），保留其余渲染不变。

**验证**：`node --check` 提取主脚本块语法（约束 #39：只验主脚本块，勿整段提取）；浏览器实测（步骤 4）。

### 步骤 4：端到端浏览器验证（四场景）

1. **无配置**（`CONFIG_PATH` 指向 `watchlist.stocks=[]` 的临时 json 起 uvicorn）：页面无自选股卡、无闪现（与现状一致）。
2. **有配置正常**：卡片显示 + 数据行 + 趋势图（fetch 1.4~5s 内完成）。
3. **有配置取数整体失败**：浏览器侧 stub——`tab.evaluate`（主 world）注入 `window.fetch = function(){ return Promise.reject(new Error("sim")); }; location.reload();` → 卡片显示「数据暂缺（取数失败）」行。
4. **API 结构**：`curl /api/watchlist` 断言 `hidden` 键两态（无配置 true / 有配置 false）。

**验证**：`tab.evaluate` 断言 `#watchlist-section` 的 `display` 与 `#watchlist-body` 文本；curl JSON 抽查。

### 步骤 5：全量回归 + 文档 + journal

- `venv/Scripts/python -m pytest tests/ -v`（基线 382+9 → 期望净增 +2）。
- `venv/Scripts/python -m uvicorn web.app:app --port 8002` 冒烟 5 端点 + 首页 200。
- `docs/architecture.md`：Web 看板 API 段补 `/api/watchlist` payload：`hidden`（无配置隐藏 / 有配置必显卡，失败占位）。
- 写 `tasks/2026-09-04-watchlist-fix/journal.md`；核对改动范围（约束 #40：改动可能被 auto-commit，用 `git log` 核对）。

**验证**：全量 pytest 输出 + `git log --oneline -3` 改动归属。

## 5. 验证命令

| # | 命令 | 阶段 | 预期 |
|---|---|---|---|
| 1 | `venv/Scripts/python -m pytest tests/test_web.py -v` | 步骤 1–2 | watchlist 用例更新 + 新增 2 条全绿 |
| 2 | `CONFIG_PATH=<空配置临时json> venv/Scripts/python -m uvicorn web.app:app --port 8002` | 步骤 4 | 无自选股卡；`curl /api/watchlist` → `hidden:true` |
| 3 | 默认启动（本机有配置）→ `curl http://localhost:8000/api/watchlist` | 步骤 4 | `hidden:false` + stocks 数据 |
| 4 | 浏览器四场景（步骤 4） | 步骤 3–4 | 卡片显示/占位行为符合验收 1–3 |
| 5 | `venv/Scripts/python -m pytest tests/ -v` | 步骤 5 | 全量无回归 |
| 6 | `git log --oneline -3` | 步骤 5 | 改动已入库、范围核对 |

注：测试全链路 monkeypatch 零联网；真实取数与超时行为仅浏览器/curl 手动验证（依赖外网，抖动 1.4~10.2s 属预期）。

## 6. 风险评估

1. **契约变更（hidden 键）**：同源前后端同批部署，无跨版本窗口；旧前端忽略未知键仍按 stocks 空隐藏——行为退化到现状（静默）但不破坏。低风险。
2. **超时阈值 12s**：实测服务器最坏 10.25s（SECTOR_TIMEOUT=10s + 网络裕量），12s 误杀概率低；若某次响应恰 >12s → 显示失败占位且**迟到响应不覆盖**（race 已 settle）——需下轮刷新恢复。取舍：不引入 abort/自动恢复复杂度；触发概率低（基于 5 次实测样本）。若后续频繁触发再上「迟到响应覆盖占位」。
3. **catch 无条件显示卡**：无配置 + 网络故障的边角场景会短暂误显「数据暂缺」卡（正常无配置路径 API 快速 200 + hidden:true，走不到 catch）。可接受：异常态展示优于静默。
4. **load_config 抛 → hidden:true**：配置文件损坏/权限错被视同无配置隐藏——保守选择，避免将"配置不可读"误报为"有配置取数失败"闪烁占位卡。日志有 warning 可查。
5. **测试面**：JS 无单测基建，超时/占位 DOM 行为靠步骤 4 浏览器验证（tab.evaluate stub fetch 覆盖 catch 分支）；Python 契约（hidden 两态 + 异常分层）由步骤 2 用例锁定。
6. **renderWatchlist 逻辑迁移**：空 stocks 隐藏逻辑从函数内上移到调用处——若遗漏调用点会导致空 stocks 直渲染空表格。已核对：`renderWatchlist(` 全文件仅 2 处（定义 1 + 调用 1）。

## 7. 影响范围

- **新增**：`/api/watchlist` payload `hidden` 键；`test_web.py` +2 条用例。
- **行为变化**：仅自选股卡——有配置时取数失败/超时/网络错 → 卡显示占位（原静默隐藏）；无配置行为不变。
- **运行面**：不变（仍实时取数零写盘；无新依赖）。
- **兼容**：payload 加键向后兼容；前端 JS 同批替换无独立版本。
