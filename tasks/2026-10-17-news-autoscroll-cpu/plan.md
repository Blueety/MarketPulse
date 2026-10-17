# 2026-10-17 资讯/告警无缝滚动在「窗口失焦」时烧 CPU

## 目标

用户报「用 Edge 开着看板特别卡」。定位到：**「最新资讯」那条无缝滚动**（`app.js` 的 `makeAutoScroller`：
`requestAnimationFrame` + 每帧写 `scrollTop`，16px/s）在**窗口可见但未聚焦**时仍以 60fps 跑，
空闲时持续吃掉 **~12–15% 单核（主线程 5.7%）**。Firefox 会把后台窗口的 rAF 压到 ~1fps ⇒ 只有 Chromium/Edge 卡。

## 涉及文件

- `web/static/app.js`（唯一改动文件，`makeAutoScroller` 内 ~10 行）

## 实测证据（有头真 Edge，页面空闲、不动鼠标）

| 配置 | 全进程 CPU | 主线程 | 资讯卡 6s 位移 |
|---|---|---|---|
| 原样（聚焦） | 12.1% | 5.7% | 滚动中 |
| **载入后把 `requestAnimationFrame` 停掉** | **−0.3% ≈ 0** | **0.0%** | 0 |
| 拦掉玻璃皮肤 | 18.9% | 6.0% | 滚动中 |

⇒ 空闲开销几乎全在滚动循环（皮肤是次要项）。排除项：Edge **0 扩展**、硬件加速开启；
9 分钟 soak（反复刷新+切 tab）DOM/`.lg-inner`/`<svg filter>`/堆/图表实例**全部持平** ⇒ 不是泄漏。

## 实施

1. `st.focused`（初值 `document.hasFocus()`，之后由 `window` 的 `focus`/`blur` 维护）。
2. `step()` 里 `!st.focused || document.hidden` ⇒ **把 rAF 本身停掉**（`st.raf = 0`，不再排下一帧）。
   ⚠️ 只「跳过推进」不够：实测 CPU 仍有 **~8%** —— 挂着的 rAF 会让浏览器一直保持 60fps 活跃（合成器不 idle）。
3. `focus` / `visibilitychange(可见)` ⇒ `st.last` 重置 + `syncFromEl()` 对齐 + `if (!st.raf) start()` 重启。
4. 悬停暂停（`st.paused`）、reduce-motion 不启动等既有语义不动。

## 验证

```bash
venv/Scripts/python %TEMP%/mprepro/focus_pause3.py        # 本地服务 + 有头 Edge：① 聚焦滚动 ② blur 停 ③ focus 恢复
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py   # 既有门禁（含 autoscroll 断言）
```

结果：① 6s 位移 **96px** / CPU **15.3%**；② blur ⇒ 位移 **0** / CPU **0.3%**；③ focus ⇒ 恢复滚动（位移 −172.8 = 跨周期回绕）/ CPU 14.8%。

档位: T2 — 1 文件 / 0 调用方 / 无视觉变化 / 有既有门禁 / ~12 行
