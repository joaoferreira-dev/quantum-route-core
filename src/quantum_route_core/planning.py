import math
import time

from quantum_route_core.application import preflight, solve
from quantum_route_core.domain import PlanningResult, ProblemInstance, RoadRequest
from quantum_route_core.errors import RouteError
from quantum_route_core.execution import ExecutionContext
from quantum_route_core.normalization import normalize, request_hash
from quantum_route_core.routing.base import RoutingProvider


def plan_deliveries(
    request: RoadRequest,
    routing_provider: RoutingProvider,
    execution_context: ExecutionContext | None = None,
    *,
    area_path: str | None = None,
) -> PlanningResult:
    context = execution_context or ExecutionContext(request.planning_time_limit_seconds)
    output = PlanningResult(planning_status="failed", request_hash=request_hash(request))
    start = time.monotonic()
    try:
        from quantum_route_core.routing.area import validate_area

        preflight(
            ProblemInstance(
                depot=request.depot,
                customers=request.deliveries,
                vehicles=request.vehicles,
            ),
            request.config,
        )
        validate_area(request, area_path)
        points = [request.depot, *request.deliveries]
        coordinates = [[p.longitude, p.latitude] for p in points]
        cache = request.config.cache_policy == "use"
        phase = time.monotonic()
        road = routing_provider.prepare(coordinates, request.routing, context, cache)  # type: ignore[arg-type]
        output.timings["matrix_seconds"] = time.monotonic() - phase
        metric = "durations" if request.routing.objective_metric == "travel_time" else "distances"
        matrix = [[math.floor(value + 0.5) for value in row] for row in road[metric]]
        instance = normalize(
            ProblemInstance(
                depot=request.depot,
                customers=request.deliveries,
                vehicles=request.vehicles,
                node_order=[p.id for p in points],
                cost_matrix=matrix,
                cost_units="seconds" if metric == "durations" else "meters",
                distance_rule="road",
            )
        )
        output.instance_hash = instance.instance_hash
        output.locations = [
            {
                "id": point.id,
                "requested_location": coordinates[i],
                "snapped_location": road["locations"][i]["location"],
                "snap_distance_meters": road["locations"][i]["snapped_distance"],
            }
            for i, point in enumerate(points)
        ]
        output.routing_metadata = {
            "provider": "openrouteservice",
            "profile": request.routing.profile,
            "options": request.routing.model_dump(),
            "matrix": road.get("metadata", {}),
            "attribution": "© openrouteservice.org © OpenStreetMap contributors",
            "queried_at_unix": time.time(),
            "cost_semantics": "distance/time along fastest road paths",
            "rounding": "half_up",
            "cache_policy": request.config.cache_policy,
        }
        context.publish({"instance": instance.model_dump(), "planning_result": output.model_dump()})
        context.check()
        budget = min(
            request.config.time_limit_seconds,
            max(0.001, context.remaining - min(10, context.remaining / 3)),
        )
        solver_context = ExecutionContext(budget, context.cancelled, context.publish)
        result = solve(instance, request.config, solver_context)
        output.solve_result = result
        output.timings["solver_seconds"] = result.timings["total_seconds"] or 0
        output.unused_vehicle_ids = result.unused_vehicle_ids
        if not result.has_feasible_solution:
            output.planning_status = "no_feasible_solution"
            return output
        output.planning_status = "partial"
        by_id = {loc["id"]: loc["snapped_location"] for loc in output.locations}
        output.vehicle_routes = [
            {
                "vehicle_id": r.vehicle_id,
                "ordered_stop_ids": r.stop_ids,
                "load": r.load,
                "objective_cost": r.objective_cost,
                "geometry_status": "pending",
                "geometry": None,
                "legs": None,
                "distance_meters": None,
                "travel_duration_seconds": None,
            }
            for r in result.routes or []
        ]
        context.publish({"planning_result": output.model_dump(), "result": result.model_dump()})
        phase = time.monotonic()
        for route in output.vehicle_routes:
            context.check()
            details = routing_provider.directions(
                [by_id[key] for key in route["ordered_stop_ids"]], request.routing, context, cache
            )
            route.update({key: value for key, value in details.items() if key != "metadata"})
            route["geometry_status"] = "ready"
            for i, leg in enumerate(route["legs"]):
                leg.update(
                    from_id=route["ordered_stop_ids"][i], to_id=route["ordered_stop_ids"][i + 1]
                )
            comparison = (
                details["travel_duration_seconds"]
                if metric == "durations"
                else details["distance_meters"]
            )
            if abs(comparison - route["objective_cost"]) > max(5, route["objective_cost"] * 0.1):
                output.warnings.append(
                    f"Matrix/directions differ by more than tolerance for {route['vehicle_id']}"
                )
            context.publish({"planning_result": output.model_dump()})
        output.timings["directions_seconds"] = time.monotonic() - phase
        output.planning_status = "ready"
    except RouteError as exc:
        output.errors.append({"code": exc.code, "message": exc.message})
        output.planning_status = (
            "partial"
            if output.solve_result and output.solve_result.has_feasible_solution
            else "failed"
        )
    finally:
        output.timings["total_seconds"] = time.monotonic() - start
        output.routing_metadata["calls"] = getattr(routing_provider, "calls", None)
        output.routing_metadata["cache_hits"] = getattr(routing_provider, "cache_hits", None)
        context.publish({"planning_result": output.model_dump()})
    return output
