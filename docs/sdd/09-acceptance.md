# 09 — Acceptance Criteria

- Status: Frozen
- Owner: [TODO]
- Last Updated: 2026-08-02
- Related: `02`/`05`/`06`/`07`/`08`；ADR-0014…0016

## 1. 用法

- 每个 P0 需求至少 1 条 AC；格式 Given / When / Then  
- LLM 测试一律 **mock** DeepSeek（fixture JSON），避免烧钱  

---

## 2. P0 用例

### AC-001 登录

- REQ-F-001  
- Given 有效 wx code（或测试桩）  
- When `POST /api/v1/auth/wechat/login`  
- Then 200 + `access_token`；带 Bearer 可访问受保护接口  

### AC-002 「+」创建并异步生成

- REQ-F-010/020/020a  
- Given 已登录  
- When `POST /api/v1/goals` 带 title/起止/note  
- Then **202** + `goal_id` + `job_id`；响应不等待 LLM  
- When 轮询 job→succeeded（mock）  
- Then 可 `GET .../wbs/generations/{id}` 看到 nodes + day_assignments_preview  

### AC-003 确认后 home 可读

- REQ-F-022/040/040a/029  
- When `POST .../confirm`  
- Then Goal=`planning`（today < plan_start）或 `active`；`day_assignments` 已落库  
- When `GET .../home`  
- Then 含 today、structure.goals、today_tasks（全目标数组）、rest_of_week；**无 LLM 调用**  

### AC-003b Structure 点目标改完成日

- REQ-F-030d / ADR-0014/0002  
- When 点 Structure 某 Goal 保存更晚且 ≥today+3 的完成日（可改备注）  
- Then 202 + `job_id`；今日 assignments 不变；未来段进入重排  

### AC-004 Schema 失败不生效

- REQ-F-021  
- Given mock 返回缺 `day_assignments`  
- When 生成 job 跑完  
- Then job=failed 或 repair 后仍 failed；无 active generation；Goal 非 active  

### AC-005 今日完成不立刻改进度权威值

- REQ-F-031/033  
- Given home 某 task progress_pct=0，今日有 assignment  
- When `POST .../complete`  
- Then day_entry=`done`；progress_pct **仍为 0**（或未回写前不变）  
- When 触发 `day-close`（同日）  
- Then 该 task progress_pct 按规则上升  

### AC-005a 勾选优先于原因文本

- REQ-F-031  
- Given 用户在原因框输入了文字但未提交 incomplete  
- When `POST .../complete`（勾选 checkbox）  
- Then status=`done`；**不**触发周内顺延；原因不作为未完成依据  

### AC-005b 点任务行不改变完成态（前端）

- REQ-F-031d / ADR-0007  
- Given 今日任务默认不展示原因区  
- When 用户点击任务标题行（非 checkbox）  
- Then 仅展开/收起原因区；`day_entry` 状态不变  
- When 用户点击 checkbox  
- Then 才调用 complete/uncomplete  

### AC-005c 未完成状态可见

- REQ-F-040b  
- Given 某今日项 `status=not_done` 且原因区收起  
- When 渲染今日任务列表  
- Then 仍显示「未完成」标识  

### AC-005d 底部入口进甘特

- REQ-F-030a/030b  
- When 点击首页「查看全局甘特图」  
- Then 进入甘特；`from=today-30`/`to=today+30`；视口以今天为中心  
- And 同**里程碑**同日多 task（≤today）：未全 `done`→未完成色；全 done→完成色  
- And **date > today** 有安排→**未开始**色，不得涂未完成色（ADR-0016）  

### AC-006 未完成必填原因并顺延

- REQ-F-032/031a  
- When `incomplete` 无 reason  
- Then 422 `ENTRY_INVALID`  
- When 已 `done` 再 `incomplete`  
- Then 422（拒绝）  
- When 未勾选且带 reason 提交  
- Then entry=`not_done`；**下一天** `day_assignments` 出现该 task（source=defer）  

### AC-007 23:59 未处理视未完成

- REQ-F-031b / ADR-0015  
- Given 今日 assignment 且 entry 仍 pending  
- When `day-close`（非周日）  
- Then entry→`not_done`；顺延到**明天**；进度已回写  
- When `day-close`（周日）  
- Then entry→`not_done`；走**新计划**重排后续日（不改 WBS 节点起止）  

### AC-008 完成日只能往后且 ≥today+3

- REQ-F-012c  
- When new_end ≤ current → `DEADLINE_NOT_LATER`  
- When new_end < today+3 → `DEADLINE_TOO_SOON`  
- When 合法 pending 未 confirm → 生效 assignments/WBS 不变  
- When confirm → 今日 assignments 不变；未来可变更  

### AC-009 禁止砍 scope

- REQ-F-047  
- Given mock 周日重排输出删除 task  
- When 校验  
- Then 拒绝该输出；规则兜底或 job failed；**task_nodes 行数不减**  

### AC-010 Internal 幂等

- ADR-0004  
- When 同一 `biz_key` 的 day-close 触发两次  
- Then 进度只按一次语义更新（第二次 no-op）  

### AC-011 周日重排降级

- REQ-F-031c / `07`  
- Given DeepSeek 不可用  
- When sunday-replan  
- Then 规则仍写出下周 assignments；不损坏已有数据；今日可读写 entry  

### AC-012 越权

- REQ-NF-004  
- When 用户 B 访问用户 A 的 goal_id  
- Then 403 或 404；无数据正文  

### AC-013 无 Redis / 无订阅消息

- ADR-0005/0009  
- Then 依赖清单无 Redis；代码路径无订阅消息发送（首期）  

---

## 3. 非功能抽检

| ID | 检查 | 通过 |
|----|------|------|
| AC-NF-001 | 小程序包 / 前端配置 | 无 DeepSeek Key |
| AC-NF-002 | 任意成功/失败 LLM | 有 `llm_call_logs` |
| AC-NF-003 | Internal 无 Token | 401/403 |

---

## 4. 测试分层

| 层 | 覆盖 |
|----|------|
| Unit | Schema、进度公式、顺延规则、日期校验 |
| Integration | API + MySQL；mock LLM |
| Contract | OpenAPI ↔ `05` |
| 手工 | 小程序走「+」→ home → 打钩 → 调 internal rollup |

## 5. Mock 约定

- 测试夹具目录建议：`tests/fixtures/llm/*.json`  
- 符合 `docs/sdd/schemas/*.json`  
- 禁止 CI 真调 DeepSeek（除非手动集成 job）
