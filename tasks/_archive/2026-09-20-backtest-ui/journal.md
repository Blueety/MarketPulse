
## 5. 验证结果（最终）

| 项 | 结果 |
|---|---|
| `pytest tests/test_backtest.py` | **12 passed**（10 条原样未改 + 2 条新增护栏） |
| `pytest tests/test_phase27.py` | **29 passed**（`bt.render_report` / `bt.collect_triggers` 用法不受搬迁影响） |
| `pytest tests/test_web.py -k backtest` | **4 passed**（契约 / **不缓存** / 空态降级 / 页面可开） |
| `pytest tests/ -q` | **748 passed / 1 failed**（唯一红仍是既有 `test_us_sector::test_volume_format`） |
| `scripts/backtest.py` CLI | stdout 逐行一致、**md 报告逐字节相同**（搬迁前后 diff 为空） |
| `verify_ui.py` 全量 | **PASS 689 / FAIL 2 / SKIP 0**（2 条 FAIL 见 §5.1，均与本任务无关） |

### 5.1 全量里仅有的 2 条 FAIL = BLS 上游瞬时状态（非本任务）
`MX-11` / `MX-11b`（BLS 经济数据月份 / 4 项）。**取证**：
- 此刻 `/api/econ` 返回 4 条序列但**最新值全 None**（`as_of 2026-08`、`failed=None`）——
  典型于 BLS v2 免配额超限时「HTTP 200 但 body 无数据」（与 09-16 G8 记录的"BLS 亦取不到 as_of"同类）；
- 本任务**不触碰任何 econ 代码**；同日 18:0x 全量跑时这两条曾 PASS（上游当时有数据）；
- 按验收分层的设计，探测判 OK ⇒ 这 2 条**报 FAIL 而非 SKIP**（保守，符合 plan §3.3 约束②）。
> 已知局限（记入 G8）：探针证明"BLS 可达"，证明不了"app 的具体请求拿到数据"——
> BLS 免配额超限恰好是"200 + 无数据"，探针无法区分。**不改**（改了会削弱探针独立性）。

### 5.2 🔴 修掉一个我自己引入的真 bug：`verify_ui.py` 入口块位置
`BT-*` 组用 `cat >>` 追加到文件**末尾**，但 `if __name__ == "__main__": sys.exit(main())` 在它**前面**
⇒ 直接以脚本运行时 `main()` 在 `assert_backtest` **尚未定义**时被调用 → `NameError`（EXIT=1，且
**没有任何 FAIL 行**，表现为"莫名崩在最后"）。**import 方式**（临时 runner）没问题 ⇒ 险些漏检。
**修法**：把入口块移到文件**真正的末尾**。**教训**：向一个"末尾是入口块"的脚本追加函数，
必须同步把入口块挪到最后（或改用 import 式 runner 并全量复跑）。

### 5.3 F-5 还有**第五处**硬编码（plan §2.3 只列了三处 navCount）
全量首跑 `F-5` 变红，但 `navCount=12 / navDisabled=1 / navBad=[]` 全对 ⇒ 断言里**还有别的**：
`sorted(f["macroHrefs"]) == sorted(["/macro","/macro/cn","/timeline"])` —— **跨页 href 数组**也是写死的。
已补 `/backtest` 进数组 + 改 label 文案（`nav=12（…4 跨页…）`），并在断言注释里写明
**"本断言有两处硬编码：navCount 值 + macroHrefs 数组"**。

### 5.4 plan 的一处笔误（已在实现中按事实处理）
plan §2.3 / §5 Step 5 说 navCount 写死**三处**（`F-5:1027` / `CN-7:2038` / `TL:3851`）——
实测是**四处**：第四处是同日鉴权任务加的 `AUTH-5`（`d["nav"] == 11`）。
四处已全部改为 12，并把"navCount 四处 + F-5 的 href 数组"写进 `docs/frontend-structure.md` §7-18。

### 4.1 补充：涨跌色冲突的最终裁定
全站既有 `.up = var(--green)` / `.down = var(--red)`（`.mac` 与 `.tl` 两处一致，
`docs/pitfalls.md:214` 的"休市绿字"也印证），文档**没有**"红涨绿跌"的决策记录。
plan 写的「红涨绿跌」会让 /backtest 与 /macro、/timeline **同概念反色**。
⇒ **沿用既有口径**（`.bt .up { color: var(--green) }`），plan 该条**未采纳**；已写进
`style.css` 的 `.bt-*` 段注释与 journal。若要改中国习惯，那是跨三页的决定（涉及 .mac/.tl/.bt 三段 + 各 JS 的 `cls()`）。
