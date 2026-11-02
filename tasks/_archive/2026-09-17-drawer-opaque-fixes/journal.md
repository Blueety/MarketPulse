# Journal — 移动端抽屉透明（不可读）修复（drawer-opaque-fixes）

- **日期**：2026-09-17
- **需求来源**：用户手机截图（Android · 浅色主题 · 390 宽）——「手机打开侧栏菜单是透明的」
- **依据**：`plan.md`（架构师已复现实证；单点 CSS 修复，计划刻意极简）
- **基线**：`master` @ `7917b3b`，工作区 clean

---

## 1. 根因（架构师已复现，本轮复核确认）

两层叠加，第二层是直接原因：
1. 遮罩 `.nav-backdrop`（rgba(0,0,0,.4)、z=55）工作正常（opacity=1、F4 滚动锁定生效）；
2. **抽屉自身全透明**：基础规则 `#sidebar { background: transparent }`（G-6 玻璃化决策，桌面与页面同层），
   而 ≤768 的抽屉规则只写了 `position:fixed / transform / z-index:60 / box-shadow`，**没补背景**
   ⇒ `rgba(0,0,0,0)` 的 fixed 覆盖层叠在压暗内容上 = 文字对比度崩塌。

**潜伏 6 天的原因**：dark 主题下遮罩黑压黑、浅色文字反而可读；今天用户在真机 + **浅色主题**（默认）下打开 ⇒ 必现。
三页共用同一份 CSS ⇒ `/`、`/macro`、`/macro/cn` 同样中招。

---

## 2. 交付（1 行 CSS + 断言补强）

| 文件 | 内容 |
|---|---|
| `web/static/style.css` | `@media(max-width:768px)` 的 `#sidebar` 规则内追加 **`background: var(--bg-elevated);`**（浮层语义 token：light `#FFFFFF` / dark `#111827`），附原因注释（含"不用 --glass-bg + blur"的理由：G-6 明令侧栏不加 backdrop-filter，且半透明在压暗背景上还是透） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | ① GLASS_JS 增 `elevatedBg`（运行时解析 `--bg-elevated`）；② **G-6 断言按视口分语义**（>768 透明 = G-6 原判据逐字保留；≤768 必须 == `--bg-elevated` 实底，且两分支都要求无 backdrop-filter）；③ `assert_home_ux` 增 `UX-1c`（桌面 1440 侧栏仍透明，G-6 不回退）+ `UX-4e`（抽屉实底）+ `HOME_UX_JS` 增 `sidebarBg/elevatedBg` |

**零改动（已核实）**：`app.js` / `macro*.js` / `chart-crosshair.js` / 模板 ×3 / `web/app.py` / `src/**` / `tests/**`。
桌面端 `background: transparent`（G-6 决策）**保持不变** —— 修复只存在于 ≤768 媒体查询内部。

---

## 3. 验证（红 → 绿，判读以完成标记为准）

| 步骤 | 结果 |
|---|---|
| **红跑**（CSS 未修，UX 组） | `UX-4e` **FAIL**：抽屉 bg = `rgba(0,0,0,0)` ≠ `--bg-elevated` ✔（用户缺陷的行为级钉子）；`UX-1c` 桌面透明双主题 PASS ✔（G-6 尚未被破坏） |
| **绿跑**（CSS 修复后，UX 组） | **22 PASS / 0 FAIL**：`UX-4e` 抽屉实底 ✔ + `UX-1c` 桌面仍透明 ✔（双主题） |
| **V2/V3/V4 探针**（`%TEMP%\mp_drawer_verify.py`） | **三页 × 双主题 × 390 视口**：开抽屉后 `#sidebar` bg = light `rgb(255,255,255)` / dark `rgb(17,24,39)`，backdrop opacity=1 ⇒ **6/6 PASS**；**桌面 1920** 双主题 sidebar bg = `rgba(0,0,0,0)` ⇒ **2/2 PASS**（G-6 不回退）✔；截图 `shot-drawer-light/dark.png` |
| **全量** | **537 PASS / 12 FAIL**，0 traceback、汇总行在；12 条 = 既有上游/Firefox 集合 ⇒ **失败集 ⊆ 基线** ✔（含改写后的 G-6 分支断言与 UX-4e/1c 全绿） |

---

## 4. 实施中的关键点

### 4.1 G-6 断言必须**按视口分语义**（R2 实锤）

`verify_ui` 的 G-6 断言（`assert_glass`）原为无条件要求 `#sidebar` 透明，且跑**全部 5 个视口**（含 375）
⇒ 修复必然撞它。**这不是放松判据，是给断言补上它写漏的半个语义**：G-6 决策说的是"桌面端侧栏与页面同层"，
而 ≤768 的侧栏是 **fixed 覆盖层**——覆盖层必须不透明是可用性底线。
修法：拆成"两分支共同要求（无 backdrop-filter）+ 按视口分支（桌面透明 / 抽屉实底）"，
桌面分支的判据**逐字保留**，抽屉分支是**新增**的更严要求。探索过程：先发现 `GLASS_JS` 已有 `sidebarBg`
字段但断言无条件要求透明 → 按视口拆分。

### 4.2 复用既有模式，避免重蹈覆辙

- 骨架/失败条的"display 覆盖 `.hidden`"陷阱（id 特异性 > `.hidden`）在本仓库已两次出现
  ⇒ 新增的 `#home-chart-skel` / `#home-fail-bar` / 本次抽屉背景全部用 `:not(.hidden)` 或不含 display 的写法。
- 本轮无 pitfalls 追加（plan 刻意极简，单点修复无可沉淀的新模式；既有规则已覆盖"覆盖层要实底"的判断）。

---

## 5. 遗留 / 待办

- ❌ 无（本任务为单点修复；桌面 G-6 透明、遮罩、F4 滚动锁定/焦点均未动）。
- ⚠️ 产线复核：下次 Railway 部署后，真机（Android · 浅色）开抽屉确认可读（本机已按 390/375 + 双主题实测）。
