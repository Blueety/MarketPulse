# Journal — 玻璃参数落地（方案 H：光斑 + 细纹理）

> ⚠️ **最终状态（2026-09-12）**：细纹理落地并验收后，用户目视否决（.05→.04→.03 仍嫌丑），
> 按用户指令**仅去掉纹理**：方案 H 三层光斑**原样保留**（`style.css` 相对 `26da86f` 仅改 dark
> 档两行 ambient 变量），`verify_ui.py` 回退至 `26da86f` 基线版（纹理断言随之移除）。
> 详见文末「追记」。

- 日期：2026-09-12
- 角色：编码执行者（Phase 3 Step 3.6-3.7），按 `plan.md`（§0/§3.1/§5/§6.2/§9）实施
- 上游任务：`tasks/2026-09-11-glassmorphism-fix/`（玻璃化已验收）；本任务为参数调优

## 目标

dark 档氛围层落地方案 H 最终参数：细纹理（alpha .05 / 周期 6px / **最上层**）+ 强光斑 3 层
（第二光斑 74% 34% → 80% 26% 避让趋势卡绘图区）；面板与模糊 token 不动；light 本轮不动；
`verify_ui.py` 同步新增 3 条断言（先红后绿），全量回归不回退。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/static/style.css` | 改（+12/−3） | 仅 dark 档 `--ambient-1`（纹理单层）/ `--ambient-2`（3 层光斑列表）；body 写法未动；同步 2 处过时注释（层序约束写进注释）。light（`:root` 26-27 行）未动 |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | 扩展（+21，零覆盖） | `import re`；`GLASS_JS` 增 `bodyFirstLayer`（复用既有 `splitTop`）；`assert_glass` 增 3 条 dark 门控断言（层数==4 / 第一段匹配 repeating-linear-gradient / alpha∈[0.03,0.07]） |
| `docs/pitfalls.md` | 追加 4 条 | 层序决定振幅 / `>=N` 测不出新增层 / `--ambient-*` 置 none 非法 / Clash 代理劫持 wait_ready + probe_texture 属自注入工具 |
| `tasks/2026-09-12-glass-texture-tuning/journal.md` | 新增 | 本文件 |

提交：外部 cron「每日数据更新」于 2026-09-12 01:00 自动 `git add -A` + commit + push
（`2b012d4 auto: 每日数据更新`，恰好仅含 style.css + verify_ui.py 两个文件；pitfalls/journal
为提交后补写）。规格与 pitfalls 均记载该现象：改动已安全入库，无需手动提交。

## 验证结果（全部实际运行）

| 步骤 | 命令 | 结果 |
|---|---|---|
| T-1 基线 | `verify_ui.py` | 首跑 EXIT=1（服务未就绪，见下），复跑 **EXIT=0 / ALL PASSED**（scrollH@1920=1216、dark/light body 层=2、backdrop 11/11） |
| 红跑 | `verify_ui.py`（CSS 未改） | **恰 9 条 FAIL** = 3 新断言 × 3 dark 视口，其余全 PASS、EXIT=1 → 断言在测东西 |
| 绿跑 | `verify_ui.py`（CSS 已改） | **ALL PASSED / EXIT=0**；dark 3 视口 body 层=4、light 仍 2；scrollH@1920=1216（≤1240 不变）；console error 0 |
| 回归 | `pytest tests/ -q` | **459 passed**（与仓库基线一致） |

像素级运行时取证（一次性脚本落 `%TEMP%\mp_glass_cmp\`，不进仓库；对**生产 CSS** 直接测量、无注入）：

| 测量点（plan §6.2） | 实测 | 判据 | 结论 |
|---|---|---|---|
| §6.2 窄条（x1892–1914, y120–1100）单列扫描线峰谷差 | 中位 **10**（8~11） | ≈12（无纹理=1） | 纹理存在且强度落在标定 .045~.055 档；1px 斜线 DPR=1 抗锯齿扩散解释与理论 12.2 的小差 |
| 卡内高频振幅（#watchlist 空白处，高斯残差 stddev） | **0.02** | ≈0 | 纹理被 backdrop-filter 糊平 = 磨砂正确表现 |
| 背景窄条高频振幅（.row-kpi/.row-main 缝隙） | **5.14** | §0.2 卡外带 5.0~5.4 | 落在上一任务实测带内 |
| R5 蓝线对比度（#66A8E0 vs 近邻背景，canvas rect 定位） | 线亮 140 / 背景 52 → **87** | 清晰 ≳60 | 光斑移位后蓝线仍清晰；新光斑 (80% 26% → x≈1536) 已在画布（右缘 x≈1301）之外 |
| R6 DPR=2 窄条高频振幅 | **2.51** | ≫0、无实心带 | 1px 纹理在 DPR=2 退化为正常细纹，未成摩尔纹/实心带 |

## 遇到的问题

1. **基线首跑假阴性**：uvicorn 40s 未就绪。取证：`import web.app` 仅 1.3s；`urllib.getproxies()`
   在无代理 env 下仍返回 Clash `127.0.0.1:7890`（Windows 注册表系统代理），默认 urlopen 与
   无代理 opener 当时均可 200 → 结论为 Clash 对 localhost 转发瞬时异常，复跑即绿。已记 pitfalls；
   如复发可给 `wait_ready` 换 `ProxyHandler({})`（本次未改，避免超出规格的改动面）。
2. **probe_texture.py 不能验生产 CSS**：它是自注入式标定工具（`add_style_tag` 覆盖 `--ambient-*`、
   光斑还是旧位置 74% 34%）。另写一次性测量脚本直读生产页面（未注入任何样式）。
3. **「峰谷差」口径坑**：宽条逐行均值峰谷差（28.6）混入光斑亮度趋势，虚高；换单列残差峰谷差
   才与标定表同口径（10 ≈ 12）。度量口径必须与标定来源对齐，否则会误判"纹理过强"。
4. **R5 首次取样落空**：按 plan 坐标 (1421,367)±100 采样无蓝线——该点在趋势卡/自选卡边界。
   改用 JS 取 `#chart-main` 真实 rect（x277 w1024）后命中 1598 线像素。像素取样坐标优先用
   运行时 rect，不要信版面估算（与 pitfalls「包围盒定位」教训同源）。

## 下次注意什么

- 规格内部矛盾以「显式最终参数 + 高危警告」为准：plan §5 T-2 行文的「`--ambient-2` 置 none」
  与 §3.1/R8 冲突，按后者执行（none = 整条 background-image 非法被丢弃）。
- 断言同步必须先红后绿，且注意多主题门控；`>=N` 类断言对新层无检出能力。
- verify_ui 基线跑挂先复跑一次再排查（Clash 代理瞬时劫持是已知假阴性源）。
- 改动落盘后尽快 `git status` 快照——cron 随时可能扫入提交，审阅时用 `git show <sha>` 对照。

## 追记（2026-09-12）：用户否决细纹理 → 回退纯光斑

- **决策**：纹理 alpha `.05 → .04 → .03` 两轮调淡后用户仍觉「丑」，先选「去掉纹理」，随后补充
  约束「**只要把纹理去掉，其他不要改**」——即保留方案 H 光斑、仅去纹理（整体回退会连光斑
  一起带回旧版 .14，不符合该约束）。标定数据只保证「可辨」，不保证「好看」——观感取舍归用户。
- **操作**：先 `git checkout 26da86f -- style.css verify_ui.py` 整体回退，再把方案 H 三层光斑
  按「首层进 `--ambient-1`、其余两层进 `--ambient-2`」拆回（保持层序 = 渲染合成与方案 H 去
  纹理后完全一致；拆分是为规避 `background-image: <层>, none` 非法值，见 pitfalls）。
  `verify_ui.py` 停在 `26da86f` 基线版（`>=2` 断言对 3 层光斑天然兼容）。
- **验证**：`verify_ui.py` → **ALL PASSED / EXIT=0**（dark body 层=**3**、light 2、backdrop 11/11、
  scrollH@1920=1216）；`git show 2b012d4` 与当前文件逐字比对 → 光斑三层值一致；像素取证
  §6.2 窄条单列峰谷差 **中位 2**（无纹理基线 1，有纹理时 10）→ 纹理确认消失；行均值趋势
  28.7 ≈ 方案 H 时的 28.6 → 光斑亮度保留。
- **保留物**：pitfalls 四条机制教训（层序 / `>=N` 断言 / `none` 非法 / 代理假阴性）与本任务全部
  工具不回退——它们记录的是真实机制，且「细纹理被否决」本身已补记进 pitfalls，防止将来重复提案。
- **若将来重提细纹**：标定工具与数据在 `tasks/2026-09-11-glassmorphism-fix/`（probe_texture.py、
  §0.1 表）；断言先红后绿的完整范式在 `git show 2b012d4`。
