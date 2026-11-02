# legacy/ —— 已退役文件存档（**仅存档，勿执行**）

本目录只用于历史留档（审计 / 部署沿革 / 排障取证）。里面的脚本**不要运行**：它们要么指向
已废弃的入口与平台，要么带破坏性默认值（例如裸跑就改库/清表）。现行入口与命令见
`AGENTS.md` 的 Project Map、`docs/commands.md`。

| 文件 | 为什么退役 |
|---|---|
| `app.py` | 旧 Railway 入口（`from web.app import app` + `uvicorn.run`）。现行部署由 `Procfile` / `railpack.json` / `railway.toml` 统一跑 `uvicorn web.app:app --host 0.0.0.0 --port $PORT`，本文件是平台自动检测时代的残留。 |
| `render.yaml` | Render 平台部署配置；部署早已迁到 Railway（`railway.toml`），保留只为回溯部署历史。 |
| `migrate_to_sqlite.py` | 三十一期 `data/history.json → data/marketpulse.db` 的一次性迁移脚本：`--db` / `--json` 都有默认值，且会 `DELETE FROM history` ⇒ **裸跑即清空生产库**。迁移已完成，脚本随本轮归档，命令已从 `docs/commands.md` 移除。 |
