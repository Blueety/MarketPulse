# 计划：最新资讯自动循环滚动（向上匀速 + 悬停暂停 + 保留手动滚动）

- **日期**：2026-09-13
- **任务目录**：`tasks/2026-09-13-news-autoscroll/`
- **性质**：纯前端（`app.js` + `style.css`），后端零改动
- **关联任务**：`tasks/2026-09-13-rss-macro-news`（RSS 双源，**未执行**）—— 见 §7 串行约束

---

## 1. 任务目标

给「最新资讯」卡片加入**自动循环滚动**，让内容不足时不滚、充足时匀速向上滚动并无缝循环。

**已确认的决策（需求方 2026-09-13）**：

| 项 | 决策 |
|---|---|
| 方向 | **向上移动**（第一条从顶部开始，逐条上移，新条目从底部进入）—— 新闻滚动条标准做法 |
| 运动方式 | **匀速连续滚动**（像跑马灯，不停顿） |
| 手动滚动 | **保留**——悬停时暂停且可用滚轮/拖动翻阅，离开后继续 |
| 长句阅读 | 依赖**悬停暂停**（需求方已知悉匀速滚 + 120 字长句的取舍） |

---

## 2. 现状（代码已较上次变更，以实测为准）

```css
/* style.css:420 */
#news-body { max-height: 132px; overflow-y: auto; }

/* style.css:422-435 */
.news-item { padding: 7px 0; border-bottom: 1px solid var(--border); }
.news-item:last-child { border-bottom: none; }
.news-item a {
  display: block; font-size: 13px; font-weight: 400;
  white-space: nowrap; overflow-x: auto; overflow-y: hidden;   /* ← 每行本身可横向滚动 */
}
.news-item a::-webkit-scrollbar { height: 4px; }

/* style.css:439-441 —— <768px 改完整换行 */
@media (max-width: 768px) {
  .news-item a { white-space: normal; overflow-x: visible; overflow-y: visible; }
}
```

```js
/* app.js:337 */
var NEWS_MAX_LEN = 120;   // 已从 42 提到 120，不再用省略号，放不下就横滚
```

**关键事实**：
- `#news-body` 的 `max-height: 132px` 与 `.alert-list` 对齐，是 `scrollHeight ≤1240` 护栏的保障（`style.css:417-419` 注释明确标注为「**必需项**」）。
- 现有 `prefers-reduced-motion: reduce` **全局**规则（`style.css:649-651`）会关掉一切 animation/transition。
- 已有自定义细滚动条覆盖 `#news-body`（`style.css:140-141`）。

---

## 3. 核心设计决策：为什么用 `scrollTop` 而不是 CSS `transform`

**这是本方案最关键的一步。**

| 方案 | 做法 | 问题 |
|---|---|---|
| A. CSS `@keyframes` + `translateY` | 内层 track 平移，容器 `overflow: hidden` | ① 与「保留手动滚动」**机制冲突**：手动滚改 `scrollTop`、动画改 `transform`，叠加后内容跳变；② 容器改 `overflow:hidden` 后**手动滚动彻底没了**；③ `reduce-motion` 关掉动画后**后面的条目永远看不到**（严重无障碍缺陷） |
| **B（选）`scrollTop` + `requestAnimationFrame`** | JS 每帧递增 `scrollTop` | 手动滚动与自动滚动**是同一个机制** → 零冲突；悬停暂停 = 停递增；`reduce-motion` 直接不启动 → 天然退化为纯手动滚动 |

**选型：B。** 它让三个已确认的决策（向上 / 匀速连续 / 保留手动滚动）**互不打架**，而 A 方案三者只能取二。

### 3.1 无缝循环

内容渲染 **两遍**（第二遍 `aria-hidden="true"`，避免屏幕阅读器读重复）：

```text
A B C D E F G H | A B C D E F G H
└─ 第一半 ─┘     └─ 克隆半 ─┘
```

`scrollTop` 递增到「第一半的高度」时，**减去该高度**（不是归零，避免累积误差）：

```text
if (el.scrollTop >= half) el.scrollTop -= half;
```

因为克隆半与第一半像素级相同，减完的视觉内容与减之前一致 → **无缝**。

### 3.2 `:last-child` 分隔线的处理

`.news-item:last-child { border-bottom: none }` 在双份内容下会失效（`last-child` 变成克隆半的最后一条）。**这条规则应删除**：滚动容器里「最后一条」没有意义，且循环点 `H → A` 之间**需要**一条分隔线才连贯。

---

## 4. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| `web/static/app.js` | 改 `renderNews` | 渲染双份内容 + 启动/停止滚动循环 |
| `web/static/app.js` | 新增约 40 行 | `startNewsAutoScroll()` / `stopNewsAutoScroll()` |
| `web/static/style.css` | 改 2 处 | 删 `.news-item:last-child` 规则；`reduce-motion` 块内显式保障手动滚动 |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 扩展约 20 行 | 断言 A-1~A-6 |
| `tasks/2026-09-13-news-autoscroll/plan.md` / `journal.md` | 新增 | 本文件 / 执行记录 |
| `docs/pitfalls.md` | 追加 | 2 条 |

**不改**：`web/app.py`、`src/*`、`daily_report.py`、`#news-body` 的 `max-height`、`.news-item a` 的横滚设置。

---

## 5. 实现步骤（每步可独立验证）

### A-0 · 基线（必测，不要用历史数字）

⚠️ 上一轮 `scrollH@1920 = 1220` 是**在 `frontend-polish`（chg-pill + 骨架屏 + `NEWS_MAX_LEN=120`）之前**测的，**已失效**。必须重新测：

```text
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
→ 记录当前 scrollH@1920 / .row-news / #alerts / #news 高度 / console error
```

### A-1 · `renderNews` 渲染双份内容

```text
function renderNews(payload) {
  stopNewsAutoScroll();                       // ★ 先停旧循环（防重复 rAF）
  var body = document.getElementById('news-body');
  ...
  var html = items.map(itemHtml).join('');
  body.innerHTML = html +                                   // 第一半
    '<div aria-hidden="true" class="news-clone">' + html + '</div>';  // 克隆半
  body.scrollTop = 0;
  startNewsAutoScroll();                      // 内容不足一屏时内部自行不启动
}
```

⚠️ **克隆半必须 `aria-hidden="true"`** —— 否则屏幕阅读器会把每条读两遍。
⚠️ 克隆半用**同一个 itemHtml**，保证像素级一致（否则循环点会跳）。

### A-2 · 滚动循环

```text
var NEWS_SCROLL_PX_PER_SEC = 16;              // 可调：见 §5.3
var _newsRaf = 0, _newsLast = 0, _newsHalf = 0, _newsPaused = false;

function startNewsAutoScroll() {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;   // ★ 无障碍：不启动
  var el = document.getElementById('news-body');
  if (!el) return;
  _newsHalf = el.scrollHeight / 2;            // 双份 → 半程即一个完整循环
  if (_newsHalf <= el.clientHeight) return;   // ★ 内容不足一屏 → 不滚（否则原地抖动）
  _newsLast = performance.now();
  _newsRaf = requestAnimationFrame(step);
}

function step(now) {
  var dt = (now - _newsLast) / 1000;
  _newsLast = now;
  var el = document.getElementById('news-body');
  if (!el) return stopNewsAutoScroll();
  if (!_newsPaused) {
    el.scrollTop += NEWS_SCROLL_PX_PER_SEC * dt;
    if (el.scrollTop >= _newsHalf) el.scrollTop -= _newsHalf;   // ★ 减半程而非归零
  }
  _newsRaf = requestAnimationFrame(step);
}
```

### A-3 · 暂停 / 恢复 / 清理

| 事件 | 动作 | 理由 |
|---|---|---|
| `mouseenter` | `_newsPaused = true` | 悬停暂停，用户可横滚/翻阅 |
| `mouseleave` | 记录 `_newsLast = performance.now()`；`_newsPaused = false` | **必须重置时间戳**，否则暂停期间的 `dt` 会在恢复瞬间产生大跳 |
| `focusin` / `focusout` | 同 hover | 键盘 Tab 到链接时暂停（无障碍） |
| `visibilitychange`（`document.hidden`） | 暂停 rAF | 后台标签页不空转 CPU |
| 重新渲染 | `cancelAnimationFrame` + 重置全部状态 | 防多个 rAF 叠加（**最易出的 bug**） |

### A-4 · `style.css` 两处改动

```text
/* 1) 删除这条：双份内容下 last-child 语义失效，且循环点 H→A 需要分隔线 */
/* .news-item:last-child { border-bottom: none; }  ← 删掉 */

/* 2) reduce-motion 块内**显式**保障手动滚动仍可用
      （动画已被全局规则关掉，但必须保证内容能手动翻到） */
@media (prefers-reduced-motion: reduce) {
  #news-body { overflow-y: auto !important; }
}
```

⚠️ 第 2 条是**必需项**：若将来有人把 `#news-body` 改成 `overflow: hidden`（比如误抄 A 方案），没有这条兜底，`reduce-motion` 用户**后面的条目就永远看不到了**。

### A-5 · 速度调参

`NEWS_SCROLL_PX_PER_SEC = 16` 是**待实测调参值**，不是定论：

- 行高约 34px（`padding 7+7` + 13px 文本）
- 16px/s → 单行通过约 2.1 秒；8 条约 17 秒一轮
- 匀速滚 + 120 字长句**本质上读不完**（需求方已知悉，靠悬停暂停）
- 验收时**目视**：能在不停顿的情况下大致扫到关键词即可；太快就降到 10~12，太慢提到 20

### A-6 · 断言（追加到 `verify_ui.py`，**只扩展不覆盖**）

| # | 断言 | 期望 |
|---|---|---|
| **A-1** | `#news-body` 的 `scrollHeight > clientHeight` 时，`scrollTop` 在 1.5s 内**有增长** | 增大 |
| **A-2** | 内容不足一屏（`scrollHeight/2 <= clientHeight`）时 `scrollTop` **恒为 0** | 0 |
| **A-3** | `#news-body` 的 `offsetHeight` **=== 132**（或与 `.alert-list` 等高） | ≤132，且改前后不变 |
| **A-4** | 双份内容：`.news-item` 数 === 接口 `items` 数 × 2；克隆半 `aria-hidden="true"` | true |
| **A-5** | 模拟 `mouseenter` 后 0.5s，`scrollTop` **不变** | 不变（暂停生效）|
| **A-6** | **回归**：`scrollH@1920 ≤1240`、`scrollWidth === innerWidth`、console error 0、backdrop 11/11 | 全部成立 |
| **A-7** | 循环无跳变：`scrollTop` 越过半程后**单调递增且无负值**（采样 40 帧） | true |

⚠️ **先红后绿**：改动前先跑，A-1/A-4/A-5/A-7 必须是红的。
⚠️ Playwright 里鼠标悬停用 `page.hover('#news-body')`；`prefers-reduced-motion` 用 `browser.new_context(reduced_motion='reduce')` 另起一个 context 验证 A-2 退化为纯手动滚动。

### A-7 · 记录

- `tasks/2026-09-13-news-autoscroll/journal.md`：最终速度值 + A-0 基线数字 + 目视结论。
- `docs/pitfalls.md` 追加：
  1. **自动滚动与手动滚动必须共用同一机制**：`transform` 动画 + `overflow:auto` 手动滚会互相打架，且 `reduce-motion` 关掉动画后内容不可达。用 `scrollTop` 驱动可同时满足三者。
  2. **`requestAnimationFrame` 必须成对清理**：重渲染不 `cancelAnimationFrame` 会叠加多个循环，表现为**速度逐次变快**。

---

## 6. 复现路径与关键测量点（UI 类必填）

### 6.1 复现路径

1. `cd d:/AGENT/MarketPulse`
2. `venv\Scripts\python -m uvicorn web.app:app --port 8020`（**换新端口**，防 CSS 缓存假阴性 —— `docs/pitfalls.md:200`）
3. 打开 `http://127.0.0.1:8020/`，硬刷新 `Ctrl+Shift+R`
4. 滚到底部 → 右侧「最新资讯」卡
5. **现状可观察**：列表静止；只有手动滚动；内容多时需自己拖
6. **目标**：进入页面后内容自动向上匀速滚动并循环；鼠标移上去立刻停住，可自由滚动翻阅；移开继续

### 6.2 关键测量点

| 测量点 | 取法 | 目标 |
|---|---|---|
| `#news-body` 的 `offsetHeight` | DOM | **≤132 且与改动前一致**（护栏保障） |
| `#news-body` 的 `scrollTop` 随时间变化 | 间隔 300ms 采样 5 次 | 单调递增（自动滚动生效） |
| `#news-body` 的 `scrollHeight` / `clientHeight` | DOM | 前者 > 后者（否则说明内容不足一屏，不应滚动） |
| `.news-item` 总数 / 半程元素数 | DOM | **= 接口条数 × 2** |
| 克隆半的 `aria-hidden` | DOM 属性 | `"true"` |
| hover 后 `scrollTop` 变化量 | `page.hover('#news-body')` 后采样 | **≈ 0** |
| `scrollTop` 越过半程时刻的值 | 采样 | **不出现负数、不出现突降**（不应跳到 0 附近以外）|
| **回归：`scrollH@1920`** | `document.documentElement.scrollHeight` | **≤1240** |
| **回归：`scrollWidth === innerWidth`** | — | true |
| **回归：console error** | — | **0** |

> ⚠️ **架构师未实测声明**：本任务的滚动**动画效果**（速度是否合适、循环点是否肉眼可见跳变）**必须人工目视确认**，Playwright 断言只能证明"在动、没跳错、高度没变"，**证明不了"看起来顺不顺"**。执行者须实际盯 10 秒以上。

### 6.3 box-sizing 说明

`web/static/style.css:51` 全局 `* { box-sizing: border-box }`，无例外。

1. **本任务完全不改盒模型** —— `scrollTop` 是滚动偏移，不参与 `width/height/padding/border` 计算 → **不改变任何尺寸**，`scrollHeight ≤1240` 护栏天然安全。
2. **双份内容不会撑高容器**：`#news-body` 有 `max-height: 132px` + `overflow-y: auto` → 内容再多容器高度恒 ≤132px。
3. **`scrollHeight / 2` 的可靠性**：`.news-item` 用 `padding: 7px 0`（border-box 下垂直 padding 计入自身高度），双份内容高度严格 2 倍，故半程 = `scrollHeight / 2` 成立。⚠️ 但 `.news-item a` 若出现**水平滚动条**（4px 高），它会占高度且**只在第一半/克隆半各出现一次**，理论上仍对称 —— 执行者需实测 `scrollHeight` 是否为偶数、除以 2 后是否正好落在条目边界。
4. **别给 `#news-body` 加 padding**：border-box 下 `max-height` 含 padding，加了会压缩可视区，且破坏与 `.alert-list` 的等高。
5. **`.news-item:last-child` 删除后**：最后一条会多出 1px 下边框，使 `scrollHeight` 增加 1px、双份不再严格对称 → **半程计算需用「第一半实测高度」，不要用 `scrollHeight/2`**。→ 见下方修正。

> ⚠️ **对 §5 A-2 的修正（重要）**：由于最后一条会带 1px 边框，`scrollHeight/2` 可能差 1px。实现时**优先用第一半元素的实测高度**：
> ```text
> _newsHalf = 前 N 个 .news-item 的 offsetHeight 之和
> ```
> （N = 接口条数）。这样与 `:last-child` 规则是否删除无关，更稳。

### 6.4 多尺寸验收

| 尺寸 | 预期 |
|---|---|
| **1920×1080** | `#news-body` 高 132px；内容 >132px 时匀速向上滚动并无缝循环；悬停立即停住、可拖滚；`#news` 与 `#alerts` 仍等高；**`scrollH ≤1240`** |
| **1280×720** | `.row-news` 单列堆叠（<1400 断点）；`#news` 全宽，单行更长 → 横滚更少；自动滚动同样生效；`scrollWidth === 1280` |
| **375×812** | `<768px` 已改**完整换行**（`.news-item a` 无横滚）→ 无「横滚 vs 竖滚」冲突；行高变高，滚动仍连续；无横向溢出 |
| **`prefers-reduced-motion: reduce`** | **不启动自动滚动**；`scrollTop` 恒为 0；**手动滚动可用**（A-2 + A-4 断言）；内容全部可达 |
| **双主题** | 无新增颜色 token；滚动条沿用现有细滚动条主题色 |

---

## 7. 与其他任务的串行约束

| 任务 | 状态 | 关系 |
|---|---|---|
| `2026-09-13-rss-macro-news`（RSS 双源） | **未执行** | 它改**后端取数**（`rss_fetcher` + `daily_report.py`），本任务改**前端渲染**，**区域不重叠**。但两者都会改变「资讯条数」→ 建议**先做 RSS、再做本任务**，这样 A-0 基线测的就是最终条数 |
| 其他前端任务 | — | 本任务只动 `#news-body` 与 `renderNews`，无已知冲突 |

⚠️ 本任务改 `renderNews` 的 **DOM 结构**（新增克隆半）。若 RSS 任务执行时也想动该函数，**必须串行并在本任务之后**。

---

## 8. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **`rAF` 未清理导致叠加 → 速度越来越快** | **高** | 每次渲染先 `cancelAnimationFrame` + 重置状态；A-1 采样验证 |
| **R2** | **`reduce-motion` 下内容不可达** | **高** | JS 不启动 + CSS 显式 `overflow-y: auto`；单独 context 验证（A-2） |
| **R3** | 循环点肉眼可见跳变 | **中** | 克隆半与第一半用**同一份 HTML**；半程用实测高度；目视盯 10s |
| **R4** | 半程计算差 1px（`:last-child` 边框） | **中** | §6.3 修正：用第一半实测高度，不用 `scrollHeight/2` |
| **R5** | 悬停恢复瞬间大跳 | **中** | `mouseleave` 时重置 `_newsLast`；A-5 验证 |
| **R6** | 内容不足一屏仍滚动 → 原地抖动 | **中** | 启动前判 `half <= clientHeight` 则 return；A-2 验证 |
| **R7** | 横滚 vs 竖滚操作冲突 | **中** | 悬停暂停是核心解法；<768px 已无横滚 |
| **R8** | 屏幕阅读器重复朗读 | **中** | 克隆半 `aria-hidden="true"`；A-4 断言 |
| **R9** | 速度不合适（太快读不了 / 太慢没感觉） | **中** | `NEWS_SCROLL_PX_PER_SEC` 常量可调；验收目视 |
| **R10** | 滚动条持续移动造成视觉干扰 | **低** | 沿用现有 4~6px 细滚动条；若干扰大可后续隐藏 |
| **R11** | 后台标签页空转 CPU | **低** | `visibilitychange` 暂停 |
| **R12** | 改 `#news-body` 高度破坏 `scrollH ≤1240` 护栏 | **低** | 本任务不改高度；A-3/A-6 断言 |

---

## 9. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 修改 | `web/static/app.js` | +约 50 / −4 行（`renderNews` 改造 + 滚动循环） |
| 修改 | `web/static/style.css` | +约 4 / −1 行 |
| 修改（扩展） | `verify_ui.py` | +约 30 行（A-1~A-7） |
| 新增 | `tasks/2026-09-13-news-autoscroll/plan.md` / `journal.md` | 本文件 / 执行记录 |
| 追加 | `docs/pitfalls.md` | 2 条 |

**净代码变更估算**：约 **+84 / −5 行**（不含断言）。

---

## 10. 不做什么

- **不用 CSS `transform` 动画**（与「保留手动滚动」及 `reduce-motion` 三者不能共存，见 §3）。
- 不改 `#news-body` 的 `max-height: 132px`（护栏保障）。
- 不改 `.news-item a` 的行内横滚设置。
- 不动后端 / 数据链路 / 玻璃化 / 栅格 / 断点。
- 不加「暂停/播放」按钮（悬停暂停已覆盖；如后需再加）。
- 不改 120 字上限。

---

## 11. 确认

- [ ] 已确认**用 `scrollTop` + `rAF` 驱动**，不用 CSS `transform`（§3，这是三条决策共存的前提）
- [ ] 已确认循环用**减半程**而非归零（§3.1）
- [ ] 已确认克隆半**必须 `aria-hidden="true"`**（R8）
- [ ] 已确认 **`reduce-motion` 下必须保留手动滚动**（R2/A-4，否则内容不可达）
- [ ] 已知悉 **A-0 基线需重测**（旧数字 1220 在 `frontend-polish` 前已失效）
- [ ] 已确认速度 16px/s 是**待调参值**，需目视定稿
- [ ] 已确认动画顺畅度**只能人工目视**，断言证明不了
- [ ] 已确认与 `rss-macro-news` 的先后顺序（建议 RSS 先做）
