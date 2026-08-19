"""重排 suggested / active 落库。"""

from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.llm.schema import ReplanPayload
from app.models import DayAssignment, Goal, TaskNode, WbsGeneration
from app.services.assignments import delete_generation_assignments


def supersede_suggested_replan_generations(db: Session, goal_id: int) -> None:
    """新 deadline_replan 触发时 supersede 同 goal 旧 suggested 草案。"""
    old = list(
        db.scalars(
            select(WbsGeneration).where(
                WbsGeneration.goal_id == goal_id,
                WbsGeneration.status == "suggested",
                WbsGeneration.source == "deadline_replan",
            )
        ).all()
    )
    for gen in old:
        delete_generation_assignments(db, goal_id=goal_id, generation_id=gen.id)
        gen.status = "superseded"


def persist_suggested_replan(
    db: Session,
    goal: Goal,
    gen: WbsGeneration,
    payload: ReplanPayload | dict,
    *,
    today: date,
    source: str,
) -> WbsGeneration:
    """从 active generation 复制节点与历史安排，应用 delta，写入 suggested generation。"""
    if isinstance(payload, ReplanPayload):
        data = payload.model_dump(exclude_none=True)
    else:
        data = payload

    if not goal.active_wbs_generation_id:
        raise ValueError("目标无 active WBS，无法重排")

    active_nodes = list(
        db.scalars(
            select(TaskNode).where(TaskNode.generation_id == goal.active_wbs_generation_id)
        ).all()
    )
    if not active_nodes:
        raise ValueError("active WBS 无节点")

    task_updates = {u["code"]: u for u in data.get("task_updates", [])}
    milestone_updates = {u["code"]: u for u in data.get("milestone_updates", [])}

    old_id_to_code = {n.id: n.code for n in active_nodes if n.kind == "task"}
    code_to_new_id: dict[str, int] = {}
    old_mil_id_to_code = {n.id: n.code for n in active_nodes if n.kind == "milestone"}

    milestones = sorted(
        [n for n in active_nodes if n.kind == "milestone"],
        key=lambda x: (x.sort_order, x.id),
    )
    for n in milestones:
        start = n.start_date
        end = n.end_date
        if n.code in milestone_updates:
            mu = milestone_updates[n.code]
            end = date.fromisoformat(mu["end_date"])
            if mu.get("start_date"):
                start = date.fromisoformat(mu["start_date"])
        db.add(
            TaskNode(
                generation_id=gen.id,
                goal_id=goal.id,
                user_id=goal.user_id,
                parent_id=None,
                kind="milestone",
                code=n.code,
                title=n.title,
                description=n.description,
                sort_order=n.sort_order,
                start_date=start,
                end_date=end,
                progress_pct=n.progress_pct,
                depends_on_json=n.depends_on_json,
            )
        )
    db.flush()

    mil_code_to_new_id = {
        n.code: n.id
        for n in db.scalars(
            select(TaskNode).where(
                TaskNode.generation_id == gen.id,
                TaskNode.kind == "milestone",
            )
        ).all()
    }

    tasks = sorted(
        [n for n in active_nodes if n.kind == "task"],
        key=lambda x: (x.sort_order, x.id),
    )
    for n in tasks:
        start = n.start_date
        end = n.end_date
        if n.code in task_updates:
            tu = task_updates[n.code]
            start = date.fromisoformat(tu["start_date"])
            end = date.fromisoformat(tu["end_date"])
        mil_code = old_mil_id_to_code.get(n.parent_id or 0)
        node = TaskNode(
            generation_id=gen.id,
            goal_id=goal.id,
            user_id=goal.user_id,
            parent_id=mil_code_to_new_id.get(mil_code or ""),
            kind="task",
            code=n.code,
            title=n.title,
            description=n.description,
            sort_order=n.sort_order,
            start_date=start,
            end_date=end,
            progress_pct=n.progress_pct,
            depends_on_json=n.depends_on_json,
        )
        db.add(node)
        db.flush()
        code_to_new_id[n.code] = node.id

    old_task_ids = list(old_id_to_code.keys())
    if old_task_ids:
        past = list(
            db.scalars(
                select(DayAssignment).where(
                    DayAssignment.goal_id == goal.id,
                    DayAssignment.task_id.in_(old_task_ids),
                    DayAssignment.plan_date <= today,
                )
            ).all()
        )
        for i, a in enumerate(sorted(past, key=lambda x: (x.plan_date, x.sort_order, x.id))):
            code = old_id_to_code.get(a.task_id)
            new_tid = code_to_new_id.get(code or "")
            if not new_tid:
                continue
            db.add(
                DayAssignment(
                    goal_id=goal.id,
                    user_id=goal.user_id,
                    task_id=new_tid,
                    plan_date=a.plan_date,
                    source=a.source,
                    sort_order=i,
                )
            )

    if data.get("confirmable", True) and data.get("deadline_adjustment") != "longer":
        for i, row in enumerate(data.get("day_assignments", [])):
            code = row["task_codes"][0]
            new_tid = code_to_new_id.get(code)
            if not new_tid:
                continue
            db.add(
                DayAssignment(
                    goal_id=goal.id,
                    user_id=goal.user_id,
                    task_id=new_tid,
                    plan_date=date.fromisoformat(row["date"]),
                    source=source,
                    sort_order=1000 + i,
                )
            )
    elif old_task_ids:
        future = list(
            db.scalars(
                select(DayAssignment).where(
                    DayAssignment.goal_id == goal.id,
                    DayAssignment.task_id.in_(old_task_ids),
                    DayAssignment.plan_date > today,
                )
            ).all()
        )
        for i, a in enumerate(sorted(future, key=lambda x: (x.plan_date, x.sort_order, x.id))):
            code = old_id_to_code.get(a.task_id)
            new_tid = code_to_new_id.get(code or "")
            if not new_tid:
                continue
            db.add(
                DayAssignment(
                    goal_id=goal.id,
                    user_id=goal.user_id,
                    task_id=new_tid,
                    plan_date=a.plan_date,
                    source="replan_held",
                    sort_order=1000 + i,
                )
            )

    if not gen.raw_response:
        gen.raw_response = json.dumps(data, ensure_ascii=False)
    db.flush()
    return gen


def persist_active_replan(
    db: Session,
    goal: Goal,
    payload: ReplanPayload | dict,
    *,
    today: date,
    source: str,
) -> dict:
    """sunday_replan：直接更新 active generation 节点与明天及以后 day_assignments。"""
    if isinstance(payload, ReplanPayload):
        data = payload.model_dump(exclude_none=True)
    else:
        data = payload

    if not goal.active_wbs_generation_id:
        raise ValueError("目标无 active WBS，无法重排")

    active_nodes = list(
        db.scalars(
            select(TaskNode).where(TaskNode.generation_id == goal.active_wbs_generation_id)
        ).all()
    )
    code_to_node = {n.code: n for n in active_nodes if n.kind == "task"}
    mil_code_to_node = {n.code: n for n in active_nodes if n.kind == "milestone"}

    task_updates = {u["code"]: u for u in data.get("task_updates", [])}
    milestone_updates = {u["code"]: u for u in data.get("milestone_updates", [])}

    for code, mu in milestone_updates.items():
        node = mil_code_to_node.get(code)
        if not node:
            continue
        node.end_date = date.fromisoformat(mu["end_date"])
        if mu.get("start_date"):
            node.start_date = date.fromisoformat(mu["start_date"])
        node.updated_at = datetime.utcnow()

    for code, tu in task_updates.items():
        node = code_to_node.get(code)
        if not node:
            continue
        node.start_date = date.fromisoformat(tu["start_date"])
        node.end_date = date.fromisoformat(tu["end_date"])
        node.updated_at = datetime.utcnow()

    active_task_ids = [n.id for n in code_to_node.values()]
    if active_task_ids:
        db.execute(
            delete(DayAssignment).where(
                DayAssignment.goal_id == goal.id,
                DayAssignment.task_id.in_(active_task_ids),
                DayAssignment.plan_date > today,
            )
        )

    for i, row in enumerate(data.get("day_assignments", [])):
        code = row["task_codes"][0]
        tid = code_to_node.get(code)
        if not tid:
            continue
        db.add(
            DayAssignment(
                goal_id=goal.id,
                user_id=goal.user_id,
                task_id=tid.id,
                plan_date=date.fromisoformat(row["date"]),
                source=source,
                sort_order=1000 + i,
            )
        )

    goal.updated_at = datetime.utcnow()
    db.flush()
    return {
        "applied": True,
        "suggested_deadline_change": data.get("suggested_deadline_change"),
        "assignment_count": len(data.get("day_assignments", [])),
    }


def generation_confirmable(gen: WbsGeneration) -> bool:
    if gen.status != "suggested":
        return False
    if gen.source != "deadline_replan":
        return True
    if not gen.raw_response:
        return True
    try:
        raw = json.loads(gen.raw_response)
        if raw.get("deadline_adjustment") == "longer":
            return False
        if "confirmable" in raw:
            return bool(raw["confirmable"])
        if raw.get("suggested_deadline_change"):
            return False
    except (json.JSONDecodeError, TypeError):
        pass
    return True
