# 计划：四象限矩阵可视化（`/macro` + `/macro/cn`）

> 用户反馈（2026-09-18）："这个 四象限：好像只有文字，没有图啊"
> 日期：2026-09-18 ｜ 任务目录：`tasks/2026-09-18-macro-quadrant-matrix/`

---

## 1. 现状（已核实）

「四象限」是宏观页一级块里的一行 12px 灰字，**没有任何图形**：

| 位置 | 现状 |
|---|---|
| `web/static/macro.js:565-572` | `#regime-quadrant` 只写一行文本：`四象限：再通胀（通胀↑ · 增长↑）` |
| `web/static/macro_cn.js:346-352` | `#cn-quadrant` 只写一行文本：`通胀 上行 · 增长 扩张` |
| `web/static/style.css:837` | `.regime-quadrant { margin-top:6px; font-size:12px; color:var(--text-secondary); }` —— 纯文字样式 |

**问题**：四象限是宏观分析最经典的一张图，纯文字丢掉两件信息——**位置感**（不知道当前在四个格的哪个角落）和**换格**（"从复苏挪到再通胀"这件事看不出来）。

---

## 2. 为什么画成 2×2 矩阵

数据只有**两个二元离散量**（`src/econ_fetcher.py` 的 `inflation_axis` = up/down、`growth_axis` = expanding/contracting），所以：

- ❌ **散点 / 定位图**：假装连续，点的位置会暗示一个并不存在的精度
- ❌ **雷达图 / 条形图**：表达不了"两轴交叉"这个核心语义
- ✅ **2×2 矩阵 + 当前格高亮**：与数据形态一一对应，**位置本身就是信息**

四格名称直接取自服务端 `QUADRANTS`（`src/econ_fetcher.py:192-197`，**两页共享同一字典** → 名称不会漂移）：

| 位置 | 组合 | 象限 | key |
|---|---|---|---|
| 左上 | 通胀↓ + 增长↑ | 复苏 | `goldilocks` |
| 右上 | 通胀↑ + 增长↑ | 再通胀 | `reflation` |
| 左下 | 通胀↓ + 增长↓ | 通缩衰退 | `deflation` |
| 右下 | 通胀↑ + 增长↓ | 滞胀 | `stagflation` |

> 横轴 = 通胀（左低右高）、纵轴 = 增长（上高下低）——与经济学教材的排布一致，**不要为了"好看"改成别的排列**。

---

## 3. 硬约束（违反会踩红，逐条都已在源码核实）

1. 🔴 **`#regime-quadrant` 的文字逻辑一行都不能改。**
   `verify_ui.py:1629` 断言：`/api/econ` 断供时该元素文本必须含「数据暂缺」。
   ⇒ 矩阵是**新增的兄弟元素**，**不是替换**那个 div。

2. 🔴 **`#cn-regime` 的 `data-quadrant` 属性不能动**（`verify_ui.py:1871` CN-4a 断言其非空）。

3. 🟡 **新 CSS 一律用新类名**（`.regime-matrix` / `.rm-cell` / `.rm-axis`，已 `grep` 全仓确认无占用）。
   `.mac-*` 由 `/macro` 与 `/macro/cn` **共享**，禁止修改既有声明（改了会自动改到另一页）。

4. 🟡 **375 档不得横向溢出**（MX-14a）。矩阵总宽 ~208px < 375 ✓，但改完要复测。

5. 🟡 **轴标签必须按页可配，不能硬编码一套**：
   - `/macro`：`通胀 ↑ / ↓`、`增长 ↑ / ↓`
   - `/macro/cn`：`通胀 上行 / 回落`、`增长 扩张 / 收缩`
   ⚠️ 中国页增长轴是 **PMI 与 50 比较的水平口径**（不是同比方向），写成 `↑/↓` 会误导。

---

## 4. 改动清单

### 4.1 `web/templates/macro.html`（第 60 行之后）

在 `#regime-quadrant` 之后追加一个空容器，**内含一个骨架占位**防止加载期高度跳变：

```html
{# 四象限矩阵（2026-09-18）：不改上面的 #regime-quadrant 文字（verify_ui:1629 契约）。
   骨架用 data-skel="quadrant" → 复用既有 SKEL_OF_SOURCE.macro 的卸载逻辑（macro.js:80）。
   ⚠️ 容器本身**不能**标 data-skel：clearSkel 是 removeChild 自身，会把容器整个删掉。 #}
<div class="regime-matrix" id="regime-matrix"><span class="skeleton rm-skel" data-skel="quadrant"></span></div>
```

### 4.2 `web/static/macro.js`

在 `renderRegime()`（557-596）里、`#regime-quadrant` 写完之后追加矩阵渲染：

- 取 `state.econ.quadrant`（key）作为当前格
- 四格顺序固定：`goldilocks / reflation / deflation / stagflation`（渲染顺序 = 视觉位置，注释写明）
- 有 quadrant → 对应格加 `is-now`；无（econ 不可用）→ **四格照常渲染但都不高亮**，容器加 `is-unknown`
  ⇒ 高度恒定、不跳变（既有惯例：宁可显示"不知道"也不让布局抖）
- 轴标签用本页措辞（见 §3-5）
- 复用 `escapeHtml`

### 4.3 `web/templates/macro_cn.html`（第 49 行之后）

同款容器，id 用 `cn-matrix`（中国页 `cn-quadrant` 本来就没有骨架，容器内不放骨架）。

### 4.4 `web/static/macro_cn.js`

在 `renderRegime()`（338-385）里追加矩阵渲染，当前格取 `d.quadrant`（`regime()` 已返回值，无需新取数）。
轴标签用中国页措辞。

### 4.5 `web/static/style.css`（追加在 `.regime-quadrant` 规则之后，~16 行）

```css
.regime-matrix { display:grid; grid-template-columns:auto repeat(2, minmax(0,1fr)); gap:3px;
  margin-top:10px; width:max-content; min-height:74px; }
.rm-axis { display:flex; align-items:center; justify-content:flex-end; padding-right:6px;
  font-size:11px; color:var(--text-muted); }
.rm-cell { border:1px solid var(--border); border-radius:6px; padding:7px 0; text-align:center;
  font-size:12px; color:var(--text-muted); }
.rm-cell.is-now { background:var(--bg-elevated); border-color:var(--blue);
  color:var(--text-primary); font-weight:600; }
.regime-matrix.is-unknown .rm-cell { opacity:.55; }
```

⚠️ 颜色必须用既有 token（`--border` / `--blue` / `--text-muted` / `--bg-elevated`），**不要写死色值**——
双主题自动跟随（项目惯例：写死色值会漏切主题）。

### 4.6 `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`

新增 **QM-1 ~ QM-5** 断言（宏页面板 + 中国页面板各跑一遍关键项）：

| 断言 | 内容 |
|---|---|
| QM-1 | `#regime-matrix`（/`#cn-matrix`）存在，且 `.rm-cell` 数量 == 4 |
| QM-2 | 四格文本集合 == `{复苏, 再通胀, 通缩衰退, 滞胀}`（防改名/漏格） |
| QM-3 | `quadrant` 非空时**恰好 1 格**带 `is-now`，且其文本 == 该象限中文名 |
| QM-4 | `/api/econ` 断供时不崩、无 `is-now`（且既有 1629 的「数据暂缺」断言仍绿） |
| QM-5 | 375 档矩阵不横向溢出 |

⚠️ 断言标签**禁用 GBK 外字符**（`⇒` 等）—— 会让整个脚本 `UnicodeEncodeError` 中途死掉（pitfalls 已有专条）。

---

## 5. 实施步骤

1. 改 §4.1 ~ §4.5（模板 + 两个 JS + CSS）。
2. 起本机服务，手动看 `#regime-matrix` 是否渲染、当前格是否高亮、双主题是否正常。
3. 加 §4.6 断言，**先跑一次确认 QM-1/2 在改动前会红**（红→绿方法论）。
4. 跑完整 `verify_ui.py`，与**当日基线**比对（G8 姿势：只看相对变化，不看绝对红条数）。
5. 补 `docs/frontend-structure.md`（宏观页模块清单）与 `journal.md`。

**验证命令**：

```bash
venv/Scripts/python -u tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
```
⚠️ 必须**前台 + 显式 timeout**（约 5 分钟）。后台跑会在 2m01s 被掐（日志 0 字节或截断）。

---

## 6. 预期影响（改前要实测确认）

| 量 | 当前 | 预期 | 护栏 |
|---|---|---|---|
| `.mac-regime` 行高 | ~92px（由四行因子列决定） | **~131px**（改由左列 hero 决定） | 宏观页**无纵向硬护栏**，但 +39px 要实测 |
| 375 档宽度 | — | 矩阵 ~208px | MX-14a 无横向溢出 |
| 双主题 | — | 用既有 token 自动跟随 | MX-13 |

---

## 7. 明确不做

- ❌ **不加"从哪个格挪过来的"轨迹/箭头** —— `history_regime` 只提供三态（Risk-On/中性/Risk-Off）**天数**，没有四象限的历史序列。画轨迹就是编数据。
- ❌ **不给四格上红绿语义色** —— 象限没有褒贬（"滞胀"不是"跌"），染红绿会被读成涨跌。
- ❌ **不改 `#regime-quadrant` 的文案**（§3-1 契约）。
- ❌ **不改后端** `/api/econ`、`/api/econ/cn` 的四象限算法。
- ❌ **不动首页**（首页没有四象限）。

---

## 8. 风险

| 风险 | 处置 |
|---|---|
| 矩阵撑高一级块 → 触发某条几何断言 | 先取当日基线，改后对比；目前 MX-* 组**无**纵向断言，但 MX-14a/b 必复测 |
| `clearSkel` 误删容器 | 容器**不标** `data-skel`，只给内部骨架标（§4.1 注释已写明） |
| 中国页轴标签照抄导致口径错误 | §3-5：两页标签分别传入（中国页 = 扩张/收缩） |
| 格子名与 `QUADRANTS` 漂移 | 前端**不硬编码中文名**，从服务端 `quadrant_label` 取；四格 key 顺序写常量表 |

---

## 9. 提交清单

```
web/templates/macro.html
web/templates/macro_cn.html
web/static/macro.js
web/static/macro_cn.js
web/static/style.css
tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
tasks/2026-09-18-macro-quadrant-matrix/plan.md
tasks/2026-09-18-macro-quadrant-matrix/journal.md
docs/frontend-structure.md        ← 若补了模块清单
```

⚠️ 用 `git add <具体路径>`，**不用** `-A`（仓库外 cron 仍全量 add，别留半成品）。
⚠️ **不加** `docs/user-guide.md`（那是上一轮独立改动，未提交，别混进来）。
