# journal — 组合盈亏（自选列表的成本视角）

- **任务档**：`tasks/2026-09-20-portfolio-pnl/`（plan；**D-1=A / D-2=A / D-3=A** 由用户 22:0x 确认后写入 plan §10）
- **执行日期**：2026-09-20 22:0x → 2026-09-21 07:3x
- **前置**：P1-1 回测 UI ✅、P1-2 设置页 ✅（本任务被 P1-2 解锁：成本价录入界面复用设置页）

## 1. 改动

| 文件 | 改动 |
|---|---|
| `src/settings_store.py` | `_validate_stocks` 支持可选 `cost`（数字 > 0；None/空串/缺省 = 清除，不写键） |
| `web/app.py` | `_build_watchlist_payload`：透传 `cost`、算 `pnl_pct`（value/cost 任一缺失 = **None**）+ `overview{covered,total,avg_pnl_pct}`（等权） |
| `web/templates/index.html` | 自选卡表头加「持仓盈亏」列；卡头 `.h2-sub` 加 `#watchlist-pnl` 概览（D-3=A，零增高）；`watchlist-body` 骨架 colspan 5→6 |
| `web/static/app.js` | `renderWatchlist` 渲染盈亏列（色沿用本页 `pos/neg`）+ 概览；**pnl 为 None 时不渲染 `.chg-pill`**（纯文本 `—`） |
| `web/static/style.css` | `.col-pnl` / `.pnl-avg` 新类；极窄屏隐藏该列 |
| `settings.html` + `settings.js` | 自选表格加「成本价」输入列（可选；空 = 清除） |
| `verify_ui.py` | **P-6 拆成两条**（自选=6 / 其它表仍=5）+ 新增 `PF-*` 5 条 |
| 测试 | `test_settings_store`（cost 校验/落盘）+ `test_web` 4 条（有 cost / 无 cost / value 缺失 / 等权）+ R3 回归（快照比对不因 cost 失效） |

**存储层零改动**：`save_watchlist_snapshot` 原样透传 dict ⇒ 加 `cost` 后快照自动携带（已由 R3 用例锁死：`as_of` 仍来自快照，且不静默回退实时取数）。

## 2. 验证

| 项 | 结果 |
|---|---|
| `pytest tests/ -q` | **773 passed / 1 failed**（唯一红是既有 `test_us_sector::test_volume_format`） |
| `verify_ui.py` 全量 | **PASS 702 / FAIL 2 / SKIP 0**；`PF-1..PF-5` 全绿 |
| 剩余 2 条 FAIL | `MX-11` / `MX-11b`（BLS 经济数据此刻无值）——**本任务不碰 econ**；按验收分层设计保守报 FAIL 而非 SKIP（探针判 OK），与 P1-1 那次同源同类 |

## 3. 过程中的问题（都修了）

1. 🔴 **`colspan` 差点全局替换**：全文件有 10 处 `colspan="5"`（含 1 处注释里的），
   **只有 `watchlist-body` 那一行属于自选表**，其余 8 处属板块/美股等 5 列表格。
   第一版脚本按 `class="col-ico"` 定位也错了（3 个表共用）⇒ 最终**先锚定 `watchlist-table` 再取其后的 thead/tbody**，
   并把 P-6 断言拆成「自选=6 + **其它表仍=5**」两条 —— 后者正是**防误伤**的护栏。
2. 🔴 **P-4 被我的新列撞红**：P-4 判定「任何没有 pos/neg 类的 `.chg-pill` 都是坏 pill」，而"未录成本"的盈亏格是空类 pill
   （11 条）。**修法**：pnl 为 None 时**不渲染 pill**，直接输出纯文本 `—`（语义上也正该不染色）。
3. ⚠️ **R3 测试 patch 错了模块**：`web/app.py` 是 `from src.analyzer import load_watchlist_snapshot` ⇒
   patch `src.analyzer` 里的名字无效，必须 patch **`web.app.load_watchlist_snapshot`**（本项目既定纪律）。
4. ⚠️ 测试块被重复追加了一次（同名 def 两份）⇒ 已按函数名去重。
5. ⚠️ 用例自己写错两处：`out["stocks"]` 是**富化后**的行（不是原始 config）；快照时点键是 **`saved_at`** 不是 `as_of`。

## 4. 明确未做

- ❌ `shares` / 金额 / 市值 / 加权收益（D-1=A 只做百分比；概览已显式标注「未含份额」）
- ❌ 新页面 / 新持久化 / 新 cron；❌ 成本价自动获取（券商 API = 新依赖）
- ❌ 盈亏曲线 / 历史盈亏（需每日快照累计）
