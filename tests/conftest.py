import pytest

from quantum_route_core.domain import Customer, Point, ProblemInstance, Vehicle


@pytest.fixture
def instance():
    return ProblemInstance(
        depot=Point(id="depot"),
        customers=[
            Customer(id="a", demand=6),
            Customer(id="b", demand=4),
            Customer(id="c", demand=3),
        ],
        vehicles=[Vehicle(id="large", capacity=10), Vehicle(id="small", capacity=3)],
        node_order=["depot", "a", "b", "c"],
        cost_matrix=[[0, 2, 8, 4], [7, 0, 2, 9], [3, 4, 0, 5], [1, 6, 8, 0]],
    )


@pytest.fixture
def settings(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    from quantum_route_core.api.settings import Settings

    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setenv("QROUTE_DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    return Settings(
        _env_file=None, database_url=url, allowed_hosts=["localhost", "127.0.0.1", "::1"]
    )
