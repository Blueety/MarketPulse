# MarketPulse 玻璃参数落地（方案 H：光斑 + 细纹理）· 实施计划

> 架构师产出。**只提供规格，不含完整实现代码**；代码由执行者编写。
> 参数来自实测标定（`tasks/2026-09-11-glassmorphism-fix/probe_texture.py`），非估算。

---

## 0. 前置说明

| 项 | 说明 |
|---|---|
| 触发 | 需求方 2026-09-12 在强度对照（A/B/F/G/H）中选定 **H · G + 细纹理** |
| 任务关系 | 上一个任务 `tasks/2026-09-11-glassmorphism-fix/` 已完成并验收（独立复跑 `ALL PASSED`）；本任务是**参数调优**，独立于它 |
| 产出依据 | `make_strength_cmp.py`（视觉三轴对照）+ `probe_texture.py`（纹理标定）+ 像素差分判定 |
| 改动范围 | **`web/static/style.css`** + `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`（断言必须同步，否则假绿，见 R3） |

### 0.1 为什么必须标定（H 的原参数不可直接落地）

方案 H 的第一版纹理是 `rgba(255,255,255,.022)`、周期 6px，且位于 `--ambient-1` 的**最后一层（最底）**。实测问题有两个：

1. **几乎不可见**：G vs H 差分仅 **3.1% 像素 >1、最大 6 个色阶** → 视觉上基本等于 G，加了等于没加。
2. **被上层衰减**：纹理在最底层，上面 3 层渐变按 `(1-α)` 逐层衰减（光斑最亮处衰减到约 52%）→ 标称 `.022` 实际只剩约一半。

**标定数据**（纯背景窄条取样，`.main` 右内边距 x1892–1914，无内容、只受氛围+纹理影响；**单调且可复现**）：

| 纹理 alpha | 条带 stddev | 扫描线**峰谷差** | 背景均值 |
|---|---|---|---|
| 无纹理 | 0.331 | **1** | 11.8 |
| .022 | 1.222 | **6** | 12.5 |
| .045 | 2.247 | **11** | 13.1 |
| **.055** | 2.896 | **13** | 13.4 |
| .070 | 3.597 | **17** | 13.9 |

→ **取值 `.05`（峰谷差约 12）**：明显可辨，又不至于"脏"。`.022` 不可见、`.070` 偏脏。

### 0.2 一个被证实的好消息（验证 H 的前提成立）

纹理在**卡片内部**的高频振幅约为 **0.00**，在**卡片外背景**的振幅为 5.0~5.4。
→ 即：背景有细纹、玻璃内被 `backdrop-filter` 糊平。这正是**磨砂玻璃的正确表现**，也说明「给 blur 一个作用对象」这个前提是成立的（blur 确实在做事：它把纹路抹掉了）。H 的选型有依据。

---

## 1. 任务目标

**Goal**

把已选中的方案 H 落地为最终 CSS 参数：强光斑氛围（保留） + 细纹理（**提到最上层**并调至 alpha `.05`） + 面板/模糊维持现状，并对齐验收断言。

**一句话验收标准**

`body` 的 `background-image` **共 4 层**、其中**第一段（最上层）是 `repeating-linear-gradient`**；纯背景窄条纹理峰谷差 **≈12**；`scrollHeight` @1920×1080 仍 **≤1240**；既有 12 条玻璃断言与全量回归仍全绿。

**必须保持（回归护栏）**

| 指标 | 当前实测 | 本任务要求 |
|---|---|---|
| `scrollHeight` @1920 | **1216** | ≤1240（不变） |
| `scrollWidth === innerWidth`（三视口） | 1920/1280/375 | 仍成立 |
| backdrop 全覆盖 | 11 / 11 | 仍为 11 / 11 |
| Console error | 0 | 0 |
| `--glass-bg` / `--glass-bg-strong` / `--glass-blur` / `--glass-border` | .035 / .66 / blur(20px) saturate(150%) / .20 | **不变**（H 就是在这套强度上加纹理） |
| `.card.promo` `backdrop-filter` | `none` | 仍为 `none` |
| 12px 小字可读性（数据卡 `--glass-bg-strong` .66） | 达标 | 不变 |

**Out of Scope**

- 不改 `--glass-bg` / `--glass-bg-strong` / `--glass-blur` / 边框 / 内高光 / 阴影（本任务只动**氛围层**）。
- 不动 `app.js` / `index.html` / `web/app.py` / `tests/` / `src/` / 生成物。
- 不加新依赖、不加二进制资源。
- 不改 light 主题（本轮只调 dark；如要同步，见 §9 R4）。

---

## 2. 现状基线（已实现，来自上一任务）

| 事实 | 值 |
|---|---|
| `--ambient-1` | `radial-gradient(1200px 820px at 78% -8%, rgba(150,190,255,.14), transparent 62%), linear-gradient(148deg, transparent 18%, rgba(120,160,220,.07) 40%, transparent 64%)` |
| `--ambient-2` | 同上的第二层（两点分布：L1 + L2） |
| `body` 背景 | `background-color: var(--bg-primary)` + `background-image: var(--ambient-1), var(--ambient-2)` + `background-repeat: no-repeat` + `background-attachment: fixed` |
| `bodyLayers`（验收实测） | **2** |
| `@supports` 降级块 | 在位，`hasFallbackRule === true` |

---

## 3. 方案

### 3.1 最终参数（dark 档）

**保持 `body` 现有写法不动**（`style.css:79`：`background-image: var(--ambient-1), var(--ambient-2);`）。
`var()` 是**文本替换**，`--ambient-2` 可以承载一个**逗号分隔的多层列表**。因此只改两个变量即可：

```text
--ambient-1: repeating-linear-gradient(115deg, rgba(255,255,255,.05) 0 1px, rgba(255,255,255,0) 1px 6px)
             ← 纹理单独放一个变量 → 展开后在最前 = 最上层

--ambient-2: radial-gradient(760px 520px at 28% 10%, rgba(150,200,255,.32), transparent 58%),
             radial-gradient(820px 560px at 80% 26%, rgba(140,185,255,.18), transparent 60%),
             linear-gradient(148deg, transparent 18%, rgba(120,160,220,.07) 40%, transparent 64%)
             ← 一个变量承载 3 层（逗号分隔），合法
```

替换后展开为 `background-image: <纹理>, <radial>, <radial>, <linear>` = **4 层，纹理在最上** ✅

> ⚠️ **不要把 `--ambient-2` 设成 `none`**：`background-image: <层1>, none` 是**非法值**（`none` 不能作为多层背景列表中的一层），会让**整条声明被丢弃** → 背景全丢、页面变纯黑/纯白。
> 要"去掉某一层"就把该层从列表里**删掉**，而不是写成 `none`。

**为什么纹理必须在最上层**：`background-image` 列表里**写在最前面的层画在最上面**。放最底层会被上面 3 层按 `(1-α)` 衰减（实测只剩约 52%），alpha 再怎么调都事倍功半。

**为什么第 3 光斑从 `74% 34%` 移到 `80% 26%`**：原位置（x≈1421, y≈367）落在**趋势卡绘图区右缘**内，实测该处背景由 `(22,31,43)` 抬到 `(29,44,66)`，蓝色序列线（`#66A8E0` = (102,168,224)）对比被削弱。上移右移后离开绘图区，同时保留右上亮度。

### 3.2 可调旋钮（后续自行微调时按此顺序）

| 旋钮 | 当前 | 效果 | 备注 |
|---|---|---|---|
| 纹理 alpha | `.05` | 峰谷差 ≈12 | 想要"更糙"→ `.07`；想"更隐"→ `.03` |
| 纹理周期 | `6px` | 条纹间距 | 改 `4px` 更密（更脏）、`8px` 更疏 |
| 光斑 peak alpha | `.32` | 玻璃"透光"强度 | 主杠杆；但过高会让数据卡泛蓝 |
| `--glass-bg` | `.035` | 面板实度 | 若要更强可提到 `.05~.06`（**不要到 .12**，会变成"灰卡片"而非玻璃） |

---

## 4. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/static/style.css` | **改** | `:root`（light）与 `[data-theme="dark"]` 两处的 `--ambient-1` / `--ambient-2` 按 §3.1 重写。**只动氛围层**，其余 token 不动 |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **改（扩展，禁止覆盖）** | 见 §5 Step T-3：新增/更新 3 条断言 |

---

## 5. 实施步骤（每步可独立验证）

### Step T-1 · 先跑一次现有脚本（护栏基线）

`venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` → 应 **EXIT=0、ALL PASSED**。
（若不是，先修复再开始，否则无法判断本任务的增量影响。）

### Step T-2 · 改 `style.css` 的氛围层

- 按 §3.1 重写 dark 档的 `--ambient-1`（4 层、纹理最上），`--ambient-2` 置 `none`。
- light 档：若暂不调，保持现状即可（见 §9 R4）。
- **验证**：目视背景出现细斜纹；卡片内部纹路被糊平（磨砂感）。

### Step T-3 · 同步验收断言（**不做就是假绿**）

在 `verify_ui.py` 的 `assert_glass`（或等价位置）新增/更新：

| # | 断言 | 目标 |
|---|---|---|
| T-1 | `body` 背景层数 | **== 4** |
| T-2 | `body` 背景**第一段**（最上层）是纹理：`backgroundImage.split(...)[0]` 匹配 `/repeating-linear-gradient/` | true ← **这条专门防"纹理放错层"** |
| T-3 | 纹理 alpha：解析该段的 alpha | `0.03 ~ 0.07` |
| T-4 | 回归：`scrollHeight` @1920×1080 | ≤1240 |
| T-5 | 回归：控制台 error、无横向溢出、backdrop 11/11 | 不变 |

⚠️ 原断言「`bodyLayers >= 2`」在加纹理后**仍然通过**（4 ≥ 2）—— 它**测不出纹理是否加上**，所以必须新增 T-1/T-2/T-3，否则纹理被漏加/放错层都不会被发现（正是 R3「不同步就是假绿」的同类问题）。

- **验证**：先跑一次，T-1~T-3 应 **FAIL**（证明断言在测东西），改完 CSS 后应 **PASS**。

### Step T-4 · 全量回归 + 收尾

- `verify_ui.py` **EXIT=0**；`venv/Scripts/python -m pytest tests/ -v` 全绿。
- 三视口目视（§7）。
- 追加 `docs/pitfalls.md`：**纹理层序（最上 vs 最下）决定实际振幅**；**背景层数断言用 `>=N` 测不出新增层**。
- 写 `tasks/2026-09-12-glass-texture-tuning/journal.md`。

---

## 6. 复现路径、测量点与坐标空间说明

### 6.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8040`（**每次换新端口**；或直接跑 `verify_ui.py`，它自动挑空闲端口）
3. 打开 `http://127.0.0.1:8040/`，硬刷新 `Ctrl+Shift+R`。
4. 观察：页面背景（尤其卡片之间的缝隙、右侧内边距）应能看见**极细斜纹**；卡片内部应**平滑无纹路**（被 `backdrop-filter` 糊平）；右上与 KPI 行有柔光。
5. 逐项核对 §6.2 的测量点。

### 6.2 关键测量点

| 测量点 | 取法 | 目标 |
|---|---|---|
| `body` 背景层数 | `getComputedStyle(body).backgroundImage` 中 `gradient(` 计数 | **4** |
| **纹理是否最上层** | 背景列表**第一段**匹配 `repeating-linear-gradient` | **true** |
| 纹理 alpha | 解析第一段中的 alpha | **0.03~0.07** |
| 纹理实际可见幅度 | 纯背景窄条（x1892–1914, y120–1100）扫描线**峰谷差** | **≈12**（无纹理时为 1） |
| 卡内是否糊平 | 卡片内部区域（`--glass-bg` 卡片空白处）高频残差 stddev | **≈0**（对比背景的 5.0+） |
| 光斑是否避开绘图区 | 采样趋势卡绘图区右缘（原 x≈1421, y≈367）背景色 | 蓝通道不宜显著高于 `(22,31,43)` 基线太多 |
| `scrollHeight` @1920 | `scrollingElement.scrollHeight` | **≤1240**（当前 1216） |
| 无横向溢出 | `scrollWidth === innerWidth`（三视口） | true |

### 6.3 坐标空间说明（canvas/背景版的 "box-sizing"）

- **`background-image` 层序 = 数组顺序，写在最前面的画在最上面**（与 `z-index` 直觉相反）。这是本任务最易错的一点，也是 T-2 断言存在的理由。
- **`background-attachment: fixed`** 下，渐变的位置百分比相对**视口**而非元素 → 光斑会随窗口尺寸改变相对位置，但**不随滚动移动**（这正是"玻璃扫过背景"的来源，保持不动）。
- 渐变尺寸统一用 **px**（不用 %）→ 小视口下仍能覆盖内容区，避免 §7 中"卡片落在纯色区"的问题。
- 本任务不改 `canvas.width/height`，也不改任何盒模型属性 → 既有 `.card` 的 `box-sizing: border-box`、圆角、padding 全部不变，`scrollHeight` 不应因本任务变化。

---

## 7. 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | 背景可见细斜纹；两处光斑（KPI 行、右上）营造局部对比；卡片内纹路被糊平 → 磨砂玻璃感；`scrollHeight ≤1240`；`.row-kpi` 5 列、`.row-3` 3 列不变 |
| **1280×720** | 纹理与光斑仍覆盖内容区（用 px 尺寸）；`.row-news` 仍单列堆叠；`scrollWidth === 1280` |
| **375×812** | 单列；纹理不产生横向条纹噪音；`scrollWidth === 375` |
| **双主题** | dark 按本规格；light 若未同步则维持现状（§9 R4），但**不得**因 dark 改动而失效 |
| **DPR=2** | 人工复核：纹理在 DPR=2 下不得变成明显摩尔纹（1px 线在高 DPR 下可能被缩放成 2px） |

---

## 8. 验证命令

```bash
# 【主验收】自动挑空闲端口 + 三视口 + 退出码 0/1
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

# 纹理标定（本任务参数来源，可复跑）
venv/Scripts/python -m uvicorn web.app:app --port 8040
venv/Scripts/python tasks/2026-09-11-glassmorphism-fix/probe_texture.py --port 8040

# 视觉三轴对照（如需重新选型）
venv/Scripts/python tasks/2026-09-11-glassmorphism-fix/make_strength_cmp.py --port 8040

# 回归
venv/Scripts/python -m pytest tests/ -v
```

---

## 9. 风险与注意事项

| # | 风险 | 等级 | 说明与对策 |
|---|---|---|---|
| **R1** | **纹理放错层（最底）** | **高** | 会被上层渐变衰减约 48%，alpha 再高也打折扣。对策：T-2 断言（背景第一段必须是纹理） |
| **R2** | 断言不同步 → 假绿 | **高** | 原 `bodyLayers >= 2` 在加纹理后仍通过，测不出纹理是否加上。必须新增 T-1~T-3 |
| **R3** | 纹理过强 → 背景"脏" | 中 | `.070` 峰谷差 17 已偏脏；落地取 `.05`（≈12）。若目视嫌脏，降到 `.03~.04` |
| **R4** | light 主题未同步 | 中 | 本任务只调 dark。light 下若纹理 alpha 用同一值，在浅底（`#F7F8FA`）上**几乎看不见**（白线叠白底）→ 若后续要 light 也有纹理，应改用**深色**细线（如 `rgba(17,24,39,.05)`），不要复用 dark 的白色 |
| **R5** | 光斑污染图表可读性 | 中 | 原 `74% 34%` 落在绘图区右缘，蓝色序列线对比下降。已移到 `80% 26%`；落地后**目视确认 `#66A8E0` 蓝线仍清晰** |
| **R6** | DPR=2 下纹理变粗/摩尔纹 | 低 | 1px 线在高 DPR 下可能渲染为 2px。需 DPR=2 人工复核 |
| **R7** | 纹理在 SSR/老浏览器 | 低 | `repeating-linear-gradient` 支持广泛；且 `@supports` 降级块已把 `--glass-blur` 置 `none`，纹理仍会显示（无害） |
| **R8** | **把某个 `--ambient-*` 设成 `none` 会让背景全丢** | **高** | `background-image: var(--ambient-1), var(--ambient-2)` 中任一变量为 `none` → 展开成 `<层>, none`，属**非法值**，**整条 `background-image` 声明被丢弃**（不是只丢那一层）→ 页面背景全无。这与 R21（CSS 变量未定义使整条声明 invalid）是同一类失效模式。**要去掉某层就从列表里删除它** |

---

## 10. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `web/static/style.css` | 改 **2 处**（dark 的 `--ambient-1` / `--ambient-2`；light 可选） |
| 修改（扩展） | `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | +约 12 行（T-1~T-5 断言） |
| 新增 | `tasks/2026-09-12-glass-texture-tuning/plan.md` | 本文件 |
| 新增 | `tasks/2026-09-12-glass-texture-tuning/journal.md` | 执行完成后写 |
| 新增 | `docs/pitfalls.md` 追加段 | 2 条（层序 / `>=N` 断言测不出新增层） |

**净代码变更估算**：约 **+16 / −4 行**，集中在 CSS 变量赋值与断言。

---

## 11. 不做什么

- 不改 `--glass-bg` / `--glass-bg-strong` / `--glass-blur` / `--glass-border` / `--glass-highlight` / `--glass-shadow`。
- 不动 `app.js`、`index.html`、`web/app.py`、`tests/`。
- 不改布局（栅格/高度/断点）。
- 不加新依赖、不加图片资源。
- 不重做 `@supports` 降级（已存在，且属结构性不可测，记为接受风险）。

---

## 12. 确认

- [ ] 人已审阅本规格
- [ ] 已确认纹理 alpha **`.05` / 周期 6px**，且**置于 `background-image` 最上层**
- [ ] 已确认只改**氛围层**，其余 glass token 不动
- [ ] 已确认 3 条新断言（T-1~T-3）必须加，且先红后绿
- [ ] 已确认光斑从 `74% 34%` 移到 `80% 26%` 以避让趋势卡绘图区
- [ ] 已确认本任务**不动** `app.js` / `index.html`
- [ ] 已确认 `verify_ui.py` **只扩展、不覆盖**
- [ ] 已确认回归护栏（`scrollHeight ≤1240`、无横向溢出、0 console error）不得回退
