import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

from quantum_route_core.domain import RoutingOptions
from quantum_route_core.errors import RouteError
from quantum_route_core.execution import ExecutionContext
from quantum_route_core.normalization import digest


def separation_meters(a: list[float], b: list[float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    value = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, value))))


class OpenRouteService:
    """Quota ledger shared across worker subprocesses; no secrets in cache keys/logs."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.heigit.org/openrouteservice",
        ledger_path: str = "var/ors.sqlite",
        cache_ttl: int = 0,
        limits: dict[str, tuple[int, int]] | None = None,
        client: httpx.Client | None = None,
        owner: str = "local",
        owner_quota_fraction: float = 0.25,
    ):
        if not api_key:
            raise RouteError("provider_not_configured", "Set ORS_API_KEY to enable road planning")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        if not self.base_url.startswith("https://"):
            raise RouteError("provider_configuration", "ORS endpoint must use HTTPS")
        self.client = client or httpx.Client(follow_redirects=False)
        self.owns_client = client is None
        self.ledger_path = ledger_path
        self.cache_ttl = cache_ttl
        # Deliberately below Standard quotas; also configurable by the operator.
        self.limits = limits or {"matrix": (400, 30), "directions": (1600, 30), "snap": (1600, 60)}
        if not 0 < owner_quota_fraction <= 0.5:
            raise ValueError("owner_quota_fraction must be in (0, 0.5]")
        self.owner = owner
        self.owner_limits = {
            endpoint: (
                max(1, int(daily * owner_quota_fraction)),
                max(1, int(minute * owner_quota_fraction)),
            )
            for endpoint, (daily, minute) in self.limits.items()
        }
        Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(ledger_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS usage(endpoint TEXT, at REAL)")
            # Separate table preserves the global quota history of existing ledgers.
            db.execute("CREATE TABLE IF NOT EXISTS owner_usage(owner TEXT, endpoint TEXT, at REAL)")
            db.execute(
                "CREATE INDEX IF NOT EXISTS ix_owner_usage ON owner_usage(owner, endpoint, at)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, at REAL, value TEXT)"
            )
        self.calls = 0
        self.cache_hits = 0

    def close(self) -> None:
        if self.owns_client:
            self.client.close()

    def _reserve(self, endpoint: str) -> None:
        now = time.time()
        with sqlite3.connect(self.ledger_path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM usage WHERE at < ?", (now - 86400,))
            db.execute("DELETE FROM owner_usage WHERE at < ?", (now - 86400,))
            daily, minute = db.execute(
                "SELECT count(*), coalesce(sum(at > ?),0) FROM usage WHERE endpoint = ?",
                (now - 60, endpoint),
            ).fetchone()
            max_daily, max_minute = self.limits[endpoint]
            if daily >= max_daily or minute >= max_minute:
                raise RouteError("provider_quota", f"Local {endpoint} quota exhausted")
            owner_daily, owner_minute = db.execute(
                "SELECT count(*), coalesce(sum(at > ?),0) FROM owner_usage WHERE owner = ? AND endpoint = ?",
                (now - 60, self.owner, endpoint),
            ).fetchone()
            max_owner_daily, max_owner_minute = self.owner_limits[endpoint]
            if owner_daily >= max_owner_daily or owner_minute >= max_owner_minute:
                raise RouteError("provider_owner_quota", f"Integrator {endpoint} quota exhausted")
            db.execute("INSERT INTO usage VALUES (?, ?)", (endpoint, now))
            db.execute("INSERT INTO owner_usage VALUES (?, ?, ?)", (self.owner, endpoint, now))
        self.calls += 1

    def _post(
        self, endpoint: str, suffix: str, payload: dict, context: ExecutionContext, cache: bool
    ) -> dict[str, Any]:
        key = digest([self.base_url, endpoint, suffix, payload])
        if cache and self.cache_ttl > 0:
            with sqlite3.connect(self.ledger_path) as db:
                db.execute("DELETE FROM cache WHERE at < ?", (time.time() - self.cache_ttl,))
                row = db.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
            if row:
                self.cache_hits += 1
                return json.loads(row[0])
        for attempt in range(3):
            context.check()
            self._reserve(endpoint)
            try:
                response = self.client.post(
                    f"{self.base_url}/v2/{endpoint}/{suffix}",
                    headers={"Authorization": self.api_key},
                    json=payload,
                    timeout=min(15.0, context.remaining),
                )
            except httpx.HTTPError as exc:
                raise RouteError("provider_unavailable", "ORS network request failed") from exc
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    raise RouteError(
                        "provider_unavailable", f"ORS returned HTTP {response.status_code}"
                    )
                try:
                    delay = max(1.0, float(response.headers.get("Retry-After", 2**attempt)))
                except ValueError:
                    delay = 2.0**attempt
                if delay >= context.remaining:
                    raise RouteError("provider_timeout", "Retry exceeds planning deadline")
                until = time.monotonic() + delay
                while time.monotonic() < until:
                    context.check()
                    time.sleep(min(0.1, max(0, until - time.monotonic())))
                continue
            if response.status_code >= 300:
                raise RouteError("provider_rejected", f"ORS returned HTTP {response.status_code}")
            try:
                data = response.json()
                if not isinstance(data, dict) or "error" in data:
                    raise ValueError("invalid response")
            except ValueError as exc:
                raise RouteError("provider_response", "ORS returned malformed JSON") from exc
            if cache and self.cache_ttl > 0:
                with sqlite3.connect(self.ledger_path) as db:
                    db.execute(
                        "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                        (key, time.time(), json.dumps(data)),
                    )
            return data
        raise AssertionError("unreachable")

    def prepare(
        self,
        coordinates: list[list[float]],
        options: RoutingOptions,
        context: ExecutionContext,
        cache: bool = False,
    ) -> dict:
        snapped = self._post(
            "snap",
            f"{options.profile}/json",
            {"locations": coordinates, "radius": options.max_snap_distance_meters},
            context,
            cache,
        )
        try:
            locations = snapped["locations"]
            if len(locations) != len(coordinates):
                raise ValueError("length")
            for requested, location in zip(coordinates, locations, strict=True):
                if location is None:
                    raise RouteError(
                        "unsnappable_point",
                        "A point cannot be snapped within the configured radius",
                    )
                if (
                    not math.isfinite(location["snapped_distance"])
                    or location["snapped_distance"] < 0
                    or location["snapped_distance"] > options.max_snap_distance_meters
                ):
                    raise RouteError(
                        "snap_distance_exceeded",
                        "Provider snapped a point too far from the request",
                    )
                point = location["location"]
                if (
                    len(point) != 2
                    or not all(math.isfinite(v) for v in point)
                    or not (-180 <= point[0] <= 180 and -90 <= point[1] <= 90)
                ):
                    raise ValueError("coordinate")
                if separation_meters(requested, point) > options.max_snap_distance_meters + 1:
                    raise RouteError("snap_distance_exceeded", "Snapped coordinates exceed radius")
            coords = [loc["location"] for loc in locations]
            for coord in coords:
                if len(coord) != 2 or not all(math.isfinite(v) for v in coord):
                    raise ValueError("coordinate")
        except (KeyError, TypeError, ValueError) as exc:
            raise RouteError("provider_response", "Invalid snapping response") from exc
        n = len(coords)
        durations: list[list[float | None]] = [[None] * n for _ in range(n)]
        distances: list[list[float | None]] = [[None] * n for _ in range(n)]
        metadata = {}
        # 50x50 is below the standard non-dynamic matrix element limit.
        for a in range(0, n, 50):
            for b in range(0, n, 50):
                sources = list(range(a, min(a + 50, n)))
                destinations = list(range(b, min(b + 50, n)))
                data = self._post(
                    "matrix",
                    options.profile,
                    {
                        "locations": coords,
                        "sources": [str(i) for i in sources],
                        "destinations": [str(i) for i in destinations],
                        "metrics": ["duration", "distance"],
                    },
                    context,
                    cache,
                )
                try:
                    for metric, target in [("durations", durations), ("distances", distances)]:
                        rows = data[metric]
                        if len(rows) != len(sources) or any(
                            len(row) != len(destinations) for row in rows
                        ):
                            raise ValueError("shape")
                        for x, i in enumerate(sources):
                            for y, j in enumerate(destinations):
                                value = rows[x][y]
                                if value is None:
                                    raise RouteError(
                                        "unreachable_pairs", f"No road cost for pair {i} -> {j}"
                                    )
                                if not math.isfinite(value) or value < 0:
                                    raise ValueError("value")
                                target[i][j] = value if i != j else 0
                    metadata = data.get("metadata", {})
                except (KeyError, ValueError, TypeError, IndexError) as exc:
                    raise RouteError("provider_response", "Invalid matrix response") from exc
        return {
            "locations": locations,
            "durations": durations,
            "distances": distances,
            "metadata": metadata,
            "provider": "openrouteservice",
        }

    def directions(
        self,
        coordinates: list[list[float]],
        options: RoutingOptions,
        context: ExecutionContext,
        cache: bool = False,
    ) -> dict:
        all_coords: list = []
        legs: list = []
        metadata = {}
        for offset in range(0, len(coordinates) - 1, 49):
            chunk = coordinates[offset : offset + 50]
            data = self._post(
                "directions",
                f"{options.profile}/geojson",
                {
                    "coordinates": chunk,
                    "preference": "fastest",
                    "instructions": False,
                    "radiuses": [options.max_snap_distance_meters] * len(chunk),
                },
                context,
                cache,
            )
            try:
                feature = data["features"][0]
                geometry = feature["geometry"]
                segments = feature["properties"]["segments"]
                coords = geometry["coordinates"]
                waypoints = feature["properties"]["way_points"]
                if (
                    geometry["type"] != "LineString"
                    or len(coords) < 2
                    or len(segments) != len(chunk) - 1
                    or len(waypoints) != len(chunk)
                ):
                    raise ValueError("geometry/segments")
                for pair in coords:
                    if (
                        len(pair) < 2
                        or not all(math.isfinite(v) for v in pair)
                        or not (-180 <= pair[0] <= 180 and -90 <= pair[1] <= 90)
                    ):
                        raise ValueError("coordinate")
                if any(type(i) is not int or i < 0 or i >= len(coords) for i in waypoints):
                    raise ValueError("waypoint index")
                if (
                    waypoints != sorted(waypoints)
                    or waypoints[0] != 0
                    or waypoints[-1] != len(coords) - 1
                ):
                    raise ValueError("waypoint order")
                for requested, index in zip(chunk, waypoints, strict=True):
                    if (
                        separation_meters(requested, coords[index])
                        > options.max_snap_distance_meters + 1
                    ):
                        raise ValueError("waypoint differs from requested stop")
                for seg in segments:
                    if any(
                        not math.isfinite(seg[k]) or seg[k] < 0 for k in ("distance", "duration")
                    ):
                        raise ValueError("metric")
                if all_coords and all_coords[-1][:2] != coords[0][:2]:
                    raise ValueError("discontinuous segments")
                all_coords.extend(coords[1:] if all_coords else coords)
                legs.extend(
                    {"distance_meters": s["distance"], "travel_duration_seconds": s["duration"]}
                    for s in segments
                )
                metadata = data.get("metadata", {})
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RouteError("provider_response", "Invalid directions response") from exc
        return {
            "geometry": {"type": "LineString", "coordinates": all_coords},
            "legs": legs,
            "distance_meters": sum(s["distance_meters"] for s in legs),
            "travel_duration_seconds": sum(s["travel_duration_seconds"] for s in legs),
            "metadata": metadata,
        }
