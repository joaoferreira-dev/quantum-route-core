import socket
import time

import httpx

from quantum_route_core import dev


def test_dev_migrates_serves_executes_job_and_stops(tmp_path, monkeypatch, instance):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv("QROUTE_DATABASE_URL", f"sqlite:///{tmp_path / 'dev.db'}")
    monkeypatch.setenv("QROUTE_NETWORK_MODE", "false")
    monkeypatch.setenv("QROUTE_AUTH_TOKENS", "{}")
    monkeypatch.setenv("QROUTE_ADMISSION_ENABLED", "true")
    monkeypatch.setattr("sys.argv", ["dev", "--port", str(port)])
    children = []

    def exercise(processes):
        children.extend(processes)
        deadline = time.monotonic() + 30
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            while True:
                assert all(p.poll() is None for p in processes)
                assert time.monotonic() < deadline, "API did not start"
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            assert client.get("/docs").status_code == 200
            response = client.post(
                "/v1/optimizations",
                json={
                    "mode": "matrix",
                    "instance": instance.model_dump(),
                    "config": {"backend": "exact"},
                },
            )
            assert response.status_code == 202, response.text
            while True:
                job = client.get(response.headers["location"]).json()
                if job["status"] in {"completed", "failed", "cancelled"}:
                    break
                assert time.monotonic() < deadline, "Worker did not finish"
                time.sleep(0.1)
            assert job["status"] == "completed", job
            assert job["result"]["has_feasible_solution"]
        raise KeyboardInterrupt

    monkeypatch.setattr(dev, "monitor", exercise)
    dev.main()
    assert len(children) == 2
    assert all(p.poll() is not None for p in children)
