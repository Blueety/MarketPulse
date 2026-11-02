# MarketPulse 十九期诊断 Journal — 概览表格隐藏不生效

> 日期：2026-08-31

## 目标

诊断 Web 看板「取消所有指标选中时概览 section 未隐藏」的问题根因，输出 `diagnosis.md`。

## 结论

**当前代码无 bug，隐藏逻辑正常；根因是浏览器缓存旧版页面**（2026-08-31 18:15 前、无隐藏逻辑的版本，rows 为空时显示「无选中指标」行而非隐藏）。

## 证据

- git 时间线：`881bc09`（18:15 加隐藏逻辑）→ `a3e1017`（18:35 选择器改 closest）。18:15 前版本行为 = 用户报告现象。
- 运行中服务（PID 38584，18:35:10 启动）实测：清空按钮与逐个取消 chip 两条路径，最终 `section.style.display` 均为 `none`，隐藏生效。
- 服务响应无 `Cache-Control` 头（curl 确认），浏览器启发式缓存可命中旧 HTML。
- Jinja2 `auto_reload` 未关闭，服务端模板跟随文件变化，服务端无问题。

## 改动文件清单

- `tasks/2026-09-01-marketpulse-phase19/diagnosis.md`（新增，诊断报告）。**源码零改动**，工作区保持干净。

## 验证结果

- 浏览器驱动（headless Chromium）对运行中服务实测：初始 10 行 → 清空 → `display: none`；逐个取消 10 chip → 行数 9→0，末次 `display: none`。逐项通过。
- `tests/test_web.py` 存在且 `test_index_html` 仅断言 status/content-type，无响应头断言——诊断报告中建议的 `Cache-Control: no-cache` 修复不影响既有测试。

## 下次注意

- 用户报告「代码不生效」类问题时，先确认其浏览器是否硬刷新过——本项目 Web 页面无缓存控制头，旧版页面会残留。
- 若实施 no-cache 修复，改动仅在 `web/app.py` 的 `/` 端点（约 3 行），`web/templates/index.html` 与 `web/static/style.css` 不动。
- 881bc09 的旧选择器 `document.querySelector(".card")` 碰巧有效（首个 .card 即概览 section）；a3e1017 已改 closest 防模块顺序调整，勿回退。
