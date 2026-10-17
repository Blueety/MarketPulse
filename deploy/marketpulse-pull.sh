#!/usr/bin/env bash
# MarketPulse 数据拉取（由 marketpulse-pull.timer 每 5 分钟调用，User=marketpulse）。
# 安装位置：/usr/local/bin/marketpulse-pull（**放仓库外**：仓库里的同名文件会被 git pull 覆盖/冲突）。
#
# 为什么要「变了才重启」：
#   - context/*.json 与 alerts/*.md 是每请求现读的 ⇒ 不用重启；
#   - data/marketpulse.db 是 SQLite 且带 WAL：git pull 换掉 .db 后，旧的 -wal/-shm 与新库不配对，
#     轻则读到旧数据、重则 "database disk image is malformed" ⇒ 换库时必须清掉 -wal/-shm 并重启进程。
#     应用对 data/ 是只读的（不写历史），所以删 WAL 不会丢数据。
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/marketpulse}"
DB="$APP_DIR/data/marketpulse.db"
KEY=/etc/marketpulse/deploy_key

cd "$APP_DIR"

if [ ! -d .git ]; then
  echo "不是 git 仓库（首次安装走的是 tar 包通道）⇒ 把 deploy key 加到 GitHub 后重跑 install-server.sh"
  exit 0
fi

# 用专用 deploy key（只读、只给这个仓库），不走 root 的凭据
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

before=$(sha256sum "$DB" 2>/dev/null | awk '{print $1}' || echo none)
# 显式给远端+分支：不依赖上游追踪配置（手工 `git init` 建立的工作区默认没有 tracking，
# 裸 `git pull` 会报 "There is no tracking information for the current branch" —— 2026-10-17 实测）
if ! git pull --ff-only --quiet origin "$(git rev-parse --abbrev-ref HEAD)"; then
  echo "git pull 失败（网络不通 / deploy key 被撤 / 本地有改动导致非快进）" >&2
  exit 1
fi
after=$(sha256sum "$DB" | awk '{print $1}')

if [ "$before" != "$after" ]; then
  rm -f "$DB-wal" "$DB-shm"
  # sudoers 里只放行了这一条命令（见 /etc/sudoers.d/marketpulse-pull）
  sudo -n /bin/systemctl restart marketpulse.service
  echo "marketpulse.db 已更新 → 已重启 marketpulse.service"
else
  echo "无数据变化"
fi
