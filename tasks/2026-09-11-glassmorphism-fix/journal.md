# 执行日志 · 看板玻璃化（Glassmorphism）

> 对应计划：`tasks/2026-09-11-glassmorphism-fix/plan.md`（679 行）
> 执行者：编码 Agent（Phase 3 Step 3.6–3.7）
> 需求方额外提醒：① **G-1 护栏先行**（先加断言、先看它红）② **G-9 三个 `:checked` 坑** ③ 后续任务 `chart-hover-crosshair` 排在本任务之后（共用 `verify_ui.py`）

## 会话记录

### 2026-09-11 · Step G-1 ~ G-10 全部执行

**目标**：让卡片呈现效果图的**低强度玻璃**（背景氛围层 + 半透明面板 + `backdrop-filter` + 冷色亮边 + 极轻托底阴影），**且不回退**上一轮已达成的布局/功能验收。

**执行顺序严格按 plan**：G-1 护栏 → G-2 token → **G-3 氛围层（前置，不可跳过）** → G-4 半透明 → blur 生效 → G-5 数据卡加实 → G-6 顶栏/侧栏 → G-7 promo 关 blur → G-8 降级 → G-9 `index.html` 重排 + 双 tab → G-10 回归收尾。

### G-1 · 护栏先行（基线红 / 护栏绿）

在**既有** `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` 上**只扩展不覆盖**（R25），新增 `GLASS_JS` + `assert_glass()`（断言 1~7 + 1b）、`G9_JS` + `assert_g9()`（G-9），并把测量主题**固定为 dark**（plan §7.2 的「修复前实测」本就是 dark 数值）。

**基线（改 CSS 前）实测 —— 与 plan §6 G-1 预测逐项吻合**：

| 断言 | 基线 | 期望 | |
|---|---|---|---|
| 1 卡片 `backdrop-filter` 全覆盖 | **0/13** | 全站 0 处 → 红 | ✅ |
| 2 `.kpi-card` alpha | **1** | <0.2 → 红 | ✅ |
| 3 数据卡 alpha | **1 / 1 / 1** | 0.6~0.8 → 红 | ✅ |
| 4 `body` 氛围层数 | **0** | ≥2 → 红 | ✅ |
| 5 顶边内高光 alpha | **0.03** | → 红 | ✅ |
| 6 卡片边框 alpha | **1** | → 红 | ✅ |
| 7 外阴影模糊半径 | **8px** | ≥24 → 红 | ✅ |
| 1b promo `backdrop-filter` | **PASS** | 基线即绿（G-4 后的回归护栏，非异常） | ✅ |
| 8~12 布局/溢出/console/抽屉/主题 | **PASS** | 护栏绿 | ✅ |

→ `FAILED: 27 条` = 9 条 × 3 视口，**无一条来自 8~12** —— 证明断言真的在测东西（非恒真/恒假）。
📌 实测卡片数 **13**（10 个 `.card` − promo + 4 个 `.kpi-card`），比 plan 预估的 16~18 个 backdrop 层更少，滚动开销更乐观。

### G-2 ~ G-8 · CSS（`web/static/style.css` 412 → 545 行）

| 步 | 内容 |
|---|---|
| G-2 | 新增 glass token **双主题双套**（数值取 §4.6.2 校准值）：`--glass-bg` / `--glass-bg-strong` / `--glass-border` / `--glass-highlight` / `--glass-blur` / `--glass-shadow` / `--ambient-1` / `--ambient-2`（**8 个**，见偏差 D2）；`--card-glow` / `--card-shadow` 保留为**过渡别名**指向新 token（R21） |
| G-3 | `body` 用 `background-image: var(--ambient-1), var(--ambient-2)` + `background-attachment: fixed`（两层：L1 右上柔光 + L2 斜向光束；L3 斜纹已否决） |
| G-4 | `.card` / `.kpi-card`：`background: var(--glass-bg)` + `border: 1px solid var(--glass-border)` + `box-shadow: var(--glass-shadow), var(--glass-highlight)` + `backdrop-filter/-webkit-backdrop-filter: var(--glass-blur)` |
| G-5 | 数据密集卡 `#overview, #trend, #alerts { background: var(--glass-bg-strong) }`（R17 小字可读） |
| G-6 | `.topbar` 玻璃化（`color-mix(in srgb, var(--bg-primary) 72%, transparent)` + blur + 底边 `--glass-border`）；`#sidebar` **只改透明**（不加 blur，规避 R19/R18）；`#sidebar-theme` 描边统一为 `--glass-border` |
| G-7 | `.card.promo` 显式 `backdrop-filter: none`（视觉保持现状 = **已知视觉妥协**） |
| G-8 | `@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px)))` 降级块：提高 alpha 至近实色 + 去 blur + 顶栏回纯色 |

### G-9 · 行 3 重排 + 板块卡双 tab（`index.html` 185 → 206 行）

- 中卡 `#sectors` → 「市场情绪 & 资金流向」，内含 **3 个子块**：风险偏好 / 资金流向（近5日）/ **市场关系**（4 个 disabled pill，静态）
- 右卡 `#us-sectors` → 「行业板块表现」**纯 CSS 双 tab**（A股 默认激活 / 美股）；A 股表从原中卡**搬入**面板
- 行 4 `.row-news` 由 4 卡降为 **2 卡**（告警 + 资讯）；CSS 改 `1fr 2.4fr`（≥1400px）/ 单列（<1400px）
- 侧栏 nav 只改 1 处文案：「美股板块」→「**板块表现**」
- **`app.js` 一行未改**：`#sector-body` / `#us-sectors-body` / `#fund-flow-body` / `#risk-appetite-body` / `#news-body` 五个 id 全保留；`renderPlaceholders` 对移入的容器 `querySelector('h2')` 返回 null → 被 `if (h)` 守卫跳过，**不报错**（已由「console error = 0」断言证实）
- 三个 `:checked` 坑**写成 CSS 注释钉在规则旁**，并**固化为断言**（见 G-1 扩展）

### 最终验收（`verify_ui.py` 全部实跑）

**玻璃判据**（dark 三视口 + **light 1920** 共 4 组，逐项 PASS）：

| 判据 | 目标 | 实测（三视口一致） |
|---|---|---|
| 1 卡片 `backdrop-filter` 覆盖 | true | **13/13** |
| 1b promo | `none` | **none** |
| 2 `.kpi-card` alpha | <0.2（dark） | **0.035** |
| 3 数据卡 alpha | 0.6~0.8（dark） | **0.66 / 0.66 / 0.66** |
| 4 `body` 氛围层 | ≥2 | **2** |
| 5 内高光白 alpha | dark [0.04,0.15] / light ≥0.85 | **0.07** / **1** |
| 6 边框 alpha | dark [0.15,0.30] / light ≥0.75 | **0.2**（`rgba(155,185,230,0.2)` 冷色亮线）/ **0.92** |
| 7 外阴影模糊 | ≥24px | **40px**（dark）/ 28px（light） |
| G-6 顶栏 / 侧栏 | blur ≠ none / 透明且无 blur | `blur(20px) saturate(1.5)` / `rgba(0,0,0,0)` + `none` |
| G-8 降级块存在 | true | **true**（从 CSSOM 读到 `CSSSupportsRule`） |

**布局/功能回归**（**零回退**）：

| 指标 | 玻璃化前 | 玻璃化后 | G-9 后 |
|---|---|---|---|
| `scrollHeight` @1920 | 1235 | **1235** | **1216** |
| `scrollHeight` @1280 | 1819 | 1819 | **1874**（≤2400 ✓） |
| `scrollHeight` @375 | 2666 | 2666 | 2477 |
| `scrollWidth === innerWidth` | true | true | **true（三视口）** |
| Console error | 0 | 0 | **0** |
| canvas 位图 == 显示尺寸 | true | true | **true** |

**其他**：`pytest tests/ -q` → **459 passed**（本任务无 Python 变更，逐值不变）；G-9 断言全绿（2 列 / 3 子块 / 占位计数 3 / 5 个 id 保留 / 双 tab 分属不同面板 / radio 前置兄弟 / radio 非 `display:none` / nav「板块表现」锚点可达 / 默认 A股 可见 + 切美股 / 切回 A股）。

---

## 与 plan 的偏差（需需求方确认）

| # | 偏差 | 理由 |
|---|---|---|
| **D1** | **G-1 断言 2/3/5/6 改为「分主题区间」**：dark KPI `<0.2`、数据卡 `0.6~0.8`、高光 `[0.04,0.15]`、边框 `[0.15,0.30]`；light `kpi<1.0`、数据卡 `[0.5,1.01]`、高光 `≥0.85`、边框 `≥0.75`；且测量主题**固定 dark** | plan **内部冲突**：§6 G-1 的这四个区间是按 §4.2 早期建议值（且只按 dark）写的，而 §4.6.2「效果图校准值」（plan §12.1 明确「实施以 §4.6.2 为准」）把 dark 改成高光 `.07` / 边框 `.20`、light 改成 `.66/.88/1/.92` → **照原区间实现必然恒 FAIL**（§4.6 只同步改了断言 4）。已在开工前报告需求方并获「按你的提案实现」 |
| **D2** | glass token 定 **8 个**（未定义 `--ambient-3`） | §4.6.1 明确 L3 斜纹「判定为噪声，不加」，氛围层 = L1 + L2 两层；定义第 3 个 ambient token 会成为死代码 |
| **D3** | 新增「右卡面板内表格紧凑化」`#us-sectors .data-table th/td{padding:4px 8px; font-size:12px}` + `.card-head/.tab-labels` margin 收紧；并加 `#sectors .ph-body{min-height:40px}` | plan 未预见的**真实回归**：G-9 后 `.row-3` 由 267 涨到 301 → `scrollHeight` 1272 **顶破 ≤1240 护栏**。用「自然内容高」探针定位到元凶是**右卡默认 A股 tab 里的 4 列表格**（299），非新加的 3 个子块（`#sectors` 仅 246）→ 只对其做紧凑化，196→ 246，总高回到 **1216**（比改前还低 19） |
| **D4** | 同步修改**上一轮遗留断言** `check(m["rowNews"] == 4, "row-news 四列")` → `== 2` | G-9 明确把行 4 改成 2 列；不同步就是"测试假绿"（与本项目 `days=91` 同类教训） |
| **D5** | 实测**美股行业板块只有 5 行**（非 plan 期望的 8 行） | 数据层即 Top5（`fetch_us_sector_heat` 落盘为 5 条，已在上一任务报告 M1）；断言写 `>= 1` 并打印实测 |
| **D6** | `PLACEHOLDERS` 的 `title` 字段对移入卡内的 2 项**不再生效**（未删该字段） | 删除会动 `app.js`，超出玻璃化边界（plan §6 G-9 亦如此处置，仅记一笔） |

## 未实测 / 已知妥协

1. **`@supports` 降级分支未真实触发**：无头 Chromium 恒支持 `backdrop-filter`，无法模拟"不支持"环境；按 plan §6 G-8 允许的方式改用 **CSSOM 断言降级规则存在**（`CSSSupportsRule` + `conditionText` 含 `backdrop-filter`）作为等价验证。降级态的实际观感仍待人工在禁用该特性的浏览器中复核。
2. **promo 卡保持高饱和亮渐变** = 已知视觉妥协（需求方「先不管他」，§4.6.4），与全局玻璃语言不一致；G-7 只做了 `backdrop-filter: none` 省合成层。
3. **玻璃强度未与效果图逐像素比对**（plan R23）：本次数值为 §4.6.2 校准值，建议人工并排复核后微调 `--glass-bg` / `--glass-blur`。
4. **`seed_history*.py` 与本任务无关**；`web/app.py`、`app.js`、`tests/`、`src/*`、生成物**一律未动**。

## 下次注意

- **本任务期间外部 auto-commit cron 仍在抢提交**（本次会话又发生多次）：改动完成后要立刻 `git status` 确认；还原历史文件必须 `git checkout <sha> -- <path>`，不要依赖 `HEAD`（plan R24）。
- `verify_ui.py` 已长到 672 行、承担「布局 + 数据 + 玻璃 + G-9」四类断言，仍是**单一事实来源**；下一个任务 `chart-hover-crosshair`（悬停横线）**共用同一脚本**，请**继续只扩展不覆盖**（R25），并按需求方要求排在本任务之后。
- 新增 CSS 断言时要**显式固定主题**（本次用 `add_init_script` 写 `localStorage`），否则浏览器默认 light 会让按 dark 设计的 alpha 区间产生假失败。
