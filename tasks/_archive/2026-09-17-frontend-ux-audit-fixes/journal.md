# Journal — 前端体验走查整改（F1–F4，P1×2 + P2×3）

- **日期**：2026-09-17
- **依据**：`plan.md`（架构师对走查报告逐条核实后出具；P3×3 明确延后）
- **性质**：对比度 token / 刷新反馈 / 主题初始化同源 / 抽屉焦点管理 + 新断言组 `UX-*`
- **基线**：`master` @ `7dc6231`，工作区仅 2 个未跟踪任务档

---

## 1. 交付内容（4 项全做完）

| 步骤 | 文件 | 实施结果 |
|---|---|---|
| **F1** 对比度 | `style.css` | light `--text-muted` **#9CA3AF → #6B7280**（页底 #F7F8FA 上 **2.39 → 4.55:1**；白卡 4.83；与 `--text-secondary` 同值）+ light `--c-ixic` **#13C2C2 → #0D7D7D**（`.chart-meta` 把系列色当文字色，白卡 **2.08 → 4.65:1**）+ `.ms-time` **10 → 11px** |
| **F2** 刷新反馈 | `app.js` / `index.html` / `style.css` | `refresh()` 重构：`refreshing` 防重入 + `setRefreshBusy`（`#refresh-btn`/`#home-retry` 禁用）+ history `if (!r.ok) throw` + **保留旧图渲染** + `#home-fail-bar`（`aria-live=polite`）+ 重试按钮；`#trend-meta` 补 `aria-live` |
| **F3** 主题初始化 | `index.html` | head 内联脚本对齐 `macro.html` 的 D1 修复版（light/dark 双处理）—— 主题初始化第 4 处对齐 |
| **F4** 抽屉 | `app.js` / `style.css` | `setDrawerOpen`：`body.nav-open{overflow:hidden}` 滚动锁定 + 开抽屉焦点移入侧栏首个可聚焦项 + 关闭/Escape 焦点归还 `#menu-toggle`（幂等，桌面端点 main 不抢焦点） |

**零改动（已逐项核实）**：`macro.html` / `macro.js` / `macro_cn.js`（宏观页昨晚交付物与 N-* 断言原样）、
`chart-crosshair.js`、`web/app.py`、`src/**`、`tests/**`、`_sidebar.html`、`_topbar.html`。

---

## 2. 实施中的关键决策

1. **F1 的色值用 WCAG 公式算出来**，不是目测：`--text-muted` #6B7280（页底 4.55 / 白卡 4.83）；
   `--c-ixic` 在 5 个候选里选 **#0D7D7D**（同色相、最小位移即达标：白 4.95 / 卡 4.65；#0E8C8C 只有 4.08 不够）。
   模式与 `--green` 的"light #16A085 / dark #2FD6A8"一致。
2. **F2 有意复制宏观页的失败条模式而不抽共享**：`#home-fail-bar`/`#home-retry` 与 `#mac-fail-bar` 同构
   （显示语义由 `:not(.hidden)` 承担），避免牵连宏观页 N-* 断言与 DOM 契约 —— 与 shell 三副本同源的取舍。
3. **F4 的 close 必须幂等**：桌面端每次点击 `#main` 都会调 close，若无条件 `menuBtn.focus()` 会**抢走正常点击的焦点**
   ⇒ `setDrawerOpen` 先判 `open === was` 直接返回，只有"从开到关"才归还焦点。
4. **F3 的行为级验证思路**：`page.route` **abort 掉 app.js** 再载入 ⇒ 页面层主题只可能来自 head 内联脚本
   ⇒ 隔离出"内联脚本是否双处理 light/dark"这一个变量（否则 app.js 的 applyTheme 兜底会掩盖缺陷）。

---

## 3. 验证（全部实跑，判读以完成标记为准）

| # | 命令 / 动作 | 结果 |
|---|---|---|
| V0 | `node --check web/static/app.js` | ✔ |
| V1 | `pytest tests/test_web.py -q` | **120 passed** ✔ |
| V2 | 改前基线 | **536 PASS / 13 FAIL**（12 条上游/Firefox + `B-6b` 告警滚动时序抖动），0 traceback、汇总行在 |
| V4 | **UX 组改前红跑** | **12 FAIL**（对比度 light 2.39 / ixic 2.08 / ms-time 10px / 隔离 app.js 后 dark 落 `light` / 失败条缺失 / 抽屉无锁定）——UX-1 dark **6.82:1 本来就过**（印证"深色修了浅色没修"） |
| V3 | 改后全量 | **535 PASS / 18 FAIL**：**UX 组 19 PASS / 0 FAIL**；新增红 = `MS-6a/b ×3 档`（见 §4）|
| V3' | 修 MS 钉子后复跑 | 见 §6（待本轮结果） |
| V5 | 双主题人工截图 | `shot-ux-home-light.png` / `shot-ux-home-dark.png`：light 副文字与 `.chart-meta` 明显更可读、整体不发灰；dark 零回归 ✔ |

---

## 4. 遇到的问题

### 4.1 F1 的 `.ms-time` 11px 与昨日钉死的几何断言冲突（预期内，已同步钉子）

`MS-6a/b`（昨日 market-session-status 交付的几何钉子）钉死 `.sidebar-footer = 63` / `.market-status = 50`。
F1 把 `.ms-time` 10→11px ⇒ 该行 +2px ⇒ **footer 65 / market-status 52**（1920/1280/769 三档实测一致，非抖动）。
处置：**钉子随有意的几何变更同步更新**（63→65、50→52，注释写明原因），语义不变（仍是"防无意的几何漂移"）。
⚠️ `docs/architecture.md` 里昨日那行写的"footer 45→63"是**历史事实**，不改；本轮决策行单独记录 65/52。

### 4.2 红跑阶段自己踩的两个坑（与昨日同族）

1. **`HOME_UX_JS` 原始字符串没闭合**（漏了结尾的三引号）→ `py_compile` 报"invalid character '（'"
   （报错点在**下一个**三引号处，离真正的失误很远）。教训：大段 JS 字符串插入后先 `py_compile` 再跑。
2. **探针里 `getElementById('home-retry').click()` 未判空** → 改动前首页没有该按钮 ⇒ 崩在整组中间。
   已改为守卫式点击（与 NA-11 同款教训）。

### 4.3 基线本身多出一条 `B-6b`（与本任务无关）

`B-6b 环绕后继续前进（循环未停住）(actual=(198, 2, 4))` 是告警自动滚动的时序类断言，
昨日两轮全量都是绿的 ⇒ 时序抖动。本轮复跑若再出现，按"基线 ⊇ 本轮"口径处理（已在基线集合里）。

---

## 5. 验证结果汇总（本轮）

- `UX-*`：**19 PASS / 0 FAIL**（对比度 light 4.55 / dark 6.82；ixic 4.65；ms-time 11px；
  主题初始化隔离测试双主题通过；失败条三段式（悬挂-失败-恢复）全过；抽屉滚动锁定 + 焦点管理全过）
- 全量：**535 PASS / 18 FAIL** → 修 MS 钉子后待复跑（预期 12 条既有集合，见 §6）
- `pytest tests/test_web.py`：**120 passed**

---

## 6. 待办 / 遗留

- ⏳ 修 MS-6a/b 钉子后的**最终全量**（见 §3 V3'）。
- ❌ P3×3 延后（plan §6）：h1 landmark、占位文案（等需求方给接入计划）、失败条下沉共享组件。
- ❌ **首页与宏观页的失败条仍是两份副本**（有意复制）——若将来出现第 3 处，应抽共享（plan §6 已记）。
- ⚠️ 走查报告的 token 名错误（`--text-tertiary` 不存在）已写入 `docs/pitfalls.md`。
