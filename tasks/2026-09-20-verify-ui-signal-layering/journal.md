# journal — UI 验收脚本的信号分层（G8）

- **任务档**：`tasks/2026-09-20-verify-ui-signal-layering/`（`plan.md` 定稿；§10 三项已裁定 D-1=A / D-2=A / D-3=做）
- **执行日期**：2026-09-20 13:3x（本机直连；上游 Yahoo/BLS 当时均可用）
- **角色**：Phase 3 Step 3.6 执行者（按 plan 实施 + 验证）

## 1. 目标

`verify_ui.py` 把三类性质不同的失败混在同一个 `FAILURES` 里输出 `FAILED: N 条`
（① 代码回归 ② 上游不可用 ③ 环境差异）⇒ 真回归被红色背景淹没。
本任务引入三态 `PASS / FAIL / SKIP`，**只把"上游确证不可用"的失败降级为 SKIP**，不改任何判据。

## 2. 改动文件清单

| 文件 | 改动 |
|---|---|
| `verify_ui.py`（+约 190 行） | ① `SKIPPED` 列表 + `N_PASS` 计数 + `UPSTREAM` 快照；② `probe_upstream()` + `_probe_get()` + `_probe_bls()`（**直连** Yahoo chart / BLS，**不 import `src.fetcher`/`web.app`**）；③ `check()` 加 `deps=()` 与三态分支；④ 13 处断言补 `deps=`（见 §4.2）；⑤ `summarize_and_exit()`（三态汇总 + `--strict` + SKIP 占比护栏）；⑥ `report.json` 加 `skipped` / `upstream` 键；⑦ `assert_firefox_scrollbar` 的 SKIP 改为**结构化**入列；⑧ `main()` 在跑断言前探一次上游并打印 |
| `docs/commands.md` | `verify_ui.py` 行补三态语义 + `--strict`；「何时跑什么」新增「看到 SKIP 时」一行 |
| `docs/system-overview.md` | §9 **G8 状态更新**（判据分层已完成 + 实测数据 + 仍开放项 + N-12 已非红） |
| `docs/frontend-structure.md` | §7 硬约束新增 11b「验收三态语义」 |

**不动**：`web/**`、`src/**`、其它 tests、**所有既有断言的阈值与期望值**（本次只加"归因"，不改"标准"）、
`style.css`（N-12 已实测通过，不改）。

## 3. 验证结果

### 3.1 第①轮：上游正常时全量跑（改动后 = 基线）
```
PASS:   679
FAIL:   0
SKIP:   0
上游探测: macro=OK econ=OK
ALL PASSED        EXIT=0
```
- **0 SKIP** 正是预期（上游可用 ⇒ 绝不产生 SKIP），说明 `deps=` 标记没有误伤。
- `report.json` 新键已验证：`skipped: []`、`upstream: {macro: True, econ: True, detail: {macro: "HTTP 200", econ: "HTTP 200"}}`。
- 重构（把汇总抽成 `summarize_and_exit`）后**又完整跑了一遍**，结果逐字一致（679/0/0）。

### 3.2 第②轮：模拟"上游不可用"（**不改代码**）—— 关键验证
手法：把 `HTTP(S)_PROXY` 指向死端口 `127.0.0.1:9` 且**保留 `NO_PROXY`**（localhost 绕过）
⇒ 本地服务照常可达，但**探针与 app 取上游都失败**。实测：

| 项 | 结果 |
|---|---|
| 对照（正常环境）probe | `macro=True econ=True` |
| 死代理 probe | `macro=False econ=False`（`URLError: [WinError 10061] 目标计算机积极拒绝`） |
| `assert_macro_page` 结果 | **SKIP 10 条 / FAIL 0 条** |
| 降级为 SKIP 的标签 | `MX-6` `MX-6b` `MX-7` `MX-8` `MX-9` `MX-9b` `MX-10` `MX-11` `MX-11b` `MX-13` |
| `FAILURES` | **空** ✔ |

⇒ **分层真的生效**：上游不可用时那 10 条**从 FAIL 变成 SKIP，而不是留在失败里**；
且未标 `deps` 的断言（如 `MX-15` console error、`MX-14a/b` 布局）不受影响。

### 3.3 机制级决策表（plan §3.3 两条硬约束）
| 情形 | 期望 | 实测 |
|---|---|---|
| `deps=()` + 失败 + 上游 DOWN | FAIL（永不禁用） | ✅ 进 FAILURES |
| `deps=("macro",)` + 失败 + probe 判 DOWN | SKIP | ✅ 进 SKIPPED（带 reason） |
| `deps=("macro",)` + 失败 + **上游 UP** | **FAIL** | ✅ ⇒ **"SKIP 不会掩盖我们的 bug"** |
| 断言成立（任意 deps） | PASS | ✅ 两者都不进 |
| probe：200 但**响应无法解读** | 视为**可用** | ✅ 不降级 |
| probe：**超时** | 视为**可用** | ✅ 不降级 |
| probe：明确非 2xx（HTTPError） | 判**不可用** | ✅ HTTP 404 → False |

### 3.4 退出码与护栏（验收标准 #5）
| 情形 | 期望 | 实测 |
|---|---|---|
| 仅 PASS（strict=False） | 0 | ✅ |
| 仅 SKIP（strict=False） | 0 + 醒目提示 | ✅ `ALL PASSED (3 SKIPPED)` |
| 仅 SKIP（**strict=True**） | **1** | ✅ |
| 有 FAIL | 1 | ✅ |
| FAIL + SKIP | 1 | ✅ |
| `SKIPPED > 总数×50%` | 仍 0，但打印 🔴 环境不可信告警 | ✅ |

### 3.5 全量单测
`pytest tests/ -q` → **740 passed / 1 failed**（唯一红仍是既有 `test_us_sector::test_volume_format`，与本轮无关）。

## 4. 遇到的问题与处置

### 4.1 `urllib` 的默认 opener 是**缓存的**（harness 踩到，值得记）
第②轮最初把 `os.environ` 改掉后直接调 `probe_upstream()`，结果**仍判上游可用** ——
因为 `urllib.request.urlopen` 用的是**第一次调用时构建的全局默认 opener**，
`ProxyHandler` 在构建时就把 env 读完了 ⇒ 之后改 env 不生效。
修法（仅 harness 需要）：`urllib.request.install_opener(urllib.request.build_opener(ProxyHandler()))` 重建。
> 生产无影响：`probe_upstream()` 每次进程只调一次（`main()` 开头）。

### 4.2 `deps=` 的取舍：我没有照抄 plan §2.3 表格
plan §2.3 把 `MX-14a/b`、`MX-15`（布局 / console error）也列进了"依赖上游"。**我没标**，
判据是**"该断言在没有上游数据时是否本就该成立"**：
- 上游挂了页面显示「数据暂缺」——**空态也必须不横向溢出、不报 console error**，否则那是我们的 bug。
- 这与 plan 自己在 §2.4① 用来举例的 `MX-11c`（「不含最新/实时」空态也该过）**是同一条原则**。
反过来我**补标**了 plan 没列的 `MX-10`（历史宏观环境 3 行 = 服务端由宏观数据派生，无数据必然不成立）。
最终标记集与"死代理下真实失败集"**完全吻合**（10 条一一对应，见 §3.2），说明标记既没漏也没多。
**刻意不标**的（并写明理由）：`MX-8b`（胶囊高亮=纯 UI）、`MX-9c`（判据本身把「样本不足」当合法）、
`MX-11c`（空态也该成立）、`MX-14a/b`、`MX-15`、`M-1/M-1b`、`M-3` 系列结构项、`M-9/M-10/M-10b`、`XC-1b/5a/6/9`。

### 4.3 为了让验收标准 #5 可验证，把汇总抽成了函数
`--strict` 的语义（"有 SKIP 即 1"）原先内联在 `main()` 尾部，**无法被单独验证**。
抽成 `summarize_and_exit(strict)` 后，§3.4 的 6 种情形都可直接调用验证 ——
这不是重构洁癖，是**"不接受应该可以"**的要求（否则 `--strict` 只能靠"我读了代码觉得对"）。

### 4.4 N-12 **不需要修**（plan §3.4，实测复核）
全量跑时 `N-12a` / `N-12b` **都 PASS**（`scrollbarColor = rgb(213,218,225) rgba(0,0,0,0)`、
`gateScrollbarWidth = thin`）⇒ 与 plan §2.4② 的独立探针结论一致。**G8 那 2 条红是 09-16 快照**。
按裁定：**判据保持原样**（`deps=()`），继续作回归护栏；**没有**改 `style.css`、**没有**把它塞进 SKIP。

### 4.5 🔴 基线 A/B 的比对口径必须调整（plan §6 明确要求写进本 journal）
本次改动**改变了失败集合的形状**（FAIL → SKIP）⇒ **不能直接比条数**。
正确口径：**比较「`FAIL` ∪ 归因于上游的 `SKIP`」与旧基线的 `FAIL` 集**。
即：若旧基线有 12 条红、本轮是 0 FAIL + 10 SKIP，**判定为"新增 0"**（那 10 条被正确归因到上游），
而不是"从 12 降到 10 = 修好了 2 条"。**后人若按条数比会得出完全错误的结论。**

## 5. 下次注意什么

1. **`SKIP` 不是绿灯**：看到它先读 `上游探测:` 那行，再去查上游；不要改前端代码。要"零未判定"就用 `--strict`。
2. **新写断言默认 `deps=()`**；只有**确证依赖上游数据**才标，且**"空态也该成立"的绝不许标**
   —— 多标就是给自己造一个掩盖 bug 的开关。
3. **探测必须独立于被测链路**（直连上游 URL），这是整个分层唯一的安全性来源；别为了"复用"去 import
   `src.fetcher` / `web.app`。
4. **探测不确定时一律视为可用**（超时/无法解读/自身异常）⇒ 宁可报红，都不误判成 SKIP。
5. 改 `os.environ` 里的代理后要**重建 urllib opener**，否则测的还是旧代理。
6. `MP_VERIFY_UPSTREAM_DOWN=1` 只用于**验证分层机制本身**（强制判 DOWN），不要拿它当"让测试变绿"的开关。

## 6. 明确未做（与 plan §9 对照）

- ❌ 未放松任何判据（阈值 / 期望值 / 断言数量全未动）
- ❌ 未让探测复用 `src/fetcher` / `web.app`；❌ 未做"数据为空就 SKIP"的宽松判定
- ❌ 未把 N-12（Firefox 引擎差异）混进上游 SKIP 机制；❌ 未改 `style.css`
- ❌ 未改 `web/app.py`（不给验收提供"失败原因"字段 —— 那会破坏探测的独立性）
- ❌ 未解决 G8 建议①（给 Yahoo 走代理/换源）—— 独立的数据源任务
