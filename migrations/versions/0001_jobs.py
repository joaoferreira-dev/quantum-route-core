"""Initial durable job queue."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(), primary_key=True),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String()),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float()),
        sa.Column("finished_at", sa.Float()),
        sa.Column("expires_at", sa.Float()),
        sa.UniqueConstraint("owner", "idempotency_key", name="uq_job_owner_idempotency"),
    )
    op.create_index("ix_jobs_status_created", "jobs", ["status", "created_at"])


def downgrade():
    raise RuntimeError("Destructive rollback is not automatic; use the documented recovery plan")
