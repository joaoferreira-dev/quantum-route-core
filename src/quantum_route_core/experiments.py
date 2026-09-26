import csv
import json
import math
import statistics
from pathlib import Path

from quantum_route_core.application import solve
from quantum_route_core.domain import ProblemInstance, SolveConfig
from quantum_route_core.normalization import normalize


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "p50": None, "p95": None, "min": None, "max": None, "stdev": None}
    return {
        "count": len(ordered),
        "p50": statistics.median(ordered),
        "p95": ordered[math.ceil(0.95 * len(ordered)) - 1],
        "min": ordered[0],
        "max": ordered[-1],
        "stdev": statistics.stdev(ordered) if len(ordered) > 1 else None,
    }


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault((row["instance_hash"], row["backend"], row["configuration"]), []).append(
            row
        )
    output = []
    for (instance_hash, backend, configuration), runs in groups.items():
        feasible = [r for r in runs if r["feasible"]]
        output.append(
            {
                "instance_hash": instance_hash,
                "backend": backend,
                "configuration": json.loads(configuration),
                "count": len(runs),
                "feasible_count": len(feasible),
                "success_rate": len(feasible) / len(runs),
                "terminations": {
                    reason: sum(r["termination"] == reason for r in runs)
                    for reason in sorted({r["termination"] for r in runs})
                },
                "seconds_all_runs": distribution([r["seconds"] for r in runs]),
                "cost_feasible_only": distribution([r["cost"] for r in feasible]),
                "absolute_gap_with_reference": distribution(
                    [r["absolute_gap"] for r in feasible if r["absolute_gap"] is not None]
                ),
                "percentile_method": "p50 median; p95 nearest rank; no confidence interval",
            }
        )
    return output


def run_manifest(path: Path, output: Path) -> None:
    """Exact references must be supplied explicitly, never silently computed."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, entry in enumerate(manifest["runs"]):
        instance = normalize(
            ProblemInstance.model_validate_json(
                (path.parent / entry["instance"]).read_text(encoding="utf-8")
            )
        )
        result = solve(instance, SolveConfig.model_validate(entry.get("config", {})))
        absolute = relative = None
        if entry.get("reference"):
            from quantum_route_core.domain import SolveResult
            from quantum_route_core.validation import validate_routes

            reference = SolveResult.model_validate_json(
                (path.parent / entry["reference"]).read_text(encoding="utf-8")
            )
            errors, cost = validate_routes(instance, reference.routes or [])
            if (
                not reference.optimality_proven
                or reference.instance_hash != instance.instance_hash
                or errors
                or reference.objective_cost != cost
            ):
                raise ValueError("Reference is not a validated, matching exact optimum")
            if result.has_feasible_solution:
                assert result.objective_cost is not None
                absolute = result.objective_cost - cost
                if absolute < 0:
                    raise ValueError("Negative gap: invalid reference or solver result")
                relative = 100 * absolute / cost if cost else None
        filename = f"run-{i:04d}.json"
        (output / filename).write_text(result.model_dump_json(indent=2), encoding="utf-8")
        rows.append(
            {
                "artifact": filename,
                "instance_hash": result.instance_hash,
                "backend": result.backend_name,
                "feasible": result.has_feasible_solution,
                "termination": result.termination_reason,
                "cost": result.objective_cost,
                "seconds": result.timings["total_seconds"],
                "absolute_gap": absolute,
                "relative_gap_percent": relative,
                "configuration": json.dumps(result.config_effective, sort_keys=True),
            }
        )
    if rows:
        with (output / "runs.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summarize(rows), indent=2), encoding="utf-8")
