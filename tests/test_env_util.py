"""敏感配置读取（`src/env_util.py`）+ **防再犯守卫**（2026-09-20）。

背景（G1）：`BOT_ID` / `SECRET` 曾以字面量写死在 `src/wecom_channel.py` / `wecom_sdk.py` /
`wecom_ws.py` 三处，而仓库是 **PUBLIC** ⇒ 公开暴露 19 天。
> **2026-09-20 更新**：用户决定不再使用企业微信通道 ⇒ 那三个模块**已删除**。
> 但本文件的**核心产出是最后那条全仓守卫用例** —— 它保护的是整个仓库，不随 wecom 消失，
> 没有它，下一次还会再写一次硬编码凭据。

两条纪律：
- 守卫的失败信息**只含 `文件:行号:变量名`，绝不打印值**（否则等于把凭据又输出到 CI 日志）。
- 「空集不算过」：守卫必须先断言**真的扫描到了足够多的文件**，否则扫 0 个文件也会绿。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src import env_util

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 夹具

@pytest.fixture(autouse=True)
def _no_ambient_env(monkeypatch):
    """隔离：清掉进程环境里可能存在的候选键，避免本机配置劫持用例。"""
    for k in ("MP_TEST_KEY",):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------- env 读取语义

def test_load_env_prefers_process_env_over_dotenv(tmp_path, monkeypatch):
    """优先级：**进程环境变量 > .env 文件**（与 news_fetcher._load_env 同语义）。"""
    dot = tmp_path / ".env"
    dot.write_text("MP_TEST_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setattr(env_util, "ENV_FILES", (dot,))
    monkeypatch.setenv("MP_TEST_KEY", "from-env")
    assert env_util.load_env("MP_TEST_KEY") == "from-env"


def test_load_env_falls_back_to_dotenv(tmp_path, monkeypatch):
    dot = tmp_path / ".env"
    dot.write_text("# 注释\nOTHER=1\nMP_TEST_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setattr(env_util, "ENV_FILES", (dot,))
    assert env_util.load_env("MP_TEST_KEY") == "from-file"


def test_load_env_strips_wrapping_quotes_but_not_inner_content(tmp_path, monkeypatch):
    """`.env` 里 `KEY="值"` 的**外层引号**要被吃掉。

    ⚠️ 但引号**内部**的空白**刻意保留**（只去掉整行外层空白 + 一层包裹引号）——
    与 `news_fetcher._load_env` 同语义，也是本项目的既定取舍：**不 mangle 敏感值**
    （口令里出现前导/尾随空格是合法的，静默 trim 会让"配了却登不上"变得极难排查，
    同 `web/app.py` 的 `MP_AUTH_PASS` 不做 strip）。
    """
    dot = tmp_path / ".env"
    dot.write_text('MP_TEST_KEY="spaced value"\n', encoding="utf-8")
    monkeypatch.setattr(env_util, "ENV_FILES", (dot,))
    assert env_util.load_env("MP_TEST_KEY") == "spaced value"

    dot.write_text('MP_TEST_KEY="  keep inner  "\n', encoding="utf-8")
    assert env_util.load_env("MP_TEST_KEY") == "  keep inner  "


def test_load_env_missing_returns_empty_and_tolerates_bad_file(tmp_path, monkeypatch):
    """取不到 → `""`（不抛）；候选文件不存在/不可读也不许抛（启动阶段不能崩）。"""
    monkeypatch.setattr(env_util, "ENV_FILES", (tmp_path / "nope.env",))
    assert env_util.load_env("MP_TEST_KEY") == ""


def test_require_env_raises_clearly_and_never_prints_the_value(monkeypatch, tmp_path):
    """D-2：缺配置**立刻、明确**报错（带着空 key 去握手只会得到难懂的连接错误）。

    ⚠️ 同时锁住"报错信息不含值"这条 —— 异常栈会进日志/CI，绝不能把凭据带出去。
    """
    monkeypatch.setattr(env_util, "ENV_FILES", (tmp_path / "nope.env",))
    with pytest.raises(RuntimeError) as ei:
        env_util.require_env("MP_TEST_KEY")
    msg = str(ei.value)
    assert "MP_TEST_KEY" in msg and ".env" in msg
    assert "公开仓库" in msg                       # 提醒别写回源码
    assert env_util.load_env("MP_TEST_KEY") == ""   # 空值不被打印成 "None" 之类

    monkeypatch.setenv("MP_TEST_KEY", "present-value")
    assert env_util.require_env("MP_TEST_KEY") == "present-value"


# ---------------------------------------------------------------- 防再犯守卫

#: 扫描范围 = **随仓库发布的 Python 代码**：仓库根 `*.py`（各入口脚本）+ `src/` + `scripts/` + `web/`。
#: ⚠️ **刻意不含 `tests/`**：测试里的假凭据是合法的（如 `tests/test_web.py` 的鉴权夹具
#: `AUTH_PASS = "s3cret-pass-16"`），扫进去只会产生假红；而真实泄露面在运行代码里。
#: ⚠️ 也不递归整棵仓库树 —— 本机根目录同时存在 `venv/` 与 **`.venv/`**，递归会把第三方包
#: （akshare / curl_cffi 里到处是 `token = "..."`）全扫进来（初版就踩了：7 条假红）。
SCAN_ROOTS = (ROOT / "src", ROOT / "scripts", ROOT / "web")
SKIP_DIRS = {"venv", "__pycache__", "site-packages", "node_modules", "reports", "tests", "_dbg"}

#: 变量名（大小写不敏感；覆盖常见凭据命名）— 阈值 ≥8 位，避免误伤 `key = ""` / 占位符。
#: 覆盖三种真实写法：`VAR = "v"` / `VAR: str = "v"`（类型注解）/ `"VAR": "v"`（字典/JSON 形态）。
_NAME = (r"bot[_-]?id|secret|token|api[_-]?key|apikey|password|passwd|"
         r"access[_-]?key|secret[_-]?key|client[_-]?secret|app[_-]?secret")
CRED_ASSIGN = re.compile(
    r"""^\s*["']?(?P<var>%s)["']?\s*(?::\s*[^=:\n]{0,40})?\s*[:=]\s*["'](?P<val>[^"'\s]{8,})["']"""
    % _NAME, re.I)


def _iter_scanned_files() -> list[Path]:
    """仓库根 `*.py`（仅一层）+ `SCAN_ROOTS` 递归（跳过点开头目录与 `SKIP_DIRS`）。"""
    out = [p for p in ROOT.glob("*.py") if not p.name.startswith(".")]
    for root in SCAN_ROOTS:
        for p in root.rglob("*.py"):
            if any(part.startswith(".") or part in SKIP_DIRS
                   for part in p.relative_to(ROOT).parts):
                continue
            out.append(p)
    return sorted(set(out))


def _scan_hardcoded() -> tuple[list[str], int]:
    """返回 `(命中列表 [相对路径:行号:变量名], 扫描文件数)`。**命中项不含值**。"""
    hits: list[str] = []
    files = _iter_scanned_files()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(text.split("\n"), 1):
            m = CRED_ASSIGN.match(line)
            if m:
                hits.append("%s:%d:%s" % (path.relative_to(ROOT).as_posix(), i, m.group("var")))
    return hits, len(files)


def test_no_hardcoded_credentials_in_source():
    """🔴 防再犯守卫：运行代码里**不得再出现凭据字面量**（G1 的核心产出）。

    本用例是"下一次还会再写一次"的唯一拦截点。修法：把值挪到 `.env`，
    代码侧用 `src/env_util.require_env("KEY")` 读取。
    """
    hits, n_files = _scan_hardcoded()
    assert n_files >= 20, "扫描文件数异常少（%d）—— 守卫可能扫空了，空集不算过" % n_files
    assert not hits, (
        "发现硬编码凭据字面量（**只报位置，不报值**；请改为 src/env_util.require_env）：\n  "
        + "\n  ".join(hits)
    )


def test_guard_pattern_actually_matches(tmp_path):
    """守卫自检（**防空转**）：正则必须真的能命中一类硬编码写法，否则上面的绿是假绿。

    用**假值**验证（`fake-not-a-real-credential`），不引入任何真实凭据。
    """
    samples = [
        'BOT_ID = "fake-not-a-real-credential"',
        "SECRET = 'fake-not-a-real-credential'",
        'bot_id = "fake-not-a-real-credential"',
        'client_secret: str = "fake-not-a-real-credential"',
        'API_KEY = "fake-not-a-real-credential"',
    ]
    for s in samples:
        assert CRED_ASSIGN.match(s), "守卫正则漏掉了这种写法: %s" % s.split("=")[0].strip()
    # 反例：空值与短占位符不该命中（否则会误伤 `key = ""`）
    for s in ('BOT_ID = ""', 'SECRET = "todo"', 'token = "${ENV}"', "# BOT_ID = 'x'"):
        assert not CRED_ASSIGN.match(s), "守卫正则误伤: %r" % s
