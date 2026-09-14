# 计划：经济数据源接入（BLS）—— 支撑宏观环境五态判断

- **日期**：2026-09-14
- **任务目录**：`tasks/2026-09-14-econ-data-source/`
- **来源**：需求方要求「把『必须有通胀数据和增长数据』这一块做了」
- **定位**：**`tasks/2026-09-14-macro-page/plan.md` 的前置依赖**（宏观页模块 6「历史宏观环境」五态 + 模块 7「经济数据」需要它）

---

## 1. 结论先行

**找到了可用源：BLS（美国劳工统计局）官方 API —— 免 Key、权威、数据本月新鲜、零新依赖。**

实测结果（本轮亲自跑的）：

```text
POST https://api.bls.gov/publicAPI/v2/timeseries/data/
HTTP 200   2.1s   status=REQUEST_SUCCEEDED
CPI-U      n=20   最新 2026-M08 = 334.980
失业率      n=20   最新 2026-M08 = 4.1
非农合计     n=20   最新 2026-M08 = 159075
PPI终需求    n=20   最新 2026-M08 = 157.411
```

**一次请求拿 4 个序列**，两个轴全覆盖：

| 轴 | 指标 | 序列 ID |
|---|---|---|
| **通胀** | CPI-U（消费者物价指数） | `CUUR0000SA0` |
| **通胀** | PPI 终需求 | `WPSFD4` |
| **增长** | 失业率 | `LNS14000000` |
| **增长** | 非农就业合计 | `CES0000000001` |

---

## 2. 数据源调研（含被否决方案的证据）

| 源 | 本机可达 | 数据新鲜 | 耗时 | 覆盖 | 判定 |
|---|---|---|---|---|---|
| **BLS 官方 API** | ✅ | **2026-M08** | **2.1s** | CPI/PPI/失业率/非农 | ✅ **选** |
| AkShare `macro_usa_cpi_yoy` | ✅ | ✅ 2026-08 | 1.0s | 仅 CPI 同比 | ⚪ 备用 |
| AkShare 其余 `macro_usa_*` | ✅ | ❌ **2025-09 停更** | **9.5~28s** | 含 PMI/GDP 但不可用 | ❌ **否决** |
| FRED CSV（免 Key） | ❌ 本机不通 | ✅ 2026-08 | — | 全线 | ❌ **否决**（见下） |

### 2.1 ❌ 否决 AkShare 的 `macro_usa_*`（除 cpi_yoy）

实测 6 个接口：

| 接口 | 耗时 | 最新数据 |
|---|---|---|
| `macro_usa_cpi_yoy` | **1.0s** | **2026-08-01** ✅ |
| `macro_usa_core_pce_price` | 24.3s | **2025-08-29** ⚠️ |
| `macro_usa_ism_pmi` | 27.4s | **2025-09-02** ⚠️ |
| `macro_usa_unemployment_rate` | 28.1s | **2025-09-05** ⚠️ |
| `macro_usa_gdp_monthly` | 9.9s | **2025-09-25** ⚠️ |
| `macro_usa_cpi_monthly` | 26.3s | **2025-09-11** ⚠️ |

**两个致命问题**：
1. **数据停更在 2025-09**（现在是 2026-09）→ **一年前的数据不能用来判断当前 regime**
2. **耗时 9.5~28s** → 远超项目任何超时预算（`SECTOR_TIMEOUT=10` / `US_SECTOR_TIMEOUT=20`），**web 端点直接调用会拖死请求**

⚠️ 有意思的是 `cpi_yoy` 的列名是 `时间/发布日期/现值/前值`，而其余是 `商品/日期/今值/预测值/前值` —— **它们来自不同的数据源**，这解释了为何只有前者新鲜。**不要假设同族接口行为一致。**

### 2.2 ❌ 否决 FRED（服务是好的，但本机网络不通）

- **FRED 服务正常**：经另一条网络路径确认，`fredgraph.csv?id=CPIAUCSL` 返回完整数据，最新 **2026-08-01 = 334.131** ✅
- **但本机不可达**：直连 20.9s 超时、走 Clash 代理 30s 仍超时（6 个序列全部失败）

→ 本地开发会一直失败；不选它做主源。**若将来部署到海外环境（Railway）可作补充源**，但本任务不做。

### 2.3 ⚪ AkShare `macro_usa_cpi_yoy` 作为备用

1.0s / 数据新鲜 / **已依赖零成本**。但**只有 CPI 同比一项**，撑不起增长轴。
→ 作为 `/api/econ` 的**通胀轴降级源**（BLS 失败时）。

---

## 3. 架构设计

### 3.1 数据流

```text
BLS API（POST，4 序列一次拿）
   │
   └─→ src/econ_fetcher.py        ← 新增：拉取 + 清洗 + 派生（同比/方向）
          │
          └─→ web/app.py  GET /api/econ   ← 新增端点，**6 小时 TTL 内存缓存**
                 │
                 └─→ 宏观页「历史宏观环境」+「经济数据」模块
```

**零写盘**（符合 Web 只读约束）：全部在内存完成，不落盘、不进 history、不改任何现有管线。

### 3.2 ⚠️ TTL 必须是小时级（本任务最关键的设计点）

**BLS 无 Key 的限额是 25 次查询 / 日 / IP。**

- 若沿用 `/api/macro` 的 **90s TTL** → 一天最多 960 次 → **必然超限**
- → `/api/econ` 的 TTL 定为 **6 小时**（一天最多 4 次，留足余量）

**经济数据是月度的**，6 小时 TTL 完全不影响新鲜度。

### 3.3 派生指标（`econ_fetcher` 内完成）

| 派生 | 算法 | 说明 |
|---|---|---|
| CPI 同比 | `(今月 / 去年同月 - 1) × 100` | BLS 返回**指数**（如 334.980），**同比要自己算** |
| CPI 方向 | 最新同比 vs 前值同比 | 上行 / 下行 / 持平 |
| PPI 同比 | 同上 | 通胀的第二确认 |
| 失业率方向 | 最新 vs 前值（3 个月变化） | 上行（恶化）/ 下行（改善） |
| 非农方向 | 最新 vs 前值（3 个月均值） | 单月噪声大，用 3 月均值更稳 |

⚠️ **必须拉够月份**：算同比至少需要 13 个月。建议 `startyear = 当前年 - 3`（约 36~48 个月），兼顾同比 + 趋势。

### 3.4 五态/四象限映射（供宏观页模块 6 使用）

```text
通胀轴 = CPI 同比方向（上行/下行）
增长轴 = 非农 3 月均值方向 + 失业率方向 共同判定（扩张/收缩）

           通胀 ↑                    通胀 ↓
增长 ↑   Reflation 再通胀        Goldilocks 复苏
增长 ↓   Stagflation 滞胀        Deflation 通缩衰退
```

叠加上 §宏观页 plan 的 `Risk-On / Neutral / Risk-Off` → **五态齐备**。

⚠️ **诚实标注**：
- 增长轴用**就业**（非农+失业率）替代 GDP/PMI —— 因为 **GDP 在 BEA（需 Key）、PMI 是 ISM 专有（无免费源）**。就业是增长轴的核心月度指标，且比季度 GDP 更及时，是合理替代，但**不是 PMI**。
- 象限**阈值是工程取值**，须在代码注释与前端标注中说明。

---

## 4. 要改的文件列表

| 文件 | 动作 | 说明 |
|---|---|---|
| **`src/econ_fetcher.py`** | **新建** | BLS 拉取 + 清洗 + 派生（同比/方向/四象限）|
| `web/app.py` | 新增约 45 行 | `GET /api/econ` + 6h TTL 缓存 + 失败降级空结构 |
| `tests/test_econ_fetcher.py` | **新建** | 纯函数单测（同比/方向/象限）+ 降级路径 |
| `tests/test_web.py` | 新增约 25 行 | `/api/econ` 端点（含降级 / 缓存）|
| `tasks/2026-09-14-econ-data-source/plan.md` / `journal.md` | 新增 | 本文件 / 执行记录 |
| `docs/architecture.md` | 追加 1 条决策 | BLS 接入 + TTL 理由 |
| `docs/pitfalls.md` | 追加 2 条 | 见 §7 |

**不改**：`daily_report.py` / `snapshot_report.py` / `src/analyzer.py` / `src/fetcher.py` / `generate_context` / 任何落盘路径 / `requirements.txt`（`requests` 已够）。

---

## 5. 实现步骤

### E-0 · 基线

```text
venv/Scripts/python -m pytest tests/ -v          # 记录通过数
```

### E-1 · 新建 `src/econ_fetcher.py`

```text
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
ECON_SERIES = {
    "CPI-U":     "CUUR0000SA0",
    "PPI终需求":  "WPSFD4",
    "失业率":     "LNS14000000",
    "非农就业":   "CES0000000001",
}

def fetch_econ_series(startyear=None, timeout=20) -> dict:
    """POST BLS 拿全部序列；失败/非 SUCCEEDED → {}（不抛）。"""

def _yoy(values) -> float | None:
    """同比 %：(今月/去年同月 - 1) * 100；不足 13 个月 → None。"""

def build_econ_payload(raw) -> dict:
    """清洗 + 派生 → 统一结构（见 §5.1）；数据不足的字段一律 None，不猜。"""
```

**§5.1 统一输出结构**：

```text
{
  "as_of": "2026-08",                      # 数据月份（不是抓取时间！）
  "fetched_at": "2026-09-14T20:00:00",
  "series": [
    {"key": "cpi", "label": "CPI-U", "unit": "index", "latest": 334.98,
     "yoy": 3.4, "prev_yoy": 3.3, "direction": "up", "history": [["2026-03", 330.29], ...]},
    ...
  ],
  "inflation_axis": "up",                  # 通胀轴
  "growth_axis": "expanding",              # 增长轴
  "quadrant": "reflation",                 # 四象限
  "quadrant_label": "再通胀"
}
```

⚠️ **`as_of` 必须是数据月份**（如 `"2026-08"`），**不是抓取时间**。经济数据有发布滞后，前端必须显示「2026年8月」而不是「最新」—— 否则用户会以为这是实时值。

### E-2 · `/api/econ` 端点（6h TTL）

```text
_ECON_TTL = 6 * 3600        # ★ 6 小时：BLS 无 Key 限量 25 次/日，90s TTL 会直接超限

@app.get("/api/econ")
def api_econ() -> dict:
    """经济数据（BLS，长 TTL；失败降级空结构，只缓存成功结果）。"""
    # 模式完全对齐现有 api_macro（web/app.py:728-741）
```

⚠️ **只缓存成功结果** —— 失败不写入缓存，否则一次失败会锁死 6 小时。

### E-3 · 测试

`tests/test_econ_fetcher.py`（用夹具，不联网）：

| 用例 | 期望 |
|---|---|
| `_yoy` 正常 | 334.98 / 324.24 → ≈3.31 |
| `_yoy` 不足 13 个月 | `None` |
| `_yoy` 去年同月为 0 | `None`（防除零） |
| 方向判定 | up / down / flat |
| 四象限映射 | 四个组合各一例 |
| BLS 返回 `REQUEST_NOT_PROCESSED` | `{}`（不抛） |
| 超时 / 网络错 | `{}`（不抛） |
| `build_econ_payload({})` | 空结构 + `as_of=None`（不崩） |

`tests/test_web.py`：`/api/econ` 200 + 结构 + 降级。

### E-4 · 记录

- journal：实测数据（4 序列最新值）、TTL 取值理由、被否决源的证据。
- `docs/architecture.md` 决策条目。
- `docs/pitfalls.md`：见 §7。

---

## 6. 验证命令（引自 `docs/commands.md`）

```text
venv/Scripts/python -m pytest tests/ -v
venv/Scripts/python -m pytest tests/test_econ_fetcher.py -v
venv/Scripts/python -c "from src.econ_fetcher import fetch_econ_series, build_econ_payload; import json; print(json.dumps(build_econ_payload(fetch_econ_series()), ensure_ascii=False, indent=2)[:900])"
curl http://localhost:<port>/api/econ
```

**验收判据**：
- [ ] `series` 含 4 项，每项 `latest` / `yoy` / `direction` 非空
- [ ] `as_of` = `"2026-08"`（数据月份）
- [ ] `quadrant` 有值且与 `inflation_axis`/`growth_axis` 自洽
- [ ] 连续调 3 次 `/api/econ`，**BLS 只被请求 1 次**（TTL 生效）
- [ ] 断网时返回 200 + 空结构（**不 500**）

---

## 7. 风险评估

| # | 风险 | 等级 | 对策 |
|---|---|---|---|
| **R1** | **BLS 无 Key 限 25 次/日，TTL 过短会超限** | **高** | TTL = **6 小时**（一天 ≤4 次）；**必须**写进代码注释，防后人"优化"成 90s |
| **R2** | **`as_of` 显示错**：经济数据有发布滞后，用抓取时间会误导 | **高** | `as_of` 取 BLS 返回的**数据月份**；前端显示「2026年8月」 |
| **R3** | **CPI 是指数不是同比**，直接用会显示 334.98% | **高** | `_yoy` 自己算同比；单测覆盖 |
| **R4** | BLS 接口变更 / 超限返回 `REQUEST_NOT_PROCESSED` | **中** | 判 `status != REQUEST_SUCCEEDED` → 返回 `{}`；失败**不写缓存** |
| **R5** | 增长轴无 GDP/PMI，用就业替代 | **中** | 在代码注释与前端标注「增长轴 = 非农 + 失业率」；**不宣称是 PMI** |
| **R6** | 四象限阈值是工程取值 | **中** | 常量集中定义 + 注释说明；前端标「口径」 |
| **R7** | 单月非农噪声大 | **中** | 用 **3 个月均值**判方向（已在 §3.3） |
| **R8** | BLS 不可达（网络） | **中** | 降级空结构；可选用 AkShare `macro_usa_cpi_yoy` 补通胀轴（§2.3） |
| **R9** | 内存缓存在 Railway 重启后失效 | **低** | 冷启动一次 2.1s，可接受；远低于限额 |
| **R10** | Web 只读约束被破坏 | **低** | 全部内存计算，**不落盘**；验收时确认无新文件 |

---

## 8. 预估影响的文件范围

| 类型 | 文件 | 规模 |
|---|---|---|
| 新建 | `src/econ_fetcher.py` | 约 150 行 |
| 新建 | `tests/test_econ_fetcher.py` | 约 130 行 |
| 修改 | `web/app.py` | +约 45 行 |
| 修改 | `tests/test_web.py` | +约 25 行 |
| 新增 | `tasks/2026-09-14-econ-data-source/plan.md` / `journal.md` | 本文件 / 执行记录 |
| 追加 | `docs/architecture.md` / `docs/pitfalls.md` | 1 决策 + 2 坑 |

**净代码变更估算**：约 **+350 行**。

---

## 9. 不做什么

- **不接入 FRED**（本机网络不通，见 §2.2）
- **不接入 AkShare 的 PMI/GDP/PCE**（数据停更在 2025-09，见 §2.1）
- **不落盘、不进 history、不改 `generate_context`**
- **不新增依赖**（BLS 用 `requests`，已在 `requirements.txt`）
- **不做 BEA / ISM**（前者需 Key，后者专有无免费源）
- **不接入中国经济数据**（本次只做美国，与 `/api/macro` 的四品种口径一致）

---

## 10. 确认

- [ ] 已确认数据源选 **BLS 官方 API**（免 Key / 权威 / 2026-M08 / 2.1s）
- [ ] 已确认 **TTL 必须 6 小时**（BLS 限 25 次/日，R1）
- [ ] 已确认 `as_of` 用**数据月份**而非抓取时间（R2）
- [ ] 已确认 **CPI 是指数，同比要自己算**（R3）
- [ ] 已确认增长轴用**就业替代** GDP/PMI，并如实标注（R5）
- [ ] 已确认本任务**零写盘**，符合 Web 只读约束
- [ ] 已确认本任务是 `2026-09-14-macro-page` 的**前置依赖**
