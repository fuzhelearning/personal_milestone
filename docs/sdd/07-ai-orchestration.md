# 07 — AI Orchestration (DeepSeek)

- Status: Frozen
- Owner: [TODO]
- Last Updated: 2026-08-02
- Related ADRs: ADR-0001…0016
- Artifacts: [schemas/](./schemas/) · [prompts/](./prompts/)

## 1. 目标与原则

| Use Case | 触发 | 改 task_nodes 排期 | 改 day_assignments | 用户确认 |
|----------|------|--------------------|--------------------|----------|
| A. 首次/重新生成 | `POST /goals` 或 regenerate | 是（新 generation） | 是（全量建议） | **要** confirm |
| A2. 完成日变更 | deadline-change confirm | 仅未来段 | 仅 **tomorrow+** | confirm 已做过 |
| B1. 顺延到下一天 | incomplete 提交 / 非周日 23:59 | **否** | 是（→明天） | 否 |
| B2. 周日新计划 | 周日 23:59（day_close 分支） | **否**（首期） | 是（后续日） | 否 |
| A3. 备注/完成日 | plan-edit 保存 | **否**（首期） | 是（tomorrow+） | 保存即确认 |

原则：

1. 模型出 JSON 建议；系统做 Schema 校验、权限、落库、幂等、降级。  
2. **禁止砍 scope**（不得删除已确认 task/milestone）。  
3. 可建议 `suggested_deadline_change`，**不得**自动改 Goal 结束日。  
4. **无分钟 / 无故事点**。  
5. API 只返回 `job_id`（ADR-0004）；首页读库**不调** AI（ADR-0009）。  
6. **AI 主路径 + 规则兜底**（B1 默认可纯规则；B2/A/A2 失败走规则）。

## 2. 调用拓扑

```text
API 入队 job=queued
  → Runner
  → Context Builder（DB）
  → Prompt（prompts/*.v1.md）
  → DeepSeek（timeout 60s，最多 2 次网络重试）
  → JSON Schema 校验（失败 repair 最多 2 次）
  → Normalizer（code→id、夹逼日期）
  → 写 suggested generation / assignments + llm_call_logs
  → job=succeeded|failed
```

配置：`DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` 仅服务端。

## 3. Use Case A — WBS + 按日安排

### 3.1 输入

- `title`, `plan_start_date`, `plan_end_date`, `note`
- Prompt：`prompts/wbs_generate.v1.md`（中文）

### 3.2 输出

- Schema：`schemas/wbs_generate.schema.json`
- 必须含 `milestones[].tasks[]` + `day_assignments[]`

### 3.3 系统校验（通过才 succeeded）

| 规则 | 说明 |
|------|------|
| 两层 | Goal→Milestone→Task；无更深嵌套 |
| 数量 | milestone 1–20；**每里程碑 1–N task**（ADR-0011） |
| 里程碑窗 | 每 milestone 必须 start/end；任务日 ∈ 所属里程碑窗；阶段宜顺序相接 |
| 日安排 | 同一日期同一 Goal 至多安排 1 个 task（反映到 day_assignments） |
| 日期 | 节点/安排日 ∈ [plan_start, plan_end]；end ≥ start |
| 引用 | `day_assignments.task_codes` ⊆ 已输出 task codes |
| 标题 | 非空 |
| 覆盖 | `day_assignments` 至少覆盖 start～end 内 **≥50%** 日历日，或明确跳过周末且工作日覆盖 ≥80%（实现选一，推荐：工作日覆盖率 ≥80%） |
| 禁字段 | 出现 minutes/story 等 → 剥离或失败 |

### 3.4 失败

| 情况 | 策略 |
|------|------|
| 超时/5xx | 网络重试 ≤2 |
| JSON/Schema 失败 | repair prompt ≤2，再 failed |
| failed | Goal 保持 `draft`；用户可改 note 重试 |

确认后：`task_nodes` + `day_assignments` 落库（source=`ai`）。

## 4. Use Case A2 — 完成日变更重排

- 触发：confirm deadline-change  
- 输入：active nodes、冻结集合、今日 assignments（只读）、新 `plan_end_date`、未完成任务  
- 输出：可用 **A 的 schema**（未来段）或 B 的 assignments schema + 节点日期补丁；实现首选：**先规则平移未来 assignments，再可选 AI 润色**  
- **禁止**改 `plan_date == today` 的 assignments；禁止改冻结节点历史  

## 5. Use Case B1 — 顺延到下一天（规则，可不调 AI）

触发：`incomplete` 提交，或 **非周日** `day_close`（23:59）结算后。

规则（ADR-0015）：

1. 整项未完成 → 在 **tomorrow** **新增**一条 `day_assignment`（`source=defer`）。  
2. 若明天已有别的 task：**直接叠加**，不影响原任务（同 Goal 同日可多条）。  
3. **不改** `task_nodes.start/end`。

## 6. Use Case B2 — 周日新计划

- 触发：周日 **23:59** `day_close` 分支  
- Prompt：`prompts/sunday_replan.v1.md`  
- Schema：`schemas/day_assignments_replan.schema.json`  
- **只改**后续 `day_assignments`；不改 WBS 节点起止  
- AI 失败 → 规则：把未完成与后续安排铺到下一周（可同日多条）  

## 7. Prompt / Schema 版本

| 文件 | 版本 |
|------|------|
| `prompts/wbs_generate.v1.md` | v1 |
| `prompts/sunday_replan.v1.md` | v1 |
| `schemas/wbs_generate.schema.json` | v1 |
| `schemas/day_assignments_replan.schema.json` | v1 |

`llm_call_logs` 记录 `purpose`、prompt 版本、model、token、耗时、status。

安全：用户 `note` 当数据；系统指令与用户内容分隔；禁止把 openid/密钥写入 prompt。

## 8. 限流（首期默认）

| 项 | 值 |
|----|-----|
| 单 Goal 并发 LLM job | 1（否则 LLM_BUSY） |
| 单用户每日 wbs_generate | ≤ 20 |
| DeepSeek timeout | 60s |
| Schema repair | ≤ 2 |

## 9. 语言

- Prompt 与模型输出说明：**中文**（JSON 键英文，title/description/rationale 中文）。
