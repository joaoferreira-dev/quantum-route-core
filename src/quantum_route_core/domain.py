"""Transport-independent contracts. All costs are integer matrix costs."""

from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

PositiveInt = Annotated[int, Field(strict=True, gt=0, le=10**9)]
Cost = Annotated[int, Field(strict=True, ge=0, le=10**12)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Point(Model):
    id: str = Field(min_length=1, max_length=128)
    x: float | None = None
    y: float | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class Customer(Point):
    demand: PositiveInt


class Vehicle(Model):
    id: str = Field(min_length=1, max_length=128)
    capacity: PositiveInt


class ProblemInstance(Model):
    schema_version: Literal["1"] = "1"
    normalization_version: Literal["1"] = "1"
    instance_id: str = "instance"
    instance_hash: str | None = None
    depot: Point
    customers: list[Customer] = Field(min_length=1, max_length=100)
    vehicles: list[Vehicle] = Field(min_length=1, max_length=50)
    node_order: list[str] = Field(default_factory=list, max_length=101)
    cost_matrix: list[Annotated[list[Cost], Field(max_length=101)]] | None = Field(
        default=None, max_length=101
    )
    cost_units: str = "units"
    cost_scale: PositiveInt = 1
    distance_rule: str = "explicit"
    rounding_rule: Literal["half_up"] = "half_up"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        ids = [self.depot.id, *(c.id for c in self.customers)]
        if len(set(ids)) != len(ids):
            raise ValueError("depot/customer IDs must be unique")
        if len({v.id for v in self.vehicles}) != len(self.vehicles):
            raise ValueError("vehicle IDs must be unique")
        if self.node_order and (
            len(self.node_order) != len(ids) or set(self.node_order) != set(ids)
        ):
            raise ValueError("node_order must contain each depot/customer ID exactly once")
        if self.cost_matrix is not None:
            if not self.node_order:
                raise ValueError("explicit cost_matrix requires node_order")
            n = len(ids)
            if len(self.cost_matrix) != n or any(len(row) != n for row in self.cost_matrix):
                raise ValueError("cost_matrix dimensions must match node_order")
            if any(self.cost_matrix[i][i] != 0 for i in range(n)):
                raise ValueError("cost_matrix diagonal must be zero")
            if max(map(max, self.cost_matrix)) * (n + len(self.vehicles)) >= 2**60:
                raise ValueError("aggregate costs exceed supported integer range")
        return self


class SolveConfig(Model):
    backend: Literal["classical", "exact", "quantum"] = "classical"
    time_limit_seconds: float = Field(default=5, gt=0, le=3600)
    memory_limit_mb: int = Field(default=1024, ge=128, le=65536)
    max_deliveries: PositiveInt = 15
    max_vehicles: PositiveInt = 5
    cache_policy: Literal["off", "use"] = "off"
    thread_limit: Literal[1] = 1
    seeds: dict[str, int] = Field(default_factory=dict)
    backend_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def no_unapplied_options(self) -> Self:
        if self.seeds or self.backend_options:
            raise ValueError("this release does not support seeds or backend_options")
        return self


class Route(Model):
    vehicle_id: str
    stop_ids: list[str]
    load: int
    objective_cost: int


Termination = Literal[
    "completed", "time_limit", "resource_limit", "cancelled", "unsupported_configuration", "error"
]


class SolveResult(Model):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    instance_hash: str
    backend_name: str
    backend_version: str = "0.1.0"
    termination_reason: Termination = "completed"
    has_feasible_solution: bool = False
    optimality_proven: bool = False
    infeasibility_proven: bool = False
    routes: list[Route] | None = None
    unused_vehicle_ids: list[str] = Field(default_factory=list)
    objective_cost: int | None = None
    validation_errors: list[str] = Field(default_factory=list)
    timings: dict[str, float | None] = Field(default_factory=dict)
    config_requested: dict[str, Any] = Field(default_factory=dict)
    config_effective: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)
    solution_origin: str | None = None


class RoutingOptions(Model):
    profile: Literal["driving-car"] = "driving-car"
    objective_metric: Literal["travel_time", "distance"] = "travel_time"
    max_snap_distance_meters: float = Field(default=100, gt=0, le=1000)


class RoadRequest(Model):
    mode: Literal["road"] = "road"
    schema_version: Literal["1"] = "1"
    depot: Point
    deliveries: list[Customer] = Field(min_length=1, max_length=100)
    vehicles: list[Vehicle] = Field(min_length=1, max_length=50)
    routing: RoutingOptions = Field(default_factory=RoutingOptions)
    config: SolveConfig = Field(default_factory=SolveConfig)
    planning_time_limit_seconds: float = Field(default=60, gt=0, le=3600)

    @model_validator(mode="after")
    def locations_and_ids(self) -> Self:
        for point in [self.depot, *self.deliveries]:
            if point.latitude is None or point.longitude is None:
                raise ValueError(f"latitude/longitude required for {point.id}")
            if point.x is not None or point.y is not None:
                raise ValueError("road mode does not accept Cartesian coordinates")
        ProblemInstance(depot=self.depot, customers=self.deliveries, vehicles=self.vehicles)
        return self


class MatrixRequest(Model):
    mode: Literal["matrix", "euclidean"]
    instance: ProblemInstance
    config: SolveConfig = Field(default_factory=SolveConfig)

    @model_validator(mode="after")
    def mode_matches(self) -> Self:
        if (self.mode == "matrix") != (self.instance.cost_matrix is not None):
            raise ValueError("matrix mode requires matrix; euclidean mode forbids matrix")
        if self.mode == "euclidean":
            for point in [self.instance.depot, *self.instance.customers]:
                if point.x is None or point.y is None:
                    raise ValueError("euclidean mode requires x/y for every point")
        return self


def default_road(value: Any) -> Any:
    if isinstance(value, dict) and "mode" not in value:
        return {"mode": "road", **value}
    return value


Request = Annotated[
    RoadRequest | MatrixRequest, Field(discriminator="mode"), BeforeValidator(default_road)
]


class PlanningResult(Model):
    planning_status: Literal["ready", "partial", "no_feasible_solution", "failed"]
    request_hash: str
    instance_hash: str | None = None
    solve_result: SolveResult | None = None
    vehicle_routes: list[dict[str, Any]] = Field(default_factory=list)
    unused_vehicle_ids: list[str] = Field(default_factory=list)
    locations: list[dict[str, Any]] = Field(default_factory=list)
    routing_metadata: dict[str, Any] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)
