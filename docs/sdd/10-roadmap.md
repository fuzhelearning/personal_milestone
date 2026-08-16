# 10 — Roadmap

- Status: Draft
- Owner: [TODO]
- Last Updated: 2026-08-02

## 阶段 dual-track

- **Track S（Spec）**：完善并冻结文档
- **Track I（Implementation）**：仅实现已冻结范围

---

## Phase 0 — Spec 对齐

**退出标准**：P0 Spec Frozen —— **已达成（2026-08-02）**

- [x] 原型对齐（`preview/home.html`）
- [x] `02`–`09` + schemas/prompts + ADR-0015/0016 Frozen/Accepted
- [ ] （可选）部署 Base URL、DeepSeek key

---

## Phase 1 — 垂直闭环 MVP

**目标**：一个人能完整走通 Journey A/B/C（可用 mock/真实 DeepSeek）

范围（建议）：

- 微信登录 + Goal CRUD
- WBS 生成（异步）+ 确认生效
- 执行反馈 upsert
- daily_replan job + 规则兜底 +（可选）真实 LLM
- 最小通知或「仅站内可查看明日计划」

退出标准：`09` 中 P0 AC 全绿

---

## Phase 2 — 体验与稳健

- （可选）订阅消息通知 — 首期不做（ADR-0005）
- 风险扫描、站内催办态
- WBS 重新生成版本对比
- Prompt/模板版本化与成本限额
- 基础管理观察面板（日志查询即可）

---

## Phase 3 — 增强（可选）

- 多目标日配额冲突
- 截止变更智能重排
- 导出 Markdown/日历
- 更细的依赖甘特

---

## 里程碑日期（你来填）

| Milestone | 目标日期 | 定义完成 |
|-----------|----------|----------|
| M0 Spec Frozen | `[TODO]` | Phase 0 退出 |
| M1 MVP Backend | `[TODO]` | Phase 1 退出 |
| M2 Notify+Risk | `[TODO]` | Phase 2 |
| M3 Enhance | `[TODO]` | Phase 3 |
