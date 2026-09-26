"""Held-Karp subset tours + heterogeneous vehicle assignment, independent of OR-Tools."""

from quantum_route_core.domain import ProblemInstance, Route, SolveResult
from quantum_route_core.execution import ExecutionContext


def solve_exact(instance: ProblemInstance, context: ExecutionContext) -> SolveResult:
    matrix = instance.cost_matrix
    assert matrix is not None and instance.instance_hash is not None
    ids = [c.id for c in instance.customers]
    index = {key: i for i, key in enumerate(instance.node_order)}
    depot = index[instance.depot.id]
    n = len(ids)
    size = 1 << n
    demands = [c.demand for c in instance.customers]
    weights = [0] * size
    tours: dict[int, tuple[int, list[int]]] = {0: (0, [])}
    paths: dict[tuple[int, int], tuple[int, list[int]]] = {}
    max_capacity = max(v.capacity for v in instance.vehicles)
    for mask in range(1, size):
        context.check()
        bit = mask & -mask
        weights[mask] = weights[mask ^ bit] + demands[bit.bit_length() - 1]
        if weights[mask] > max_capacity:
            continue
        for last in range(n):
            if not mask & (1 << last):
                continue
            rest = mask ^ (1 << last)
            node = index[ids[last]]
            if rest == 0:
                paths[mask, last] = (matrix[depot][node], [last])
            else:
                candidates = [
                    (cost + matrix[index[ids[prev]]][node], route + [last])
                    for prev in range(n)
                    if (item := paths.get((rest, prev)))
                    for cost, route in [item]
                ]
                paths[mask, last] = min(candidates)
        tours[mask] = min(
            (cost + matrix[index[ids[last]]][depot], route)
            for last in range(n)
            if (item := paths.get((mask, last)))
            for cost, route in [item]
        )
    states: dict[int, tuple[int, list[int]]] = {0: (0, [])}
    full = size - 1
    for vehicle in instance.vehicles:
        next_states: dict[int, tuple[int, list[int]]] = {}
        for covered, (cost, assignments) in states.items():
            context.check()
            remaining = full ^ covered
            subset = remaining
            while True:
                if weights[subset] <= vehicle.capacity and subset in tours:
                    candidate = (cost + tours[subset][0], assignments + [subset])
                    new_mask = covered | subset
                    if new_mask not in next_states or candidate < next_states[new_mask]:
                        next_states[new_mask] = candidate
                if subset == 0:
                    break
                subset = (subset - 1) & remaining
        states = next_states
    result = SolveResult(instance_hash=instance.instance_hash, backend_name="exact")
    if full not in states:
        result.infeasibility_proven = True
        return result
    _, assignments = states[full]
    result.routes = [
        Route(
            vehicle_id=v.id,
            stop_ids=[instance.depot.id, *(ids[i] for i in tours[mask][1]), instance.depot.id],
            load=weights[mask],
            objective_cost=tours[mask][0],
        )
        for v, mask in zip(instance.vehicles, assignments, strict=False)
        if mask
    ]
    result.optimality_proven = True
    return result
