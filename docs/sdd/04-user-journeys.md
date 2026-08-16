# 04 — User Journeys

- Status: Frozen
- Owner: [TODO]
- Last Updated: 2026-08-02
- Related ADRs: ADR-0001…0016

## Journey A — 「+」创建 → AI 生成 WBS+按日安排（P0，ADR-0008）

**触发**：首页右上角「+」。

| 步 | 角色 | 行为 | 系统响应 | 对应 REQ |
|----|------|------|----------|----------|
| 1 | User | 登录 | 会话令牌 | REQ-F-001 |
| 2 | User | 「+」填写：名称、开始日、结束日、备注 | 创建 Goal=`draft`，立即开生成 job | REQ-F-010/020 |
| 3 | User | 轮询 `job_id` | AI 生成两层 WBS + **DayAssignment** | REQ-F-020a |
| 4 | System | Schema 校验 | 含按日安排；失败有限次重试 | REQ-F-021 |
| 5 | User | 预览后确认 | generation 生效；Goal=`planning`（未到开始日）或 `active` | REQ-F-022 |
| 6 | User | 回首页 | 全目标今日任务 + 本周剩余（默认折叠） | REQ-F-040/040a |

**边界**

- 结束日 < 开始日：422  
- AI 超时/失败：Goal 保持 `draft`；可改备注重试  
- 完成日/备注保存：只重排未来 `day_assignments`（今日不动，ADR-0015）

---

## Journey B — 今日任务 → 定时回写 Structure（P0，ADR-0007）

**触发**：用户打开首页。

| 步 | 角色 | 行为 | 系统响应 | 对应 REQ |
|----|------|------|----------|----------|
| 1 | User | 打开首页 | 日期 + Structure + **全目标**今日任务 + 本周剩余（默认折叠） | REQ-F-029/030/040/040a |
| 1a | User | **点击 Structure 某目标** | 编辑完成日/备注 → 保存立刻重排未来 | REQ-F-030d |
| 1b | User | **点击「查看甘特」** | 甘特页：Goal → Milestone × 日期格 | REQ-F-030a/030b |
| 2a | User | **点 checkbox** | `done`；展开中则原因框置灰；忽略原因 | REQ-F-031 |
| 2a′ | User | **点任务标题行** | 展开/收起原因区 | REQ-F-031d |
| 2b | User | 提交未完成原因 | `not_done`；列表显示「未完成」；顺延 | REQ-F-032/040b |
| 3 | Scheduler | **每天 23:59** day_close | 回写进度；未完成→次日或周日新计划 | REQ-F-033/031c |
| 4 | User | 回首页 / 甘特页 | 首页执行态更新；甘特按 ADR-0016 着色 | REQ-F-030 |

**边界**

- 本周剩余：不含今天；默认折叠；首期只读预览  
- 日终未处理：23:59 day_close → 未完成；非周日顺延次日叠加；周日新计划（ADR-0015）  
- 权威进度以 23:59 day_close 为准  
- 今日任务不受「改完成日」影响（ADR-0002）

---

## Journey C — 日终结算与顺延（P0，ADR-0015）

**定位**：补全 Journey B；**不得改 WBS 节点起止**。

| 步 | 角色 | 行为 | 系统响应 | 对应 REQ |
|----|------|------|----------|----------|
| 1 | User | 提交未完成 / 或等到日终 | `not_done` | REQ-F-032/031b |
| 2 | System | **非周日**：未完成 **叠加到明天**（不挤掉原任务） | `day_assignments` | REQ-F-031a |
| 3 | Scheduler | **每天 23:59** `day_close` | 结算 pending→not_done + 回写进度 | REQ-F-033 |
| 4 | Scheduler | 若当天是**周日** 23:59 | **新计划**：重排后续日 assignments（AI+规则） | REQ-F-031c |

**边界**：DeepSeek 失败则规则兜底；幂等 `day_close:{goal_id}:{today}`；催办 21:00 为 P1。

---

## Journey D — 调整完成日 / 备注（P0，ADR-0014/0015）

**触发**：首页 Structure 点目标 → 编辑面板。小程序主路径：`POST .../plan-edit`（保存即确认）。

| 步 | 角色 | 行为 | 系统响应 | 对应 REQ |
|----|------|------|----------|----------|
| 1 | User | 改 `new_plan_end_date` 和/或 `note` 并保存 | 校验 ADR-0002；立刻入队重排 job | REQ-F-030d/012 |
| 2 | System | 重排 **明天及以后** `day_assignments` | **不改** WBS 起止；**今日安排不变** | REQ-F-025/ADR-0015 |
| 3 | User | 继续今日任务；之后看新安排 | 今日清单与变更前一致 | REQ-F-040 |

**边界**

- `DEADLINE_NOT_LATER` / `DEADLINE_TOO_SOON`  
- 仅改备注也重排  
- 可选保留 `deadline-change` 两段式 API；小程序用 `plan-edit`  
---

## 反用例（Abuse / Misuse）

| 场景 | 期望 |
|------|------|
| 伪造他人 goal_id | 403/404，不泄露存在性策略 `[DECIDE]` |
| 疯狂点击生成 WBS | 限流 + 进行中任务复用 |
| Prompt 注入写进目标描述 | 输出仍受 Schema 约束；禁止执行工具调用 |
