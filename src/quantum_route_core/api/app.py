import hmac
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib.util import find_spec
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quantum_route_core.api.schemas import ERROR_RESPONSES, OptimizationJob
from quantum_route_core.api.settings import Settings
from quantum_route_core.application import preflight
from quantum_route_core.domain import MatrixRequest, RoadRequest
from quantum_route_core.domain import Request as PlanningRequest
from quantum_route_core.errors import RouteError
from quantum_route_core.jobs.database import Repository
from quantum_route_core.normalization import request_hash

adapter: TypeAdapter = TypeAdapter(PlanningRequest)


def iso(value):
    return datetime.fromtimestamp(value, UTC).isoformat() if value is not None else None


def envelope(job: dict) -> dict:
    snapshot = job["snapshot"]
    result = snapshot.get("result")
    planning = snapshot.get("planning_result")
    road = job["payload"]["mode"] == "road"
    planning_status = (planning or {}).get(
        "planning_status", "pending" if road else "not_applicable"
    )
    if (
        road
        and job["status"] in {"failed", "cancelled"}
        and planning_status in {"pending", "ready"}
    ):
        planning_status = "partial" if result and result["has_feasible_solution"] else "failed"
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "request_hash": job["request_hash"],
        "request_id": snapshot.get("request_id"),
        "instance_hash": (result or {}).get("instance_hash")
        or (planning or {}).get("instance_hash"),
        "created_at": iso(job["created_at"]),
        "started_at": iso(job["started_at"]),
        "finished_at": iso(job["finished_at"]),
        "expires_at": iso(job["expires_at"]),
        "queue_seconds": (job["started_at"] or job["finished_at"] or time.time())
        - job["created_at"],
        "elapsed_seconds": (job["finished_at"] or time.time()) - job["created_at"],
        "config_effective": job["payload"]["config"],
        "result": result,
        "error": snapshot.get("error"),
        "planning_status": planning_status,
        "planning_result": planning,
        "links": {
            "self": f"/v1/optimizations/{job['job_id']}",
            "cancel": f"/v1/optimizations/{job['job_id']}/cancel",
        },
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    repository = Repository(settings.database_url, limits=settings.repository_limits)

    @asynccontextmanager
    async def lifespan(_):
        # Fail explicitly if migrations have not run; never mutate schema at import.
        with repository.engine.connect() as db:
            db.execute(text("SELECT version_num FROM alembic_version"))
        yield
        repository.engine.dispose()

    app = FastAPI(
        title="Quantum Route Core",
        version="0.1.0",
        lifespan=lifespan,
        description="Asynchronous delivery planning. POST returns a job; poll GET until terminal.",
    )
    app.state.repository = repository
    app.state.settings = settings

    @app.middleware("http")
    async def guards(request: Request, call_next):
        request.state.request_id = str(uuid4())
        if (
            not settings.network_mode
            and request.client
            and request.client.host not in {"127.0.0.1", "::1", "testclient", "localhost"}
        ):
            return JSONResponse(
                status_code=403,
                content={"code": "local_only", "message": "Enable authenticated network mode"},
            )
        if request.method == "POST":
            length = request.headers.get("content-length")
            try:
                if length and int(length) > settings.max_payload_bytes:
                    return JSONResponse(status_code=413, content={"code": "payload_too_large"})
            except ValueError:
                return JSONResponse(status_code=400, content={"code": "invalid_content_length"})
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > settings.max_payload_bytes:
                    return JSONResponse(status_code=413, content={"code": "payload_too_large"})
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(RouteError)
    async def error_handler(request, exc):
        status = {
            "unauthorized": 401,
            "not_found": 404,
            "idempotency_conflict": 409,
            "queue_full": 429,
            "owner_quota": 429,
            "storage_full": 503,
            "provider_not_configured": 503,
            "admission_disabled": 503,
        }.get(exc.code, 422)
        return JSONResponse(
            status_code=status,
            headers={"Retry-After": "60"} if status == 429 else {},
            content={
                "code": exc.code,
                "message": exc.message,
                "field_errors": [],
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [
            {"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()
        ]
        malformed = any(e["type"] == "json_invalid" for e in exc.errors())
        return JSONResponse(
            status_code=400 if malformed else 422,
            content={
                "code": "invalid_input",
                "message": "Invalid request",
                "field_errors": errors,
                "request_id": request.state.request_id,
            },
        )

    def owner(authorization: str | None = Header(default=None)) -> str:
        if not settings.auth_tokens and not settings.network_mode:
            return "local"
        token = authorization.removeprefix("Bearer ") if authorization else ""
        for name, secret in settings.auth_tokens.items():
            if hmac.compare_digest(token, secret.get_secret_value()):
                return name
        raise RouteError("unauthorized", "Valid bearer token required")

    @app.get("/health")
    def health():
        with repository.engine.connect() as db:
            db.execute(text("SELECT version_num FROM alembic_version"))
        return {"status": "ok"}

    @app.get("/v1/capabilities")
    def capabilities(_owner: str = Depends(owner)):
        return {
            "backends": {
                "classical": {"enabled": find_spec("ortools") is not None, "asymmetric": True},
                "exact": {"enabled": True, "max_deliveries": 10, "asymmetric": True},
                "quantum": {
                    "enabled": False,
                    "experimental": True,
                    "reason": "QUBO verification gate",
                },
            },
            "limits": {
                "max_deliveries": settings.max_deliveries,
                "max_vehicles": settings.max_vehicles,
                "max_solver_seconds": settings.max_solver_seconds,
                "max_planning_seconds": settings.max_planning_seconds,
                "memory_limit_mb": settings.max_memory_mb,
                "queue_capacity": settings.queue_capacity,
                "owner_queue_capacity": settings.owner_queue_capacity,
                "owner_submissions_per_minute": settings.owner_submissions_per_minute,
                "owner_storage_bytes": settings.owner_storage_bytes,
            },
            "routing": {
                "provider": "openrouteservice",
                "configured": bool(settings.ors_api_key.get_secret_value()),
                "profiles": ["driving-car"],
                "service_area": "custom"
                if settings.area_path
                else "São Paulo municipality / IBGE 3550308",
                "geometry": "GeoJSON LineString",
                "traffic": False,
            },
            "modes": ["road", "matrix", "euclidean"],
        }

    @app.post(
        "/v1/optimizations",
        status_code=202,
        response_model=OptimizationJob,
        responses=ERROR_RESPONSES,
        summary="Submit a delivery plan and poll the returned Location",
    )
    def submit(
        payload: PlanningRequest,
        request: Request,
        identity: str = Depends(owner),
        idempotency_key: str | None = Header(default=None, max_length=128),
    ):
        if not settings.admission_enabled:
            raise RouteError("admission_disabled", "Admission is paused")
        cfg = payload.config
        defaults = {
            "max_deliveries": settings.max_deliveries,
            "max_vehicles": settings.max_vehicles,
            "time_limit_seconds": min(5, settings.max_solver_seconds),
            "memory_limit_mb": settings.max_memory_mb,
        }
        cfg = cfg.model_copy(
            update={
                key: value for key, value in defaults.items() if key not in cfg.model_fields_set
            }
        )
        payload = payload.model_copy(update={"config": cfg})
        if (
            isinstance(payload, RoadRequest)
            and "planning_time_limit_seconds" not in payload.model_fields_set
        ):
            payload = payload.model_copy(
                update={"planning_time_limit_seconds": min(60, settings.max_planning_seconds)}
            )
        if (
            cfg.max_deliveries > settings.max_deliveries
            or cfg.max_vehicles > settings.max_vehicles
            or cfg.time_limit_seconds > settings.max_solver_seconds
            or cfg.memory_limit_mb > settings.max_memory_mb
        ):
            raise RouteError("resource_limit", "Requested configuration exceeds server limits")
        if cfg.backend == "classical" and find_spec("ortools") is None:
            raise RouteError("unsupported_configuration", "Classical backend is not installed")
        if isinstance(payload, RoadRequest):
            if payload.planning_time_limit_seconds > settings.max_planning_seconds:
                raise RouteError("resource_limit", "Planning deadline exceeds server limit")
            from quantum_route_core.domain import ProblemInstance
            from quantum_route_core.routing.area import validate_area

            preflight(
                ProblemInstance(
                    depot=payload.depot, customers=payload.deliveries, vehicles=payload.vehicles
                ),
                cfg,
            )
            validate_area(payload, settings.area_path)
            if not settings.ors_api_key.get_secret_value():
                raise RouteError(
                    "provider_not_configured", "Set ORS_API_KEY before road submissions"
                )
        elif isinstance(payload, MatrixRequest):
            preflight(payload.instance, cfg)
        job = repository.submit(
            identity,
            idempotency_key,
            request_hash(payload),
            payload.model_dump(),
            settings.queue_capacity,
            settings.retention_seconds,
        )
        if not job["snapshot"].get("request_id"):
            repository.progress(job["job_id"], {"request_id": request.state.request_id})
            job = repository.get(job["job_id"], identity) or job
        return JSONResponse(
            status_code=202,
            headers={"Location": f"/v1/optimizations/{job['job_id']}"},
            content=envelope(job),
        )

    @app.get(
        "/v1/optimizations/{job_id}", response_model=OptimizationJob, responses=ERROR_RESPONSES
    )
    def get_job(job_id: str, identity: str = Depends(owner)):
        job = repository.get(job_id, identity)
        if not job or (
            job["status"] in {"completed", "failed", "cancelled"}
            and job["expires_at"] < time.time()
        ):
            raise RouteError("not_found", "Job not found")
        return envelope(job)

    @app.post(
        "/v1/optimizations/{job_id}/cancel",
        response_model=OptimizationJob,
        responses={
            **ERROR_RESPONSES,
            202: {
                "model": OptimizationJob,
                "description": "Cancellation requested; poll until terminal",
            },
        },
    )
    def cancel(job_id: str, identity: str = Depends(owner)):
        job = repository.cancel(job_id, identity, settings.retention_seconds)
        if not job:
            raise RouteError("not_found", "Job not found")
        return JSONResponse(
            status_code=202 if job["status"] == "cancel_requested" else 200, content=envelope(job)
        )

    # Outermost middleware: reject untrusted hosts before buffering request bodies.
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts, www_redirect=False
    )
    return app
