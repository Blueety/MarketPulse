# 方案：企业微信凭据泄露处置（G1）

> **任务档**：`tasks/2026-09-20-wecom-cred-revoke/`
> **P0 序列第 2 个**（① web 鉴权 ✅已交付 → ② 本任务 → ③ G8 验收信号分层）
> **角色**：Phase 3 Step 3.3 架构师（只读分析 + 方案，**不含完整实现代码**，不改任何项目文件）
> 实测条件：2026-09-20 00:2x，本机直连。
>
> 🔒 **本文档全文不含真实凭据值**，一律 `***REDACTED***`。
> 执行者在自己的终端里能看到真值，**但禁止把它抄进任何文档、commit message、issue 或日志**。

---

## 0. 结论先行

1. 🔴 **严重等级被低估了**。`docs/system-overview.md` §9 G1 写的是「仓库会 push 到远端 → 凭据泄露」——
   实测 `gh repo view`：**`isPrivate=false`、`visibility=PUBLIC`**（`https://github.com/Blueety/MarketPulse`）。
   即凭据**已在公网可克隆的仓库里躺了约 19 天**（首次引入 `9e414df`，2026-09-01）。
2. 🔴 **止损的唯一手段是在企业微信后台吊销/重置凭据，不是删代码。**
   删代码能阻止继续扩散，**但无法撤回已经泄露的事实**——GitHub 上针对 secret 的自动爬虫是分钟级，
   必须**假设凭据已被获取**。因此本任务的**第 0 步是用户侧操作**，执行者的代码改动排在它之后。
3. **建议保留模块并做 env 化（方案 A1）**，而非删除（方案 B）。理由是这三个模块是有意建设的能力
   （`9e414df auto: 添加企业微信SDK模块`），且可能与 Hermes→QQ 是并行的第二条推送路径。
   ⇒ **待你拍板 D-1**（§10）。
4. **本任务最有价值的产出不是改这 6 行，而是加一个"防再犯"的守卫**：一条 pytest 用例扫描仓库源码，
   禁止再出现硬编码凭据字面量（§5 Step 4）。**没有它，下一次还会再写一次。**
5. **清理 git history 建议单独立项、不与本任务捆绑**（§10.3）——理由见 §7 R3。

---

## 1. 任务目标

**Goal**：消除企业微信 `BOT_ID` / `SECRET` 泄露的影响，并把「凭据写进源码」这条路径永久堵上。

拆成三件事，缺一不可：

| # | 事 | 谁做 | 能否止损 |
|---|---|---|---|
| **A** | 企业微信后台吊销旧凭据、签发新凭据 | **用户**（仓库外操作） | ✅ **唯一真正的止损** |
| **B** | 三处源码改为从 env / `.env` 读取 | 执行者 | ❌ 防继续扩散，不撤回泄露 |
| **C** | 加防回归守卫（单测扫描硬编码） | 执行者 | ✅ 防再犯 |

验收标准见 §6。

---

## 2. 实测取证（Step 0，已完成）

| 项 | 实测结果 |
|---|---|
| 硬编码位置 | `src/wecom_channel.py:16-17`、`src/wecom_sdk.py:12-13`、`src/wecom_ws.py:17-18`（同一份凭据**抄了 3 遍**） |
| 使用方式 | 拼进 WS 握手 body（`"bots": [{"<key>": BOT_ID}]` 等），与 `SECRET` 一起发给服务端 |
| **仓库可见性** | 🔴 **PUBLIC** / `isPrivate=false` / `github.com/Blueety/MarketPulse` |
| 引入时间 | `9e414df auto: 添加企业微信SDK模块`（2026-09-01 前后） |
| 是否在 HEAD | ✅ 在；且 `git rev-parse HEAD` == `git ls-remote origin master` == `4f6e112` ⇒ **远端已含** |
| 模块引用情况 | `grep -rn wecom --include=*.py`（排除自身/venv/tasks）→ **零命中** ⇒ 孤儿模块（G3） |
| 依赖缺失（G2） | `wecom_aibot_sdk`、`websockets` **均不在** `requirements.txt` |
| 既有 env 惯例 | `src/news_fetcher.py:22` 的 `_load_env(key)`：env → `.env` → `D:/hermes/.env` → `""` |
| `.gitignore` | **第 14 行已有 `.env`** ✅ ⇒ 配 `.env` 不会被提交 |
| 二次泄露检查 | 全仓 `*.md` 中 `BOT_ID\|SECRET` 的命中**全是变量名**，无真实值 ✅ |

> ⚠️ 附带更正：`docs/system-overview.md:291` 的 G1 描述「仓库会 push 到远端 → 凭据泄露」应改为
> 「**公开**仓库，已泄露约 19 天」，并把处置顺序（先吊销）写明。

---

## 3. 方案选型

### 3.1 模块去留

| 方案 | 做法 | 评价 |
|---|---|---|
| **A. env 化（推荐）** | 三处改为从 env 读 | 保留能力、消除泄露面；**仍保留 G2/G3 两个旧债** |
| B. 直接删除三模块 | `git rm` 三个文件 | 一次性消除泄露面 **+ G2 + G3**；代价：砍掉可能想要的企业微信推送能力 |

**推荐 A**。理由：① `9e414df` 是有意建设的功能，删了要重建；② 若确实不用，删除是**后续独立决策**，
不该与安全处置捆绑（赶时间容易砍错）；③ A 的风险可控（env 化后代码里再无凭据）。

### 3.2 env 读取放哪

| 方案 | 做法 | 评价 |
|---|---|---|
| **A1. 新建 `src/env_util.py`（推荐）** | 单点实现 `_load_env()`，三模块 import | 单一实现 ⇒ 将来新模块也走它，**修一处即修全部** |
| A2. 每个文件内联一份 | 复制 3 份 | 最快，但会变成第 4/5/6 份副本；与「凭据读取必须唯一」的诉求冲突 |

**推荐 A1**。本项目虽有「shell 副本是有意决策」的先例（AJM `frontend-structure.md` §7-4），
但那是 UI 行为；**安全相关的读取逻辑不该有副本** —— 副本意味着将来某份漏改就再泄露一次。

> 迁移期建议：`news_fetcher._load_env` 暂不改（`keep diff minimal`），只在 `src/env_util.py` docstring
> 注明它是规范实现，后续可再收敛。

---

## 4. 涉及文件清单

| 文件 | 改动 |
|---|---|
| `src/env_util.py` | **新增**（约 40 行）：`_load_env(key)` 单点实现（照搬 `news_fetcher.py:22-33` 语义并加 `WECOM_*` 说明） |
| `src/wecom_channel.py` | `BOT_ID` / `SECRET` 两行改为调用 `_load_env`；新增缺失时的**明确报错**（见 D-2） |
| `src/wecom_sdk.py` | 同上 |
| `src/wecom_ws.py` | 同上 |
| `tests/test_wecom_env.py` | **新增**：env 优先级 4 条 + **硬编码扫描守卫 1 条**（核心产出，见 Step 4） |
| `docs/system-overview.md` | §9 G1 行改为「已泄露 19 天 + 已处置」；补 §2.4/§9 的处置顺序说明 |
| `docs/pitfalls.md` | 新增「凭据管理」小节（含本轮 4 条教训） |
| `README.md` | 新增「🔒 凭据配置」：`WECOM_BOT_ID` / `WECOM_SECRET` 放 `.env`，**`.env` 已在 gitignore** |

**不动**：`src/**` 其余全部 · `web/**` · `data/**` · `.env`（用户本地文件）· `config.json` ·
`requirements.txt`（G2 单独立项，见 §9）

---

## 5. 实施步骤（每步可独立验证）

### Step 0 — 🔴 **用户侧：到企业微信后台吊销旧凭据**（执行者**不得**代做，也做不了）

1. 登录企业微信管理后台 → 找到对应智能机器人
2. **立即删除 / 停用该 bot**（或轮换 Secret）
3. 签发新的 `BOT_ID` / `SECRET`，**只写进本机 `.env`**
4. 检查该 bot 近期的调用记录有无异常

> ⚠️ 这一步**必须在 Step 1 之前**完成。原因：只要旧凭据还在后台有效，删代码也挡不住别人拿它调用。

### Step 1 — 新建 `src/env_util.py`

照搬 `src/news_fetcher.py:22-33` 的 `_load_env(key)` 语义（env → `.env` → `D:/hermes/.env` → `""`），
补 docstring 说明「这是本项目读取敏感配置的唯一入口」。

### Step 2 — 三模块 env 化

每处由
```
BOT_ID = "***REDACTED***"
SECRET = "***REDACTED***"
```
改为（**伪代码**）：
```
from src.env_util import require_env      # 或沿用既有 _load_env 命名
BOT_ID = require_env("WECOM_BOT_ID")
SECRET = require_env("WECOM_SECRET")
```

**D-2（关键）**：取值失败时**不要静默退化为空串**——旧代码带着空密钥去握手会变成难以理解的
连接错误。建议开局一处校验：缺 key 就 `raise RuntimeError("缺少环境变量 WECOM_BOT_ID：请在本机 .env 配置")`，
让失败**立刻、明确地**暴露。

### Step 3 — 配本地 `.env`（Windows 本机）

```
WECOM_BOT_ID=<新值>
WECOM_SECRET=<新值>
```
验证 `.gitignore:14` 已覆盖 ⇒ `git status --porcelain` 中**不应出现 `.env`**。

### Step 4 — 🔴 防回归守卫（本任务的核心产出）

`tests/test_wecom_env.py` 新增一条：**扫描仓库源码，禁止硬编码凭据**。要点（**伪代码**）：

```
遍历 src/**/*.py（跳过 venv/）
对每个文件逐行匹配：
    形如  ^\s*(BOT_ID|SECRET|TOKEN|API_KEY|PASSWORD|ACCESS_KEY)\s*=\s*["\x27][^"\x27]{8,}["\x27]
 ⇒ 命中即 FAIL（报错里只打印 文件:行号 + 变量名，**绝不打印值**）
```

三个坑必须在实现时处理：
1. **测试用例自身会命中自己**（正则里的字符串）⇒ 断言要**排除本测试文件**。
2. **不要打印值** ⇒ 失败信息只含 `文件:行号:变量名`，避免把凭据又输出到 CI 日志。
3. **长度阈值 ≥8** 才能避免误伤 `key = ""` 这类空值/占位。

> 守卫写完后应能立刻验证：临时把某一行改回硬编码，`pytest` 应变红；改回来变绿。
> （这就是红→绿：先证伪再证明，别写完就当它对。）

### Step 5 — 文档

按 §4 更新 3 份文档；特别把 `system-overview.md:291` 的 G1 描述从「会泄露」订正为
「**公开仓库已泄露 19 天 → 已吊销 + 已 env 化**」。

---

## 6. 验证命令

```bash
# ① 新增单测（含守卫）
venv/Scripts/python -m pytest tests/test_wecom_env.py -v

# ② 全量回归
venv/Scripts/python -m pytest tests/ -q

# ③ 确认 .env 未被 git 跟踪（必须无输出）
git status --porcelain -- .env

# ④ 确认源码里已无真实凭据（应只剩 `require_env(...)` 形式）
grep -rn "WECOM_BOT_ID\|WECOM_SECRET" src/*.py

# ⑤ 确认没把 .env 误提交
git diff --stat -- .env
```

**验收标准**

1. `src/wecom_*.py` 三个文件中**不再出现任何凭据字面量**
2. 缺 env 时三模块给出**明确报错**（而非空串静默失败）
3. `.env` 不在 `git status` 输出中
4. 守卫用例：注入硬编码 → 红，移除 → 绿（**必须真跑一遍红**）
5. 全量 `pytest` 无新增失败
6. 用户已在企业微信后台完成旧凭据吊销（Step 0，非代码验收）

---

## 7. 风险评估

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| **R1** | 🔴 **只改代码不吊销 = 没有止损** | **最高** | Step 0 前置且由用户执行；文档与本报告均强调 |
| **R2** | 新凭据又被提交上去 | 高 | `.gitignore:14` 已覆盖 `.env`；守卫用例 + `git status --porcelain -- .env` 双保险 |
| **R3** | 清理 git history 的代价被低估 | 中 | **不与本任务捆绑**（§10.3）。原因：①公开 19 天，大概率已被爬取 ⇒ 收益有限；②重写全部 commit hash + force push，属破坏性操作、需重新 clone；③一旦处置期间出错反而扩大影响 |
| **R4** | GitHub Secret Scanning 可能已自动吊销某些凭据 | 中 | 好事；但**不要依赖它**，必须人工确认 |
| **R5** | 缺 env 时静默连不上，排障困难 | 中 | D-2：开局显式 raise |
| **R6** | `requirements.txt` 仍缺 `websockets` / `wecom_aibot_sdk`（G2） | 中 | 本任务**不动** requirements（保持 diff）；一旦有入口 import 这三模块会 ImportError ⇒ 在 `README.md` 与模块 docstring 显式标注「未纳入部署依赖」 |
| **R7** | 执行者把真 FIPS 凭据抄进 commit message / 文档 | — | 已在文档顶部写明禁令；commit message 一律不含值 |

---

## 8. 预计影响的文件范围

| 类别 | 数量 |
|---|---|
| 新增 | 2 个（`src/env_util.py`、`tests/test_wecom_env.py`） |
| 修改源码 | 3 个（`wecom_channel.py` / `wecom_sdk.py` / `wecom_ws.py`，各改 2 行 + 1 处 import） |
| 文档 | 3 个（`system-overview.md` / `pitfalls.md` / `README.md`） |
| **不动** | `web/**`、`src/**` 其余、`data/**`、`requirements.txt`、`.env` |

---

## 9. 明确不做

- ❌ **不代做**企业微信后台的吊销/轮换（仓库外、需登录）
- ❌ 不改 `requirements.txt`（G2 单独立项）
- ❌ 不删除 wecom 模块（G3，取决于 D-1）
- ❌ **不重写 git history / force push**（R3，单独立项）
- ❌ 不动 `src/news_fetcher.py` 的既有 `_load_env`（保持 diff 最小，后续收敛）
- ❌ 不在任何文档/commit/日志中出现凭据明文

---

## 10. 待你拍板

### 10.1 D-1：模块去留

- **A. 保留 + env 化（推荐）** —— 保住能力，泄露面归零
- B. **直接删除**三模块 —— 连 G2/G3 一起消除，但砍掉可能想要的企业微信推送

### 10.2 D-2：缺 env 时的行为

- **A. 开局 raise 明确报错（推荐）**
- B. 静默空串（**不推荐**：会变成难以理解的连接失败）

### 10.3 D-3：是否清理 git history

- **暂不做（推荐）**：先吊销止损；清理 history 收益有限且操作不可逆，建议冷静后单独评估
- 要做的话走 `git filter-repo` / BFG，**需先全量备份 + 确认无协作者中间态**

---

## 11. 给用户的一句话

**立刻去企业微信后台把旧的 bot 凭据删掉。** 代码这边的改动（env 化 + 防再犯守卫）是防止下一次，
但**这一次已经发生的泄露，只有后台吊销能止住**。
