# journal — web 层访问控制（HTTP Basic Auth）

- **任务档**：`tasks/2026-09-19-web-basic-auth/`（`prd.md` 定稿 + `plan.md` 定稿；§10 三项待拍板已裁）
- **执行日期**：2026-09-19 23:3x（本机直连）
- **角色**：Phase 3 Step 3.6 执行者（按 plan 实施 + 验证，不做架构决策）

## 1. 目标

堵住 P0 缺口：`web/app.py` **零鉴权**，线上 `marketpulse-blue.up.railway.app` 的 `/`、
`/api/timeline`、`/api/watchlist` 全部 200 可读（`/api/watchlist` 实质暴露 11 只自选 ETF 的方向）。
方案 A：**全站 HTTP Basic Auth 中间件 + 无鉴权的 `/healthz`**，零新依赖、零前端改动。

## 2. 改动文件清单

| 文件 | 改动 |
|---|---|
| `web/app.py`（+约 100 行） | ① imports 加 `base64` / `hmac` / `Request` / `JSONResponse`；② 访问控制段：`_auth_user()` / `_auth_pass()` / `_auth_disabled()` / `auth_enabled()`（**现读 env，R9**）+ `_authorized()` + `_unauthorized()` + `@app.middleware("http")` + `GET /healthz` + `@app.on_event("startup")` 打鉴权状态；③ docstring 未改 |
| `railway.toml` | `healthcheckPath = "/"` → `"/healthz"`（🔴 R1：不改即部署重启循环） |
| `tests/test_web.py`（+9 条） | 鉴权用例组（见 §3.2） |
| `verify_ui.py`（+约 110 行） | D-4a：`main()` 在 `Popen` 前 `os.environ["MP_AUTH_DISABLED"]="1"`；D-4b：新增 `assert_auth()`（`AUTH-*` 7 条 check，自带带鉴权实例）+ main 接线 |
| `docs/commands.md` | 快速检查表 +2 行（鉴权单测 / 鉴权三连）；「何时跑什么」+1 行 |
| `docs/system-overview.md` | §2.4 端点表订正（**3 页 9 API → 4 页 11 端点**，补漏的 `/timeline`、`/api/timeline`、新增 `/healthz`）+ 鉴权说明；§8 命令速查补鉴权命令；§9 新增 **G9 行（本缺口，已解决）** |
| `docs/frontend-structure.md` | §4 API 契约表补注：全部端点需 Basic Auth + 为何选 Basic 而非 Bearer + `MP_AUTH_DISABLED=1` |
| `README.md` | Web 看板节新增「🔒 访问控制」：env 清单、fail-open 警告、HTTPS 约束、`/healthz` 说明 |

**不动**（plan §4 逐条核对）：`src/**`、`web/templates/**`、`web/static/**`（⇒ 不涉及 `_ASSET_FILES`）、
`data/**`、`.env`、`config.json`、`Procfile` / `railpack.json`、既有 `verify_ui.py` 断言语义（只增不改）。

## 3. 验证结果

### 3.1 本地三连（plan §6 ②③）
```
未配 env（fail-open）： /healthz=200 {"status":"ok"}；/=200；启动 WARNING「web 鉴权未启用…全站裸奔」✔
配 env 后：            /=401  /macro=401  /macro/cn=401  /timeline=401
                       /api/latest=401  /api/watchlist=401  /api/timeline=401  /static/app.js=401
                       /healthz=200
                       -u demo:demo123 /=200、/api/watchlist=200
                       -u demo:wrong    /=401
WWW-Authenticate: Basic realm="MarketPulse"  ✔（无凭据 GET / 的响应头）
畸形头不 500：无 Basic 前缀=401 / 非 base64=401 / base64 无冒号=401 / 空凭据=401
小写 `basic ` 前缀 + 正确凭据 = 200（RFC 7235 大小写不敏感）
```

### 3.2 单测
```
pytest tests/test_web.py -v -k auth   →  9 passed
pytest tests/ -q                      →  732 passed / 1 failed
```
唯一失败仍是 `tests/test_us_sector.py::test_volume_format`（`$12.0亿` vs 期望 `$1.2B`）——
**既有红、与本轮无关**（上一任务已用 `git archive HEAD` 隔离副本 A/B 证实 HEAD 同样失败）。

用例清单：无凭据 401 + `WWW-Authenticate` / **4 页 10 API + `/static` 全覆盖 401** /
错密码与错用户名 401 / 正确凭据 200 / `/healthz` 无凭据 200（带凭据也 200）/ `MP_AUTH_DISABLED=1` 全站 200 /
未配置 → `auth_enabled() is False` + 放行 + 启动 WARNING 含「鉴权未启用」「裸奔」/ 四类畸形头 401 不 500 /
小写 `basic ` 前缀 200。

### 3.3 UI 验收
```
verify_ui.py（全脚本，前台）  →  ALL PASSED / EXIT=0
```
- `AUTH-*`（7 条）全绿：`AUTH-5` 用 `new_context(http_credentials=...)` 打开 `/` →
  `dash=True cards=8 nav=11 overflow=0`；`AUTH-5c` 验到 `body` 有背景色 ⇒ **静态 CSS 在鉴权下确实送达**
  （这是 D-3「静态资源不豁免」唯一能被证伪的地方，单测覆盖不到）。
- 既有 `TL-*` / `EV-*` / `MS-*` / `MX-*` / `UX-*` / `PW-*` / `N-12` 全部仍绿 ⇒
  **D-4a 的 `MP_AUTH_DISABLED=1` 注入生效，既有 700+ 条断言零新增失败**（R2 已解除）。

## 4. 遇到的问题与处置

1. **启动日志里"鉴权已启用"（INFO）看不到**：root logger 默认 WARNING ⇒ `log.info` 被吞。
   **不影响 R3**：真正要醒目的"未启用 ⇒ 裸奔"是 `log.warning`，实测**会出现**（已验证）。
   "已启用"是正常态，静默可接受；确认凭据是否生效走 `curl` 验 401（已写进文档）。
2. **R9 是本轮最容易踩的坑**：若把 env 求值成模块级常量，单测 monkeypatch 直接失效（且很难自查）。
   已按 plan §11 把读取封成 `auth_enabled()` 等函数，中间件每次调用现读；单测因此**无需** `importlib.reload`
   （reload 会污染其它用例）。
3. **文档漂移（顺带订正）**：`system-overview.md` §2.4 写「3 页 9 API」且**漏了 `/timeline` 一页与
   `/api/timeline` 一个 API**；`architecture.md` 同样写「3 页 9 API」（plan §2 已记）。
   本轮按 plan §4 只订正了 `system-overview.md`（并补 G9 缺口行）；
   `architecture.md` **未改**（不在 plan §4 清单里）—— 已在 §7 列为遗留项。

## 5. 线上待办（**需你自己做，不属于执行者改动范围**）

在 **Railway 后台 → 服务 → Variables** 加两个环境变量并保存（会自动重部署，约 40s）：

| 变量名 | 值 |
| --- | --- |
| `MP_AUTH_USER` | 用户名 |
| `MP_AUTH_PASS` | 密码。**不强制 ≥16 位** —— 关键是不可猜：**12 位以上真随机**即可（`secrets.token_urlsafe(12)`）；❌ 字典词 / 项目相关词 / 与其它站点复用（理由见 §9） |

⚠️ **顺序**：本节代码 push 上线 → **再**配 env → **再**跑线上三连。
先配 env 会空窗（"代码未上线、env 已配"），更糟的是"`/` 返 401 但 `/healthz` 还没上线"
（`railway.toml` 的改动随同一批代码上线，所以一次 push 即可，但要确认部署完成）。

线上验收三连（plan §6 ⑤）：
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://marketpulse-blue.up.railway.app/         # 期望 401
curl -s -o /dev/null -w "%{http_code}\n" https://marketpulse-blue.up.railway.app/healthz  # 期望 200
curl -s -o /dev/null -w "%{http_code}\n" -u user:pass https://marketpulse-blue.up.railway.app/  # 期望 200
```
并**确认部署没有进入重启循环**（Railway 面板看 deployment 状态；这也是为什么 healthcheckPath 必须改）。

## 6. 下次注意什么

1. **新增任何端点都要想清楚它要不要鉴权** —— 中间件目前只白名单 `/healthz` 一个路径
   （**精确相等**，不做前缀匹配，防 `/healthz/../` 类绕过）。要放行其它路径需显式加。
2. **改动 `railway.toml` 的 healthcheck 相关配置前，先确认 `/healthz` 在线上存在**
   （否则部署重启循环的排查成本极高）。
3. **验收脚本新增实例时必须显式 `env.pop("MP_AUTH_DISABLED", None)`** ——
   父进程 `main()` 已注入 `1`，子进程会继承；不 pop 的话新实例其实没鉴权，`AUTH-*` 会假绿。
4. 401 的 `WWW-Authenticate` 头被单测和 `AUTH-1` 双重锁定，**不要删**（删了浏览器不弹窗 = 反复失败无提示）。
5. `MP_AUTH_PASS` **不做 strip**（空格可能是合法字符）；用户名 strip 是为了避免配置里的首尾空白。

## 9. 口令长度的口径（2026-09-20 追加，回应用户"密码没大于 16 位可以吗"）

**可以。长度不是判据，"不可猜"才是** —— plan/README 里的"≥16 位"是**随机性的代理指标**，不是硬要求。

- ✅ **12 位以上真随机**即可（生成：`venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(12))"`）
- ✅ 与其它站点不复用
- ❌ 字典词 / 常见口令 / `marketpulse`、邮箱前缀等项目相关词

**为什么短一点也行**：凭证明码（`hmac.compare_digest`）+ HTTPS 传输已到位，剩下的威胁是
**在线暴力尝试**；62^12 ≈ 2×10^21 的量级远超任何可行尝试次数。真正会被打穿的是**可猜口令**，
不是"长度不够的随机口令"。

**已知边界（写进 README，供后续决策）**：中间件**没有失败次数限制 / 锁定**（实测代码里无频控，
grep `rate|limit|throttle|lockout` 只命中无关的宏观代码）。若将来要用短口令或想更稳，
可再加一层简单的按 IP 频控 —— **不属于当前实现**（plan §9 未列，未做）。

## 7. 明确未做（与 plan §9 对照）

- ❌ 登录页 / Session / Cookie / 登出；❌ 多用户、角色、权限分级、审计日志
- ❌ 改 `src/**`、改前端模板或静态资源；❌ 保护 `alerts/` `context/` 文件本体
- ❌ **G1**（`wecom_*.py` 硬编码 BOT_ID/SECRET）→ P0 序列**第 2 个**任务
- ❌ **G8**（`verify_ui` 验收信号分层）→ P0 序列**第 3 个**任务
- ❌ 不修改任何既有 `verify_ui.py` 断言语义（只新增 `AUTH-*` 组）

## 8. 后续建议（不属本轮范围）

1. `docs/architecture.md` 的「3 页 9 API」同样过时（实测 4 页 10 API + `/healthz`），
   且模块表里没有 `web` 的访问控制说明 —— plan §4 未列入，建议单独一条小改动订正。
2. `tests/test_us_sector.py::test_volume_format` 仍是既有红（`$12.0亿` vs 期望 `$1.2B`）。
3. 若要更强的"绝不裸奔"保证，可把 D-1 改成 fail-closed（一行判断），但当前裁定是 fail-open + WARNING。
