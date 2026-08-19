from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.replan import replan_future_assignments
from app.models import DayAssignment, DayEntry, Goal, JobRun, TaskNode, User


def run_day_close(db: Session, *, as_of: datetime | None = None) -> dict:
    """每天 23:59：回写进度；非周日顺延未完成；周日重排未来。"""
    # 默认按上海日；多用户时按各自 timezone 取「今日」
    processed = 0
    skipped = 0
    users = list(db.scalars(select(User)).all())
    for user in users:
        from app.timeutil import user_today
        from zoneinfo import ZoneInfo

        if as_of is not None:
            today = as_of.astimezone(ZoneInfo(user.timezone)).date()
        else:
            today = user_today(user.timezone)

        # 按 user 维度幂等：biz_key = date:user_id
        biz = f"{today.isoformat()}:u{user.id}"
        run = db.scalar(select(JobRun).where(JobRun.job_type == "day_close", JobRun.biz_key == biz))
        if run and run.status == "succeeded":
            skipped += 1
            continue
        if not run:
            run = JobRun(job_type="day_close", biz_key=biz, status="running", attempts=1)
            db.add(run)
            db.flush()
        else:
            run.status = "running"
            run.attempts += 1

        try:
            _close_user_day(db, user, today)
            run.status = "succeeded"
            run.finished_at = datetime.utcnow()
            processed += 1
        except Exception as exc:  # noqa: BLE001
            run.status = "failed"
            run.last_error = str(exc)
            run.finished_at = datetime.utcnow()
            raise

    return {"accepted": True, "processed": processed, "skipped": skipped}


def _close_user_day(db: Session, user: User, today: date) -> None:
    goals = list(
        db.scalars(
            select(Goal).where(
                Goal.user_id == user.id,
                Goal.deleted_at.is_(None),
                Goal.status.in_(("active", "planning")),
            )
        ).all()
    )
    is_sunday = today.weekday() == 6

    for goal in goals:
        assigns = list(
            db.scalars(
                select(DayAssignment).where(
                    DayAssignment.goal_id == goal.id,
                    DayAssignment.plan_date == today,
                )
            ).all()
        )
        for a in assigns:
            e = db.scalar(
                select(DayEntry).where(DayEntry.task_id == a.task_id, DayEntry.work_date == today)
            )
            if not e:
                e = DayEntry(
                    goal_id=goal.id,
                    user_id=user.id,
                    task_id=a.task_id,
                    work_date=today,
                    status="not_done",
                    incomplete_reason="日终未打卡",
                )
                db.add(e)
                db.flush()
            if e.status == "pending":
                e.status = "not_done"
                if not e.incomplete_reason:
                    e.incomplete_reason = "日终未打卡"
                e.updated_at = datetime.utcnow()

            if e.status == "not_done" and not is_sunday:
                _stack_assignment(db, goal, a.task_id, today + timedelta(days=1))

        _recompute_progress(db, goal)

        if is_sunday:
            replan_future_assignments(db, goal, today)


def _stack_assignment(db: Session, goal: Goal, task_id: int, to_date: date) -> None:
    exists = db.scalar(
        select(DayAssignment).where(
            DayAssignment.goal_id == goal.id,
            DayAssignment.task_id == task_id,
            DayAssignment.plan_date == to_date,
        )
    )
    if exists:
        return
    db.add(
        DayAssignment(
            goal_id=goal.id,
            user_id=goal.user_id,
            task_id=task_id,
            plan_date=to_date,
            source="day_close_defer",
            sort_order=0,
        )
    )


def _recompute_progress(db: Session, goal: Goal) -> None:
    if not goal.active_wbs_generation_id:
        return
    tasks = list(
        db.scalars(
            select(TaskNode).where(
                TaskNode.generation_id == goal.active_wbs_generation_id,
                TaskNode.kind == "task",
            )
        ).all()
    )
    if not tasks:
        return

    assigns = list(db.scalars(select(DayAssignment).where(DayAssignment.goal_id == goal.id)).all())
    by_task: dict[int, list[DayAssignment]] = defaultdict(list)
    for a in assigns:
        by_task[a.task_id].append(a)

    mil_progress: dict[int, list[int]] = defaultdict(list)
    for t in tasks:
        planned = by_task.get(t.id, [])
        if not planned:
            t.progress_pct = 0
            mil_progress[t.parent_id or 0].append(0)
            continue
        done_n = 0
        for a in planned:
            e = db.scalar(
                select(DayEntry).where(DayEntry.task_id == t.id, DayEntry.work_date == a.plan_date)
            )
            if e and e.status == "done":
                done_n += 1
        pct = int(round(100 * done_n / len(planned))) if planned else 0
        t.progress_pct = pct
        t.updated_at = datetime.utcnow()
        mil_progress[t.parent_id or 0].append(pct)

    milestones = list(
        db.scalars(
            select(TaskNode).where(
                TaskNode.generation_id == goal.active_wbs_generation_id,
                TaskNode.kind == "milestone",
            )
        ).all()
    )
    for m in milestones:
        kids = mil_progress.get(m.id, [])
        m.progress_pct = int(round(sum(kids) / len(kids))) if kids else 0
        m.updated_at = datetime.utcnow()

    task_pcts = [t.progress_pct for t in tasks]
    goal.overall_progress_pct = int(round(sum(task_pcts) / len(task_pcts))) if task_pcts else 0
    goal.updated_at = datetime.utcnow()
