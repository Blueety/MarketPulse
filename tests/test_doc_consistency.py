"""文档一致性护栏（BUG-013）：文档里写的 `/api/history` `days` 上限必须等于代码真值。

代码是唯一事实来源（`web.app.api_history` 的 `Query(30, ge=1, le=3650)`，D9 放宽）。文档曾长期
落后（`AGENTS.md` 写 365、`docs/commands.md` 写「366→422」），而 `AGENTS.md` 是 agent 上下文
文件 —— 漂移会持续误导后续实现，所以在这里钉成断言：**代码改了文档不跟就红**。

真值不硬编码，直接从签名里取：FastAPI 0.14x 把 `ge`/`le` 放进 `FieldInfo.metadata`
（`Le(le=3650)`），取不到时退化为硬编码 3650。
"""
import inspect
import re
from pathlib import Path

import web.app as web_app

ROOT = Path(__file__).resolve().parent.parent
#: 会写 days 上限/边界的文档：AGENTS.md（agent 上下文，优先）+ commands.md（命令手册）+
#: architecture.md（决策表里留了这条数值）。
DOCS = ("AGENTS.md", "docs/commands.md", "docs/architecture.md")
#: 签名取不到 `le` 时的退化真值（与 `web/app.py` 的 `Query(30, ge=1, le=3650)` 同步）。
FALLBACK_LIMIT = 3650


def _days_upper_bound():
    """`api_history` 的 `days` 上限（`Query(le=...)`）。"""
    param = inspect.signature(web_app.api_history).parameters.get("days")
    assert param is not None, "api_history 没有 days 参数 —— 签名变了，本测试需同步"
    limit = getattr(param.default, "le", None)
    if limit is None:  # pydantic v2：约束在 FieldInfo.metadata 的 Le 对象里
        for meta in getattr(param.default, "metadata", ()):
            if getattr(meta, "le", None) is not None:
                limit = meta.le
                break
    return limit if isinstance(limit, int) else FALLBACK_LIMIT


def test_documented_days_upper_bound_matches_code():
    limit = _days_upper_bound()
    for rel in DOCS:
        path = ROOT / rel
        assert path.is_file(), "文档 %s 不见了（本测试依赖它承载 days 上限）" % rel
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                 if "days" in ln or "/api/history" in ln]
        assert lines, "%s 里没有任何提到 days / /api/history 的行 —— 断言失去目标" % rel
        assert any(str(limit) in ln for ln in lines), (
            "%s 未写出 /api/history 的 days 上限真值 %d（以代码为准）；相关行：%s"
            % (rel, limit, " ｜ ".join(ln[:160] for ln in lines)))
    # 显式写法「`days` 上限 **N**」的每一条都必须等于真值（防再次写成旧上限）
    for rel in ("AGENTS.md", "docs/architecture.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for claimed in re.findall(r"`days`\s*上限\s*\*\*(\d+)\*\*", text):
            assert int(claimed) == limit, \
                "%s 声明 days 上限 %s，代码真值 %d" % (rel, claimed, limit)
