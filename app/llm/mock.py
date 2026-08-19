"""Mock LLM：构造合法假数据（落库与重排见 persist / replan）。"""

from __future__ import annotations

from datetime import date, timedelta

from app.models import Goal


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
    }


def build_mock_replan(
    context: dict,
    goal: Goal,
    today: date,
    new_plan_end_date: date,
    job_type: str,
) -> dict:
    """Mock 重排：延长未完成任务窗，按日排未完成任务，避开其他目标已有安排。"""
    _ = goal, job_type
    target = context["target_goal"]
    incomplete = [t for t in target["tasks"] if t["progress_pct"] < 100]
    tomorrow = today + timedelta(days=1)

    if not incomplete:
        return {
            "task_updates": [],
            "milestone_updates": [],
            "day_assignments": [],
            "assumptions": ["mock-replan", "无未完成任务"],
        }

    if tomorrow > new_plan_end_date:
        return {
            "task_updates": [],
            "milestone_updates": [],
            "day_assignments": [],
            "suggested_deadline_change": f"建议将完成日延长至 {(tomorrow + timedelta(days=len(incomplete) - 1)).isoformat()} 或更晚",
            "assumptions": ["mock-replan"],
        }

    occupied = {
        d
        for d, items in context.get("all_goals_by_date", {}).items()
        if any(not x.get("is_target") for x in items)
    }

    task_updates = []
    for t in incomplete:
        t_start = date.fromisoformat(t["start_date"]) if t["start_date"] else tomorrow
        task_updates.append(
            {
                "code": t["code"],
                "start_date": max(tomorrow, t_start).isoformat(),
                "end_date": new_plan_end_date.isoformat(),
            }
        )

    day_assignments = []
    cur = tomorrow
    day_idx = 0
    while cur <= new_plan_end_date:
        if cur.isoformat() not in occupied:
            t = incomplete[day_idx % len(incomplete)]
            day_assignments.append({"date": cur.isoformat(), "task_codes": [t["code"]]})
            day_idx += 1
        cur += timedelta(days=1)

    if len(day_assignments) < (new_plan_end_date - tomorrow).days + 1:
        return {
            "task_updates": task_updates,
            "milestone_updates": [],
            "day_assignments": day_assignments,
            "suggested_deadline_change": (
                f"建议将完成日延长，或调整并行目标后重试（需覆盖 {(new_plan_end_date - tomorrow).days + 1} 天）"
            ),
            "assumptions": ["mock-replan"],
        }

    mil_updates = []
    for m in target["milestones"]:
        if m["progress_pct"] >= 100:
            continue
        mil_updates.append({"code": m["code"], "end_date": new_plan_end_date.isoformat()})

    return {
        "task_updates": task_updates,
        "milestone_updates": mil_updates,
        "day_assignments": day_assignments,
        "assumptions": ["mock-replan"],
    }
