# Journal · 2026-10-17 修 Chromium 首页滚动掉帧

## 1. 目标与结论
用户报：**Chrome / Edge 打开首页「卡、掉帧」，Firefox 正常**。

结论：**液态玻璃的 refract 引擎在页面滚动时逐帧重滤 12 个玻璃面，把 Chromium 压到 ~10fps**；
而套件里本该兜住它的「滚动期降级」在本应用里**两条钩子都失效**（CSS 选择器不匹配 + JS 监听挂错阶段）。
修好后滚动中位帧间隔 **69.5ms → 7ms**，静止时**折射照旧保留**。

## 2. 诊断（有头 Edge + 真实滚动手势；帧统计只取「真实滚动窗口」）
| 配置 | 中位帧间隔 | >50ms 帧 | 滚动期 `.lg-inner` 计算值 |
|---|---|---|---|
| refract（修前） | 69–104ms | 73% | `url("#lg-1")` |
| refract + 降级生效 | **7ms** | **1%** | `blur(12px) saturate(1.4)` |
| frost（强制） | 6.9ms | 0% | `blur(16px) …` |
| 无皮肤 | 6.9ms | 0% | — |

三条根因：
1. **引擎选择**：`skin.js` 用引擎的 `supportsBackdropFilter()`（`!!window.chrome && CSSOM 接受 url()`）⇒ **Chromium 恒走 refract**（`backdrop-filter: url(#lg-N)` = SVG `feDisplacementMap`）；Firefox 拿不到 `window.chrome` ⇒ 恒走 frost（普通 blur，便宜）⇒ 「只有 Chrome/Edge 卡」。
2. **套件的降级规则永不匹配**：`html.is-scrolling [data-liquid-skin] .lg-inner` 把 `data-liquid-skin` 当**后代**，而宿主把它挂在 `<html>` 上（套件文档要求同元素）⇒ 实测 `is-scrolling` 已置位、计算值仍是 `url("#lg-N")`。
3. **`skin.js` 的监听挂错阶段**：视口 `scroll` 事件在 `document` 上派发、**不冒泡** ⇒ 气泡阶段 0 次触发（捕获阶段实测 206 次）；`window.dispatchEvent(new Event('scroll'))` 会触发 ⇒ 合成事件让人误判「监听已生效」。

## 3. 改动（2 文件）
- `web/static/skin/mp-skin.css`：新增 §8 宿主版降级规则（`html.is-scrolling[data-liquid-skin] .lg-inner` + `!important`），外包 `@media (prefers-reduced-transparency: no-preference)` 守卫（补丁选择器比套件的无障碍兜底更具体，不守卫会压掉「减少透明」偏好）。
- `web/static/skin.js`：`bindScrollDegrade` 监听改 `{ passive: true, capture: true }`，并**排除元素级滚动**（`e.target !== document && e.target !== document.scrollingElement` 即 return）—— 不排除时资讯/告警卡跑马灯每秒 60 次 `scrollTop` 会把玻璃**永久降级**（实测中位帧间隔反而 1006ms）。

## 4. 验证
| 门禁 | 结果 |
|---|---|
| 新回路 `tasks/2026-10-17-scroll-degrade/verify_scroll_degrade.py`（本地） | **ALL PASSED** —— D1 静止保留折射 ✓ / D2 滚动降级成 blur ✓ / D2b 降级覆盖率 **91%** ✓ / D3a 中位 **7ms** ✓ / D3b >50ms 帧 **1%** ✓ / D4 只跑跑马灯不降级 ✓ / D5 零 pageerror ✓ |
| `verify_skin.py --headed` | **61 PASSED / 2 SKIPPED**（exit 0；两条 SKIP 是既有条件项） |
| `verify_ui.py` | **ALL PASSED (10 SKIPPED)**（SKIP 全是上游 macro/econ 不可用） |
| `pytest tests/ -q` | **869 passed** |
| 闸门 B | `grep "\[DEBUG-"` 无输出；`git status` 只有本次预期文件 |

## 5. 线上
- 提交 `e4eb545` 推送后由 ECS 的 5 分钟 timer 自动 `git pull`（无需重启；静态资源按请求读、`?v=` 取 `_ASSET_FILES` 最大 mtime）。
- 线上验收（`verify_scroll_degrade.py --url https://123.60.176.219:8443/`）：**ALL PASSED** —— 中位帧间隔 **7ms**、>50ms 帧 **0%**、降级覆盖率 **91%**、静止时 `url("#lg-1")` 保留、零 pageerror。线上 `skin.js` / `mp-skin.css` 与本地逐字节一致（**比对前须归一化 CRLF**：仓库工作区是 CRLF、ECS checkout 是 LF，直接比 sha256 会假红）。

## 7. 下次注意
- 套件的 CSS 选择器是按「`data-liquid-skin` 挂在容器上」写的，**本应用挂在 `<html>`** ⇒ 凡涉及 `[data-liquid-skin]` 作**后代**的规则都要在 `mp-skin.css` 里补一条（本次只补了滚动降级这一条；其余同类规则尚未逐条审计）。
- 给 `window` 加 `scroll` 监听必须用 **capture**，且必须**排除元素级滚动**（本站有两处每秒 60 次的程序化 `scrollTop` 写入）。
- 帧率类指标的统计窗口要以「首个/末个视口 `scroll` 事件」为边界，否则数字完全失真（本次踩了 3 次）。
- 无 ADR：改动是一个选择器 + 一个事件选项，易撤销、无真实取舍。

## 8. 追加：默认引擎改 frost（用户拍板 A 方案，同日）

修完滚动降级后用户改选 **A**：Chromium 也一律走 frost（永久放弃折射，换取"任何情况下都不重滤 SVG 位移滤镜"）。
落地：
- `web/static/skin.js`：`const real = forced === 'refract' ? 'refract' : 'frost'`（refract 仅显式强制时启用）。
- `web/templates/index.html`：首帧前落定 `data-glass-engine` 的内联脚本同步改成只认显式强制
  （其余 5 页不挂皮肤，无此脚本 —— 皮肤仅首页，见文件头）。
- 连带修一个**切到 frost 才暴露的既有无障碍缺陷**：套件 `prefers-reduced-transparency: reduce` 的
  `backdrop-filter: none !important` 被引擎注入的 CSS 压掉（实测 computed 仍是 `blur(16px)…`，只有 background 生效；
  refract 档下它反而生效 ⇒ 该冲突只在 frost 档可见，`verify_skin.py` 的 LG-5c 就是这条）。
  改为在 `skin.js` 里用**内联 + `!important`**（层叠最高优先级）写 `none`，并把引擎原值存 WeakMap、关闭偏好时原样还回
  （还回时**不带** `!important`，否则会压过滚动降级那条规则）。

**验证**：`pytest` **877 passed**（+8 例）· `verify_skin.py --engine=frost` **64 PASSED / 1 SKIPPED**（LG-5c 转绿）·
`verify_skin.py --engine=refract` **61 PASSED / 2 SKIPPED**（折射回归覆盖保留）· 滚动降级回路 **ALL PASSED**（中位 6.9ms）。
