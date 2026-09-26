import time
from collections.abc import Callable
from typing import Any

from quantum_route_core.errors import RouteError


class ExecutionContext:
    def __init__(
        self,
        seconds: float,
        cancelled: Callable[[], bool] | None = None,
        publish: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        self.cancelled = cancelled or (lambda: False)
        self.publish = publish or (lambda _: None)

    def check(self) -> None:
        if self.cancelled():
            raise RouteError("cancelled", "Execution cancelled")
        if self.remaining <= 0:
            raise RouteError("time_limit", "Execution deadline reached")

    @property
    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())
