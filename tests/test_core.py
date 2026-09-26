import itertools
import subprocess
import sys

import pytest

from quantum_route_core.domain import ProblemInstance, Route, SolveConfig
from quantum_route_core.errors import RouteError
from quantum_route_core.normalization import normalize
from quantum_route_core.public import solve
from quantum_route_core.validation import validate_routes


def brute_cost(instance):
    """Independent permutation/cut oracle for a tiny two-vehicle fixture."""
    order = instance.node_order
    costs = []
    for permutation in itertools.permutations(instance.customers):
        for cut in range(len(permutation) + 1):
            groups = [permutation[:cut], permutation[cut:]]
            if any(
                sum(c.demand for c in group) > vehicle.capacity
                for group, vehicle in zip(groups, instance.vehicles, strict=False)
            ):
                continue
            cost = 0
            for group in groups:
                stops = [instance.depot.id, *(c.id for c in group), instance.depot.id]
                cost += sum(
                    instance.cost_matrix[order.index(a)][order.index(b)]
                    for a, b in zip(stops, stops[1:], strict=False)
                )
            costs.append(cost)
    return min(costs)


def test_exact_matches_independent_enumeration(instance):
    result = solve(instance, SolveConfig(backend="exact"))
    assert result.optimality_proven and result.has_feasible_solution
    assert result.objective_cost == brute_cost(instance)
    assert not validate_routes(normalize(instance), result.routes)[0]


def test_classical_heterogeneous_and_asymmetric(instance):
    # This checks routing correctness; cold native-library import latency is not
    # part of this fixture's two-second search budget.
    pytest.importorskip("ortools.constraint_solver.pywrapcp")
    pytest.importorskip("ortools.constraint_solver.routing_enums_pb2")
    result = solve(instance, SolveConfig(time_limit_seconds=2))
    assert result.has_feasible_solution
    assert result.objective_cost >= brute_cost(instance)
    assert not result.optimality_proven
    assert next(r for r in result.routes if r.vehicle_id == "small").load <= 3


def test_hash_is_order_independent(instance):
    original = normalize(instance)
    data = instance.model_dump()
    permutation = [2, 0, 3, 1]
    data["node_order"] = [instance.node_order[i] for i in permutation]
    data["cost_matrix"] = [[instance.cost_matrix[i][j] for j in permutation] for i in permutation]
    data["customers"].reverse()
    data["vehicles"].reverse()
    data["instance_id"] = "different name"
    assert normalize(ProblemInstance.model_validate(data)).instance_hash == original.instance_hash
    data["vehicles"][0]["capacity"] += 1
    assert normalize(ProblemInstance.model_validate(data)).instance_hash != original.instance_hash


def test_bin_packing_infeasibility(instance):
    data = instance.model_dump()
    for c in data["customers"]:
        c["demand"] = 6
    for v in data["vehicles"]:
        v["capacity"] = 10
    result = solve(ProblemInstance.model_validate(data), SolveConfig(backend="exact"))
    assert result.infeasibility_proven and result.objective_cost is None


def test_validator_does_not_trust_solver(instance):
    route = Route(vehicle_id="small", stop_ids=["depot", "a", "depot"], load=6, objective_cost=0)
    errors, _ = validate_routes(normalize(instance), [route, route])
    assert {
        "capacity_exceeded",
        "incorrect_cost",
        "repeated_vehicle",
        "customers_omitted_or_repeated",
    } <= set(errors)


def test_zero_cost_optimum(instance):
    data = instance.model_dump()
    data["cost_matrix"] = [[0] * 4 for _ in range(4)]
    result = solve(ProblemInstance.model_validate(data), SolveConfig(backend="exact"))
    assert result.has_feasible_solution and result.objective_cost == 0


def test_core_import_does_not_load_adapters():
    code = "import quantum_route_core.public, sys; assert not any(x in sys.modules for x in ['fastapi','sqlalchemy','httpx','ortools','qiskit','typer'])"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_quantum_explicitly_unavailable(instance):
    result = solve(instance, SolveConfig(backend="quantum"))
    assert result.termination_reason == "unsupported_configuration"
    assert result.objective_cost is None


@pytest.mark.parametrize("field,value", [("capacity", 0), ("capacity", True)])
def test_invalid_capacity_rejected(instance, field, value):
    data = instance.model_dump()
    data["vehicles"][0][field] = value
    with pytest.raises(ValueError):
        ProblemInstance.model_validate(data)


def test_extreme_euclidean_coordinates_return_validation_error():
    from quantum_route_core.domain import Customer, Point, Vehicle

    instance = ProblemInstance(
        depot=Point(id="d", x=1e308, y=0),
        customers=[Customer(id="a", x=-1e308, y=0, demand=1)],
        vehicles=[Vehicle(id="v", capacity=1)],
    )
    with pytest.raises(RouteError, match="cost range"):
        normalize(instance)
