# 📊 MarketPulse — 全市场情绪监控系统

> 每天自动获取美股、A股、波动率、黄金、比特币数据，生成带 AI 解读的日报，通过 QQ 推送。
> 异常波动时主动告警 + 自动归因分析 + 板块热度追踪 + 相关性分析。

![Architecture](docs/architecture-diagram.html)

---

## ✨ 十五期能力一览

| 期 | 能力 | 说明 |
|---|---|---|
| 一期 | 收盘日报 | VIX/VXN/MOVE 日报 + 缓存 |
| 二期 | 午盘快照 + 趋势图 | 快照 + matplotlib 三面板趋势图 |
| 三期 | 阈值告警 | 单日变化率超阈值独立推送 |
| 四期 | AI 解读 + 归因 | 每日 AI 解读 + 异动日新闻归因 |
| 五期 | 阈值配置化 | config.json 配置 + env 覆盖 |
| 六期A | 美股大盘 | 标普500 + 纳斯达克 |
| 六期B | A股大盘 | 上证 + 深证 + 创业板 |
| 七期 | 盘中快照扩展 | 6 个 cron + 创业板 + AkShare 实时 |
| 八期 | 板块热度 | A股 Top5 领涨/领跌 + 美股 11 板块 |
| 九期 | 趋势图扩展 | 美股/A股/另类资产三张图 |
| 十期 | 黄金 & 比特币 | GLD + BTC-USD 监控 |
| 十一期 | Web 看板 | FastAPI + Chart.js + 深色主题 |
| 十二期 | 相关性分析 | Pearson 相关系数 + 5 组关键对 |
| 十三期 | 回测验证 | 告警阈值历史回测 + 报告 |
| 十四期 | 日报图片化 | Playwright 截图 + QQ 推送图片 |
| 十五期 | 开盘分析 | 开盘跳空 + 板块轮动 + 新闻归因 |

---

## 🚀 快速开始

```bash
# 1. 进入项目目录
cd D:\AGENT\MarketPulse

# 2. 激活虚拟环境
venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 运行日报
python daily_report.py

# 5. 启动 Web 看板
uvicorn web.app:app --port 8000
```

---

## 📊 监控标的（12 个）

| 类别 | 指数/资产 | 数据源 |
|------|----------|--------|
| 美股大盘 | 标普500、纳斯达克 | Yahoo Finance |
| A股大盘 | 上证、深证、创业板 | **AkShare（实时）** |
| 波动率 | VIX、VXN、MOVE | Yahoo Finance |
| 另类资产 | 黄金(GLD)、比特币(BTC-USD) | Yahoo Finance |
| 美股板块 | 11 个 SPDR Sector ETF | Yahoo Finance |
| A股板块 | 概念板块 Top5 领涨/领跌 | **AkShare** |

---

## ⏰ 自动调度（7 个 cron）

| 任务 | 时间(北京) | 推送 |
|------|-----------|------|
| 收盘日报 + AI 解读 | 08:00 | QQ |
| 开盘分析 + 快照 | 09:45 | QQ |
| A股午盘快照 + AI 分析 | 11:45 | QQ |
| A股收盘快照 + AI 分析 | 15:00 | QQ |
| 美股开盘快照 + AI 分析 | 21:45 | QQ |
| 美股午盘快照 + AI 分析 | 00:00 | QQ |
| 数据同步 GitHub | 08:15 | 本地 |

---

## 🌐 Web 看板

```bash
# 本地访问
http://localhost:8000

# 公网访问 (Railway)
https://marketpulse-blue.up.railway.app
```

功能：
- 📈 市场概览（10 指数实时数据）
- 📉 趋势图（美股/A股/波动率/另类资产，相对涨跌）
- 🔥 板块热度（A股领涨/领跌 + 美股 11 板块）
- 📊 相关性分析（5 组关键对）
- 🔔 告警记录

---

## 📁 项目结构

```
MarketPulse/
├── src/                    # 核心模块
│   ├── fetcher.py          # 数据获取（Yahoo + AkShare）
│   ├── analyzer.py         # 分析逻辑（阈值/趋势/相关性）
│   ├── alerter.py          # 告警管理
│   ├── reporter.py         # 报告渲染
│   ├── config.py           # 配置管理
│   ├── image_renderer.py   # 日报图片化
│   └── opening_analyzer.py # 开盘分析
├── web/                    # Web 看板
│   ├── app.py              # FastAPI 应用
│   └── templates/          # HTML 模板
├── scripts/                # 工具脚本
│   ├── backtest.py         # 回测验证
│   └── render_report_image.py
├── daily_report.py         # 日报入口
├── snapshot_report.py      # 快照入口
├── opening_analyzer.py     # 开盘分析入口
├── config.json             # 配置文件
├── data/                   # 数据文件
├── reports/                # 报告输出
└── tests/                  # 测试
```

---

## ⚙️ 配置说明

### 告警阈值（config.json）

```json
{
  "alert": {
    "vix": 20.0,
    "vxn": 20.0,
    "move": 12.0,
    "gspc": 2.5,
    "ixic": 3.5,
    "sh": 2.5,
    "sz": 3.5,
    "cyb": 5.0
  }
}
```

### 环境变量覆盖

```bash
ALERT_THRESHOLD_VIX=25    # 覆盖 VIX 阈值
ALERT_THRESHOLD_GSPC=3.0  # 覆盖标普阈值
```

---

## 🧪 测试

```bash
pytest tests/ -v
```

当前：**281 测试通过**

---

## 📝 更新日志

- **2026-08-31**: 十五期开盘分析 + A股新浪实时接口 + 所有分析加新闻搜索
- **2026-08-31**: 十四期日报图片化(Playwright) + Web 看板深色主题
- **2026-08-30**: 十三期回测 + 十二期相关性 + 十一期 Web 看板 + 十期黄金比特币
- **2026-08-29**: 一期~九期(从 MVP 到全市场监控)

---

*本报告由 MarketPulse 自动生成 | 数据来源：Yahoo Finance / AkShare*
