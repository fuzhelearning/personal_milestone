# ADR-0005: 首期无 Redis、无订阅消息、BIGINT 自增主键

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户
- Related Specs: 00-constitution, 02-requirements, 05-api-contract, 06-data-model, 08-jobs-and-notifications

## Context

在 ADR-0004 已选定 MySQL 存 job、云定时器调度的前提下，需冻结缓存/队列、通知通道与主键策略，避免实现期摇摆。

## Decision

1. **Redis**：首期**不引入**。Job 状态、幂等、锁均用 MySQL（如 `job_runs`）。后续若有性能/分布式锁刚需再单独立项。
2. **微信订阅消息**：首期**不上**。催办与计划变更以**小程序内打开查看**（及可选站内待办/列表红点）为准；`REQ-F-050` 等订阅通道降为后续增强。
3. **主键**：业务表主键统一 **`BIGINT` 自增**（MySQL `BIGINT AUTO_INCREMENT`）。对外 JSON 可用数字或字符串序列化，但存储为自增整型。不在首期使用 UUID 主键。

## Consequences

- Positive: 依赖面更小；表关联与调试简单。
- Negative: 无 Redis 时并发锁能力偏弱（靠 DB 唯一键/行锁足够个人场景）；无订阅消息则触达弱，依赖用户主动打开。
- Follow-up: 前端轮询/进入小程序拉周计划与待办；主键在 OpenAPI 中类型与序列化约定写清。
