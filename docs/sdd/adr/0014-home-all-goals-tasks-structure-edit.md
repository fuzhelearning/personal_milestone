# ADR-0014: 首页任务合并全目标；Structure 点目标=改完成日/备注并重排

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户
- Related Specs: 02, 04, 05, 08, 09；ADR-0001/0002
- Supersedes: ADR-0010 中「今日任务仅当前选中 Goal」「点 Structure 选中当前 Goal」；废止 `POST /home/select-goal` 作为首页主路径

## Context

首页曾用 Structure 选中「当前目标」再联动今日/本周任务，与「一眼看清所有目标今天干什么」冲突。  
点 Structure 目标的正确意图是：**改该目标的计划完成时间与备注**，保存后按既有规则立刻重排（非筛选今日列表）。

## Decision

### 1. 今日任务 / 本周剩余：合并所有目标

- `GET /home` 的今日区、本周剩余区展示用户下 **全部** `active|planning` Goal 的安排（跨目标列表）。  
- 每条须带 `goal_id` / `goal_title`（及可选 milestone）以便区分。  
- AI 初排宜一天一事；**顺延后**同 Goal 同日可多条（ADR-0015）。  

- **不再**用「选中 Goal」过滤首页任务。

### 2. 本周剩余：默认收起

- 「本周剩余」卡片**默认折叠**；点击标题/卡片才展开；再点收起。  
- 折叠时可显示一行摘要（如「本周还有 N 项」）。

### 3. 点 Structure 某目标 → 编辑计划完成日 + 备注

- 点击 Structure 列表中的某个 Goal → 打开编辑面板（非选中、非进甘特）。  
- 可改：`plan_end_date`（计划完成时间）、`note`（备注）。  
- 用户点**保存**即确认：校验通过后**立刻**入队重排 job（异步）；UI 可轮询 `job_id`。  
- 进甘特：仍走卡片底部「查看全局甘特图」入口（非整行 Goal）。

### 4. 保存后重排规则（复用 ADR-0001 / ADR-0002，不另开例外）

| 规则 | 说明 |
|------|------|
| 完成日只能往后 | `new_plan_end_date > current`；否则 `DEADLINE_NOT_LATER` |
| 不早于 today+3 | `new >= today+3`；否则 `DEADLINE_TOO_SOON` |
| 今日不动 | **今天**的 `day_assignments` 不变 |
| 只动未来日安排 | 重排 **明天及以后** `day_assignments`；**不改** WBS 节点起止（ADR-0015） |
| 备注进 AI | 仅改备注也要重排；见 ADR-0015 |
| 禁止砍 scope | 不得删除已确认 milestone/task（ADR-0006） |
| 可建议再改期 | AI 可返回 `suggested_deadline_change`，不得自动再改 |
| 默认完成日 | 编辑面板默认跳到最早可选日（无「延误」产品概念） |

## Consequences

- 废止首页 `select-goal` / `selected_goal_id` 主路径。  
- Home：`today_tasks[]`（多目标）+ `rest_of_week`（多目标，默认折叠）。  
- Structure 行点击 → `POST .../plan-edit`（一体保存；亦可兼容 deadline-change 两段式）。  

