# Task Handoff：MarketPulse 第七期 — 盘中快照扩展

> 复制到 `tasks/2026-09-01-marketpulse-phase7/prd.md`


## Goal

扩展盘中快照能力,在 A 股和美股交易时段内各取快照,通过 Hermes cron 推送。新增创业板指数(399006.SZ),SYMBOLS 7→8。

## 已确认的设计决策

1. **4 个 cron 任务**:A 股午盘(11:30) + A 股收盘(15:00) + 美股开盘(21:30) + 美股午盘(00:00)
2. **新增创业板**(399006.SZ),SYMBOLS 8 个
3. **扩展现有 snapshot_report.py**,不新建模块
4. **快照存 reports/snapshots/**(跟现有午盘快照同目录,gitignore 已有)
5. **不做存储 cleanup**(简单化)
6. **不做报告整合**(快照独立存储,日报不加"盘中关键时点")
7. **不做快照 AI 解读**

## 新增指数

| 市场 | 指数 | Yahoo 代码 | 告警阈值 |
|------|------|-----------|---------|
| A 股 | 创业板指 | `399006.SZ` | ±5% |

## 4 个快照 cron

| 任务 | 时间(北京) | 市场 | 推送 |
|------|-----------|------|------|
| A 股午盘 | 11:30 | a-share | 推送快照 |
| A 股收盘 | 15:00 | a-share | 推送快照 |
| 美股开盘 | 21:30 | us | 推送快照 |
| 美股午盘 | 00:00 | us | 推送快照 |

## Requirements

### 数据获取
- snapshot_report.py 支持 `--market a-share` / `--market us` 参数
- a-share: 取 SH/SZ/创业板(399006.SZ)
- us: 取 GSPC/IXIC
- 复用 fetcher.py 已有获取逻辑

### 快照存储
- 存储路径:`reports/snapshots/YYYY-MM-DD-{market}-{time}.md`
- 格式:Markdown(跟现有午盘快照一致,不是 JSON)
- 不写 history.json(快照仅存储,不影响涨跌幅基准)

### 告警
- 快照时也检查大盘告警(复用 alerter.py)
- 触发则推送告警(跟日报告警共用通道)

### 测试
- 新增快照相关测试
- 既有测试不受影响

## Constraints

- 零新依赖
- 快照不写 history.json
- 快照文件 gitignore 已有(不入库)
- Yahoo 对休市日返回最近收盘值(非 None),快照仍正常生成

## Done When

- [ ] snapshot_report.py 支持 `--market a-share` / `--market us` 参数
- [ ] 创业板(399006.SZ)加入 SYMBOLS,fetcher/analyzer/alerter/config 同步
- [ ] 4 个 Hermes cron 配置完成
- [ ] 快照文件正确生成(freports/snapshots/)
- [ ] 快照时大盘告警正常触发
- [ ] 所有测试通过

## Verification

- [ ] 运行 `python snapshot_report.py --market a-share`,检查快照生成
- [ ] 运行 `python snapshot_report.py --market us`,检查快照生成
- [ ] 运行 `python daily_report.py`,检查 8 个指数全取到
- [ ] 模拟创业板告警,确认触发
- [ ] pytest tests/ -v 全绿