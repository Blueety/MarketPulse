# 📊 MarketPulse — 美国市场波动率监控系统

> 每天自动获取 VIX / VXN / MOVE 三个波动率指数，生成带 AI 解读的日报，通过 QQ 推送。
> 异常波动时主动告警 + 自动归因分析。

![Architecture](docs/architecture-diagram.html)

---

## ✨ 五期能力一览

| 期 | 能力 | 说明 |
|---|---|---|
| 一期 | 收盘日报 | 每日获取 VIX/VXN/MOVE，生成 Markdown 日报 + 涨跌幅 + 状态 |
| 二期 | 午盘快照 + 趋势图 | 美东12:30 快照 + matplotlib 三面板近30日趋势图 |
| 三期 | 阈值告警 | 单日变化率超阈值(VIX/VXN ±20%, MOVE ±15%)独立推送告警 |
| 四期 | AI 解读 + 异动归因 | 每日 AI 市场解读 + 异动日 tavily 搜索归因分析 |
| 五期 | 阈值配置化 | 阈值外置到 config.json + env 覆盖，改配置不改代码 |

---

## 🚀 快速开始

```bash
# 1. 进入项目目录
cd D:\AGENT\MarketPulse

# 2. 激活虚拟环境
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 运行收盘日报
python daily_report.py

# 5. 运行午盘快照
python snapshot_report.py

# 6. 运行测试
python -m pytest tests/ -v
```

---

## 📁 项目结构

```
MarketPulse/
├── daily_report.py              # 收盘日报编排入口 (81 行)
├── snapshot_report.py           # 午盘快照入口 (46 行)
├── seed_history.py              # 半年历史回填工具 (113 行)
├── requirements.txt             # requests + matplotlib + pytest
├── .env.example                 # 无需 API 密钥
│
├── src/                         # 核心模块 (约 1065 行)
│   ├── fetcher.py               #   数据获取 (Yahoo REST + 重试/退避)
│   ├── analyzer.py              #   纯逻辑层 (状态/涨跌幅/缓存/历史/阈值/关键词)
│   ├── alerter.py               #   告警层 (渲染/去重/编排)
│   ├── config.py               #   配置加载 (默认/env/json 三级, 零依赖)
│   └── reporter.py              #   报告层 (日报/快照/趋势图/context生成)
│
├── tests/                       # 单元测试 (113 项, 约 900 行)
│   ├── test_analyzer.py         #   185 行
│   ├── test_alerter.py          #   184 行
│   ├── test_reporter.py         #   148 行
│   ├── test_config.py          #   配置加载/接线测试
│   └── test_context.py          #   190 行
│
├── docs/                        # 项目文档
│   ├── architecture.md          #   架构说明
│   ├── architecture-diagram.html #  架构图 (暗色系 SVG)
│   ├── commands.md              #   验证命令
│   └── pitfalls.md              #   已知坑点
│
├── skills/                      # 开发流程模板
│   ├── bug-fix/SKILL.md         #   Bug 修复流程
│   └── pre-review/SKILL.md      #   提交前审查流程
│
├── tasks/                       # 四期任务交接 (prd/plan/journal)
├── reports/                     # 报告输出 (运行时生成, gitignore)
├── data/                        # 数据 (运行时生成, gitignore)
├── context/                     # AI 上下文 (运行时生成, gitignore)
└── alerts/                      # 告警文件 (运行时生成, gitignore)
```

---

## 🔄 数据流

```
Yahoo Finance (^VIX / ^VXN / ^MOVE)
        │  fetcher.py (重试/退避/单源容错)
        ▼
   analyzer.py ──────────────────────────────────────
   │ 状态分类 │ 涨跌幅 │ 缓存 │ 历史 │ 阈值判断 │
   │                                               │
   ├──► daily_report.py ──► reports/YYYY-MM-DD.md  │
   │                        + charts/趋势图         │
   │                        + context/JSON          │
   │                                               │
   ├──► snapshot_report.py ──► snapshots/noon.md   │
   │                                               │
   └──► alerter.py ──► alerts/{type}.md            │
                      + alerts.log (去重)           │
                                │                   │
                                ▼                   │
                    Hermes Agent (MiMo-V2.5)        │
                    │                               │
                    ├── 读 context → AI 市场解读     │
                    ├── 异动日 → tavily 搜索归因     │
                    └── 组装 → 推送 QQ              │
```

---

## ⏰ 自动调度 (Hermes Cron)

| 任务 | 时间 | 内容 | 推送 |
|------|------|------|------|
| 📉 收盘日报+AI解读 | 每天早 8:00 (北京) | 跑脚本→读context→AI解读→异动归因 | 日报+趋势图+AI+归因 |
| 🕛 午盘快照 | 每天 00:30 (北京) = 12:30 (美东) | 跑快照→检测告警 | 快照+告警(如有) |

---

## 📊 三个波动率指数

| 指数 | 含义 | 阈值 |
|------|------|------|
| **VIX** (恐慌指数) | 标普500 波动率，衡量市场恐慌程度 | <20 平静 / 20-30 警惕 / ≥30 恐慌 |
| **VXN** (科技波动) | 纳斯达克100 波动率 | 同 VIX |
| **MOVE** (债市波动) | 美国国债波动率 | <100 平静 / 100-130 警惕 / ≥130 恐慌 |

---

## 🧪 测试

```bash
# 全部测试 (113 项)
python -m pytest tests/ -v

# 预期: 113 passed
```

覆盖范围: 状态分类 / 涨跌幅 / 告警阈值 / 去重 / 趋势图 / context生成 / 关键词 / 配置加载

---

## 📈 趋势图

收盘日报自动附带三面板趋势图 (VIX/VXN/MOVE 近30日走势), 由 matplotlib 渲染:
- 橙色 = MOVE (债市)
- 玫红 = VXN (科技)
- 蓝色 = VIX (恐慌)

---

## 🚨 告警机制

- **触发条件**: 单日变化率超阈值 (VIX/VXN ±20%, MOVE ±15%)
- **阈值覆盖**: 支持环境变量 `ALERT_THRESHOLD_VIX=25`
- **去重**: 午盘触发则收盘跳过同一指数
- **推送**: 独立告警消息 (不混在日报里)

## ⚙️ 配置说明（五期）

阈值（状态分类、告警、趋势窗口、历史保留）已外置到 `config.json`（项目根，gitignore 排除，不入库）。

**优先级链**：环境变量 > config.json > 内置默认。config.json 缺失/损坏/类型非法 → 对应键回退默认，仅记日志，不崩溃。

**config.json 结构**（示例值即默认，可改）：

```json
{
  "analysis": {
    "vix": { "peaceful": 20, "panic": 30 },
    "move": { "normal": 100, "tight": 130 }
  },
  "alert": { "vix": 20, "vxn": 20, "move": 15 },
  "trend": { "chart_days": 30 },
  "history": { "retention_days": 90 }
}
```

**环境变量覆盖**（最高优先级，调用时生效，无需重启）：

| env | 覆盖项 |
| --- | --- |
| ALERT_THRESHOLD_VIX / VXN / MOVE | 变化率告警阈值 |
| STATUS_THRESHOLD_VIX_CALM / VIX_PANIC | VIX/VXN 平静/恐慌分界 |
| STATUS_THRESHOLD_MOVE_CALM / MOVE_WARN | MOVE 平静/警惕分界 |
| TREND_CHART_DAYS | 趋势图窗口（天） |
| HISTORY_RETENTION_DAYS | 历史保留天数 |
| CONFIG_PATH | 自定义配置文件路径 |

> 改配置对下次运行生效（cron 每进程全新启动）。告警阈值 env 非法/非正自动回退默认。
---

## 🤖 AI 解读 + 异动归因

- **每日常规解读**: 200-300 字市场情绪解读
- **异动归因** (breach.triggered=true): tavily 搜索当日新闻→300-400 字归因分析
- **容错**: 归因失败不影响日报推送

---

## 🔧 技术栈

| 项 | 值 |
|---|---|
| 语言 | Python 3.14 (venv) |
| 依赖 | requests + matplotlib + pytest |
| 数据源 | Yahoo Finance (公开 REST, 无需 API key) |
| AI | Hermes Agent + MiMo-V2.5 + Tavily Search |
| 调度 | Hermes Cron |
| 推送 | QQ 私聊 |
| 测试 | 113 项, 全绿 |

---

## 📝 开发工作流

1. 在 `tasks/` 下建任务目录, 写 `prd.md`
2. 架构师 (K2.7) 出 `plan.md`, 等用户确认
3. 执行者 (Hy3) 实施, 逐步验证, 留 diff 审阅
4. 用户确认后 commit, 经验沉淀到 `docs/`

---

## 📜 Git 历史

```
5791e77 feat: 四期AI解读+异动归因上下文
23c238f feat: 三期阈值告警(主动监控/告警去重/env阈值)
df26279 feat: 二期盘中感知+可视化(快照/趋势图/三模块拆分)
12a2086 feat: 波动率监控 MVP(VIX/VXN/MOVE日报+缓存)
b738421 docs: 完善项目 README 说明
1843d9e init: 项目脚手架+技术栈初始化
```

---

*MarketPulse — 让你每天早上知道市场在想什么，异常时告诉你为什么。*