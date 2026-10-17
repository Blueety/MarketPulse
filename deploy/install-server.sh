#!/usr/bin/env bash
# MarketPulse → 华为云 ECS 一次性安装（root 执行；幂等，可重复跑）。
#
# 用法：
#   scp deploy/install-server.sh deploy/nginx-marketpulse.conf deploy/marketpulse.service \
#       deploy/marketpulse-pull.service deploy/marketpulse-pull.timer deploy/marketpulse-pull.sh \
#       [config.json] root@<IP>:~/
#   ssh -t root@<IP> 'PUBLIC_IP=<公网IP> bash ~/install-server.sh'
#
# 做十件事：
#   1) 装系统包（python3-venv / pip / openssl / git / curl）
#   2) 建服务用户（默认 marketpulse）
#   3) 代码落地：有 deploy key 走 git（增量、可自动更新），否则走 codeload tar 包（首次无凭据也能装）
#   4) venv + pip install（走清华镜像；用 requirements.txt 的 sha256 做 stamp，内容没变就跳过）
#   5) config.json（gitignore 排除 ⇒ 不在 tar 包里，需随脚本一起 scp 上来）
#   6) .env：生成 16 位随机 Basic Auth 口令（**不打印**，只给查看命令）
#   7) 自签证书（SAN = 公网 IP），装在 /etc/nginx/ssl/marketpulse.{crt,key}
#   8) nginx 反代（8443 TLS → 127.0.0.1:8000；nginx -t 失败回滚）
#   9) systemd：marketpulse.service + marketpulse-pull.{service,timer}（每 5 分钟拉数据）+ sudoers 白名单
#  10) 自检：/healthz 200、无凭据 401、TLS 侧 200
#
# 可覆盖变量：APP_DIR APP_USER APP_PORT TLS_PORT REPO BRANCH PUBLIC_IP
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/marketpulse}"
APP_USER="${APP_USER:-marketpulse}"
APP_PORT="${APP_PORT:-8000}"
TLS_PORT="${TLS_PORT:-8443}"
REPO="${REPO:-Blueety/MarketPulse}"
BRANCH="${BRANCH:-master}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
KEY_DIR=/etc/marketpulse
KEY="$KEY_DIR/deploy_key"
CONF=/etc/nginx/conf.d/marketpulse.conf
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\n[install] %s\n' "$*"; }
ok()   { printf '  ✓ %s\n' "$*"; }
warn() { printf '  ⚠ %s\n' "$*"; }
die()  { printf '\n[install] ✗ %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "请用 root 执行，或 sudo bash $0"

# 公网 IP 用于证书 SAN；未传则尝试云元数据
if [ -z "${PUBLIC_IP:-}" ]; then
  PUBLIC_IP="$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
fi
[ -n "${PUBLIC_IP:-}" ] || die "缺公网 IP：请用 PUBLIC_IP=<公网IP> bash $0 显式传入（证书 SAN 需要）"

for f in nginx-marketpulse.conf marketpulse.service marketpulse-pull.service marketpulse-pull.timer marketpulse-pull.sh; do
  [ -f "$HERE/$f" ] || die "同目录缺少 $f（请把 deploy/ 下的资产一起 scp 上来）"
done

log "参数：APP_DIR=$APP_DIR  APP_USER=$APP_USER  应用端口=$APP_PORT  对外端口=$TLS_PORT  PUBLIC_IP=$PUBLIC_IP"

# ------------------------------------------------------------ 1) 系统包
log "1/10 系统包"
export DEBIAN_FRONTEND=noninteractive
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y -qq
  apt-get install -y -qq python3-venv python3-pip openssl git curl ca-certificates nginx >/dev/null
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q python3-pip openssl git curl ca-certificates nginx >/dev/null
elif command -v yum >/dev/null 2>&1; then
  yum install -y -q python3-pip openssl git curl ca-certificates nginx >/dev/null
else
  die "未识别的包管理器"
fi
ok "python3 $(python3 -V 2>&1 | awk '{print $2}') ｜ nginx $(nginx -v 2>&1 | awk -F/ '{print $2}')"

# ------------------------------------------------------------ 2) 服务用户
log "2/10 服务用户 $APP_USER"
if id "$APP_USER" >/dev/null 2>&1; then
  ok "已存在"
else
  useradd --system --create-home --home-dir "/home/$APP_USER" --shell /usr/sbin/nologin "$APP_USER"
  ok "已创建（system 用户，无登录 shell）"
fi
mkdir -p "$APP_DIR"
# 目录属性必须一开始就正确：服务用户要能**穿过**（x）并**写**仓库根（设置页写 config.json + .bak-*）
chown "$APP_USER:$APP_USER" "$APP_DIR"
chmod 755 "$APP_DIR"

# ------------------------------------------------------- 3) deploy key + 代码落地
log "3/10 代码落地"
mkdir -p "$KEY_DIR" && chmod 700 "$KEY_DIR"
if [ ! -f "$KEY" ]; then
  ssh-keygen -t ed25519 -f "$KEY" -N '' -C "marketpulse@$(hostname)" -q
  ok "已生成 deploy key：$KEY"
fi
chown "$APP_USER" "$KEY"; chmod 600 "$KEY"
chown "$APP_USER" "$KEY_DIR" 2>/dev/null || true

GIT_SSH="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
KEY_OK=0
if sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH" git ls-remote "git@github.com:$REPO.git" HEAD >/dev/null 2>&1; then
  KEY_OK=1
  ok "deploy key 可用 ⇒ 走 git 通道（之后可自动增量更新）"
else
  warn "deploy key 还不可用（多半是公钥没加到 GitHub）⇒ 本次走 codeload tar 包"
fi

if [ "$KEY_OK" = "1" ]; then
  if [ -d "$APP_DIR/.git" ]; then
    sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH" git -C "$APP_DIR" pull --ff-only -q
    ok "git pull 完成（$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)）"
  else
    sudo -u "$APP_USER" git -C "$APP_DIR" init -q -b "$BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" remote add origin "git@github.com:$REPO.git" 2>/dev/null || true
    sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH" git -C "$APP_DIR" fetch -q origin "$BRANCH"
    # --hard 只覆盖被跟踪文件；venv/ 与 .env 未跟踪 ⇒ 不受影响
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard -q "origin/$BRANCH"
    ok "已建立 git 工作区（$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)）"
  fi
else
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL --max-time 180 -o "$TMP/mp.tar.gz" "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" \
    || die "codeload 下载失败（网络受限？）"
  tar -xzf "$TMP/mp.tar.gz" -C "$TMP" --strip-components=1
  # 用 tar 管道而不是 `cp -a "$TMP"/. "$APP_DIR"/`：后者会把**源目录自身**的属性
  # （mktemp 的 drwx------ root）套到目标目录上 ⇒ $APP_DIR 变成 700 root，服务用户连目录都进不去
  # （2026-10-17 实测踩到：sudo: unable to execute .../venv/bin/pip: Permission denied）
  tar -c -C "$TMP" . | tar -x -C "$APP_DIR"
  ok "tar 包落地完成（$BRANCH，$(du -sh "$APP_DIR" | awk '{print $1}')）"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 755 "$APP_DIR"
[ -f "$APP_DIR/web/app.py" ] || die "$APP_DIR/web/app.py 不存在 —— 代码没落地成功"
[ -f "$APP_DIR/app.py" ] || warn "根目录 app.py 缺失（Railway 时代的转发入口，历史上删它会 502；本地版正常不该缺）"

# ------------------------------------------------------------ 4) venv + 依赖
log "4/10 venv + 依赖（清华镜像；requirements.txt 未变则跳过）"
REQ_HASH="$(sha256sum "$APP_DIR/requirements.txt" | awk '{print $1}')"
STAMP="$APP_DIR/venv/.requirements-stamp"
if [ -d "$APP_DIR/venv" ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$REQ_HASH" ]; then
  ok "依赖已是最新（stamp 命中）"
else
  # venv 由服务用户创建（避免 root 建的 venv 与 sudo -u 执行混用）；已存在但不可执行则重建
  if [ ! -d "$APP_DIR/venv" ] || ! sudo -u "$APP_USER" test -x "$APP_DIR/venv/bin/pip"; then
    rm -rf "$APP_DIR/venv"
    sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
  fi
  chown -R "$APP_USER:$APP_USER" "$APP_DIR/venv"
  sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q -U pip -i "$PIP_INDEX" >/dev/null
  log "  pip install -r requirements.txt（akshare/pandas/matplotlib 首次较慢，约 1-3 分钟）"
  sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt" -i "$PIP_INDEX"
  echo "$REQ_HASH" > "$STAMP"
  ok "依赖安装完成"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# ------------------------------------------------------------ 5) config.json
log "5/10 config.json（gitignore 排除，需随脚本 scp 上来）"
if [ -f "$APP_DIR/config.json" ]; then
  ok "已存在（$(stat -c '%y' "$APP_DIR/config.json" | cut -d. -f1)），保留不覆盖"
elif [ -f "$HERE/config.json" ]; then
  cp "$HERE/config.json" "$APP_DIR/config.json"
  ok "已从上传副本安装（阈值/自选股/macro 配置）"
else
  warn "没有 config.json ⇒ 应用走内置默认（自选股卡片会隐藏、阈值用默认值）"
fi

# ------------------------------------------------------------ 6) .env（口令）
log "6/10 .env（Basic Auth 凭据）"
if [ -f "$APP_DIR/.env" ]; then
  ok "已存在，保留不覆盖"
else
  PASS="$(python3 -c 'import secrets;print(secrets.token_urlsafe(16))')"
  cat > "$APP_DIR/.env" <<EOF
# MarketPulse Web 看板环境（systemd EnvironmentFile 注入；应用只读进程环境，不解析本文件）
# ⚠️ 以下三个「不要设置」：MP_AUTH_DISABLED=1 会关闭全站鉴权；RAILWAY_ENVIRONMENT 会让设置页变只读；
#    MP_SKIP_RESTORE=1 会跳过空库恢复。
MP_AUTH_USER=marketpulse
MP_AUTH_PASS=$PASS
EOF
  chmod 600 "$APP_DIR/.env"
  ok "已生成随机口令（16 位，未打印）"
fi
chown "$APP_USER" "$APP_DIR/.env"

# ------------------------------------------------------------ 7) 自签证书
log "7/10 自签证书（SAN = IP:$PUBLIC_IP）"
mkdir -p /etc/nginx/ssl
if [ -f /etc/nginx/ssl/marketpulse.crt ]; then
  ok "已存在，保留（换证书请替换这两个文件后 systemctl reload nginx）"
else
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout /etc/nginx/ssl/marketpulse.key -out /etc/nginx/ssl/marketpulse.crt \
    -subj "/CN=$PUBLIC_IP" -addext "subjectAltName=IP:$PUBLIC_IP" 2>/dev/null
  chmod 600 /etc/nginx/ssl/marketpulse.key
  ok "已生成（自签 ⇒ 浏览器首次会警告，但传输是加密的）"
fi

# ------------------------------------------------------------ 8) nginx
log "8/10 nginx 反代（$TLS_PORT → 127.0.0.1:$APP_PORT）"
[ -f "$CONF" ] && cp -f "$CONF" "$CONF.bak"
sed -e "s|__TLS_PORT__|$TLS_PORT|g" -e "s|__APP_PORT__|$APP_PORT|g" -e "s|__SERVER_NAME__|$PUBLIC_IP|g" \
  "$HERE/nginx-marketpulse.conf" > "$CONF"
if ! nginx -t 2>/dev/null; then
  echo "[install] nginx -t 失败，输出如下：" >&2
  nginx -t || true
  if [ -f "$CONF.bak" ]; then mv -f "$CONF.bak" "$CONF"; else rm -f "$CONF"; fi
  die "nginx 配置有问题 ⇒ 已回滚 $CONF"
fi
rm -f "$CONF.bak"
systemctl enable --now nginx >/dev/null 2>&1 || systemctl start nginx
systemctl reload nginx
ok "nginx -t 通过并已 reload（$(systemctl is-active nginx)）"

# ------------------------------------------------------------ 9) systemd
log "9/10 systemd 单元 + 拉取 timer + sudoers"
render() { sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" -e "s|__APP_PORT__|$APP_PORT|g" "$1" > "$2"; }
render "$HERE/marketpulse.service"      /etc/systemd/system/marketpulse.service
render "$HERE/marketpulse-pull.service" /etc/systemd/system/marketpulse-pull.service
render "$HERE/marketpulse-pull.timer"   /etc/systemd/system/marketpulse-pull.timer
install -o root -g root -m 0755 "$HERE/marketpulse-pull.sh" /usr/local/bin/marketpulse-pull
echo "$APP_USER ALL=(root) NOPASSWD: /bin/systemctl restart marketpulse.service" > /etc/sudoers.d/marketpulse-pull
chmod 440 /etc/sudoers.d/marketpulse-pull
visudo -cf /etc/sudoers.d/marketpulse-pull >/dev/null || die "sudoers 校验失败"
ok "单元已安装（应用 + 每 5 分钟拉取；sudoers 只放行一条 restart）"

systemctl daemon-reload
systemctl enable --now marketpulse.service >/dev/null 2>&1
systemctl enable --now marketpulse-pull.timer >/dev/null 2>&1
ok "marketpulse.service：$(systemctl is-active marketpulse) ｜ timer：$(systemctl is-active marketpulse-pull.timer)"

# ------------------------------------------------------------ 10) 自检
log "10/10 自检"
wait_code() { # url 期望码 超时秒
  local url="$1" want="$2" t="${3:-40}" code=""
  for _ in $(seq 1 "$t"); do
    code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 3 "$url" 2>/dev/null || true)"
    [ "$code" = "$want" ] && { echo "$code"; return 0; }
    sleep 1
  done
  echo "$code"; return 1
}

c_health="$(wait_code "http://127.0.0.1:$APP_PORT/healthz" 200 45)" || true
[ "$c_health" = "200" ] && ok "应用 /healthz → 200（免鉴权健康检查）" || warn "应用 /healthz → $c_health（期望 200，看 journalctl -u marketpulse）"

c_root="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:$APP_PORT/" || true)"
[ "$c_root" = "401" ] && ok "应用 / → 401（Basic Auth 生效，未裸奔）" || warn "应用 / → $c_root（期望 401！若为 200 说明鉴权未生效）"

c_tls="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "https://127.0.0.1:$TLS_PORT/healthz" || true)"
[ "$c_tls" = "200" ] && ok "nginx TLS $TLS_PORT /healthz → 200" || warn "nginx TLS $TLS_PORT /healthz → $c_tls（看 nginx -t / ss -lntp）"

cat <<EOF

[install] 完成。
  应用：http://127.0.0.1:$APP_PORT  （systemd: marketpulse.service，User=$APP_USER）
  对外：https://$PUBLIC_IP:$TLS_PORT/  ← 自签证书，浏览器会警告一次
  代码：$APP_DIR$([ -d "$APP_DIR/.git" ] && echo "（git 通道，timer 每 5 分钟自动拉取）" || echo "（tar 通道：把下面的公钥加到 GitHub 后重跑本脚本即可切换为自动拉取）")
  口令：sudo cat $APP_DIR/.env        ← 修改后 systemctl restart marketpulse
  日志：journalctl -u marketpulse -f

  还差两步（都要你手动）：
    1) 华为云控制台 → 安全组 → 入方向 → 放行 TCP $TLS_PORT
    2) GitHub → 仓库 Settings → Deploy keys → Add deploy key（只读即可）：
$(cat "$KEY.pub" | sed 's/^/       /')

  复验：curl -sk -o /dev/null -w '%{http_code}\n' https://$PUBLIC_IP:$TLS_PORT/healthz   # 期望 200
        curl -sk -o /dev/null -w '%{http_code}\n' https://$PUBLIC_IP:$TLS_PORT/           # 期望 401
EOF
