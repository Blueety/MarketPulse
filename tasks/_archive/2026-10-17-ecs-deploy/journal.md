# 2026-10-17 MarketPulse 部署到华为云 ECS — 交接日志

## 目标

把 Web 看板从 Railway 复制一份到已有的华为云 ECS（上海 `123.60.176.219`，Ubuntu 24.04，2 核 2 GiB），
与另一站点 Todo（8080）共存。用户确认的三个决策：**自签 HTTPS（8443）** / **ECS 每 5 分钟拉取数据** / **口令由 agent 在服务器上生成**。

## 改动文件清单（**应用代码 0 行改动**）

| 文件 | 类型 | 说明 |
|---|---|---|
| `deploy/install-server.sh` | 新增 | 服务器侧一次性安装（幂等，10 步）：系统包 → 服务用户 → 代码落地 → venv+pip → config.json → .env → 自签证书 → nginx → systemd+timer+sudoers → 自检 |
| `deploy/nginx-marketpulse.conf` | 新增 | 8443 TLS 反代模板（`__TLS_PORT__`/`__APP_PORT__`/`__SERVER_NAME__`） |
| `deploy/marketpulse.service` | 新增 | 应用单元：`User=marketpulse`、`EnvironmentFile=.env`、`MemoryMax=1G`、`ProtectSystem=strict` + `ReadWritePaths` |
| `deploy/marketpulse-pull.{service,timer}` | 新增 | 每 5 分钟拉 GitHub 数据 |
| `deploy/marketpulse-pull.sh` | 新增 | 拉取本体（安装到 `/usr/local/bin/marketpulse-pull`，**仓库外**避免与 pull 冲突）；DB 变化才清 `-wal/-shm` 并重启 |
| `docs/deploy-ecs.md` | 新增 | 运行手册（架构/安装/运维/约束/回滚/切真证书） |
| `tasks/2026-10-17-ecs-deploy/{plan,journal}.md` | 新增 | 本任务计划与日志 |

## 验证结果（全部实跑，服务器 = 真机）

| # | 验证 | 结果 |
|---|---|---|
| 1 | 安装脚本语法 | `bash -n` 通过（install-server.sh / marketpulse-pull.sh） |
| 2 | 安装执行 | 10 步全绿；`nginx -t` 通过并 reload；`marketpulse.service` active、`marketpulse-pull.timer` active |
| 3 | 鉴权闸门 | 无凭据 `/` → **401**（未裸奔）；`/healthz` → **200**（免鉴权） |
| 4 | 13 个端点逐个带凭据请求 | **全部 200**（`/`、`/api/latest|history|alerts|news|watchlist|macro|timeline|backtest|econ|econ/cn|cn/quotes`），字节数非空 |
| 5 | 静态资源 | 页面引用的 9 个 `/static/*` 全部 200（app.js / skin.js / chart-crosshair.js / 4 个 skin css / style.css / vendor liquid-glass.css） |
| 6 | **真浏览器（经 SSH 隧道，自签证书 ignoreHTTPSErrors）** | `title=MarketPulse 市场看板`、40 张卡、5 个 canvas、首屏 **1389 ms**、**pageerror 0 / requestfailed 0**；页面文本含真实数据：标普500 **7,748.49 +0.21%**、上证 **3,716.28 +0.24%**、VIX 16.87、红利低波ETF 1.36 +0.07%、自选列表 10 条 ETF 涨跌 |
| 7 | 数据真实来源 | `/api/econ/cn?group=price` 返回 AkShare 实数据（CPI 0.9，2026-09，含历史）；`/api/cn/quotes` 中债 10Y 1.648；`/api/latest` 来自入库 DB/context |

## 遇到的问题（按发生顺序）

1. **`cp -a "$TMP"/. "$APP_DIR"/` 把 mktemp 的 `drwx------ root` 属性套到目标目录** ⇒ `sudo: unable to execute /srv/marketpulse/venv/bin/pip: Permission denied`。
   改用 `tar -c -C SRC . | tar -x -C DST`，并在建目录时就 `chown/chmod 755`。
2. **nginx 1.24 不认识独立 `http2 on;` 指令** ⇒ `[emerg] unknown directive "http2"`。改回 `listen 8443 ssl http2;`（1.25.1+ 也接受旧写法）。闸门按设计生效：`nginx -t` 失败自动回滚 conf，未留下半成品。
3. **服务器 github.com:443 与 raw.githubusercontent.com 超时**（`api.github.com`/`codeload` 正常）⇒ `git clone https://` 不可用；**22 端口可达** ⇒ 走 SSH deploy key（首次安装用 codeload tar 包落地，无需凭据）。
4. **`ssh -f -N -L` 在 Windows 上不能真正后台化**（本机 omp 的 daemon broker 也不可用）⇒ 隧道改用「同一命令内 `&` 起、结束 kill」的方式，验证完即关。

## 已知降级（不是 bug，是网络位置决定的）

服务器到 **Yahoo 403 / BLS 403**（AkShare 国内源正常）：

| 端点 | 状态 |
|---|---|
| `/api/macro`（美元指数 / 10Y美债 / 原油 / 黄金COMEX） | 全部 `value: null`，前端显示「数据未接入」 |
| `/api/econ`（BLS 四序列） | `latest: null`，`history: []` |
| `/api/cn/quotes` 的 `cny` | `null`（Yahoo 汇率），中债 10Y 正常 |

**建议的修法（未做，属应用改动）**：照 `/api/watchlist` 已有的「快照文件优先、实时兜底」模式，把 macro/econ 也做成 `data/*.json` 快照，
由本机 Hermes（有 Clash）生成后随 auto-push 一起同步 ⇒ 服务器端零联网也能显示。

## 下次注意什么

- **换 `marketpulse.db` 必须先清 `-wal`/`-shm` 再重启**（SQLite WAL 与库文件配对，跨库复用会 malformed）；已由 `marketpulse-pull` 强制执行。
- **`config.json` 不在仓库里**（gitignore）⇒ 换机/重装都要手工 scp；服务器上那份是设置页的写入目标，`git pull` 不会覆盖它。
- **不要设 `RAILWAY_ENVIRONMENT` / `MP_AUTH_DISABLED` / `MP_SKIP_RESTORE`**（分别导致设置页只读 / 全站无鉴权 / 跳过空库恢复）。
- 凭据只在**进程环境**读（应用不解析 `.env`）⇒ 必须靠 systemd `EnvironmentFile`；手工前台跑要自己 export。
- 本机 omp 的 `browser` 守护进程与 daemon broker 都不可用（本次实测）⇒ 浏览器验证只能走「SSH 隧道 + 本地 Playwright」。

## 待用户执行的两步

1. 华为云控制台 → 安全组 → 入方向 → 放行 **TCP 8443**（协议端口栏只填数字）。
2. GitHub → 仓库 Settings → Deploy keys → 添加脚本打印的公钥（只读）→ 重跑 `install-server.sh` 即切换为 git 增量拉取。

## 追加（同日）：deploy key 到位 → 切换 git 通道 → 公网验收

用户完成两步后复跑安装脚本（幂等），并修掉两个切换过程中暴露的缺陷：

| 缺陷 | 现象 | 修法 |
|---|---|---|
| **`git init`+`fetch`+`reset` 建立的工作区没有上游追踪** | `marketpulse-pull` 报 `There is no tracking information for the current branch`；timer 每 5 分钟失败一次（14:10 那次实拍） | 安装脚本显式 `git branch --set-upstream-to=origin/$BRANCH`；拉取脚本改成 `git pull --ff-only origin "$(git rev-parse --abbrev-ref HEAD)"`，不依赖 tracking 配置 |
| **codeload tar 包落在 `mktemp -d` 目录里**，被随后的 tar 管道一起复制进站点根 | `/srv/marketpulse/mp.tar.gz` 残留（`git status` 多出 1 个未跟踪文件） | 压缩包改到 `mktemp --suffix=.tar.gz`（目录之外）+ `trap` 清理；并清掉服务器上那份残留 |

### 复验（全部实跑）

| # | 验证 | 结果 |
|---|---|---|
| 1 | 上游追踪 | `* master 00fbfed [origin/master]` ✓ |
| 2 | 手动拉取 | `无数据变化`，`exit=0` ✓ |
| 3 | systemd 路径（timer 实际调用的那条） | `Result=success`、`ExecMainStatus=0` ✓；timer 下次触发 14:15 |
| 4 | sudoers 放行的重启（数据变更分支的关键一步） | `sudo -u marketpulse sudo -n systemctl restart marketpulse` **可用**；重启后 `active`、`/healthz` 200 ✓ |
| 5 | 工作树 | `git status --porcelain` **0 行**（venv/.env/config.json 未跟踪且保留）✓ |
| 6 | **公网可达**（安全组已放行 8443） | TCP 8443 开放（25 ms）；`https://123.60.176.219:8443/healthz` → **200**（0.115 s）、`/` → **401** ✓ |
| 7 | **公网真浏览器**（`https://123.60.176.219:8443/`，自签已忽略） | `title=MarketPulse 市场看板`、`isSecureContext=true`、40 卡、5 canvas、**TTFB 251 ms / load 1070 ms**、24 个资源 / 325 KB、`failedRequests: 0`、页面含真实数据；截图 `tmp/mp-public.png` |
| 8 | 唯一的控制台错误 | `/favicon.ico` **404**（应用没有该路由，浏览器自动请求）⇒ 纯装饰性问题，修法：加 `/favicon.ico` 路由或 `static/favicon.ico` + `<link rel=icon>` |

### 顺带发现

- nginx access.log 里有境外扫描器 `184.105.247.198` 探测 `/favicon.ico`（13:23，当时是 8080 上的 Todo）⇒ 端口暴露在公网必然被扫；当时靠 Basic Auth 兜底，后来按用户要求关掉鉴权后改为「设置页只读 + 只公开非敏感数据」（见下一节）。
- 服务器只开了 8443 与 8080 两个站点端口；`/healthz` 一直免鉴权（给探活/监控用）。鉴权本身已于同日按用户要求关闭（见下节）。

## 追加（同日）：按用户要求去掉登录（+ 把设置页锁只读）

用户要求「不要登录，打开就能看」。执行前先量化了暴露面，再按用户选定方案落地。

### 暴露面取证（决定风险等级）

| 检查 | 结果 |
|---|---|
| 自选列表是否含持仓成本 | **11 个标的 cost / pnl_pct 全为 null**（0/11）⇒ 公开的只是「行情 + 你选了哪些 ETF + 阈值」，**没有持仓与成本** |
| `/api/settings` 是否泄露密钥类 env | 只回 config.json 的值与只读标注，**不含任何密钥** |
| 关鉴权后能否被匿名改写 | ⚠️ **能**：无凭据 `POST /api/settings {"alert.vix":20}` → `{"saved":true}`，服务器生成 `config.json.bak-20261017-142209` |

### 落地内容

1. `.env` 加 `MP_AUTH_DISABLED=1`（**凭据行保留**，恢复登录 = 改成 `0` 或删行 + 重启）。
2. 因上面第 3 条，同时加 `RAILWAY_ENVIRONMENT=1`（应用自带的只读开关；全仓仅 `settings_store.is_readonly()` 读它，无其它副作用）⇒ **用户选定「锁定设置页为只读」**。

### 复验

| # | 验证 | 结果 |
|---|---|---|
| 1 | 无凭据访问（服务器侧与外网侧各一遍） | `/healthz`、`/`、`/api/latest`、`/api/watchlist`、`/settings` **全部 200** ✓（不再弹登录框） |
| 2 | `GET /api/settings` | `readonly: true` + 只读原因 ✓ |
| 3 | 匿名 `POST /api/settings` | **403**，且 `config.json` 的 mtime **未变化**（未被写入）✓ |
| 4 | **真浏览器、零凭据**（`https://123.60.176.219:8443/`） | HTTP **200**、无登录弹框、看板正常渲染（40 卡 / 5 canvas / 真实数据）；`/settings` 页面 200、**保存按钮 `disabled=true`**、页面文案出现「线上（Railway）只读展示」✓；`failedRequests: 0`；截图 `tmp/mp-noauth.png` |

### 已知副作用（应用文案，未改代码）

只读提示文案来自 `settings_store.readonly_reason()`，写的是「线上环境（Railway 临时文件系统）为只读展示…」—— 本机不是 Railway，**语义不准**。修法是在 `src/settings_store.py` 改这句文案（应用改动，未做）。

## 涉及的 ADR

无新增（三条准入不齐：决策可撤销、无背景不困惑、非真实取舍）。部署形态与「免登录 + 设置页只读」的取舍记录在 `docs/deploy-ecs.md` 与 `docs/pitfalls.md`。
