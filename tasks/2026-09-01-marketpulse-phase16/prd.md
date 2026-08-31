# Task Handoff：MarketPulse 第十六期 — 修复 19 个失败测试

> 复制到 `tasks/2026-09-01-marketpulse-phase16/prd.md`


## Goal

修复项目中 19 个失败的测试用例,恢复测试全绿。


## 失败分类

### 1. 阈值变更未同步（6 个）
- tests/test_alerter.py::test_defaults
- tests/test_alerter.py::test_nonpositive_env_falls_back
- tests/test_config.py::test_defaults_match_hardcoded
- tests/test_config.py::test_hermetic_defaults
- tests/test_phase6a.py::test_config_defaults_phase6a
- tests/test_phase6b.py::test_sh_triggers
- tests/test_phase6b.py::test_sh_exact_not_trigger
- tests/test_phase6b.py::test_sz_independent_threshold

**原因**:三期改了 src/config.py 的告警阈值,但测试还在用旧值断言


### 2. Web API history payload 问题（6 个）
- tests/test_web.py::test_api_history
- tests/test_web.py::test_build_history_payload_normalized_base100
- tests/test_web.py::test_build_history_payload_null_preserved
- tests/test_web.py::test_build_history_payload_zero_base
- tests/test_web.py::test_build_history_payload_single_value
- tests/test_web.py::test_build_history_payload_change_7d_last_non_null

**原因**:web/app.py 的 _build_history_payload 归一化逻辑有边界问题


### 3. Phase14 playwright mock 不完整（3 个）
- tests/test_phase14.py::test_render_report_image_no_playwright
- tests/test_phase14.py::test_render_report_image_timeout
- tests/test_phase14.py::test_render_report_image_size_guard

**原因**:十四期改用 playwright 替代 imgkit,测试 mock 不完整


### 4. Phase15 新测试问题（4 个）
- tests/test_phase15.py::TestLoadOpeningRefs::test_both_present
- tests/test_phase15.py::TestLoadOpeningRefs::test_missing_returns_empty
- tests/test_phase15.py 的其他失败

**原因**:十五期新测试有语法/逻辑错误


## 修复原则

1. **最小改动**:只修复测试断言,不改业务逻辑(除非是 bug)
2. **阈值同步**:读取 src/config.py 的 DEFAULTS["alert"] 确保测试用对的值
3. **Web API**:修复归一化边界问题(零值、单值、null)
4. **Mock 完善**:确保 playwright mock 覆盖所有调用路径
5. **测试独立**:每个测试独立运行,不依赖其他测试的状态


## Context Pointers

### 需修改的文件
| 文件 | 修改内容 |
|------|---------|
| tests/test_alerter.py | 更新阈值断言值 |
| tests/test_config.py | 更新阈值断言值 |
| tests/test_phase6a.py | 更新阈值断言值 |
| tests/test_phase6b.py | 更新阈值断言值 |
| tests/test_web.py | 修复 history payload 测试 |
| tests/test_phase14.py | 完善 playwright mock |
| tests/test_phase15.py | 修复新测试 |

### 需读取的文件
| 文件 | 用途 |
|------|------|
| src/config.py | 获取当前阈值 DEFAULTS["alert"] |
| src/image_renderer.py | 理解 playwright 调用方式 |
| opening_analyzer.py | 理解 Phase15 函数签名 |
| web/app.py | 理解 _build_history_payload 逻辑 |


## Constraints

- 不修改 src/ 下的业务逻辑代码
- 修复后的测试必须独立运行通过
- pytest tests/ -q 最终结果:0 failed, N passed


## Done When

- [ ] pytest tests/ -q 显示 0 failed
- [ ] 所有测试独立运行通过
- [ ] 无语法错误
