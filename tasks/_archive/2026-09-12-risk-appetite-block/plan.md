# Plan — 看板「风险偏好」子块接真数据（点亮第一个占位）

> 日期：2026-09-12 ｜ 角色：架构师 ｜ 状态：待用户确认后交执行者
> 前置背景：前端共 6 处「只有外表没有功能」的区块（见会话盘点），本任务按「先简单」原则只做 **`#risk-appetite` 风险偏好**——数据零新增取数，全部现成。

## 0. 结论先行

**做法**：`/api/latest` 响应新增 `risk_appetite` 键，由 web 后端**纯函数**从已有数据合成（VIX 状态 + MOVE 状态 + VIX 近 5 日变化三点打分），前端只做渲染。不改前端数据获取链路、不新增 API 请求、不动 `src/` 生产链路。

**选型理由**（替代方案对比）：

| 方案 | 说明 | 取舍 |
|---|---|---|
| **B 后端合成（选定）** | `web/app.py` 纯函数 `_compute_risk_appetite(indices, records)`，打分逻辑服务端单点、`test_web.py` 可锁 | 与项目惯例一致（`_compute_latest`/`_build_watchlist_payload` 同为先例：web 层纯函数 + test_web 锁定） |
| A 前端拿原始数据自己算 | app.js 内读 VIX/MOVE 值自己打分 | 业务逻辑进前端：不可单测、阈值漂移风险、与「纯逻辑在 src/、web 只渲染」分层相悖 |
| C 日报链路落盘 context 新键 | daily_report 写 `context.risk_appetite`，web 读 | 要动 Hermes 契约面（context 八键+），为一个小部件扩契约不值；且状态本就可由 classify 即时导出 |

**打分规则（V1，确定性、可解释）**——状态词表复用 `analyzer.classify_vix / classify_move`（平静/警惕/恐慌，阈值 env 可覆盖、调用时复核，单一事实来源，前端零阈值拷贝）：

```text
score = 0
VIX  : classify_vix(value) → 平静 +1 ｜ 警惕 0 ｜ 恐慌 -1
MOVE : classify_move(value) → 恐慌 -1 ｜ 其余 0     # 债市波动只在剧烈时拉低偏好，平静不给正分
VIX 5日变化（最近 6 个非空收盘首尾比，%）：≤ -5% +1 ｜ ≥ +5% -1 ｜ 其间 0

level: score ≥ +1 → "high"(风险偏好高·绿) ｜ score ≤ -1 → "low"(风险偏好低·红) ｜ 否则 "neutral"(中性·灰)
```

**响应契约**（`/api/latest` 新增键，向后兼容）：

```json
"risk_appetite": {
  "level": "high | neutral | low | null",
  "score": 2,
  "factors": [
    {"name": "VIX", "value": 14.2, "state": "平静", "impact": 1},
    {"name": "MOVE", "value": 98.1, "state": "平静", "impact": 0},
    {"name": "VIX 5日", "change_pct": -8.3, "impact": 1}
  ]
}
```

VIX 值缺失（取数失败/空库）→ `level: null`、factors 照常列出可得项——前端显示「数据暂缺」，不隐藏子块。

## 1. 任务目标

`web/templates/index.html` 的 `#risk-appetite` 子块（「市场情绪 & 资金流向」卡内）从 `data-placeholder` 静态占位（「数据未接入」）点亮为真实风险偏好仪表：主标签（高/中性/低，带色）+ 2~3 行依据小字，数据与概览表 VIX/MOVE 值同源一致。

## 2. 要改的文件列表

| 文件 | 改动 |
|---|---|
| `web/app.py` | 新增纯函数 `_compute_risk_appetite(indices, records)`（import `classify_vix/classify_move` 自 `src.analyzer`）；`api_latest` 组装响应时接入（`_last_records(7)` → `(10)`，供 5 日变化取数） |
| `web/templates/index.html` | `#risk-appetite` 移除 `data-placeholder="1"`；`.ph-body` 内改为留给渲染的目标容器（保留 `id="risk-appetite-body"`） |
| `web/static/app.js` | `PLACEHOLDERS` 注册表移除 `risk-appetite` 项；新增 `renderRiskAppetite(latest)`（level→标签/配色，factors→小字行；null/缺失→「数据暂缺」）；在 `/api/latest` 到达后的渲染链（`renderSector` 同一调用点）接入 |
| `web/static/style.css` | 新增 `.ra-label`（主标签，复用 `--green/--red/--text-muted` token）与 `.ra-factors` 小样式；**高度预算见 §4 测量点** |
| `tests/test_web.py` | 纯函数用例（平静+回落→high / 恐慌→low / VIX 缺失→null / 5 日窗口含 None / MOVE 恐慌单独拉低）+ `api_latest` 含 `risk_appetite` 键 |
| `docs`（收尾） | AGENTS.md web 行「3 个占位」→「2 个」；pitfalls 记一条（PLACEHOLDERS 注册表与 data-placeholder 双点同步） |

**零改动**：`src/*`（classify 只 import 不修改）、`daily_report.py`、前端数据获取链、`#fund-flow`/`#news`/`#market-relation` 等其余占位。

## 3. 实现步骤（每步可独立验证）

### S1 后端纯函数 + 接线
1. `_compute_risk_appetite(indices, records)`：
   - `indices` 里按 `symbol == "VIX"` / `"MOVE"` 取 `value`（就是 `_compute_latest` 产物，含前向回填值）；
   - VIX 状态：`classify_vix(value)` 首元素；MOVE 状态：`classify_move(value)` 首元素；
   - 5 日变化：`records` 中 `vix` 键最近 **6 个非 None** 收盘（保持时间序），`(末-首)/首*100`；不足 6 个 → 该因子缺省（impact 0、不计入打分）；
   - 按 §0 规则合成 level/score/factors；`value is None` → 整体 `level=None`。
2. `api_latest`：`_last_records(10)` 传给纯函数，响应加 `"risk_appetite": ...` 键（无 indices 时也返回 `level: null` 结构，恒有键）。

**验证**：`venv/Scripts/python -m pytest tests/test_web.py -v`（新增用例全绿；既有用例零改动通过——新增键向后兼容，无键集全等断言，已核实）。

### S2 前端渲染
1. `index.html`：去掉 `#risk-appetite` 的 `data-placeholder="1"`（`PLACEHOLDERS` 双点同步：app.js 注册表删同名项——**两处必须同一提交改，漏一处会出现「数据未接入」残留或空块**）。
2. `app.js`：`renderRiskAppetite(latest)`——
   - `level` 映射：high→「风险偏好高」+ pos 色、low→「风险偏好低」+ neg 色、neutral→「风险偏好中性」+ 中性色；
   - `factors` 渲染为 12px 小字行（`VIX 14.2 · 平静` / `VIX 5日 -8.3%`），impact 正负带 `pos/neg` 色；
   - `level == null` 或键缺失 → 沿用 `.ph-note` 显示「数据暂缺」（不隐藏块，防布局跳变——28 期占位经验）；
   - 调用点：`refresh()` 中 `/api/latest` 成功分支，紧跟 `renderSector(latest)` 之后。
3. `style.css`：`.ra-label`（主标签 ~15px 600）+ `.ra-factors li`（12px、muted、行距紧凑）；色值只用既有 token。

**验证**：`venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（AGENTS.md 硬规定，Playwright 三视口）；另起新端口 uvicorn 人工核对：子块显示真值、与概览表/顶部 VIX 数值一致。

### S3 全量回归 + 文档收尾
- `venv/Scripts/python -m pytest tests/ -v` 全绿；`git diff` 核对改动范围 = §2 清单；
- AGENTS.md（占位计数 3→2）、pitfalls.md（双点同步坑）。

## 4. UI 专项说明（按输出规范）

**复现路径（改动前）**：`venv/Scripts/python -m uvicorn web.app:app --port 8017` → 浏览器 `http://localhost:8017` → 行 3「市场情绪 & 资金流向」卡 → 第一个子块「风险偏好」显示灰色小字「数据未接入」（`renderPlaceholders` 写入 `.ph-note`）。

**关键测量点**（改后必须复核，防撑破卡片）：
- `#risk-appetite` 的 `offsetHeight`：改前 = `.ph-body` min-height 40px 量级；改后（label + 3 行 factors）预期 **60~80px**；
- `#sectors` 卡 `scrollHeight ≤ clientHeight`（style.css:369 注释表明该卡高度有过 scrollHeight 护栏调优——子块增高会把整卡撑高、挤压行 3 栅格，若超限则 factors 压成 2 行或去掉第三因子行）；
- `.sub-block` 间距规则 `.sub-block + .sub-block { margin-top: 8px }` 不受影响（结构未变）。

**box-sizing**：全局 `* { box-sizing: border-box }`（style.css:72）——新增元素的高度含 padding，无 content-box 撑高陷阱；只要不写固定 `height`，仅用 min-height/padding 自适应即可，风险低。

**多尺寸验收**：
- **720p 小窗**（~1280×720）：行 3 三卡并排变窄——「风险偏好」子块 label 单行不换行、factors 最多 3 行不溢出、`#sectors` 卡不因此出现纵向滚动条；
- **1080p 常规**（≥1920×1080）：label + factors 全量展示，与「市场关系」「资金流向」子块高度协调（资金流向仍是占位矮块，允许两块高度有差，卡高以最高子块为准）。

## 5. 风险评估和注意事项

1. **双点同步**：`data-placeholder`（HTML）与 `PLACEHOLDERS`（app.js）必须同一次改动摘除，否则占位文案/渲染互相覆盖——收尾记 pitfalls。
2. **`classify_*` 的 env 复核是调用时的**：web 进程 env 若设了 `STATUS_THRESHOLD_VIX_*` 会即时生效（与日报同语义，非 bug）；测试需 `monkeypatch.delenv` 隔离宿主环境（既有纪律）。
3. **VIX 值可能是前向回填值**（`source_date` 非空，如休市日）：仪表仍可显示，但属「最近收盘」语义——V1 不做特殊标注（概览表已有「（MM-DD收盘）」标注可对照），V2 可选。
4. **数据暂缺路径**：空 history / 全 None → `level=null` + factors 尽列 → 前端「数据暂缺」，不白屏不隐藏（占位→真值→暂缺三态切换都不产生布局跳变）。
5. **阈值不动 config**：±5%（5 日变化）为 web/app.py 模块级常量，V1 不入 config.json（避免为一个小部件扩配置面）；若后续要调，再议外置。
6. **`_last_records(7)→(10)`**：api_latest 现有调用点共 1 处，改窗口不影响既有断言（相邻记录自算 change 逻辑不变）。

## 6. 验证命令（引用 docs/commands.md）

| 用途 | 命令 |
|---|---|
| 单测 | `venv/Scripts/python -m pytest tests/test_web.py -v` |
| 全量 | `venv/Scripts/python -m pytest tests/ -v` |
| 手测 | `venv/Scripts/python -m uvicorn web.app:app --port 8017`（新端口防缓存）→ 浏览器看子块 |
| UI 验收（必跑） | `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` |

## 7. 预计影响的文件范围

`web/app.py`（+~45 行）、`web/templates/index.html`（±3 行）、`web/static/app.js`（+~25/-1 行）、`web/static/style.css`（+~12 行）、`tests/test_web.py`（+~60 行）、AGENTS.md / docs/pitfalls.md（收尾各 1 条）。**不动**：`src/*`、后端其他端点、其余占位区块。
