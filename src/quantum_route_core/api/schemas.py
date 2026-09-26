from typing import Any, Literal

from pydantic import BaseModel, Field

from quantum_route_core.domain import PlanningResult, SolveResult


class APIError(BaseModel):
    code: str
    message: str
    field_errors: list[dict[str, Any]] = Field(default_factory=list)
    request_id: str | None = None


class OptimizationJob(BaseModel):
    job_id: str
    status: Literal["queued", "running", "cancel_requested", "completed", "failed", "cancelled"]
    request_hash: str
    request_id: str | None = None
    instance_hash: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    expires_at: str | None
    queue_seconds: float
    elapsed_seconds: float
    config_effective: dict[str, Any]
    result: SolveResult | None
    error: APIError | None
    planning_status: Literal[
        "pending", "ready", "partial", "no_feasible_solution", "failed", "not_applicable"
    ]
    planning_result: PlanningResult | None
    links: dict[str, str]


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": APIError, "description": description}
    for code, description in {
        400: "Malformed JSON",
        401: "Missing or invalid bearer token",
        403: "Local-only service",
        404: "Job unavailable for this integrator or expired",
        409: "Idempotency key reused with a different request",
        413: "Payload too large",
        422: "Invalid input or unsupported configuration",
        429: "Queue full or integrator quota exhausted; retry after Retry-After",
        503: "Admission paused, storage unavailable or routing provider unconfigured",
    }.items()
}
