# journal — 企业微信凭据泄露处置（G1）

- **任务档**：`tasks/2026-09-20-wecom-cred-revoke/`（`plan.md` 定稿；§10 三个待拍板项见 §2）
- **执行日期**：2026-09-20 11:4x（本机直连）
- **角色**：Phase 3 Step 3.6 执行者（按 plan 实施 + 验证）
- 🔒 **本文档全文不含任何凭据值**，一律脱敏；六个原字面量已从源码移除。

## 1. 目标

消除企业微信 `BOT_ID` / `SECRET` 泄露的影响，并把「凭据写进源码」这条路径永久堵上。
三件事：**A 用户侧吊销**（唯一真止损）→ **B 源码 env 化** → **C 防回归守卫**。

## 2. 裁定（plan §10 三项）

| # | 议题 | 用户裁定 | 落地 |
|---|---|---|---|
| **D-1** | 模块去留 | **未明确**（用户反问「这个是企业微信的什么东西」，说明还不了解该能力） | 按 plan 推荐执行 **A：保留 + env 化**。理由：删除是「能力取舍」不该由执行者在用户未搞清前代决；且 env 化在两种结局下都不浪费（守卫用例无论如何都要留）。**要翻成删除，`git rm` 三文件即可** |
| **D-2** | 缺 env 行为 | ✅ **开局 raise 明确报错** | `require_env()` 缺失即抛 `RuntimeError`（含变量名 + 配置位置提示 + 「本仓库为公开仓库」提醒，**不含值**） |
| **D-3** | 清理 git history | 未提（plan 推荐暂不做） | **未做**，只写入文档为单独立项 |

## 3. 我独立核实的事实（与 plan 一致 + 两处修正）

| 项 | 实测 |
|---|---|
| 仓库可见性 | `gh repo view --json visibility` → **PUBLIC**（`isPrivate=false`）⇒ 全网可克隆 |
| 硬编码位置 | `wecom_channel.py:16,17` · `wecom_sdk.py:12,13` · `wecom_ws.py:17,18`（`BOT_ID` 35 字符 / `SECRET` 43 字符，**同值抄 3 遍 = 6 行**） |
| 远端已含 | HEAD == `origin/master` ⇒ 凭据确实在公开仓库上 |
| 暴露时长 | 首次提交 `9e414df` **2026-09-01 → 第 19 天** |
| 平台兜底 | `gh api .../secret-scanning/alerts` → **0 条** ⇒ **没有任何自动吊销发生过**，不能依赖它（R4 成立） |
| **修正①** | plan/G2 说 `websockets` / `wecom_aibot_sdk`「不在 requirements 所以未暴露」——实测**两个包本机 venv 里都已安装**，且**以 `.bat` 的姿势直跑能成功启动**（25s 内无异常、进程停在 `while client.is_connected`）⇒ **强烈提示那对旧凭据目前仍然有效**（不排除只是没来得及报错）。**按"有效"处理** |
| **修正②** | 启动方式实测是 `python src\wecom_sdk.py`（**脚本方式**，`sys.path[0]` = `src\`）⇒ 直接写 `from src.env_util import ...` 会 `ModuleNotFoundError`，必须双形态兜底（见 §5.1） |
| 二次泄露普查 | 我另跑了一次全仓扫描（377 个 git 跟踪文件：AWS AKIA / GitHub token / OpenAI `sk-` / Slack `xox` / PEM / Google API key / 变量名式赋值）→ **只有那 6 处命中**，无第二处泄露；修完 **0 命中** |

## 4. 改动文件清单

| 文件 | 改动 |
|---|---|
| `src/env_util.py` | **新增**：`load_env()` / `require_env()` 单点实现（env → 仓库根 `.env` → `D:/hermes/.env` → `~/.hermes/.env`，与 `news_fetcher._load_env` 同语义）+ docstring 说明「这是读敏感配置的唯一入口、安全逻辑刻意不做副本」 |
| `src/wecom_channel.py` / `wecom_sdk.py` / `wecom_ws.py` | 各 **-2 行字面量 + 双形态 import**（共替换 6 处）；`BOT_ID = require_env("WECOM_BOT_ID")` / `SECRET = require_env("WECOM_SECRET")` |
| `tests/test_wecom_env.py` | **新增（8 条）**：env 优先级 / `.env` 回退 / 引号处理 / 缺失返回空 / `require_env` 报错且不泄值 / **防再犯守卫** / **守卫自检（正则真能命中 + 防空转）** / 三模块双形态 import 锁定 |
| `docs/system-overview.md` | §9 G1 行：从「会泄露」订正为「**公开仓库已泄露 19 天**」+ 处置四步 + 平台不兜底 + 未做 history 清理 |
| `docs/pitfalls.md` | 新增「凭据管理」小节（6 条实测教训） |
| `README.md` | 新增「🔒 凭据配置（不要写进源码）」：仓库是 PUBLIC、只放 `.env`、`require_env` 用法、三模块未纳入部署依赖、守卫说明、泄露后的处置顺序 |

**不动**（plan §4 逐条核对）：`src/**` 其余、`web/**`、`data/**`、`.env`（用户本地文件）、`config.json`、
`requirements.txt`（G2 单独立项）、`scripts/wecom_service.bat`（靠双形态 import 保持可用）。

## 5. 遇到的问题与处置

### 5.1 🔴 启动方式决定了 import 写法（plan 未预见）
`scripts/wecom_service.bat` 是 `python.exe D:\AGENT\MarketPulse\src\wecom_sdk.py` —— **脚本方式**运行，
此时 `sys.path[0]` = `src\` 而**不是** cwd ⇒ 写 `from src.env_util import require_env` 会直接
`ModuleNotFoundError`，把今天还能跑的启动路径弄坏。修法（三文件各 4 行）：

```python
try:
    from src.env_util import require_env
except ImportError:                     # 脚本方式直跑（scripts/wecom_service.bat）
    from env_util import require_env
```
**没有**用 `sys.path.insert` 那种 hack（本项目 `d9394a3` 刚移除过一次），也**没有**改 `.bat`（不在 plan 清单内）。
实测 `python src/wecom_sdk.py` 仍能走到 `require_env` 并抛出预期错误 ✔。

### 5.2 🔴 改凭据不能用"逐行编辑"
用 Edit 工具替换那 6 行，就必须把**凭据原文**写进工具调用 —— 等于把刚泄露的凭据又抄一份进对话记录。
改为**一次性脚本**（`%TEMP%\mp-ev\patch_wecom.py`）做「定位 + 替换」，脚本**只打印
`文件:行号:变量名` 与新行内容**；读文件也走脱敏打印（`show_redacted.py`）。
前置动作：先把 3 个原文件备份到 `%TEMP%`（含凭据原值，仅本机，不入库）。

### 5.3 守卫初版两处假红（都已修，并写进 pitfalls）
1. **递归整棵仓库树**扫进了第三方包 —— 本机根目录**同时存在 `venv/` 与 `.venv/`**，
   而 akshare / curl_cffi 里到处是 `token = "..."` ⇒ **7 条假红**。
   改为只扫**随仓库发布的 Python**：根 `*.py` + `src/` + `scripts/` + `web/`（37 个文件），
   并跳过一切点开头目录。
2. **正则不认类型注解写法**（`client_secret: str = "..."`）—— 由「守卫自检」用例当场抓到
   （这正是自检用例存在的意义）。已扩展成覆盖 `VAR = "v"` / `VAR: str = "v"` / `"VAR": "v"` 三种写法。

### 5.4 一处测试期望写错（实现是对的）
`.env` 里 `KEY="  spaced  "`：我最初断言内部空白被 trim，实际实现（与 `news_fetcher` 同语义）
**刻意保留内部内容**。这与本项目「不 mangle 敏感值」的既定取舍一致（同 `MP_AUTH_PASS` 不做 strip）
⇒ 改测试 + 在 docstring 与 pitfalls 写明该取舍。

## 6. 验证结果

| 项 | 结果 |
|---|---|
| `pytest tests/test_wecom_env.py -v` | **8 passed** |
| `pytest tests/ -q` | **740 passed / 1 failed**（+8；唯一红仍是既有 `test_us_sector::test_volume_format`，与本轮无关） |
| 守卫**红→绿**（plan §6 ④） | 往 `src/` 放 `BOT_ID = "fake-guard-probe-value"`（**假值**）⇒ 守卫 **FAIL** 且报 `src/_guard_probe_tmp.py:2:BOT_ID`（**只位置、不报值**）；删除后 **PASS** ✔ |
| 守卫防空转 | 断言 `n_files >= 20`（实测扫描 37 个文件）；另有「正则真能命中」自检用例 |
| `git status --porcelain -- .env` | **无输出**（`.env` 未被跟踪） |
| `git diff --stat -- .env` | 无输出（没误提交） |
| `grep -rn "WECOM_BOT_ID\|WECOM_SECRET" src/*.py` | 只剩 3 组 `require_env(...)` 调用 + `env_util.py` docstring |
| 脱敏凭据普查（377 个 tracked 文件） | **0 命中** ✔ |
| D-2 行为 | 缺 env 时 `RuntimeError: 缺少环境变量 WECOM_BOT_ID：请把它配到本机 .env（或 D:/hermes/.env），不要把凭据写回源码 —— 本仓库为公开仓库。` ✔ |

## 7. ⚠️ 仍需用户完成（执行者做不到）

1. 🔴 **企业微信管理后台吊销/轮换旧凭据**（plan Step 0）。**这是唯一真止损**，且实测**平台不会替你兜底**
   （Secret Scanning 0 告警），而我复现启动时它**疑似仍然有效**。
   步骤：管理后台 → 对应智能机器人 → 删除/停用该 bot（或轮换 Secret）→ 签发新凭据 → 查近期调用记录有无异常。
2. 把**新**凭据写进本机 `.env`（`.gitignore:14` 已覆盖）：
   ```
   WECOM_BOT_ID=<新值>
   WECOM_SECRET=<新值>
   ```
   ⚠️ 在此之前三个模块会**按设计**抛 `RuntimeError`（这是 D-2 要的效果，不是 bug）。
3. （可选）决定 **D-1**：若确认不用企业微信这条路径，`git rm src/wecom_{sdk,channel,ws}.py` 即可
   （守卫与 `env_util` 保留）。

## 8. 明确未做（与 plan §9 对照）

- ❌ 未代做后台吊销（仓库外、需登录）
- ❌ 未改 `requirements.txt`（G2 单独立项）
- ❌ 未删除 wecom 三模块（D-1 用户未明确；翻成删除只需 `git rm`）
- ❌ **未重写 git history / force push**（R3；单独立项）
- ❌ 未动 `src/news_fetcher.py` 的既有 `_load_env`（保持 diff 最小；已在 `env_util` docstring 注明后续可收敛）
- ❌ 未在任何文档 / commit message / 日志中出现凭据明文

## 9. 下次注意什么

1. **凭据类风险先实测仓库可见性再定级**（一句 `gh repo view --json visibility`），别按"会 push 到远端"想当然。
2. **删代码 ≠ 止损**：顺序永远是"先吊销、后改码"；且不要指望平台自动兜底。
3. **改凭据一律用脚本做定位+替换**，只打印位置不打印值；读文件先脱敏。
4. **给"既当包导入又被 .bat 脚本直跑"的模块加 import 时，先确认 `sys.path[0]` 是哪**。
5. 写守卫/扫描类用例，必须同时做「正则能命中」+「扫到足够多文件」两条自检，否则是空转假绿。

## 7-bis. 吊销闭环验证（2026-09-20 22:0x）：🔴 **旧凭据仍然有效 —— 吊销未生效**

用户 22:0x 报告"企业微信我已经吊销了"。用 git 历史里的旧凭据（`9af984c^:src/wecom_sdk.py`，
env 化提交之前）做了一次**直连 SDK 验证**（`wecom_aibot_sdk.WSClient.connect_async()`，20s 超时，
全程不打印值）—— 结果 **`CONNECTED`**。

⚠️ 注意：三模块已被删除（6ec1562，D-1 裁定改删除；守卫测试同名改名为 `test_env_util.py`），
验证探针改为**直连 SDK**（`%TEMP%\mp-ev\verify_wecom_revoke2.py`，从 git 历史读旧值、只打印长度）。

**可能原因**（按概率）：
1. 吊销/删除的对象不对（企业微信后台可能有多个应用/机器人，删的不是这一只）；
2. 操作未保存/未确认（后台某些变更要点「保存」才生效）；
3. 改的是 Secret 而 bot 未停用（或反之）——两者都要失效才算闭环；
4. 平台传播延迟（可能性低，>10 分钟仍连上基本排除）。

**下一步（用户）**：回后台确认 **bot_id 与泄露的那个一致**（可对长度 35 的 ID 逐一比对）→
**删除/停用该智能机器人本体**（不只是重置 Secret）→ 告知后我用同一探针复验（探针可重复跑）。
**复验判据不变**：`CONNECTED` = 未生效；`REJECTED` = 闭环达成。
