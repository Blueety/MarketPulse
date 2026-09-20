"""敏感配置读取的**唯一入口**（2026-09-20，任务档 `tasks/2026-09-20-wecom-cred-revoke/`）。

## 为什么有这个模块（G1）

企业微信的 `BOT_ID` / `SECRET` 曾以**字面量**直接写死在 `src/wecom_channel.py` /
`src/wecom_sdk.py` / `src/wecom_ws.py` **三个文件**里（同一组值抄了三遍），
而本仓库是 **PUBLIC** —— 凭据在公开仓库里躺了 19 天（首次提交 2026-09-01 `9e414df`）。

处置分两步：① 后台吊销旧凭据（用户侧，唯一真止损）；② **代码里不再有凭据字面量**（本模块）。
把"读敏感配置"收敛成**单点实现**，是为了让"将来某个文件漏改"这条泄露路径不复存在 ——
安全相关的读取逻辑**刻意不做副本**（与 `web/static/*.js` 的多份 shell 副本是有意决策不同）。
`tests/test_wecom_env.py` 的守卫用例会扫描仓库源码，禁止再次出现硬编码凭据。

## 读取优先级（与 `src/news_fetcher.py:_load_env` 同语义，刻意保持一致）

1. 进程环境变量（如 `WECOM_BOT_ID`）
2. 仓库根 `.env`（**已在 `.gitignore:14`** ⇒ 不会入库）
3. `D:/hermes/.env`
4. `~/.hermes/.env`

> 迁移期说明：`src/news_fetcher.py:_load_env` **本轮不动**（保持 diff 最小），
> 它是同一语义的私有副本；后续可收敛到本模块。

⚠️ **`require_env` 而不是到处判空**：带着空 key 去握手只会得到一个"连接被关闭 / 鉴权失败"的
模糊错误，排障成本高。**缺配置属于部署错误，必须立刻、明确地暴露**（plan D-2 已裁定）。
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

#: `.env` 候选文件（**有序**，先命中先用）；均不入库
ENV_FILES: tuple[Path, ...] = (
    BASE_DIR / ".env",
    Path(r"D:/hermes/.env"),
    Path.home() / ".hermes" / ".env",
)


def load_env(key: str) -> str:
    """读敏感配置；取不到返回 `""`（不抛）。

    优先级：进程环境变量 > `.env` 候选文件（见 `ENV_FILES`）。
    行格式按 `KEY=VALUE` 精确匹配键名，值去掉首尾空白与可选的引号。
    """
    val = os.environ.get(key, "")
    if val:
        return val
    for dotenv in ENV_FILES:
        try:
            if not dotenv.exists():
                continue
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("%s=" % key):
                    return line[len(key) + 1:].strip().strip("'\"")
        except OSError:       # 权限/编码问题不该让调用方崩在启动阶段
            continue
    return ""


def require_env(key: str, hint: str = "") -> str:
    """读敏感配置；**缺失即抛 `RuntimeError`**（含变量名与配置位置提示，但**不含任何值**）。

    ⚠️ 报错信息里**绝不打印值**（哪怕是空值），避免凭据经由异常栈再次进入日志/CI 输出。
    """
    val = load_env(key)
    if not val:
        raise RuntimeError(
            "缺少环境变量 %s：请把它配到本机 .env（或 D:/hermes/.env），"
            "不要把凭据写回源码 —— 本仓库为公开仓库。%s" % (key, (" " + hint) if hint else "")
        )
    return val
