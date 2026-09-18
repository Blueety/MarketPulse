---
name: ui-verify-assertion
description: 给 tasks/2026-09-11-frontend-bento-redesign/verify_ui.py 新增一组 UI 断言（含 mock 夹具）时用。覆盖：红→绿方法论、HEAD 隔离副本、完成标记判读、全量/基线集合比对、必踩的三个 Playwright mock 坑。
---

# 给共享验收脚本新增一组 UI 断言

适用：给 `verify_ui.py` 加 `XX-*` 断言组（本项目已做 5 次：`NA-*` / `UX-*` / `PW-*` / `QM-*` / `MX-*` 族）。
目标不是"跑绿"，而是**证明这组断言真的能抓住它要抓的缺陷**。

## 0. 前置

- 断言标签**禁用 GBK 外字符**（`⇒` 等）：`print` 在 cp936 控制台抛 `UnicodeEncodeError` → 整个脚本中途死。
  `↑`/`↓`/`→` 在 GBK 内，可用。
- 断言标签前缀先 `grep` 查重（`grep -oE "^  (PASS|FAIL)  [A-Z]+-" ...`）：撞名会让失败报告无法定位。

## 1. 先写断言，跑"改前红"

```bash
# 建 HEAD 隔离副本（不动工作区；外部 cron 每几分钟提交 ⇒ git stash 不可靠）
T="$TEMP/mp-base-xx"; rm -rf "$T"; mkdir -p "$T"; git archive HEAD | tar -x -C "$T"
cp -r context/. "$T/context/"; cp -r data/. "$T/data/"
cp tasks/2026-09-11-frontend-bento-redesign/verify_ui.py "$T/tasks/2026-09-11-frontend-bento-redesign/"
# venv 用 junction 指回（PowerShell: New-Item -ItemType Junction -Target D:\AGENT\MarketPulse\venv）
```

探针脚本落 `%TEMP%`（**不落仓库**），结构照抄既有 `mp_*_probe.py`：
importlib 加载 `verify_ui` → 覆盖 `vu.ROOT` → 自己起 uvicorn（`vu.free_port()` + `vu.wait_ready`）
→ 包 `try/except` 调被测断言组 → **崩溃时打印 `★ XX 组崩溃（未跑完）★` + traceback，退出码 2**
（与"有失败"的 1 区分）→ 正常结束打印 `XX-COMPLETE` 完成标记。

## 2. 判读纪律（三条，缺一条就会被骗）

1. **先看完成标记**（`ALL PASSED` / `FAILED: N 条` / 探针的 `XX-COMPLETE`）：没有 = 崩溃 = 结果无效。
   只 `grep -c '^  FAIL'` 会把"组内崩溃"读成"几乎全绿"（2026-09-17 实测被骗过一次）。
2. **红跑里仍 PASS 的逐条归类**：要么是**真不变量**（改前改后都该绿，如 `无 pageerror`、既有契约），
   要么是**漏网**。本次实例：`QM-3c` 首版在"没有高亮格"时平凡成立 ⇒ 补 `nowCount == 1` 前置条件。
3. **"数据驱动"的断言必须补确定性 mock 跑正向分支**：写成"有数据就 X、没数据就 Y"是对的，
   但上游那一刻没数据 ⇒ 正向分支**从未执行**。判据：看打印的分支是哪一支。

## 3. Playwright mock 的三个坑（本轮全踩过）

- 🔴 **`page.route` 的 handler 只能有 1 个形参**。写 `lambda r, b=body:` 这种"默认参数捕获"，
  Playwright 会按 `(route, request)` 调用 ⇒ `b` 是 Request ⇒ `json.dumps` 抛 `TypeError`，
  **异常延后到别的 API 处才重抛**（本次在 `wait_for_function` 报），症状酷似"mock 没生效"。
  正确写法：工厂返回单参函数 `def _mk(body): def _route(route): route.fulfill(...); return _route`。
- 🔴 **等"值"不要等"壳"**：骨架屏/空态容器在首帧就存在 ⇒ `wait_for_function("cells >= 4")` 立刻返回、
  拿到空态。等你要断的那个值（如 `#cn-level === 期望 label`）。
- 🟡 **别把"假设数据陈旧/新鲜"写进判据**：`as_of` 类快照字段一律由数据推导期望值
  （否则就是"数据一变就翻红"，V-2/V-3 都栽过）。

## 4. 绿跑 → 全量 → 与当日基线比集合

```bash
./venv/Scripts/python.exe -m pytest tests/test_web.py -q            # V1
PYTHONIOENCODING=utf-8 ./venv/Scripts/python.exe tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
#   ⚠️ 前台 + 显式 timeout（~5 分钟）；后台跑会被 120s 上限掐断（日志 0 字节/截断）
```

**全量判据**：先完成标记，再 `grep -c '^  PASS  XX-'` 确认**新组真的跑了**
（本轮漏注册调用 ⇒ 全量 604/0 但新组 0 条，是假绿），最后与当日基线比**集合差**（新增红必须为 0）。

## 5. 收尾

- `docs/pitfalls.md`（可复用规则，含本次踩的坑）+ `docs/architecture.md`（决策行）+ 任务 `journal.md`。
- 提交用 `git add <具体路径>`，**不用** `-A`；清单 = 源码/模板/样式 + 本验收脚本 + `docs/` + `tasks/<本任务>/`。
