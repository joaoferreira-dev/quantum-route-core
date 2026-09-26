import concurrent.futures
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from quantum_route_core.api.app import create_app
from quantum_route_core.errors import RouteError
from quantum_route_core.jobs.database import Repository, RepositoryLimits, jobs
from quantum_route_core.jobs.worker import run_once


def payload(instance):
    return {"mode": "matrix", "instance": instance.model_dump(), "config": {"backend": "exact"}}


def test_api_worker_lifecycle(settings, instance):
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        submitted = client.post(
            "/v1/optimizations", json=payload(instance), headers={"Idempotency-Key": "test"}
        )
        assert submitted.status_code == 202
        url = submitted.headers["location"]
        assert client.get(url).json()["status"] == "queued"
        assert run_once(settings)
        result = client.get(url).json()
        assert result["status"] == "completed", result
        assert result["result"]["optimality_proven"]
        assert (
            client.post(
                "/v1/optimizations", json=payload(instance), headers={"Idempotency-Key": "test"}
            ).json()["job_id"]
            == result["job_id"]
        )
        changed = payload(instance)
        changed["config"]["time_limit_seconds"] = 2
        assert (
            client.post(
                "/v1/optimizations", json=changed, headers={"Idempotency-Key": "test"}
            ).status_code
            == 409
        )


def test_cancel_queued_and_auth_isolation(settings, instance):
    from pydantic import SecretStr

    settings.auth_tokens = {"a": SecretStr("a" * 32), "b": SecretStr("b" * 32)}
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        a = {"Authorization": "Bearer " + "a" * 32}
        b = {"Authorization": "Bearer " + "b" * 32}
        assert client.post("/v1/optimizations", json=payload(instance)).status_code == 401
        url = client.post("/v1/optimizations", json=payload(instance), headers=a).headers[
            "location"
        ]
        assert client.get(url, headers=b).status_code == 404
        assert client.post(url + "/cancel", headers=b).status_code == 404
        assert client.post(url + "/cancel", headers=a).json()["status"] == "cancelled"
        assert not run_once(settings)


def test_atomic_idempotency(settings, instance):
    repo = Repository(settings.database_url)

    def submit(_):
        return repo.submit("a", "same", "hash", payload(instance), 100, 3600)["job_id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert len(set(pool.map(submit, range(16)))) == 1


def test_recovery_preserves_incumbent_and_queue_expiry(settings, instance):
    repo = Repository(settings.database_url)
    job = repo.submit("a", None, "hash", payload(instance), 100, 3600)
    repo.claim(300, 3600)
    repo.progress(job["job_id"], {"result": {"objective_cost": 123}})
    repo.recover(3600)
    recovered = repo.get(job["job_id"])
    assert (
        recovered["status"] == "failed" and recovered["snapshot"]["result"]["objective_cost"] == 123
    )
    stale = repo.submit("a", None, "hash", payload(instance), 100, 3600)
    with repo.transaction() as db:
        db.execute(
            update(jobs)
            .where(jobs.c.job_id == stale["job_id"])
            .values(created_at=time.time() - 1000)
        )
    assert repo.claim(1, 3600) is None
    assert repo.get(stale["job_id"])["snapshot"]["error"]["code"] == "queue_timeout"


def test_limits_malformed_and_quantum(settings, instance):
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert (
            client.post(
                "/v1/optimizations", content="{broken", headers={"Content-Type": "application/json"}
            ).status_code
            == 400
        )
        data = payload(instance)
        data["config"] = {"backend": "quantum"}
        assert client.post("/v1/optimizations", json=data).status_code == 422
        data["config"] = {"max_deliveries": 16}
        assert client.post("/v1/optimizations", json=data).status_code == 422
        assert client.get("/v1/capabilities").json()["limits"]["max_vehicles"] == 5
        assert (
            "requestBody"
            in client.get("/openapi.json").json()["paths"]["/v1/optimizations"]["post"]
        )


def test_defaults_follow_server_and_openapi(settings, instance):
    settings.max_deliveries = 3
    settings.max_vehicles = 2
    settings.max_memory_mb = 256
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        response = client.post("/v1/optimizations", json=payload(instance))
        assert response.status_code == 202, response.text
        config = response.json()["config_effective"]
        assert config["max_deliveries"] == 3 and config["max_vehicles"] == 2
        assert config["memory_limit_mb"] == 256
        schemas = client.get("/openapi.json").json()["components"]["schemas"]
        assert "OptimizationJob" in schemas and "SolveResult" in schemas
        data = payload(instance)
        data["config"]["max_vehicles"] = 3
        assert client.post("/v1/optimizations", json=data).status_code == 422


def test_road_mode_omitted(settings):
    import json
    from pathlib import Path

    data = json.loads(Path("examples/http/road-request.json").read_text())
    data.pop("mode")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        response = client.post("/v1/optimizations", json=data)
        assert response.status_code == 503, response.text
        assert response.json()["code"] == "provider_not_configured"


def test_queue_full_and_cancel_completion_race(settings, instance):
    settings.queue_capacity = 1
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.post("/v1/optimizations", json=payload(instance)).status_code == 202
        assert client.post("/v1/optimizations", json=payload(instance)).status_code == 429
    repo = Repository(settings.database_url)
    job = repo.claim(300, 3600)
    repo.cancel(job["job_id"], "local", 3600)
    repo.finish(
        job["job_id"],
        "completed",
        {"result": {"has_feasible_solution": True, "termination_reason": "completed"}},
        3600,
    )
    result = repo.get(job["job_id"])
    assert result["status"] == "cancelled"
    assert result["snapshot"]["result"]["termination_reason"] == "cancelled"
    repo.finish(job["job_id"], "completed", {}, 3600)
    assert repo.get(job["job_id"])["status"] == "cancelled"


def test_running_cancellation(settings, instance):
    repo = Repository(settings.database_url)
    data = payload(instance)
    data["config"] = {"backend": "classical", "time_limit_seconds": 20}
    job = repo.submit("local", None, "cancel-test", data, 100, 3600)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_once, settings)
        deadline = time.monotonic() + 10
        while repo.get(job["job_id"])["status"] == "queued":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        repo.cancel(job["job_id"], "local", 3600)
        assert future.result(timeout=15)
    assert repo.get(job["job_id"])["status"] == "cancelled"


def test_supervisor_memory_limit(settings, instance, monkeypatch):
    from types import SimpleNamespace

    import quantum_route_core.jobs.worker as worker

    class OversizedProcess:
        def __init__(self, pid):
            pass

        def memory_info(self):
            return SimpleNamespace(rss=2 * 1024**3)

        def children(self, recursive=False):
            return []

    # Inject a sampled RSS above the limit, without exhausting the test host.
    monkeypatch.setattr(worker.psutil, "Process", OversizedProcess)
    data = payload(instance)
    data["config"] = {"backend": "classical", "time_limit_seconds": 20}
    repo = Repository(settings.database_url)
    job = repo.submit("local", None, "memory", data, 100, 3600)
    assert run_once(settings, repo)
    result = repo.get(job["job_id"])["snapshot"]["result"]
    assert result["termination_reason"] == "resource_limit"
    assert not result["optimality_proven"]


def test_worker_time_limit(settings, instance):
    from quantum_route_core.domain import Customer, Point, ProblemInstance, Vehicle

    # A nontrivial fixture spans coarse Windows monotonic-clock ticks.
    larger = ProblemInstance(
        depot=Point(id="d"),
        customers=[Customer(id=str(i), demand=1) for i in range(10)],
        vehicles=[Vehicle(id="v", capacity=10)],
        node_order=["d", *map(str, range(10))],
        cost_matrix=[[int(i != j) for j in range(11)] for i in range(11)],
    )
    data = payload(larger)
    data["config"]["time_limit_seconds"] = 0.000001
    repo = Repository(settings.database_url)
    job = repo.submit("local", None, "deadline", data, 100, 3600)
    assert run_once(settings, repo)
    result = repo.get(job["job_id"])["snapshot"]["result"]
    assert result["termination_reason"] == "time_limit"
    assert not result["optimality_proven"]


def test_host_header_and_preflight_before_normalization(settings):
    from unittest.mock import patch

    data = {
        "mode": "euclidean",
        "instance": {
            "depot": {"id": "d", "x": 0, "y": 0},
            "customers": [{"id": str(i), "x": i, "y": 0, "demand": 1} for i in range(16)],
            "vehicles": [{"id": "v", "capacity": 20}],
        },
        "config": {"backend": "exact"},
    }
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        with patch("quantum_route_core.application.normalize") as normalization:
            response = client.post("/v1/optimizations", json=data)
        assert response.status_code == 422
        assert normalization.call_count == 0
        assert client.get("/health", headers={"Host": "rebind.attacker.test"}).status_code == 400


def test_extreme_coordinates_rejected_before_job_admission(settings):
    data = {
        "mode": "euclidean",
        "instance": {
            "depot": {"id": "d", "x": 1e308, "y": 0},
            "customers": [{"id": "a", "x": -1e308, "y": 0, "demand": 1}],
            "vehicles": [{"id": "v", "capacity": 1}],
        },
        "config": {"backend": "exact"},
    }
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        response = client.post("/v1/optimizations", json=data)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_input"


def test_expired_terminal_job_is_hidden_from_get_and_cancel(settings, instance):
    repo = Repository(settings.database_url)
    job = repo.submit("local", None, "expired", payload(instance), 100, 3600)
    repo.finish(job["job_id"], "completed", {}, 60)
    with repo.transaction() as db:
        db.execute(
            update(jobs).where(jobs.c.job_id == job["job_id"]).values(expires_at=time.time() - 1)
        )
    assert repo.get(job["job_id"], "local") is None
    assert repo.cancel(job["job_id"], "local", 60) is None


def test_owner_admission_limit_is_independent(settings, instance):
    repo = Repository(
        settings.database_url,
        limits=RepositoryLimits(
            owner_pending=1,
            submissions_per_minute=10,
            owner_bytes=5000,
            total_bytes=20000,
            snapshot_bytes=4000,
            min_free_disk_mb=1,
        ),
    )
    data = payload(instance)
    oversized = {**data, "extra": "x" * 6000}
    with pytest.raises(RouteError, match="Integrator storage quota"):
        repo.submit("integrator-storage", None, "large", oversized, 100, 3600)
    repo.submit("integrator-a", None, "one", data, 100, 3600)
    with pytest.raises(RouteError, match="Integrator active job"):
        repo.submit("integrator-a", None, "two", data, 100, 3600)
    repo.submit("integrator-b", None, "three", data, 100, 3600)
