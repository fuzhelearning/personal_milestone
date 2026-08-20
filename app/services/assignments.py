"""日安排查询与 generation 级清理。"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import DayAssignment, DayEntry, Goal, TaskNode

# 日终顺延语义：新写 day_close_defer；历史 defer 读路径同族兼容
EXECUTION_DEFER_SOURCES = frozenset({"day_close_defer", "defer"})


def is_execution_defer_source(source: str) -> bool:
    return source in EXECUTION_DEFER_SOURCES


def active_task_ids_by_goal(db: Session, goals: list[Goal]) -> dict[int, set[int]]:
    gen_ids = [g.active_wbs_generation_id for g in goals if g.active_wbs_generation_id]
    if not gen_ids:
        return {}
    rows = db.execute(
        select(TaskNode.goal_id, TaskNode.id).where(
            TaskNode.generation_id.in_(gen_ids),
            TaskNode.kind == "task",
        )
    ).all()
    out: dict[int, set[int]] = {}
    for goal_id, task_id in rows:
        out.setdefault(goal_id, set()).add(task_id)
    return out


def task_ids_for_generation(db: Session, generation_id: int) -> list[int]:
    return list(
        db.scalars(
            select(TaskNode.id).where(
                TaskNode.generation_id == generation_id,
                TaskNode.kind == "task",
            )
        ).all()
    )


def delete_generation_assignments(
    db: Session,
    *,
    goal_id: int,
    generation_id: int,
) -> None:
    task_ids = task_ids_for_generation(db, generation_id)
    if not task_ids:
        return
    db.execute(
        delete(DayAssignment).where(
            DayAssignment.goal_id == goal_id,
            DayAssignment.task_id.in_(task_ids),
        )
    )


def migrate_day_entries_for_generation_swap(
    db: Session,
    *,
    goal_id: int,
    old_generation_id: int,
    new_generation_id: int,
) -> None:
    """确认 replan 时将 DayEntry 从旧 task_id 迁移到新 task_id（按 code）。"""
    old_tasks = {
        n.code: n.id
        for n in db.scalars(
            select(TaskNode).where(
                TaskNode.generation_id == old_generation_id,
                TaskNode.kind == "task",
            )
        ).all()
    }
    new_tasks = {
        n.code: n.id
        for n in db.scalars(
            select(TaskNode).where(
                TaskNode.generation_id == new_generation_id,
                TaskNode.kind == "task",
            )
        ).all()
    }
    for code, old_tid in old_tasks.items():
        new_tid = new_tasks.get(code)
        if not new_tid or old_tid == new_tid:
            continue
        entries = list(
            db.scalars(select(DayEntry).where(DayEntry.task_id == old_tid)).all()
        )
        for entry in entries:
            conflict = db.scalar(
                select(DayEntry).where(
                    DayEntry.task_id == new_tid,
                    DayEntry.work_date == entry.work_date,
                )
            )
            if conflict:
                db.delete(entry)
            else:
                entry.task_id = new_tid
                entry.goal_id = goal_id
