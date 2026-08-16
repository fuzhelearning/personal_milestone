# ADR-0009: 不建 DB 外键；日安排落表；澄清「实时算」不等于烧 Token

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户
- Related Specs: 06-data-model, 03-domain-model

## Context

用户担心：今日/本周列表若「实时算」会废 token、缓存会因重启丢失，因此希望 `day_entries` 与今日/本周列表都落表。

## Clarification（讨论结论）

| 担心 | 实际情况 |
|------|----------|
| 实时算废 DeepSeek token | **不会**。从 MySQL 按 `plan_date` 查列表是普通 SQL，**不调 AI**。只有「+」生成 / 周日重排 / 完成日确认重排才调 DeepSeek。 |
| 服务器重启丢数据 | **内存/Redis 缓存**会丢；**MySQL 表不会丢**。 |
| 要落表 | 同意：用 **`day_assignments` 作为今日/本周列表的持久化真相**（不是另搞一层易失缓存）。 |

## Decision

1. **外键**：列上保留 `*_id` 与索引；**不创建 MySQL `FOREIGN KEY` 约束**；引用完整性由应用层保证。
2. **迁移**：Alembic。
3. **MySQL**：**8.0**（常用 LTS）。
4. **软删**：仅 `goals.deleted_at`；`day_entries` / `day_assignments` 历史按规则保留或重排覆盖，不做自动清库。
5. **落表策略**：
   - `day_assignments`：**落表** = 「哪天做哪项」= 今日任务 + 本周剩余的数据源（重启安全）。
   - `day_entries`：**落表** = 完成/未完成+原因。
   - 首页读取：`SELECT ... FROM day_assignments WHERE goal_id=? AND plan_date=...`（可 JOIN entries），**禁止**为渲染列表去调 LLM。
   - **不**用 Redis 扛今日/本周列表。

## Consequences

- 与用户「列表也要落表」一致；`day_assignments` 即该落表，无需再加第三张「today_cache」表。
- 顺延/重排改的是 `day_assignments` 行，不是改缓存。
