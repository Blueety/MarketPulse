# 2026-10-17 MarketPulse 部署到华为云 ECS（自签 HTTPS + systemd + nginx 反代）

## 目标

把 MarketPulse 的 **Web 看板**从 Railway 复制一份到已有的华为云 ECS（上海，Ubuntu 24.04，2 核 2 GiB，公网 `123.60.176.219`），
与另一站点 Todo（8080）共存。数据新鲜度沿用现有架构：**本机 Hermes 生成 `data/` `context/` `alerts/` → GitHub → 服务器拉取**。

## 用户已确认的三个决策（本轮 ask）

| 决策 | 选择 |
|---|---|
| 访问方式 | **自签 HTTPS（8443）** —— Basic Auth 凭据必须加密传输；IP 直连免备案；代价是浏览器首次证书警告 |
| 数据新鲜度 | **ECS 每 5 分钟拉取**（本机 Hermes 继续生成并 auto-push） |
| Basic Auth 口令 | **由 agent 在服务器上生成 16 位随机口令**，不打印到聊天 |

## 只读分析结论（决定方案的事实，均有实测/代码证据）

| 事实 | 证据 |
|---|---|
| 应用是 FastAPI + uvicorn，无 SSR 模板渲染压力 | `web/app.py`；`app.py` 转发入口；`Procfile`/`railway.toml` 的 `uvicorn web.app:app` |
| web 进程**只读**看板：唯一可写 = `config.json`（+ 同目录 `.bak-*`）；`data/` 需可写（SQLite WAL 建库/空库恢复） | scout 报告 §1.3；`web/app.py:5-6` docstring；`src/storage.py:372-440` |
| 运行时数据全部来自**仓库内**文件：`data/marketpulse.db`(tracked) + `data/backup/` + `data/news.json` + `data/watchlist.json` + `context/*.json` + `alerts/*.md` | scout 报告 §1.1/§1.2 逐端点表 |
| 重依赖**按需 import**（不在启动路径）：akshare（CN 取数）、matplotlib（日报图）、playwright（日报图片，未在 requirements 中） | `src/fetcher.py:168,474,615,680`、`src/cn_econ_fetcher.py:250,586`、`src/reporter.py:387`、`src/image_renderer.py:220`（有 try/except 降级） |
| 服务器 Python 3.12.3 + venv 可用；内存可用 1379 MB；磁盘余 35 GB | 实测 `python3 -V` / `free -m` / `df -h` |
| 服务器到**国内数据源**通畅：腾讯行情 0.13 s / 东财 / AkShare 系可用 | 实测 `qt.gtimg.cn 200`、`push2.eastmoney.com 404(可达)` |
| 服务器到 **Yahoo** 被拒：无 UA 429、带 UA 403（不是 GFW 断连，是 Yahoo 侧拒） | 实测 `query1/query2.finance.yahoo.com` |
| 服务器 **github.com:443 与 raw.githubusercontent.com 超时**；`api.github.com` 200、`codeload.github.com` 200 | 实测；⇒ **git pull over HTTPS 不可行** |
| 服务器 **github.com:22 可达**（`Permission denied (publickey)` = 握手成功） | 实测 ⇒ 用 **SSH deploy key** 做拉取通道 |
| codeload tar 包（`refs/heads/master`）200、**2.0 MB / 1.25 s** | 实测 ⇒ 用它做**首次**代码落地（无需凭据）；**不**用于每 5 分钟轮询（2 MB×288/天 ≈ 17 GB/月，占流量包 100 GB 的 17%） |
| `requests==2.34.2` / `pytest==9.1.1` 在 PyPI 真实存在 | PyPI JSON API 查询 |
| pip 走 pypi.org 直连 8 s（太慢）；清华 TUNA 1.04 s | 实测 ⇒ pip 用清华镜像 |

## 方案

```
浏览器 ──HTTPS(自签,8443)──> nginx ──http──> 127.0.0.1:8000 uvicorn web.app:app (systemd, user=marketpulse)
                                              └─ 读 /srv/marketpulse/{data,context,alerts,web}
数据：本机 Hermes → GitHub(master) ──ssh:22 deploy key──> marketpulse-pull.timer(每5分钟) → 变更则重启服务
```

## 涉及文件（全部新增，**不改任何应用代码**）

| 文件 | 作用 |
|---|---|
| `deploy/install-server.sh` | 服务器侧一次性安装（幂等）：装包 → 建用户 → 代码落地（tar 或 git）→ venv+pip（清华镜像）→ `.env`（生成随机口令）→ 自签证书 → nginx conf（`nginx -t` 闸门）→ systemd 单元 + timer + sudoers → 自检 |
| `deploy/nginx-marketpulse.conf` | 站点模板：`listen __TLS_PORT__ ssl` + 反代 `127.0.0.1:__APP_PORT__`（透传 Authorization / X-Forwarded-*） |
| `deploy/marketpulse.service` | 应用 systemd 单元（`User=marketpulse`、`MemoryMax=1G`、加固项、`--proxy-headers`） |
| `deploy/marketpulse-pull.service` / `.timer` | 每 5 分钟拉取 GitHub；DB 变化则 `rm -f *.db-wal *.db-shm` + 重启 |
| `deploy/marketpulse-pull.sh` | 拉取脚本本体（安装到 `/usr/local/bin/marketpulse-pull`，**放仓库外**避免与 pull 冲突） |
| `docs/deploy-ecs.md` | 运行手册（部署步骤、验证、排查、回滚、口令查看、切真证书） |
| `tasks/2026-10-17-ecs-deploy/{plan,journal}.md` | 本任务计划与日志 |

## 实施步骤

1. 写齐上述 `deploy/` 资产与手册；
2. 本机静态校验：`bash -n` 全部 shell 脚本；nginx 模板占位符与渲染逻辑核对（本机无 nginx，闸门在服务器侧 `nginx -t`）；
3. `scp` 资产到服务器 → 执行 `install-server.sh`（代码走 codeload tar，首次不依赖 GitHub 凭据）；
4. 服务器侧验证：`systemctl status` / `journalctl` / `curl 127.0.0.1:8000/healthz`（免鉴权 200）/ 无凭据 `401` / `-k https://127.0.0.1:8443/healthz`；
5. 生成 deploy key → 交给用户加到 GitHub Deploy Keys（只读）→ 重跑安装脚本开启 `git pull` 通道 → 实测一次 pull；
6. 用户控制台放行 **TCP 8443** 后，本机外网复测：`curl -k` 401/200、真 Chromium（`ignore_https_errors`）打开页面看渲染与 API；
7. 报告 + journal + `docs/pitfalls.md` 追加实测坑。

## 验证命令

```bash
# 服务器侧
systemctl status marketpulse --no-pager
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/healthz          # 期望 200（免鉴权）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/                 # 期望 401（鉴权生效）
curl -sk -o /dev/null -w '%{http_code}\n' https://127.0.0.1:8443/healthz        # 期望 200
journalctl -u marketpulse -n 30 --no-pager
systemctl list-timers marketpulse-pull.timer --no-pager
# 本机（外网）
curl -sk -o /dev/null -w '%{http_code}\n' https://123.60.176.219:8443/healthz
```

## 测试 seam

本项目无 Web 部署相关测试；本次是**基础设施任务、应用代码零改动** ⇒ 不新增测试（符合 AGENTS.md「纯 Python 脚本项目未配置 lint/build」现状）。
验收靠运行时取证：systemd 状态 + 三个 HTTP 断言 + 真浏览器渲染 + 外网复测。

## 预估 diff 范围

新增约 500–650 行（4 个 shell/配置资产 + 1 份手册 + 任务文件），**应用代码 0 行改动**，不新增 Python 依赖。

## 已知风险（须在报告里对用户明说）

1. **Yahoo 取数在服务器上会失败**（403/429）⇒ `/api/macro`、`/api/watchlist` 的快照缺失回退、盘中实时价会降级；DB/context 驱动的页面不受影响。缓解：Hermes 本机继续生成数据（含 Yahoo 数据）并经 GitHub 同步过来。
2. **自签证书**：浏览器每次（或首次）警告；不影响加密强度，但**证书变更后**需要重新接受。
3. 2 GiB 内存：已设 `MemoryMax=1G` 兜底，避免 OOM 波及 sshd；akshare/pandas 首次导入较慢。
4. `config.json` 被设置页写改（服务器本地），**不会**被 `git pull` 覆盖（它在 .gitignore 内）。
5. 首次安装 `pip install` 会拉 akshare/pandas/matplotlib（约 300 MB 磁盘、数分钟）；服务器磁盘余 35 GB，充裕。
