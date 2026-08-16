# ADR-0007: 首页双区 — Structure + 今日任务；checkbox / 任务行点击分离

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户（以原型为准）
- Related Specs: 02-requirements, 03-domain-model, 04-user-journeys, 05-api-contract, 09-acceptance

## Context

首页「今日任务」需区分两种点击，避免「始终展示原因框」与「点开才显示」混淆。

## Decision

### 页面结构

1. 页头：今日日期 +「+」  
2. **Structure 摘要**（首页）：**多目标列表**；点某 Goal → 改完成日/备注并重排（[ADR-0014](./0014-home-all-goals-tasks-structure-edit.md)）；底部入口进甘特  
2b. **今日 / 本周**：合并所有目标任务；本周剩余**默认折叠**（ADR-0014）  

3. **甘特图页**（[ADR-0010](./0010-gantt-hierarchy-and-cardinality.md) / [ADR-0011](./0011-milestone-window-and-current-focus.md)）：  
   - **全局**列出 Goal.status ∈ `{active, planning}`  
   - **点击目标** → 展开；**上方**当前里程碑条；**主表每个里程碑一行**日期格（AI 全貌）  
   - 日期格：执行态填色；同日多任务须全 done 才不算未完成色（[ADR-0016](./0016-same-day-multi-task-all-done.md)）；细操作在今日任务区  
   - 数据：`goals` + `task_nodes` + `day_assignments` + `day_entries`  

4. 今日任务：`not_done` **始终展示「未完成」状态标**（原因区收起时也可见）  
5. 本周剩余：只读预览  
6. 进度权威回写：**每天 23:59**  

### 今日任务交互（必须区分）

| 用户动作 | 命中区域 | UI | 业务 |
|----------|----------|-----|------|
| **点 checkbox（方框）** | 左侧勾选框 | 切换勾选态；若当前已展开原因区且变为已完成 → 原因框**置灰禁用** | **`done` / 取消 done**；勾选为完成时**忽略**原因文本，不触发顺延 |
| **点任务（标题行，不含 checkbox）** | 任务名称所在行 | **展开 / 收起**「未完成原因」+「提交」；**默认收起**，非始终展示 | 仅 UI；不改变完成态 |
| **在展开区点「提交」** | 提交按钮 | — | 仅当**未勾选**时有效：`not_done` + 原因必填 → 周内顺延；若已勾选则按钮禁用/拒绝 |

**优先级**：checkbox 完成态 > 原因文本。已 `done` 时原因不参与判定。

### 明确否定

- ~~原因框始终展示~~（曾误写入 Spec，已纠正）  
- 点任务行 ≠ 完成任务  
- 点 checkbox ≠ 展开原因框  

## Consequences

- 前端事件需 `stopPropagation`，避免点 checkbox 冒泡成「展开」。  
- API：`complete` / `incomplete` 分离；`incomplete` 在已 `done` 时拒绝。  
