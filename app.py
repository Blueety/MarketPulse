"""Railway 部署入口 —— 从 `web/app.py` 导入 FastAPI 应用。

🔴 **本文件不可删除、不可移动**（2026-09-24 线上事故）：

- Railway 服务的**实际**启动命令是 `uvicorn app:app`（2026-09-01 的部署修复记录
  `tasks/20260901-railway-deploy-fix/plan.md` 写下过这条命令；dashboard 的 config-as-code
  开关是否让仓库内 `railway.toml` / `Procfile` / `railpack.json` 生效，本地无从确认）。
- 2026-09-24 把它当作"误放的实验文件"移进 `tasks/2026-09-24-qa-bughunt/legacy/` ⇒ **从那一刻起
  每一次部署都失败**（GitHub commit status = `failure`，线上 502 `Application failed to respond`），
  而本地 `uvicorn web.app:app` 与全部门禁（pytest / verify_ui）**完全正常**，本地怎么测都发现不了。
  恢复本文件的提交 = 线上恢复。

⇒ 3 行转发模块，成本为零，却是线上唯一入口。改这个仓库根目录的文件前先读 `docs/pitfalls.md`。
"""
from web.app import app

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
