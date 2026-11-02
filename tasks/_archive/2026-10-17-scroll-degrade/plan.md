# 2026-10-17 · 修 Chromium 首页滚动掉帧（滚动期降级钩子失效）

## 目标
用户报：Chrome/Edge 打开首页「卡、掉帧」，Firefox 正常。

## 诊断（实测数据，有头 Edge，真实滚动手势）
| 配置 | 中位帧间隔 | >50ms 帧占比 | 滚动期计算值 |
|---|---|---|---|
| refract（现状） | 69–104ms | 73% | `url("#lg-1")` |
| refract + 降级真的生效 | **6.9–7ms** | 1% | `blur(12px) saturate(1.4)` |
| frost（强制） | 6.9ms | 0% | `blur(16px) …` |
| 无皮肤 | 6.9ms | 0% | — |

三条根因（缺一条都不成立）：
1. `skin.js` 用引擎的 `supportsBackdropFilter()`（`!!window.chrome && CSSOM 接受 url()`）选引擎 ⇒ **Chromium 恒走 refract**（SVG 位移滤镜，12 个玻璃面滚动时逐帧重滤）；Firefox 恒走 frost ⇒ 只有 Chrome/Edge 卡。
2. 套件的滚动降级规则 `html.is-scrolling [data-liquid-skin] .lg-inner` 把 `data-liquid-skin` 当**后代**，而宿主把它挂在 `<html>` 上 ⇒ **该规则永不匹配**（实测：`is-scrolling` 已置位、计算值仍是 `url("#lg-N")`）。
3. `skin.js` 的 `scroll` 监听在**气泡阶段**，而视口 `scroll` 事件在 `document` 上派发、不冒泡 ⇒ **真实滚动时一次都不触发**（实测：捕获 206 次 / 气泡 0 次；合成 `dispatchEvent` 会触发，极易误判）。

## 改动（2 文件）
- `web/static/skin/mp-skin.css`：新增 §8 —— 宿主版降级规则 `html.is-scrolling[data-liquid-skin] .lg-inner { backdrop-filter: blur(var(--lg-tune-degrade-blur, 12px)) saturate(140%) !important }`，外加 `@media (prefers-reduced-transparency: no-preference)` 守卫（本选择器比套件的无障碍兜底更具体，不守卫会在滚动期压掉「减少透明」偏好）。
- `web/static/skin.js`：`bindScrollDegrade` 的监听改 `{ passive: true, capture: true }`，并**排除元素级滚动**（`e.target !== document && e.target !== document.scrollingElement` 即 return）——资讯/告警卡的无缝滚动每秒 60 次 `scrollTop` 会派发元素级 scroll，不排除会让玻璃永久降级（实测：中位帧间隔反而 1006ms）。

## 验证
- 新回路 `verify_scroll_degrade.py`：**ALL PASSED**（D1 静止保留折射 / D2 滚动降级 / D2b 覆盖率 91% / D3 中位 7ms、>50ms 占 1% / D4 只跑跑马灯不降级 / D5 零 pageerror）。
- `verify_skin.py --headed`、`verify_ui.py`、`pytest`：见 journal §4。
- 线上（`--url https://123.60.176.219:8443/`）：见 journal §5。

## 非目标
- 不改引擎（vendored 禁改写）、不改 frost/refract 的选择策略（用户明确选 B：保留静止时的折射）。
- 跑马灯 60fps → 16fps 的步进优化：本次不做（用户未选）。
