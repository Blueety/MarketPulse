# Journal — 视觉保真补齐（对照效果图）

- 日期：2026-09-12
- 角色：编码执行者（Phase 3 Step 3.6-3.7），按 `plan.md`（§0→§3→§5→§9）实施
- 前置：玻璃化 / 纹理调优 / crosshair 均已落地验收；开工前 `git status` 干净、基线 EXIT=0

## 目标

补齐 5 项与效果图的视觉差距：V1 四处列表品牌色图标（16px 圆角方块 + 1 字符，Q2）、
V2 趋势图 y 轴右侧、V3 品牌字 MarketPulse（去 mono/字距）、V4 头像圆角方块、
V5 侧栏导航 10 项（Q1：4 映射 + 3 保留 + 3 占位）。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/static/app.js` | 改（896 → 940 行） | `OVERVIEW_CARDS` 加 `char`；新增 `ICON_COLORS`（symbol→`--c-*` 变量名）/ `ICON_CHARS` / `ICON_PALETTE`（板块循环）/ `iconHtml()`；4 处渲染插入图标；`scales.y` 加 `position:'right'`；2 处 colspan 4→5 |
| `web/static/style.css` | 放（546 → 561 行） | `.ico`；`.mini-label` 改 flex 容纳图标；`.bar-row` 网格两处加 18px 图标列（**主档 + 375 断点**）；`.brand-mark` 去 mono/字距；`.avatar` 圆形→6px 方块（`--bg-hover` 面 + `--text-secondary` 字 + `--border` 描边）；`.nav-item.is-disabled` + `.nav-divider` |
| `web/templates/index.html` | 改 | 品牌字 `MarketPulse`；两张表 thead 加 `th.col-ico` + 加载态 colspan 5；nav「最新资讯→新闻资讯」+ 分隔线 + 3 个 `is-disabled` 占位（`<span>`，无 href/data-target，各配 1 个内联 svg） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 扩展（760 → 845 行，零覆盖） | `FIDELITY_JS` + `assert_fidelity(page, m)`（F-1a~e/F-2/F-3/F-4/F-5/F-6a~c/F-7a，共 13 条）；调用点在 assert_crosshair 之前（末尾移出鼠标给 crosshair 留干净基线） |
| `docs/pitfalls.md` | 追加 3 条 | 加列三处同步（colspan/网格×2/表头）/ nav 占位防死链 / 图标色走内联 var() 防主题切换漏色 |
| `tasks/2026-09-12-visual-fidelity/journal.md` | 新增 | 本文件 |

## 验证结果（全部实际运行）

| 步骤 | 命令 | 结果 |
|---|---|---|
| F-1 基线 | `verify_ui.py` | **EXIT=0 / ALL PASSED**（178 条 PASS） |
| F-6 红跑 | `verify_ui.py`（代码未改） | **恰 9 条 FAIL**（F-1a~d/F-2/F-3/F-4/F-5/F-7a），F-6 回归护栏与既有断言全 PASS |
| 绿跑 | `verify_ui.py` | **ALL PASSED / EXIT=0**：13 条 F 断言全绿；crosshair CS-1~7 在轴右状态下照常工作；scrollHeight@1920 仍 1216 ≤1240 |
| F-7b 取证 | `%TEMP%/verify_f7_bubble_side.py`（禁 tooltip + 像素带对比） | 右带 14/29 行有气泡块、左带 0/29 → **气泡贴右侧**；`$crosshairLabel='+1.6%'` 在轴右下正常产生 |
| 静态门 | `node --check app.js` + grep colspan | JS OK；`colspan="4"` 0 处、`colspan="5"` 5 处（app.js 3 + index.html 2） |
| 回归 | `pytest tests/ -q` | **459 passed** |

## 遇到的问题 / 关键决策

1. **plan 说 watchlist「在第 1 个 td 内插入图标」但又要求 colspan 4→5**——两者矛盾（td 内插图标不增列）。
   按用户任务书的硬指令「5 处 colspan 全部改 5」执行 = **新增独立图标列**（图标列 + 原四列 = 5 列），
   表头/空态/加载态三处同步。5 处 colspan 实测 grep 全中（app.js :180/:687/:874 + index.html :114/:171）。
2. **`.bar-row` 网格有两处**（主档 `:412` + 375 断点 `:521`），plan 只提了主档——375 档若不同步会挤爆。
   两处都改成 `18px minmax(0,1fr) …`。
3. **主题切换不重渲染列表**（theme handler 只重跑主图 + sparkline）→ 图标底色若用 `cssVar()` 取实值
   会漏主题切换；改为 `iconHtml()` 输出**内联 `var(--c-*)` 引用**，绘制时实时解析，双主题自动跟随（R5）。
4. **V5 实际改动比 plan 小**：us-sectors 的 nav 标签**本来就是**「板块表现」（G9 断言在锁），实际只改
   「最新资讯→新闻资讯」+ 加分隔线与 3 个占位。占位图标零依赖：3 个 ~3 行的内联 svg（柱状/日历/齿轮）。
5. **F-5 断言设计**：只查「data-target 全命中」在旧 7 项结构上会假绿（红跑须 FAIL）→ 改为
   「总数==10 + is-disabled==3 + target 全命中」三件套，红跑 7 项结构下 FAIL ✓。
6. **F-7a 的 `$crosshairLabel` 在 mouseout 后不清空**（插件只清 `$crossY`）→ 直接读会是陈旧值；
   F-7a 自己做一次悬停再读，且放在 assert_crosshair 之前、结束时把鼠标移出，保证 crosshair 基线干净。
7. **图标可读性（Q2 代价）**：16px 方块 + 9px 汉字按方案落地（概览卡：美/A/金/元/债/油；板块取首字；
   自选按 symbol 查 ICON_CHARS、回退名称首字）。目视若不清，按方案 §3 V1 顺序调：
   ① 10px 字 + 18px 块（.bar-row 图标列同步 20px）② 汉字换单字母 ③ 退回纯色块。

## 下次注意什么

- 给表/网格加列：grep `colspan` + grep `grid-template-columns`（**含各断点覆盖档**）+ 表头 th，三处一起动。
- 效果图里的 nav 标签先对照页面区块存在性，无区块的项用 is-disabled 占位，别照抄。
- 切主题不重渲染的 DOM，颜色一律引用 CSS 变量（内联 `var(--token)`），不要 JS 取实值。
- 跨任务回归点（如 crosshair × 轴位）要写成断言（F-7）+ 像素取证（%TEMP% 探针），不能只靠"代码看起来会跟随"。
