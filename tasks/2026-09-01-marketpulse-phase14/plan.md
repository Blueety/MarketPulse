# MarketPulse 十四期：日报图片化推送 — 实施计划

> 架构师只读分析产出。目标、涉及文件、核心设计、实施步骤、验证命令、风险与待确认决策。
> 分析基线：`daily_report.py`（流程末尾 generate_context 后收尾，退出码恒 0）、`src/reporter.py`（render_report 章节结构：日期行 + 4 张指数表（美股大盘/A股大盘/波动率/另类资产）+ 趋势图章节 + 脚注；图表相对路径 `./charts/xxx.png`）、`src/analyzer.py`（REPORTS_DIR/CHARTS_DIR/ALERTS_DIR 路径常量单一事实来源）、`src/alerter.py`（告警附录块格式：frontmatter + 标题 + 字段）、环境实测（jinja2 3.1.6 已装；**imgkit 未装、wkhtmltopdf 不在 PATH**，PIL 12.3.0 随 matplotlib 间接存在）。

## 目标

- 新增 `src/image_renderer.py`：解析日报 md → 结构化数据 → Jinja2 模板渲染 HTML → imgkit/wkhtmltopdf 转 PNG。
- 新增 `web/templates/report_card.html`：手机竖屏长图模板（头部标题+日期 / 核心指数卡片区 2 列网格 / 趋势图区 / AI 解读区 / 告警区 / 脚注数据来源）。
- `daily_report.py` 流程末尾调用渲染，生成 `reports/images/YYYY-MM-DD.png`；渲染失败仅记日志，不中断日报、退出码恒 0。
- 新增 `scripts/render_report_image.py --date` 独立重渲染入口：Hermes 追加 AI 解读到 md 后重新渲染含解读的图片再推送（Hermes 推送的是图片，脚本不含推送逻辑）。
- 约束落地：宽 600px、高度自适应、PNG ≤800KB、渲染 ≤15s、中文字体（PingFang SC / Microsoft YaHei）、趋势图缺失显示「暂缺」、保留 .md 推送用 .png。

## 涉及文件

| 文件 | 改动类型 |
|---|---|
| `src/image_renderer.py` | 新增：md 解析 / 告警解析 / HTML 渲染 / imgkit 接线（超时 + 容错 + 尺寸守卫） |
| `web/templates/report_card.html` | 新增：图片长图模板（内联 CSS，自包含） |
| `scripts/render_report_image.py` | 新增：独立重渲染入口（Hermes 追加解读后调用，backtest.py 同款最小入口模式） |
| `src/analyzer.py` | 修改：+`IMAGES_DIR` 路径常量（路径单一事实来源纪律） |
| `daily_report.py` | 修改：末尾 try/except 调用 `render_report_image(date)`（决策 E 模式） |
| `requirements.txt` | 修改：+`imgkit`（PRD 已确认技术栈；wkhtmltopdf 为系统工具不入 pip） |
| `tests/test_phase14.py` | 新增：解析/模板/接线/容错测试（全 mock imgkit，不依赖 wkhtmltopdf） |
| `AGENTS.md` / `docs/architecture.md` / `docs/commands.md` / `docs/pitfalls.md` | 文档同步 |

不改：`snapshot_report.py`（快照不图片化）、`src/reporter.py`、`src/fetcher.py`、`src/config.py`、`src/alerter.py`、`config.json`（图片参数为 PRD 固定值，常量化不配置化）、`web/app.py`（仅模板目录新增文件）、`.env`、`data/`、`alerts/`、`context/`。

## 环境前提（本机实测未就绪，步骤 1 先行）

- `venv/Scripts/pip install -r requirements.txt`（新增 imgkit）。
- 安装 wkhtmltopdf 系统工具（`winget install wkhtmltopdf` 或官网安装包，安装后确保加入 PATH；0.12.6+ 默认禁止本地文件访问，渲染需 `--enable-local-file-access`）。验证：`wkhtmltopdf --version`。

## 核心设计

### 1. 数据流与触发时机

```text
daily_report.py 末尾（generate_context 之后、return 0 之前）
  └─> render_report_image(date)
        ├─> 读 reports/YYYY-MM-DD.md（解析 4 张指数表 / 趋势图引用 / 解读章节）
        ├─> 读 alerts/YYYY-MM-DD-close.md（收盘告警，可选）
        ├─> Jinja2 渲染 report_card.html（内联 CSS）
        └─> imgkit → reports/images/YYYY-MM-DD.png（宽 600 自动高，≤15s，≤800KB）
        失败/超时/缺 md → 仅 log.warning，退出码恒 0

Hermes 追加 AI 解读（## 🤖 AI 解读 章节）到 md 后：
  venv/Scripts/python scripts/render_report_image.py --date YYYY-MM-DD
  └─> 复用同一 render_report_image → 含解读区的新图 → Hermes 推 QQ 图片
```

关键点：`daily_report.py` 调用在告警检查之后（`alerts/` 文件已生成，基础图含告警区）；AI 解读区数据源 = md 中的解读章节（Hermes 追加，交付配置非仓库文件，解析容错：标题含「解读」即识别），基础图无解读章节时该区省略，最终推送图由重渲染脚本产出——满足 PRD 图片结构第 4 条。

### 2. src/image_renderer.py 模块（约 200 行）

常量（模块级，测试可断言）：

```python
IMAGE_WIDTH = 600                # PRD 固定宽度（px）
MAX_IMAGE_BYTES = 800 * 1024     # PRD 文件上限
RENDER_TIMEOUT = 15              # imgkit 渲染限时（秒），超时跳过
RETRY_ZOOM = 0.8                 # 尺寸超标降级重试缩放
```

函数：

- `parse_report(md_text: str, md_path: Path) -> dict`：纯函数。提取 `date`（`**日期**：…`行）、`cards`（4 张指数表行 → `{label, value, change, trend_or_status, sign}`，sign 由 change 首字符 +/− 判定）、`charts`（正则 `!\[[^\]]*\]\(([^)]+)\)` 提取引用 → 相对路径基于 `md_path.parent` 解析 → 存在性检查，缺失标 `missing=True`）、`interpretation`（`## ` 标题含「解读」的章节正文，无则 `None`）。坏 md（缺日期/无表）不抛异常，返回可渲染的降级结构。
- `parse_alerts(date: str) -> list[dict]`：读 `alerts/{date}-close.md` 附录块（按 `---` frontmatter 分块），提取 `symbol / level / change / threshold / state / suggestion`；文件缺失 → `[]`，坏文件 → `[]` 记日志。
- `render_html(data: dict) -> str`：Jinja2（`FileSystemLoader(BASE_DIR/"web"/"templates")`）渲染 `report_card.html`。
- `_run_with_timeout(fn, timeout)`：daemon 线程 `join(15)`，与 reporter 图表限时同一模式（Windows 无 SIGALRM）。
- `render_report_image(date: str) -> Path | None`：编排。md 缺失 → `None`；`imgkit` 导入失败（未安装）或 wkhtmltopdf 不可用 → 记日志 `None`；渲染超时 → `None`；成功 → 写 `reports/images/{date}.png` 并校验（见 4）。
- `_png_dimensions(path) -> tuple[int, int]`：纯 Python 读 PNG IHDR（struct），不依赖 PIL。

### 3. web/templates/report_card.html（约 140 行）

- 内联 `<style>` 自包含（imgkit 单文件渲染最稳，不引外部 CSS/JS）。
- 字体栈 `font-family: "PingFang SC", "Microsoft YaHei", sans-serif;`（Windows 走 YaHei）。
- 配色沿用看板主题（`web/static/style.css` 既有约定）：涨 `#1a9e6c`、跌 `#e5484d`、中性灰；背景深色卡片风格。
- 结构（自上而下）：头部（标题「MarketPulse 全市场情绪日报」+ 日期）→ 核心指数卡片区（`grid-template-columns: repeat(2, 1fr)`，10 个标的按 md 顺序：美股/A股/波动率/另类，卡片 = 名称 + 数值 + 涨跌幅着色）→ 趋势图区（每图全宽 `<img>`，缺失 → 「📉 趋势图暂缺」占位块）→ AI 解读区（`interpretation` 非空才渲染）→ 告警区（每条告警一张卡：级别徽标 + 指数 + 变化率 + 建议；空则省略整区）→ 脚注（「数据来源：Yahoo Finance」）。

### 4. imgkit 接线与约束落地

- options：`{"width": "600", "disable-smart-width": None, "enable-local-file-access": None, "encoding": "UTF-8", "format": "png"}`；`disable-smart-width` + 显式宽度 → 页高随内容自适应（长图）。
- 图表以 `file://` 绝对路径引用（经 base_url 解析），不 base64 内嵌（避免 +33% 膨胀）。
- 尺寸守卫：渲染后 `Path.stat().st_size` > 800KB → `zoom=0.8` 重试一次；仍超标 → 保留文件 + `log.warning`（不崩溃）。实测确认典型尺寸，若普遍超标再议（决策 C）。
- 超时：imgkit 调用包 daemon 线程 `join(15)`，超时跳过图片不中断日报。

### 5. daily_report.py 接线

generate_context 块之后追加（约 6 行）：

```python
try:  # 十四期：图片化推送（决策 E 模式）：失败仅记日志，不影响日报/退出码
    image_path = render_report_image(date)
    if image_path:
        log.info("日报图片已生成: %s", image_path)
except Exception as exc:
    log.warning("日报图片渲染失败，不影响日报: %s", exc)
```

### 6. scripts/render_report_image.py（约 40 行）

- `argparse --date YYYY-MM-DD`（默认今日美东日期）；复用 `src.image_renderer.render_report_image`；输出路径 + 文件大小日志；缺 md → 提示后退出码 0。`sys.path` 插入项目根（backtest.py 同款）。

### 7. 测试 tests/test_phase14.py（约 12 条，全 mock imgkit）

1. `parse_report`：日期/卡片数量（10）与字段/涨跌幅符号判定（+/−/中性）；
2. `parse_report`：图表引用解析（相对路径正确解析到 reports/charts/）、缺失文件 → `missing=True`；
3. `parse_report`：解读章节存在（`## 🤖 AI 解读`）与缺失两种；坏 md（空/无日期）不抛且降级；
4. `parse_alerts`：无文件 → `[]`；单块/多块字段解析正确；坏文件 → `[]` 不崩；
5. `render_html`：卡片数、涨跌颜色 class、暂缺占位、告警区/解读区有无条件渲染；
6. `render_report_image` 集成：monkeypatch `imgkit.from_string`（成功写假 PNG）→ 返回路径；抛异常 → `None` 不抛；
7. `render_report_image`：imgkit 导入失败路径（monkeypatch import）→ `None`；
8. 超时路径：mock imgkit 阻塞 → `_run_with_timeout` join 超时 → `None`；
9. 尺寸守卫：mock PNG 文件 >800KB → 触发 zoom 重试判定逻辑（纯函数断言）；
10. `_png_dimensions`：构造最小合法 PNG 头断言宽高；
11. 入口：`daily_report.py` 渲染失败退出码仍 0（monkeypatch render_report_image 抛异常，调 main）；
12. `render_report_image.py --date`：缺 md 优雅退出码 0（subprocess 或直接调入口函数）。

## 实施步骤

1. **环境准备**：requirements.txt +`imgkit`，`pip install -r requirements.txt`；安装 wkhtmltopdf；验证 `wkhtmltopdf --version`。
2. **解析层**：analyzer.py +`IMAGES_DIR`；`src/image_renderer.py` 的 `parse_report` / `parse_alerts` / `_png_dimensions` 纯函数 + 测试 1-4、10。
3. **模板层**：`web/templates/report_card.html` + `render_html` + 测试 5。
4. **接线层**：`_run_with_timeout` + `render_report_image`（imgkit 调用、超时、容错、尺寸守卫）+ 测试 6-9。
5. **入口**：`daily_report.py` 末尾调用 + `scripts/render_report_image.py` + 测试 11-12。
6. **实跑验证**：`daily_report.py` 实跑 → `reports/images/YYYY-MM-DD.png` 生成；纯 Python 读 IHDR 断言宽 600；`stat` 断言 ≤800KB；内容核对（卡片/趋势图/告警区/脚注）；手工给 md 追加 `## 🤖 AI 解读` 章节后跑重渲染脚本 → 新图含解读区。验证后恢复 md 原状。
7. **回归 + 文档**：`venv/Scripts/python -m pytest tests/ -v` 全量；同步 architecture.md（模块表 + 数据流 + 关键决策）、commands.md（新命令 + 环境前提）、pitfalls.md（图片渲染纪律：mock imgkit、图表 file:// 引用、md 章节解析依赖 reporter 模板、渲染失败不中断主流程）、AGENTS.md（project map）。

## 验证命令

1. `venv/Scripts/wkhtmltopdf --version` — wkhtmltopdf 就绪。
2. `venv/Scripts/python -m pytest tests/test_phase14.py -v` — 新增全绿（不依赖 wkhtmltopdf）。
3. `venv/Scripts/python -m pytest tests/ -v` — 既有全量不回归 + 新增（既有约 231 条）。
4. `venv/Scripts/python daily_report.py` — `reports/images/YYYY-MM-DD.png` 生成；IHDR 宽 600、≤800KB、内容完整（卡片/趋势图/脚注；无告警则无告警区；缺图表有「暂缺」）。
5. `venv/Scripts/python scripts/render_report_image.py --date YYYY-MM-DD` — 重渲染含解读区图片（先手工追加解读章节）。
6. 容错：删 md / 卸载 imgkit（或 mock）跑两入口 — 仅记日志、退出码 0、日报主流程不受影响。

## 待确认决策

- **A（默认采纳）**：AI 解读区数据源 = 日报 md 中标题含「解读」的章节；Hermes 追加后经重渲染脚本产出最终图片。备选：渲染器增加独立 `interpretation` 参数接口（Hermes 侧需额外契约，且基础图仍无解读）。
- **B（默认采纳）**：新增 `scripts/render_report_image.py` 重渲染入口。备选：不加入口，Hermes 推基础图 + 文字解读分离 —— 违反 PRD 图片结构第 4 条（AI 解读区在图中）。
- **C（默认采纳）**：≤800KB 用 zoom 0.8 重试一次实现，不显式新增 pillow 依赖（PIL 随 matplotlib 间接存在但不依赖）；实测普遍超标再议显式降采样。备选：requirements.txt 显式 +`pillow` 做后处理降采样。
- **D（默认采纳）**：涨跌配色沿用看板既有约定（绿涨红跌，全市场统一）。备选：A 股红涨绿跌 / 美股绿涨红跌双标准（需在模板分市场着色，复杂度上升）。
- **E（默认采纳）**：告警区仅取 `alerts/YYYY-MM-DD-close.md`（日报收盘告警）；盘中快照告警不入日报图片。
- **F（默认采纳）**：核心指数卡片区含全部 10 个标的（顺序同 md：美股/A股/波动率/另类）。备选：仅波动率 3 项（解读「核心指数」字面义，但手机读图信息量不足）。

## 风险与边界

- **wkhtmltopdf 环境缺失**：本机未装，步骤 1 前置；所有测试 mock imgkit，CI/测试不依赖真实二进制。
- **渲染超时**：daemon 线程 join(15) 兜底；wkhtmltopdf 子进程可能残留，可接受（与图表限时同一模式）。
- **尺寸超标**：zoom 重试 + 步骤 6 实测；若典型 >800KB 触发决策 C 备选。
- **md 结构漂移**：parse 依赖 reporter.py 固定模板（章节标题/表格格式），测试锁定格式；reporter 改模板需同步 test_phase14。
- **本地文件访问**：wkhtmltopdf 0.12.6+ 默认禁止读本地文件，必须 `enable-local-file-access`，否则图表全挂 → 容错显示「暂缺」（验证命令 4 覆盖）。
- **解读章节契约**：识别规则 = 标题含「解读」；Hermes Prompt（交付配置）需按此追加章节，docs/commands.md 写明契约。
- **imgkit 维护状态**：imgkit 包较旧但纯 Python 兼容 3.14；若渲染行为异常，退化路径 = 保留 md 推送（现状），图片失败不影响日报。

## PRD Done When 对照

- src/image_renderer.py 实现 → 核心设计 2 + 步骤 2/4
- web/templates/report_card.html 模板 → 核心设计 3 + 步骤 3
- daily_report.py 调用渲染 → 核心设计 5 + 步骤 5
- reports/images/ 生成图片 → 核心设计 1/4 + 步骤 6
- QQ 收到图片 → 核心设计 1（Hermes 侧：重渲染脚本 + 推送，交付配置）+ 决策 B
- 图片手机可读 → 核心设计 3/4（宽 600 自动高、2 列卡片、字体）+ 步骤 6 实跑检查
- pytest 全绿 → 步骤 7（新增 12 条 + 既有 231 条不回归）
