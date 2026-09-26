from typing import Any, Protocol

from quantum_route_core.domain import RoutingOptions
from quantum_route_core.execution import ExecutionContext


class RoutingProvider(Protocol):
    def prepare(
        self,
        coordinates: list[list[float]],
        options: RoutingOptions,
        context: ExecutionContext,
        cache: bool = False,
    ) -> dict[str, Any]: ...

    def directions(
        self,
        coordinates: list[list[float]],
        options: RoutingOptions,
        context: ExecutionContext,
        cache: bool = False,
    ) -> dict[str, Any]: ...
