# 部署到华为云 ECS（自签 HTTPS + systemd + nginx 反代）

> 本文件是**运行手册**。部署资产在 `deploy/`，安装脚本 `deploy/install-server.sh`（幂等，可重复跑）。
> 线上形态：`https://123.60.176.219:8443/`（自签证书）→ nginx → `127.0.0.1:8000` uvicorn。

## 0. 架构与数据流

```
浏览器 ──HTTPS(自签,8443)──> nginx ──http──> 127.0.0.1:8000  uvicorn web.app:app
                                                 │  systemd: marketpulse.service（User=marketpulse, MemoryMax=1G）
                                                 └─ 只读 data/ context/ alerts/ web/；只写 config.json

数据：本机 Hermes（日报/快照/开盘分析）──auto_commit_push──> GitHub master
      GitHub ──ssh:22 + deploy key──> marketpulse-pull.timer（每 5 分钟）
                                      └─ marketpulse.db 变了 ⇒ 清 -wal/-shm + 重启服务
```

- **数据不在服务器上生成**：服务器只消费仓库里的 `data/marketpulse.db` + `context/*.json` + `alerts/*.md` + `data/news.json`。
  这与 Railway 时代同构（Railway 也是读仓库里那份），所以本机 Hermes 的 7 个 cron 照旧，不用改。
- **应用代码零改动**：本次只加 `deploy/` 与本文档。

## 1. 一次性安装

```bash
# 本机（Windows PowerShell / Git Bash，仓库根）
scp deploy/install-server.sh deploy/nginx-marketpulse.conf deploy/marketpulse.service \
    deploy/marketpulse-pull.service deploy/marketpulse-pull.timer deploy/marketpulse-pull.sh \
    config.json root@123.60.176.219:~/
ssh -t root@123.60.176.219 'PUBLIC_IP=123.60.176.219 bash ~/install-server.sh'
```

`install-server.sh` 依次做（每步幂等）：

| # | 步骤 | 产物 |
|---|---|---|
| 1 | 装系统包 | `python3-venv` / `pip` / `openssl` / `git` / `curl` / `nginx` |
| 2 | 建服务用户 | `marketpulse`（system、无登录 shell）+ `/srv/marketpulse`（属主 marketpulse、755） |
| 3 | 代码落地 | 有 deploy key 走 `git`（增量），否则走 `codeload` tar 包（首次无需凭据） |
| 4 | venv + 依赖 | `/srv/marketpulse/venv`（由服务用户创建），pip 走**清华镜像**；`requirements.txt` 的 sha256 作 stamp，没变就跳过 |
| 5 | config.json | 从上传副本安装（**它在 .gitignore 里，不在 tar 包里**）；已存在则保留 |
| 6 | `.env` | 生成 **16 位随机** `MP_AUTH_USER`/`MP_AUTH_PASS`（不打印），chmod 600 |
| 7 | 自签证书 | `/etc/nginx/ssl/marketpulse.{crt,key}`，SAN = `IP:<公网IP>`，825 天 |
| 8 | nginx 反代 | `/etc/nginx/conf.d/marketpulse.conf`，**`nginx -t` 通过才 reload，失败回滚** |
| 9 | systemd | `marketpulse.service` + `marketpulse-pull.{service,timer}` + sudoers 白名单（只放行一条 restart） |
| 10 | 自检 | `/healthz` 200（免鉴权）、`/` 401（鉴权生效）、TLS 侧 200 |

装完还要**手动两步**（脚本结尾会打印）：

1. 华为云控制台 → 安全组 → 入方向 → 放行 **TCP 8443**（协议端口栏只填数字）；
2. GitHub → 仓库 Settings → Deploy keys → 加脚本打印的那个公钥（**只读**即可）→ 重跑一次 `install-server.sh` 即切换为 git 增量拉取。

## 2. 日常运维

### 2.1 更新代码（改了 `web/`、`src/`、模板之后怎么上线）

```bash
# 本机（仓库根）：源码**不在**自动推送白名单（白名单只有 data/ context/ alerts/）⇒ 必须手动提交
git add <改动文件> && git commit -m "..." && git push origin master
# 之后无需任何服务器操作：marketpulse-pull.timer 每 5 分钟 `git pull --ff-only origin master`（**整仓**）
```

- **不需要重启服务**：模板由 Jinja `Environment(loader=FileSystemLoader(...))` 提供，`auto_reload` 默认 `True` ⇒ 模板改动下一次请求即生效；
  静态资源（`web/static/**`）按请求读 + `_RevalidateStatic` 一律 `no-cache` + `?v=` 取 `_ASSET_FILES` 的最大 mtime ⇒ 浏览器必然拿到新副本。
- 只有 **`data/marketpulse.db` 的 sha256 变了**才会「清 `-wal`/`-shm` + `systemctl restart marketpulse`」（`marketpulse-pull` 里写死）。
- 想立刻上线（不等那 5 分钟）：`ssh root@<ECS> 'sudo -u marketpulse /usr/local/bin/marketpulse-pull'`。
- 上线验收（本机即可，鉴权已关）：

```bash
curl -sk https://123.60.176.219:8443/ | grep -c <你新增的静态资源名>       # 期望 ≥1
curl -sk -o /dev/null -w '%{http_code}\n' https://123.60.176.219:8443/static/<你新增的资源>  # 期望 200
```

```bash
sudo cat /srv/marketpulse/.env          # 看 Basic Auth 用户名/口令
sudo nano /srv/marketpulse/.env         # 改口令后必须重启
sudo systemctl restart marketpulse
systemctl status marketpulse --no-pager
journalctl -u marketpulse -f            # 应用日志（含 akshare 降级等 WARNING）
systemctl list-timers marketpulse-pull.timer --no-pager   # 下一次拉取时间
sudo -u marketpulse /usr/local/bin/marketpulse-pull       # 手动拉一次（等同 timer 行为）
```

复验（服务器上）：

```bash
curl -s  -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/healthz   # 200（免鉴权）
curl -s  -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/          # 401（鉴权生效）
curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8443/healthz  # 200
```

带凭据访问：

```bash
curl -sk -u "$USER:$PASS" -o /dev/null -w '%{http_code}\n' https://123.60.176.219:8443/
```

## 3. 关键约束（踩过的坑，别重犯）

| 约束 | 原因 / 现象 |
|---|---|
| **Basic Auth 凭据只从进程环境读**（应用不解析 `.env`） | 所以必须由 systemd `EnvironmentFile` 注入；手工前台跑要自己 `export MP_AUTH_USER/MP_AUTH_PASS` |
| **`MP_AUTH_DISABLED=1`** | 关闭全站 Basic Auth ⇒ 打开即看（2026-10-17 用户决定，**已启用**；凭据行保留，改回 `0` 即恢复登录） |
| **`RAILWAY_ENVIRONMENT=1`** | 复用应用自带的只读开关 ⇒ 设置页只读、`POST /api/settings` 403（**已启用**：公网匿名可写是实测风险，见下）。副作用：只读提示文案写的是「Railway 临时文件系统」，语义不准。全仓只有 `src/settings_store.is_readonly()` 读它 |
| **`MP_SKIP_RESTORE=1`** | **不要设**：会跳过空库恢复链（`data/backup/` → DB） |
| 公网匿名可写（实测） | 鉴权关闭后，无凭据 `POST /api/settings` 曾返回 `{"saved":true}` 并在服务器生成 `config.json.bak-*` ⇒ **必须**同时设 `RAILWAY_ENVIRONMENT=1` 锁只读；锁后复测 403 且 `config.json` mtime 不变 |
| **换 `marketpulse.db` 必须先清 `-wal`/`-shm`** | 旧 WAL 与新库不配对，轻则读到旧数据、重则 `database disk image is malformed`；应用对 `data/` 只读，删 WAL 不丢数据（已由 `marketpulse-pull` 强制执行） |
| **`config.json` 不在仓库里** | 被 `.gitignore` 排除 ⇒ 每次重装/换机都要手工 scp 一份；设置页改的是服务器本地那份，`git pull` 不会覆盖它 |
| **别用 `cp -a "$SRC"/. "$DST"/` 铺代码** | 它会把**源目录自身**的属性（如 `mktemp` 的 `drwx------ root`）套到目标目录 ⇒ 服务用户连目录都进不去，报 `sudo: unable to execute .../venv/bin/pip: Permission denied`。用 `tar -c -C SRC . \| tar -x -C DST` |
| **venv 由服务用户创建** | root 建的 venv 再 `sudo -u` 执行容易出现属主/权限混用 |
| **服务器到 github.com:443 不通** | 实测超时（`raw.githubusercontent.com` 同样），所以 `git clone https://...` 不可用；**22 端口可达** ⇒ 走 SSH deploy key |
| **codeload tar 包只用于首次落地** | 2 MB/次；每 5 分钟拉一次 ≈ 17 GB/月，占流量包 100 GB 的 17% ⇒ 日常更新走 git 增量 |
| **pip 直连 pypi.org 8 s/请求** | 用清华镜像（实测 1.04 s） |
| **Yahoo 数据在服务器上取不到** | 实测 `query1/query2.finance.yahoo.com` 无 UA 429、带 UA 403 ⇒ `/api/macro`、`/api/watchlist` 快照缺失时的实时回退、盘中实时价会降级；DB/context 驱动的页面不受影响。要救就给应用设 `HTTPS_PROXY`（需要服务器可达的代理） |

## 4. 与 Railway 的关系（2026-10-17：Railway 线**决定下线**）

**现状（2026-10-17 实测）**：`marketpulse-blue.up.railway.app` 探活返回
`404 {"status":"error","code":404,"message":"Application not found"}`（Railway 边缘说这个应用不存在）；
最近若干提交在 GitHub 上也**没有任何 Railway 部署状态**（`/commits/<sha>/status` → `statuses: 0`）
⇒ Railway 那份实际已经不可用，线上以本文档的 ECS 部署为准。

**关停步骤**（需要账号操作，仓库侧改不了）：

1. Railway dashboard → 该项目 → Settings → Danger zone → **Delete Service / Delete Project**（不可逆；释放域名与用量）；
2. GitHub → Settings → Applications → **Railway** → Configure → Repository access → 把 `Blueety/MarketPulse` 移出（或直接 Uninstall）⇒ 之后 push 不会再触发 Railway 部署；
3. 顺手在 Railway → Account → Tokens 里撤销遗留 token。

**仓库里这几处一律保留，不要「顺手清理」**：

| 文件 | 为什么留着 |
|---|---|
| 根目录 `app.py` | 它是 Railway 的入口（线上启动命令是 `uvicorn app:app`）。2026-09-24 有人把它当「误放的实验文件」挪走 ⇒ **每一次部署都失败**（线上 502 `Application failed to respond`），而本地 `uvicorn web.app:app` + 全部门禁全绿、**本地测试发现不了**。删它同样会炸掉任何**遗留的**自动部署（服务可能只是探活不可达，不代表 Railway 侧已彻底不存在） |
| `railway.toml` / `Procfile` / `railpack.json` | 惰性配置（线上生效的是 dashboard 侧的启动命令）；删掉并不能「关掉 Railway」，反而会让护栏测试 `tests/test_web.py::test_deploy_start_commands_reference_an_importable_module` 失去输入 |

ECS 这份是 systemd + nginx 的独立部署，**不参与 Railway 的部署流程**，也不要求仓库里加任何 CI 配置。

## 5. 切真证书（域名备案后）

```bash
# 1) 域名 A 记录 → 123.60.176.219；完成 ICP 备案
# 2) 换证书文件（华为云免费证书或 certbot）
sudo cp 你的域名.crt /etc/nginx/ssl/marketpulse.crt
sudo cp 你的域名.key /etc/nginx/ssl/marketpulse.key
# 3) 改 /etc/nginx/conf.d/marketpulse.conf：listen 443 ssl / server_name 你的域名
sudo nginx -t && sudo systemctl reload nginx
```

## 6. 回滚 / 卸载

```bash
sudo systemctl disable --now marketpulse marketpulse-pull.timer
sudo rm -f /etc/systemd/system/marketpulse.service /etc/systemd/system/marketpulse-pull.{service,timer}
sudo rm -f /usr/local/bin/marketpulse-pull /etc/sudoers.d/marketpulse-pull
sudo rm -f /etc/nginx/conf.d/marketpulse.conf && sudo nginx -t && sudo systemctl reload nginx
# 代码与数据（含 .env / config.json）保留在 /srv/marketpulse，需要时再 rm -rf
```
