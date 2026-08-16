# Spec 状态与实现顺序

## 已 Frozen（可开工）

| 文档 | 状态 |
|------|------|
| [02-requirements.md](./02-requirements.md) | Frozen |
| [03-domain-model.md](./03-domain-model.md) | Frozen |
| [04-user-journeys.md](./04-user-journeys.md) | Frozen |
| [05-api-contract.md](./05-api-contract.md) | Frozen |
| [06-data-model.md](./06-data-model.md) | Frozen |
| [07-ai-orchestration.md](./07-ai-orchestration.md) | Frozen |
| [08-jobs-and-notifications.md](./08-jobs-and-notifications.md) | Frozen |
| [09-acceptance.md](./09-acceptance.md) | Frozen |
| [schemas/](./schemas/) · [prompts/](./prompts/) | Frozen |
| ADR-0001 … [0016](./adr/0016-same-day-multi-task-all-done.md) | Accepted |
| 交互参考 | [`preview/home.html`](../../preview/home.html) |

## 可后补（不挡编码）

| 文档 | 说明 |
|------|------|
| [00-constitution.md](./00-constitution.md) | Python 版本号等 |
| [01-product-brief.md](./01-product-brief.md) | 成功指标数字 |
| [10-roadmap.md](./10-roadmap.md) | 个人日期 |

## 变更纪律

Frozen 后行为变更：先 ADR → 再改 Spec → 再改代码。

## 建议实现顺序

1. FastAPI + Alembic + 表（`06`）  
2. Auth JWT + Goals CRUD + Jobs 轮询  
3. Mock LLM → 生成确认 → `GET /home`  
4. today complete/incomplete + 顺延叠加  
5. 每天 23:59 `day_close`  
6. 真 DeepSeek  
