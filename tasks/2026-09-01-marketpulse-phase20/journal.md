# MarketPulse 二十期 实施日志

## 目标
Web 看板视觉升级：首页从「普通 SaaS / Admin Dashboard」升级为现代、专业、紧凑的金融市场终端（Bloomberg / TradingView 的信息密度 + Apple 的克制层级）。仅改 `web/static/style.css` 与 `web/templates/index.html`；`app.py` / `src` / `tests` 零改动；涨跌色体系不动；无构建步骤、无新依赖、Railway 兼容。

## 改动文件清单
1. `web/static/style.css`（全量重写，339 → 约 370 行）
   - `:root` 变量：`--bg-primary #0d1117→#0b0e14`、`--border #2a3038→#1f252d`、新增 `--mono` 等宽字体栈与 `--fs-num/--fs-num-sm` token；`--bg-card` 不再用于卡片（仅 hover 复用为 `--bg-hover`）。
   - `body` 启用 `font-variant-numeric: tabular-nums`。
   - `topbar` 收窄（padding 16→10px、标题 20→18px、日期等宽次级色）。
   - 卡片→分区：`.card` 去背景/边框/圆角，改 `padding: 18px 0` + `border-bottom` hairline（末节无）。
   - 概览表：`td` padding 收敛、`td.num` 等宽数字、value 18px/600、change 14px/600、指数名 13px；表头 11px uppercase。
   - 状态圆点 `.status-dot` + `.dot-gray/orange/red/green`（D5 决策）。
   - 图表区：`.chart-box` 去边框背景透明、`canvas` 220px（移动 200/180）。
   - 告警：`.alert-card` 仅左 3px 色条 + 紧凑行式、`badge` 10px。
   - 响应式 768/480 两档；≤480 隐藏 `.col-status` 与 `.col-turnover` 防溢出。
2. `web/templates/index.html`（约 +25/-15 行）
   - 4 个 section 标题加 `.h2-sub` 次级副文本（市场概览/板块/告警）；趋势标题保留。
   - 概览状态列 `th/td` 加 `.col-status`；板块成交额 `th/td` 加 `.col-turnover`（供移动端隐藏）。
   - `renderOverview`：数值单元格加 `num/val/chg` class（等宽数字 + 字号阶梯），状态单元格加 `.status-dot` 并按关键词归类（休市灰 / 失败橙 / 异动红 / 其余绿）；删除原 `section.style.display = "";` 这一预存 `ReferenceError` bug（未定义全局 `section` 会让概览永远停在「加载中」）。
   - `renderSector`：成交额 `td` 加 `.col-turnover`。
   - 其余 JS（状态机 / 筛选 / 排序 / 图表渲染 / CDN 降级）一字未动；`renderAlerts` 结构沿用 `.alert-card .alert/.warn` 契约，仅 CSS 紧凑化。

## 验证结果
- `pytest tests/ -q`：**324 passed**（含 `test_web.py` 31 passed，`app.py`/`tests` 零改动契约不破）。
- 浏览器驱动实测（uvicorn 8002，真实 `data/history.json` + `context/`）：
  - 桌面 1440×900：`scrollWidth == innerWidth`（无横向溢出）；概览 10 行、4 图（CDN 正常）、板块 5 行、告警占位「暂无告警记录」；hero 值 18px、涨跌幅 14px；卡片背景透明（`rgba(0,0,0,0)`）；状态圆点存在（默认绿）；`.h2-sub` 生效。
  - 交互回归：排序表头三态（15.25 ↔ 78213.35 顺序变化）、chip 取消选中 10→9→恢复 10、类别按钮隔离→2 行→全选恢复 10、7/30/90 天切换图表仍 4 个且无报错。
  - 移动 375×812：无横向溢出；`.col-status` 与 `.col-turnover` 均 `display:none`；10 行 / 4 图。
  - 移动 320×720：无横向溢出；10 行 / 4 图。
- 降级路径未做破坏性实测（避免清空真实 `history.json`/`context`）：空态代码路径（暂无数据 / 数据暂缺 / 暂无告警记录）为既有逻辑、本次未改动，已通过「告警空目录→暂无告警记录」间接验证。

## 遇到的问题
1. **同文件多 PUT 行号错位**：想把 `renderSector` 的 turnover `<td>` 改为带 `.col-turnover`，PUT 用了 155-215 窗口里的行号 204，实际全量 read 中该行位于 211，导致错误地把一行 `<td class="col-turnover">…` 插入到 `renderAlerts` 内部（`renderSector` 的 turnover 反而未改）。已用 grep 取真实行号后 CUT 游离行 + PUT 修正 `renderSector`，回归通过。
2. **编辑工具误写错文件**：计划给 `docs/pitfalls.md` 追加坑点，却把内容写进了 `web/static/style.css`（错误锚点），使 `.chart-box canvas` 的 width/height 之间插入 6 行文档文本，CSS 语法损坏。已用整体 `write` 重写 `style.css` 复原，并经浏览器确认 served CSS 不再含该文本（`cssHasCorruption=false`）。
3. **自动化提交扫入错误版本**：上述两处失误发生时，项目内「每日数据更新」cron 以 `git add -A` 把未提交改动（含损坏的 `style.css`）一并提交，导致 HEAD 一度包含损坏版；最终修正后的工作区 `style.css` 与 HEAD 的差异正好是那 6 行注入文本（`git diff HEAD` 显示 6 deletions），修正已落盘、待下次 cron 提交。
4. **端口/缓存**：8000 被既有看板进程占用，且 FastAPI 在启动时缓存 `index.html`，旧进程不反映模板改动；验证改用 8001/8002 未缓存端口。

## 下次注意什么
- 同文件多个定点编辑，必须用 grep 逐个取真实行号，或优先整体 `write` 重写；不要凭不同 read 窗口的偏移估算。
- edit 写入前再次核对 `[path#TAG]` 是否为目标文件——错文件会污染无关资源（本次污染 `style.css`）。
- 验证模板/静态改动要起未缓存端口或硬刷新，旧进程会掩盖改动。
- 注意自动化 cron 会用 `git add -A` 扫入未提交改动；若编辑期间失误被提交，需在工作区修正后由下一轮 cron 提交，`git diff HEAD` 即可确认修正量。
- 重写函数时顺手修掉预存的 `section.style.display` 这类未定义引用 bug。

## 后续工作
- 无阻塞项。两处失误均已修复并实测通过。
- 待提交：`web/static/style.css`（修正版）、`docs/pitfalls.md`（新增二十期坑点），将由下次「每日数据更新」cron 一并提交（与本项目既有自动提交纪律一致）。
