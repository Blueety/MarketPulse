# PRD 评审：`/macro` 前端重构（dark financial terminal）

> **评审对象**：2026-09-16 用户提供的 Task Handoff（拟落 `tasks/2026-09-16-macro-page-frontend-refactor/prd.md`）
> **评审人**：架构师（读过 `docs/frontend-structure.md` / `web/templates/macro.html` / `web/static/style.css` / `web/static/macro.js` / `verify_ui.py` 后的实测结论）
> **结论**：**手写前必须先裁定 3 项**（其中 1 项会撞掉既有断言 M-7），并修正 2 处事实错误 + 1 个范围漏洞。
> **本文性质**：评审意见，不含实施代码；**未修改任何项目文件**。

---

## 0. 一句话结论

这份 handoff 有 **6 项是"之前改过、这次要往回改"**（每项都有留档的理由），**真新增只有 4 项**（其中 3 项有现成基座）。
其中 **Hero 卡片化**会**直接违反既有验收断言 `M-7`**；**"提升对比度"**会反转四/五级块"背景资料"的刻意降对比；**改 `.mac-*` 必然波及 `/macro/cn`**，与它自己写的 Out of Scope 冲突。

---

## 1. 之前改过、这次又要改的（6 项，逐条给依据）

| # | handoff 要求 | 既有设计（依据 = 文件:行） | 冲突性质 |
|---|---|---|---|
| **1** | 「Hero 模块 `#mac-regime` 打造为核心仪表盘卡片」 | 一级块 = `.mac-flat`，**刻意"无边框/无底色，靠间距与卡片区分"**（`macro.html:41-43` plan §3.2「降卡片感」；`style.css:707`） | 🔴 **撞既有断言** |
| **2** | 「提升视觉对比度」（通篇全局提法） | 四/五级块 = `.mac-card-quiet`，**刻意"降对比度 = 背景资料"**（`style.css:709`；`macro.html:107-108` 标注「PRD 要点 8」） | 🟡 反转分级意图 |
| **3** | 「核心变量与因子**卡片化 / 网格布局**」 | 三级块是「**同一卡片内两栏**」——上一轮**刚去掉"卡片套卡片"**两层壳以消除空转留白（`macro.html:77-79`，pitfalls D5/D6） | 🟡 反向前一轮结论 |
| **4** | 「关键数值统一等宽字体（JetBrains Mono）」 | `--mono` **已存在**（系统 mono 栈，`style.css:16`）；`.score-num` / `.f-val` / `.mac-var .v-value` / `.e-value` / `.rel-r` / `.h-val` / `.e-chg` **本来就是 mono** | 🟡 真新增的是「引入 webfont」 |
| **5** | 「未接入/未开放显示 Disabled + `SOON` 徽章」 | **已有实现**：侧栏 `.nav-item.is-disabled`（2 项）、顶栏 `.is-placeholder + disabled`（搜索/通知/头像）、`#us-sectors` 的 `.link-btn{cursor:not-allowed}`（`style.css:258`）；`frontend-structure.md §8` 有完整清单 | 🟡 属"改样式"非"新增功能" |
| **6** | 「骨架屏 / Empty State 替代粗糙提示」 | **`style.css:675` 已有 `.skeleton`**，首页 overview / watchlist / sectors / alerts 已在用 | 🟢 属"把已有基座用到宏观页" |

### 1.1 🔴 第 1 项的断言证据（最必须处理的一条）

`tasks/2026-09-11-frontend-bento-redesign/verify_ui.py:1987-1989`：

```python
# M-7：一级模块必须**不再是等权卡片**（PRD「降卡片感」；plan §3.2）
check(d["regimeIsCard"] is False and str(d["regimeBorderTop"]).startswith("0"),
      "M-7 「当前宏观环境」为无边框区块（不再是等权卡片）", (d["regimeIsCard"], d["regimeBorderTop"]))
```

即：**现有验收脚本明文禁止 `#mac-regime` 是卡片、且要求 `border-top-width` 为 0**。
handoff 若照字面实现（给它套卡片），`M-7` 必红。

**处置（二选一，禁止第三种）**：
- **(A) 推荐——保住 M-7**：Hero 的"仪表盘感"做在**一级块内部**（放大 `#regime-score`、加区间刻度/进度条、正负语义色、强化 `#regime-factors` 的行内排版），**不给它加卡片边框**。M-7 保持绿。
- **(B) 若确要卡片化**：这属于**产品决策反转**，必须 ① 在 `docs/architecture.md` 决策表追加一行（写明"推翻 2026-09-14 的分层决策"及原因）；② 把 M-7 **改成新的可测不变量**（例如"Hero 块文字对比度 ≥ 相邻二级卡"+`#regime-score` 字号 ≥ N px"）。
  ⚠️ **绝不能只是删掉 M-7** —— 本项目明确纪律：**删断言让它变绿 = 把真红改成假绿**（`docs/pitfalls.md` 有专条）。

---

## 2. 真新增的（4 项）

| # | 新增内容 | 现状（依据） | 可复用基座 / 风险 |
|---|---|---|---|
| 1 | **宏观页骨架屏** + `#macro-chart-fail` 升级为 Empty State（带重试） | `macro.html:72` 目前只有一行文字「图表加载失败」；宏观页首屏是空白或 `—`（`frontend-structure.md §9-5` 原文承认） | ✅ 复用 `.skeleton`（`style.css:675`）。⚠️ **必须区分「加载中 / 取数失败 / 无数据」三态** —— 骨架屏会把"上游 403"伪装成"正在加载"，正是 `pitfalls` 记过的「降级为空会掩盖故障」 |
| 2 | **`—` → shimmer 占位** | 字面量 `—` 出现在 `#macro-asof` / `#regime-score` / `#econ-asof` | ⚠️ CN 页有断言「缺失值不得拼单位（`"—%" not in 文本`）」；`.mac-*` 共享 → 改占位符要 grep 断言是否依赖 `—` 字面 |
| 3 | **四维度因子的「影响资产」Badge / Icon** | 现状是**纯文本**：`macro.js:543` 渲染 `.fr-assets` → `factorAssets(name, impact)`；页面已有说明「影响资产为前端静态映射」（`macro.html:86`） | ⚠️ **图标系统只在 `app.js`**（`ICON_COLORS` / `iconAssetHtml` / `iconFlagHtml`），`/macro` 上**不存在** → 要么复制**第 4 份**，要么抽共享文件（需在 3 个模板按「业务脚本之前」引入 + 在 `web/app.py:115 _ASSET_FILES` 登记）。素材已有：`web/static/icons/{dollar,bond,gold,oil}.svg` |
| 4 | **`#regime-score` 正负语义色** | `style.css:743` 现为**中性** `var(--text-primary)` → 确属新增 | ✅ 用 `var(--green)` / `var(--red)`（项目既有 token，light/dark 各一套） |

---

## 3. 必须修正的 3 处硬错误

### 3.1 「Out of Scope: 不深度重构 `/macro/cn`」与共享样式矛盾（范围漏洞）

`.mac-*` 是 **`/macro` 与 `/macro/cn` 共用**的（`frontend-structure.md §3.3`：`.cn-*` 只在 `style.css:837-881` 补了 ~8 条规则，其余全部复用 `.mac-*`）。
⇒ **只要动 `.mac-*` 的底色 / 对比度 / 卡片化，就必然改到中国宏观页的观感**，Out of Scope 在共享规则上**无法自动成立**。

**处置（二选一）**：
- **(A) 用 id 限定作用域**：新增规则一律写成 `#mac-regime …` / `#mac-metrics …`，不去改 `.mac-*` / `.mac-flat` / `.mac-card-quiet` 的公共声明；
- **(B) 承认共享**：把 `/macro/cn` 的回归纳入验收（`verify_ui.py` 的 `assert_macro_cn_page` 与 `CN-*` 组），并在 prd 里显式列出"会被 CN 页继承的属性清单"。

### 3.2 `text-emerald-400` / `text-rose-400` 是 Tailwind 类名

handoff 的 Current Understanding 里写「看多用绿 `--green` / `text-emerald-400`，看空用红 `--red` / `text-rose-400`」。
本项目 **无框架、无构建、纯 CSS 自定义属性**（`frontend-structure.md §1`）。
⇒ 删掉这两个 Tailwind 类名，统一用 `var(--green)` / `var(--red)`；顺手核对颜色语义与项目一致（`--green` = 涨/正、`--red` = 跌/负）。

### 3.3 「切换为 Dark Theme」与 Done When「双主题验证」自相矛盾

- 现状：`macro.html:2` 是 `<html lang="zh-CN" data-theme="light">`，且 **light 是主推主题**（二十五期「Light 优先完整」；2026-09-02 专门做过 light-theme 任务）；主题初始化**同源 4 处**（`frontend-structure.md §7-1`）。
- 而 Done When 又要求「手动切换双主题…验证正常」。

⇒ **必须先裁定**：(A) **保留双主题，只增强 dark 下的 `.mac-*` 表现**（推荐，不动默认主题）；还是 (B) 把默认主题改为 dark（= 改产品决策，牵动 3 页 + 4 处主题初始化 + 主题相关断言）。
⚠️ 若在 `.mac-*` 里写死深色（`#0B0F17` / `#151C28`），**light 主题下会变成深色块** —— 必须全部走 token。

---

## 4. handoff 里正确、但可以更精确的部分

| 项 | 核实结果 |
|---|---|
| `style.css` 关注 `689-836` 行 `.mac-*` | ✅ 正确（689 起 `.mac-*`，837 起 `.cn-*`） |
| 「5 视口 1920/1600/1280/900/375」 | ✅ 正确（`verify_ui.py:33 VIEWPORTS` 实测为该 5 档） |
| 「chart-crosshair.js 必须在 macro.js 之前」 | ✅ 正确，与 `frontend-structure.md §7-2` 一致 |
| 「canvas 显式高度 + `maintainAspectRatio:false` + 禁 `!important`」 | ✅ 正确，与 §7-5 一致 |
| `#mac-regime` / `#mac-metrics` id | ✅ 存在且用词正确 |
| 「改 class 名要基线 A/B」 | ✅ 方向对，但**漏了更危险的一层**（见 §5.2） |

**新增提醒**：`docs/frontend-structure.md` 目前是**未跟踪文件**（`git status` 显示 `??`，22:04 新建）——它是本 handoff 的 Context Pointer，交付时必须与 prd 一起 `git add`，否则引用悬空。

---

## 5. 动布局前必须先读的 5 条既有护栏（handoff 未列）

| 断言 | 内容 | 位置 |
|---|---|---|
| **M-6** | 宏观因子列额外留白 ≤ 20px（D5 改前 77px） | `verify_ui.py:1991` |
| **M-7** | 「当前宏观环境」为**无边框区块**（`regimeIsCard === false` 且 border=0） | `verify_ui.py:1988` |
| **M-8** | 375 档主图高 ≥ 360px（D11 改前 325px） | `verify_ui.py:2020` |
| **M-9 / M-9b** | 1920/1280/375 三档零横向溢出；`/macro` console error = 0 | `verify_ui.py:1959/2015/2022` |
| **M-10 / M-10b** | 1280 档两列区保持 2 列；375 档降为 1 列 | `verify_ui.py:2017/2019` |

### 5.1 改类名的"静默变 0"陷阱（比 handoff 的表述更危险）

`verify_ui.py` 的选择器直接依赖这些类名：
`.mac-var`（1444/1458）、`.mac-rel-row` / `.mac-rel-row.strong`（1446/1462）、`.mac-hist-row`（1469）、`.mac-econ-item`（1470/1698）、`.mac-2col`（1474/1666）、`.mac-card-head`（1636）、`.mac-empty`（1472）、`.mac-note`（1707）。
⇒ 改名后**部分断言会变红（可发现），但"应为 0"类断言会直接变假绿**（选择器匹配不到 → 恒 0 通过）。
**处置**：改名前后各 `grep` 一次这些类名，**逐条判断残留断言是"变红"还是"变假绿"**，并在 journal 里记下"为什么某条基线由红/绿翻转"。

### 5.2 「高对比度暗黑终端风格」这项 Done When 目前**无法自动验收**

`verify_ui.py` 测的是**几何 / 结构 / console**，不测观感。`M-*` 里与视觉相关的只有 `quietBg`（采样底色，未用于断言）与层级断言。
⇒ 必须补：**人工双主题截图对比** + 至少 1~3 条**可量化不变量**（例：dark 下 `.mac` 正文与卡片底色的对比度 ≥ 4.5:1；`#regime-score` 字号 ≥ 相邻 `h2` 的 2×）。否则这项等于"凭肉眼说做完了"。

---

## 6. 给 handoff 的最小修订建议

1. **Hero**：明确"**不加卡片边框**，仪表盘感做在一级块内部"（保 M-7）；若坚持卡片化，先走决策反转流程（§1.1-B）。
2. **对比度**：改成**分级提对比** —— 一/二级提，四/五级维持"背景资料"。
3. **字体**：**不引入 webfont**（无新依赖原则），只做"哪些数值该用 `--mono`"的一致性收口。
4. **范围**：写死"新规则一律用 `#mac-*` id 限定，不改 `.mac-*` 公共声明"，或在 prd 里显式列出会被 `/macro/cn` 继承的属性。
5. **删除** Tailwind 类名表述；**裁定**默认主题问题（§3.3）。
6. **验收**：补齐 §5 的 5 条护栏 + §5.1 的 grep 纪律 + §5.2 的对比度不变量；Verification 里加 `docs/frontend-structure.md` 与 prd 一起入库。
7. **补一句**：**不得为了让 MX-11 / MX-6 等上游数据类断言变绿而在前端造数** —— 那 10 条红是 Yahoo 403 上游问题（`docs/system-overview.md §9 G8`），本任务只会让它们"红得更好看"。
