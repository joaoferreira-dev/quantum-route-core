import json
import random
from pathlib import Path

import typer

from quantum_route_core.domain import Customer, Point, ProblemInstance, SolveConfig, Vehicle
from quantum_route_core.public import normalize, preflight, solve

app = typer.Typer(help="Quantum Route Core — local diagnostics and reproducible experiments")


@app.command("generate")
def generate(
    customers: int = 5,
    vehicles: int = 2,
    capacity: int = 10,
    seed: int = 42,
    output: Path = Path("instance.json"),
):
    if customers < 1 or vehicles < 1 or capacity < 1 or customers > vehicles * capacity:
        raise typer.BadParameter("Provide positive counts and enough capacity for unit demands")
    rng = random.Random(seed)
    instance = ProblemInstance(
        depot=Point(id="depot", x=0, y=0),
        customers=[
            Customer(id=f"delivery-{i + 1}", x=rng.uniform(0, 10), y=rng.uniform(0, 10), demand=1)
            for i in range(customers)
        ],
        vehicles=[Vehicle(id=f"vehicle-{i + 1}", capacity=capacity) for i in range(vehicles)],
        cost_scale=1000,
        cost_units="synthetic_units",
        metadata={"generator_seed": seed, "generator_version": "1"},
    )
    output.write_text(normalize(instance).model_dump_json(indent=2), encoding="utf-8")
    typer.echo(str(output))


@app.command("validate")
def validate(path: Path):
    instance = normalize(ProblemInstance.model_validate_json(path.read_text(encoding="utf-8")))
    typer.echo(json.dumps({"valid_input": True, "instance_hash": instance.instance_hash}))


@app.command("preflight")
def check(path: Path, backend: str = "classical"):
    instance = normalize(ProblemInstance.model_validate_json(path.read_text(encoding="utf-8")))
    typer.echo(json.dumps(preflight(instance, SolveConfig(backend=backend))))  # type: ignore[arg-type]


@app.command("solve")
def resolve(
    path: Path,
    backend: str = "classical",
    time_limit: float = 5,
    output: Path = Path("result.json"),
):
    instance = ProblemInstance.model_validate_json(path.read_text(encoding="utf-8"))
    result = solve(instance, SolveConfig(backend=backend, time_limit_seconds=time_limit))  # type: ignore[arg-type]
    output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(
        json.dumps(
            {
                "feasible": result.has_feasible_solution,
                "objective_cost": result.objective_cost,
                "termination": result.termination_reason,
                "output": str(output),
            }
        )
    )


@app.command("benchmark")
def benchmark(manifest: Path, output_dir: Path = Path("results")):
    from quantum_route_core.experiments import run_manifest

    run_manifest(manifest, output_dir)
    typer.echo(str(output_dir))
