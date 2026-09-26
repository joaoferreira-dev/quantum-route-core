"""Explicit sequential road evaluation; dry-run by default, no hidden calls."""

import argparse
import json
from collections import Counter
from pathlib import Path

from quantum_route_core.api.settings import Settings
from quantum_route_core.domain import RoadRequest
from quantum_route_core.experiments import distribution
from quantum_route_core.planning import plan_deliveries
from quantum_route_core.routing.area import validate_area
from quantum_route_core.routing.providers.openrouteservice import OpenRouteService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--cache", choices=["off", "use"], default="off")
    parser.add_argument("--output", type=Path, default=Path("results/road"))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 100:
        parser.error("repetitions must be between 1 and 100")
    settings = Settings()
    request = RoadRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
    validate_area(request, settings.area_path)
    request.config.cache_policy = args.cache
    from quantum_route_core.application import preflight
    from quantum_route_core.domain import ProblemInstance

    preflight(
        ProblemInstance(
            depot=request.depot, customers=request.deliveries, vehicles=request.vehicles
        ),
        request.config,
    )
    if len(request.deliveries) > 15 or len(request.vehicles) > 5:
        parser.error("evaluation runner is limited to the initial 15-delivery/5-vehicle pilot")
    plan = {
        "repetitions": args.repetitions,
        "cache": args.cache,
        "deliveries": len(request.deliveries),
        "vehicles": len(request.vehicles),
        "maximum_calls_with_retries": args.repetitions * 3 * (2 + len(request.vehicles)),
        "executed": args.execute,
    }
    print(json.dumps(plan))
    if not args.execute:
        return
    if args.cache == "use" and settings.ors_cache_ttl <= 0:
        parser.error("cache use requires an explicitly configured positive ORS cache TTL")
    if not settings.ors_api_key.get_secret_value():
        parser.error("configure ORS_API_KEY locally before execution")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "request.json").write_text(request.model_dump_json(indent=2), encoding="utf-8")
    results = []
    for index in range(args.repetitions):
        provider = OpenRouteService(
            settings.ors_api_key.get_secret_value(),
            settings.ors_base_url,
            settings.ors_ledger_path,
            settings.ors_cache_ttl,
            limits={
                "matrix": (settings.ors_matrix_daily, settings.ors_matrix_minute),
                "snap": (settings.ors_snap_daily, settings.ors_snap_minute),
                "directions": (settings.ors_directions_daily, settings.ors_directions_minute),
            },
        )
        try:
            result = plan_deliveries(request, provider, area_path=settings.area_path)
            results.append(result)
            (args.output / f"run-{index:04d}.json").write_text(
                result.model_dump_json(indent=2), encoding="utf-8"
            )
        finally:
            provider.close()
    groups = {"all": results}
    if args.cache == "use":
        groups = {"initial_request": results[:1], "subsequent_requests": results[1:]}
    summary = {
        name: {
            "count": len(runs),
            "ready": sum(r.planning_status == "ready" for r in runs),
            "errors": dict(Counter(e["code"] for r in runs for e in r.errors)),
            "calls": sum(r.routing_metadata.get("calls", 0) for r in runs),
            "cache_hits": sum(r.routing_metadata.get("cache_hits", 0) for r in runs),
            "timings": {
                phase: distribution([r.timings[phase] for r in runs if phase in r.timings])
                for phase in [
                    "matrix_seconds",
                    "solver_seconds",
                    "directions_seconds",
                    "total_seconds",
                ]
            },
        }
        for name, runs in groups.items()
    }
    (args.output / "summary.json").write_text(
        json.dumps(
            {
                "plan": plan,
                "groups": summary,
                "method": "p50 median; p95 nearest rank; missing phases excluded with counts",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
