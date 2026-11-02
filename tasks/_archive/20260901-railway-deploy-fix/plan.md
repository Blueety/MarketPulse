# Railway 部署修复 — PEP 668 externally-managed-environment

日期：2026-09-01

## 目标

修复 Railway（Nixpacks 构建）部署失败：

```
error: externally-managed-environment
× This environment is externally managed
╰─> This command has been disabled as it tries to modify the immutable `/nix/store` filesystem.
```

让 `pip install -r requirements.txt` 在构建期成功，服务正常启动。

## 涉及文件

- `nixpacks.toml` — 问题根源（删除或改造）
- `railway.toml` — 保留，已正确指定 Python 3.11
- `railpack.json` — 备用配置，本次不启用（Railway 当前 builder 是 nixpacks）
- `Procfile` — 入口命令，与 railway.toml startCommand 需对齐
- `requirements.txt` — 不动

## 根因诊断

### 现象

构建期 `pip install` 报 PEP 668 externally-managed-environment，指向 `/nix/store`。

### 机制

1. `nixpacks.toml` 的 `[phases.setup]` 显式声明 `nixPkgs = ["python311", "python311Packages.pip"]`。
2. `[phases.install]` 直接执行 `pip install -r requirements.txt` —— 这里的 `pip` 是 **Nix 包管理器提供的 pip**（python311Packages.pip），其 site-packages 位于 `/nix/store/.../lib/python3.11/site-packages`。
3. 两个叠加的硬失败：
   - `/nix/store` 是**只读不可变**文件系统，系统级安装必然 PermissionError；
   - Nix 的 Python 环境携带 PEP 668 `EXTERNALLY-MANAGED` 标记，pip 默认拒绝写入外部管理环境 —— 这就是错误文案的直接来源。
4. `--break-system-packages` 在此场景**无效**：它只绕过 PEP 668 检查，但写入目标仍是只读的 `/nix/store`，依然失败。

### 为什么默认 Nixpacks 不会踩坑

Nixpacks 官方 Python provider（检测到 `requirements.txt` 时）的默认流程是：

- nixPkgs 只装 `python311`（不带 nixpkgs 的 pip）；
- 创建**项目内虚拟环境**（`python -m venv`，落在可写的 `/app` 路径）；
- 用 **venv 内的 pip**（从 ensurepip 安装，非 Nix 管理的 pip）执行安装。

venv 内 pip 的目标目录可写、无 EXTERNALLY-MANAGED 标记，所以默认流程从不触发 PEP 668。**问题完全来自 `nixpacks.toml` 对 phases 的覆盖**：它把 Nix 系统 pip 暴露到 PATH 并直接调用，绕过了默认的 venv 隔离。

## 方案对比

| 方案 | 改动 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| A. 删除 `nixpacks.toml` 的 phases 覆盖（或整文件） | 1 个文件 | 最小改动；回归 Nixpacks 默认 venv 流程；版本仍由 `railway.toml` 的 `NIXPACKS_PYTHON_VERSION=3.11` 控制 | 无 | **推荐** |
| B. 保留自定义但改为 venv 显式创建 | nixpacks.toml | 显式可控 | 需要自己维护 venv 路径与 start 命令 PATH，繁琐易错；与默认行为重复 | 不必要 |
| C. `--break-system-packages` | 1 行 | 无 | Nix 下仍写不进只读 store，方案无效 | 否决 |
| D. Dockerfile | 新增 1 文件 + 改 builder | 完全可控、标准 | akshare 依赖链重（pandas/lxml 等），slim 镜像有编译风险；改动面大；Railway 构建时长增加 | 备用（A 失效时再上） |

## 实施步骤（方案 A）

1. 删除 `nixpacks.toml`（或仅清空其 `[phases.*]`，保留空文件）。删除更干净，避免残留配置干扰 Nixpacks 自动检测。
2. `railway.toml` **不动**：`NIXPACKS_PYTHON_VERSION = "3.11"` 继续固定版本；`healthcheckPath`、restart 策略保持不变。
3. 对齐启动命令（一致性修正，非 PEP 668 必需）：
   - 现状：`railway.toml` startCommand = `uvicorn app:app ...`，`Procfile` = `uvicorn web.app:app ...`。
   - 根目录 `app.py` 存在且仅做 `from web.app import app` 转发，两条命令都能跑；但建议统一为 `uvicorn web.app:app --host 0.0.0.0 --port $PORT`（少一层 import 转发，与 Procfile/render.yaml 一致）。Railway 中 startCommand 优先于 Procfile，需两处同改。
4. 不修改 `railpack.json`（当前 builder 为 nixpacks，railpack 不生效；留作将来迁移备选）。

## 验证

- 本地无法直接复现 Nix 环境；用 Docker 模拟 Nix 复现 PEP 668，确认诊断成立：
  ```
  docker run --rm -v D:/AGENT/MarketPulse:/app -w /app nixos/nix nix-shell -p python311 python311Packages.pip --run "pip install -r requirements.txt"
  ```
  预期：复现相同的 externally-managed-environment 错误。
- 修复后验证（无本地 Docker 时直接走 Railway 重新部署）：
  1. Railway 部署日志：`pip install` 阶段成功，无 PEP 668 报错；
  2. 构建产物含 venv（日志可见 `python -m venv` 步骤）；
  3. 启动日志出现 `Uvicorn running on http://0.0.0.0:PORT`；
  4. `GET /` 健康检查通过（healthcheckPath），看板 HTML 返回 200。

## 风险与后续

- **数据为空**：`data/history.json`、`context/*.json`、`alerts/` 均被 `.gitignore` 排除，部署实例没有历史数据，看板初始为空（属预期，与本次修复无关；如需部署侧数据，需另行决定种子策略）。
- akshare 依赖链重（pandas/lxml 等），首次安装耗时较长；均为 manylinux wheel，无需编译，风险低。
- 若删除 nixpacks.toml 后仍失败（Nixpacks 版本行为差异），回退方案 D：改 `railway.toml` builder 为 dockerfile，新增 `Dockerfile`（`python:3.11-slim` + `pip install -r requirements.txt` + `CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "$PORT"]`）。
