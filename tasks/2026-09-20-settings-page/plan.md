# 方案：设置页（阈值 / 自选的看板化管理）

> **任务档**：`tasks/2026-09-20-settings-page/`
> **P1 第 2 个**（P0 四项闭环；P1-1 回测 UI **执行中**）
> **角色**：Phase 3 Step 3.3 架构师（只读分析 + 方案，**不含完整实现代码**，不改任何项目文件）
> 实测条件：2026-09-20 20:5x，本机。
>
> ⚠️ 本文档作者是架构师，**不直接改项目代码**。
> 🔴 **前置硬约束：必须等 P1-1（回测 UI）执行完成后再开工**（§7 R3：两任务同时改
> `_sidebar.html` / `verify_ui.py` / `style.css`，并发必踩）。
>
> **状态（2026-09-20 21:1x）：定稿，可交付执行者实施。** §10 三项已裁定
> （**D-1=A / D-2=A / D-3=A**，用户原话「都按你的推荐来」）。
> **开工检查单（执行者第一件事）**：① 确认 P1-1 的 journal.md 已存在（否则等待）；
> ② 以 P1-1 后的 `navCount=12` 为基线改 `navDisabled`；③ `verify_ui.py` 的 `BT-*` 组已存在，
> 本任务新增 `ST-*` 组**不得改动** `BT-*`。

---

## 0. 结论先行

1. **用户已拍板的两个边界**（2026-09-20 20:5x）：
   ① **web 层首次获得"有限写"权限**（写 `config.json`）——打破「web 进程绝不写」的既有原则，范围仅限白名单键；
   ② **MVP = 本地看板的设置页**（本地生效）。线上（Railway）**只读展示**——`config.json` 不入库且
   Railway 是临时文件系统，线上写入重启即丢；线上持久化（迁 db）是独立任务，本轮不做。
2. 🔴 **头号设计问题不是"写文件"，是"写了也不生效"**：`src/analyzer.py` 的告警/状态阈值全部是
   **import 时快照**（`ALERT_THRESHOLDS` / `ALERT_DYNAMIC` / `ALERT_LOOKBACK_DAYS` / `ALERT_K_FACTOR` /
   `VIX_CALM` 等 **8 组常量**，analyzer.py:43-63，注释自述"import 时快照"）。`load_config()` 本身无缓存
   （每次调用都读文件），但**这些快照不会跟着变**。
   ⇒ 设置页如果只写文件，用户会看到「已保存」但**告警与回测行为纹丝不动**——**功能价值归零，且骗人**。
3. **解法（本方案的核心）**：新增 `analyzer.reload_config_snapshots()`（重建全部 8 组快照），
   web 的写入端点在**写盘成功后调用它**。三个 cron 入口（daily/snapshot/opening）**无需处理**——
   它们每次运行都是新进程，import 时自然拿到新 config。
4. 🔴 **第二个产品级发现：改"固定阈值"在动态模式下几乎无效**。实测回测报告里 7 个标的的
   阈值模式分布全是 `dynamic N / fixed 0` —— 动态模式（默认开）覆盖了 100% 的触发判定，
   `alert.vix` 等固定阈值**只在样本不足/零方差/关闭动态时回退生效**。
   ⇒ 设置页必须把 **`alert.dynamic`（开关）/ `lookback_days` / `k_factor`** 作为**一等公民**，
   固定阈值要如实标注「仅作动态模式的回退基准 + env 覆盖时的实际生效值」。
   **不这样设计 = 用户改了半天、改了个寂寞。**
5. **联动红利**：设置页（改阈值 → reload）+ 回测 UI（实时算、不缓存）⇒ **改完立刻能在 `/backtest`
   看到历史表现的变化**。两个任务拼起来才是完整的调优工作流。这也是本任务排在回测 UI 之后的理由。

---

## 1. 任务目标

**Goal**：在看板上提供「阈值 / 自选」的可视化管理，**改完即生效**（本地），替代手改 `config.json`。

验收标准：

1. 新页面 `/settings`（侧栏「设置」占位转正）可编辑：各标的告警阈值、动态阈值三参数、
   VIX/MOVE 状态区间、自选列表（增删改 `symbol`/`label`）
2. 保存后：**web 进程内的告警与回测行为立即变化**（reload 生效）——可用 `/backtest` 数值变化实证
3. 白名单外的键**拒绝写入**（保持 `src/config.py` 白名单校验的完整性）
4. 写入原子（tmp+rename）且**写前备份**；写坏不影响启动（`load_config` 本有容错，但备份是第一道防线）
5. Railway 上：页面**只读展示** + POST 返回 403；本地不受影响
6. env 覆盖关系在页面上**如实展示**（`ALERT_THRESHOLD_<SYM>` env 存在时，标注"被 env 覆盖，UI 修改不生效"）
7. `pytest` 无新增失败；`verify_ui` 全绿（`navDisabled` 1→0 三处断言同步 + `ST-*` 组）

---

## 2. 实测取证（Step 0，已完成）

### 2.1 🔴 快照常量盘点（`src/analyzer.py`，import 时求值）

| 常量 | 来源键 | 消费点 |
|---|---|---|
| `VIX_CALM` / `VIX_WARN` | `analysis.vix.peaceful / panic` | `classify_vix`（状态显示） |
| `MOVE_CALM` / `MOVE_WARN` | `analysis.move.normal / tight` | `classify_move` |
| `ALERT_THRESHOLDS` | `alert.<sym>`（7 标的） | `alert_threshold` → `check_breach` |
| `ALERT_DYNAMIC` / `ALERT_LOOKBACK_DAYS` / `ALERT_K_FACTOR` | `alert.dynamic / lookback_days / k_factor` | `dynamic_alert_threshold` |
| `STREAK_DAYS` | `trend.streak_days` | 连涨/连跌统计 |
| `HISTORY_MAX` | `history.retention_days` | 三十一期已 deprecated（保留防引用断裂）——**不进 UI** |

### 2.2 动态模式覆盖率的实证

回测报告（今日实跑）：7 个标的的「阈值模式分布」**全部是 `dynamic N / fixed 0`**。
⇒ 固定阈值在动态模式下是**死配置**（仅回退用）。设置页若不突出动态三参数，就是无效功能。

### 2.3 其它事实

| 项 | 实测 |
|---|---|
| `load_config()` | **无缓存**（src/config.py:172，每次调用读文件）⇒ 读侧天然新鲜 |
| env 覆盖 | `ALERT_THRESHOLD_<SYM>` env > config（`analyzer.py:177`）⇒ env 存在时 UI 改 config **无效**，须展示 |
| 白名单 | `src/config.py` 有键白名单校验（DEFAULTS 结构 + 合并逻辑）⇒ 写入端必须同构 |
| Railway 检测 | 仓库内**无** RAILWAY env 惯例（grep 零命中）⇒ 新增 `RAILWAY_ENVIRONMENT` 检测（Railway 官方注入） |
| 鉴权 | Basic Auth 中间件覆盖**全部路由**（P0-1 产物）⇒ POST 天然在鉴权之后，无需新增 |
| 「设置」占位 | `_sidebar.html:29` `.nav-item.is-disabled`（**唯一** disabled 项）；`verify_ui` 断言 `navDisabled == 1` 三处 |
| 并发 | **P1-1 正在改** `_sidebar.html`（+「阈值回测」项）、`verify_ui.py`（navCount→12）、`style.css`（`.bt-*`） |

---

## 3. 方案设计

### 3.1 可写键的白名单（写权限的最小面）

| 组 | 键 | 校验规则 |
|---|---|---|
| 告警阈值 | `alert.vix / vxn / move / gspc / ixic / sh / sz / cyb` | 数字 > 0 |
| 动态参数 | `alert.dynamic`（bool）/ `alert.lookback_days`（int ≥ 5）/ `alert.k_factor`（float > 0） | 一等公民，UI 置顶 |
| 状态区间 | `analysis.vix.peaceful / panic`、`analysis.move.normal / tight` | 数字 > 0 且 peaceful < panic、normal < tight |
| 自选列表 | `watchlist.stocks[]`（`symbol` 非空 + `label` 非空，≤ 30 条）、`watchlist.corr_high_threshold`（0~1） | 去重 by symbol |

**不给 UI**（明确排除）：`trend.chart_days` / `history.retention_days`（系统级，误改伤数据链）/
`watchlist` 之外的一切未知键（`src/config.py` 白名单校验兜底拒绝）。

### 3.2 快照失效：`analyzer.reload_config_snapshots()`

```
# analyzer.py 新增（伪代码）
def reload_config_snapshots() -> None:
    """重建全部 import 时快照（设置页写盘后调用；cron 入口无需调用——每次新进程）。"""
    global VIX_CALM, VIX_WARN, MOVE_CALM, MOVE_WARN, ALERT_THRESHOLDS, \
           ALERT_DYNAMIC, ALERT_LOOKBACK_DAYS, ALERT_K_FACTOR, STREAK_DAYS
    cfg = load_config()
    ...逐项重建（与 import 段的求值表达式**逐字同源**）...
```

**三条纪律**：
1. 重建表达式与 import 段**必须同源** —— 更好的做法是**把 import 段改为调用该函数**（import 时调一次），
   求值逻辑就**只有一份**（消灭"两处表达式漂移"的可能）。⚠️ 推荐后者。
2. reload 失败（config 损坏）⇒ **保持旧快照不动** + 记日志（快照是内存态，坏 config 在下次进程启动时
   会被 `load_config` 的容错兜底；内存态宁可保守）。
3. `HISTORY_MAX` **不重建**（deprecated，动了会误导）。

### 3.3 API

```
GET  /api/settings
  → { readonly: bool, readonly_reason: str|None,
      values: {…当前生效值（config 与 env 合并后的结果）…},
      env_overrides: {key: true,…},   # 哪些键被 env 覆盖（UI 标注"改了也没用"）
      schema: {…白名单与校验规则（前端渲染用）…} }

POST /api/settings      body = { "<path>": value, … }（部分更新）
  → 校验（白名单 + 规则）→ 备份 → 原子写 → reload_config_snapshots()
  → 200 { saved: true, values: … }
  → 400 校验失败（逐键错误信息）；403 readonly（Railway）；500 写盘失败（不 reload）
```

- **只读判定**：`bool(os.environ.get("RAILWAY_ENVIRONMENT"))` ⇒ Railway 上 GET 正常、POST 403。
  fail 方向：**只有明确检测到 Railway 才只读**（本地误判成只读会让功能完全不可用；反向误判只是多了一次写本地文件的机会）。
- 备份：`config.json.bak-<YYYYMMDD-HHMMSS>`，**保留最近 5 份**（滚动清理更旧的）。
- 原子写：tmp + `os.replace`（`analyzer` 既有范式）。
- ⚠️ **写入必须保持 `config.json` 里用户既有的其它键不动**：读原文件 → 深合并白名单内的改动 → 写回。
  **不得**用 `load_config()` 的返回值写回（那是三级合并后的结果，会把内置默认固化进用户文件）。

### 3.4 前端

- `_sidebar.html`：「设置」占位 → 真链接 `/settings`（`active_page="settings"`）
- 页面：① 动态阈值卡（开关 + 两参数，**置顶**，附一句"当前触发判定 100% 走动态模式"的实测事实）
  ② 各标的阈值表（标注"回退基准"+ env 覆盖状态）③ 状态区间 ④ 自选表格（增删改行）
  ⑤ 保存按钮 → POST → 成功提示"已生效（含看板内告警与回测计算）"
- 失败条/骨架：照 `#home-fail-bar` 模式（同构复制，不抽共享）
- ⚠️ 本页是**第 6 份 shell 副本**（P1-1 造了第 5 份）——继续沿用"复制+记录"决策，**在 journal 里累计计数**。

---

## 4. 涉及文件清单

| 文件 | 改动 |
|---|---|
| `src/analyzer.py` | 快照求值收敛为 `reload_config_snapshots()`（import 时调用一次；写盘后由 web 调用） |
| `src/settings_store.py`（**新增**） | 白名单 schema / 校验 / 备份 / 原子写 / 深合并（**读写配置的唯一入口**，web 专用但逻辑独立可测） |
| `web/app.py` | `GET /api/settings` + `POST /api/settings` + `/settings` 路由 |
| `web/templates/settings.html` | 新页面（head 主题内联 = **第 6 处同源**） |
| `web/static/settings.js` | 第 6 份 shell 副本 + 表单逻辑 |
| `web/templates/_sidebar.html` | 设置占位 → 真链接 |
| `web/static/style.css` | `.st-*` 段（不改任何既有声明） |
| `tasks/.../verify_ui.py` | `navDisabled` **1→0**（三处）+ navCount 保持 12（P1-1 后）+ 新增 `ST-*` 组 |
| `tests/test_settings_store.py`（**新增**） | 校验/备份/原子写/深合并/白名单拒绝（不联网、不碰真实 config.json——patch 路径） |
| `tests/test_web.py` | GET/POST 契约、Railway 只读（monkeypatch env）、reload 被调用 |
| `docs/commands.md` / `docs/frontend-structure.md` / `docs/system-overview.md` / `AGENTS.md` | 常规同步 + **「web 只读原则」条款的修订**（有限写白名单） |

**不动**：`src/config.py` 的三级链与白名单逻辑 · `check_breach` 语义 · 三个 cron 入口 ·
`data/**` · `.env`

---

## 5. 实施步骤

1. **`src/settings_store.py`**：schema + 校验 + 备份 + 原子写 + 深合并（纯函数，patch 路径可测）——先写测试再实现（红→绿）
2. **`analyzer.reload_config_snapshots()`**：import 段改为调用它（求值单源化）；跑 `pytest tests/test_config.py` **确认快照测试仍绿**（这是最可能碎的地方）
3. **API**：GET / POST（Railway 只读、备份、reload）
4. **页面**：模板 + JS（第 6 份 shell）+ `_sidebar` 转正
5. **verify_ui**：navDisabled 三处 1→0 + `ST-*` 组
6. **文档**：含 `AGENTS.md` 只读原则条款的修订

---

## 6. 验证命令

```bash
venv/Scripts/python -m pytest tests/test_settings_store.py tests/test_web.py tests/test_config.py -v
venv/Scripts/python -m pytest tests/ -q
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py          # 前台 + timeout 600000
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py --strict
```

**人工验收（核心闭环，缺一不可）**：
1. 改 `alert.k_factor` 2.0 → 2.5 → 保存 → 打开 `/backtest` ⇒ **触发次数/有效触发率应变化**
2. 改某个标的阈值 → 保存 → 页面刷新后值保持；`config.json` 出现 `.bak` 备份
3. POST 一个白名单外键（curl）⇒ 400 且文件未变
4. `RAILWAY_ENVIRONMENT=1` 起服 ⇒ POST 403、页面只读态

---

## 7. 风险评估

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| **R1** | 🔴 **写完不生效**（快照未刷新）——本任务头号风险 | **最高** | §3.2 reload + §6 人工验收 1（用 `/backtest` 变化实证） |
| **R2** | 🔴 reload 与 `tests/test_config.py` 的快照测试冲突（:174-198 直接断言快照值） | 高 | Step 2 单独跑该文件；若测试依赖"重新 import"语义，保持兼容（reload 只加不改既有求值） |
| **R3** | **与 P1-1 并发冲突**（同改 `_sidebar` / `verify_ui` / `style.css`） | 高 | **硬前置：等 P1-1 journal 落地后开工**；navCount 以 P1-1 后的 12 为基线 |
| **R4** | env 覆盖让用户"改了没用"（优先级链 env > config） | 中 | GET 返回 `env_overrides`，UI 显式标注；不隐藏 |
| **R5** | 写坏 `config.json` | 中 | 白名单校验先行 + 写前备份 + `load_config` 容错兜底（三层） |
| **R6** | Railway 检测失效导致线上可写（写入即丢且误导） | 中 | 检测只认 `RAILWAY_ENVIRONMENT`；线上只读是**默认安全侧** |
| **R7** | 把 `load_config()` 合并结果写回用户文件（固化内置默认） | 高 | §3.3 明令：读原文件深合并，**禁止**写回合并结果 |
| **R8** | 固定阈值表让用户误以为"改这里就调灵敏度" | 中 | §0-4：动态三参数置顶 + 固定阈值标注"回退基准" |

---

## 8. 预计影响的文件范围

新增 3（`settings_store.py` / `settings.html` / `settings.js` + 测试 1）· 修改 ≈9（analyzer / web.app /
sidebar / style.css / verify_ui / 4 文档）· **不动** config.py 三级链 / check_breach / cron 入口 / data/**

---

## 9. 明确不做

- ❌ 线上（Railway）配置持久化（迁 db）——独立任务
- ❌ 用户系统 / 多用户 / 操作审计日志（单人看板）
- ❌ `trend.*` / `history.*` 系统键的 UI
- ❌ 修改三级优先级链（env > config > 默认）——UI 必须服从它并如实展示
- ❌ Web Push / 邮件通知（那是"站内通知"任务的事）
- ❌ 在设置页里做"实时回测预览"（回测 UI 已有，跳过去看即可）

---

## 10. 决策裁定（2026-09-20 21:1x，用户已确认「都按你的推荐来」= 全采纳）

| # | 议题 | 裁定 | 落地 |
|---|---|---|---|
| **D-1** | 自选列表（watchlist）是否进本轮 | ✅ **A：进**（增删改 `symbol`/`label` + `corr_high_threshold`，高频操作） | §3.1 白名单 / Step 4 表单 |
| **D-2** | 备份策略 | ✅ **A：`config.json.bak-<YYYYMMDD-HHMMSS>` 滚动保留 5 份**（同目录，gitignore 已覆盖） | Step 1 |
| **D-3** | web 只读原则的修订方式 | ✅ **A：`AGENTS.md` 条款收窄**——「web 进程只可写 `config.json`（经 `src/settings_store.py` 白名单路径）；`data/` `alerts/` `context/` 仍然绝不写」 | Step 6 |

### 10.1 由裁定导出的实施要点

1. **D-1（自选进本轮）** ⇒ 校验规则补充：`stocks[]` 按 `symbol` 去重、≤30 条、两项均非空；
   保存后 `watchlist.json` 快照链路**不需要**动（下次报告时点自然刷新——既有语义，保持）。
2. **D-2（滚动 5 份）** ⇒ 清理逻辑在**写入成功后**执行（先备份再写，写失败不留备份不清理）。
3. **D-3（原则收窄）** ⇒ `AGENTS.md` 的修订**必须同时**出现在两处：
   「Project Map → web/」的只读描述 + 「Working Rules」如有相关条目一并同步；
   `docs/system-overview.md` §3 架构分层的「Web 零写盘」行同步。

### 10.2 实施后必须验证（缺一不可）

1. `pytest tests/test_settings_store.py tests/test_web.py tests/test_config.py -v` + 全量 `-q`
2. `verify_ui.py`（前台 + timeout 600000）：`navDisabled == 0`（三处）、`ST-*` 全绿、`BT-*`（P1-1 产物）**不回归**
3. **人工闭环**（本任务的存在意义，逐条做）：
   - 改 `alert.k_factor` 2.0→2.5 → 保存 → `/backtest` 数值变化（reload 生效实证）
   - 增删一条自选 → 保存 → 首页自选卡在下次数据时点反映（或 `GET /api/watchlist` 校验）
   - curl POST 白名单外键 ⇒ 400 且 `config.json` 未变
   - `RAILWAY_ENVIRONMENT=1` 起服 ⇒ POST 403、页面只读态
   - `config.json.bak-*` 存在且 ≤5 份
