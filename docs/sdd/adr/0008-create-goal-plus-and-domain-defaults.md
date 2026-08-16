# ADR-0008: 「+」创建目标触发生成排期，及领域默认规则

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户
- Related Specs: 02-requirements, 03-domain-model, 06-data-model, 04-user-journeys, 05-api-contract, 07-ai-orchestration, 08-jobs-and-notifications

## Decision

1. **进度**：任务 `progress_pct` = 已完成计划日数 / 计划工作日数（日期粒度，无分钟）；里程碑 = 子任务进度简单平均；目标总进度 = 里程碑平均或任务加权——首期用**子任务简单平均**亦可，见 domain-model。
2. **创建入口**：首页右上角日期旁 **「+」**。用户填写：目标/任务名称、计划开始日、计划结束日、备注；据此调用 AI **生成两层 WBS，并直接排出「哪天做哪几项」**（今日任务 / 本周剩余的数据源）。确认后生效；若属重生成/调整，则对 WBS 与每日安排一并重新排期（遵守 ADR-0001/0002：已发生与今日隔离等）。
3. **未处理 / 日终**：见 **ADR-0015** —— 每天 **23:59** `day_close`（非周日顺延次日；周日新计划）。
4. ~~单独周日任务~~ → 并入每天 23:59 的周日分支。
5. **粒度**：不要故事点；**不要精确到分钟**（仅日期）。
6. **Goal.at_risk**：首期不做。

## Consequences

- AI 输出必须含按日任务分配，不仅是树结构。
- 表结构以日期为主键语义；无 `estimate_minutes` 必填。
