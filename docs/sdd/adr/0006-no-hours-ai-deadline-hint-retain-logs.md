# ADR-0006: 暂不上工时冲突、AI 可建议改期不可砍 scope、保留执行记录且无导入导出

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户
- Related Specs: 01-product-brief, 02-requirements, 07-ai-orchestration, 06-data-model

## Decision

1. **多目标同日工时冲突**：首期**不上**工时配额/抢占逻辑。不做跨 Goal 的每日可用分钟分配。单 Goal 内仍可保留「每日可用分钟」作为排计划约束（若已有），但不做多目标争抢。
2. **AI 建议边界**：
   - **允许**建议修改 deadline（仅提示 / `suggested_deadline_change`；真正改期仍走用户确认的 Journey D + ADR-0002）。
   - **禁止**建议或执行「砍 scope」（不得删除/合并掉用户已确认 WBS 中的里程碑或任务作为自动策略）。
3. **数据保留与导入导出**：
   - **保留**每日「干了什么」的执行记录（ProgressReport 及必要审计），作为核心数据长期留存（首期不做自动过期删除）。
   - **不做**导入/导出功能（无 Excel/日历订阅/批量导入等）。

## Consequences

- Positive: 范围更小；执行历史可复盘；AI 不可擅自削需求。
- Negative: 多 Goal 并行时需用户自行协调时间；订错 scope 只能人工改 WBS（若后续开放编辑）。
