import platform
import time

from quantum_route_core.domain import ProblemInstance, SolveConfig, SolveResult
from quantum_route_core.errors import RouteError
from quantum_route_core.execution import ExecutionContext
from quantum_route_core.normalization import normalize, validate_euclidean_range
from quantum_route_core.validation import validate_routes


def check_size(instance: ProblemInstance, config: SolveConfig) -> None:
    if (
        len(instance.customers) > config.max_deliveries
        or len(instance.vehicles) > config.max_vehicles
    ):
        raise RouteError("resource_limit", "Delivery or vehicle count exceeds configured limits")
    if instance.cost_matrix is None:
        validate_euclidean_range(instance)


def preflight(instance: ProblemInstance, config: SolveConfig) -> dict:
    check_size(instance, config)
    if config.backend == "quantum":
        raise RouteError(
            "unsupported_configuration",
            "QAOA is gated on a verified QUBO formulation; unavailable in v0.1",
        )
    if config.backend == "exact" and len(instance.customers) > 10:
        raise RouteError("resource_limit", "Exact reference supports at most 10 deliveries")
    return {
        "backend": config.backend,
        "deliveries": len(instance.customers),
        "vehicles": len(instance.vehicles),
        "memory_enforcement": "supervisor RSS monitor in service; cooperative in-process library",
    }


def solve(
    instance: ProblemInstance,
    config: SolveConfig | None = None,
    execution_context: ExecutionContext | None = None,
) -> SolveResult:
    config = config or SolveConfig()
    check_size(instance, config)
    instance = normalize(instance)
    assert instance.instance_hash is not None
    context = execution_context or ExecutionContext(config.time_limit_seconds)
    start = time.monotonic()
    result = SolveResult(instance_hash=instance.instance_hash, backend_name=config.backend)
    try:
        preflight(instance, config)
        context.check()
        if max(c.demand for c in instance.customers) > max(
            v.capacity for v in instance.vehicles
        ) or sum(c.demand for c in instance.customers) > sum(v.capacity for v in instance.vehicles):
            result.infeasibility_proven = True
        elif config.backend == "exact":
            from quantum_route_core.solvers.exact import solve_exact

            result = solve_exact(instance, context)
        else:
            from quantum_route_core.solvers.classical import solve_classical

            result = solve_classical(instance, context)
    except ImportError as exc:
        raise RouteError("missing_dependency", "Install the selected solver extra") from exc
    except RouteError as exc:
        if exc.code not in {
            "time_limit",
            "cancelled",
            "resource_limit",
            "unsupported_configuration",
        }:
            raise
        result.termination_reason = exc.code  # type: ignore[assignment]
        result.diagnostics["reason"] = exc.message
    if result.routes is not None:
        errors, total = validate_routes(instance, result.routes)
        result.validation_errors = errors
        if errors:
            result.routes = None
            result.objective_cost = None
            result.has_feasible_solution = result.optimality_proven = False
            result.termination_reason = "error"
        else:
            result.has_feasible_solution = True
            result.objective_cost = total
            result.solution_origin = config.backend
    used = {r.vehicle_id for r in result.routes or []}
    result.unused_vehicle_ids = [v.id for v in instance.vehicles if v.id not in used]
    result.config_requested = config.model_dump()
    result.config_effective = config.model_dump()
    result.timings["total_seconds"] = time.monotonic() - start
    result.timings.setdefault("first_feasible_seconds", None)
    result.environment = {"python": platform.python_version(), "platform": platform.system()}
    context.publish({"result": result.model_dump()})
    return result
