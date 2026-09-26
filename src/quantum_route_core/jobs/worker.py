import logging
import multiprocessing as mp
import os
import signal
import time
from contextlib import contextmanager
from pathlib import Path

import psutil
from pydantic import TypeAdapter

from quantum_route_core.api.settings import Settings
from quantum_route_core.application import solve
from quantum_route_core.domain import MatrixRequest, Request, SolveResult
from quantum_route_core.errors import RouteError
from quantum_route_core.execution import ExecutionContext
from quantum_route_core.jobs.database import Repository
from quantum_route_core.normalization import normalize

logger = logging.getLogger(__name__)


@contextmanager
def worker_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError as exc:
            raise RuntimeError("A worker already owns this database") from exc
        yield


def _child(payload: dict, settings: Settings, connection, stop, owner: str):
    provider = None
    try:
        request: Request = TypeAdapter(Request).validate_python(payload)
        seconds = (
            request.config.time_limit_seconds
            if isinstance(request, MatrixRequest)
            else request.planning_time_limit_seconds
        )
        context = ExecutionContext(
            seconds, stop.is_set, lambda patch: connection.send(("progress", patch))
        )
        if isinstance(request, MatrixRequest):
            result = solve(request.instance, request.config, context)
            connection.send(("done", {"result": result.model_dump()}))
        else:
            from quantum_route_core.planning import plan_deliveries
            from quantum_route_core.routing.providers.openrouteservice import OpenRouteService

            provider = OpenRouteService(
                settings.ors_api_key.get_secret_value(),
                settings.ors_base_url,
                settings.ors_ledger_path,
                settings.ors_cache_ttl,
                owner=owner,
                owner_quota_fraction=settings.ors_owner_quota_fraction,
                limits={
                    "matrix": (settings.ors_matrix_daily, settings.ors_matrix_minute),
                    "directions": (settings.ors_directions_daily, settings.ors_directions_minute),
                    "snap": (settings.ors_snap_daily, settings.ors_snap_minute),
                },
            )
            planning = plan_deliveries(request, provider, context, area_path=settings.area_path)
            connection.send(
                (
                    "done",
                    {
                        "planning_result": planning.model_dump(),
                        "result": planning.solve_result.model_dump()
                        if planning.solve_result
                        else None,
                        "error": planning.errors[0] if planning.errors else None,
                    },
                )
            )
    except RouteError as exc:
        connection.send(("failed", {"error": {"code": exc.code, "message": exc.message}}))
    except Exception:
        # No arbitrary exception text: HTTP exceptions can contain credentials/coordinates.
        connection.send(
            (
                "failed",
                {
                    "error": {
                        "code": "execution_error",
                        "message": "Worker execution failed; inspect local diagnostics",
                    }
                },
            )
        )
        logger.error("Job child failed", exc_info=False)
    finally:
        if provider:
            provider.close()
        connection.close()


def run_once(settings: Settings, repository: Repository | None = None) -> bool:
    repo = repository or Repository(settings.database_url, limits=settings.repository_limits)
    job = repo.claim(settings.queue_timeout_seconds, settings.retention_seconds)
    if job is None:
        return False
    spawn = mp.get_context("spawn")
    parent, child = spawn.Pipe(duplex=False)
    stop = spawn.Event()
    process = spawn.Process(
        target=_child, args=(job["payload"], settings, child, stop, job["owner"])
    )
    started = time.monotonic()
    request: Request = TypeAdapter(Request).validate_python(job["payload"])
    seconds = (
        request.config.time_limit_seconds
        if isinstance(request, MatrixRequest)
        else request.planning_time_limit_seconds
    )
    # Includes bounded process startup grace; exported separately from solver timings.
    deadline = started + seconds + 5
    reason = None
    stop_at = None
    last: dict = {}
    process.start()
    child.close()
    try:
        while True:
            while parent.poll(0.05):
                try:
                    kind, patch = parent.recv()
                except EOFError:
                    break
                last.update(patch)
                repo.progress(job["job_id"], patch)
                if kind in {"done", "failed"}:
                    if reason and patch.get("result"):
                        patch["result"]["termination_reason"] = reason
                        patch["result"]["optimality_proven"] = False
                        if patch.get("planning_result"):
                            patch["planning_result"]["solve_result"] = patch["result"]
                            patch["planning_result"]["planning_status"] = (
                                "partial"
                                if patch["result"].get("has_feasible_solution")
                                else "failed"
                            )
                    status = "failed" if kind == "failed" or patch.get("error") else "completed"
                    repo.finish(job["job_id"], status, patch, settings.retention_seconds)
                    return True
            if not process.is_alive():
                # Drain any final message before treating exit as a crash.
                if parent.poll():
                    try:
                        kind, patch = parent.recv()
                        last.update(patch)
                        if kind == "done":
                            repo.finish(
                                job["job_id"],
                                "failed" if patch.get("error") else "completed",
                                last,
                                settings.retention_seconds,
                            )
                            return True
                    except EOFError:
                        pass
                reason = reason or "worker_crashed"
                break
            current = repo.get(job["job_id"])
            if current and current["status"] == "cancel_requested":
                reason = "cancelled"
            if time.monotonic() >= deadline:
                reason = reason or "time_limit"
            try:
                handle = psutil.Process(process.pid)
                rss = handle.memory_info().rss + sum(
                    p.memory_info().rss for p in handle.children(recursive=True)
                )
                if rss > request.config.memory_limit_mb * 1024**2:
                    reason = "resource_limit"
            except psutil.Error:
                pass
            if reason:
                stop.set()
                stop_at = stop_at or time.monotonic()
                if time.monotonic() - stop_at >= 1:
                    break
        if (
            not last.get("result")
            and isinstance(request, MatrixRequest)
            and reason in {"time_limit", "resource_limit", "cancelled"}
        ):
            instance = normalize(request.instance)
            last["result"] = SolveResult(
                instance_hash=instance.instance_hash or "",
                backend_name=request.config.backend,
                config_requested=request.config.model_dump(),
                config_effective=request.config.model_dump(),
                unused_vehicle_ids=[v.id for v in instance.vehicles],
                timings={"total_seconds": time.monotonic() - started},
            ).model_dump()
        if last.get("result"):
            last["result"]["termination_reason"] = (
                reason if reason in {"cancelled", "time_limit", "resource_limit"} else "error"
            )
        if last.get("planning_result"):
            last["planning_result"]["planning_status"] = (
                "partial" if last.get("result", {}).get("has_feasible_solution") else "failed"
            )
            last["planning_result"]["solve_result"] = last.get("result")
        last["error"] = {"code": reason, "message": "Execution stopped by supervisor"}
        status = "cancelled" if reason == "cancelled" else "failed"
        if isinstance(request, MatrixRequest) and reason in {"resource_limit", "time_limit"}:
            status = "completed"
        repo.finish(job["job_id"], status, last, settings.retention_seconds)
        return True
    except RouteError as exc:
        # A full quota must stop this child without taking down the worker loop.
        repo.finish(
            job["job_id"],
            "failed",
            {"error": {"code": exc.code, "message": exc.message}},
            settings.retention_seconds,
        )
        return True
    finally:
        stop.set()
        process.join(timeout=1)
        if process.is_alive():
            try:
                for descendant in psutil.Process(process.pid).children(recursive=True):
                    descendant.kill()
            except psutil.Error:
                pass
            process.terminate()
            process.join(timeout=2)
        parent.close()


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    repo = Repository(settings.database_url, limits=settings.repository_limits)

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    if os.name == "nt":
        signal.signal(signal.SIGBREAK, interrupt)
    try:
        with worker_lock(settings.database_path.with_suffix(".worker.lock")):
            repo.recover(settings.retention_seconds)
            logger.info("Worker ready")
            while True:
                if not run_once(settings, repo):
                    time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Worker stopped")
    finally:
        repo.engine.dispose()


if __name__ == "__main__":
    main()
