"""Explicit road request: requires ORS_API_KEY and consumes provider quota."""

from pathlib import Path

from quantum_route_core.api.settings import Settings
from quantum_route_core.domain import RoadRequest
from quantum_route_core.public import plan_deliveries
from quantum_route_core.routing.providers.openrouteservice import OpenRouteService

settings = Settings()
request = RoadRequest.model_validate_json(
    Path("examples/http/road-request.json").read_text(encoding="utf-8")
)
provider = OpenRouteService(settings.ors_api_key.get_secret_value())
try:
    result = plan_deliveries(request, provider)
    Path("planning-result.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print(result.planning_status)
finally:
    provider.close()
