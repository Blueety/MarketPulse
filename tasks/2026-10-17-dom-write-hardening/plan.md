# 2026-10-17 DOM 写入语义哨兵（方案 ③ 检测 + 方案 ① 免疫）

## 目标

首页（以及另外 5 页）出现「内容重复」的**根因不在本仓**：截图取证表明是页面里的 DOM 写入语义被第三方脚本
改写成了「前置插入、旧内容留下」（详见本任务 `journal.md` §1 的取证链）。用户已选定处置顺序：**先 0（定位注入源）
→ 再 ③（只检测、不修改）**。

本任务只做 ③：**加一个启动哨兵，让这类改写下次出现时一眼可辨**，不改任何渲染逻辑、不做免疫（方案 ①/② 未选）。

- 首次渲染**之前**检测 `innerHTML` / `textContent` 的写入语义（行为探针：游离节点连写两次，看第二次是否替换第一次）。
- 命中时留两处证据：
  1. `console.warn('[dom-write] …')`：被改写的 API、**实测行为**、以及**当前 setter 的源码片段**（片段通常直接点名肇事扩展/用户脚本）；
  2. `<html data-dom-write-patched="innerHTML,textContent">`（机器可读）。
- 页面加载后再查一次**重复 id**（克隆型注入的特征：同一元素被复制 ⇒ 写入只落进第一个克隆体，副本冻结在旧值），命中时
  打 `<html data-dom-write-dup-ids="N">` + 一条 warn。

非目标：不重写 160 个写入点（方案 ②，见文末「追加」一节为何 ① 足以覆盖本场景）；
不碰任何渲染/取数/皮肤逻辑。

## 涉及文件

| 文件 | 改动 |
|---|---|
| `web/static/dom-write-guard.js` | **新增**（~90 行，经典脚本，零依赖） |
| `web/templates/{index,macro,macro_cn,timeline,backtest,settings}.html` | head 里各加 1 行 `<script src="/static/dom-write-guard.js?v={{ asset_v }}">`（放在 meta 之后、主题内联脚本之前） |
| `web/app.py` | `_ASSET_FILES` 加 `"dom-write-guard.js"`（否则改它不换 `?v=`，验证会吃旧副本） |
| `tasks/2026-10-17-dom-write-hardening/verify_dom_write_guard.py` | **新增**验收脚本（自动挑端口起 uvicorn + Playwright，三例） |

## 实施步骤

1. 先写验收脚本并**跑一次拿到红**（闸门 A）：三例中的 C2/C3 现在必然失败（哨兵还不存在 ⇒ 无 marker、无 warn）。
2. 新增 `web/static/dom-write-guard.js`（检测逻辑：行为探针 ×2 API，加载后 1.5s 复查一次 + 重复 id 计数）。
3. 6 个模板各加 1 行 + `web/app.py` 登记资源。
4. 重跑验收脚本 → 绿；再跑既有门禁（`verify_ui.py` + `pytest`）确认零回归。

## 验证命令

```bash
# 闸门 A / 本任务主回路（红 → 绿）
venv/Scripts/python tasks/2026-10-17-dom-write-hardening/verify_dom_write_guard.py

# 前端门禁（改了 web/templates 与 web/static ⇒ 必跑）
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py

# 后端契约
venv/Scripts/python -m pytest tests/ -q

# 闸门 B
grep -rn "\[DEBUG-" --include=*.py --include=*.js .
git status --short
```

## 测试 seam

- **seam = 页面启动时的 DOM 写入语义**（`Element.prototype.innerHTML` / `Node.prototype.textContent` 的 setter 行为）。
  可注入：Playwright `add_init_script` 在 document_start 改写成「前置插入」语义（与用户截图同款签名），
  以及一个「克隆节点并插进文档」的变体（覆盖重复 id 分支）。
- 不写常驻单测：本仓 `tests/` 是纯 Python 逻辑测试，没有浏览器 seam；本任务用**任务内验收脚本**（仓库既有惯例，
  同 `verify_ui.py` / `verify_skin.py`）。

## 预估 diff 范围

- 新增 ~90 行（哨兵）+ 6 行（模板）+ 1 行（`_ASSET_FILES`）+ ~150 行（验收脚本）。
- 不改任何既有行为：哨兵只读 DOM、只 console.warn、只写 `<html>` 上的 `data-*` 标记。

档位: T3 — 9 文件 / 0 调用方 / 正常环境行为不变 / 无覆盖测试（新建注入型验收）/ 预估 ~250 行

---

## 追加（同日，用户选 ①）：让本仓在被改写的环境里仍然单份渲染

用户先选 ③（只检测），随后追加「让本仓免疫（方案 ①）」。**文件集合不变**（仍是那 9 个：
哨兵文件扩写、验收脚本扩例、模板与 `web/app.py` 的接线不动）⇒ 档位维持 T3，无需重新声明。

### 目标

被改写的环境里，页面仍按「写入 = 替换」渲染 ⇒ 不再出现重复（用户可见症状消失）；
修不动时（对方把描述符锁成 non-configurable）**必须优雅降级**：页面照常渲染、如实打标记，不许更糟。

### 设计：修回「替换语义」，而不是「取回原生 setter」

第一版实现是「从同源空白 iframe 的 realm 取原生访问器覆盖回去」。**实测否掉了它**：

- 内容脚本的 `all_frames` 是常见配置 ⇒ **新 iframe 的 realm 同样被改写**，取回的「原生」就是被改写的那一个；
  本仓验收里 Playwright 的 `add_init_script` 正是「注进所有 frame」的行为，一次就把这条路堵死。
- 更糟的是**跨 realm 委派会把页面写崩**：实测注入层开始抛
  `Failed to execute 'insertBefore' on 'Node': parameter 1 is not of type 'Node'`，
  于是「修」比「不修」更坏（页面从「重复」变成「报错 + 渲染失败」）。

改用**语义修复**：给命中的 setter 套一层「**先清空目标元素的子节点，再委派给当前 setter**」的包装。

- 不依赖任何干净 realm ⇒ 不受 `all_frames` 影响；
- 不与改写层争「谁的原型函数是原生的」⇒ 不产生跨 realm 节点；
- 对方是「前置插入」还是「追加」都被抹平（清空后无论怎么加，结果都只剩新内容）；
- 清空只用 `firstChild` / `removeChild`（比 `replaceChildren` 更不容易被同族改写波及）；
- 只在**探针命中**时安装 ⇒ 干净环境零改动（不装、不 warn、不写标记）。

### 标记与证据（机器可读 + 点名肇事者）

| 标记 | 含义 |
|---|---|
| `<html data-dom-write-patched="innerHTML,textContent">` | 探针命中（写入语义被改写），含 warn 里的**当前 setter 源码片段** ⇒ 用于点名肇事扩展/用户脚本 |
| `<html data-dom-write-repaired="…">` | 已修回替换语义（复核通过） |
| `<html data-dom-write-repair-failed="…">` | 修不动（如描述符被锁）⇒ 页面降级为「仍会重复但可用」 |
| `<html data-dom-write-dup-ids="N">` | 克隆型注入：同一 id 出现 N 个（`getElementById` 只命中第一个副本） |

### 验收（扩到四例，仍走闸门 A：注入环境 → 红/绿）

`tasks/2026-10-17-dom-write-hardening/verify_dom_write_guard.py`（chromium + firefox 两引擎）：

- **C1** 干净环境 ×6 页：无 patched / repaired / dupIds、无 warn、无 pageerror（不得误报）。
- **C2** 前置语义注入：`patched` ✓ + warn 含 setter 源码片段 ✓ + `repaired` ✓ +
  页面内探针回到 `'b'` ✓ + **连点 3 次刷新后概览恒为 6 小卡**（症状消失）✓ + 零 pageerror。
- **C3** 克隆型注入：`data-dom-write-dup-ids > 0` + 一条说明重复 id 后果的 warn。
- **C4** 锁死描述符（`configurable:false`）：`patched` ✓ + `repair-failed` ✓ + 页面照常渲染 + 零 pageerror。

判据：**C2 的「连点刷新后仍 6 小卡」是用户可见症状的回归护栏**（未修复时该断言必红 —— 修前实测
3 次刷新后为 24 张）。

### 验证命令（追加 ① 后全量复跑）

```bash
venv/Scripts/python tasks/2026-10-17-dom-write-hardening/verify_dom_write_guard.py   # 主回路
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py            # 改了 web/static ⇒ 必跑
venv/Scripts/python -m pytest tests/ -q
grep -rn "\[DEBUG-" --include=*.py --include=*.js .
```
