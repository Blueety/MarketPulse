# 十四期执行日志 — 日报图片化推送

## 目标
将 Markdown 日报 + 趋势图转为 600px PNG，经 QQ 推送图片；渲染失败不影响日报（决策 E 容错）。

## 改动文件清单
- 新增 `src/image_renderer.py`：md 解析（日期 / 4 类指数卡片 / 趋势图引用 / AI 解读章节）→ Jinja2 模板 → imgkit/wkhtmltoimage 转 PNG；告警附录块解析；全链路容错，失败返回 None。
- 新增 `web/templates/report_card.html`：深色专业主题卡片模板（移动端 600px 竖图，系统无衬线中文字体栈，趋势图以 `file://` 绝对路径引用）。
- 新增 `scripts/render_report_image.py`：独立重渲染入口（`--date`），供 Hermes 追加 AI 解读章节后重渲染含解读图。
- 新增 `tests/test_phase14.py`：17 条单元测试（解析 / 渲染 / 尺寸守卫 / 容错 / 接线），全绿。
- 改 `src/analyzer.py`：新增 `IMAGES_DIR` 路径常量（顺带恢复此前误删的 `SNAPSHOTS_DIR`）。
- 改 `daily_report.py`：导入 `render_report_image`，末尾以 try/except 容错调用（失败仅记日志、退出码恒 0）。
- 改 `requirements.txt`：+`imgkit>=1.2.3`。
- 改 `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` / `AGENTS.md`：同步模块表、数据流、关键决策、命令、易错点、项目地图。

## 验证结果
- `pytest tests/test_phase14.py -v`：17 passed。
- 全量 `pytest tests/`：267 passed / 14 failed。基线（stash 我的改动）同为 14 failed / 250 passed ⇒ 14 个失败为仓库既存问题（test_alerter 2 / test_config 2 / test_phase6a 1 / test_phase6b 3 / test_web 6），与图片化无关，零回归。
- 降级冒烟：构造最小报告 + 假图，调用 `render_report_image` 在无 wkhtmltoimage 时返回 None、不抛、不影响日报（决策 E 验证通过）。
- imgkit 已 `pip install`（1.2.3）。

## 遇到的问题
1. **wkhtmltopdf 无法在本环境安装**：winget 安装 `wkhtmltopdf` 多次超时（900s），静默安装报 “请求的操作需要提升”(740)——当前 shell 非管理员、无交互 UAC，NSIS 安装器强制提权；7-Zip 不可用、无法解包安装器。结论：真实 PNG 渲染需在有管理员权限 / 已预装 wkhtmltoimage 的部署主机（Hermes 侧）完成；本仓库代码路径正确且已优雅降级。
2. **edit 工具对 commands.md 标签失效**：本会话中 `edit` 对该文件持续报 “No hashline”，改用 bash+Python 精确插入绕过；其余文档 edit/bash 正常。
3. **解析严格依赖 render_report 结构**：image_renderer 正则耦合日报 md 标题 / 表头 / 趋势图引用 / 解读章节命名，已在 pitfalls 记录；改报告渲染须同步回归。

## 下次注意
- 部署到 Hermes 主机时确认 `wkhtmltoimage` 在 PATH（或写绝对路径）；图片生成后建议实际预览一次，确认中文字体 / 宽度 / ≤800KB。
- 改 `render_report` 输出结构须同步 `src/image_renderer.py` 与 `tests/test_phase14.py`。
- 告警仅取 `alerts/{date}-close.md`（决策 E），盘中快照告警不进图片。
- 本环境非管理员，涉及系统级安装（winget / NSIS）的任务须提前确认提权方式，否则在部署侧完成验证。
