# ADR-0001: 按触发源区分 WBS 变更与日计划变更

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户（产品）
- Related Specs: 00-constitution, 02-requirements, 03-domain-model, 04-user-journeys, 05-api-contract, 07-ai-orchestration

## Context

需要明确：AI/系统调整后，哪些必须经用户确认才生效，以及何种情况下允许改动 WBS 总体排期。

## Decision

采用**按触发源分流**的策略，而不是「所有计划一律确认」或「一律自动生效」。

### 触发 A — 用户调整计划完成时间（deadline / 目标完成时间）

1. 前端发起变更后，须由用户调用**确认接口**才进入重规划。
2. 确认后：仅对 **尚未发生** 的 WBS 排期进行变更（已发生/已完成部分冻结）。
3. 同步触发**日计划**变更：重算**明天及以后**；**今日日计划不受影响**（详见 ADR-0002 的 today+3 下限）。

### 触发 B — 用户提交某日执行情况（未完成 / 少完成等）

1. 通过执行反馈提交接口即可生效，**不再**为日计划单独走确认。
2. 系统据此调整**日计划**（例如把未完成量滚入后续日安排）。
3. **WBS 总体排期不变**（里程碑目标日、任务计划窗等排期字段不因反馈重算）。

### 补充（与初建一致）

- 目标首次生成 WBS：仍须用户确认后生效（见 Journey A / REQ-F-022）。

## Alternatives Considered

| 方案 | 优点 | 缺点 | 为何未选 |
|------|------|------|----------|
| 一切 AI 输出都需确认 | 最安全 | 日报后还要点确认，摩擦大 | 与「提交即驱动次日安排」冲突 |
| 一切自动生效 | 省事 | deadline 大改会 silently 改写用户已认可的 WBS | 风险过高 |
| 反馈也改 WBS 排期 | 更能追截止 | 排期频繁抖动，用户难建立稳定预期 | 产品明确要求排期稳定 |

## Consequences

- Positive: 截止变更有明确闸门；日常偏差只动「今天/后续几天干什么」，不改大计划骨架。
- Negative / Trade-offs: 长期落后时 WBS 排期可能与真实进度脱节，需靠风险状态 / 建议改期（P1）补救。
- Follow-up Spec updates: 已回填 constitution、requirements、journeys、API、AI orchestration、DISCUSSION。
