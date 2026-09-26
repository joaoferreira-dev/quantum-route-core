from pathlib import Path

from quantum_route_core.public import ProblemInstance, SolveConfig, solve

path = Path(__file__).parents[1] / "instances" / "matrix.json"
instance = ProblemInstance.model_validate_json(path.read_text(encoding="utf-8"))
print(solve(instance, SolveConfig(backend="exact")).model_dump_json(indent=2))
