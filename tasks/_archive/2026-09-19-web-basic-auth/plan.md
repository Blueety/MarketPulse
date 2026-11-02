# 方案：web 层访问控制（HTTP Basic Auth）

> **任务档**：`tasks/2026-09-19-web-basic-auth/`（prd.md 已定稿）
> **P0 序列第 1 个**（序列：① 鉴权 → ② G1 凭据重置 → ③ G8 验收信号分层）
> **角色**：Phase 3 Step 3.3 架构师（只读分析 + 方案，**不含完整实现代码**）
> 所有「实测」结论均标注实测条件（2026-09-19 23:0x，本机直连）。
>
> **状态（2026-09-19 23:30）：定稿，可交付执行者实施。** §10 的三个待拍板项**已全部裁定**
> （见 §10.1）—— 实施前**不必**再回来问。⚠️ 本文档作者是架构师，**不直接改项目代码**。

---

## 0. 结论先行

1. **缺口成立且定性 P0**：`web/app.py` 零鉴权，线上 `marketpulse-blue.up.railway.app` 全部端点 200 可读，
   `/api/watchlist` 暴露 11 只自选 ETF 的 symbol + 实时价。
2. **推荐方案 A：HTTP Basic Auth 中间件**。零新依赖、零前端改动、浏览器原生支持、覆盖全部 10 个 API 与 4 个页面。
3. 🔴 **头号地雷不是鉴权本身，是 healthcheck**：`railway.toml` 的 `healthcheckPath = "/"` + `ON_FAILURE`
   + `MaxRetries = 10` ⇒ 给 `/` 返 401 会让部署**陷入重启循环直到失败**。**必须先加 `/healthz` 并改配置**。
4. 🔴 **二号地雷是验收脚本**：实测 `verify_ui.py` 有 **28 处裸 `new_context`** + **7 处裸 `urllib` 业务请求**
   + **0 处 `set_extra_http_headers`** ⇒ 直接加鉴权会让既有 700+ 条断言**几乎全红**，重蹈 G8「红色淹没真回归」。
5. **5 个决策点已给推荐项**（§3），其中 **D-1（未配置时 fail-open vs fail-closed）需用户拍板**。

---

## 1. 任务目标（引用 prd.md 的 Goal）

> 给 MarketPulse 的整个 web 层加访问控制，堵住「线上零鉴权、数据全网可读」这个 P0 缺口。

验收标准全文见 `prd.md` §验收标准（7 条）。

---

## 2. 实测取证（Step 0，已完成）

| 项 | 实测结果 | 用途 |
|---|---|---|
| 鉴权存在性 | `grep "auth\|login\|token\|password\|API_KEY\|Secret" web/app.py` → **零命中** | 缺口成立 |
| 线上可达 | `/`=200、`/api/timeline`=200、`/api/watchlist`=200（含 11 只 ETF 明细） | 定性 P0 |
| 路由与 API | **4 页路由 + 10 个 JSON API**（数 `@app.get`）；侧栏 11 项 | 覆盖口径 |
| app 结构 | `app = FastAPI()` @71；startup @77；`app.mount("/static")` @112；**零 middleware、零 Depends** | 插入点 |
| env 惯例 | `os.environ.get("MP_SKIP_RESTORE") == "1"`（@79）、`WATCHLIST_STOCKS`、`MACRO_STOCKS` | 命名对齐 `MP_*` |
| 部署配置 | `railway.toml`：`healthcheckPath="/"`、`restartPolicyType="ON_FAILURE"`、`MaxRetries=10` | 🔴 R1 |
| 验收脚本 | **28 处** `new_context`（全裸）、**7 处**业务 `urllib.request.urlopen`、`set_extra_http_headers` **0 处** | 🔴 R2 |
| 验收起服 | `subprocess.Popen([PY,"-m","uvicorn","web.app:app","--port",port], cwd=ROOT)`，**未传 env ⇒ 继承父进程** | D-4a 可行 |
| 仓库内外部调用 | grep `marketpulse-blue\|railway.app` 于 `*.py/*.sh/*.toml` → **无命中** | R6 收敛 |

> ⚠️ **文档漂移（顺带发现）**：`architecture.md` 写「3 页 9 API」、`system-overview.md` 写「4 页 12 API」，
> 实测均为 **4 页 10 API**。`frontend-structure.md` §1/§2 是准的。本任务会顺手订正 `system-overview.md`。

---

## 3. 方案选型（替代方案对比 + 选型理由）

| 方案 | 改动量 | 新依赖 | 浏览器体验 | 结论 |
|---|---|---|---|---|
| **A. HTTP Basic Auth 中间件** | 小（1 文件） | **0** | 原生弹窗，一次输入后**自动对所有同域请求（含 `/static/*` 与所有 `fetch`）带 Authorization** | ✅ **选用** |
| B. Bearer Token / API Key（header） | 中 | 0 | **差**：`<a href="/macro">` 无法带 header，页面跳转必失败；前端每个 `fetch` 都要改 | 否决 |
| C. Session Cookie + 登录页 | 大 | 0 | 最好（可登出） | 否决：单人自用看板，登录页/会话管理是过度工程；且要新增模板 = 需登记 `_ASSET_FILES` |
| D. 平台层鉴权（Railway 前置反代 / Cloudflare Access） | 0 代码 | 依赖平台 | 好 | 否决：Railway 无内置 Basic Auth；本地与验收环境行为不一致，无法单测 |

**选 A 的理由**：
① 单人自用看板，单组凭据足够；② Basic Auth 是**唯一**浏览器原生支持、无需改任何 HTML/JS 就能覆盖
「页面导航 + 静态资源 + XHR」三类请求的方案；③ stdlib 即可实现（`base64` + `hmac.compare_digest`），
满足 AGENTS.md「不引入新依赖」；④ `curl -u` 与 `urllib` 均易覆盖，便于验收。

### 决策记录

| # | 决策点 | 推荐 | 理由 |
|---|---|---|---|
| **D-1** | 未配置凭据时 fail-open 还是 fail-closed | **fail-open + 启动 WARNING** | 与项目既有纪律一致（失败降级不中断，`git_ops` 失败仅记日志退出码 0）；fail-closed 会锁死本地开发与验收。**⚠️ 需用户拍板**：若要求"绝不裸奔"改为 fail-closed（一行判断） |
| **D-2** | healthcheck 怎么办 | **新增 `GET /healthz`（无鉴权）+ 改 `railway.toml` 的 `healthcheckPath`** | D-2b（中间件放行 `/` 的 HEAD）脆：Railway 也可能发 GET。`⚠️ /healthz` 只回 `{"status":"ok"}`，**不查 DB** —— DB 挂了重启也修不好，不该让健康检查背锅 |
| **D-3** | 静态资源是否豁免 | **不豁免** | Basic Auth 下浏览器自动带凭据；豁免会制造"页面能开、数据全 401"的半开状态，更难排查 |
| **D-4** | 验收脚本怎么办 | **D-4a + D-4b 配套**（见 §5 Step 4） | 否决 D-4c（给 28 context + 7 urllib 全加凭据）：改动面过大，且把"鉴权改动"与"既有信号"耦合 |
| **D-5** | env 命名 | `MP_AUTH_USER` / `MP_AUTH_PASS` / `MP_AUTH_DISABLED` | 对齐既有 `MP_SKIP_RESTORE` 前缀 |
| **D-6** | 凭据比较 | `hmac.compare_digest`（常量时间） | 防时序侧信道；stdlib |
| **D-7** | 401 响应 | 必须带 `WWW-Authenticate: Basic realm="MarketPulse"` | 缺该头浏览器**不弹窗**，表现为反复失败且无任何提示 |

---

## 4. 要改的文件清单

### 主改动

| 文件 | 改动 |
|---|---|
| `web/app.py` | ① 模块级读 env（`MP_AUTH_USER` / `MP_AUTH_PASS` / `MP_AUTH_DISABLED`）+ 未配置时 `log.warning`；② 新增 `@app.middleware("http")` 鉴权中间件（含 `/healthz` 白名单、Basic 解头、`hmac.compare_digest`、401 + `WWW-Authenticate`）；③ 新增 `GET /healthz` |

### 配置与文档

| 文件 | 改动 |
|---|---|
| `railway.toml` | `healthcheckPath = "/"` → `"/healthz"`（**🔴 遗漏即部署循环重启**） |
| `docs/commands.md` | 快速检查表 +1 行（鉴权单测）；「何时跑什么」+1 行；补 curl 验鉴权的三连 |
| `docs/system-overview.md` | §9 缺口表更新（本条从"建议"划为"已解决"）；顺手订正 §2.4 的「4 页 / 10 API」与 §8 |
| `docs/frontend-structure.md` | §4 API 契约表补注：全部端点需 Basic Auth；`MP_AUTH_DISABLED=1` 本地免鉴权 |
| `README.md`（或 `docs/user-guide.md`） | 部署需配的 env 清单 + `MP_AUTH_*` 说明 |

### 测试与验收

| 文件 | 改动 |
|---|---|
| `tests/test_web.py` | 新增鉴权用例组（TestClient，见 §5 Step 3） |
| `tasks/2026-09-11-frontend-bento-redesign/verify_ui.py` | ① `main()` 在 `Popen` 前设 `os.environ["MP_AUTH_DISABLED"]="1"`；② 新增 `assert_auth()`（`AUTH-*` 组） |

### 不动（逐条核对）

`src/**` · `web/templates/**` · `web/static/**`（⇒ 不涉及 `_ASSET_FILES`） · `data/**` · `.env` · `config.json` ·
`Procfile` / `railpack.json` · 既有 `verify_ui.py` 断言语义（只增不改）

---

## 5. 实施步骤（每步可独立验证）

### Step 1 — `/healthz` + `railway.toml`（**先做，它是部署安全的先决条件**）

- `web/app.py` 新增 `GET /healthz` → `{"status": "ok"}`（**不查 DB**，见 D-2）
- `railway.toml` 改 `healthcheckPath = "/healthz"`
- 验证：
  ```bash
  venv/Scripts/python -m uvicorn web.app:app --port 8010
  curl -s localhost:8010/healthz          # 期望 {"status":"ok"} + 200
  ```
- ⚠️ 本步**不改**任何鉴权逻辑，单独提交也可安全上线。

### Step 2 — 鉴权中间件

在 `app.mount("/static", ...)` **之后**（或之前均可；中间件对所有路由生效）注册：

```
# 伪代码，非可运行代码
_USER = os.environ.get("MP_AUTH_USER") or ""
_PASS = os.environ.get("MP_AUTH_PASS") or ""
_DISABLED = os.environ.get("MP_AUTH_DISABLED") == "1"
_ENABLED = bool(_USER and _PASS) and not _DISABLED        # 模块级，启动时算一次
if not _ENABLED: log.warning("web 鉴权未启用：设置 MP_AUTH_USER/MP_AUTH_PASS 以启用")

@app.middleware("http")
async def _auth(request, call_next):
    if not _ENABLED:                    return await call_next(request)
    if request.url.path == "/healthz":  return await call_next(request)   # 白名单
    hdr = request.headers.get("authorization", "")
    if not hdr.startswith("Basic "):    return _unauthorized()
    try:    raw = base64.b64decode(hdr[6:]).decode("utf-8")
    except Exception:                   return _unauthorized()
    if ":" not in raw:                  return _unauthorized()
    u, p = raw.split(":", 1)
    # 常量时间比较，两处都要 compare_digest，不能只比一个
    if not (hmac.compare_digest(u, _USER) and hmac.compare_digest(p, _PASS)):
        return _unauthorized()
    return await call_next(request)

def _unauthorized():
    return JSONResponse({"detail": "Unauthorized"}, status_code=401,
                        headers={"WWW-Authenticate": 'Basic realm="MarketPulse"'})
```

要点：① `Basic ` 前缀大小写按 RFC 应不敏感，实现可统一 `hdr[:6].lower() == "basic "`；
② 401 必须带 `WWW-Authenticate`（D-7）；③ 路径白名单用**精确相等**，不做前缀匹配（防 `/healthz/../` 类绕过；
Starlette 已规范化路径，但仍用精确比较最稳）。

### Step 3 — 单测（`tests/test_web.py`）

建议用例（TestClient + monkeypatch env，注意鉴权常量在**导入时**求值 ⇒ 需 `importlib.reload(web.app)`
或把读取封装成函数供 patch；**推荐后者**，避免 reload 污染其它用例）：

| 用例 | 期望 |
|---|---|
| 鉴权开启 + 无凭据访问 `/` | 401，含 `WWW-Authenticate` |
| 鉴权开启 + 错密码 | 401 |
| 鉴权开启 + 正确凭据 | 200 |
| `/healthz` 无凭据 | 200 |
| 各 API（`/api/latest`、`/api/timeline`、`/api/watchlist`）无凭据 | 401 |
| `MP_AUTH_DISABLED=1` | 全站 200 |
| 未配置 `MP_AUTH_USER/PASS` | 放行 + 已 `log.warning`（capsys 或 caplog 断言） |
| `Basic` 前缀缺 / 非 base64 / 无冒号 | 401（不 500） |

### Step 4 — 验收脚本接线（🔴 二号地雷）

**D-4a（零风险，必做）**：`verify_ui.py` 的 `main()` 在 `subprocess.Popen` 之前 `os.environ["MP_AUTH_DISABLED"] = "1"`。
子进程继承父 env ⇒ **既有 700+ 条断言零改动、零新增失败**。

**D-4b（配套，必做）**：新增 `assert_auth()` 断言组，**另起一个带鉴权的服务实例**（复用 `free_port()`），断言：

| 断言 | 内容 |
|---|---|
| `AUTH-1` | 无凭据 `GET /` → 401 且 `WWW-Authenticate` 存在 |
| `AUTH-2` | 无凭据 `GET /api/watchlist` → 401（**直接验 P0 的那个端点**） |
| `AUTH-3` | 无凭据 `GET /healthz` → 200 |
| `AUTH-4` | 错凭据 → 401；正确凭据 → 200（用 `urllib` 带 `Authorization` 头） |
| `AUTH-5` | Playwright `new_context(http_credentials=...)` 打开 `/` → 渲染成功、console error 0 |

> ⚠️ **`AUTH-5` 是必须的**：它验证"浏览器带上凭据后页面真能正常工作"，
> 这是 D-3（静态资源不豁免）唯一能被证伪的地方 —— 单测覆盖不到浏览器自动带凭据的行为。

### Step 5 — 跑全量验证

```bash
venv/Scripts/python -m pytest tests/test_web.py -v -k auth
venv/Scripts/python -m pytest tests/ -q
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py
```

> ⚠️ `verify_ui.py` 约 5 分钟，**必须前台 + 显式 timeout 600000**（PowerShell 后台 120s 会被掐，
> 表现为 exit 1 + 日志截断）。判"红是不是我改出来的"用 `git archive HEAD` 隔离副本做 A/B，
> **不看绝对条数**（G8）。

### Step 6 — 文档与线上验收

- 按 §4 更新 4 份文档
- 在 Railway 配 `MP_AUTH_USER` / `MP_AUTH_PASS`（**不要**设 `MP_AUTH_DISABLED`）
- 部署后验证（见 §6）

---

## 6. 验证命令（引用 `docs/commands.md` 的实际命令 + 本任务新增）

```bash
# ① 单测（本任务新增行，需同步进 docs/commands.md）
venv/Scripts/python -m pytest tests/test_web.py -v -k auth

# ② 本地带鉴权起服（docs/commands.md 已有 uvicorn 命令，此处加 env 前缀）
MP_AUTH_USER=demo MP_AUTH_PASS=demo123 venv/Scripts/python -m uvicorn web.app:app --port 8011

# ③ 三连验证（期望 401 / 200 / 200 / 401）
curl -s -o /dev/null -w "%{http_code}\n" localhost:8011/                        # 401
curl -s -o /dev/null -w "%{http_code}\n" localhost:8011/healthz                # 200
curl -s -o /dev/null -w "%{http_code}\n" -u demo:demo123 localhost:8011/       # 200
curl -s -o /dev/null -w "%{http_code}\n" -u demo:wrong   localhost:8011/       # 401

# ④ 全量
venv/Scripts/python -m pytest tests/ -q
venv/Scripts/python tasks/2026-09-11-frontend-bento-redesign/verify_ui.py      # 前台，timeout 600000

# ⑤ 线上验收（配好 Railway env 后）
curl -s -o /dev/null -w "%{http_code}\n" https://marketpulse-blue.up.railway.app/         # 期望 401
curl -s -o /dev/null -w "%{http_code}\n" https://marketpulse-blue.up.railway.app/healthz  # 期望 200
```

> Windows Git Bash 下 env 前缀写法：`MP_AUTH_USER=demo MP_AUTH_PASS=demo123 venv/Scripts/python ...`（可行）；
> 若不行改用 `export` 两行再跑。

---

## 7. 风险评估与注意事项

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| **R1** | 🔴 **healthcheck 401 → 部署重启循环**（`ON_FAILURE` + 10 次重试后服务不可用） | **最高** | Step 1 先做；`railway.toml` 同步改；上线后**先确认健康状态再继续** |
| **R2** | 🔴 验收脚本 28 context + 7 urllib 全红 | 高 | D-4a 注入 `MP_AUTH_DISABLED=1`；D-4b 新增 `AUTH-*` 独立覆盖 |
| **R3** | 忘记配 Railway env ⇒ 等同没做（fail-open 裸奔） | 高 | 启动 `log.warning`；部署清单写明；**上线后必须 curl 验 401** |
| **R4** | 401 缺 `WWW-Authenticate` ⇒ 浏览器不弹窗、反复失败无提示 | 中 | D-7 + 单测锁定该 header |
| **R5** | HTTP 明文下凭据泄露 | 中 | Railway 强制 HTTPS；文档注明**不可用 HTTP 暴露** |
| **R6** | 仓库外 Hermes cron 若打线上 API 会 401 | 中 | 仓库内已确认无调用（§2）；**需用户确认 cron 清单**，必要时改用 `/healthz` 或给 cron 专用开关 |
| **R7** | Basic Auth 无"登出"，浏览器会记住凭据 | 低 | 关标签页 / 清站点数据；个人看板可接受 |
| **R8** | 时序侧信道 | 低 | `hmac.compare_digest`（D-6），**用户名与密码都要** |
| **R9** | 模块级常量在导入时求值 ⇒ 单测 monkeypatch env 不生效 | 中 | 把 env 读取封装为函数（如 `_auth_enabled()`），或测试内 `importlib.reload`；**推荐前者** |

---

## 8. 预计影响的文件范围

| 类别 | 数量 | 说明 |
|---|---|---|
| 主代码 | 1 文件 | `web/app.py` 新增约 **40 行**（中间件 + `/healthz` + env 常量） |
| 配置 | 1 文件 1 行 | `railway.toml` 的 `healthcheckPath` |
| 测试 | 1 文件 | `tests/test_web.py` 新增约 8 条用例 |
| 验收 | 1 文件 | `verify_ui.py` +1 行 env 注入 + 新增 `AUTH-*` 组（约 60 行） |
| 文档 | 4 文件 | `commands.md` / `system-overview.md` / `frontend-structure.md` / `README.md`（或 `user-guide.md`） |
| **不动** | — | `src/**`、模板、静态资源、`data/**`、`.env`、`config.json` |

**提交范围**（AGENTS.md 纪律）：显式 `git add <具体路径>`，**不用 `-A`**；
不含 `data/` `context/` `alerts/`（那些归 cron 白名单）。

---

## 9. 明确不做

- ❌ 登录页 / Session / Cookie / 登出（D-1 已否决方案 C）
- ❌ 多用户、角色、权限分级、审计日志
- ❌ 改 `src/**`、改前端模板或静态资源
- ❌ 保护 `alerts/` `context/` 文件本体（非 web 层）
- ❌ **G1**（`wecom_*.py` 硬编码 BOT_ID/SECRET）→ P0 序列**第 2 个**任务
- ❌ **G8**（`verify_ui` 验收信号分层：上游失败标 `SKIPPED`）→ P0 序列**第 3 个**任务
- ❌ 不修改任何既有 `verify_ui.py` 断言语义（只新增 `AUTH-*` 组）

---

## 10. 决策裁定（2026-09-19 23:30，用户已确认）

### 10.1 三项待拍板 —— 已裁

| # | 问题 | 裁定 | 影响 |
|---|---|---|---|
| **D-1** | 未配置凭据时 fail-open 还是 fail-closed | ✅ **fail-open + 启动 WARNING** | 忘了配 = 回到现状（不比现在更糟），且启动打醒目 `log.warning`；本地开发与验收零摩擦。**不要**实现 fail-closed |
| **R6** | Hermes cron 是否打线上 API | ✅ **无，风险解除** | 实测 `hermes cron list` 共 **9 个** cron，`grep -rl "marketpulse-blue\|railway.app" /d/hermes/cron/` → **零命中**（唯一 curl 是历史 output 里的 `127.0.0.1:8000`，本地）⇒ **不需要任何 cron 豁免** |
| **R5** | 是否纯 HTTPS | ✅ **是**（`marketpulse-blue.up.railway.app`，Railway 默认强制 HTTPS，无自定义域） | Basic Auth 走 HTTPS 即可；**文档里仍要写明"不可用 http:// 暴露"** |

### 10.2 用户需自行完成的一步（**不属于执行者改动范围**）

在 **Railway 后台 → 服务 → Variables** 加两个环境变量并保存（会自动重部署，约 40s）：

| 变量名 | 值 |
|---|---|
| `MP_AUTH_USER` | 用户名（如 `mp`） |
| `MP_AUTH_PASS` | 密码（**≥16 位随机**，勿用弱口令） |

> ⚠️ 这一步**必须在执行者交付代码之后**做（先有 `/healthz` 与中间件，再配 env），
> 否则可能出现「代码未上线、env 已配」的空窗期，或更糟的「`/` 返 401 但 `/healthz` 还没上线」。
> **顺序：Step 1~6 全部完成并 push 上线 → 再配 env → 再跑 §6 的线上验收。**

---

## 11. 实施落点速查（给执行者，行号基于 2026-09-19 工作区）

| 位置 | 现状 | 要做什么 |
|---|---|---|
| `web/app.py:13-19` | `import json / logging / os / re / threading / time` | 加 `base64`、`hmac` |
| `web/app.py:21` | `from fastapi import FastAPI, Query` | 加 `Request` |
| `web/app.py:22` | `from fastapi.responses import HTMLResponse` | 加 `JSONResponse` |
| `web/app.py:71` | `app = FastAPI(title="MarketPulse Web 看板")` | 之后新增鉴权常量/函数/中间件 |
| `web/app.py:77` | `@app.on_event("startup")` 已有 `_restore_history_db` | 可另加一个 `@app.on_event("startup")` 打鉴权状态 WARNING |
| `web/app.py:112` | `app.mount("/static", ...)` | 中间件挂哪都行（对所有路由生效）；建议放在 mount 之后、路由之前 |

> ⚠️ **R9 提醒**：env **不要**在模块级求值成常量（会让单测 monkeypatch 失效）。
> 请把读取封装成函数（如 `_auth_credentials() -> (enabled, user, pwd)`），中间件每次调用它 ——
> `os.environ.get` 的开销可忽略，换来的是可测性。
