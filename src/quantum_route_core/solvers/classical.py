import time

import ortools
from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from quantum_route_core.domain import ProblemInstance, Route, SolveResult
from quantum_route_core.execution import ExecutionContext
from quantum_route_core.validation import validate_routes


def solve_classical(instance: ProblemInstance, context: ExecutionContext) -> SolveResult:
    assert instance.cost_matrix is not None and instance.instance_hash is not None
    matrix = instance.cost_matrix
    order = instance.node_order
    manager = pywrapcp.RoutingIndexManager(
        len(order), len(instance.vehicles), order.index(instance.depot.id)
    )
    routing = pywrapcp.RoutingModel(manager)
    callback = routing.RegisterTransitCallback(
        lambda a, b: matrix[manager.IndexToNode(a)][manager.IndexToNode(b)]
    )
    routing.SetArcCostEvaluatorOfAllVehicles(callback)
    demands = {c.id: c.demand for c in instance.customers}
    demand_callback = routing.RegisterUnaryTransitCallback(
        lambda a: demands.get(order[manager.IndexToNode(a)], 0)
    )
    routing.AddDimensionWithVehicleCapacity(
        demand_callback, 0, [v.capacity for v in instance.vehicles], True, "Capacity"
    )
    parameters = pywrapcp.DefaultRoutingSearchParameters()
    parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    parameters.time_limit.FromMilliseconds(max(1, int(context.remaining * 1000)))
    result = SolveResult(
        instance_hash=instance.instance_hash,
        backend_name="classical",
        backend_version=ortools.__version__,
    )

    def extract(next_value):
        routes = []
        for vehicle_idx, vehicle in enumerate(instance.vehicles):
            current = routing.Start(vehicle_idx)
            stops = [instance.depot.id]
            while not routing.IsEnd(current):
                current = next_value(routing.NextVar(current))
                stops.append(order[manager.IndexToNode(current)])
            if len(stops) > 2:
                cost = sum(
                    matrix[order.index(a)][order.index(b)]
                    for a, b in zip(stops, stops[1:], strict=False)
                )
                routes.append(
                    Route(
                        vehicle_id=vehicle.id,
                        stop_ids=stops,
                        load=sum(demands.get(s, 0) for s in stops),
                        objective_cost=cost,
                    )
                )
        return routes

    best = float("inf")

    def incumbent():
        nonlocal best
        if context.cancelled():
            routing.solver().FinishCurrentSearch()
        objective = routing.CostVar().Value()
        if objective >= best:
            return
        candidate = extract(lambda var: var.Value())
        errors, cost = validate_routes(instance, candidate)
        if not errors:
            best = cost
            result.routes = candidate
            result.has_feasible_solution = True
            result.objective_cost = cost
            result.unused_vehicle_ids = [
                v.id for v in instance.vehicles if v.id not in {r.vehicle_id for r in candidate}
            ]
            result.timings.setdefault("first_feasible_seconds", time.monotonic() - context.started)
            context.publish({"result": result.model_dump()})

    routing.AddAtSolutionCallback(incumbent)
    solution = routing.SolveWithParameters(parameters)
    if solution:
        result.routes = extract(solution.Value)
    result.diagnostics = {
        "routing_status": routing.status(),
        "first_solution_strategy": "PATH_CHEAPEST_ARC",
        "local_search": "GUIDED_LOCAL_SEARCH",
    }
    if context.cancelled():
        result.termination_reason = "cancelled"
    elif context.remaining < 0.02:
        result.termination_reason = "time_limit"
    return result
