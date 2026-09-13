# 执行日志 · 最新资讯自动循环滚动

> 对应计划：`tasks/2026-09-13-news-autoscroll/plan.md`（344 行）
> 执行者：编码 Agent（Phase 3 Step 3.6–3.7）
> 执行顺序：A-0 基线 → A-6 断言先写（**先红**）→ A-1~A-4 实现 → 后绿 → A-5 目视（见「未做项」）→ A-7 记录

## A-0 · 基线（plan 要求重测，已实测）

```
verify_ui.py → ALL PASSED / failures=[]
1920×1080  scrollH = 1220   .row-news 195   #news 195   #alerts 195
1280×720   scrollH = 1935
375×812    scrollH = 2539
```
（plan 担心 `frontend-polish` 后基线已变；实测**未变**，仍 1220。）

前置：`2026-09-13-rss-macro-news` **已先执行**（plan §7 要求的先后顺序）→ 基线测到的就是最终条数（8 条）。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/static/app.js` | +69 / −1 | `renderNews` 改为渲染**双份**（克隆半 `aria-hidden="true"`）；新增 `NEWS_SCROLL_PX_PER_SEC` / `stopNewsAutoScroll` / `_newsStep` / `startNewsAutoScroll` / `_bindNewsHover` |
| `web/static/style.css` | +3 / −1 | 删 `.news-item:last-child { border-bottom: none }`；`@media (prefers-reduced-motion: reduce)` 内新增 `#news-body { overflow-y: auto !important }` |
| `verify_ui.py` | +约 220 行 | 新增 `AUTOSCROLL_JS` / `SAMPLE_JS` / `WRAP_JS` / `HALVES_JS` / `RATE_JS` + `assert_news_autoscroll` / `assert_news_reduced_motion` / `assert_news_short_content`；**修正既有 N-1 取样口径**（见下） |
| `docs/pitfalls.md` | +5 条 | 见 A-7 |
| `tasks/2026-09-13-news-autoscroll/journal.md` | 新增 | 本文件 |

**未改**：`web/app.py`、`src/*`、`#news-body` 的 `max-height`、`.news-item a` 的横滚设置。

## A-6 · 先红（改动前的实测）

断言先写好再跑，**6 条红**：

```
FAIL  A-4  .news-item 数 == 接口条数 × 2   (actual=(8, 8, 0))
FAIL  A-4b 克隆半 aria-hidden=true
FAIL  A-3b #news-body 与 .alert-list 等高  (actual=(132, 195))   ← 断言本身写错，见偏差 D1
FAIL  A-1  内容超一屏 → scrollTop 递增     (actual=[0, 0, 0, 0, 0])
FAIL  A-5  悬停暂停                        (actual=(False, 0, 0))
FAIL  A-7b 采样期间持续前进                (actual=(130, 130))
```
A-3（高度 ≤132）/A-6（回归）/A-2（reduce-motion）在改动前即为绿 —— 它们是**护栏**而非红项。

## 实现要点（与 plan 的对应）

- **A-1**：`body.innerHTML = html + '<div class="news-clone" aria-hidden="true">' + html + '</div>'`（同一份 `html` 字符串 → 像素级一致）。
- **A-2**：`startNewsAutoScroll()` 先判 `prefers-reduced-motion`（是则 return）；半程用**第一半元素的实测高度**（`Σ items[i].offsetHeight`）而非 `scrollHeight/2`（plan §6.3 修正，规避末条 1px 边框的不对称）；`half <= clientHeight` 则 return（不足一屏不滚）。
- **A-3**：`mouseenter/focusin` → `_newsPaused = true`；`mouseleave/focusout` → 恢复**并重置 `_newsLast`**（防暂停期间 dt 大跳）；`visibilitychange` 后台暂停；`renderNews` 开头 `stopNewsAutoScroll()`（`cancelAnimationFrame` + 重置状态，防 rAF 叠加）。
- **A-4**：删 `:last-child` 规则；reduce-motion 块内显式 `#news-body { overflow-y: auto !important }`。

## 后绿 · 关键实测数字

```
api=8  dom=16  clone=8  hidden=true   bodyH=132  client=132  scroll=542
自动滚动采样: [40, 43, 48, 52]  moved=True
循环采样    half=272  first=2  last=36  drops=[269]
实测速率    15.84 px/s（常量 16）
三个视口 scrollH = 1220 / 1935 / 2539（与 A-0 逐项一致）
```

| 断言 | 目标 | 实测 |
|---|---|---|
| A-4 DOM 数 == 接口 × 2 | 16 == 8×2 | **16 / 8 / clone 8** |
| A-4b 克隆半 aria-hidden | true | **true** |
| A-3 #news-body 高 | ≤132 且 max-height=132px | **132 / 132px** |
| A-3b 超限时钳在 132px（双份不撑高） | ==132 | **132** |
| A-3c #news 与 #alerts 等高 | ±2px | **195 == 195** |
| A-1 自动滚动生效 | 递增 | **[40,43,48,52]** |
| A-5 悬停暂停 | 滚动中 → 0.6s 不变 | **moved=True 且 Δ=0** |
| A-5b 移开不产生大跳 | <200px | ✅ |
| A-7a 无负值 / A-7c 只回绕一次 / A-7d 幅度≈半程 | — | **drops=[269]，half=272** |
| A-7b 回绕后继续前进 | 前进 | **wrapIdx 命中，post 增长** |
| A-7e 两半逐条一致（文本+高度） | 0 不一致 | **0**（回绕无缝的客观代理） |
| A-5c 实测速率 | ≥8px/s | **15.84 px/s** |
| A-2a/2b reduce-motion | overflow-y:auto + scrollTop 恒 0 | **auto / 0** |
| A-2'a/2'b 内容不足一屏（1 条） | scrollHeight ≤ client 且 scrollTop 恒 0 | **68 ≤ 132 / 0** |
| A-6 回归 | scrollH ≤1240 / 无横溢 / console 0 | **1220 / true / 0** |

## A-5 · 速度定稿（**未做目视，需需求方确认**）

plan §A-5/§6.2 明确「速度是否合适、循环点是否肉眼可见跳变**必须人工目视**，Playwright 断言证明不了」。**本机不具备图像/视觉判断能力**（`docs/pitfalls.md` 已记：本机未配视觉模型，`inspect_image` 报 "does not support image input"），因此**这一项我没有执行**，请需求方目视定稿。

可提供的量化代理（替代不了观感，但可缩小范围）：
- `NEWS_SCROLL_PX_PER_SEC = 16`，**实测 15.84 px/s**；单条 ≈34px（`half=272` ÷ 8 条）→ **约 2.1s 过一条、约 17s 一轮**。
- **回绕无缝**：A-7e 逐条比对「首半 vs 克隆半」的 `textContent` 与 `offsetHeight`，**0 处不一致**；回绕幅度 269 ≈ 半程 272（`-half` 语义正确）→ 回绕点在数学与内容两个层面都等价于同一画面。
- 若目视觉得偏快 → 把 `NEWS_SCROLL_PX_PER_SEC` 降到 10~12；偏慢 → 提到 20（plan §A-5）。

## 遇到的问题

1. **既有 N-1 被双份渲染打破**：`N-1 DOM .news-item 数 == /api/news items 数 (actual=(16, 8))`。这是本任务的**预期连带**（plan 未预见）。处置：把 `NEWS_JS` 的取样限定为**第一半**（用 `clone.contains(el)` 过滤），保持 N-1 原意「接口返回的条目都渲染了」；克隆半的数量/`aria-hidden` 由新增 A-4 覆盖。
2. **并行跑 pytest 与 verify_ui 会互相造成假失败**：本轮同时跑时 `test_phase9::test_us_png_generated` 失败（图表 `MARKET_CHART_TIMEOUT=5s` 在 CPU 争用下超时），且 A-7b 因帧间隔被拉到 ~0.125s 而假红。**串行复跑**：`pytest tests/test_phase9.py` → **13 passed**、`pytest tests/` → **548 passed**、verify_ui → **ALL PASSED**。
3. **采样器自纠**：`WRAP_JS` 初版「一检测到回绕就 resolve」，只采到 `[270, 2]` 两点 → 无法观测回绕后的前进 → A-7b 假红。改为**回绕后再多采 10 帧**。
4. **A-3b 断言自纠**：初版拿 `#news-body`（内层滚动容器 132）比 `#alerts`（整张卡 195），是苹果比橘子。改为「超限时恰好钳在 132px」+ 新增 A-3c 比两张**卡**（`#news` vs `#alerts`）。

## 与 plan 的偏差

| # | 项 | 说明 |
|---|---|---|
| **D1** | A-3b 断言重定义 | plan §6.2 写「`offsetHeight`===132 或与 `.alert-list` 等高」，字面比 `#alerts` 卡片是错的（内层容器 vs 外层卡）。改为「超限时钳 132」+ A-3c 比两卡等高。 |
| **D2** | 新增 A-2'（短内容） | plan A-2 只给了「内容不足一屏 `scrollTop` 恒 0」的判据，但正常数据下该分支永不执行（8 条远超一屏）。用 `page.route` 伪造 1 条响应 + 独立 context 真实覆盖（R6）。 |
| **D3** | 新增 A-7e / A-5c | plan 未要求；作为「回绕无缝」与「速度」的**客观代理**（因为 A-5 目视无法在本机执行）。 |
| **D4** | 修正 N-1 取样口径 | 双份渲染的必然连带（plan 未预见）。 |
| **D5** | A-5 目视**未执行** | 本机无视觉能力；已在上面「A-5 速度定稿」写明并请需求方确认。 |
| **D6** | `_newsStep` 增加 `dt` 钳制 0.5s | plan 未提；防「后台标签页切回 / 长间隔」时一次跳很远。 |

## A-7 · 记录

- 本 journal；`docs/pitfalls.md` 追加「模块 web/（资讯自动滚动 2026-09-13）」5 条。
- 未提交（按纪律等需求方确认）。

## 追加修复 · 用户反馈「我感觉卡卡的，他滚动的时候」（2026-09-13）

### 取证路径（不靠推理）

| 探针 | 目的 | 结论 |
|---|---|---|
| `probe_scroll_smoothness.py` | rAF 间隔 + CDP `Performance.getMetrics` | rAF 仅 ~10fps；但 `TaskDuration` 32ms/3s、`LayoutCount 0`、`ScriptDuration 3ms` → **主线程空闲**，瓶颈在绘制/合成 |
| `probe_frame_rate.py` | 区分「环境节流」与「页面慢」 | 同一次启动：`about:blank` **61fps** vs 真实页面 **9.2fps** → 不是环境节流，是**页面自身** |
| `probe_dt.py` | 逐帧原始轨迹 | 帧间隔恒 ~100ms；`scrollTop` 每次跳 **2px**；无 `dt<=0` 早退 → 循环是活的，但**步进是整数跳变** |
| `probe_ab2.py`（修正指标后） | 逐层 A/B | 见下表 |
| `probe_old_impl.py` | 同增量下的新旧实现对照 | **旧实现 60 帧后仍为 0；新实现 24** |

**修正了一处自己的指标错误**：上一版 A/B 把「最后一帧增量」当成净增量（`dScrollTop`），导致误读为「注入样式后不滚」。改测净增量后结论自洽。

### 根因 A（已修）· `el.scrollTop += 增量` 是「自吞噬」的

该容器 `el.scrollTop` **读回来是整数**。于是：

```text
每帧：读回被取整的位置 → 加上小数增量 → 又落回整数 → 小数部分每帧被抹掉
```

- **60fps 时**：16px/s ÷ 60 = **0.27px/帧** → 永远停在原地 → **看起来完全不动**（实测 `all_blur_off` 相位：`raf` 每 2s +120（循环在跑）但 `netScrollTop = 0`）
- **10fps 时**：16px/s ÷ 10 = 1.6px/帧 → 取整成 **2px 一格一跳**（实测轨迹 `[6,8,10,12,13,13,15,17,19,21]`）→ **观感卡顿**

**页内反证**（同一速率 0.4px/帧 × 60 帧，应走 24px）：

| 实现 | 60 帧后 `scrollTop` | 前 10 帧 |
|---|---|---|
| 旧：`el.scrollTop += 0.4` | **0（完全不动）** | `[0,0,0,0,0,0,0,0,0,0]` |
| 新：`_newsPos += 0.4; el.scrollTop = _newsPos` | **24** ✓ | `[0,1,1,2,2,2,3,3,4,4]` |

**修复**：新增浮点累加器 `_newsPos`（只在实际赋值时交给浏览器取整）；`startNewsAutoScroll` / `mouseleave` / `focusout` / `visibilitychange` 恢复时用 `_newsSyncFromEl()` 把累加器对齐到真实位置（防用户手动滚后被「跳回去」）。

**新增回归断言 A-5d**：把 `NEWS_SCROLL_PX_PER_SEC` 降到 4px/s（≈0.4px/帧，复现旧实现的冻结条件）→ 2.2s 后 `scrollTop = 9`（期望 8.8）✓。旧实现下该断言必红。

### 根因 B（已量化，**本次未修**）· 滚动重绘带动全页 backdrop-filter 重合成

A/B（修复后重测，各相位速率一致 ≈16px/s，因此 fps 可比）：

| 相位 | fps | 结论 |
|---|---|---|
| baseline（滚动中） | **8.8** | 基线 |
| 仅关 `#news` 的 backdrop-filter | 8.6 | ❌ 无效 |
| **关全部 backdrop-filter** | **60.5** | ✅ 有效 |
| `body` 背景渐变关 | 8.3 | ❌ 无效 |
| `#news-body { will-change: scroll-position }` | 8.6 | ❌ 无效 |
| `#news { contain: paint }` | 9.1 | ❌ 无效 |
| `#news { transform: translateZ(0) }` | 8.6 | ❌ 无效 |
| **停掉自动滚动（对照）** | **59.4** | 页面在「不重绘」时是 60fps |

→ 机制：**只要页面发生一次滚动重绘，11 张玻璃卡的 backdrop-filter 就要重合成一遍**；在**软件光栅**（无头无 GPU）下这一步约 90ms/帧。

⚠️ **必须说明的取证缺口**：以上 fps 是**无头 + 软件光栅**下测的，**不能直接外推到你的真实浏览器**（GPU 合成下 blur 通常便宜得多）。我在此环境**没有** GPU 加速的浏览器，**也没有**图像/观感判断能力，因此：
- 根因 A 是**与环境无关的代码 bug**，已修且有反证 → 你看到的「卡」很可能主要来自它（60fps 下刚好落在「完全冻结/偶发跳一格」的最差区间）。
- 根因 B 的量级**需要你在真实浏览器里复测**。若仍卡，可试的**已预先验证过方向**的缓解项：降低 `--glass-blur` 半径（全局一处 token）、或让滚动卡片 `#news` 退出玻璃层（单独关它=实测无效，需连带动其它卡才有用，取舍要你定）。

### 验证

```
verify_ui.py → ALL PASSED（含 A-5d；实测速率 15.30 px/s）
pytest tests/ -q → 548 passed
```

## 下次注意

- **叠加型动效先问「手动操作要不要保留」**：要保留就必须与手动共用同一机制（`scrollTop`），`transform` 动画与 `overflow:auto` 天然打架。
- **`requestAnimationFrame` 必须成对清理**：重渲染不 `cancelAnimationFrame` → 多个循环叠加 → **速度逐次变快**（最易出的 bug）。
- **「某东西不动」类断言必须与「它本来在动」配对**，否则在功能缺失时恒真（假绿）。
- **并行跑重型验证脚本会制造假失败**（本机实测：pytest + Playwright 同跑 → 图表 5s 限时超时 + rAF 采样被拉长）。**验证一律串行**。
- 采样类断言要**按时间**取样（不是按帧数），否则帧率高时采到「几乎没动」。
