from collections import Counter

from quantum_route_core.domain import ProblemInstance, Route


def validate_routes(instance: ProblemInstance, routes: list[Route]) -> tuple[list[str], int]:
    errors: list[str] = []
    customers = {c.id: c.demand for c in instance.customers}
    vehicles = {v.id: v.capacity for v in instance.vehicles}
    index = {key: i for i, key in enumerate(instance.node_order)}
    visits: list[str] = []
    used: list[str] = []
    total = 0
    assert instance.cost_matrix is not None
    for route in routes:
        used.append(route.vehicle_id)
        stops = route.stop_ids
        if len(stops) < 3 or stops[0] != instance.depot.id or stops[-1] != instance.depot.id:
            errors.append("malformed_route")
            continue
        if instance.depot.id in stops[1:-1]:
            errors.append("internal_depot")
        visits.extend(stops[1:-1])
        if any(s not in index for s in stops):
            errors.append("unknown_stop")
            continue
        load = sum(customers.get(s, 0) for s in stops[1:-1])
        cost = sum(
            instance.cost_matrix[index[a]][index[b]] for a, b in zip(stops, stops[1:], strict=False)
        )
        if route.vehicle_id not in vehicles:
            errors.append("unknown_vehicle")
        elif load > vehicles[route.vehicle_id]:
            errors.append("capacity_exceeded")
        if load != route.load:
            errors.append("incorrect_load")
        if cost != route.objective_cost:
            errors.append("incorrect_cost")
        total += cost
    if len(used) != len(set(used)):
        errors.append("repeated_vehicle")
    if Counter(visits) != Counter(customers.keys()):
        errors.append("customers_omitted_or_repeated")
    return errors, total
