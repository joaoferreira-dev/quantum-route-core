import json

import httpx
import pytest

from quantum_route_core.domain import RoadRequest
from quantum_route_core.errors import RouteError
from quantum_route_core.execution import ExecutionContext
from quantum_route_core.planning import plan_deliveries
from quantum_route_core.routing.area import validate_area
from quantum_route_core.routing.providers.openrouteservice import OpenRouteService


@pytest.fixture
def road_request():
    return RoadRequest.model_validate(
        {
            "depot": {"id": "d", "latitude": -23.5505, "longitude": -46.6333},
            "deliveries": [
                {"id": "a", "latitude": -23.5614, "longitude": -46.6559, "demand": 6},
                {"id": "b", "latitude": -23.5874, "longitude": -46.6576, "demand": 3},
            ],
            "vehicles": [{"id": "large", "capacity": 6}, {"id": "small", "capacity": 3}],
            "config": {"backend": "exact"},
        }
    )


def handler(request):
    """Synthetic network responses, not evidence of real road coverage."""
    body = json.loads(request.content)
    if "/snap/" in request.url.path:
        return httpx.Response(
            200,
            json={"locations": [{"location": c, "snapped_distance": 1} for c in body["locations"]]},
        )
    if "/matrix/" in request.url.path:
        n = len(body["locations"])
        return httpx.Response(
            200,
            json={
                "durations": [
                    [0 if a == b else 100 + 10 * a + b for b in range(n)] for a in range(n)
                ],
                "distances": [[0 if a == b else 1000 for b in range(n)] for a in range(n)],
            },
        )
    return httpx.Response(
        200,
        json={
            "features": [
                {
                    "geometry": {"type": "LineString", "coordinates": body["coordinates"]},
                    "properties": {
                        "way_points": list(range(len(body["coordinates"]))),
                        "segments": [
                            {"distance": 1000, "duration": 100} for _ in body["coordinates"][1:]
                        ],
                    },
                }
            ]
        },
    )


def provider(tmp_path, callback=handler, **kwargs):
    return OpenRouteService(
        "test-key-not-real",
        ledger_path=str(tmp_path / "ors.sqlite"),
        client=httpx.Client(transport=httpx.MockTransport(callback)),
        **kwargs,
    )


def test_complete_road_pipeline(tmp_path, road_request):
    output = plan_deliveries(road_request, provider(tmp_path))
    assert output.planning_status == "ready", output
    assert len(output.vehicle_routes) == 2
    assert output.solve_result.optimality_proven
    assert {r["vehicle_id"] for r in output.vehicle_routes} == {"large", "small"}
    assert all(r["geometry"]["type"] == "LineString" for r in output.vehicle_routes)


def test_geometry_failure_preserves_valid_solution(tmp_path, road_request):
    def failure(request):
        if "/directions/" in request.url.path:
            return httpx.Response(400, json={"error": "bad request"})
        return handler(request)

    result = plan_deliveries(road_request, provider(tmp_path, failure))
    assert result.planning_status == "partial"
    assert result.solve_result.has_feasible_solution
    assert result.errors[0]["code"] == "provider_rejected"
    assert all(r["geometry"] is None for r in result.vehicle_routes)


def test_unreachable_matrix_does_not_invoke_solver(tmp_path, road_request):
    def unreachable(request):
        if "/matrix/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "durations": [[None] * 3 for _ in range(3)],
                    "distances": [[None] * 3 for _ in range(3)],
                },
            )
        return handler(request)

    result = plan_deliveries(road_request, provider(tmp_path, unreachable))
    assert result.solve_result is None
    assert result.errors[0]["code"] == "unreachable_pairs"


def test_city_boundary(road_request):
    validate_area(road_request)
    data = road_request.model_dump()
    data["depot"].update(latitude=-22.9068, longitude=-43.1729)
    with pytest.raises(RouteError, match="outside"):
        validate_area(RoadRequest.model_validate(data))


def test_cache_and_quota_shared_across_instances(tmp_path, road_request):
    one = provider(tmp_path, cache_ttl=300)
    coords = [[-46.6333, -23.5505], [-46.6559, -23.5614]]
    first = one.prepare(coords, road_request.routing, ExecutionContext(10), True)
    two = provider(tmp_path, cache_ttl=300)
    assert two.prepare(coords, road_request.routing, ExecutionContext(10), True) == first
    assert two.calls == 0 and two.cache_hits == 2
    restricted = provider(tmp_path, limits={"snap": (1, 1), "matrix": (1, 1), "directions": (1, 1)})
    with pytest.raises(RouteError, match="quota"):
        restricted.prepare(coords, road_request.routing, ExecutionContext(10))


def test_provider_quota_has_per_integrator_limit(tmp_path, road_request):
    limits = {"snap": (4, 4), "matrix": (4, 4), "directions": (4, 4)}
    first = provider(tmp_path, limits=limits, owner="integrator-a")
    first._reserve("snap")
    with pytest.raises(RouteError, match="Integrator snap quota"):
        provider(tmp_path, limits=limits, owner="integrator-a")._reserve("snap")
    provider(tmp_path, limits=limits, owner="integrator-b")._reserve("snap")


def test_snapping_failure_and_retry_deadline(tmp_path, road_request):
    def no_snap(request):
        return httpx.Response(200, json={"locations": [None, None, None]})

    result = plan_deliveries(road_request, provider(tmp_path, no_snap))
    assert result.errors[0]["code"] == "unsnappable_point"

    def throttled(request):
        return httpx.Response(429, headers={"Retry-After": "120"})

    result = plan_deliveries(road_request, provider(tmp_path, throttled))
    assert result.errors[0]["code"] == "provider_timeout"


def test_geometry_wrong_stop_rejected(tmp_path, road_request):
    def wrong_stop(request):
        response = handler(request)
        if "/directions/" in request.url.path:
            data = response.json()
            data["features"][0]["geometry"]["coordinates"][1] = [-43.17, -22.90]
            return httpx.Response(200, json=data)
        return response

    result = plan_deliveries(road_request, provider(tmp_path, wrong_stop))
    assert result.planning_status == "partial"
    assert result.errors[0]["code"] == "provider_response"


def test_snap_distance_verified_from_coordinates(tmp_path, road_request):
    def wrong_snap(request):
        return httpx.Response(
            200, json={"locations": [{"location": [-43.17, -22.90], "snapped_distance": 1}] * 3}
        )

    result = plan_deliveries(road_request, provider(tmp_path, wrong_snap))
    assert result.errors[0]["code"] == "snap_distance_exceeded"
