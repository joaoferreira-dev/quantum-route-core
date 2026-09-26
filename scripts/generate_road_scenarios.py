"""Generate fixed synthetic candidate scenarios; no provider calls or real customers."""

import json
import math
from pathlib import Path

from quantum_route_core.domain import RoadRequest
from quantum_route_core.routing.area import validate_area

# Public-area candidate coordinates. Road access must be checked with ORS.
POINTS = [
    (-23.5614, -46.6559),
    (-23.5874, -46.6576),
    (-23.5660, -46.6930),
    (-23.5290, -46.6690),
    (-23.5080, -46.6240),
    (-23.5420, -46.6060),
    (-23.5500, -46.5800),
    (-23.5580, -46.5590),
    (-23.5380, -46.5760),
    (-23.6500, -46.7100),
    (-23.6200, -46.6950),
    (-23.5990, -46.6750),
    (-23.4900, -46.6450),
    (-23.5200, -46.7000),
    (-23.5400, -46.4700),
]


def main():
    output = Path("examples/road-scenarios")
    output.mkdir(parents=True, exist_ok=True)
    for count in (5, 10, 15):
        for vehicles in range(1, 6):
            data = {
                "mode": "road",
                "depot": {"id": "depot", "latitude": -23.5505, "longitude": -46.6333},
                "deliveries": [
                    {"id": f"point-{i + 1:02d}", "latitude": lat, "longitude": lon, "demand": 1}
                    for i, (lat, lon) in enumerate(POINTS[:count])
                ],
                "vehicles": [
                    {"id": f"vehicle-{i + 1}", "capacity": math.ceil(count / vehicles) + i}
                    for i in range(vehicles)
                ],
                "config": {"backend": "classical", "time_limit_seconds": 5},
            }
            validate_area(RoadRequest.model_validate(data))
            (output / f"deliveries-{count}-vehicles-{vehicles}.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
    print("15 synthetic scenarios written; road access and performance are unverified.")


if __name__ == "__main__":
    main()
