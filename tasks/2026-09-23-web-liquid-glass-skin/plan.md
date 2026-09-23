# plan — Web 看板换上 skin-kit 液态玻璃皮肤（第一期：`/` 首页 + 背景改造）

- **任务档**：`tasks/2026-09-23-web-liquid-glass-skin/`
- **提出**：2026-09-23，用户原话「`D:\AGENT\Todo\skin-kit` 你看一下这个液态玻璃皮肤，我想给我的前端换上这一套皮肤」
- **决策已定（2026-09-23 用户确认）**：①完整接入引擎，**要折射**；②**先做一页**（`/` 首页）；③**给背景加纹理/换背景**；④门禁按架构师方案（重写视觉数值断言 + 新增 `LG-*`）；⑤引擎 **vendored 进仓**。
- **产出角色**：架构师（本文件为方案；**未改任何项目文件**，全部实测数据来自 `%TEMP%` 临时验证环境）
- **上游皮肤**：`D:\AGENT\Todo\skin-kit` + `@avenra/liquid-glass@1.2.0`（MIT，npm-only）

---

## 0. 结论摘要（先看这 8 条，全部实测）

| # | 结论 | 证据 |
|---|---|---|
| C1 | **折射要有「可弯折的内容」**：现状背景在 11px 位移尺度上的亮度差仅 **0.30/255（浅）/0.39（暗）**，套件 demo 的斜纹背景是 3.6–3.9 ⇒ 现状下折射不可见。 | 背景频谱探针 `d11 = mean\|I(x+11)−I(x−11)\|`，`%TEMP%\bg-K0_current.png` |
| C2 | **纹理能被玻璃「透过」的前提是间距 ≥ 16px**。实测「卡内/卡外」纹理留存比：6px 细斜纹 **0.02**（被 blur 2.5 抹平）、24px 圆点 0.13、**16px 方格 0.52**、32px 方格 0.52（blur 2.5）；把 blur 降到 1.0 才能让 6px 斜纹留存 0.77。 | 矩阵实测 `mix-<blur>-<texture>.png`（DPR3 边缘横跨带，卡外 d11 / 卡内 d11） |
| C3 | **推荐背景＝16px 细方格纸 + 品牌蓝光斑**（不是 6px 斜纹；斜纹在 2026-09-12 已被否，且此处物理上也被抹平）。实测：卡外 d11 2.65（α=.10）/ 1.6（α=.06），卡内留存 ~52%。 | 同上 + `rec-full.png`（推荐配置整页效果） |
| C4 | **面板必须给「看得见」的染色**，kit 默认窗口染色只有 .06 ⇒ 数据密集看板会变「几乎全透」，正文可读性受损。推荐 `color-mix(in srgb, var(--bg-elevated) 46%, transparent)`（实测整页可读、文字对比度肉眼无损）。 | `rec-full.png` vs `final-grid16-blur1.png`（后者过度通透，观感发飘） |
| C5 | **材质成本实测**：真实 `/` 首页 13 个宿主（topbar + 4 kpi + 8 card）同步挂载共 **188.8ms**（单面 7–32.3ms），生成 13 棵 `<svg><filter>`。⇒ 必须走 `scheduleGlass` 分帧，首屏只挂静态壳。 | `window.__reskin`，`%TEMP%\skinspike` |
| C6 | **宿主自带玻璃必须让位**：`.card`/`.kpi-card`/`.topbar` 今天都有 `backdrop-filter` + 白色填充；只关 `backdrop-filter` 不够——填充也要改（否则材质被自身白底盖住，实测卡内纹理留存直接归零）。 | spike 两轮对照（只关 blur vs 同时改填充） |
| C7 | **`verify_ui.py`（5436 行）会被大面积打红**：钉死了卡片圆角/阴影/`box-sizing`（`:4882-4884`）、`scrollHeight ≤1240`（`:1035/:1321`）、canvas 位图==CSS 尺寸（`:4873/:879`）、`--text-muted == #8E9BAE`（`:1281`）、玻璃 alpha 区间（`:389-393`）、对比度 ≥4.5（`:3518-3524`）。换肤＝**先重写门禁再改样式**。 | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` |
| C8 | **令牌作用域必须选 `[data-liquid-skin]`（(0,1,0)），不要用 `port-example` 的 `html[data-skin='liquid']`（(0,1,1)）**：后者会盖掉宿主已修的 `--text-muted`（`#6B7280`/`#8E9BAE`）。实测用前者时宿主值胜出。 | spike `getComputedStyle(documentElement).getPropertyValue('--text-muted')` → `#6B7280` |

> 一句话：**换皮肤＝换背景（16px 方格纸）+ 引擎折射材质 + 面板染色 + 关掉宿主那层旧玻璃**；其中背景是新增工作量，也是「液态」成立的唯一前提。

---

## 1. 任务目标

1. 把 `skin-kit`（引擎 + 皮肤 CSS + JS 运行时）完整接入 `web/`，让 `/` 首页呈现真实折射的液态玻璃；
2. 换掉现有「平坦渐变」画布，改为**能给玻璃提供可折射结构的背景**（浅/暗双主题），同时不损伤数据可读性；
3. 保持仓库纪律：零构建、不改后端数据链路与 10 个 JSON API、不破坏报告主流程；
4. 验收可量化：纹理留存比、材质可见性、文本对比度、降级链、命中区、性能。

**本期范围**：仅 `/` 首页（含共享 `_topbar.html`/`_sidebar.html`）。`/macro`、`/macro/cn`、`/timeline`、`/backtest`、`/settings` 留到第二期。

**非目标**：不引入 UI 框架/构建器；不做套件 React 档；不改 `src/**` 与数据链路。

---

## 2. 上游事实（硬契约）

### 2.1 加载顺序（唯一不可改的次序）
```
① web/static/vendor/liquid-glass/liquid-glass.css   引擎样式
② web/static/skin/tokens.css                          主题令牌
③ web/static/skin/liquid-skin.css                     皮肤本体
④ web/static/skin/motion.css                          过渡 + reduced-motion 守卫
⑤ web/static/style.css                                宿主 CSS（永远最后）
```
皮肤靠**源顺序 + 宿主选择器特异性**压过引擎；**禁止 `@layer`**（未分层样式优先于所有分层样式，引擎 CSS 未分层 ⇒ 皮肤覆盖全失效）。

### 2.2 作用域与主题
- 作用域属性 `[data-liquid-skin]`，**令牌必须与 `data-theme` 同元素**（I11：写错层 ⇒ `var()` guaranteed-invalid ⇒ **整页白页且不报错**）。落地：`<html data-liquid-skin data-theme="light|dark">`。
- **不要**用 `html[data-skin='liquid']`（见 C8）。

### 2.3 引擎（v1.2.0）关键接口
- `init({root})` / `createLiquidGlass(el, opts)`；`init` 只扫**子树**（不匹配 root 自身），幂等（`_lgInit`）；属性通道**不认** `radius/width/height/options` ⇒ 圆角用 CSS、radio/select 走工厂。
- 每次调用注入 `.lg-inner`(z3) + `.lg-clone`(z1) + `.lg-clone-world` + 1 棵 `<svg><filter>`；**内容层必须自己抬到 z4**（用 `.skin-glass-body`）。
- **材质是写进内联样式的**（`backdrop-filter: url("#lg-N")`），只有作者 `!important` 能压。
- `supportsBackdropFilter()` 实为 `!!window.chrome && CSSOM 接受 url()`；`applyEngineMode(doc,{force})` 只翻 CSS 分支。**首帧前**写 `document.documentElement.dataset.glassEngine`。
- 宿主可传参数（`data-*` 或 opts）：`bezelWidth / glassThickness / refractiveIndex / blur / saturation / specularSlope / profile / filterMode`。

### 2.4 套件给不了、必须宿主自补
`applyEngineMode()` 首帧前调用、`scheduleGlass` 分帧、`html.is-scrolling` 滚动降级触发、浮层材质、`destroy()` 后 `.lg-switch-track` 清理、克隆折射路径（**刻意不搬**，非 Chromium 会白卡）。

---

## 3. 背景方案（实测定稿）

### 3.1 物理规则（实测得出，是本计划的核心约束）

玻璃材质 = `feGaussianBlur(blur) → feDisplacementMap(scale≈11px) → saturate → specular`。因此背景纹理要**同时**满足：
1. **间距不能太密**：特征周期 P 必须远大于模糊尺度（σ≈2.5px ⇒ 衰减 ≈ `exp(−2π²σ²/P²)`）。实测 P=6px 几乎全灭（留存 0.02），P≥16px 留存 ~0.52。
2. **对比度要够**：纹理太淡（α<.04）即使间距合适也读不出位移。

实测矩阵（`d11 = mean|I(x+11)−I(x−11)|`，DPR3 卡边横跨带；比值 = 卡内/卡外）：

| 纹理 | 间距 | 卡外 d11 | 卡内 d11 | 留存比 | 判定 |
|---|---|---|---|---|---|
| 无（现状） | — | 0.29–0.53 | 0.05 | 0.1 | ✗ 折射不可见 |
| 细斜纹 | 6px | 3.50 | 0.07 | **0.02** | ✗ 被 blur 抹平（且 2026-09-12 已被否决） |
| 圆点阵 | 24px | 4.07 | 0.53 | 0.13 | ✗ 位移下散掉 |
| **细方格** | **16px** | **2.65**（α=.10）/ 1.6（α=.06） | 1.39 / 0.9 | **0.52** | ✅ 推荐 |
| 大格 | 32px | 1.81 | 0.94 | 0.52 | ○ 备选（更「图纸」、更疏） |

### 3.2 推荐配方（浅色；暗色需等比例换白线并在第二期验证）

```css
/* 纹理层放在最上，保留宿主两层环境光 */
body {
  background-image:
    repeating-linear-gradient(0deg,  rgba(17,24,39,.06) 0 1px, transparent 1px 16px),
    repeating-linear-gradient(90deg, rgba(17,24,39,.06) 0 1px, transparent 1px 16px),
    var(--ambient-1), var(--ambient-2);
  background-repeat: repeat, repeat, no-repeat, no-repeat;
  background-size: auto, auto, auto, auto;
  background-attachment: fixed;   /* 保持既有「玻璃扫过背景」语义，且不参与布局 */
}
/* 玻璃面板染色：kit 默认 .06 太透，数据密集页需要更实的底 */
.card > .lg-inner, .kpi-card > .lg-inner, .topbar > .lg-inner {
  background: color-mix(in srgb, var(--bg-elevated) 46%, transparent);
}
/* 宿主旧玻璃让位（I7：不许玻璃套玻璃） */
.card, .kpi-card, .topbar { backdrop-filter: none; -webkit-backdrop-filter: none; }
```
- ⚠️ **`background-image: <纹理>, none` 是非法值**（整条声明会被丢弃，2026-09-12 踩过）⇒ 多层里必须每层都是合法图像。
- ⚠️ 纹理层不参与布局 ⇒ 不影响 `scrollHeight`（`verify_ui.py` 的总高基线不该因此变化）。
- ⚠️ 染色必须落在 `.lg-inner`（材质层），不是宿主 —— 宿主的 `background` 在材质层**下面**，染错了等于没染。

### 3.3 效果证据
- 推荐配置整页：`%TEMP%\rec-full.png`（16px 方格 α=.06 + 面板染色 46% + blur 2.5）
- 玻璃边缘放大（DPR3）：`%TEMP%\mix-2.5-grid16.png`（可看到方格在卡内衰减并轻微弯折）
- 反例（过度通透、发飘）：`%TEMP%\final-grid16-blur1.png`

---

## 4. 涉及文件

### 4.1 新增

| 文件 | 内容 |
|---|---|
| `web/static/vendor/liquid-glass/liquid-glass.css` | 引擎样式（16KB，**原样**，禁止改写/内联） |
| `web/static/vendor/liquid-glass/liquid-glass.esm.js` | 引擎 ESM（98KB，自包含） |
| `web/static/vendor/liquid-glass/LICENSE-avenra-liquid-glass.txt` | MIT 文本（NOTICE 要求随产物保留） |
| `web/static/vendor/liquid-glass/README.md` | 版本 1.2.0、来源、刷新方法、易变面清单（引 `skin-kit/NOTICE §4`） |
| `web/static/skin/tokens.css` | 套件令牌**宿主化**：只补宿主缺失名（`--bg/--text/--surface-opaque/--hairline/--accent/--track/--grip`），其余别名到 `--bg-primary/--text-primary/--border/--blue`；**不覆盖** `--text-muted` |
| `web/static/skin/liquid-skin.css` | 套件皮肤本体（原样搬，`[data-liquid-skin]` 作用域） |
| `web/static/skin/motion.css` | 套件过渡守卫（原样） |
| `web/static/skin/mp-skin.css` | 宿主补丁层（放最后）：§3.2 的背景配方、面板染色、旧玻璃让位、内容层抬升（`.card > .skin-glass-body{z-index:4}`）、scrollbar 让位、`--lg-tune-*` 调参点 |
| `web/static/skin.js` | 首帧前 `applyEngineMode()` + `scheduleGlass` 分帧挂载 + `.is-scrolling` + `window.mpSkin.remount(el)` |
| `tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py` | 皮肤验收脚本（Playwright，自动挑空闲端口） |

### 4.2 修改

| 文件 | 改动 |
|---|---|
| `web/templates/_topbar.html` | `.topbar` 加 `data-liquid-glass`，内容包 `.skin-glass-body` |
| `web/templates/index.html` | `<head>` 按 ①②③④⑤ 插 `<link>` + `skin.js`；8 个静态 `.card`（含 `.promo` 视决策）加 `data-liquid-glass` + `.skin-glass-body` |
| `web/static/style.css` | ① 令牌双轨（新增别名，**保留** `--text-muted` 原值）；② §3.2 背景配方；③ 宿主旧玻璃让位；④ 圆角阶梯对齐套件档位（12 → 16/24 待定，见 D-7） |
| `web/static/app.js` | 主题初始化处同步 `data-liquid-skin`；渲染批次后调 `window.mpSkin?.remount(container)` |
| `web/app.py` | `_ASSET_FILES`（`:216-217`）登记新增静态文件（否则无 `?v=` 指纹） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 重写视觉数值断言 + 新增 `LG-*` 组（C7） |
| `docs/architecture.md`、`docs/frontend-structure.md` | 记录外部皮肤来源/版本、加载顺序契约、令牌映射、背景配方、禁改项 |

**不碰**：`src/**`、`daily_report.py`、`snapshot_report.py`、`data/**`、`alerts/**`、`context/**`、API 响应契约。

---

## 5. 实施步骤（每步独立验收）

### S0 门禁先行（C7）
1. 读全 `verify_ui.py` 的视觉数值断言清单，按「①结构/契约类（保留）②视觉数值类（重写）③皮肤新增类（新增）」三分类出清单。
2. 记录现行基线值（卡片圆角/阴影/alpha 区间/总高/对比度）为 `--baseline` 快照，避免「改完不知道原来是多少」。
3. **验收**：`verify_ui.py` 在未改样式时全绿（除已知基线红），分类清单入档。

### S1 背景改造（本期唯一「新增设计」）
1. 按 §3.2 改 `body` 背景 + 面板染色 + 关旧玻璃。
2. **验收**：纹理留存比 ≥0.4；卡外 `d11 ≥ 1.5`；文本对比度 ≥4.5；`scrollHeight` 与基线一致；浅/暗双主题各拍一张基线图。

### S2 引擎接线
1. vendored 引擎 + 3 张套件 CSS + `skin.js`；6 处 `<head>` 与 `_ASSET_FILES`。
2. `<html>` 加 `data-liquid-skin`（与 `data-theme` 同元素）。
3. **验收**：页面 200、`html[data-glass-engine] === 'refract'`、控制台 0 error、**此步无视觉变化**（还没挂宿主）。

### S3 首页首个玻璃面
1. `.topbar` + `#trend` 大卡加 `data-liquid-glass` + `.skin-glass-body`；`scheduleGlass` 分帧挂载。
2. **验收**：每宿主**恰好 1 个 `.lg-inner` + 1 个引擎 `<svg><filter>`**；无 console error；`.lg-inner` 圆角 == 宿主圆角；单面耗时记账。

### S4 其余首页宿主 + 动态重挂载
1. 4 个 `.kpi-card` + 其余 `.card` 上材质（`.promo` 视其渐变色卡定位决定是否跳过）。
2. `app.js` 渲染批次后 `remount`（自选表/概览迷你卡等 `innerHTML` 重建区）。
3. ⚠️ M1 专项：检查引擎位移在**卡片相邻边**产生的伪影（spike 中在概览区出现过一处白色团块），定位后用「宿主 `overflow:hidden` + 内容层 z4」或调整 bezel 参数消除。

### S5 门禁重写与文档
1. 重写 `verify_ui.py` 视觉数值断言、新增 `LG-*`；写 `verify_skin.py`。
2. `docs/*` 落契约。
3. **验收**：`verify_ui.py` + `verify_skin.py` 双绿；`pytest tests/` 保持既有基线（后端零改动）。

---

## 6. 验证命令与验收判据

```bash
venv/Scripts/python -m pytest tests/ -q                                   # 回归基线
venv/Scripts/python -m uvicorn web.app:app --port 8123                    # 起服（每轮换端口，规避静态缓存）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
venv/Scripts/python tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py
venv/Scripts/python tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py --engine=frost
```
> `SKIP` **不是绿灯**（未判定）；要「一条都不许未判定」加 `--strict`。

### 6.1 关键测量点（逐宿主/逐层量）
| 量 | 期望 | 方法 |
|---|---|---|
| 宿主子节点顺序 | `.lg-clone → .lg-inner → .skin-glass-body →` 含 `filter` 的 `<svg>` | `host.children`；注意 `:scope > svg` 会先抓到自家图标 svg |
| `.lg-inner` 几何 | `absolute; inset:0; z-index:3; border-radius == 宿主圆角` | `getComputedStyle` |
| 材质生效 | `backdrop-filter: url("#lg-N")`（refract） | 同上 |
| **纹理留存比** | 卡内 d11 / 卡外 d11 **≥ 0.4** | DPR3 卡边横跨带截图 + numpy（方法见 §3.1） |
| 背景结构 | 卡外 d11 **≥ 1.5** | 同上 |
| 面板可见性 | 面板不是「全透」（卡内空白区亮度与背景差 ≥ 8/255） | 同法 |
| 文本对比度 | 正文 ≥ 4.5:1 | 复用 `verify_ui.py` 既有口径 |
| 命中区（I2） | 可见圆角外 `elementFromPoint` 不命中内层 input/button | Playwright 取点 |
| 降级链 | reduced-motion → 过渡 `none`；forced-colors → `.lg-inner` 1px `CanvasText`；reduced-transparency → 面转 `color-mix(--surface-opaque 92%)` | `emulateMedia` |
| 性能 | 首屏 13 面 ≤ 一次分帧序列（每帧 ≤12ms 预算）；长任务台账 | `performance.now()` + `PerformanceObserver` |
| 非 Chromium | Firefox 不白屏、玻璃面非白卡 | `--engine=firefox` |
| 宿主契约 | canvas 位图 == CSS 尺寸；`scrollHeight` 不超基线 | `verify_ui.py` |

### 6.2 新增断言组 `LG-*`
`LG-1` 页 0 console error｜`LG-2` 每宿主恰 1 `.lg-inner` + 1 引擎滤镜｜`LG-3` 材质可见性（纹理留存比 + 面板可见性）｜`LG-4` 主题切换令牌正确翻转（不得白页）｜`LG-5` 降级三态｜`LG-6` 磨砂档强制回归（`--engine=frost`：窗口级 `.lg-inner` = blur16/sat1.6/bri1.03 + 染色 .16，**不是**引擎自带 8px/1.4/1.05）｜`LG-7` Firefox 无白卡｜`LG-8` 动态渲染批次后材质仍在（或可重挂）｜`LG-9` 对比度 ≥4.5｜`LG-10` 背景纹理配方生效（卡外 d11 阈值 + 多层 `background-image` 未被丢弃）

---

## 7. UI 专项

### 7.1 复现路径
1. `venv/Scripts/python -m uvicorn web.app:app --port 8123`（**每轮换端口**，见 memory #93）；
2. 开 `http://127.0.0.1:8123/`，等 `html[data-skin-ready]`；
3. 定位顺序：背景（先关所有卡片看纹理）→ 材质（看 `.lg-inner` 是否存在）→ 旧玻璃让位（宿主 `backdrop-filter` 必须 none）→ 面板染色（`.lg-inner` 的 `background`）→ 内容层 z4；
4. 对照基线：`verify_ui.py` 截图目录 + §3.3 的 `%TEMP%` 证据图。

### 7.2 关键测量点
见 §6.1。补充：`getComputedStyle(host).position`（`static` 会被引擎强制改 `relative`）、`host.clientWidth/Height`（引擎按此建图，**必须已在布局中**）、`documentElement.scrollHeight`。

### 7.3 box-sizing 说明
- 套件自带 `[data-liquid-skin] :is(p,h1,…,ul,dl){margin:0}`（特异性 (0,1,1)），**会压过宿主同权重类规则**（如 `.card-title{margin:…}`）⇒ 卡片内垂直间距可能整体收紧；套件**不提供** `box-sizing` 复位（I9：宿主自己声明，宿主的 `*{box-sizing:border-box}` 保留即可）。
- `.lg-inner` 是 `absolute; inset:0` ⇒ **不参与布局、不改变宿主高度**。若卡片高度变了，来源只可能是 ①多包一层 `.skin-glass-body` 的 margin/line-height，或 ②套件 reset 吃掉了垂直 margin。
- 圆角：套件档位 24/22/16/14/12/10/6；宿主 `--radius-card: 12px`。**圆角只能给宿主**（`data-radius` 在 v1.2.0 不存在），`verify_ui.py:4882-4884` 钉着旧值 ⇒ S0 先改断言。

### 7.4 多尺寸预期
| 视口 | 预期 |
|---|---|
| 1920×1080 | 4 视觉行栅格不变；`scrollHeight` 回到基线 ≤1240 或给出新基线；13 个宿主位图 == 宿主位图（含 DPR 1.25/2） |
| 1440×900（本期主测） | 同 `%TEMP%\rec-full.png`：16px 方格可见、卡片半透但文字清晰 |
| 1280×720 | 不引入横向溢出（`scrollWidth == clientWidth`）；纹理尺度不随视口变化（`background-size` 固定） |
| 375×812 | 侧栏是 `position:fixed` 抽屉 ⇒ **不做玻璃宿主**（I1）；小控件一律 `GLASS_BTN` 参数（`bezelWidth:3, glassThickness:10`，I5） |

---

## 8. 风险与注意事项

| 风险 | 说明 | 对策 |
|---|---|---|
| **R1 背景纹理过密** | 6px 级纹理被 blur 抹平（留存 0.02），换完发现「还是没折射」 | §3.1 物理规则；间距 ≥16px 进验收（`LG-10`） |
| **R2 面板过透** | kit 默认染色 .06 ⇒ 数据密集页发飘、对比度掉 | 面板染色 46%（C4）并进 `LG-9` 对比度断言 |
| **R3 玻璃套玻璃（I7）** | 宿主 `.card/.kpi-card/.topbar` 的 `backdrop-filter` + 白填充不关，材质被盖住（实测卡内留存归零） | S1 统一让位；逐面抽样核对 |
| **R4 动态渲染丢材质** | `app.js` 等重写 `innerHTML`；玻璃节点是 JS 注入子节点 | 只挂**模板内静态壳**；动态区渲染后 `remount()` |
| **R5 令牌冲突** | `--text-muted` 同名；作用域特异性写高就盖掉已修的 WCAG 灰度 | 用 `[data-liquid-skin]`（(0,1,0)）+ 宿主 CSS 最后（C8） |
| **R6 引擎内联样式** | `backdrop-filter`/部分 `box-shadow` 由引擎写内联，仅作者 `!important` 可压 | 引擎产物原样 vendored + 记版本；升级前过 `NOTICE §4` |
| **R7 首帧闪 / 掉帧** | `applyEngineMode()` 晚写会先渲错材质一帧；13 面同步建图 188.8ms | 首帧前内联模块；`scheduleGlass` 分帧；`data-skin-ready` 供验收等待（I13） |
| **R8 浏览器分流** | 折射仅 Chromium；FF/Safari 需磨砂档，否则白卡 | 首帧前写 `data-glass-engine`；不搬克隆折射；FF 实跑进验收 |
| **R9 滚动条冲突** | 宿主已有 Chromium/FF 双路由滚动条（`style.css:150-171`）；套件 `scrollbar-width: thin` 会让 Chromium 忽略全部 `::-webkit-scrollbar` | `mp-skin.css` 显式让位 |
| **R10 背景层夺权** | 宿主 `body` 画环境光；套件画布在 `[data-liquid-skin]`(html) 上 | 实测 body 层胜出 ⇒ 关掉套件画布（`data-bg="solid"` 或覆写） |
| **R11 无障碍回退** | `prefers-reduced-transparency` 把面改成 `color-mix(--surface-opaque 92%)`；令牌没对齐会出现怪色 | `tokens.css` 必须映射 `--surface-opaque`；该档进验收 |
| **R12 新依赖治理** | 首次引入第三方前端产物（98KB JS + 16KB CSS） | vendored + LICENSE + 版本 + 刷新说明；`requirements.txt` 不变 |
| **R13 相邻面位移伪影** | spike 在概览区见到一处白色团块（疑似位移在相邻卡边溢出） | S4 的 M1 专项定位；必要时给宿主 `overflow:hidden` |

---

## 9. 影响范围与规模

- 模板 1 页 + 2 include；CSS 新增 6 文件 + 改 `style.css`；JS 新增 `skin.js` + 改 `app.js`；门禁 2 个脚本。
- 粗略拆分：S0 门禁分类 ≈ 半天；S1 背景 ≈ 半天（含双主题取基线）；S2 接线 ≈ 半天；S3–S4 材质 ≈ 1 天；S5 门禁与文档 ≈ 1 天。**合计 ≈ 4 个工作日**。

---

## 10. 决策记录

| # | 决策 | 状态 |
|---|---|---|
| D-1 | 完整接入引擎（要折射） | ✅ 用户确认 2026-09-23 |
| D-2 | 先做 `/` 一页 | ✅ 用户确认 |
| D-3 | 加纹理 / 换背景 | ✅ 用户确认；配方见 §3.2（16px 方格纸 + 光斑 + 面板染色 46%） |
| D-4 | 门禁：重写视觉数值断言 + 新增 `LG-*` | ✅ 用户确认（「听你的」） |
| D-5 | 引擎 vendored 进仓 | ✅ 用户确认 |
| D-6 | 背景方向：16px 方格纸（α=.06） | ✅ 用户确认 2026-09-23（「都按你的建议来」） |
| D-7 | 面板染色：`color-mix(in srgb, var(--bg-elevated) 46%, transparent)` | ✅ 用户确认 |
| D-8 | 卡片圆角：对齐套件档位 **16px**（宿主 `--radius-card: 12px → 16px`） | ✅ 用户确认 |
| D-9 | `.card.promo` 不上玻璃，保留为「实底」锚点 | ✅ 用户确认 |

> 全部决策已定。**按 S0 → S5 执行**；执行记录写入本目录 `journal.md`。

---

## 11. 执行移交（Executor Brief）

> 需求来源即本文件 §0/§1 + §10 决策表（无单独 `prd.md`；若上游流水线需要，可从 §1 拆出）。
> **只做 `/` 首页一期**，其余 5 页不动。

### 11.1 硬契约（违反即返工）

1. **加载顺序**（`index.html`、`_topbar.html` 所在页头）：
   ```html
   <link rel="stylesheet" href="/static/vendor/liquid-glass/liquid-glass.css?v={{ asset_v }}" />
   <link rel="stylesheet" href="/static/skin/tokens.css?v={{ asset_v }}" />
   <link rel="stylesheet" href="/static/skin/liquid-skin.css?v={{ asset_v }}" />
   <link rel="stylesheet" href="/static/skin/motion.css?v={{ asset_v }}" />
   <link rel="stylesheet" href="/static/style.css?v={{ asset_v }}" />      <!-- 既有，保持在此位置 -->
   <link rel="stylesheet" href="/static/skin/mp-skin.css?v={{ asset_v }}" /><!-- 宿主补丁，最后 -->
   ```
2. **禁改清单**：`web/static/vendor/liquid-glass/liquid-glass.*`（引擎产物原样，不得改写/内联/进 `@layer`）；不得使用 `html[data-skin='liquid']` 作用域（会盖掉 `--text-muted`，见 C8）；小控件不得沿用大面参数（I5）；不得覆盖 `--text-muted`；不得 `git add -A`（自动提交白名单只含 `data/` `context/` `alerts/`）。
3. **作用域**：`<html data-liquid-skin data-theme="{{ light|dark }}">`（令牌与 `data-theme` 同元素，I11）。
4. **引擎入口**：`web/static/skin.js` 用 `type="module"` + **动态 `import('/static/vendor/liquid-glass/liquid-glass.esm.js')`**（不依赖 import map）；`data-glass-engine` 必须在**首帧前**落到 `<html>`：先在页头内联经典脚本用「UA + CSSOM 接受 `url()`」判定写一次，再由 `skin.js` 用引擎 `supportsBackdropFilter()` 复核（不一致时 `console.warn` 并改正）。
5. **材质参数表**（照套件定稿，勿自由发挥）：

   | 面 | 选择器 | bezelWidth / glassThickness | refractiveIndex | blur |
   |---|---|---|---|---|
   | 窗口大面 | `.card`、`.kpi-card` | 20 / 80 | 1.5 | 2.5 |
   | 顶部胶囊 | `.topbar` | 20 / 80 | 1.5 | 4 |
   | 小控件 | 按钮/输入/勾选/开关 | 3 / 10 | 1.5 | 默认 |

   圆角**只能由 CSS 给宿主**（`data-radius` 不存在）；`.card`/`.kpi-card` 统一 16px。
6. **玻璃宿主标记**：`<section class="card skin-glass" data-liquid-glass data-bezel-width="20" data-glass-thickness="80" data-blur="2.5">` + 内容包一层 `<div class="skin-glass-body">`；`.skin-glass-body` 必须抬到 z-index 4（`.lg-inner` 是 z3）。`.card.promo` **不加**这些标记。
7. **背景与面板染色**（写进 `mp-skin.css`，逐字照 §3.2）：16px 方格 `rgba(17,24,39,.06)`（暗色换 `rgba(255,255,255,.06)`）+ 保留 `var(--ambient-1/2)`；面板染色 `color-mix(in srgb, var(--bg-elevated) 46%, transparent)` 落在 `.lg-inner`；宿主旧玻璃让位 `.card,.kpi-card,.topbar{backdrop-filter:none;background:transparent}`（`.promo` 不动）。
8. **重挂载**：只给模板里的静态壳上材质；`app.js` 等 `innerHTML` 重建的容器，渲染后调 `window.mpSkin.remount(container)`（引擎幂等）。

### 11.2 步序与逐步验收

| 步 | 动作 | 验收（必须实际跑） |
|---|---|---|
| S0 | 全量读 `verify_ui.py`，把断言分三堆（结构/契约 = 保留；视觉数值 = 重写；皮肤 = 新增 `LG-*`），并快照现行基线值 | `verify_ui.py` 未改样式时全绿（除已知基线红）；分类清单入 `journal.md` |
| S1 | 背景 + 面板染色 + 旧玻璃让位（只这一项就有可见变化） | 卡外 d11 ≥1.5、纹理留存比 ≥0.4、对比度 ≥4.5、`scrollHeight` 与基线一致；浅/暗各留基线图 |
| S2 | vendored 引擎 + 3 张套件 CSS + `skin.js` + 6 处注册 | 页面 200；`html[data-glass-engine] === 'refract'`；控制台 0 error；**无视觉变化** |
| S3 | `.topbar` + `#trend` 大卡上材质（`scheduleGlass` 分帧） | 每宿主恰 1 `.lg-inner` + 1 引擎滤镜；`.lg-inner` 圆角 == 宿主圆角；单面耗时记账 |
| S4 | 其余 `.card` + 4 个 `.kpi-card`；`app.js` 重挂载；**M1 伪影专项**（相邻卡边位移白团） | `LG-1..LG-10` 全绿 |
| S5 | 重写 `verify_ui.py` 视觉断言 + 落 `verify_skin.py`；更新 `docs/architecture.md`、`docs/frontend-structure.md` | `verify_ui.py` + `verify_skin.py` 双绿；`pytest tests/ -q` 维持既有基线 |

### 11.3 验证命令

```bash
venv/Scripts/python -m pytest tests/ -q
venv/Scripts/python -m uvicorn web.app:app --port 8123          # 每轮换端口（memory #93）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
venv/Scripts/python tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py
venv/Scripts/python tasks/2026-09-23-web-liquid-glass-skin/verify_skin.py --engine=frost
```

### 11.4 完成定义（DoD）

- `/` 首页在 Chromium 下呈真实折射（`LG-3`/`LG-10` 阈值达标），Firefox 走磨砂档且不白屏；
- 13 个宿主分帧挂载、首屏无长任务「迟到感」；动态渲染区材质不丢；
- 浅/暗双主题、降级三态、命中区、对比度全部有断言覆盖且通过；
- 门禁已改为「钉新皮肤」；文档记录了外部皮肤来源/版本/刷新方式与禁改项；
- 未触碰 `src/**`、报告主流程、`data/**`、API 契约；`requirements.txt` 无变化。

### 11.5 已知需要执行期定位的问题

- **M1**：位移伪影（spike 在概览区见到白色团块）。先定位是哪一面的 `.lg-inner` 越界，再在宿主加 `overflow:hidden` 或调整该面的 `bezelWidth/glassThickness`；不得用 `!important` 硬压。
- **M2**：暗色主题的纹理/染色需按 S1 的判据重新取数（本方案数值取自浅色实测）。
- **M3**：`_ASSET_FILES` 若命名成目录（如 `skin/`），要确认 `_asset_version()` 的 mtime 哈希按文件逐个注册（沿用既有两个文件的写法）。
