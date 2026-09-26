import json
from functools import lru_cache
from importlib.resources import files

from shapely.geometry import Point, shape
from shapely.ops import unary_union

from quantum_route_core.domain import RoadRequest
from quantum_route_core.errors import RouteError


@lru_cache(maxsize=4)
def load_area(path: str | None = None):
    text = (
        files("quantum_route_core").joinpath("data/sao-paulo.geojson").read_text(encoding="utf-8")
        if path is None
        else __import__("pathlib").Path(path).read_text(encoding="utf-8")
    )
    data = json.loads(text)
    shapes = (
        [shape(f["geometry"]) for f in data["features"]]
        if data["type"] == "FeatureCollection"
        else [shape(data)]
    )
    return unary_union(shapes)


def validate_area(request: RoadRequest, path: str | None = None) -> None:
    area = load_area(path)
    outside = [
        p.id
        for p in [request.depot, *request.deliveries]
        if not area.covers(Point(p.longitude, p.latitude))
    ]
    if outside:
        raise RouteError(
            "outside_service_area", f"Points outside service area: {', '.join(outside)}"
        )
