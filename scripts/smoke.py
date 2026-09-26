"""Explicit end-to-end API checks; --road consumes ORS quota."""

import argparse
import json
import os
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--road", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
token = os.environ.get("QROUTE_SMOKE_TOKEN", "")
headers = {"Authorization": f"Bearer {token}"} if token else {}
if args.road:
    payload = json.loads((root / "examples/http/road-request.json").read_text(encoding="utf-8"))
else:
    payload = {
        "mode": "matrix",
        "instance": json.loads(
            (root / "examples/instances/matrix.json").read_text(encoding="utf-8")
        ),
        "config": {"backend": "classical", "time_limit_seconds": 2},
    }
with httpx.Client(base_url=args.url, headers=headers, timeout=10) as client:
    client.get("/health").raise_for_status()
    response = client.post("/v1/optimizations", json=payload)
    response.raise_for_status()
    location = response.headers["Location"]
    until = time.monotonic() + 150
    while time.monotonic() < until:
        response = client.get(location)
        response.raise_for_status()
        job = response.json()
        if job["status"] in {"completed", "cancelled", "failed"}:
            if job["status"] != "completed" or not (job.get("result") or {}).get(
                "has_feasible_solution"
            ):
                raise SystemExit(f"Smoke failed: {job['status']} {job.get('error')}")
            if args.road and job["planning_status"] != "ready":
                raise SystemExit("Road smoke incomplete")
            print(
                json.dumps(
                    {
                        "job_id": job["job_id"],
                        "status": job["status"],
                        "planning_status": job["planning_status"],
                    }
                )
            )
            break
        time.sleep(0.3)
    else:
        raise SystemExit("Smoke deadline expired")
