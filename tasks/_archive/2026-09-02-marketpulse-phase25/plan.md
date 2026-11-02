# MarketPulse 二十五期 Plan — 美股去重 + 浅色皮肤

> 架构分析产物。未修改任何源码。依据：`prd.md` + `docs/architecture.md` + `docs/pitfalls.md` + 现状源码/数据核对。

## 问题 1 实测核对（决定性证据）

`data/history.json` 末 6 行实测（关键键）：

| date | gspc | ixic | sh | vix | move | btc |
|---|---|---|---|---|---|---|
| 08-28 | None（取数失败） | None | 3952.179 | None | None | 77830.29 |
| 08-29 | 7711.76 | 26402.424 | 3952.179 | 14.43 | 70.965 | None |
| 08-30 | 7711.76 | 26402.424 | 3952.179 | 14.43 | 70.9655 | 77615.61 |
| 08-31 | 7686.14 | 26370.889 | 3986.298 | 14.92 | 75.3193 | 78567.58 |
| 09-01 | 7686.14 | 26370.889 | 3987.559 | 14.92 | 75.319 | 78738.44 |

三条结论直接决定方案形态：

1. **「美股重复」特指 GSPC/IXIC**：08-30 与 08-29 的 gspc/ixic 全同、09-01 与 08-31 全同（vix/vxn 亦同）。
2. **整条记录几乎从不全同**：08-30 有 gld 408.89 / btc 77615.61（08-29 为 None 失败，属恢复日实值）；09-01 有 A 股三指数 + btc 实值变化。→ 若按「全 10 键相等才跳过」判定，两个问题日**都不会被跳过**，方案失效。
3. **MOVE 有浮点级抖动**（70.965 → 70.9655，+0.0007%）：判定符号集若含 MOVE，08-30 不会触发跳过，方案失效。

→ 判定符号集必须取 **GSPC + IXIC**（可扩展 VIX/VXN，见 D1），排除 MOVE。

另确认：history 唯一写入点是 `daily_report.py:179` 的 `append_history(record)`（analyzer 内部按 date 覆盖、90 天滚动、原子写；snapshot/backtest 只读；scripts/ 无其他写入者）→ 单点加门即可，零后端变更。

## 待确认决策

| # | 决策 | 推荐 | 备选 | 理由 |
|---|---|---|---|---|
| D1 | 去重判定符号集 | **GSPC+IXIC** | ①全 10 键 ②gspc+ixic+vix+vxn ③含 move | 全键方案永不触发（证据 2）；含 move 被浮点抖动破坏（证据 3）；+vix/vxn 与纯 gspc+ixic 在观测数据上行为全同（非交易日 vix/vxn 必然同值），仅理论上更稳，可按需一行扩展。「美股」= 两个美股大盘指数，与 PRD 示例（gspc）一致 |
| D2 | 混合日（美股未交易但 A 股/BTC/GLD 变动，如 09-01）| **整条跳过（PRD 字面）** | ①全键比较（几乎永不触发，方案失效，证据 2）②未变市场字段置 None（趋势图周末/节假日断点：报告 matplotlib 图、web 图、backtest 全受影响，违反「零后端变更」，且与 A 股节假日当前平值连线行为不一致）| PRD「如果今天的美股数据与昨天相同,则不写入新记录」是显式指令，09-01 是 PRD 点名的问题日。取舍：该日 A 股收盘（sh 3987.559 / sz 13933.107 / cyb 3407.037）**不写入 history**（当日日报/context 仍完整含该日数据，仅历史序列缺此日，下一交易日 A 股涨跌幅跨日计算）——此为 PRD 明确取舍，需人确认 |
| D3 | 浅色主题落地 | **`:root.light` 变量覆盖 + `html.light` class + localStorage `mp-theme`**；另加 1 行 `:root.light .card { background: var(--bg-elevated); }` 兑现「卡片 #ffffff」 | `data-theme` 属性选择器 | PRD 字面指定 `:root.light`；仅颜色变量覆盖、涨跌色（--green/--red/--blue/--orange）不变；按钮放 topbar 右上（PRD：右上角） |
| D4 | 测试 vs PRD「零测试变更」 | **既有测试零改动；新增 2 纯逻辑 + 2 接线用例**（test_phase24.py） | 不加测试 | PRD「零测试变更」= 既有断言无需改；新契约（跳过历史）无覆盖则 AGENTS.md「必须实际运行验证」不成立。改动仅 daily_report.py + 测试，不碰 src/ |

## 影响分析

### 功能 1：美股去重（daily_report.py，~10 行）

新增模块级纯函数（可单测）：

```python
_US_GATE = ("gspc", "ixic")   # D1：判定符号集（小写键）

def _is_us_duplicate_day(history: list[dict], record: dict) -> bool:
    """美股（GSPC/IXIC）与最近历史记录全同 → True（非交易日重复，跳过写历史）。

    排除 MOVE（浮点抖动 70.965→70.9655 会误判）；其余键（A 股/另类）变动不阻止
    跳过（D2：混合日整条跳过，PRD 字面）。history 为空（首跑）→ False。
    """
    if not history:
        return False
    prev = history[-1]
    return all(prev.get(k) == record.get(k) for k in _US_GATE)
```

`main()` 中 `append_history` 前加门：

```python
    record = {"date": date, **{k.lower(): values[k] for k in SYMBOLS}}
    if _is_us_duplicate_day(history, record):
        log.info("美股数据与最近记录相同（非交易日），跳过历史追加: %s", date)
    else:
        append_history(record)
        log.info("历史已追加: %s", record)
```

边界行为（写进单测）：

- history 为空 / prev 无 gspc 键 → False（首跑必写）。
- prev gspc=None（取数失败）且当日有值 → False（恢复日必写）；两者皆 None → True（连续失败日无信息，跳过合理）。
- 同日重复运行：第二跑 prev 即当日记录、值全同 → True（跳过 = 与既有按 date 覆盖等价）。
- **真正平盘日**（美股真的收平）会被跳过 → 下一交易日涨跌幅跨日计算；与周末跳过同语义，接受（D1 备注）。
- `save_last_values` 保持无条件更新（跳过日值全同，缓存内容不变，仅日期前进；对次日基准零影响）——PRD ~10 行范围，不动。

### 功能 2：浅色皮肤

**web/static/style.css（~35 行）**

- `:root` 之后追加 `:root.light` 变量覆盖（深色值保持原样不动）：

```css
/* 浅色皮肤（html.light）：仅颜色变量覆盖，涨跌色不变 */
:root.light {
  --bg-primary: #f5f5f5;
  --bg-elevated: #ffffff;
  --bg-hover: #f2f2f2;
  --border: #e0e0e0;
  --text-primary: #1a1a1a;
  --text-secondary: #4a525c;
  --text-muted: #8b949e;
}
:root.light .card { background: var(--bg-elevated); }
```

- 按钮 + 右上分组样式（复用 range-bar 按钮的透明/边框/hover 范式）：

```css
.topbar-right { display: flex; align-items: center; gap: 10px; }
.theme-toggle {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: 5px;
  font-size: 13px;
  line-height: 1;
  padding: 5px 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.theme-toggle:hover { color: var(--text-primary); border-color: var(--blue); }
```

- 检查过全部硬编码色：dot-gray #6e7681、badge.alert #fff / badge.warn #000、range-bar/group-bar active #fff、Chart.js labels #8b949e / pointBorderColor #fff 在浅色下均可读或属点装饰，无需改。

**web/templates/index.html（~20 行）**

- `<head>` 最前加主题预应用脚本（防刷新闪烁 FOUC）：

```html
<script>
  (function () {
    try {
      if (localStorage.getItem("mp-theme") === "light") {
        document.documentElement.classList.add("light");
      }
    } catch (e) {}
  })();
</script>
```

- topbar 右上分组 + 按钮（PRD 指定 🌙/☀️ 图标；默认深色 → 显示 ☀️ 表示可切浅色）：

```html
<header class="topbar">
  <h1>MarketPulse 市场看板</h1>
  <div class="topbar-right">
    <span class="subdate" id="overview-date"></span>
    <button type="button" id="theme-toggle" class="theme-toggle" title="切换深色/浅色主题">☀️</button>
  </div>
</header>
```

- 主 `<script>` 加 `setTheme(light)`（切 class + 写 localStorage + 更新图标），DOMContentLoaded 里绑 click + 初始化图标。

**web/app.py 零改动**：/static 与模板机制原样服务新 CSS/HTML；主题纯前端。

### 测试（tests/test_phase24.py 追加，既有零改动）

| 用例 | 断言 |
|---|---|
| `_is_us_duplicate_day` 纯逻辑 ×4 | 同 gspc/ixic → True；gspc 变 → False；空 history → False；仅 btc 变（混合日）→ True |
| 接线·跳过 | seed 昨日记（同 gspc/ixic、btc 不同）→ `dr.main()`（monkeypatch get_us_eastern_date + fetch_all + 既有 _monkeypatch_net）→ `load_history()` 仍 1 条、退出码 0 |
| 接线·写入 | fetch gspc 变 → `load_history()` 2 条 |

monkeypatch 落点纪律：全部打在 `daily_report` 模块（dr.get_us_eastern_date / dr.fetch_all / dr.save_report），路径常量沿用 `_monkeypatch_net`（an.HISTORY_FILE → tmp）。

### 文档同步

- `docs/architecture.md`：关键决策表加 2 行（二十五期：美股去重判定符号集 + 混合日整条跳过；浅色主题落地）；web 看板职责行提主题切换。
- `docs/pitfalls.md`：新增易错点——判定符号集必须排除 MOVE（浮点抖动）、全键比较永不触发、混合日 A 股数据不写 history 为 PRD 取舍、真正平盘日误跳；web 主题——FOUC 预应用、localStorage 校验、uvicorn 模板缓存/换端口、`tab.evaluate` 断言。
- `docs/commands.md`：验证要点 + 测试计数。

## 修改清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `daily_report.py` | 修改 | `_US_GATE` + `_is_us_duplicate_day()` + main() 加门（~10 行） |
| `web/static/style.css` | 修改 | `:root.light` 变量块 + `.card` 白底 + `.topbar-right`/`.theme-toggle`（~35 行） |
| `web/templates/index.html` | 修改 | head 预应用脚本 + topbar 分组按钮 + setTheme/绑定（~20 行） |
| `tests/test_phase24.py` | 修改（追加） | 纯逻辑 ×4 + 接线 ×2（既有断言零改动） |
| `docs/architecture.md` | 修改 | 关键决策表 + web 职责 |
| `docs/pitfalls.md` | 修改 | 去重 + 主题易错点 |
| `docs/commands.md` | 修改 | 验证要点 |

## 执行步骤

1. **daily_report.py**：加 `_US_GATE` + `_is_us_duplicate_day` + main() 门 → 验证：`venv/Scripts/python -m pytest tests/test_phase24.py -v` 新增用例绿。
2. **style.css**：`:root.light` + 按钮样式 → **index.html**：预应用脚本 + 按钮 + setTheme → 验证：`venv/Scripts/python -m pytest tests/test_web.py -v` 既有用例全绿（app.py 未动）。
3. **Web 闭环**：`venv/Scripts/python -m uvicorn web.app:app --port 8001`（新端口防 8000 占用 + 模板缓存）→ browser 打开 → `tab.evaluate` 断言：按钮存在；初始 body 背景 `rgb(11,14,20)`（深色）；点击 → `html.light` + `localStorage["mp-theme"]=="light"` + body 背景 `rgb(245,245,245)`；刷新 → 主题保持；再点 → 恢复深色。
4. **全量验证**：`venv/Scripts/python -m pytest tests/ -v` 全绿。
5. **闭环冒烟（可选，值可能已漂移）**：`venv/Scripts/python daily_report.py`——若 Yahoo 仍返回 7686.14/26370.889，日志出现「跳过历史追加」且 history 不新增 9-01 重复行；若值已变则正常按 date 覆盖（两种情况均验证退出码 0、不崩）。
6. **文档**：architecture / pitfalls / commands 同步；`git diff` 检查改动范围。
7. **收尾**：`tasks/2026-09-02-marketpulse-phase25/journal.md`（目标/改动/验证/风险/下次注意）。

## 验证方法

- **单测**：`venv/Scripts/python -m pytest tests/test_phase24.py tests/test_web.py -v` → 全量 `venv/Scripts/python -m pytest tests/ -v`（既有 ~240+ passed 零回归）。
- **Web**：uvicorn :8001 + browser `tab.evaluate` 断言（类名/localStorage/computed background-color 三态 + 刷新持久化）；截图留档（本机视觉模型不可用则以 computed style 断言为准，见 pitfalls 二十三期）。
- **去重**：接线测试为确定性验证；真实运行冒烟为可选项。

## 已知限制（验收口径）

- **history 已有重复行不清理**（08-30 等已在库）：90 天滚动自然淘汰；PRD 未要求迁移（~10 行范围）。
- **日报自身在非交易日的 0% 显示不变**：日报涨跌幅来自 `last_values` 缓存（非 history），非交易日值全同 → 0% 是事实正确；PRD 修复目标为 history 驱动的 web 看板涨跌幅（相邻记录自算），看板最新行不再出现因重复导致的 0%。
- **混合日（D2）A 股/BTC/GLD 当日数据不写 history**（09-01 类）：PRD 明示取舍，日报/context 当日仍完整。
- **真正平盘日会被跳过**：与周末跳过同语义（D1 备注）。

## 不做什么

- 不动 `src/` 任何模块（零后端变更）、`web/app.py`、`snapshot_report.py`、`scripts/`、`config.json`、`.env`。
- 不引入交易日历依赖、不做字段级 None 化、不迁移已有历史。
- 不改日报/context 在非交易日的生成行为（仍每日产出，Hermes 流程不变）。
- 不改动深色主题既有样式（`:root` 原值保持）。

## 预估 diff 范围

- 新增文件：无（journal.md 为任务记录）
- 修改文件：`daily_report.py`（+10）/ `web/static/style.css`（+35）/ `web/templates/index.html`（+20）/ `tests/test_phase24.py`（+40）/ 3 份 docs（+40）
- 删除文件：无

## 确认

- [ ] 人已审阅计划
- [ ] D1 判定符号集 = GSPC+IXIC（或指定扩展）
- [ ] D2 混合日整条跳过（接受 A 股当日数据不写 history）
- [ ] D3 浅色主题 = `:root.light` + html.light + localStorage
- [ ] D4 新增 6 条测试用例（既有零改动）
- [ ] 没有引入不必要依赖
