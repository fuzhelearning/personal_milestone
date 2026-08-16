# 03 — Domain Model

- Status: Frozen
- Owner: [TODO]
- Last Updated: 2026-08-02
- Related ADRs: ADR-0001 … ADR-0016

## 1. 术语表

| 中文 | 英文 | 定义 |
|------|------|------|
| 目标 | Goal | 用户用「+」创建的项目：名称、计划起止日、备注 |
| Structure / WBS | Structure | 两层：里程碑 → 任务，含进度% |
| 里程碑 | Milestone | WBS 第一层 |
| 任务 | Task | WBS 第二层；可出现在某日的今日/本周列表 |
| 日安排项 | DayAssignment | 「哪一天计划做哪个 Task」（AI 排出，可被顺延/重排改） |
| 日执行记录 | DayEntry | 用户对某日某 Task：完成 / 未完成+原因 |
| 今日任务 | TodayTasks | `DayAssignment` 中 date=今天 的项 + 执行态 |
| 本周剩余 | RestOfWeek | 本周内 date>今天 的 `DayAssignment` |
| 日终结算 | DayClose | 每天 **23:59**：结算未完成 + 回写进度 + 顺延/周日新计划 |
| 周内顺延 | IntraWeekDefer | 未完成改派到本周后续日（改 DayAssignment） |
| 周日重排 | SundayReplan | 每周日 **23:59** 重排后续日安排 |

> 「目标」≠「里程碑」：Goal 是项目容器；Milestone 是 WBS 节点。

## 2. 实体关系

```text
User
 └── Goal
      ├── WbsGeneration (版本；一份 active)
      │    └── TaskNode (milestone → task)
      ├── DayAssignment (goal + task + plan_date)  ← 哪天做哪项
      ├── DayEntry (goal + task + work_date)      ← 用户当天结果
      ├── DeadlineChange (pending/confirmed)
      └── Job / LlmCallLog
```

**今日 / 本周剩余不单独当厚实体**：由 `DayAssignment`（+ `DayEntry`）查询得出。

## 3. 状态机

### 3.1 Goal.status（首期，无 at_risk）

```text
draft → planning → active → completed
                 ↘ cancelled
active → completed
active → cancelled
```

| 状态 | 含义 |
|------|------|
| draft | 已用「+」创建；生成中或待确认（**尚无生效排期**） |
| planning | **已有任务/排期**，整体偏「计划中」（如未到开始日或部分任务日未到）——**不是**没生成 |
| active | 进行中 |
| completed | 全部完成或用户标记完成 |
| cancelled | 取消 |

> ADR-0015：`planning` 与 `active` 只要当日有 `day_assignment`，都进首页今日/本周列表。

### 3.2 TaskNode（进度态，非复杂工作流）

- 不强制 todo/doing/blocked 状态机。
- 以 `progress_pct`（0–100）与是否仍有未完成 `DayAssignment` 表达。
- `progress_pct == 100` 视为该任务完成。

### 3.3 DayEntry.status

```text
pending → done          # 用户勾选；勾选优先，忽略原因框内容
pending → not_done      # 未勾选且提交未完成原因；或日终 23:59 仍未处理
done → pending          # 用户取消勾选（可选）
not_done → done         # 用户补勾选，视为完成
```

**优先级**：`done`（点 checkbox）> 原因文本。  

**UI 约定（ADR-0007）**：原因区默认隐藏；**点任务行**才展开；**点 checkbox** 只切完成态（完成时展开区内控件置灰）。

### 3.4 Async Job.status

```text
queued → running → succeeded
running → failed → queued（有限次）
failed → dead
```

## 4. 关键规则（已拍板，ADR-0008）

### 4.1 进度计算（日期粒度，无分钟）

- 任务计划工作日数 = 该任务关联的 `DayAssignment` 日期数（或 start~end 内工作日，**以 DayAssignment 计数为准**）。
- 已完成日数 = `DayEntry.status=done` 且对应日曾属于该任务安排的天数。
- `task.progress_pct = round(已完成日数 / 计划工作日数 * 100)`；分母为 0 则 0。
- `milestone.progress_pct = round(平均(子任务 progress_pct))`。
- `goal` 总进度 = 所有 task 的简单平均（或所有 milestone 平均；首期：**所有 task 简单平均**）。
- **权威写入时刻**：每天 **23:59** DayClose。

### 4.2 「+」创建与 AI 排期

用户输入：

| 字段 | 必填 | 说明 |
|------|------|------|
| title | Y | 目标/任务名称 |
| plan_start_date | Y | 计划开始日 |
| plan_end_date | Y | 计划结束日（完成日）；须 ≥ start |
| note | N | 备注；内含用户对拆分/节奏的要求，进入 AI prompt |

系统：异步生成 **两层 WBS + 每一天的 DayAssignment** → 用户确认 → Goal=`planning` 或 `active`（已有排期；未到开始日可为 planning）。  
完成日/备注保存：只重排未来 **day_assignments**（ADR-0015）；今日不动。

### 4.3 未处理 = 未完成

某今日项在 **23:59 DayClose** 时仍为 `pending` → `not_done`；非周日顺延到明天，周日走新计划（ADR-0015）。

### 4.4 时钟（用户时区）

| 事件 | 时刻 |
|------|------|
| 日终结算 DayClose | 每天 **23:59**（回写进度 + 未完成处理；周日走「新计划」） |
| 周边界 | 周一 ~ 周日 |

### 4.5 不变量（摘要）

1. 每 Goal 仅一份 active `WbsGeneration`。
2. 层级 Goal→Milestone→Task；**每 Milestone ≥1 Task**；Milestone **必有** start/end（ADR-0011）。
3. 同一 Goal 同一 task 同一日至多 1 条 `day_assignment`；同 Goal 同日可多 task（ADR-0015）。甘特**里程碑×日**格：≤today 须该里程碑该日全部 done 才完成色；**>today = 未开始**（ADR-0016）。
4. `DayEntry` 唯一键见数据模型；用户隔离 `user_id`。
5. 完成日只能往后且 ≥ today+3；确认后不改今日安排（ADR-0002）。
6. 无故事点、无分钟估时。
7. 甘特全局：仅 `active|planning` Goal；当前里程碑条 + **全里程碑行**日期格（ADR-0011）。

### 4.6 「尚未发生」（完成日变更时）

冻结：已 `progress_pct=100`，或 `end_date < today`，或仅存在于今天及过去的安排且已结算。  
今日：今日任务列表不因完成日变更而改。  
可重排：未来日的 DayAssignment + 未完成任务的未来排期。

## 5. 模型选择题（结论）

| ID | 结论 |
|----|------|
| DM-1 存储 | parent_id 邻接表 |
| DM-2 日安排 | **DayAssignment 落库快照**（AI/重排写入） |
| DM-3 估时 | **不要分钟/故事点** |
| DM-4 多目标工时 | 不上 |
| DM-5 深度 | 两层；Milestone:Task=1:N；Milestone 有起止日 |
| DM-6 周 | 周一~周日 |
| DM-7 at_risk | 首期不做 |
| DM-8 进度 | 完成日数/安排日数；平均 |
| DM-9 甘特 | 全局；日格执行态按「同日全 done」聚合；today±30 居中（ADR-0016/0013） |
| DM-10 今日 | 首页合并全目标；勾选细节在今日任务 |
