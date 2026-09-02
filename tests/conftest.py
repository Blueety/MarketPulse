"""测试隔离（设计 B）。

collection 前（本模块导入时）强制 CONFIG_PATH 指向不存在文件，使全量测试恒用
内置默认值运行——避免用户定制过的 config.json 在 analyzer/reporter import 时被
快照读入，破坏 classify 边界值 / 90 天滚动 / 30 天窗口等默认断言。
"""
import os
from pathlib import Path

os.environ["CONFIG_PATH"] = str(Path(__file__).parent / "_nonexistent_config.json")

# 二十六期护栏：强制关闭自动推送，防止 test_phase25 等真实调用 daily_report.main()
# 触发的 auto_commit_push 误推 GitHub（AUTO_PUSH=0 → git_ops 直接返回 False，零子进程）。
os.environ["AUTO_PUSH"] = "0"
