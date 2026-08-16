# 05 — API Contract（Backend ↔ Mini Program）

- Status: Frozen
- Owner: [TODO]
- Last Updated: 2026-08-02
- Related: `02` / `03` / `06`；ADR-0001…0016

## 1. 通用约定

| 项 | 约定 |
|----|------|
| Base URL | `[DEPLOY: 部署时填写]`，前缀 `/api/v1` |
| 协议 | HTTPS + `application/json` |
| 鉴权 | 微信 `code2session` → 签发 **JWT**；请求头 `Authorization: Bearer <access_token>` |
| 日期 | 业务日一律 `YYYY-MM-DD`，语义为**用户时区**日历日 |
| 时间戳 | ISO-8601（若出现） |
| ID | JSON 数字（BIGINT），非 UUID 字符串 |
| 幂等 | 写接口可选头 `Idempotency-Key` |
| 成功 | 除特别说明外 HTTP 200；异步创建用 **202** |
| 错误体 | `{ "code": "STRING", "message": "可读中文", "request_id": "...", "details": {} }` |

### 1.1 错误码

| code | HTTP | 含义 |
|------|------|------|
| UNAUTHORIZED | 401 | 未登录 / token 失效 |
| FORBIDDEN | 403 | 越权（非本人资源） |
| NOT_FOUND | 404 | 资源不存在（越权可统一 404） |
| VALIDATION_ERROR | 422 | 参数校验失败 |
| LLM_BUSY | 409 | 同 Goal 已有生成/重排 job 进行中 |
| LLM_FAILED | 502 | 模型失败（可重试生成） |
| RATE_LIMITED | 429 | 限流 |
| DEADLINE_TOO_SOON | 422 | 新完成日 < today+3 |
| DEADLINE_NOT_LATER | 422 | 新完成日未严格晚于当前 |
| GOAL_NOT_ACTIVE | 422 | 状态不允许该操作 |
| ENTRY_INVALID | 422 | 如未完成未填原因 |

### 1.2 公共对象

**User**

```json
{
  "id": 1,
  "nickname": "string|null",
  "avatar_url": "string|null",
  "timezone": "Asia/Shanghai"
}
```

**Job**

```json
{
  "job_id": 9,
  "type": "wbs_generate",
  "status": "queued|running|succeeded|failed|dead",
  "error": "string|null",
  "result_ref": { "generation_id": 3 },
  "created_at": "2026-08-02T10:00:00Z",
  "finished_at": "2026-08-02T10:00:45Z|null"
}
```

轮询：间隔 1–2s；建议客户端总等待 ≤ 120s。

**StructureNode**

```json
{
  "id": 2,
  "code": "1.1",
  "title": "string",
  "kind": "milestone|task",
  "parent_id": 1,
  "progress_pct": 80,
  "start_date": "2026-08-02",
  "end_date": "2026-08-10",
  "sort_order": 0
}
```

**TodayTaskItem**

```json
{
  "task_id": 2,
  "assignment_id": 15,
  "title": "string",
  "code": "1.1",
  "status": "pending|done|not_done",
  "incomplete_reason": "string|null"
}
```

**RestOfWeekDay**

```json
{
  "date": "2026-08-03",
  "weekday": "Monday",
  "items": [
    { "task_id": 3, "assignment_id": 16, "title": "string", "code": "1.2" }
  ]
}
```

---

## 2. Auth

### `POST /api/v1/auth/wechat/login`

- REQ: REQ-F-001
- Auth: 无
- Body:

```json
{ "code": "wx_login_code" }
```

- Resp 200:

```json
{
  "access_token": "jwt...",
  "token_type": "Bearer",
  "expires_in": 7200,
  "user": { "id": 1, "nickname": null, "avatar_url": null, "timezone": "Asia/Shanghai" }
}
```

---

## 3. Goals

### `POST /api/v1/goals`

- REQ: REQ-F-010 / REQ-F-020（首页「+」）
- Body:

```json
{
  "title": "Launch Folio Website",
  "plan_start_date": "2026-08-02",
  "plan_end_date": "2026-09-01",
  "note": "希望前两周偏设计，备注要求会进 prompt"
}
```

- 校验：`plan_end_date >= plan_start_date`；title 非空
- 行为：建 Goal=`draft`，入队 `wbs_generate`（生成 WBS + day_assignments，未确认前 generation=`suggested`）
- Resp **202**:

```json
{
  "goal_id": 1,
  "job_id": 9,
  "status": "draft"
}
```

### `GET /api/v1/goals`

- REQ: REQ-F-011
- Query：`page=1&page_size=20`（可选；默认不分页返回全部 active+planning）
- Resp 200:

```json
{
  "items": [
    {
      "id": 1,
      "title": "string",
      "status": "active",
      "plan_start_date": "2026-08-02",
      "plan_end_date": "2026-09-01",
      "overall_progress_pct": 75,
      "updated_at": "2026-08-02T12:00:00Z"
    }
  ]
}
```

### `GET /api/v1/goals/{goal_id}`

- Resp 200：单条详情，字段含 `note`、`active_wbs_generation_id` 等

### `PATCH /api/v1/goals/{goal_id}`

- 仅基础信息：`title`、`note`（可选）
- **不可**用此接口改 `plan_end_date`（走 deadline-change）

### `POST /api/v1/goals/{goal_id}/archive`

- REQ: REQ-F-013
- 软删 / status→`cancelled`（实现选一，推荐 status=`cancelled` + `deleted_at`）
- Resp 200：`{ "goal_id": 1, "status": "cancelled" }`

---

## 4. Jobs

### `GET /api/v1/jobs/{job_id}`

- REQ: REQ-F-020a
- 仅本人 job
- Resp 200：见 **Job** 对象

---

## 5. WBS Generation

### `GET /api/v1/goals/{goal_id}/wbs/generations/{generation_id}`

- job 成功后预览
- Resp 200:

```json
{
  "generation_id": 3,
  "status": "suggested",
  "version": 1,
  "structure": {
    "nodes": [ /* StructureNode[] 扁平两层，milestone 在前 */ ]
  },
  "day_assignments_preview": [
    { "date": "2026-08-02", "items": [{ "task_code": "1.1", "title": "..." }] }
  ]
}
```

### `POST /api/v1/goals/{goal_id}/wbs/generations/{generation_id}/confirm`

- REQ: REQ-F-022
- Body（可选微调，首期可空对象表示原样确认）:

```json
{
  "nodes": null,
  "day_assignments": null
}
```

- 行为：generation→`active`；写入/激活对应 `day_assignments`；Goal→`active`
- Resp 200：`{ "goal_id": 1, "generation_id": 3, "status": "planning|active" }`  
  - 若 `today < plan_start_date` → `planning`；否则 → `active`（ADR-0015）

### `POST /api/v1/goals/{goal_id}/wbs/generations`

- 显式重新生成（P1 可用；与「+」同类异步）
- Resp 202：`{ "generation_id": 4, "job_id": 10, "status": "queued" }`
- 进行中则 `LLM_BUSY`

### `GET /api/v1/goals/{goal_id}/structure`

- REQ: REQ-F-030（也可只用 home）
- Resp 200：

```json
{
  "overall_progress_pct": 75,
  "nodes": [ /* StructureNode[] */ ]
}
```

---

## 6. Home（主界面，ADR-0010 / ADR-0014）

### `GET /api/v1/home`

- REQ: REQ-F-029/030/040/040a  
- **不调 LLM**  
- Resp 200:

```json
{
  "today": {
    "date": "2026-08-02",
    "weekday": "Sunday",
    "display": "Sunday, August 2, 2026",
    "timezone": "Asia/Shanghai"
  },
  "structure": {
    "goals": [
      {
        "goal_id": 1,
        "title": "通过看书学会 agent",
        "status": "active",
        "overall_progress_pct": 35,
        "plan_end_date": "2026-09-05",
        "note": "前两周偏概念"
      },
      {
        "goal_id": 2,
        "title": "考研数学一轮",
        "status": "planning",
        "overall_progress_pct": 10,
        "plan_end_date": "2026-12-01",
        "note": null
      }
    ]
  },
  "today_tasks": [
    {
      "task_id": 22,
      "assignment_id": 15,
      "goal_id": 1,
      "goal_title": "通过看书学会 agent",
      "title": "看第三章",
      "milestone_code": "1.0",
      "milestone_title": "懂概念",
      "status": "pending",
      "incomplete_reason": null
    },
    {
      "task_id": 31,
      "assignment_id": 40,
      "goal_id": 2,
      "goal_title": "考研数学一轮",
      "title": "极限与连续",
      "milestone_code": "1.0",
      "milestone_title": "高数基础",
      "status": "pending",
      "incomplete_reason": null
    }
  ],
  "rest_of_week": [
    {
      "date": "2026-08-05",
      "weekday": "Tuesday",
      "items": [
        {
          "task_id": 23,
          "goal_id": 1,
          "goal_title": "通过看书学会 agent",
          "title": "做概念笔记",
          "milestone_code": "1.0"
        }
      ]
    }
  ],
  "rest_of_week_count": 3
}
```

- `structure.goals`：仅 `active|planning`  
- `today_tasks`：**数组**，合并所有目标；同 Goal 同日可多条；空=`[]`  
- `rest_of_week`：合并所有目标；前端**默认折叠**，用 `rest_of_week_count` 做摘要  
- 点 Structure 某 Goal → 编辑完成日/备注（见下）；点「查看甘特」→ `GET /api/v1/gantt`  
- ~~`selected_goal_id` / `select-goal`~~：废止（ADR-0014）

### `POST /api/v1/goals/{goal_id}/plan-edit`

- REQ: REQ-F-012 / REQ-F-030d（Structure 点目标保存）  
- Body:

```json
{
  "new_plan_end_date": "2026-10-01",
  "note": "多留一周做小程序联调"
}
```

- `new_plan_end_date`：若传入则按 **ADR-0002** 校验：  
  1. 必须 **严格晚于** 当前 `plan_end_date` → 否则 `DEADLINE_NOT_LATER`  
  2. 必须 **≥ today+3**（用户时区）→ 否则 `DEADLINE_TOO_SOON`  
  3. 前端日期控件 `min` = `max(current+1, today+3)`  
- `note`：可选；写入 Goal.note  
- 至少变更完成日或备注之一（仅改备注、完成日不变：仍可触发未来段重排）  
- 校验通过后**立刻**入队重排 job；**今日 assignments 不变**  
- Resp **202**:

```json
{
  "goal_id": 1,
  "job_id": 12,
  "status": "queued",
  "plan_end_date": "2026-10-01",
  "note": "多留一周做小程序联调",
  "earliest_allowed_date": "2026-08-05"
}
```

- 也可继续用 §8 `deadline-change` 两段式；首期小程序推荐本一体接口。  

### `GET /api/v1/gantt`（全局，ADR-0010 / ADR-0011 / ADR-0013）

- REQ: REQ-F-030a/030b  
- Query：`from` / `to`（可选）；`goal_id`（可选，仅筛展示）  
- **缺省窗口（ADR-0013）**：`from = today-30`，`to = today+30`（用户时区；含今天共 61 日）  
- 仅返回用户下 Goal.status ∈ **`{active, planning}`**  
- **不调 LLM**  
- Resp 200:

```json
{
  "from": "2026-07-04",
  "to": "2026-09-02",
  "today": "2026-08-03",
  "dates": ["2026-07-04", "…", "2026-08-03", "…", "2026-09-02"],
  "goals": [
    {
      "goal_id": 1,
      "title": "通过看书学会 agent",
      "status": "active",
      "overall_progress_pct": 35,
      "current_milestone": {
        "milestone_id": 11,
        "code": "1.0",
        "title": "懂概念",
        "start_date": "2026-08-01",
        "end_date": "2026-08-10"
      },
      "milestones": [
        {
          "milestone_id": 11,
          "code": "1.0",
          "title": "懂概念",
          "start_date": "2026-08-01",
          "end_date": "2026-08-10",
          "is_current": true,
          "cells": [
            {
              "date": "2026-08-02",
              "planned": true,
              "status": "done",
              "task_ids": [21]
            },
            {
              "date": "2026-08-03",
              "planned": true,
              "status": "not_done",
              "task_ids": [21, 22]
            }
          ]
        },
        {
          "milestone_id": 12,
          "code": "2.0",
          "title": "能使用",
          "start_date": "2026-08-11",
          "end_date": "2026-08-20",
          "is_current": false,
          "cells": [
            {
              "date": "2026-08-11",
              "planned": true,
              "status": "pending",
              "task_ids": [31]
            }
          ]
        }
      ]
    }
  ]
}
```

- 前端：Goal → 当前里程碑横幅；每里程碑一行格；行上不写死任务名  
- 格语义（ADR-0016），**仅该里程碑 × 该日** 的 `task_ids`：  
  - 无安排 → 空  
  - **date > today** 有安排 → `pending`（**未开始**，非未完成橙）  
  - **date ≤ today** 且全部 done → `done`  
  - **date ≤ today** 且未全 done → `not_done`（未完成色）  
- 进入页：以 `today` 列居中（ADR-0013）  

---

## 7. 今日任务操作

### 今日任务 UI 与 API 映射（ADR-0007）

| UI | API |
|----|-----|
| 点 checkbox → 勾选 | `POST .../complete` |
| 点 checkbox → 取消勾选 | `POST .../complete` 的逆操作：可用 `DELETE .../complete` 或 `POST .../uncomplete`（首期实现选一，推荐 `POST .../uncomplete` 空 body） |
| 点任务行 | **纯前端**展开/收起，无 API |
| 展开区点提交 | `POST .../incomplete` |

### `POST /api/v1/goals/{goal_id}/today-tasks/{task_id}/complete`

- REQ: REQ-F-031（对应 **checkbox**，不是点任务行）
- 语义：`day_entry` → **`done`**；忽略任何已填原因
- 须存在今日 `day_assignment`；幂等
- Resp 200: `{ "task_id": 2, "work_date": "2026-08-02", "status": "done" }`
- **不**立即改 Structure 权威 `progress_pct`（23:59 day_close 回写）

### `POST /api/v1/goals/{goal_id}/today-tasks/{task_id}/uncomplete`

- REQ: REQ-F-031
- 语义：取消勾选 → `pending`（或清除 done）；可再次展开填原因
- Resp 200: `{ "task_id": 2, "work_date": "2026-08-02", "status": "pending" }`

### `POST /api/v1/goals/{goal_id}/today-tasks/{task_id}/incomplete`

- REQ: REQ-F-032 / REQ-F-031a
- Body: `{ "incomplete_reason": "对接同事请假，改明天继续" }`
- 前置：当前不得为已勾选完成的权威态；若服务端已是 `done`，返回 `422 ENTRY_INVALID`（提示先取消勾选，或直接忽略——**推荐拒绝 incomplete**）
- `incomplete_reason` 必填非空
- 行为：`day_entry`→`not_done`；触发周内顺延
- Resp 200: `{ "task_id": 2, "work_date": "2026-08-02", "status": "not_done", "incomplete_reason": "...", "defer_job_id": 11 }`

---

## 8. 完成日变更

日期字段与 Goal 对齐，使用 **`new_plan_end_date`**（`YYYY-MM-DD`）。

### `POST /api/v1/goals/{goal_id}/deadline-change`

- REQ: REQ-F-012a/012c
- Body: `{ "new_plan_end_date": "2026-10-01" }`
- 校验顺序：
  1. `new <= current plan_end_date` → `DEADLINE_NOT_LATER`
  2. `new < today + 3` → `DEADLINE_TOO_SOON`
- Resp 200:

```json
{
  "change_id": 5,
  "status": "pending",
  "current_plan_end_date": "2026-09-01",
  "new_plan_end_date": "2026-10-01",
  "earliest_allowed_date": "2026-08-05"
}
```

### `POST /api/v1/goals/{goal_id}/deadline-change/{change_id}/confirm`

- REQ: REQ-F-012b
- Resp **202**: `{ "change_id": 5, "job_id": 12, "status": "queued" }`
- 成功后：重排未来 `day_assignments`（首期不改 WBS 节点起止）；**今日 assignments 不变**

### `POST /api/v1/goals/{goal_id}/deadline-change/{change_id}/cancel`

- Resp 200：`{ "change_id": 5, "status": "cancelled" }`

---

## 9. Internal Jobs（云定时器）

- 前缀：`/internal/jobs/...`
- 鉴权：请求头 `X-Internal-Token: <共享密钥>`（或等价 HMAC）；**禁止**小程序调用
- Body 可选：`{ "as_of": "2026-08-02T15:30:00+08:00" }`
- 幂等：依赖 `job_runs(job_type, biz_key)`

| 方法 | 路径 | Cron（用户时区语义） | 说明 |
|------|------|----------------------|------|
| POST | `/internal/jobs/day-close/run` | **每天 23:59** | 结算+回写进度；非周日→顺延次日；周日→新计划（ADR-0015） |
| POST | `/internal/jobs/report-reminder/run` | 可选晚间 | 刷新站内催办态 |
| POST | `/internal/jobs/llm-timeout-sweep/run` | 每 5–10 分钟 | 超时 job→failed |

Resp 200 示例：`{ "accepted": true, "processed": 3, "skipped": 1 }`

---

## 10. 小程序调用顺序（对照）

```text
登录 → POST /auth/wechat/login
「+」→ POST /goals → 轮询 GET /jobs/{id}
     → GET .../wbs/generations/{id} → POST .../confirm
首页 → GET .../home
打钩 → POST .../today-tasks/{id}/complete
未完成 → POST .../today-tasks/{id}/incomplete
（次日）GET .../home 看 Structure%（经 23:59 day_close）
```

---

## 11. 契约规则

1. 字段重命名/删除 = Breaking → `/api/v2` 或兼容窗口  
2. 新增可选字段 = Non-breaking  
3. 行为冲突时：以 **Frozen Spec + 最新 ADR** 为准；产品变更须先改 ADR/Spec  

4. 已废弃：旧 `PUT .../reports`、厚 DailyPlan 接口——**不要实现**
