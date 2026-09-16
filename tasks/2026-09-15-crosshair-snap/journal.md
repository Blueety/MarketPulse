# Journal — 悬停横线吸附到数据线（crosshair snap）

- **日期**：2026-09-15
- **任务目录**：`tasks/2026-09-15-crosshair-snap/`
- **计划**：`plan.md`（架构师实测后出具；方案 **B** = 吸附 + 线色归因 + 吸附点圆点，已确认）
- **性质**：前端内联插件（三页共享）+ 验收脚本断言改造 + 文档回填

---

## 1. 目标（已达成）

横线不再是"鼠标 y 的镜像"，而是**吸附到当前 x 最近的数据线**，随鼠标沿 x 在线上滑行；
顺带修掉**轴端读数与 x 无关**的缺陷（旧实现恒读"鼠标高度处的轴值"）。

---

## 2. 改动文件清单

| 文件 | 规模 | 内容 |
|---|---|---|
| `web/static/chart-crosshair.js` | +103 / −18 | 新增 `snapToNearest(chart, mx, my)`（先定 x 列→该列 y 最近的可见数据集；tie 取小索引；缺口 ±1..±3 邻域回退；NaN 守卫）；`afterEvent` 用吸附 y 作 `$crossY`、新增 `$crossSource`、**节流对象改为吸附后的 y**（0.5px）；`afterDatasetsDraw` 线色取吸附系列 `borderColor`(α.65) + 吸附点 3px 圆点；头注释「硬契约」新增第 7 条并修正「与系列无关」的定调 |
| `tasks/.../verify_ui.py` | +423（本次新增 ~420） | 独立探针 `SNAP_JS` + `_snap_geom/_snap_probe/_second_mouse_y/_snap_same_line`；`assert_crosshair_snap`（CS-2a/2b/8/8b/9/10，**四档宽度**含 1500 盲区 + 覆盖度断言）；`assert_crosshair_dpr2`（CS-D1~D4）；`assert_macro_cn_crosshair`（CNC-0~6）；CS-2 旧判据替换为注释说明；XC-5 拆为 XC-5a/5b；main() 挂三处调用 |
| `docs/architecture.md` | +2 | 决策表追加 1 行（append-only，`## 约束` 之前） |
| `docs/pitfalls.md` | +6 | 新段「模块 web/（悬停横线吸附 crosshair snap，2026-09-15）」3 条规则 |
| `tasks/2026-09-15-crosshair-snap/journal.md` | 新增 | 本文件 |

**零改动（与计划一致，已复核）**：`src/**`、`tests/**`、`web/app.py`（`_ASSET_FILES` 实测已含 `chart-crosshair.js`）、`web/templates/**`、`web/static/app.js`、`web/static/macro.js`、`web/static/style.css`；三页调用点契约未变（仍是 `plugins: [window.hoverCrosshair]` / `[window.makeHoverCrosshair({formatter})]`）。

---

## 3. 验证结果（全部实跑，串行）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `node --check web/static/chart-crosshair.js` | 退出码 0（独立 .js 可直接校验；未对模板做整体校验，避 plan §7 陷阱 1 的假阴性） |
| 2 | **改 JS 前** `venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **EXIT=1，FAILED 15 条**（先红 ✅，清单见 §4） |
| 3 | **改 JS 后** 同上 | **EXIT=0，ALL PASSED**；CS-8 四档 / CS-8b / CS-9 / CS-2a / CS-2b / CS-10 / XC-5a / XC-5b / CNC-0~6 / CS-D0~D4 **全部 PASS**；`console error = 0`；`scrollHeight@1920 = 1216 ≤ 1240`（护栏未动） |
| 4 | `venv/Scripts/python -m pytest tests/ -q` | **663 passed**（本改动不触 Python；663 = 上轮 639 + 并行会话中国页新增 24，零回归） |
| 5 | 报告 JSON | `%TEMP%\marketpulse-verify\verify-report.json`（`failures: []`） |

---

## 4. 红跑证据（改 JS 前，15 条）

| 断言 | 实测值 | 说明 |
|---|---|---|
| CS-8 @1920/1500/1280/375 | `(crossY, expectY) = (207, 257.74)` / 375 档 `(131, 162.30)` | 横线在鼠标高度，离最近数据线 50+px |
| CS-8b | `|$crossY − mouseY| = [0.2, 0.2, 0.2, 0.2]` | 旧行为：完全跟手 |
| CS-9 | `$crossSource` 不存在 | 挂钩未实现 |
| CS-10 | `['+20.0%', '+20.0%', '+20.0%']` | 三个 x 读数完全相同 = 缺陷复现 |
| CS-2b | 两点吸不到同一条线 | 旧行为同 x 纵移必然不同 |
| XC-5b | `(250, 316.78)` | 同上 |
| CNC-2 / CNC-3 / CNC-4 | `(239, 372.65)`；`['3950.22','3950.22','3950.22']`；不吸 | **CNC-3 与 plan §3.5 记录的恒定读数 `3950.22` 逐字吻合** —— 计划的事实依据得到独立复现 |
| CS-D2 | `bitmapW=2049 vs cssW*2=2048` | 取整残差 → 断言加 **±1px 容差**（非坐标系问题） |
| CS-D3 | `(207, 297.63)` | DPR=2 下同样未吸附 |

---

## 5. 遇到的问题

1. **GBK 控制台打印非 ASCII 符号会中途抛异常**（`pitfalls.md` 已记载，本次又踩）：CS-8b 标签里的 `−`（U+2212，抄自 plan 文本）触发
   `UnicodeEncodeError: 'gbk' codec can't encode character '\u2212'`，脚本在断言中途崩掉、前面的 PASS 已打印（看起来像"跑完了"）。
   → 断言标签一律 **ASCII + 中文**（`−` 改 `-`）。
2. **`CNC-2` 差 25px（1 个采样点距）—— 根因不是实现，而是探针坐标口径**：运行时诊断实测
   `idx0=32 usedIdx=32 expectY=372.65` vs 插件 `$crossSource={dsIndex:0, dataIdx:33}`、`crossY=347.33`，
   `mouse.x = 667.803`。Chart.js 的 `getRelativePosition` 对事件坐标做 **`Math.round`** → 插件实际用 668；
   探针未取整 → 在**并列（tie）**区间算出相邻列。修法：探针 `px/py` 同口径取整后两边一致（`idx0=usedIdx=33`、`expectY == crossY == 347.33`）。
   ⚠️ 这一点正是 plan §3.4(2) 警告的 tie 场景（`colCount` 曾为 4）。
3. **"二次派发同源事件"的尝试无效但不有害**：先怀疑首帧落在入场动画未结束的坐标上，加了二次 `mouse.move` 后数值完全不变 → 证明不是动画、是取整口径（见 2）。
   该改动保留（对动画竞态仍是正当防护），并已注释说明理由。
4. **`CN-4c` / `CN-4g` 在红跑出现、后续跑消失**（`CN-4f` 亦同）—— 属**并行会话**在途的中国页 bp 口径工作（依赖 AkShare/BLS 外部数据，抖动即红），与本次改动无关；未触碰、未修。
5. **提交边界：`verify_ui.py` 里混着并行会话的未提交改动** —— `git diff -U0` 显示 12 个 hunk，其中 6 个位于 `assert_macro_cn_page`（`-1391 / -1429 / -1434 / -1437 / -1438 / -1442 / -1471`），内容是 CN-4f/4g/4h 的 `bp` 口径断言与 `CN_MACRO_JS` 新字段，**不是我写的**。故：
   - **本次未执行任何 `git add`/`commit`**（`web/static/macro_cn.js` 亦为他们的在途改动）；
   - 提交时**不能**对整个 `verify_ui.py` 用 `git add`（会扫走别人的半成品）—— 需等其落盘后按 hunk 区分，或由需求方裁定。

---

## 6. 取证缺口（明确标注，未做）

- ❌ **真实触屏未实测**：`touchmove` 与鼠标共用同一 `afterEvent`（逻辑等价），但触屏下 `pointHoverRadius:0` + tooltip 禁用 → 横线是唯一读数，吸附收益最大；Playwright 需 `hasTouch=true` 才能模拟。**记为等价性论证，未行为验证**。
- ❌ **Firefox 内核未验**：本改动无 `-webkit-`/`-moz-` 分支、不涉原生控件外观 → 按 `pitfalls.md` 判据不属"引擎专项 CSS"（与滚动条那次的判据不同），故未双内核。
- ✅ 已补 plan §7 要求的 **DPR=2 取证**（CS-D1~D4）与 §8.4 的 **1500 中间盲区**（CS-8 四档 + 覆盖度断言）。

---

## 7. 下次注意

- 断言标签禁用非 GBK 符号（`−`/`⇒`/emoji）；`print` 兜底只写 ASCII+中文。
- **验收探针重算"应该吸哪一点"时，必须复刻被测实现的坐标归一化**（Chart.js 事件坐标 `Math.round`）；出现 1 个索引/1 像素级分歧时先对齐口径，再怀疑实现。
- 改"跟随鼠标的量"时先问**最终画出去的是哪个量**：节流必须挂在它上面（本次 L4）；早退分支不要顺手写派生状态。
- 需求从"跟手"改成"吸附"时，**「同 x 不同 Y → 指纹不同」类断言语义会反转**：必须按"补强"拆成 a/b（不删除、不放松）；注意 XC-5 这类**仍绿但语义漂移**的情况 —— 要在 journal 里写清"绿的原因已变"。
- 共享验收脚本（`verify_ui.py` / `chart-crosshair.js`）在多会话并行时：提交前用 `git diff -U0 -- <file>` **逐 hunk 确认归属**，不属于自己的不提交。
