"""数据目录自动提交推送（script 模式 cron 的入口，2026-09-20）。

任务档：`tasks/2026-09-20-autopush-pathspec-fix/`（方案 A）。

**为什么有它**：原来这条 cron 是 **prompt 模式** —— "只提交 data/context/alerts" 这条约束
写在提示词里，靠 LLM 每次照做。2026-09-20 的实测教训是：约束写在 prompt 里**没有机器强制**
（当时的洞不在 `git add`，而在 `git commit` 不带 pathspec 会提交整个暂存区）。
改成 **script 模式**后，范围由**代码**强制，无 token 成本、失败可见。

**复用而非重写**：白名单与提交逻辑**全部**走 `src/git_ops`（单一事实来源）：
- `_has_changes()` → 判断白名单路径内有没有改动（与提交同口径）
- `auto_commit_push()` → commit + push（含 Clash 代理注入、`gh` 凭据助手兜底、
  `GIT_TERMINAL_PROMPT=0` 防挂死、失败不抛异常等既有纪律）

⚠️ **本脚本刻意调用 `auto_commit_push` 而不是只调 `_commit`**：plan 的伪代码只写了 `_commit`，
但这条 cron 的存在意义就是"把数据推到线上"（原 prompt 里有 `git push origin master`）——
只提交不推送会让 Railway 拿不到新数据，是**功能回退**。
`auto_commit_push` 一次覆盖 commit + push 两件事，且自带既有的凭据/代理处理。

**退出码**：0 = 成功（含"无改动，跳过"）；1 = 提交或推送失败（供 Hermes 识别）。

用法（仓库根执行）：
    venv/Scripts/python -m scripts.auto_commit_data

仓库外 cron 的 wrapper：`$HERMES_HOME/scripts/marketpulse_autopush.sh`
（本机 = `D:\\hermes\\scripts\\`，**不是** `~/.hermes/scripts` —— 后者在本机不会被解析到）。
"""

from __future__ import annotations

import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import git_ops  # noqa: E402

#: 提交消息里的动作名（**ASCII**：规避 Windows cp936 乱码，同 F5 纪律）。
#: 最终消息形如 `auto: 2026-09-20 data sync`（与三入口的 `auto: {date} {type}` 同格式）。
REPORT_TYPE = "data sync"


def main() -> int:
    """无参数：白名单内有改动就 commit + push，无改动就跳过。"""
    root = Path(__file__).resolve().parents[1]
    # 先单独判一次"有没有改动"：`auto_commit_push` 的返回值把"无改动"和"失败"都编码成 False，
    # 分不清就没法给 cron 一个有意义的退出码（这里要区分"跳过"与"失败"）。
    if not git_ops._has_changes(root):
        print("[data-commit] 改动=无，跳过（幂等）")
        return 0
    ok = git_ops.auto_commit_push(_date.today().isoformat(), REPORT_TYPE, root=root)
    print("[data-commit] 改动=有，" + ("提交并推送=ok" if ok else "提交/推送=失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
