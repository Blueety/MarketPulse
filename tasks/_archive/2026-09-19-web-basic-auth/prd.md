# PRD — web 层访问控制（HTTP Basic Auth）

- **任务档**：`tasks/2026-09-19-web-basic-auth/`
- **提出**：2026-09-19（架构师能力缺口盘点；P0 序列第 1 个）
- **状态**：需求定稿，待实施

---

## Goal

给 MarketPulse 的整个 web 层加访问控制，堵住「线上零鉴权、数据全网可读」这个 P0 缺口。

## 问题陈述（取证，非转述）

`grep -n "auth|login|token|password|API_KEY|Secret" web/app.py` → **零命中**。

curl 实测 `https://marketpulse-blue.up.railway.app`（2026-09-19 23:0x）：

| 请求 | 结果 |
|---|---|
| `GET /` | **200** |
| `GET /api/timeline?days=90` | **200** |
| `GET /api/watchlist` | **200**，返回 11 只自选 ETF 的 symbol + 实时价 + 涨跌幅 |

⇒ 任何人拿到 URL 即可读取全部数据；`/api/watchlist` 实质暴露用户的自选配置方向。

## 范围

**做**
1. 全站（页面 + 10 个 API）默认要求认证
2. 放行一个无鉴权的健康检查端点，供 Railway healthcheck
3. 本地开发 / 自动化验收可用环境变量关闭鉴权
4. 单测 + UI 验收脚本覆盖鉴权行为本身
5. 文档同步（部署必须配的 env、API 契约变更）

**不做**
- 登录页 / 会话 / 登出 / 多用户 / 角色权限
- 改 `src/**`、改前端模板与静态资源
- G1（`wecom_*.py` 硬编码凭据）→ **独立任务，P0 序列第 2 个**
- G8（验收信号分层）→ **独立任务，P0 序列第 3 个**
- 保护 `alerts/` `context/` 文件本体（非 web 层）

## 约束

- **零新依赖**（AGENTS.md 纪律）：用 stdlib `base64` + `hmac.compare_digest`
- **不修改** `.env`、生产配置、生成文件
- 保持 `venv/Scripts/python -m uvicorn web.app:app` 手动可跑
- 既有 `verify_ui.py` 的 700+ 条断言**不得因本次改动变红**（G8 教训：红色背景会淹没真回归）

## 验收标准

1. 未带凭据访问 `/`、`/macro`、`/macro/cn`、`/timeline`、任一 `/api/*` → **401** 且响应头带 `WWW-Authenticate: Basic realm="MarketPulse"`
2. `/healthz` 无凭据 → **200**（Railway healthcheck 必须通）
3. 正确凭据 → 200；错误凭据 → 401
4. `MP_AUTH_DISABLED=1` 或**未配置**凭据时全站放行，且启动打印醒目 WARNING
5. `pytest tests/test_web.py -k auth` 全绿；`pytest tests/ -q` 无新增失败
6. `verify_ui.py` 既有断言零新增失败，新增 `AUTH-*` 组全绿
7. 配好 env 部署后，线上 `/` 返 401、`/healthz` 返 200，且**部署不进入重启循环**
