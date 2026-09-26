import time

from sqlalchemy import select

from quantum_route_core.api.settings import Settings
from quantum_route_core.jobs.database import Repository, jobs

settings = Settings()
repo = Repository(settings.database_url)
until = time.monotonic() + settings.max_planning_seconds + 10
while time.monotonic() < until:
    with repo.engine.connect() as db:
        active = db.execute(
            select(jobs.c.job_id).where(
                jobs.c.status.in_(["queued", "running", "cancel_requested"])
            )
        ).all()
    if not active:
        break
    time.sleep(1)
else:
    raise SystemExit("Active jobs did not drain within the deadline")
