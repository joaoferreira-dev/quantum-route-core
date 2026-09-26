# Repository Guidelines

## Project Structure & Module Organization

`src/quantum_route_core/` contains the reusable Python core. Transport and infrastructure live in `api/`, `jobs/`, `routing/`, and `cli/`; optimization backends live in `solvers/`. Keep core imports independent of FastAPI, SQLAlchemy, and Typer. Municipal boundary data lives in `data/`.

Use `tests/` for automated checks, `migrations/` for Alembic changes, and `examples/` for HTTP requests, Python integrations, benchmark scenarios, and the map viewer. Deployment files belong in `deploy/`, operational helpers in `scripts/`, and workflows in `.github/workflows/`. Consult `specs/quantum-route-core-spec.md` and keep `docs/status.md` accurate.

## Build, Test, and Development Commands

Use Python 3.12 and run commands from the repository root:

Start with `uv run dev` and open `http://127.0.0.1:8000/docs`. Ctrl+C stops both services. Separate-process commands:

```sh
uv sync --frozen --extra service --extra classical --extra cli
uv run alembic upgrade head
uv run uvicorn quantum_route_core.api.app:create_app --factory --host 127.0.0.1
uv run qroute-worker
```

Run the last two commands in separate terminals.

```sh
uv run ruff check src tests migrations scripts
uv run ruff format --check src tests migrations scripts
uv run mypy src
uv run pytest --cov=quantum_route_core
uv build
```

These check lint, formatting, types, tests/coverage, and package construction. Apply formatting with `uv run ruff format src tests migrations scripts`.

## Coding Style & Naming Conventions

Use four-space indentation, 100-character lines, type annotations, and Ruff-managed imports. Use `snake_case` for modules/functions and `PascalCase` for classes. Preserve integer canonical costs, independent route validation, heterogeneous vehicle capacities, and explicit backend selection. Never substitute straight-line distances for failed road queries.

## Testing Guidelines

Use pytest with `test_*.py` files and `test_*` functions. Add regression tests for changed behavior, especially job transitions, deadlines, capacity constraints, and provider failures. Mock HTTP for deterministic tests; real ORS checks require explicit execution and consume quota. CI collects coverage but defines no minimum percentage. Do not present mocked results as real-road validation.

## Commit & Pull Request Guidelines

History currently contains only `initial commit`; no established message convention exists. Use concise imperative subjects and focused changes. Every commit must end with:

Create work branches as `feat/<name>` or `fix/<name>`. Push commits only to these branches; never push directly to `main`. Submit a pull request to `main` and merge it after CI passes. The resulting merge update to `main` runs CI and is the only event that can start automatic deployment.

```text
Co-authored-by: codex <codex@openai.com>
```

PRs should describe the problem, behavior changes, validation, and limitations; link relevant issues and include screenshots for map changes. Require passing CI before merging.

## Security & Configuration

Copy `.env.example` to `.env`; never commit credentials. Configure `ORS_API_KEY` locally and unique integrator tokens for network access. Keep QAOA disabled until the SPEC’s formulation gate is satisfied.
