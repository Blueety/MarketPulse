"""测试隔离（设计 B）。

collection 前（本模块导入时）强制 CONFIG_PATH 指向不存在文件，使全量测试恒用
内置默认值运行——避免用户定制过的 config.json 在 analyzer/reporter import 时被
快照读入，破坏 classify 边界值 / 90 天滚动 / 30 天窗口等默认断言。
"""
import os
from pathlib import Path

os.environ["CONFIG_PATH"] = str(Path(__file__).parent / "_nonexistent_config.json")
