"""Mock LLM：不请求 DeepSeek，直接在库里写入 suggested WBS + day_assignments。"""

from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DayAssignment, Goal, LlmCallLog, TaskNode, WbsGeneration


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def build_mock_plan(goal: Goal) -> dict:
    """按起止日切三段里程碑，每天一事。"""
    start, end = goal.plan_start_date, goal.plan_end_date
    span = (end - start).days + 1
    if span < 3:
        # 极短目标：单里程碑
        milestones = [
            {
                "code": "1.0",
                "title": "执行",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "tasks": [
                    {
                        "code": "1.1",
                        "title": f"推进：{goal.title}",
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                    }
                ],
            }
        ]
        days = [{"date": d.isoformat(), "task_codes": ["1.1"]} for d in _daterange(start, end)]
        return {"milestones": milestones, "day_assignments": days, "assumptions": ["mock"]}

    t1 = start + timedelta(days=max(1, span // 3) - 1)
    t2 = start + timedelta(days=max(2, (2 * span) // 3) - 1)
    if t1 >= end:
        t1 = start
    if t2 <= t1:
        t2 = min(end, t1 + timedelta(days=1))
    if t2 >= end:
        t2 = end - timedelta(days=1) if end > start else end

    windows = [
        ("1.0", "懂概念", start, t1, "1.1", "学习基础概念"),
        ("2.0", "能使用", t1 + timedelta(days=1), t2, "2.1", "动手练习"),
        ("3.0", "做出完整成果", t2 + timedelta(days=1), end, "3.1", "落地小项目"),
    ]
    # clamp
    fixed = []
    for code, title, s, e, tc, tt in windows:
        if s > end:
            continue
        e = min(max(e, s), end)
        fixed.append((code, title, s, e, tc, tt))

    milestones = []
    day_assignments = []
    for code, title, s, e, tc, tt in fixed:
        milestones.append(
            {
                "code": code,
                "title": title,
                "start_date": s.isoformat(),
                "end_date": e.isoformat(),
                "tasks": [
                    {
                        "code": tc,
                        "title": f"{tt}（{goal.title[:24]}）",
                        "start_date": s.isoformat(),
                        "end_date": e.isoformat(),
                    }
                ],
            }
        )
        for d in _daterange(s, e):
            day_assignments.append({"date": d.isoformat(), "task_codes": [tc]})

    return {
        "milestones": milestones,
        "day_assignments": day_assignments,
        "assumptions": ["mock-llm", "一天一事"],
        "note_echo": goal.note,
    }


def persist_suggested_generation(db: Session, goal: Goal) -> WbsGeneration:
    payload = build_mock_plan(goal)
    log = LlmCallLog(
        user_id=goal.user_id,
        goal_id=goal.id,
        purpose="wbs_generate",
        model="mock",
        prompt_hash="mock",
        request_meta={
            "title": goal.title,
            "plan_start_date": goal.plan_start_date.isoformat(),
            "plan_end_date": goal.plan_end_date.isoformat(),
            "note": goal.note,
        },
        response_meta={"mode": "mock"},
        status="succeeded",
    )
    db.add(log)
    db.flush()

    ver = db.scalar(
        select(func.coalesce(func.max(WbsGeneration.version), 0)).where(WbsGeneration.goal_id == goal.id)
    )
    gen = WbsGeneration(
        goal_id=goal.id,
        user_id=goal.user_id,
        version=int(ver) + 1,
        status="suggested",
        source="ai",
        llm_call_id=log.id,
        raw_response=json.dumps(payload, ensure_ascii=False),
    )
    db.add(gen)
    db.flush()

    code_to_task_id: dict[str, int] = {}
    sort_m = 0
    for m in payload["milestones"]:
        ms = TaskNode(
            generation_id=gen.id,
            goal_id=goal.id,
            user_id=goal.user_id,
            parent_id=None,
            kind="milestone",
            code=m["code"],
            title=m["title"],
            sort_order=sort_m,
            start_date=date.fromisoformat(m["start_date"]),
            end_date=date.fromisoformat(m["end_date"]),
        )
        db.add(ms)
        db.flush()
        sort_m += 1
        sort_t = 0
        for t in m["tasks"]:
            node = TaskNode(
                generation_id=gen.id,
                goal_id=goal.id,
                user_id=goal.user_id,
                parent_id=ms.id,
                kind="task",
                code=t["code"],
                title=t["title"],
                sort_order=sort_t,
                start_date=date.fromisoformat(t["start_date"]),
                end_date=date.fromisoformat(t["end_date"]),
            )
            db.add(node)
            db.flush()
            code_to_task_id[t["code"]] = node.id
            sort_t += 1

    # suggested 阶段先把 assignments 以 generation 绑定的 task 写入（确认时再激活语义上已存在）
    # 用临时标记：source=ai，确认后保留；若未确认也可预览
    for i, row in enumerate(payload["day_assignments"]):
        tid = code_to_task_id.get(row["task_codes"][0])
        if not tid:
            continue
        db.add(
            DayAssignment(
                goal_id=goal.id,
                user_id=goal.user_id,
                task_id=tid,
                plan_date=date.fromisoformat(row["date"]),
                source="ai",
                sort_order=i,
            )
        )

    return gen


def mock_replan_future_assignments(db: Session, goal: Goal, today: date) -> int:
    """仅改 tomorrow+ 的 day_assignments：按剩余日重新一天一事铺开未完成/未来任务。"""
    if not goal.active_wbs_generation_id:
        return 0
    tasks = db.scalars(
        select(TaskNode).where(
            TaskNode.generation_id == goal.active_wbs_generation_id,
            TaskNode.kind == "task",
        )
    ).all()
    if not tasks:
        return 0

    # 删除未来安排
    future = db.scalars(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.plan_date > today,
        )
    ).all()
    for a in future:
        db.delete(a)
    db.flush()

    # 简单：从 tomorrow 到 plan_end，轮转 task
    tomorrow = today + timedelta(days=1)
    if tomorrow > goal.plan_end_date:
        return 0
    days = list(_daterange(tomorrow, goal.plan_end_date))
    # 过滤已 100% 的 task
    active_tasks = [t for t in tasks if t.progress_pct < 100] or list(tasks)
    n = 0
    for i, d in enumerate(days):
        task = active_tasks[i % len(active_tasks)]
        exists = db.scalar(
            select(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.task_id == task.id,
                DayAssignment.plan_date == d,
            )
        )
        if exists:
            continue
        db.add(
            DayAssignment(
                goal_id=goal.id,
                user_id=goal.user_id,
                task_id=task.id,
                plan_date=d,
                source="deadline_replan",
                sort_order=i,
            )
        )
        n += 1
    return n
