# ADR-0010: 甘特层级与数量约束（Goal → Milestone → Task）

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户
- Related Specs: 02, 03, 05, 06, 07；OPEN-QUESTIONS（已关闭）

## Decision

统一层级：**目标 (Goal) → 里程碑 (Milestone) → 任务 (Task)**。

| # | 结论 |
|---|------|
| 1 | **甘特页全局**：列出用户所有非已完成 Goal |
| 2 | **日期格挂在里程碑行**；UI 必须呈现 Goal → 其下 Milestone 的层级（先 Goal，点开/展开见里程碑+格子） |
| 3 | ~~一个里程碑下只安排一个任务（1:1）~~ → **已由 [ADR-0011](./0011-milestone-window-and-current-focus.md) 废止**：Milestone:Task=1:N；里程碑有起止日；甘特上方展示当前里程碑 |
| 4 | **首页 Structure = 多目标列表**（未完成 Goal 的名称与总进度等） |
| 5 | 「非已完成」= Goal.status ∈ **`{active, planning}`** |
| 6 | AI **初排**宜一 Goal 一天 1 条；**执行顺延可同日多条**（[ADR-0015](./0015-eod-2359-planning-semantics.md)）。首页合并多目标 / 点 Structure=改完成日备注 → [ADR-0014](./0014-home-all-goals-tasks-structure-edit.md) |

### 衍生约束

- （#3 衍生见 ADR-0011）  
- 首页交互以 **ADR-0014** 为准（任务合并全目标；点 Goal=编辑完成日/备注）。  

## Consequences

- 全局甘特 + 一目标一日一事仍有效。  
- Milestone 数量关系与「当前里程碑」展示以 **ADR-0011** 为准。  
