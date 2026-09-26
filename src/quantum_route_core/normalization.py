import hashlib
import json
import math
from typing import Any

from quantum_route_core.domain import Point, ProblemInstance, Request
from quantum_route_core.errors import RouteError


def euclidean_cost(a: Point, b: Point, scale: int) -> int:
    assert a.x is not None and a.y is not None and b.x is not None and b.y is not None
    distance = scale * math.hypot(a.x - b.x, a.y - b.y)
    if not math.isfinite(distance) or distance > 10**12:
        raise RouteError("invalid_input", "Scaled Cartesian distance exceeds supported cost range")
    return math.floor(distance + 0.5)


def validate_euclidean_range(instance: ProblemInstance) -> None:
    points = [instance.depot, *instance.customers]
    if any(p.x is None or p.y is None for p in points):
        return
    xs = [p.x for p in points if p.x is not None]
    ys = [p.y for p in points if p.y is not None]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    maximum = math.hypot(dx, dy)
    if not math.isfinite(maximum) or maximum > 10**12 / instance.cost_scale:
        raise RouteError("invalid_input", "Scaled Cartesian distance exceeds supported cost range")


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def normalize(instance: ProblemInstance) -> ProblemInstance:
    data = instance.model_dump()
    points = {p.id: p for p in [instance.depot, *instance.customers]}
    order = sorted(points)
    if instance.cost_matrix is None:
        validate_euclidean_range(instance)
        if any(p.x is None or p.y is None for p in points.values()):
            raise ValueError("matrix or Cartesian x/y coordinates required")
        matrix = [
            [euclidean_cost(points[a], points[b], instance.cost_scale) for b in order]
            for a in order
        ]
        data["distance_rule"] = "euclidean"
    else:
        index = {key: i for i, key in enumerate(instance.node_order)}
        matrix = [[instance.cost_matrix[index[a]][index[b]] for b in order] for a in order]
    data.update(
        node_order=order,
        cost_matrix=matrix,
        customers=sorted(data["customers"], key=lambda c: c["id"]),
        vehicles=sorted(data["vehicles"], key=lambda v: v["id"]),
    )
    data["instance_hash"] = digest(
        {
            "normalization_version": "1",
            "depot": instance.depot.id,
            "customers": [{"id": c["id"], "demand": c["demand"]} for c in data["customers"]],
            "vehicles": data["vehicles"],
            "node_order": order,
            "cost_matrix": matrix,
            "cost_units": instance.cost_units,
            "cost_scale": instance.cost_scale,
        }
    )
    return ProblemInstance.model_validate(data)


def request_hash(request: Request) -> str:
    data = request.model_dump()
    if request.mode == "road":
        data["deliveries"] = sorted(data["deliveries"], key=lambda x: x["id"])
        data["vehicles"] = sorted(data["vehicles"], key=lambda x: x["id"])
    else:
        data["instance"] = normalize(request.instance).model_dump()
        data["instance"].pop("instance_id", None)
    return digest(data)
