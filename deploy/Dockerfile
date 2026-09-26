FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv==0.11.15
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra service --extra classical --no-editable

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 qroute && mkdir -p /app/var && chown -R qroute:qroute /app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY examples ./examples
COPY scripts ./scripts
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER qroute
EXPOSE 8000
CMD ["uvicorn", "quantum_route_core.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
