# Journal · 2026-10-17 资讯无缝滚动在窗口失焦时烧 CPU

## 1. 目标与结论

用户报「用 Edge 开着看板特别卡」。**结论：是本站自己的无缝滚动**（`web/static/app.js` 的 `makeAutoScroller`，
`requestAnimationFrame` + 每帧写 `scrollTop`）在**窗口可见但未聚焦**时仍以 60fps 运行，
空闲时持续吃掉 **~12–15% 单核 / 主线程 5.7%**；窗口失焦后停掉 rAF ⇒ **0.3%**。

为什么「火狐不卡、Edge 卡」：该循环只处理了 `document.hidden`（标签切走才停），**没处理窗口失焦**；
Chromium 在这种情况下仍按 60fps 跑 rAF，Firefox 会把后台窗口的 rAF 压到 ~1fps。

## 2. 改动文件

- `web/static/app.js`：`makeAutoScroller` 内 ~12 行（`st.focused` + `step()` 停 rAF + `focus`/`visibilitychange` 重启）。
- 新增 `tasks/2026-10-17-news-autoscroll-cpu/{plan.md,journal.md}`；`docs/pitfalls.md` 增一节。

## 3. 验证结果

- 本地服务 + 有头真 Edge（`%TEMP%/mprepro/focus_pause3.py`，6s 窗口）：

  | 状态 | 资讯卡位移 | 全进程 CPU |
  |---|---|---|
  | ① 聚焦 | 96.0px（16px/s） | 15.3% |
  | ② `window blur` | **0.0** | **0.3%** |
  | ③ `window focus` | 恢复（−172.8 = 跨周期回绕） | 14.8% |

- 空闲 CPU 对照（同一探针，有头 Edge）：原样 12.1% / **杀掉 rAF 后 −0.3%≈0** / 拦掉玻璃皮肤 18.9%
  ⇒ 开销几乎全在滚动循环，皮肤是次要项。
- 排除项：Edge **0 扩展**、硬件加速**开启**；9 分钟 soak（反复点刷新 + 切趋势 tab）DOM 节点 884–886、
  `.lg-inner`/`.lg-clone`/`<svg filter>` 恒 12、堆 5–11MB 无趋势、图表实例恒 1 ⇒ **不是泄漏**。
- 既有门禁：`verify_ui.py`（含 news autoscroll 的速率断言）⇒ **ALL PASSED (10 SKIPPED)**。

## 3b. 推送与上线

- 提交 `bc18835`。**推送一度被网络挡住**：`github.com:443` 间歇不可达（IPv4 21s 超时、IPv6 立即失败；DNS 正常解析到 20.205.243.166），
  第 4 次重试（每 60s）成功 ⇒ 若再遇到，重试即可，不要改远端。
- 上线后线上行为验证（同一个 `focus_pause` 探针指向线上）：本地/线上 `app.js` 哈希一致（约 225s 后）⇒
  ① 聚焦滚动（6s 位移 96px，CPU 18.2%）② `blur` ⇒ **位移 0**、③ `focus` ⇒ 恢复（−172.8）。
  失焦状态 CPU 复测 3 个 6s 窗口：**0.3% / 0.1%** 单核（第一次量到的 40.4% 是瞬时尖峰；无皮肤对照 0.9% / 1.4% 同量级）
  ⇒ 相对修复前的 **12–18%** 是数量级改善。

## 4. 遇到的问题

1. **只跳过推进不够**：第一版把 `!st.focused` 加进「跳过本帧」的条件里 ⇒ 位移确实停了，但 CPU 仍有 **~8%**
   —— 一直挂着的 rAF 会让浏览器保持 60fps 活跃（合成器不 idle）。必须 **停掉 rAF 本身**（`st.raf = 0`，不再排下一帧）
   并在 `focus`/可见时重启。⇒ 判据要量 **CPU**，不能只量「有没有动」。
2. **Playwright 的 `bring_to_front()` 不会真的让另一个窗口失焦**：开两个 context、甚至两个浏览器实例，
   被「切走」那页的 `document.hasFocus()` 仍然是 `true` ⇒ 拿它验证失焦路径会**假绿**。
   可靠做法：直接 `window.dispatchEvent(new Event('blur'/'focus'))`（浏览器真失焦时发的就是这两个事件）。
3. **被遮挡的窗口会把 rAF 压到 ~1fps**：soak 里量到 `p50 = 1000ms`（9 帧/30s）不是页面卡，是窗口不可见的节流
   ⇒ 帧率类指标必须在**可见且聚焦**的窗口上量。
4. 首次验证时误测了**线上**（改动还在本地未部署）⇒ 位移照旧在滚，差点误判「修复无效」。
   前端改动的验证必须打**本地服务**（`uvicorn web.app:app` + 空闲端口）。

## 5. 下次注意什么

- 任何「常驻 rAF / 常驻定时器」都要在**窗口失焦**（`window.blur`）与**标签不可见**（`visibilitychange`）时**真的停掉调度**，
  而不是只跳过工作；判据用 CPU（CDP `SystemInfo.getProcessInfo` 的 `cpuTime` 差分 / `Performance.getMetrics` 的 `TaskDuration`），
  不要只看「行为有没有发生」。
- 想量「这页到底吃多少 CPU」的最短路径：`SystemInfo.getProcessInfo`（本浏览器实例全部进程 CPU 累计）
  + `Performance.getMetrics().TaskDuration`（主线程），两次采样差分除以窗口秒数。

## 6. 涉及的 ADR

无（三条准入不齐：改动易撤销、无背景不困惑、非架构取舍）。
