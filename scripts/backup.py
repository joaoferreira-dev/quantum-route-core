import sqlite3
import time

from quantum_route_core.api.settings import Settings

path = Settings().database_path
if path.exists():
    backup = path.parent / "backups" / f"jobs-{int(time.time())}.db"
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    print(f"Backup created: {backup.name}")
else:
    print("First installation: no existing database to back up")
