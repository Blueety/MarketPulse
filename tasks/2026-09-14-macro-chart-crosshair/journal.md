# 执行记录：宏观数据页主图加悬停水平参考线（crosshair）

- **日期**：2026-09-14
- **计划**：`tasks/2026-09-14-macro-chart-crosshair/plan.md`
- **前置**：`2026-09-11-chart-hover-crosshair` ✅（首页已实现）· `2026-09-14-macro-page` ✅ · `2026-09-14-macro-page-refine` ✅
- **改动文件**：`web/static/chart-crosshair.js`（新建）、`web/static/app.js`、`web/static/macro.js`、`web/templates/index.html`、`web/templates/macro.html`、`web/app.py`（1 行，见 §4）、`tasks/2026-09-11-frontend-bento-redesign/verify_ui.py`
- **未改**：`src/*`、`style.css`（crosshair 是 canvas 绘制，不走 CSS）、宏观页模块结构、图表数据口径

---

## 1. 结论先行

| 计划项 | 结果 | 实测 |
|---|---|---|
| XC-1 宏观页挂上插件 | ✅ | `plugins=['hoverCrosshair']`（**顺序错会静默失效**，见 §3）|
| XC-1b 读数口径可注入 | ✅ | 实例级 `formatter` 已注入 |
| XC-2 黄金 = 真实价（**不是 `+4286.6%`**）| ✅ | `$4500.87`（轴值 4500.871）|
| XC-3 10Y = 3 位小数 + `%`（**未被二次换算**）| ✅ | `4.501%`（轴值 4.50087；若踩二次换算会是 `0.450%`）|
| XC-4 全部对比 = 纯指数数字 | ✅ | `134.14`（轴值 134.144）|
| XC-5 横线跟手 | ✅ | 不同 Y 的画布指纹不同 |
| XC-6 移出绘图区隐藏 | ✅ | `$crossY === null` |
| XC-7 切范围重建后不丢插件 | ✅ | 新实例 `plugins=['hoverCrosshair']` + formatter |
| XC-9 console 干净 | ✅ | 悬停交互期间 error = 0 |
| XC-8（plan：首页 CS-*/F-7a 回归）| ✅ | 全量验收里 `CS-1 / CS-2 / CS-3 / CS-4 / CS-5 / CS-6 / CS-7a / CS-7b / F-7a` 全绿 |
| 全量验收 | ✅ | `verify_ui.py` **ALL PASSED**；`pytest tests/ -q` **620 passed** |

抽出共享文件后，首页 crosshair **行为逐字节不变**（插件的 `id` / `$crossY` / `$crosshairLabel` / 1px 节流 / 轴侧动态 / `afterDatasetsDraw` 全部原样，默认兜底仍是 `fmtAxisPct`）。

---

## 2. 先红后绿（基线用**提交级回退**取得）

```text
改动前（macro.js 回退到 36189b8 = 加入 crosshair 之前的提交）
  FAIL XC-1  (actual=[])            ← 宏观页图表 config.plugins 为空
  FAIL XC-1b / XC-2 / XC-3 / XC-4   ← $crosshairLabel 为 None（根本没有气泡）
  FAIL XC-5                         ← 两次 Y 的画布指纹相同（没有横线）
  FAIL XC-7
  FAILED: 7 条
改动后：ALL PASSED（同一批断言）
```

⚠️ **`git stash` 取基线在本项目里会空跑**：自动提交 cron 每隔几分钟就把工作区提交掉，
`git stash push` 会输出 `No local changes to save`（本次实测踩到）。正确做法：
`git log --diff-filter=A --format=%H -- <新文件>` 找到引入改动的那次提交，
`git checkout <parent> -- <目标文件>` 临时回退 → 跑 → `git checkout HEAD -- <目标文件>` 恢复（结束后核 `git status --short`）。

---

## 3. 本次踩到的**真缺陷**：插件选项里的函数会被 Chart.js 立即调用

按 plan §4.2 把读数格式化器注入到 `options.plugins.hoverCrosshair.formatter`，**页面直接抛异常**：

```text
TypeError: Cannot convert object to primitive value
    at isFinite (<anonymous>)
    at macroCrosshairFormatter (macro.js:264)
    at Object.get (chart.umd.min.js)          ← 只是**读** `c.options.plugins.hoverCrosshair`
```

**根因**：Chart.js 把插件选项当 **scriptable option** 解析 —— 读到函数值时会**立即以 context 调用**它
（期望 `(ctx) => value`），而不是把它当数据。我们的 `formatter(v, chart)` 收到的是 **context 对象**，
`isFinite(object)` 立刻抛错。也就是说：**`options.plugins.<id>.<fn>` 不是"存函数"的地方**。

**改法**：新增工厂 `window.makeHoverCrosshair({ formatter })`，返回**实例级插件对象**（函数挂在插件对象上，
`config.plugins` 是纯数组、不经过选项代理）：

```js
plugins: [window.makeHoverCrosshair({ formatter: macroCrosshairFormatter })]
```

插件内部 `resolveFormatter(chart)` 只从 `config.plugins` 里按 `id === 'hoverCrosshair'` 取那个对象读 `formatter`
→ 取不到则回落到 `window.__defaultCrosshairFormatter`（= `fmtAxisPct`）→ 首页行为不变。
`id` 不变 → CS-1 / CS-7b 仍成立。

⚠️ 探针也踩了同一个坑：断言脚本里读 `c.options.plugins.hoverCrosshair` 同样会触发解析 → 探针改成只读 `config.plugins`。

---

## 4. 与计划的偏差（诚实清单）

1. **标签用 `XC-*` 而非计划写的 `MX-*`**：`MX-1..MX-15` 已被宏观页断言（`assert_macro_page`）占用，
   重名会让失败报告无法定位。断言内容与 plan X-4 表格一一对应（XC-1~XC-9，其中 XC-8 由既有 `assert_crosshair` /
   `assert_fidelity` 覆盖，不重复断言）。
2. **`web/app.py` 改了 1 行**（计划 §5 写"不改 web/app.py"）：`_ASSET_FILES` 必须登记 `chart-crosshair.js`。
   该文件里有一行明确注释「新增前端文件记得加进来 —— 否则改它不会换 URL，验证时吃旧副本」，
   不登记就正好踩这条自定的坑。除这一行外 `web/app.py` 未动。
3. **`state.mode` / `state.activeKey` 不存在**（计划 §4.3 的示例代码用了这两个名字）：
   真实的判据是 `state.pick === "__all__"`、品种键取 `state.pick`；照抄示例会让 `multi` 恒为 false
   且 `unitOf(undefined)`。另：计划引用的 `macro.js:244-246/270/295` 行号已被 `macro-page-refine` 推移。
4. **顺带去掉两份重复实现**：`cssVar` 原在 `app.js` / `macro.js` 各一份、`withAlpha` 也是两份 →
   随插件一起收敛到 `chart-crosshair.js`（两页业务脚本仍裸调用同名全局函数，调用点零改动）。
   口径按 **app.js 原实现**统一（只处理 hex），因为本页 `--c-*` token **实测全是 hex**
   （`--c-axis-tick: #86868b/#8492A6` 等），故两页行为都不变；不做"rgb() 也改写 alpha"的增强，
   那会悄悄改变首页网格线透明度。
5. **黄金气泡带 `$` 前缀**：plan §4.3 的代码是 `u === '$' ? u + s : s + u`（前缀），
   而表格里的期望值写的是 `4386.60`（无前缀）。按**代码**实现（`$4500.87`）。

---

## 5. 遗留（未做，非本次范围）

- **单位位置在图表内不统一**：悬停气泡是 `$4500.87`（前缀），而**图表 tooltip** 是 `4994.01$`（后缀，既有实现）。
  计划 §9 明确「不改宏观图现有 tooltip」，故保留现状；若要统一，建议单开一个小任务（两处都改成前缀更符合货币写法）。
- 未做 `Chart.register`（保持内联插件，避免影响其它实例）；未引入任何新依赖/CDN。
- `macro.js` 与 `app.js` 现已共享 `chart-crosshair.js`，但**shell 行为**（主题 / 移动端抽屉 / 顶栏数据日）
  仍是两份复制 —— 按文件头注释的约定，下次涉及该区域时应抽 `shell.js`。

---

## 6. 验收原始输出

```text
plugins=['hoverCrosshair'] hasFormatter=True axisPos=right
gold:   label='$4500.87' axis=4500.871080139373
10Y:    label='4.501%'   axis=4.5008710801393725
all:    label='134.14'   axis=134.14375113393058
===== 结果 =====
ALL PASSED                                  （verify_ui.py 全量：首页 + CS/F + MX + M + XC + KY + Firefox）
620 passed, 10 warnings in 49.03s           （pytest tests/ -q）
```

截图：`%TEMP%/marketpulse-verify/shot-macro-crosshair.png`（黄金模式悬停：虚线 + 轴端 `$4500.87` 气泡 + tooltip 并存）。
