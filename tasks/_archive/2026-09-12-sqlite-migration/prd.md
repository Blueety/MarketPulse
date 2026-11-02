# Task Handoff：数据存储升级（JSON → SQLite）

> 来源：用户 2026-09-12 提供的 Handoff（备份机制已更新为按月归档版）


## Goal

**将历史行情数据从 JSON 文件迁移到 SQLite 数据库**，并让 Web 看板改为查询 SQLite，实现更快的查询、更灵活的时间范围检索，**永久保留历史数据**，为后续复杂分析（回测、相关性）打基础。


## Current Understanding

### 现有存储方式

| 数据 | 现状 | 格式 |
| :--- | :--- | :--- |
| 历史行情 | `data/history.json` | 单一 JSON，date 为键，保留 90 天 |
| 告警记录 | `alerts/*.md` | Markdown 文件 |
| AI 上下文 | `context/*.json` | 每日 JSON 文件 |

### 目标存储方式

| 数据 | 目标 | 说明 |
| :--- | :--- | :--- |
| 历史行情 | **SQLite** (`data/marketpulse.db`) | 结构化存储，支持索引查询，永久保留 |
| 告警记录 | 保持 Markdown | 暂不迁移 |
| AI 上下文 | 保持 JSON | 暂不迁移 |

### 已确认的关键决策

| 决策项 | 结论 |
| :--- | :--- |
| **迁移方式** | 迁移后**直接切换**，不做双写过渡 |
| **JSON 文件** | 迁移完成后保留为备份，不再更新 |
| **数据保留** | **永久保留**，取消 90 天限制 |
| **备份机制** | **每日脚本运行后自动备份**，**按月归档**，提交到 Git 仓库 |


## Context Pointers

### 需新增/修改的文件

| 文件 | 动作 | 说明 |
| :--- | :--- | :--- |
| `data/marketpulse.db` | 新建 | SQLite 数据库文件（运行时生成，加入 .gitignore） |
| `src/storage.py` | 新建 | SQLite 连接管理 + 读写封装 |
| `src/analyzer.py` | 修改 | 历史数据读写改为调用 `storage.py` |
| `src/reporter.py` | 修改 | 趋势图数据从 SQLite 读取 |
| `web/app.py` | 修改 | `/api/history` 改为查询 SQLite，支持日期范围参数 |
| `scripts/migrate_to_sqlite.py` | 新建 | 一次性迁移脚本（JSON → SQLite） |
| `scripts/backup_db.py` | 新建 | SQLite 导出为 JSON 的备份脚本（按月归档） |
| `data/backup/` | 新建目录 | 存放备份文件（**提交到 Git**） |
| `tests/test_storage.py` | 新建 | SQLite 读写单元测试 |
| `requirements.txt` | 修改 | 无需新增依赖（使用标准库 `sqlite3`） |

### 需确认的现有实现

- `data/history.json` 的实际结构（date 为键还是列表？）
- `src/analyzer.py` 中读写历史数据的具体函数
- `web/app.py` 中 `/api/history` 的当前实现
- `src/config.py` 中 `retention_days: 90` 的配置项
- `daily_report.py` 的末尾流程（在哪里插入备份调用）


## Constraints

- **标准库优先**：使用 Python 标准库 `sqlite3`，不引入 ORM
- **直接切换**：迁移完成后，脚本和 Web 都直接读写 SQLite，不再双写 JSON
- **Web 仍为只读**：Web 看板只查询 SQLite，不写入
- **永久保留**：取消 90 天滚动删除逻辑
- **备份按月归档**：每月一个备份文件，当月重复运行覆盖更新
- **性能**：`/api/history` 查询响应时间 ≤ 200ms（30 天数据）
- **并发安全**：SQLite 使用 WAL 模式


## Out of Scope

- 告警、上下文、快照数据的迁移
- Web 看板的写操作
- 多用户支持
- 云数据库（PostgreSQL 等）
- 复杂查询优化


## Done When

### 阶段一：SQLite 基础设施

- [ ] `src/storage.py` 实现：
  - `init_db()` → 创建表和索引
  - `save_history(date, symbol, value, change)` → 写入单条记录
  - `query_history(symbols, start_date, end_date)` → 查询历史数据
  - `get_latest(symbol)` → 获取最新值
  - `get_date_range()` → 获取数据日期范围
- [ ] 数据库表结构：`history(date, symbol, value, change, PRIMARY KEY(date, symbol))`
- [ ] 索引：`idx_symbol_date ON history(symbol, date)` + `idx_date ON history(date)`
- [ ] 启用 WAL 模式：`PRAGMA journal_mode=WAL`

### 阶段二：数据迁移

- [ ] `scripts/migrate_to_sqlite.py` 实现：
  - 读取 `data/history.json`
  - 逐条写入 SQLite（事务批量写入）
  - 迁移完成后校验记录数一致
  - 输出迁移报告（成功/失败条数）
- [ ] 运行迁移脚本，确认 `data/marketpulse.db` 生成且数据完整
- [ ] `data/history.json` 保留为备份，不再被读写

### 阶段三：脚本侧改造

- [ ] `src/analyzer.py` 的历史读写改为调用 `storage.py`
- [ ] `src/reporter.py` 的趋势图数据从 SQLite 读取
- [ ] **移除 90 天滚动删除逻辑**，改为永久保留
- [ ] `src/config.py` 中 `retention_days` 配置废弃或标记为 deprecated
- [ ] 确认日报生成结果与迁移前一致

### 阶段四：Web 侧改造

- [ ] `web/app.py` 的 `/api/history` 改为查询 SQLite
- [ ] 支持查询参数：`days`（现有）、`start_date`/`end_date`（新增）
- [ ] 返回格式与现有 API 保持一致（前端无需改动）
- [ ] Web 看板功能不受影响，页面正常加载

### 阶段五：备份机制（按月归档）

- [ ] `scripts/backup_db.py` 实现：
  - 将 SQLite 全量导出为 JSON
  - **文件命名：`data/backup/history_YYYY-MM.json`**（按月归档）
  - **当月重复运行覆盖同一文件**（不产生多份）
  - 使用事务确保导出过程一致性
  - 导出完成后输出报告（记录数、文件大小）
- [ ] **每日脚本运行后自动触发备份**：在 `daily_report.py` 末尾调用备份逻辑
- [ ] **备份文件提交到 Git**：
  - 修改 `.gitignore`，确保 `data/backup/` **不被忽略**
  - 在自动 push 流程中（`AUTO_PUSH`）包含备份文件
  - 验证：运行脚本后，备份文件出现在 `git status` 中并被提交
- [ ] **备份按月保留**：每月一个文件，不删除历史月份
- [ ] **Web 启动恢复机制**（可选）：
  - Web 服务启动时，若 SQLite 不存在，从 `data/backup/` 最新的 JSON 恢复

### 验收

- [ ] 迁移后数据与 JSON 完全一致
- [ ] 日报生成结果不变
- [ ] Web 看板趋势图正常显示
- [ ] `/api/history?days=30` 响应时间 ≤ 200ms
- [ ] 新增 `start_date`/`end_date` 参数正常工作
- [ ] 历史数据不再被删除（超过 90 天仍可查询）
- [ ] 备份脚本能正常导出 JSON
- [ ] **每日脚本运行后自动更新当月备份文件**
- [ ] **备份文件被提交到 Git 仓库**
- [ ] 所有测试通过


## Verification

- [ ] 运行 `python scripts/migrate_to_sqlite.py`，检查迁移报告
- [ ] 对比 SQLite 查询结果与 `history.json`，确认数据一致
- [ ] 运行 `python daily_report.py`，确认日报生成正常
- [ ] 检查 `data/backup/` 目录下是否生成当月备份文件（如 `history_2026-09.json`）
- [ ] 同月内重复运行脚本，确认覆盖同一文件而非新增
- [ ] 运行 `git status`，确认备份文件被追踪
- [ ] 访问 `/api/history?days=30`，确认返回数据正确
- [ ] 访问 `/api/history?start_date=2026-08-01&end_date=2026-08-30`，确认新参数生效
- [ ] 查询超过 90 天的数据，确认仍可获取
- [ ] 重启 Web 服务，确认 SQLite 数据持久化
- [ ] `pytest tests/ -v` 全绿


## Risks

| 风险 | 应对 |
| :--- | :--- |
| 迁移过程中数据丢失 | 迁移前备份 `history.json`；迁移脚本使用事务，失败时回滚 |
| 直接切换后出现问题无法回退 | 保留 `history.json` 作为备份；如需回退，恢复旧代码 + JSON 即可 |
| Web 查询 SQLite 时并发冲突 | 启用 WAL 模式，读写分离；查询使用只读连接 |
| Railway 部署后 SQLite 文件丢失 | 备份机制 + Web 启动恢复：从 `data/backup/` 最新 JSON 恢复 |
| **备份文件提交 Git 导致仓库膨胀** | 按月归档，每月一份约 30KB-100KB，一年约 1MB，完全可控 |
| 备份文件与数据库不一致 | 备份脚本使用事务读取，确保导出时数据一致 |
| 永久保留导致数据库无限增长 | 个人项目每日约 12 条记录，10 年约 4.4 万条，SQLite 轻松处理 |
| 自动 push 流程与备份冲突 | 确认 `AUTO_PUSH` 流程包含 `data/backup/`，且不覆盖已有备份 |
| **同月多次运行导致备份文件被覆盖，丢失当月中间状态** | 这是预期行为（按月归档），最终状态以当月最后一次运行为准 |


## 📎 附录：SQLite 表结构

```sql
CREATE TABLE IF NOT EXISTS history (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    value REAL,
    change REAL,
    PRIMARY KEY (date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_symbol_date ON history(symbol, date);
CREATE INDEX IF NOT EXISTS idx_date ON history(date);
```

📎 附录：storage.py 接口设计

```python
def init_db(db_path="data/marketpulse.db"): ...
def save_history(date, symbol, value, change, db_path=...): ...
def save_history_batch(records, db_path=...): ...
def query_history(symbols=None, start_date=None, end_date=None, db_path=...): ...
def get_latest(symbol, db_path=...): ...
def get_date_range(db_path=...): ...
```

📎 附录：备份文件格式（按月归档）

```json
{
  "export_date": "2026-09-12",
  "month": "2026-09",
  "record_count": 1234,
  "records": [
    {"date": "2026-08-01", "symbol": "vix", "value": 22.30, "change": 0.15},
    {"date": "2026-08-01", "symbol": "spx", "value": 5600.00, "change": 0.012},
    ...
  ]
}
```

文件命名：data/backup/history_2026-09.json（当月文件，每次运行覆盖更新）

📎 附录：备份与恢复流程

每日备份（daily_report.py 末尾自动调用）：

```
1. 调用 scripts/backup_db.py
2. 读取 SQLite 全量数据
3. 导出为 JSON
4. 保存到 data/backup/history_YYYY-MM.json（当月文件，覆盖更新）
5. 输出备份报告（记录数、文件大小）
6. 备份文件被 AUTO_PUSH 流程提交到 Git
```

恢复（Web 服务启动时，可选实现）：

```
1. 检查 data/marketpulse.db 是否存在
2. 若不存在，从 data/backup/ 最新的 JSON 恢复
3. 若备份也不存在，从 data/history.json 恢复（旧格式）
```

📎 附录：.gitignore 调整

```gitignore
# 数据库文件（运行时生成，不提交）
data/marketpulse.db
data/marketpulse.db-wal
data/marketpulse.db-shm

# 备份文件（提交到 Git）
# data/backup/  # ← 不要忽略，需提交
```

📎 附录：备份文件体积估算

时间跨度 记录数 文件大小
1 个月 ~360 条 ~30KB
1 年 ~4,400 条 ~360KB
5 年 ~22,000 条 ~1.8MB

按月归档后，一年产生 12 个文件，总体积约 400KB，完全可控。

Created: 2026-09-12 | Next: 将本卡交给本地 Agent 开始编码
