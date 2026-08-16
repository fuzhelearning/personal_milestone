# ADR-0002: 计划开始后完成时间只能顺延，且不早于 today+3

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户（产品）
- Related Specs: 00-constitution, 02-requirements, 03-domain-model, 04-user-journeys, 05-api-contract, 09-acceptance
- Related ADRs: ADR-0001
- Supersedes note: 已撤销「当前完成日 <= today+3 则整单锁定」；改为「只能往后、不能往回」

## Context

完成时间允许在确认后重排未来 WBS（ADR-0001）。需要防止把截止日往回拧紧，并保证「今天正在做的事」不被完成时间变更打乱；同时保留相对「今天」的最短缓冲，避免改到过近的日期。

## Decision

1. **适用条件**：Goal 已进入执行（`status = active`）。计划未开始时，本条不约束初始 deadline（另定）。
2. **只能往后，不能往回**：新完成日必须**严格晚于**当前生效完成日。  
   - `date(new_deadline, user_tz) > date(current_deadline, user_tz)`  
   - 往回改（提前截止）一律拒绝 → `DEADLINE_NOT_LATER`
3. **相对今天的下限**：新完成日不得早于 **今天 + 3 天**。  
   - `date(new_deadline, user_tz) >= date(today, user_tz) + 3 days`  
   - 例：今天 2026-08-02 → 新完成日至少 2026-08-05；`08-04` 及更早拒绝 → `DEADLINE_TOO_SOON`  
   - 与第 2 条同时满足：实际最早可选日 = `max(current_deadline_date + 1 day, today + 3 days)`
4. **今日任务不受影响**：确认重排后，**当日 DailyPlan 不变**；只重算明天及以后。
5. **校验时机**：提议与 confirm 均校验；confirm 以确认时刻的 today / current_deadline 为准。

### 示例（今天 = 2026-08-02）

| 当前完成日 | 试图改为 | 结果 |
|------------|----------|------|
| 08-10 | 08-12 | 允许（往后，且 ≥ 08-05） |
| 08-10 | 08-09 | 拒绝 `DEADLINE_NOT_LATER`（往回） |
| 08-10 | 08-04 | 拒绝（往回；亦触碰 today+3） |
| 08-05 | 08-08 | 允许（往后顺延） |
| 08-05 | 08-05 | 拒绝（未往后） |
| 08-03 | 08-04 | 拒绝 `DEADLINE_TOO_SOON`（虽往后但 < today+3） |
| 08-03 | 08-05 | 允许 |

## Alternatives Considered

| 方案 | 优点 | 缺点 | 为何未选 |
|------|------|------|----------|
| 贴 today+3 则整单锁定（含禁止顺延） | 简单 | 无法减压延期；误读产品意图 | **已撤回** |
| 允许往回改但不早于 today+3 | 灵活 | 会压缩已认可的排期窗口 | 产品：不能往回 |
| 连今日计划一并重排 | 全局一致 | 打断当天执行 | 今日不受影响 |

## Consequences

- Positive: 完成时间单调不减（日历日）；始终满足 today+3；当天执行不被打断。
- Negative: 订错了偏晚的 deadline 不能靠「往回改」纠正，只能靠执行或后续若支持的砍 scope。
- Follow-up: 错误码 `DEADLINE_NOT_LATER`、`DEADLINE_TOO_SOON`；前端最早可选 = `max(current+1, today+3)`。
