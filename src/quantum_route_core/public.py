"""Stable in-process API; no service, database, or network client imported here."""

from quantum_route_core.application import preflight, solve
from quantum_route_core.domain import ProblemInstance, RoadRequest, SolveConfig
from quantum_route_core.normalization import normalize

__all__ = [
    "normalize",
    "preflight",
    "solve",
    "plan_deliveries",
    "ProblemInstance",
    "RoadRequest",
    "SolveConfig",
]


def plan_deliveries(request, routing_provider, execution_context=None):
    from quantum_route_core.planning import plan_deliveries as plan

    return plan(request, routing_provider, execution_context)
