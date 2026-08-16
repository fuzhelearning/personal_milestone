# 06 — Data Model (MySQL)

- Status: Frozen
- Owner: [TODO]
- Last Updated: 2026-08-02
- Related ADRs: ADR-0005…0009, ADR-0015, ADR-0016
- Note: 已确认——`day_assignments` 即今日/本周落表真相；不建第三张缓存表；无 DB FK；Alembic；MySQL 8.0

## 1. 约定（已拍板）

| 项 | 值 |
|----|-----|
| MySQL | **8.0**（常用） |
| 字符集 | utf8mb4 / utf8mb4_unicode_ci |
| 主键 | `BIGINT AUTO_INCREMENT` |
| 外键约束 | **不建** `FOREIGN KEY`；`*_id` + 索引；应用层保证引用（ADR-0009） |
| 迁移 | **Alembic** |
| 时间戳 | `created_at` / `updated_at` 存 UTC `DATETIME` |
| 业务日 | `DATE`（用户时区日历日） |
| 软删 | 仅 `goals.deleted_at`；`day_entries` **保留历史** |
| Redis | **无**；列表不以缓存为准 |

### 1.1 今日 / 本周为何「落表」却不烧 Token（ADR-0009）

```text
DeepSeek  ——只在——→  「+」生成 / 完成日确认重排 / 周日 23:59 重排
                              ↓ 写入 MySQL
                     day_assignments（哪天做哪项）  ← 已落表
                     day_entries（完成/原因）       ← 已落表
                              ↓
首页每次打开 ——只做——→  SQL 按 plan_date 查询（不调 AI）
服务器重启  ——数据仍在——→  MySQL；无需 Redis
```

- **今日任务** = `day_assignments` where `plan_date = today`  
- **本周剩余** = `day_assignments` where `today < plan_date <= week_sunday`  
- 不另建 `today_cache` 表；`day_assignments` 本身就是持久化列表真相。

---

## 2. 表设计

> 文中 `→ users.id` 表示逻辑引用，**不建 FK CONSTRAINT**。

### 2.1 `users`

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| openid | VARCHAR(64) | UNIQUE NOT NULL | |
| unionid | VARCHAR(64) | NULL | |
| nickname | VARCHAR(64) | NULL | |
| avatar_url | VARCHAR(512) | NULL | |
| timezone | VARCHAR(64) | NOT NULL DEFAULT 'Asia/Shanghai' | |
| created_at / updated_at | DATETIME | NOT NULL | |

### 2.2 `goals`

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| user_id | BIGINT | NOT NULL，INDEX → users | |
| title | VARCHAR(200) | NOT NULL | 「+」名称 |
| note | TEXT | NULL | 备注（进 AI） |
| plan_start_date | DATE | NOT NULL | |
| plan_end_date | DATE | NOT NULL | ≥ start |
| status | VARCHAR(32) | NOT NULL | draft/planning/active/completed/cancelled |
| active_wbs_generation_id | BIGINT | NULL，INDEX → wbs_generations | |
| overall_progress_pct | TINYINT UNSIGNED | NOT NULL DEFAULT 0 | 23:59 回写 |
| created_at / updated_at | DATETIME | NOT NULL | |
| deleted_at | DATETIME | NULL | 软删 |

**索引**：`(user_id, status)`，`(status, plan_end_date)`

### 2.3 `wbs_generations`

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| goal_id | BIGINT | NOT NULL，INDEX | |
| user_id | BIGINT | NOT NULL，INDEX | |
| version | INT | NOT NULL | 同 goal 从 1 递增 |
| status | VARCHAR(32) | NOT NULL | suggested/active/superseded/failed |
| source | VARCHAR(32) | NOT NULL | ai/user/hybrid |
| llm_call_id | BIGINT | NULL | |
| raw_response | MEDIUMTEXT | NULL | |
| created_at | DATETIME | NOT NULL | |
| confirmed_at | DATETIME | NULL | |

**唯一**：`UNIQUE(goal_id, version)`  
同时仅一条 `status=active`（应用层事务保证）。

### 2.4 `task_nodes`

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| generation_id | BIGINT | NOT NULL，INDEX | |
| goal_id | BIGINT | NOT NULL，INDEX | |
| user_id | BIGINT | NOT NULL，INDEX | |
| parent_id | BIGINT | NULL，INDEX | milestone=NULL；task→milestone |
| kind | VARCHAR(16) | NOT NULL | milestone \| task |
| code | VARCHAR(32) | NOT NULL | 如 1.0 / 1.1 |
| title | VARCHAR(200) | NOT NULL | |
| description | TEXT | NULL | |
| sort_order | INT | NOT NULL DEFAULT 0 | |
| start_date | DATE | NULL* | *milestone **必填**（应用层）；task 建议落在父里程碑窗内 |
| end_date | DATE | NULL* | 同上 |
| progress_pct | TINYINT UNSIGNED | NOT NULL DEFAULT 0 | |
| depends_on_json | JSON | NULL | |
| created_at / updated_at | DATETIME | NOT NULL | |

**索引**：`(generation_id, parent_id)`，`(goal_id, kind)`  
无分钟/故事点列。

### 2.5 `day_assignments`（今日 + 本周剩余的落表真相）

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| goal_id | BIGINT | NOT NULL，INDEX | |
| user_id | BIGINT | NOT NULL，INDEX | |
| task_id | BIGINT | NOT NULL，INDEX → task_nodes | 仅 task |
| plan_date | DATE | NOT NULL | |
| source | VARCHAR(32) | NOT NULL | ai / defer / sunday_replan / deadline_replan |
| sort_order | INT | NOT NULL DEFAULT 0 | |
| created_at / updated_at | DATETIME | NOT NULL | |

**唯一**：  
- `UNIQUE(goal_id, task_id, plan_date)`  
- ~~`UNIQUE(goal_id, plan_date)`~~ — **已取消**（ADR-0015：顺延可叠到已有日，同 Goal 同日可多条）

> AI 初排仍宜一天一事；执行顺延后首页同一 Goal 可出现多条今日任务。

**索引**：`(goal_id, plan_date)`  

写入：AI 确认、周内顺延、周日重排、完成日变更重排（写入时须维持上述唯一约束）。  
读取：home / gantt —— **纯 SQL**。

### 2.5b `task_nodes` 数量约束（应用层）

每个 `(generation_id, milestone_id)` 下 **至少 1** 条 `kind=task`（ADR-0011，1:N）。  
Milestone 的 `start_date`/`end_date` 应用层 **NOT NULL**。

### 2.6 `day_entries`（执行结果，长期保留）

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| goal_id | BIGINT | NOT NULL，INDEX | |
| user_id | BIGINT | NOT NULL，INDEX | |
| task_id | BIGINT | NOT NULL，INDEX | |
| work_date | DATE | NOT NULL | |
| status | VARCHAR(16) | NOT NULL | pending / done / not_done |
| incomplete_reason | VARCHAR(500) | NULL | |
| created_at / updated_at | DATETIME | NOT NULL | |

**唯一**：`UNIQUE(task_id, work_date)`  
**索引**：`(goal_id, work_date, status)`

### 2.7 `deadline_changes`

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| goal_id / user_id | BIGINT | NOT NULL，INDEX | |
| old_end_date | DATE | NOT NULL | |
| new_end_date | DATE | NOT NULL | |
| status | VARCHAR(32) | NOT NULL | pending/confirmed/cancelled |
| job_id | BIGINT | NULL | |
| created_at / confirmed_at | DATETIME | | |

### 2.8 `llm_call_logs`

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| user_id / goal_id | BIGINT | NULL，INDEX | |
| purpose | VARCHAR(64) | NOT NULL | |
| model | VARCHAR(64) | NULL | |
| prompt_hash | VARCHAR(64) | NULL | |
| request_meta / response_meta | JSON | NULL | |
| status | VARCHAR(32) | NOT NULL | |
| error_message | TEXT | NULL | |
| created_at | DATETIME | NOT NULL | |

### 2.9 `jobs`

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| user_id / goal_id | BIGINT | NULL，INDEX | |
| type | VARCHAR(64) | NOT NULL | |
| status | VARCHAR(32) | NOT NULL | queued/running/succeeded/failed/dead |
| result_ref_json | JSON | NULL | |
| error_message | TEXT | NULL | |
| created_at / updated_at / finished_at | DATETIME | | |

### 2.10 `job_runs`

| 列 | 类型 | 约束 | 说明 |
|----|------|------|------|
| id | BIGINT | PK AI | |
| job_type | VARCHAR(64) | NOT NULL | |
| biz_key | VARCHAR(128) | NOT NULL | |
| status | VARCHAR(32) | NOT NULL | |
| attempts | INT | NOT NULL DEFAULT 0 | |
| locked_at / finished_at | DATETIME | NULL | |
| last_error | TEXT | NULL | |
| created_at | DATETIME | NOT NULL | |

**唯一**：`UNIQUE(job_type, biz_key)`

---

## 3. 不建的表

- `daily_plans` / `today_cache` / Redis 列表  
- `progress_reports`（由 `day_entries` 替代）  
- 分钟/故事点列  

---

## 4. Job 读写

| Job | 读 | 写 |
|-----|-----|-----|
| day_close 23:59 | assignments + entries | entries；progress_pct |
| intra_week_defer | not_done | **改 day_assignments** |
| sunday_replan 23:59 | 本周未完成 | **重写后续 day_assignments** |

---

## 5. 迁移

- **Alembic**；禁止无迁移改生产库。  
- 模型里 `ForeignKey(...)` 可写逻辑关系，但 migrate 时 **`use_alter`/不生成 CONSTRAINT**，或明确 `create_constraint=False`（实现时按项目惯例二选一，以「库上无 FK」为准）。
