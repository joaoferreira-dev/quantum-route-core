from alembic import context
from sqlalchemy import create_engine

from quantum_route_core.api.settings import Settings
from quantum_route_core.jobs.database import metadata

settings = Settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        connection.commit()
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
