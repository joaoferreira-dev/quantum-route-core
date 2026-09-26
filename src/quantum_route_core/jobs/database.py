import json
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    Float,
    LargeBinary,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    case,
    cast,
    create_engine,
    delete,
    func,
    select,
    update,
)

from quantum_route_core.errors import RouteError

metadata = MetaData()
jobs = Table(
    "jobs",
    metadata,
    Column("job_id", String, primary_key=True),
    Column("owner", String, nullable=False),
    Column("idempotency_key", String),
    Column("request_hash", String, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("started_at", Float),
    Column("finished_at", Float),
    Column("expires_at", Float),
    UniqueConstraint("owner", "idempotency_key", name="uq_job_owner_idempotency"),
)
TERMINAL = {"completed", "cancelled", "failed"}


@dataclass(frozen=True)
class RepositoryLimits:
    owner_pending: int = 20
    submissions_per_minute: int = 10
    owner_bytes: int = 32_000_000
    total_bytes: int = 256_000_000
    snapshot_bytes: int = 4_000_000
    min_free_disk_mb: int = 256


def json_bytes(value: dict) -> int:
    return len(json.dumps(value).encode("utf-8"))


def expired(job) -> bool:
    return job["status"] in TERMINAL and job["expires_at"] <= time.time()


class Repository:
    def __init__(self, url: str, *, limits: RepositoryLimits | None = None):
        self.engine = create_engine(url, connect_args={"timeout": 10})
        self.limits = limits or RepositoryLimits()

    def _check_storage(self, db, owner: str, payload: dict, snapshot: dict, job_id=None) -> None:
        size = json_bytes(snapshot)
        if size > self.limits.snapshot_bytes:
            raise RouteError("storage_full", "Job snapshot exceeds storage limit")
        # Reserve room for a small terminal error even when the shared quota is full.
        charged = func.length(cast(jobs.c.payload, LargeBinary)) + func.max(
            1024, func.length(cast(jobs.c.snapshot, LargeBinary))
        )
        query = select(
            func.coalesce(func.sum(charged), 0),
            func.coalesce(func.sum(case((jobs.c.owner == owner, charged), else_=0)), 0),
        )
        if job_id is not None:
            query = query.where(jobs.c.job_id != job_id)
        total, owned = db.execute(query).one()
        added = json_bytes(payload) + max(1024, size)
        if owned + added > self.limits.owner_bytes:
            raise RouteError("owner_quota", "Integrator storage quota exhausted")
        if total + added > self.limits.total_bytes:
            raise RouteError("storage_full", "Global job storage quota exhausted")

    def _check_disk(self) -> None:
        path = self.engine.url.database
        if path and path != ":memory:":
            if (
                shutil.disk_usage(Path(path).resolve().parent).free
                < self.limits.min_free_disk_mb * 1024**2
            ):
                raise RouteError("storage_full", "Free disk space below admission threshold")

    @contextmanager
    def transaction(self):
        with self.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def submit(
        self,
        owner: str,
        key: str | None,
        request_hash: str,
        payload: dict,
        capacity: int,
        retention: int,
    ) -> dict:
        now = time.time()
        with self.transaction() as db:
            db.execute(delete(jobs).where(jobs.c.status.in_(TERMINAL), jobs.c.expires_at < now))
            if key:
                existing = (
                    db.execute(
                        select(jobs).where(jobs.c.owner == owner, jobs.c.idempotency_key == key)
                    )
                    .mappings()
                    .first()
                )
                if existing:
                    if existing["request_hash"] != request_hash:
                        raise RouteError(
                            "idempotency_conflict",
                            "Idempotency key already used for a different request",
                        )
                    return dict(existing)
            self._check_disk()
            self._check_storage(db, owner, payload, {})
            recent = db.scalar(
                select(func.count())
                .select_from(jobs)
                .where(jobs.c.owner == owner, jobs.c.created_at > now - 60)
            )
            if recent >= self.limits.submissions_per_minute:
                raise RouteError("owner_quota", "Integrator submission rate exceeded")
            owned_pending = db.scalar(
                select(func.count())
                .select_from(jobs)
                .where(jobs.c.owner == owner, jobs.c.status.not_in(TERMINAL))
            )
            if owned_pending >= self.limits.owner_pending:
                raise RouteError("owner_quota", "Integrator active job quota exhausted")
            pending = db.scalar(
                select(func.count()).select_from(jobs).where(jobs.c.status.not_in(TERMINAL))
            )
            if pending >= capacity:
                raise RouteError("queue_full", "Job queue is full")
            job = {
                "job_id": str(uuid4()),
                "owner": owner,
                "idempotency_key": key,
                "request_hash": request_hash,
                "payload": payload,
                "snapshot": {},
                "status": "queued",
                "created_at": now,
                "started_at": None,
                "finished_at": None,
                "expires_at": now + retention,
            }
            db.execute(jobs.insert().values(**job))
            return job

    def get(self, job_id: str, owner: str | None = None) -> dict | None:
        query = select(jobs).where(jobs.c.job_id == job_id)
        if owner is not None:
            query = query.where(jobs.c.owner == owner)
        with self.engine.connect() as db:
            row = db.execute(query).mappings().first()
        return dict(row) if row and not expired(row) else None

    def cancel(self, job_id: str, owner: str, retention: int) -> dict | None:
        with self.transaction() as db:
            row = (
                db.execute(select(jobs).where(jobs.c.job_id == job_id, jobs.c.owner == owner))
                .mappings()
                .first()
            )
            if not row or expired(row):
                return None
            job = dict(row)
            if job["status"] not in TERMINAL:
                status = "cancelled" if job["status"] == "queued" else "cancel_requested"
                values: dict[str, Any] = {"status": status}
                if status == "cancelled":
                    values.update(finished_at=time.time(), expires_at=time.time() + retention)
                db.execute(update(jobs).where(jobs.c.job_id == job_id).values(**values))
                job.update(values)
            return job

    def claim(self, queue_timeout: float, retention: int) -> dict | None:
        now = time.time()
        with self.transaction() as db:
            db.execute(delete(jobs).where(jobs.c.status.in_(TERMINAL), jobs.c.expires_at < now))
            db.execute(
                update(jobs)
                .where(jobs.c.status == "queued", jobs.c.created_at < now - queue_timeout)
                .values(
                    status="failed",
                    finished_at=now,
                    expires_at=now + retention,
                    snapshot={
                        "error": {"code": "queue_timeout", "message": "Queue deadline expired"}
                    },
                )
            )
            row = (
                db.execute(
                    select(jobs)
                    .where(jobs.c.status == "queued")
                    .order_by(jobs.c.created_at)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            job = dict(row)
            job.update(status="running", started_at=now)
            db.execute(
                update(jobs)
                .where(jobs.c.job_id == job["job_id"])
                .values(status="running", started_at=now)
            )
            return job

    def progress(self, job_id: str, patch: dict) -> None:
        with self.transaction() as db:
            job = db.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().one()
            if job["status"] in TERMINAL:
                return
            snapshot = {**job["snapshot"], **patch}
            self._check_storage(db, job["owner"], job["payload"], snapshot, job_id)
            db.execute(update(jobs).where(jobs.c.job_id == job_id).values(snapshot=snapshot))

    def finish(self, job_id: str, status: str, patch: dict, retention: int) -> None:
        with self.transaction() as db:
            row = db.execute(select(jobs).where(jobs.c.job_id == job_id)).mappings().one()
            if row["status"] in TERMINAL:
                return
            if row["status"] == "cancel_requested":
                status = "cancelled"
            snapshot = {**row["snapshot"], **patch}
            if status == "cancelled" and snapshot.get("result"):
                snapshot["result"] = {**snapshot["result"], "termination_reason": "cancelled"}
                if snapshot.get("planning_result"):
                    planning = dict(snapshot["planning_result"])
                    planning["solve_result"] = snapshot["result"]
                    planning["planning_status"] = (
                        "partial" if snapshot["result"].get("has_feasible_solution") else "failed"
                    )
                    snapshot["planning_result"] = planning
            try:
                self._check_storage(db, row["owner"], row["payload"], snapshot, job_id)
            except RouteError:
                status = "cancelled" if row["status"] == "cancel_requested" else "failed"
                snapshot = {
                    "error": {"code": "storage_full", "message": "Result exceeds storage quota"}
                }
            db.execute(
                update(jobs)
                .where(jobs.c.job_id == job_id)
                .values(
                    status=status,
                    snapshot=snapshot,
                    finished_at=time.time(),
                    expires_at=time.time() + retention,
                )
            )

    def recover(self, retention: int) -> None:
        # Only called while holding the single-worker OS lock.
        with self.transaction() as db:
            rows = (
                db.execute(select(jobs).where(jobs.c.status.in_(["running", "cancel_requested"])))
                .mappings()
                .all()
            )
            for row in rows:
                snapshot = {
                    **row["snapshot"],
                    "error": {
                        "code": "service_interrupted",
                        "message": "Worker restarted; solver not retried",
                    },
                }
                db.execute(
                    update(jobs)
                    .where(jobs.c.job_id == row["job_id"])
                    .values(
                        status="failed",
                        snapshot=snapshot,
                        finished_at=time.time(),
                        expires_at=time.time() + retention,
                    )
                )
