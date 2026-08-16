# ADR-0004: LLM 异步 job 轮询 + 云定时器调度

- Status: Accepted
- Date: 2026-08-02
- Deciders: 用户（产品/工程）
- Related Specs: 00-constitution, 02-requirements, 05-api-contract, 07-ai-orchestration, 08-jobs-and-notifications

## Context

DeepSeek 调用耗时长，微信小程序同步等待易超时；催办/周内顺延/周日重排需要可靠的到点触发，且不宜与 Web 进程强耦合。

## Decision

### 1. LLM / 重计划生成：异步 + job_id 轮询

适用于（至少）：

- 首次 WBS 生成
- 完成时间变更后的未来段 WBS 重排
- 需要调用 DeepSeek 的周日重排（及可选的周计划生成）

流程：

1. 客户端 `POST` 触发生成 → 立即 `202`（或 `200`）返回 `{ job_id, status: "queued" }`
2. 服务端后台执行（同进程 worker / 后台 task 均可，首期不强制独立队列中间件）
3. 客户端轮询 `GET /api/v1/jobs/{job_id}`（建议间隔 1–2s，带超时上限）
4. `succeeded` 后客户端再拉业务资源（WBS generation / weekly plans）
5. `failed` 返回可读错误；支持有限次重试策略见 AI Spec

**不做**：让小程序同步阻塞等待完整 LLM 响应作为主路径。

### 2. 调度：云定时器打内部接口

- 使用云厂商 / 系统 crontab 等**外部定时器**，到点 `POST /internal/jobs/{job_type}/run`（需签名或内网密钥）。
- 覆盖 JOB-001~004 等（补齐周计划、催办、周内顺延、周日重排）及 timeout sweeper（也可由定时器高频触发）。
- **DB 幂等**（`job_runs.biz_key`）防云定时器重试导致双跑。
- 本地开发可用手动 curl / 脚本触发同一 Internal API，不强制本机常驻 APScheduler。

**不做（首期）**：Celery/RQ+Redis 作为必选；进程内 APScheduler 作为生产主调度。

## Consequences

- Positive: 小程序不易超时；调度与 Web 进程解耦；组件少。
- Negative: 需实现 job 状态表与轮询接口；云定时器要配鉴权与监控。
- Follow-up: OpenAPI 补齐 jobs；部署文档写明各 Cron 与密钥注入。
