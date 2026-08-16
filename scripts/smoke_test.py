"""端到端冒烟：mock 登录 → 建目标 → 确认 WBS → home / complete。"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


def main() -> None:
    Path("data").mkdir(exist_ok=True)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    client = TestClient(app)
    r = client.post("/api/v1/auth/wechat/login", json={"code": "smoke1"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    today = date.today()
    end = today + timedelta(days=20)
    r = client.post(
        "/api/v1/goals",
        headers=headers,
        json={
            "title": "学会 agent",
            "plan_start_date": today.isoformat(),
            "plan_end_date": end.isoformat(),
            "note": "前两周偏概念",
        },
    )
    assert r.status_code == 202, r.text
    goal_id = r.json()["goal_id"]
    job_id = r.json()["job_id"]

    r = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded", r.json()
    gen_id = r.json()["result_ref"]["generation_id"]

    r = client.get(f"/api/v1/goals/{goal_id}/wbs/generations/{gen_id}", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["structure"]["nodes"], r.json()

    r = client.post(
        f"/api/v1/goals/{goal_id}/wbs/generations/{gen_id}/confirm",
        headers=headers,
        json={},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("active", "planning"), r.json()

    r = client.get("/api/v1/home", headers=headers)
    assert r.status_code == 200, r.text
    home = r.json()
    assert home["structure"]["goals"], home
    assert isinstance(home["today_tasks"], list), home

    if home["today_tasks"]:
        item = home["today_tasks"][0]
        r = client.post(
            f"/api/v1/goals/{item['goal_id']}/today-tasks/{item['task_id']}/complete",
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "done"

    r = client.get("/api/v1/gantt", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["goals"], r.json()

    print("SMOKE OK")


if __name__ == "__main__":
    main()
