# 执行日志 · 把自动循环滚动同样加到「告警记录」卡

> 对应计划：`tasks/2026-09-13-alerts-autoscroll/plan.md`
> 前置：`2026-09-13-news-autoscroll`（资讯卡自动滚动 + 亚像素根因修复）已验收
> 执行顺序：S-1 工厂化（先红观察）→ S-2 告警接线 → S-3 验证/记录

## 目标

`#alerts`（告警记录）与 `#news`（最新资讯）并排、同为 `max-height:132px` 滚动容器。把资讯卡上已验证的自动循环滚动同样加到告警卡：向上匀速、悬停暂停、保留手动滚动、`reduce-motion` 退化。

## 改动文件清单

| 文件 | 动作 | 内容 |
|---|---|---|
| `web/static/app.js` | 重构 | 滚动机制抽成 `makeAutoScroller(bodyId, itemSel)` 工厂（**每容器一份独立状态**）；实例化 `newsScroller` / `alertScroller`，暴露 `window.__scroll` 供断言读内部状态；`renderNews` 改用 `newsScroller`；`renderAlerts` 双份渲染 + `alertScroller.stop/bind/start` |
| `web/static/style.css` | +6 / −1 | `.news-clone, .alert-clone { display: contents }`（克隆半只为挂 `aria-hidden`，不产生盒子 → gap/分隔线均匀）；`reduce-motion` 兜底规则加上 `#alert-list` |
| `verify_ui.py` | 重构 + 扩展 | 探针改为**按 cfg 参数化**（`autoscroll_js/sample_js/wrap_js/halves_js/rate_js` + `_tpl`）；`assert_autoscroll(page, base_url, cfg)` / `assert_reduced_motion` / `assert_short_content` 三个通用函数；`CFG_NEWS`(prefix `A`) / `CFG_ALERTS`(prefix `B`) 各跑一遍 |
| `docs/pitfalls.md` | +5 条 | 见下 |
| `tasks/2026-09-13-alerts-autoscroll/journal.md` | 新增 | 本文件 |

**未改**：`web/app.py`、`src/*`、两卡的 `max-height`、`.news-item a` 的横滚、`NEWS_SCROLL_PX_PER_SEC`（两卡共用同一速度）。

## S-1 · 工厂化（不含告警接线）→ 先红

跑一次确认断言在测真东西：

```
A-* 18 条 → 全 PASS（工厂化未破坏资讯行为）
B-* 18 条 → 9 条 FAIL：
  B-1  (3, 3, 0)            无克隆半
  B-2  克隆半缺失
  B-4  [0,0,0,0,0,0,0]      不滚动
  B-5  (False, 0, 0)        无「滚动中」前置条件
  B-6b (-1, 119, 119)       无回绕
  B-7  {'n':1,'mismatches':[{'i':0,'h':[117,134]}]}
  B-8  0 px/s ；B-9  0      未滚动
  B-12a (1, 0, 117)         无克隆、周期 0
```
（B-3/3b/3c/6a/6c/6d/10/11 在改动前即绿 —— 它们是**护栏**而非红项。）

## S-2 · 告警接线 → 后绿

**`verify_ui.py` → ALL PASSED（A-* 18 + B-* 18 + A/B 各 2 条 reduce-motion / 短内容 = 40 条）**

| 断言 | 目标 | 实测 |
|---|---|---|
| B-1 双份内容 | `.alert-card` 数 == 接口 × 2 | **api=3 / dom=6 / clone=3** |
| B-2 克隆半 aria-hidden | true | **true** |
| B-3 容器高度 | ≤132 且 max-height=132px | **132 / 132px** |
| B-3b 超限时钳在 132px | ==132 | **132** |
| B-3c `#news` 与 `#alerts` 等高 | ±2px | **195 == 195** |
| B-4 自动滚动 | 递增 | 采样有增长 |
| B-5 悬停暂停 | 滚动中 → 0.6s 不变 | 通过 |
| B-6 回绕 | 只回绕一次且幅度 ≈ 周期 | **period=379 / drops=[376]** |
| B-7 两半逐条一致 | 0 不一致 | **0** |
| B-8 实测速率 | ≥8px/s | **15.95 px/s**（常量 16） |
| B-9 亚像素回归 | 4px/s 仍前进 | **scrollTop=9**（期望 8.8） |
| B-10 护栏 | scrollH ≤1240 / 无横溢 | **1220 / true** |
| B-11 reduce-motion | overflow-y:auto + 恒 0 | **auto / 0** |
| B-12 短内容（1 条） | 周期 ≤ clientHeight 且恒 0 | **period=121 ≤ 132 / 0** |

其它：`pytest tests/ -q → 548 passed`；三视口 `scrollH = 1220 / 1935 / 2539`（与改动前一致）。
A-12（资讯短内容）：`items=2 period=34 client=68` → 34 ≤ 68 且恒 0 ✓。

## 关键设计修正：循环周期改为 `offsetTop` 差

资讯卡用「前一半 `offsetHeight` 之和」算周期；但**告警列表是 flex 列 + `gap:4px`**，求和法会**少算 n×gap**（3 条差 12px）→ 回绕点会可见地跳一下。

改为：
```js
period = items[n].offsetTop - items[0].offsetTop      // 克隆半首条相对第一半首条的偏移
```
对 border 分隔（`.news-item`）与 flex gap（`.alert-list`）两种布局都精确，且与「克隆半是否包一层」无关（配合 `display: contents`）。实测告警侧 `period=379`、回绕幅度 `376`（差 3px 为采样点落在回绕后所致）✓。

## 帧率实测：两个滚动器**不会**更卡

（承前任务根因 B：滚动重绘会带动全页 backdrop-filter 重合成）

| 场景 | fps | 说明 |
|---|---|---|
| 两个滚动器同时跑 | **8.1** | `moves=32`（两卡都在动） |
| 只跑资讯 | **8.0** | 告警冻结在 151 |
| 全部停掉 | **57.5** | 对照 |

→ 成本由**每帧重绘**主导，**第二个滚动容器几乎免费**（同一帧内一起重绘）。⚠️ 该 fps 是无头软件光栅下的数字，**不能外推到你的真实浏览器**（GPU 合成下 blur 便宜得多）；如需进一步降低绘制成本，方向仍是根因 B 的两个选项（降 `--glass-blur` / 让卡片退出玻璃层）。

## 与 plan 的偏差

| # | 项 | 说明 |
|---|---|---|
| **D1** | 断言标签重编号 | 原 A-1~A-7/A-5c/A-5d 等拆成**统一体系**：资讯 `A-1`~`A-12`、告警 `B-1`~`B-12`（同一份通用实现跑两遍）。语义与覆盖点未减，只是编号规整化。 |
| **D2** | 短内容判据修正 | plan 写「半程 ≤ clientHeight」，实现与断言统一为**周期**（`offsetTop` 差）。⚠️ 断言不能再用 `scrollHeight ≤ clientHeight`：双份内容下 `scrollHeight ≈ 2×周期`，恒大于容器高（实测告警 1 条：`scrollHeight 242 > 132` 但 `period 121 ≤ 132` → 正确不滚）。 |
| **D3** | 新增 `display: contents` | plan 未提；克隆半包一层后若用普通块盒，`.alert-list` 的 flex gap 会在「第一半 → 克隆半」之间多/少一段间距 → 回绕点不齐。 |
| **D4** | 新增 `_tpl()` 模板替换 | 断言侧参数化实现方式（占位符替换），非行为变更。 |
| **D5** | 未改动速度常量 | 两卡共用 `NEWS_SCROLL_PX_PER_SEC = 16`（plan 未要求分开调）。 |

## 下次注意

- **一个页面有多个自动滚动器时，状态必须每容器一份**（本例从模块级 `_newsXxx` 全局改为 `makeAutoScroller()` 闭包）；否则两个循环互相踩（A 卡的速度/暂停会写到 B 卡）。
- **算「一个循环周期」不要用条目高度求和** —— flex `gap` / 外边距会让它偏小。用 `items[n].offsetTop - items[0].offsetTop` 最稳。
- **克隆半用 `display: contents` 包一层**：既能挂 `aria-hidden`，又不引入额外盒子（gap/分隔线保持均匀）。
- **「内容不足一屏」的判据是周期，不是 `scrollHeight`**（双份内容下后者恒大于容器高）。
- 多个动画容器的帧率成本**不是线性叠加**（实测 1 个 8.0fps / 2 个 8.1fps）—— 成本在「每帧重绘」而不在「几个容器」。
