# 计划：把资讯的自动循环滚动同样加到「告警记录」卡

- **日期**：2026-09-13
- **任务目录**：`tasks/2026-09-13-alerts-autoscroll/`
- **性质**：纯前端（`app.js` + `style.css` + `verify_ui.py`），后端零改动
- **触发**：需求方 2026-09-13「现在好了，给旁边的告警记录也加上这个功能」（前提任务 `2026-09-13-news-autoscroll` 已验收）

---

## 1. 目标

`#alerts`（告警记录）与 `#news`（最新资讯）并排、同为 `max-height:132px` 的滚动容器。把已验收的自动循环滚动**同样**加到告警卡上：向上匀速、悬停暂停、保留手动滚动、`reduce-motion` 退化。

## 2. 现状与要点

| 项 | 现状 |
|---|---|
| 机制 | `scrollTop` + `rAF` + **浮点累加器 `_newsPos`**（亚像素不被取整吞噬，根因 A 的修复） |
| 循环 | 内容渲染两遍，越过「一个循环周期」时 `-= 周期`（无缝） |
| 周期算法 | 资讯卡用「前一半 `offsetHeight` 之和」（`.news-item` 是 border 分隔） |
| ⚠️ 告警卡布局不同 | `.alert-list { display:flex; flex-direction:column; gap:4px }` → **周期 = 前一半高度 + n×gap**，用旧的求和法会**差 4px**（回绕处可见一跳） |
| 状态 | 目前是模块级单份 `_newsXxx` 全局；同时滚动两个容器 → **必须拆成每容器独立状态** |

**关键设计**：周期改为 **`items[n].offsetTop - items[0].offsetTop`**（克隆半首条相对第一半首条的偏移）——对 border 与 flex gap 两种布局都精确，且与「克隆半是否包一层」无关。

## 3. 要改的文件

| 文件 | 动作 |
|---|---|
| `web/static/app.js` | 把滚动机制抽成 `makeAutoScroller(bodyId, itemSel)` 工厂；实例化 `newsScroller` / `alertScroller`；`renderAlerts` 双份渲染 + 启动；`renderNews` 改用工厂 |
| `web/static/style.css` | `.news-clone, .alert-clone { display: contents; }`（克隆半包一层仅为 `aria-hidden`，不引入额外盒模型） |
| `verify_ui.py` | 断言片段参数化（A-* 改读 `window.__scroll.news.state`）；新增 B-1~B-6（告警卡） |
| `tasks/2026-09-13-alerts-autoscroll/plan.md` / `journal.md` | 本文件 / 执行记录 |
| `docs/pitfalls.md` | 追加（gap 布局的周期算法 / 多滚动器必须各自独立状态） |

**不改**：`web/app.py`、`src/*`、两卡的 `max-height`、`.news-item a` 的横滚、`NEWS_SCROLL_PX_PER_SEC`（两卡共用同一速度）。

## 4. 实施步骤

### S-1 · 工厂化（不含告警接线）→ 先红观察点
抽出 `makeAutoScroller()`；`renderNews` 改用 `newsScroller`；**`renderAlerts` 暂不动**。
断言侧参数化并把 A-* 改读新 API，**新增 B-1~B-6（告警）**。
**期望：A-* 全绿、B-* 全红**（证明 B-* 在测真东西）。

### S-2 · 告警接线
`renderAlerts` 渲染两遍（`.alert-clone` + `aria-hidden="true"`）→ `alertScroller.stop/bind/start`；CSS 加 `display: contents`。
**期望：全绿。**

### S-3 · 验证与记录
```
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
venv/Scripts/python -m pytest tests/ -q
```
+ journal（含 A-0/S-1/S-2 三档实测数字）+ `docs/pitfalls.md` 2 条。

## 5. 断言清单（B-*，告警卡）

| # | 断言 | 期望 |
|---|---|---|
| B-1 | `.alert-card` 数 == `/api/alerts` 条数 × 2 | 相等 |
| B-2 | 克隆半 `aria-hidden="true"` | true |
| B-3 | `#alert-list` 高度 ≤132 且与 `#news-body` 等高（并排护栏） | 成立 |
| B-4 | 内容超一屏 → `scrollTop` 递增（复合：先证明「在动」） | 递增 |
| B-5 | 悬停暂停（滚动中 → 0.6s 内不变） | 成立 |
| B-6 | 亚像素速率（4px/s）下仍前进（根因回归） | ≥3px / 2.2s |
| B-7 | 回归：`scrollH@1920 ≤1240`、无横溢、两卡等高 | 成立 |

## 6. 风险

| # | 风险 | 对策 |
|---|---|---|
| R1 | flex `gap` 让周期算错 4px → 回绕可见跳 | 周期用 `offsetTop` 差（§2 关键设计）；断言 B-4 + 目视 |
| R2 | 两个 rAF 同时跑 → 帧率进一步下降（根因 B：滚动重绘带动全页 blur 重合成） | 不变更速度；实测并记录 fps（不作为断言，环境相关） |
| R3 | 拆全局状态时影响既有 A-* 断言 | S-1 只改读取路径，跑一遍确认 A-* 仍绿 |
| R4 | `.alert-list` 空态（`<p class="empty">`）时误加双份 | 空态提前 return（不加 clone、不起滚动） |

## 7. 不做什么

- 不加快度/方向参数（两卡共用同一速度常量）。
- 不加暂停/播放按钮。
- 不改 `#news` 已有行为与断言语义。
