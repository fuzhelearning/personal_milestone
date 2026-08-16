from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def user_today(tz_name: str = "Asia/Shanghai") -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=n)


def week_sunday(d: date) -> date:
    # Monday=0 … Sunday=6
    return d + timedelta(days=(6 - d.weekday()))


def earliest_plan_end(current_end: date, today: date) -> date:
    after_current = add_days(current_end, 1)
    min_by_today = add_days(today, 3)
    return max(after_current, min_by_today)


def weekday_name(d: date) -> str:
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return names[d.weekday()]
