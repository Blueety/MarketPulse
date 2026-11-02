# journal — 设置页（阈值 / 自选的看板化管理）

- **任务档**：`tasks/2026-09-20-settings-page/`（plan 定稿；D-1=A / D-2=A / D-3=A）
- **执行日期**：2026-09-20 21:0x–21:3x
- **前置**：P1-1（回测 UI）已交付并提交（`cae2aae`）✔

## 1. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/settings_store.py`（**新**） | 白名单 schema（17 键，动态三参数置顶）/ 单键校验 / **合成结果上的跨字段校验**（走项目自己的 `load_config` 三级链）/ 写前备份（滚动 5 份）/ 原子写 / 深合并（**只 set 白名单路径，用户其它键原样保留**） |
| `src/analyzer.py` | **快照求值单源化**：新增 `reload_config_snapshots()`，import 段改为调用它；`ALERT_THRESHOLDS` 声明在前由它填充（原地 clear+update）；`HISTORY_MAX` 不重建 |
| `web/app.py` | `GET /api/settings`（恒 200）+ `POST /api/settings`（Railway 403 → 校验 400 → 备份+原子写 → **reload**）+ `/settings` 路由 + `_ASSET_FILES` 登记 `settings.js` |
| `web/templates/settings.html` / `web/static/settings.js` | 新页面（**第 6 处**主题内联 / **第 6 份** shell 副本）+ 动态三参数置顶 + 阈值表（env 覆盖标注）+ 状态区间 + 自选增删改 |
| `web/templates/_sidebar.html` | 「设置」占位转正（唯一 `.is-disabled` 项） |
| `web/static/style.css` | `.st-*` 段（不改既有声明） |
| `verify_ui.py` | `navDisabled` 1→0（F-5）+ macroHrefs 数组 + `/settings` + 新 `ST-*` 组 7 条（**只读断言，绝不 POST 真实 config**） |
| `tests/test_settings_store.py`（**新**，15 条）/ `tests/test_web.py`（+5） | 校验/备份/原子写/深合并/白名单拒绝/不缓存/get-post-reload/Railway 403 |
| 文档 | `AGENTS.md`（只读原则收窄 D-3）/ `system-overview` / `frontend-structure` / `commands.md` |

## 2. 验证

| 项 | 结果 |
|---|---|
| `pytest tests/test_settings_store.py` | **15 passed** |
| `pytest tests/test_web.py -k settings` | **5 passed** |
| `pytest tests/ -q` | **768 passed / 1 failed**（唯一红仍是既有 us_sector） |
| `verify_ui.py` 全量 | **PASS 698 / FAIL 0 / SKIP 0（ALL PASSED）** —— `ST-*` 7 条全绿、`navDisabled=0`、BT-* 不回归 |
| **人工闭环（plan §10.2-3）** | ① 改 k_factor 2.0→2.5 保存 → **/backtest 触发 309→218 变化**（reload 生效实证）✔ ② 白名单外键 → 400 且文件未变 ✔ ③ 备份存在且 ≤5 份 ✔ ④ `RAILWAY_ENVIRONMENT=1` → GET 正常 + POST 403 + 回测展示不受影响 ✔ |

**变异验证**（证明测试不是空转）：临时注入 R7 bug（把三级合并结果写回用户文件）⇒
`test_apply_updates_writes_raw_and_keeps_user_keys` **立刻红**，还原后绿。

## 3. 过程中的问题与修正

1. 🔴 **备份文件名硬编码了 "config.json.bak-"**（人工闭环 ③ 抓到：0 份备份）——
   多环境/测试用不同 config 文件名时，备份会写错名甚至互相覆盖。**修法**：`_backup_prefix(path)` 按文件名派生。
2. ⚠️ **自选上限用 20 而非 plan 写的 30**：`src/config.py:_valid_watchlist` 的既有上限是 20
   （超限静默截断）——写 25 条若被读侧静默砍到 20，比报错更骗人。已做成一致性断言
   `test_stocks_cap_matches_reader`。**plan 笔误，已按事实处理**。
3. 🔴 **入口块位置坑第二次踩**：ST 组 `cat >>` 追加到 `verify_ui.py` 末尾，而入口块在它前面
   ⇒ 直接运行时 `main()` 调到未定义函数 → `NameError`（无 FAIL 行，险些漏检）。
   已把入口块清理为**恰好一个**并置于文件末尾；**这条已连续踩两次，后来者引以为戒**。
4. **并发会话在同时改本文档**：`frontend-structure` / `system-overview` 的多处计数已被并发会话同步
   （我脚本断言"命中 0"才发现）⇒ 剩余补齐前**先查现状再写**，避免重复/冲突。
5. `test_config.py` 的快照测试（plan R2 担心碎）**未受影响**：62 条相关测试全绿
   —— 因为 reload 只加不改既有求值路径（import 时仍调一次）。

## 4. 明确未做（与 plan §9 对照）

- ❌ 线上配置持久化（迁 db）❌ 多用户/审计 ❌ `trend.*`/`history.*` 的 UI
- ❌ 未改三级优先级链（env > config > 默认，UI 服从并如实展示）
- ❌ 未抽第 6 份 shell 副本（沿用"复制+记录"，抽取单独立项）
