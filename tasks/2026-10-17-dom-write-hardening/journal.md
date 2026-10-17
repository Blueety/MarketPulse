# Journal · 2026-10-17 DOM 写入语义哨兵（方案 ③ 检测 + 方案 ① 免疫）

## 1. 目标与结论

用户报「首页会显示重复」。取证链（只读分析 → 机制确认）结论：**本仓没有产生重复的代码路径**，
重复来自**页面里的 DOM 写入语义被第三方脚本改写**（`el.innerHTML = x` / `el.textContent = x`
不再替换，而是「前置插入、旧内容留下」）。用户拍板处置顺序：**先 0（定位注入源）→ 再 ③（只检测）**，
随后追加 **①（让本仓免疫）**。本任务最终落地 **③ + ①**：哨兵在首帧前认出这类改写（含**肇事 setter 的
源码片段**，用于点名），并把写入语义**修回替换**（页面不再累积重复）；修不动时如实打标记、优雅降级。

### 1.1 取证链（为什么能排除本仓）

| 证据 | 读数 |
|---|---|
| 全仓 + git 历史有无克隆/原型改写 | 零 `cloneNode`、零 `defineProperty(...prototype...)`；前端唯一 `insertBefore` 是引擎 `inject()` 插两个**空** div（`.lg-inner` / `.lg-clone`，后者 `display:none`） |
| 6 种浏览器配置实测（无头/有头 × DPR1/2 × 1440/2560 × frost/refract，含滚动/6 次刷新/切范围/切主题/改窗口/切 tab） | DOM 恒为单份：概览 6 小卡、板块 5 行、1 个风险偏好块、1 个日期 chip、**0 个重复 id**、`lg-inner=lg-clone=12` |
| 用户截图的三条签名 | ① 复制件落在**正常排版节距**上、互不重叠、把卡片外框撑高（⇒ 真实 DOM 节点，非绘制假影）；② 日期 chip = `2026-10-16 周五`×4 + 末尾仍是初始占位 `—`，`#overview-body` = 4 组真实卡 + 最后 1 组**骨架屏**（首次渲染的产物）；③ `北京时间 14:45` 紧跟 `14:44`（同屏两个时刻 ⇒ 布局重复与绘制假影都做不到） |
| 机制复现 | 同一份代码 + 把 setter 改成「前置插入」语义跑一遍 ⇒ **逐项复现**上述形态（日期 ×4+`—`、板块 25 行、4 组+骨架、风险偏好 ×4） |

### 1.2 步骤 0：静态排查注入源（结论 + 边界）

| 嫌疑 | 结论 |
|---|---|
| omp/hapi 本体（`/d/hapi` 的 `cli` / `hub`） | **排除**：无 `addInitScript` / `evaluateOnNewDocument` / 原型改写，且 `cli hub` 内零 `innerHTML` |
| Firefox 扩展 **Long Screenshot** | **排除**：MV2 遗留实现，靠 `ctx.drawWindow` 截图，不碰 DOM |
| Firefox 扩展 **AdGuard** | **不符**：`vendors/tsurlfilter.js` 的 `prevent-innerHTML` scriptlet 确实重定义 `Element.prototype.innerHTML`，但语义是**吞掉写入**（`return` 不写），不会产生「重复」 |
| Firefox 扩展 **Mira Translator**（2026-10-16 19:30 装，与截图同期） | **存疑**：双语模式会**克隆块**并以 `insertAdjacentElement('afterend')` 插到原文之后（18 处 `afterend`）；但插入位置在原文**之后**，与「旧值被顶到最后」的签名不完全吻合 |
| **Tampermonkey 用户脚本** | **未能穷举**：Firefox 的 `storage/default/` 按源一目录铺开，全量扫描两次都超时（300s/240s 被杀）；要查得先按 UUID 定位到具体扩展的 `idb` |
| cua-driver / cua | 只有 pid 文件与界面覆盖层，未见页面注入 |

⇒ 静态侧只能把范围收窄到「翻译/脚本类扩展」，**无法闭合**。故把识别能力做进 ③ 的哨兵：
它跑在**出问题的那台环境里**，命中时把**被改写 setter 的源码片段**打进 console —— 片段通常直接点名肇事者。

## 2. 改动文件清单

| 文件 | 改动 |
|---|---|
| `web/static/dom-write-guard.js` | **新增**（哨兵：行为探针 + 写入语义修复 + 重复 id 检查；只在探针命中时安装包装 ⇒ 干净环境零改动；永不抛错） |
| `web/templates/{index,macro,macro_cn,timeline,backtest,settings}.html` | head 里各 +1 行 `<script src="/static/dom-write-guard.js?v={{ asset_v }}">`（meta 之后、主题内联脚本之前） |
| `web/app.py` | `_ASSET_FILES` +`"dom-write-guard.js"`（不登记 ⇒ 改它不换 `?v=`，验收吃旧副本） |
| `tasks/2026-10-17-dom-write-hardening/{plan.md,verify_dom_write_guard.py,journal.md}` | **新增**（计划 / 验收回路 / 本日志） |
| `docs/pitfalls.md` | +1 节「前端『内容重复』的取证与哨兵（2026-10-17）」 |

哨兵设计要点（详见文件头注释）：

- **行为探针**而不是源码特征：`el.innerHTML = 'aaa'` 再 `= 'b'`，读回应为 `'b'`（被前置化则 `'baaa'`）。探针用**游离节点** ⇒ 不触发布局、不影响页面。
- **两轮检测**：head 里**最先**执行（抓 `document_start` 注入）+ `DOMContentLoaded` +1.5s 复查（抓晚改写与克隆型；复查也会再修一次）。
- **证据（点名肇事者）**：`console.warn('[dom-write] …')`（含 API 名、实测行为、**当前 setter 的源码片段**）+ `<html data-dom-write-patched="…">`。
- **① 免疫 = 修回「替换语义」**（不是取回原生 setter）：给命中的 setter 套一层
  `set(v){ while(this.firstChild) this.removeChild(this.firstChild); return 原setter.call(this,v); }`
  ⇒ 对方是「前置插入」还是「追加」都被抹平；标记 `data-dom-write-repaired` / `data-dom-write-repair-failed`。
- **为什么不用「从干净 realm 取原生访问器覆盖回去」（第一版实现，实测否掉）**：内容脚本的 `all_frames`
  是常见配置 ⇒ 新 iframe 的 realm 同样被改写，取回的「原生」就是被改写的那一个（本仓验收里 Playwright 的
  `add_init_script` 正是「注进所有 frame」的行为）；更糟的是跨 realm 委派会把页面**写崩** —— 实测注入层开始抛
  `insertBefore: parameter 1 is not of type 'Node'`，于是「修」比「不修」更坏。
- **已知盲点**（写在文件头）：被改写的是 `insertAdjacentHTML` / `appendChild` 这类**方法**时探针看不到；
  对方把描述符设成 non-configurable 时修不动（如实报 `repair-failed`，页面降级为「仍会重复但可用」）。

## 3. 验证结果

| 命令 | 结果 |
|---|---|
| `tasks/2026-10-17-dom-write-hardening/verify_dom_write_guard.py`（闸门 A 主回路） | **修前红**：PASS 5 / FAIL 6（哨兵未落地，C2/C3 全红）；**③ 后绿**：chromium + firefox **52 / 0**；**① 后绿**：chromium + firefox **74 / 0**，exit 0 |
| ↳ 关键判据（C2，两引擎） | `patched` ✓ · warn 含被改写 setter 的**源码片段** ✓ · `repaired` ✓ · 页面内探针回到 `'b'` ✓ · **连点 3 次刷新后概览恒为 6 小卡（用户可见症状消失）** ✓ · 零 pageerror ✓ |
| ↳ 优雅降级（C4，两引擎） | 描述符被锁（`configurable:false`）⇒ `patched` + `repair-failed` + 页面照常渲染（6 小卡）+ 零 pageerror ✓ |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | **PASS 690 / FAIL 0 / SKIP 10**，`ALL PASSED (10 SKIPPED)`；SKIP 全部是 `上游 macro=DOWN econ=DOWN`（`HTTP 403`，本机无代理的既有行为），与本次改动无关 |
| `venv/Scripts/python -m pytest tests/ -q` | **869 passed**，12 warnings（既有的 matplotlib tight_layout 警告） |
| `grep -rn "\[DEBUG-" --include=*.py --include=*.js .` | 无输出（闸门 B ✓） |
| `git status --short` | 仅本次预期文件 + 一个**既有的**未跟踪 `_wd_check.py`（4 行时区探针，非本次产生，按闸门 B 应由其作者删除） |

验收四例（`verify_dom_write_guard.py`，每例都在 chromium 与 firefox 各跑一遍）：

- **C1 干净环境 ×6 页**：无 `patched` / `repaired` / `dupIds`、无 warn、无 pageerror（不得误报）—— 这一条同时验证 6 个模板的接线。
- **C2 前置语义注入**：见上表关键判据。**「连点 3 次刷新后仍 6 小卡」是用户可见症状的回归护栏**（未修复时该断言实测为 24 张）。
- **C3 克隆型注入**：`data-dom-write-dup-ids="1"` ✓ + warn 说明重复 id 的后果（`getElementById` 只命中第一个副本 ⇒ 其余副本冻结在旧值）✓。
- **C4 锁死描述符**：见上表优雅降级。

## 4. 遇到的问题

1. **「③ 只点名不修复」的断言一开始写成了 `miniCards > 6`**（靠「多次渲染会累积」）⇒ 在该验收窗口内只落了 1~2 次渲染，读数恒为 6，红。改成**直接探针**（在页面里连写两次读回 `baaa`）后与渲染次数解耦。
2. **静态排查两次超时**：`grep -rIl` 扫整个 `/d/hapi`（含 `node_modules`）300s 被杀；扫 Firefox `storage/default/` 240s 被杀。教训写进 pitfalls（先按 UUID 定位到具体扩展再扫）。
3. `verify_ui.py` 报 10 条 SKIP：不是回归，是上游不可用（`macro=DOWN econ=DOWN`）——按 `docs/commands.md` 的口径，SKIP ≠ 通过，已按提示先查上游。
4. **① 的第一版实现（从同源空白 iframe 的 realm 取原生访问器覆盖回去）被验收否掉**：Playwright 的 `add_init_script` 注进**所有 frame** ⇒ 新 iframe 的 realm 同样被改写，取回的「原生」就是被改写的那一个；且跨 realm 委派让注入层开始抛
   `insertBefore: parameter 1 is not of type 'Node'`（页面从「重复」变成「报错」）。改用「先清空子节点、再委派给当前 setter」后两引擎全绿 —— **这条弯路写进了 `docs/pitfalls.md`**（`all_frames` 是常见配置，别指望有干净 realm）。
5. 一次验收因 uvicorn 未在 30s 内就绪而中断（`wait_ready` 超时）⇒ 已把就绪超时放宽到 60s，并把 uvicorn 的 stdout/stderr 落 `%TEMP%` 日志、失败时打印尾部（下次同类失败可直接归因，不用猜）。

## 5. 下次注意什么

- 哨兵**必须**留在 head 里最先的位置：`document_start` 阶段注入的脚本只在首帧前能被抓到；晚改写靠 `DOMContentLoaded` +1.5s 复查兜底。
- 新增静态资源**必须**登记 `web/app.py` 的 `_ASSET_FILES`，否则 `?v=` 不变、验收吃旧副本。
- 报告「第三方改写了页面」这类问题时，要给**可复现的判据**（行为探针 + 源码片段 + 三条签名），不要只说「像是扩展干的」—— 本任务的 C2 就是那条回路。
- **判据要钉用户可见症状**：「标记出现了」只证明检测生效；`连点 3 次刷新后概览仍 6 小卡` 才证明免疫生效（未修复时该断言实测为 24 张）。
- 方案 ②（160 个写入点改用 `replaceChildren`）**未做**：① 的「先清空再委派」已覆盖本场景且改动面小得多；只有哪天连 `insertAdjacentHTML` 这类**方法**也被改写，才需要上 ②（真免疫，不依赖任何原型包装）。

## 6. 部署与线上验收（2026-10-17）

- 线上 = **华为云 ECS**（`https://123.60.176.219:8443/`，systemd + nginx + 每 5 分钟 `git pull --ff-only` **整仓**）⇒ 本次只需 `commit + push`：
  `fb046d3`（哨兵 + 免疫）已推送，**约 15s 后**线上即生效（timer 拉取），**无需重启**（模板 Jinja `auto_reload` 默认 True；静态资源按请求读）。
- 验收（本机 curl）：`/` 首页含 `dom-write-guard` **1** 处（原 0）、`/static/dom-write-guard.js` **200**（原 404）、
  **6 个页面全部包含**该脚本、指纹 `?v=1792217399`。
- 真浏览器验收（Playwright，`ignore_https_errors=True`，chromium + firefox 各一遍，脚本在 `%TEMP%`）：
  `hasGuard=true`；`patched/repaired/repair-failed/dup-ids` 全为 `null`（干净环境**零副作用**）；页面内探针 `writeSemantics='b'`（正常替换语义）；
  KPI 4 张 / 概览 6 小卡；液态玻璃 `glassEngine=frost`、`skinReady=1`；**零 `[dom-write]` warn、零 pageerror**。
- Railway 线：`b6dcb73` 把「Railway 决定下线」写进 `docs/deploy-ecs.md §4`（现状 404 `Application not found` + 关停步骤 + 仓库侧为何保留 `app.py`/三处配置）。
  ⚠️ **关停本身我做不了**：本机无 Railway CLI / `~/.railway` token / `RAILWAY_*` 环境变量 ⇒ 需要账号侧操作（Railway dashboard 删服务 + GitHub App 撤仓库授权）。
- **加固版（`fb385b8`）同样一条龙验过**：线上 `/static/dom-write-guard.js` 的 sha256 == 本地 `01e7b9bb…`（推送后约 **195s** 生效），
  真浏览器（chromium + firefox 各一遍）`hasGuard=true`、四个 `data-dom-write-*` 标记全 `null`、页面探针 `'b'`、概览 **6** 小卡、零 warn / 零 pageerror。

## 7. 部署后仍重复 ⇒ 持续复核（C5/C6）与「不许更糟」还原

**现象**：部署后用户浏览器里仍重复（截图：概览 6 小卡 → 真卡重复 + 末尾骨架）。线上侧已排除：
`dom-write-guard.js` 线上哈希与本地**逐字节一致**（`7bc327d3…`）、是 head 里第一个 `<script>`、6 页都带它、干净环境真浏览器验收零副作用。

**闸门 A（先红）**：验收加 C5/C6，对「只做首帧 +1.5s 两次检查」的版本实测 —— C5（晚改写，即哨兵最后一轮**之后**才改写入语义）
`patched=None`、探针 `'baaa'`、连点 3 次刷新后概览 **24** 小卡（6 → 24，与截图同形）；C6（修回后**再次**被覆盖）探针 `''`。⇒ 两条都红。

**修法**：④ 持续复核（setter 身份比对做廉价判据；3s 心跳 + DOM 变化 400ms 节流 + visibilitychange）。

**过程中两个真实教训**（都已进 `docs/pitfalls.md`）：

1. **strict 模式 + 顶层 try/catch = 静默死亡**：watch 状态变量漏声明 ⇒ `ReferenceError` ⇒ 整段复核被外层 catch 吞掉，
   验收表现为 C3/C5/C6 红而页面零报错（最难查的一种）。⇒ 外层 catch 现在写 `data-dom-write-guard-error` + `console.error`，
   验收每例都断言该标记为空。
2. **`<template>` 必须特判**：模板内容在 `.content`，元素 childNodes 恒空；改写层又常拿「当前 setter」当解析器
   （`const t = document.createElement('template'); 当前setter.call(t, v); 用 t.content`）⇒ 委派链落到模板上时，
   对方的 `this.insertBefore(t.content, this.firstChild)` 会把内容**丢空**（Chromium 实测 `t.content.childNodes.length === 0`），
   页面渲染成空白（比「重复」更糟）。⇒ 包装里模板一律绕开委派、用 `DOMParser` 自己解析填 `.content`；
   并且**修完复核不达标就还原**成动手前的描述符 + 停止再尝试该 API（「不许更糟」）。

**肇事者线索（静态排查结论）**：`ypud1q61.default-release` 里活跃扩展的 **updateDate** 与症状出现时间高度吻合 ——
**Mira Translator - Web Translation 3.5.8.8000，2026-10-16 19:30 更新**（重复第一次出现就在 10-16 当天）；
其次 AdGuard 5.5.3.5（10-14 更新，其 `prevent-innerHTML` scriptlet 语义是「吞掉写入」，与「重复」不符）。
另：hapi（`/d/hapi`）源码与 dist 里**没有**任何原型 setter 改写（只找到 e2e 的 `addInitScript` 与自家 UI 的 `cloneNode`）。

**用户侧实测（决定性，2026-10-17）**：在出问题的页面跑三行判据，得到

```json
{"mark":{"theme":"light","liquidSkin":"","glassEngine":"frost","skinMounted":"16","skinReady":"1"},
 "dup":[],"mini":12,"setter":"function innerHTML() { [native code] }"}
```

⇒ **`innerHTML` setter 是原生的、没有重复 id、但 `#overview-body` 有 12 张卡（应 6）** ⇒ 线上那台**不是机制 (A)「写入语义被改写」**，
而是 **(B) 有脚本克隆 DOM 块插在原文之后**（本站代码与哨兵都无责；`<html>` 上没有任何 `data-dom-write-*` 标记 = 哨兵安静，这是正确行为）。
⇒ 本节的 C5/C6 修复（112/0 全绿）修的是机制 (A) 的真实故障模式，**不解决用户当前这条**；用户当前这条的正解 = 关掉/排除该扩展。
两种机制的判别命令与本次实测数据已写进 `docs/pitfalls.md`（「两种机制 + 一条命令分清」）。

**门禁结果（2026-10-17）**：`pytest` **869 passed** ✓；`verify_ui` 首跑 **1 条 FAIL**（`CS-2b`，crosshair 吸附组）——
复现证明是**该组固有抖动、与哨兵无关**：把哨兵用 `page.route(..., abort)` 整条拦掉再连跑 3 次，红的是同一组
（`CS-8 375 档` 3/3 红、`CS-8b` 2/3 红、`CS-2b` 3/3 绿）；带哨兵时同样是这一组在红。
⇒ 判定与复现姿势写进 `docs/pitfalls.md`（「前端验收 verify_ui 的 crosshair 组会随机红」）。
**复跑结果：`ALL PASSED (10 SKIPPED)`** ✓（10 条 SKIP 全是上游 macro/econ 不可用，非回归）⇒ 抖动结论成立。

## 8. 涉及的 ADR

无。三条准入不齐（改动易撤销：一个 `<script>` 标签 + 一个自包含文件），决策记在本 journal 与 `docs/pitfalls.md`。
