# 行业板块两 tab 视觉对齐 + B-6b 探针根因修复（2026-09-19）

## 目标

用户反馈：「这两个结构不一致」→ 追加「我只要他们看起来整齐就行了」→ 追加「他们的列位置不整齐」。
即：**只做视觉对齐，不改数据语义**。

## 改动文件

| 文件 | 改动 |
|---|---|
| `web/static/style.css` | `#us-sectors .data-table { table-layout: fixed }` + `th:nth-child(n)` 显式列宽（50px / 27% / 19% / 22%，第 5 列吃剩余）+ `td { overflow:hidden; text-overflow:ellipsis }` 兜底 |
| `src/fetcher.py` | `_fmt_us_volume`：`$X.XB/M/K` → `$X.X亿`（与 A股侧 `f"{.../1e8:.1f}亿"` 逐字同款；保留 `$` 因币种不同） |
| `web/static/app.js` | `renderSectorAsOf`：「仅陈旧时标注」→「总是标注该 tab 的 as_of」；另修正一条过时注释（写着"没挂 change 监听"，实际 F2 整改时已挂） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | ① V-2/V-3 期望值去掉 `!= cur` 条件（**判据变严**）；② **`wrap_js` 首样本同步化 + 重试判据改写**（见下） |
| `docs/pitfalls.md` | 「预置位」一节补第二版修正（本次的核心产出） |

## 验证结果

- **列宽**（1440 档实测）：改前 A股 `[54,135,113,124,107]` vs 美股 `[56,165,117,108,88]`；
  **改后两侧均为 `[50,144,101,117,121]`**（逐列相同）、**无内容截断**、`#us-sectors` 卡高 249 未变。
- **标注**：`cnText='· 数据截至 2026-09-18'`、`usText='· 数据截至 2026-09-17'`，h2 高 19/19、card 249/249（V-5 零增高保持）。
- **验收**：`verify_ui` **ALL PASSED / EXIT=0**（连跑 2 次）。

## 遇到的问题

### ① 成交额格式改了但页面不显示 —— 数据的刷新路径

`/api/latest` 的板块数据读的是 **context 快照**（`_load_latest_context`），不是实时取数。
试跑 `snapshot_report.py --market us --time noon` 被**项目护栏**拦下：
`13:35:51 INFO 休市，us 时段=noon 无盘中数据，跳过生成`。
⇒ **最早生效点 = 周一 08:02 的 `daily_report`**（全量 `merge=False` 写 context）。
注意 A股收盘快照（`--market a-share`）**不会**更新美股板块（`us_sector_heat=None` → merge 保留旧值）。
**没有**手工改 context（改生成物 + 会把"格式改动"与"数据更新"混在一起）。

### ② 🔴 B-6b 从绿变红 —— 挖出探针的真根因（此前两次都当成"抖动"，是错的）

**现象**：改 CSS 后 `B-6b`（告警 ticker 回绕）稳定红，签名 `period=777 first=0 last=503 drops=[] armTries=20`。

**取证**：
1. **基线 A/B**（`git archive HEAD` + venv junction 建隔离副本，不动工作区）：基线 **绿**
   （`first=777 drops=[775] armTries=2`）⇒ 确认是本次改动触发。
   （基线另有 7 条自选列表红，因副本缺 `config.json`/快照，属环境差异。）
2. **逐帧诊断**（自写探针打印每帧 scrollTop + 滚动器 `state.pos/period`）：
   ```
   after-arm  931   (st.pos=931, st.period=933)
   f7         933   (st.pos=932.87)
   f8           0   (st.pos=0.13)   ← 滚动器**正常回绕**（app.js:442 `st.pos -= st.period`）
   ```

**真根因**：探针预置点 `start = period - 2` **距回绕点只有 2px**，而滚动器持续运行
（≈0.27px/帧 ⇒ **约 8 帧后自己就回绕**）。旧实现把首样本留给第一次 `requestAnimationFrame`，
于是 arm → 首帧之间只要有 >2px 延迟，位置已归零，**被旧判据 `out.length === 0 && cur < start-1`
误判成"摆位没生效"** → 重摆 → 再被抢先 → 20 帧耗尽 → 假红。
**本次改动只是让布局变快、把延迟推进了这个 2px 窗口**，不是 CSS 有 bug。

**修法**（判据未放松）：arm 后**同帧同步**取首样本；重试判据改为「**还没观测到回绕** + 位置回到起点附近」。
修后连跑 2 次 `armTries=0` 全绿。

### ③ CN-4e/4f/4g 间歇红

中国宏观「利率与流动性」有一格 `—`。手工实测 `_fetch_one('lpr'/'shibor'/'bond_10y')`
**全部正常**（155 / 2371 / 141 行）⇒ **AkShare 间歇性取数失败**，与本轮无关，复跑即绿。

## 下次注意

1. **"被本次改动触发"≠"本次改动有缺陷"** —— 断言若依赖时序窗口，任何扰动都能让它翻脸；
   判据要看**失败签名**（`first=0` 是"从未摆上"，`drops=[]` 是"没见到回绕"），并做基线 A/B。
2. **"先设状态再观察"的断言，还要问一句"这状态会不会自己往前走"** —— 被观测对象若持续运行，
   "摆位 → 观察"之间就有一个**隐含时间常量**。摆到"临界点前 N 像素"必须把 N 算够，或干脆同帧采样。
   （已写入 `docs/pitfalls.md`）
3. **纯 CSS 改动立即生效，数据格式改动要等数据链路** —— 两者生效时机不同，汇报时要分开说。
