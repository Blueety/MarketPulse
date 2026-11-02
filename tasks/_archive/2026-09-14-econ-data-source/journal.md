# 执行记录：经济数据源接入 —— BLS 官方 API

- **日期**：2026-09-14
- **计划**：`tasks/2026-09-14-econ-data-source/plan.md`
- **定位**：`tasks/2026-09-14-macro-page/plan.md` 的**前置依赖**（宏观页模块 6「历史宏观环境」四象限 + 模块 7「经济数据」）
- **结论**：BLS 接入完成，**一次 POST 拿 4 序列**，`/api/econ` 上线（6h TTL / 只缓存成功 / 零写盘）。**执行中发现并修掉了 plan 算法里的一个会静默算错的缺陷**（见 §3）。

---

## 1. 改动清单

| 文件 | 改动 |
|---|---|
| `src/econ_fetcher.py` | **新建**（约 230 行）：`ECON_SERIES`（4 序列）+ `fetch_econ_series`（一次 POST，任何失败→`{}`）+ `_clean_series`（滤 `M13` 年度均值 / 非数值 / 非法 year）+ `_yoy` / `_yoy_at` / `_direction` / `_mean` / `_infl_axis` / `_growth_axis` / `_QUADRANTS` + `build_econ_payload` |
| `web/app.py` | `_ECON_TTL = 6*3600` + `_econ_cache` + `_econ_lock` + `GET /api/econ`（模式对齐 `api_macro`，**只缓存成功结果**）；模块级导入 `build_econ_payload / fetch_econ_series`（monkeypatch 打使用方） |
| `tests/test_econ_fetcher.py` | **新建**（约 230 行，**全程不联网**，stub `_SESSION.post`） |
| `tests/test_web.py` | `_reset_watch_cache` fixture 增加 `_econ_cache` 复位；新增 3 条端点测试（结构 / 降级+失败不缓存 / TTL 只请求 1 次 + `_ECON_TTL` 防回退断言） |
| `docs/architecture.md` / `docs/pitfalls.md` | 决策行 1 条 / 坑 4 条 |

**未改**（按 plan §9）：`daily_report.py` / `snapshot_report.py` / `generate_context` / `src/fetcher.py` / `requirements.txt` / 任何落盘路径。

---

## 2. 验证实测

### 2.1 测试

- E-0 基线：`554 passed`
- 改动后：**`592 passed`**（+38：`test_econ_fetcher.py` 新建 35 条 + `test_web.py` 新增 3 条）
- `pytest tests/test_econ_fetcher.py tests/test_web.py -q` → **122 passed**

### 2.2 真实数据（实跑，1 次 BLS 调用）

```
as_of= 2026-08 | axes= up expanding | quadrant= reflation 再通胀
  cpi          latest= 334.98   2026-08  yoy= 3.40   prev= 3.36   dir= flat
  ppi          latest= 157.411  2026-08  yoy= 5.41   prev= 4.80   dir= up
  unemployment latest= 4.1      2026-08  yoy= -4.65  prev= -4.65  dir= flat
  payrolls     latest= 159075.0 2026-08  yoy= 0.38   prev= 0.23   dir= up
```

按 plan 的验收判据逐条对照：

| 判据 | 实测 | 结论 |
|---|---|---|
| series 含 4 项，每项 latest / yoy / direction 非空 | 4 项全非空 | ✅ |
| `as_of == "2026-08"`（数据月份） | `2026-08` | ✅ |
| quadrant 与两轴自洽 | `reflation` = (`up`, `expanding`) 查表一致 | ✅ |
| 连续调 3 次只请求 BLS 1 次 | 见 §2.3 | ✅ |
| 断网时 200 + 空结构 | `test_api_econ_degrade_and_failure_not_cached` | ✅ |
| 无新增落盘文件 | `econ_fetcher.py` 内 `write_text/open/json.dump/...` **零命中**；无新增未跟踪文件 | ✅ |

### 2.3 真实服务（uvicorn）+ 连调 3 次

```
as_of:      ['2026-08', '2026-08', '2026-08']
fetched_at: ['2026-09-14T20:19:27', '2026-09-14T20:19:27', '2026-09-14T20:19:27']
TTL(3 次 fetched_at 相同): True          ← payload 级缓存命中 = BLS 只被请求 1 次
quadrant: reflation 再通胀   n=4
```

> 备注：本沙箱把含 `uvicorn` 字样的命令识别成「服务命令」并吞掉输出，改用等价写法才取到上面这段输出。

---

## 3. ⚠️ 执行中发现的问题：plan 的同比算法会**静默算错**（已修）

**现象（第一次实跑就暴露）**：4 个序列里 **CPI 与失业率的 `yoy` 是 `None`**，PPI / 非农正常。

**取证（打印真实序列尾部与缺失月份）**：

```
cpi          n=43   missing_in_24m=['2025-10']
unemployment n=43   missing_in_24m=['2025-10']
ppi          n=44   missing_in_24m=[]
payrolls     n=44   missing_in_24m=[]
```

→ **BLS 官方数据存在真实缺月**（CPI-U、失业率都缺 `2025-10`，43 条 vs 完整 44 条；PPI/非农不缺）。

**plan §3.3 的算法是"取倒数第 13 个"**（`values[-13]`）。在缺月序列上它会**把错月份的数值当去年同月**，算出的同比是错的、格式合法、**没有任何报错**。（我当时先加的"13 个月必须连续"守卫把它变成了 `None`，才没静默出错 —— 但 `None` 又会导致 CPI 同比在宏观页显示为空。）

**修复**：`_yoy_at` 改成**按月份键找去年同月**（`"2026-08"` → 查 `"2025-08"`），中间缺月不影响；去年同月缺失才 `None`。修复后 CPI `yoy=3.40`。

**API 变化（与 plan 的差异）**：

1. `_yoy(values: list)` → **`_yoy(base, cur)`**（两个标量）。plan 的用例写法「334.98 / 324.24 → ≈3.31」与两参形式一致；「不足 13 个月 → None」这条语义移到 `_yoy_at`（`len(rows) < 13` 守卫）。
2. 删掉了中途加过的 `_is_consecutive_months`（改用按键查找后不再需要，避免留死代码）。
3. `build_econ_payload` 内改为 `_yoy_at(rows, len(rows)-1)` / `(rows, len(rows)-2)`。

---

## 4. 其它实现取舍

1. **`_clean_series` 过滤 `M13`**：BLS 的 `M13` 是**年度均值**，混进来会污染 `latest`；`value="-"`（不可用）一并丢弃；输出统一**升序**（BLS 返回是倒序）—— 这些都在单测里钉住。
2. **`as_of` 取各序列中最新的数据月份**，单序列月份另放 `series[].date`（本次 4 序列同为 `2026-08`）。
3. **增长轴判定次序**：非农 3 个月均值方向为主（非持平即定调），非农持平才看失业率（**上行=恶化→收缩**）；两者都无数据 → `axis=None`。冲突时以非农为准的理由写在 docstring 里。
4. **`basis` 字段**：把「通胀轴 = CPI-U 同比（PPI 二次确认）」「增长轴 = 非农 3 月均值 + 失业率 3 月变化，**非 PMI**」「as_of 为数据月份、存在发布滞后」直接放进响应，供宏观页如实标注（plan R5/R6）。
5. **`inflation_axis` 在"持平"时**：先看 PPI，两者都持平 → 取 `"up"`（工程约定，四象限需二值轴）—— 已注释 + 单测覆盖。

---

## 5. 未做 / 后续

- **FRED**（本机不通，服务本身正常）与 **AkShare 其它 `macro_usa_*`**（停更在 2025-09、9.5~28s）均按 plan 否决，本任务不接。
- **AkShare `macro_usa_cpi_yoy` 降级源未接**（plan §2.3 列为可选）：BLS 失败时目前直接返回空结构。若后续要接，落点应是 `api_econ` 的失败分支（`build_econ_payload` 之外），**注意它只有 CPI 一项，不要伪装成 4 序列**。
- 前端消费（宏观页四象限 / 经济数据模块）属 `2026-09-14-macro-page` 任务，本任务只交付数据底座。
