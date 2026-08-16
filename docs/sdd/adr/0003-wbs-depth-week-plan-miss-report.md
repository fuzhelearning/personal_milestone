# ADR-0003: 两层 WBS、周视图日计划、漏填与周内顺延

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户（产品）
- Related Specs: 02-requirements, 03-domain-model, 04-user-journeys, 05-api-contract, 07-ai-orchestration, 08-jobs-and-notifications

## Context

需冻结 WBS 深度、日计划展示跨度，以及用户漏填/未标明完成时的处理策略。

## Decision

### 1. WBS 固定两层

- 结构仅为：**里程碑（Milestone）→ 任务（Task）**。
- 不允许第三层及更深；AI 输出若超层则校验失败并修复/重试。
- `TaskNode.kind ∈ {milestone, task}`；`task` 的 parent 必须是 `milestone`；`milestone` 的 parent 为空（根下直接挂里程碑）。

### 2. 按「一个星期」展示（甘特切片，ADR-0007）

- 用户看到的是**一周甘特/格子**，不是另填一套厚「日计划表单」。
- 数据：任务起止条 + 每日打钩；查询按自然周聚合即可。
- 周边界：**周一 ~ 周日**；周日为周结算点。  
  `[ASSUMPTION: 周起始=周一]`

### 3. 漏填 / 未标明完成：先问用户，周内顺延，周日重排

当用户未按时提交日报，或条目未标明是否完成时：

1. **催办并让用户选择**：对该日（或未决条目）明确选择「已完成 / 未完成」。
2. **未完成，或仍未选择**：视为未完成；将对应任务在**本周剩余日子内顺延**（只改日计划分配，不改 WBS 总体排期，ADR-0001）。
3. **到周日仍未完成**：触发**重排**（对本周未完成量与后续周的日计划做更积极的调整；仍不改 WBS 总体排期，除非用户另走完成时间变更）。

定时任务需覆盖：日报催办、周内顺延补算、周日重排。

## Consequences

- Positive: 模型简单；用户有整周可见性；漏填不会立刻「大改」，周日才加重排。
- Negative: 周日重排可能一次变动较大；需定义「未选择」的截止时刻（建议：次日催办窗口结束仍未选 → 按未完成顺延）。
- Follow-up: `GET .../weekly-plans?week_start=`；JOB 增加周日重排类型。
