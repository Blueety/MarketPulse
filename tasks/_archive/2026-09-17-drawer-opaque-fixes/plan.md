# 实施计划：移动端抽屉透明（不可读）修复

> **需求来源**：2026-09-17 14:14 用户手机截图（Android · 浅色主题 · 390 宽）——「手机打开侧栏菜单是透明的」
> **产出**：架构师复现 + 实测后出具；**未修改任何项目文件**
> **基线**：2026-09-17 14:1x，`master` @ `7917b3b`，工作区 **clean**
> **本文性质**：方案文档；这是**单点 CSS 修复**，计划刻意保持极简

---

## 1. 渲染表现根因（用户看到什么）

手机（≤768px）点汉堡打开抽屉后：抽屉**没有自己的底色**，侧栏文字（导航项、北京时间）**叠在页面内容上**，
内容透过抽屉清晰可见 ⇒ 读性崩溃，观感是"菜单是透明的/坏了的"。

## 2. 代码逻辑根因（机制，已复现实证）

**两层叠加，第二层是直接原因：**

1. **遮罩在工作是好的**：`.nav-backdrop`（`style.css:584`，`rgba(0,0,0,.4)`、z-index 55）由 JS 动态创建
   （`app.js:1179-1181`），实测 `opacity=1`、滚动锁定生效（`body{overflow:hidden}`，F4 交付物正常）。
2. **抽屉自身全透明（直接原因）**：基础规则 `#sidebar { background: transparent }`（`style.css:174-176`，
   **G-6 决策**：桌面端侧栏与页面同层、玻璃化只改透明）；而 ≤768 的抽屉规则（`style.css:624-628`）只写了
   `position: fixed / transform / z-index: 60 / box-shadow`，**没有补任何背景**。
   ⇒ `rgba(0,0,0,0)` 的 fixed 覆盖层叠在 `.4` 压暗的内容上 = 内容透出、文字对比度崩塌。

**为什么现在才被发现（潜伏期分析）**：
- 抽屉结构是 2026-09-05 重构引入，`background: transparent` 是 2026-09-11 **玻璃化 G-6** 引入
  ⇒ 潜伏 6 天；
- **dark 主题下遮罩黑压黑、侧栏浅色文字反而可读**（走查/调试多在 dark）⇒ 一直没暴露；
- 今天用户在**真机 + 浅色主题**（light 已是默认）下打开 ⇒ 必现。三页共用同一份 CSS ⇒ `/macro`、`/macro/cn` 同样中招。

### 复现路径（我已实跑，探针 `%TEMP%\mp_drawer_probe.py` → `%TEMP%\mp-drawer-probe\`）

1. `venv/Scripts/python -m uvicorn web.app:app --port <空闲端口>`；视口 **390×844**（或 375×812）
2. 打开 `/` → 点 `#menu-toggle` → 等过渡（~600ms）
3. 实测值（改前）：`#sidebar` computed `backgroundColor = rgba(0, 0, 0, 0)`；`.nav-backdrop` opacity=1 / z=55；
   `body` overflow=hidden；`elementFromPoint(110,420) = nav-item`（抽屉可交互）——两视口（390/375）一致

### 关键测量点与 box-sizing 说明

- 本缺陷与 `box-sizing` / 尺寸**无关**（不要往 padding/width 方向修）：`#sidebar` 宽 240px、几何正常，
  唯一问题变量是 **`background`（层叠表面的不透明度）**。
- 相关层级（勿动）：topbar z=**100** > 抽屉 z=**60** > 遮罩 z=**55**；`#sidebar` 有 `box-shadow: 0 8px 30px …`。

---

## 3. 修法（一行 CSS，作用域锁死在抽屉媒体查询内）

在 `@media (max-width: 768px)` 的 `#sidebar` 规则（`style.css:624-628`）里**追加一行**：

```css
background: var(--bg-elevated);   /* light #FFFFFF / dark #111827 —— 浮层语义 token，双主题自带 */
```

**为什么是 `--bg-elevated`**：
- 它就是"抬升表面"语义 token（卡片浮层的实底色），双主题各有值 ⇒ **无需写死色值、无需双份**；
- **不用** `--glass-bg` + blur：G-6 明令侧栏不加 `backdrop-filter`（规避 R19 sticky+blur 滚动残影、R18 层叠上下文），
  且半透明玻璃在压暗背景上**还是透**，修不彻底；
- 桌面端 `background: transparent`（G-6 决策）**保持不变** —— 改动只存在于 ≤768 媒体查询内部，作用域天然隔离。

**明确不做**：不给遮罩加深、不调 z-index、不动 F4 的滚动锁定/焦点逻辑、不抽共享组件。

---

## 4. 验证

| # | 命令 / 动作 | 期望 |
|---|---|---|
| V1 | `verify_ui.py`（**改前先跑**记基线，改后再跑） | 失败集 ⊆ 基线（G8：上游红是常态，只看相对变化）；抽屉相关断言（F4 的滚动锁定/焦点、z 层级）全绿 |
| V2 | 390/375 视口开抽屉 | `#sidebar` computed `backgroundColor` = **不透明**（light `rgb(255,255,255)` / dark `rgb(17,24,39)`） |
| V3 | 三页各开一次抽屉 | `/`、`/macro`、`/macro/cn` 一致修复 |
| V4 | 双主题人工截图 | light / dark 各一张；桌面端（>768）侧栏**仍是透明同层**（G-6 不回退） |

---

## 5. 风险

| # | 风险 | 处置 |
|---|---|---|
| R1 | 改动落在媒体查询外 → 桌面侧栏变白块（G-6 回退） | 行必须写在 `@media (max-width:768px)` 块内；V4 桌面截图复核 |
| R2 | `verify_ui` 有断言读侧栏背景（主题切换三态组） | 改前 grep `sidebar` + `backgroundColor` 相关断言；改后 V1 全量对比 |
| R3 | 半透明观感损失（抽屉不再"透出"页面） | **有意为之**：覆盖层必须不透明是可用性底线；效果图玻璃感由 box-shadow + 边框承担 |

---

## 7. 预计影响范围

```
web/static/style.css    +1  −0    @media(max-width:768px) 内 #sidebar 补 background
tasks/2026-09-17-drawer-opaque-fixes/   本任务档（plan/journal）
```

**零改动**：`app.js` / `macro*.js` / 模板 / `web/app.py` / `src/**` / `tests/**`。
**提交清单**：`web/static/style.css` + 本任务档；`git add <具体路径>`，不用 `-A`。
