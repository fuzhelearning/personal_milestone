# ADR-0011: 里程碑时间窗 + 当前里程碑聚焦（修正 ADR-0010 #3）

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户
- Related Specs: 02, 03, 05, 06, 07；supersedes ADR-0010 §Decision #3 及「每里程碑恰好 1 task」衍生约束
- Supersedes: ADR-0010 中「Milestone : Task = 1:1」

## Context

用户举例：目标「通过看书学会 agent」→ 里程碑「懂概念 / 能使用 / 做出完整小程序」。  
「懂概念」下按日拆任务：第一天看一二章、第二天看三章……  
因此：

- 里程碑是**阶段**，须有 **start_date / end_date**；
- 一里程碑下可有**多个**按日任务；
- 「当前时刻」执行上可有多条（顺延叠加，ADR-0015）；AI 初排仍宜一天一事；不是结构上 Milestone:Task=1:1；
- 甘特须展示 AI 排出的**全貌**：每个里程碑一行日期格；表格上方另标**当前里程碑**；行上**不预写**各 task 标题。

## Decision

| # | 结论 |
|---|------|
| 1 | **保留** ADR-0010：全局甘特、格挂里程碑、Structure 多目标、active+planning；同日条数见 ADR-0015 |
| 2 | **废止** Milestone:Task=1:1。Milestone : Task = **1:N**（N≥1）；任务落在所属里程碑的起止日内 |
| 3 | 每个 Milestone **必须**有 `start_date`、`end_date`（∈ Goal 计划区间；建议阶段互不重叠或仅在边界相接） |
| 4 | **当前里程碑**（展示条）：today ∈ `[start,end]`；否则下一即将开始 / 最后一个；进入新里程碑开始日后横幅切换 |
| 5 | **甘特主表**：**每一个里程碑各一行**日期格（全貌）；行标签=里程碑 code+title+起止，**不**挂任务名 |
| 6 | 日期格语义：见 **[ADR-0016](./0016-same-day-multi-task-all-done.md)**（里程碑×日；≤today 全 done / 未完成；>today 未开始） |
| 7 | **周维度重排**（既有 ADR-0003，不改）：周内未完成 → 顺延；**周日 23:59** 仍积压 → 重排**后续日 `day_assignments`**（首期**不改**里程碑/任务 WBS 节点，除非用户走完成日变更） |

### AI / 数据

- WBS：`milestones[].tasks` 为 **1–N**；`day_assignments` 仍 **同一 date 至多 1 个 task**。  
- 今日任务标题来自当日 assignment，不写在里程碑行上。

## Consequences

- Schema/Prompt：`tasks` 为 1–N。  
- API/预览：`milestones[].cells` 全量行 + `current_milestone` 横幅。  
- ADR-0010 其余条款仍有效。  

