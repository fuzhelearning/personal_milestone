# 08 — Jobs & Notifications

- Status: Frozen
- Owner: [TODO]
- Last Updated: 2026-08-02
- Related: ADR-0004/0005/0008/0009/0015；`05` Internal API

## 1. 调度方式

- **生产**：云定时器 → `POST /internal/jobs/{name}/run`  
- 头：`X-Internal-Token: <SHARED_SECRET>`  
- **幂等**：`job_runs` 唯一键 `(job_type, biz_key)`  
- **无 Redis**

时区：按每个 `users.timezone` 解释「今天 / 23:59 / 是否周日」。  
推荐：定时器高频触发，服务端扫「当地 23:59 已到且未跑」的用户。

## 2. Job 清单

| Job | Internal 路径 | 何时 | 做什么 | P |
|-----|---------------|------|--------|---|
| day_close | `/internal/jobs/day-close/run` | 用户时区 **每天 23:59** | 见 §2.1（合并原 23:30 回写 + 顺延/周日重排） | P0 |
| report_reminder | `/internal/jobs/report-reminder/run` | 每天 **21:00**（可选） | 站内提醒态 | P1 |
| llm_timeout_sweep | `/internal/jobs/llm-timeout-sweep/run` | 每 **5** 分钟 | running 超时 → failed | P0 |

> 今日/本周任务来自已落库 `day_assignments`，无需 `ensure_today_tasks`。

### 2.1 day_close（每天 23:59）— ADR-0015

对每个 Goal（`planning|active` 且有生效排期）：

1. **结算当日**：今日 assignment 仍无 entry 或 `pending` → `not_done`（默认原因「超时未反馈」）  
2. **回写进度**：按领域规则更新 task/milestone/goal `progress_pct`  
3. **分支**：  
   - **非周日**：每个当日 `not_done` → **顺延到下一天并叠加**（`source=defer`；不挤掉明日原有任务）  
   - **周日**：对积压/后续做 **新计划**（AI `sunday_replan` + 规则兜底），重写**明天及以后** assignments；**不改**当日已有 assignments；**不改** WBS 节点起止（首期）  
4. `biz_key = day_close:{goal_id}:{today}`  

用户主动 `incomplete`：可立即触发「顺延到下一天」，不必等 23:59。

### 2.2 llm_timeout_sweep

- `jobs.status=running AND updated_at < now-90s` → `failed`

## 3. 与用户 API 异步 Job

| 来源 | 轮询 |
|------|------|
| `POST /goals`、regenerate、`plan-edit` | `GET /api/v1/jobs/{id}` |

## 4. 通知

| 通道 | 首期 |
|------|------|
| 订阅消息 | **不做** |
| 站内 | `GET /home` 的 `today_tasks[]` + Structure；本周默认折叠 |

## 5. 部署检查清单

- [ ] `INTERNAL_TOKEN` / `DEEPSEEK_*` / `JWT_*`  
- [ ] 云定时指向 **day-close**、llm-timeout-sweep  
- [ ] 幂等：同一 `day_close` biz_key 不双写  
- [ ] 时区：用户当地 23:59 才结算  
