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
