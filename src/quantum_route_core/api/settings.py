from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QROUTE_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///var/jobs.db"
    max_deliveries: int = Field(default=15, ge=1, le=100)
    max_vehicles: int = Field(default=5, ge=1, le=50)
    max_solver_seconds: float = Field(default=30, gt=0)
    max_planning_seconds: float = Field(default=120, gt=0)
    max_memory_mb: int = Field(default=1024, ge=128)
    max_payload_bytes: int = Field(default=1_000_000, ge=1024)
    queue_capacity: int = Field(default=100, ge=1)
    owner_queue_capacity: int = Field(default=20, ge=1)
    owner_submissions_per_minute: int = Field(default=10, ge=1)
    owner_storage_bytes: int = Field(default=32_000_000, ge=4096)
    storage_bytes: int = Field(default=256_000_000, ge=4096)
    max_snapshot_bytes: int = Field(default=4_000_000, ge=1024)
    min_free_disk_mb: int = Field(default=256, ge=1)
    queue_timeout_seconds: float = Field(default=300, gt=0)
    retention_seconds: int = Field(default=86400, ge=60)
    auth_tokens: dict[str, SecretStr] = Field(default_factory=dict)
    network_mode: bool = False
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "::1"])
    admission_enabled: bool = True
    area_path: str | None = None
    ors_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="ORS_API_KEY")
    ors_base_url: str = "https://api.heigit.org/openrouteservice"
    ors_ledger_path: str = "var/ors.sqlite"
    ors_cache_ttl: int = Field(default=0, ge=0)
    ors_matrix_daily: int = Field(default=400, gt=0)
    ors_matrix_minute: int = Field(default=30, gt=0)
    ors_directions_daily: int = Field(default=1600, gt=0)
    ors_directions_minute: int = Field(default=30, gt=0)
    ors_snap_daily: int = Field(default=1600, gt=0)
    ors_snap_minute: int = Field(default=60, gt=0)
    ors_owner_quota_fraction: float = Field(default=0.25, gt=0, le=0.5)

    @model_validator(mode="after")
    def safe_mode(self):
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("v0.1 requires a local SQLite database")
        if self.network_mode and not self.auth_tokens:
            raise ValueError("network mode requires auth_tokens")
        if not self.allowed_hosts or any(
            not host or "*" in host or "/" in host for host in self.allowed_hosts
        ):
            raise ValueError("allowed_hosts must contain explicit hostnames without wildcards")
        if not self.network_mode and set(self.allowed_hosts) - {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("local mode only permits loopback hostnames")
        values = [v.get_secret_value() for v in self.auth_tokens.values()]
        if any(len(v) < 24 for v in values) or len(set(values)) != len(values):
            raise ValueError("tokens must be unique and at least 24 characters")
        return self

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.removeprefix("sqlite:///"))

    @property
    def repository_limits(self):
        from quantum_route_core.jobs.database import RepositoryLimits

        return RepositoryLimits(
            owner_pending=self.owner_queue_capacity,
            submissions_per_minute=self.owner_submissions_per_minute,
            owner_bytes=self.owner_storage_bytes,
            total_bytes=self.storage_bytes,
            snapshot_bytes=self.max_snapshot_bytes,
            min_free_disk_mb=self.min_free_disk_mb,
        )
