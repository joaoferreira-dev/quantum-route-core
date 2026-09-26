import json
from pathlib import Path

from quantum_route_core.experiments import distribution, run_manifest, summarize


def test_summary_keeps_failures_and_zero_optimum():
    rows = [
        {
            "instance_hash": "h",
            "backend": "exact",
            "configuration": "{}",
            "feasible": True,
            "termination": "completed",
            "seconds": 1,
            "cost": 0,
            "absolute_gap": 0,
        },
        {
            "instance_hash": "h",
            "backend": "exact",
            "configuration": "{}",
            "feasible": False,
            "termination": "time_limit",
            "seconds": 3,
            "cost": None,
            "absolute_gap": None,
        },
    ]
    group = summarize(rows)[0]
    assert group["success_rate"] == 0.5
    assert group["seconds_all_runs"]["count"] == 2
    assert group["cost_feasible_only"]["count"] == 1
    assert group["absolute_gap_with_reference"]["p50"] == 0
    assert distribution([])["p95"] is None


def test_manifest_export(tmp_path):
    output = tmp_path / "benchmark"
    run_manifest(Path("examples/benchmarks/classical.json"), output)
    assert (output / "runs.csv").is_file()
    summary = json.loads((output / "summary.json").read_text())
    assert len(summary) == 2
    assert all(group["count"] == 1 for group in summary)
