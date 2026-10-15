#!/bin/sh
# Backend container entrypoint.
#
# docker-compose.yml's `depends_on: [postgres, ...]` only waits for those
# containers to *start*, not for Postgres to actually be ready to accept
# connections — Postgres can take a few seconds after "started" before it's
# reachable. Without this wait, `Base.metadata.create_all()` in app/main.py
# (which runs on import, before uvicorn even binds a port) can throw and the
# backend container exits before the database is up, which looks like a
# random one-in-a-few-runs failure rather than a consistent bug.
#
# This also auto-runs the one-time `python -m app.seed` migration the README
# asks for manually (`docker compose exec backend python -m app.seed`) — but
# ONLY the first time the database is empty. Re-running it on every restart
# would silently wipe any data created through the running app, since seed.py
# clears every table before reloading (see its own docstring).
set -e

echo "Waiting for Postgres..."
python - <<'PY'
import os
import time
import sys
import psycopg2

url = os.getenv("DATABASE_URL", "")
if not url.startswith("postgresql"):
    sys.exit(0)  # sqlite fallback, nothing to wait for

# psycopg2 doesn't understand the SQLAlchemy "+psycopg2" driver suffix.
dsn = url.replace("postgresql+psycopg2", "postgresql")
for attempt in range(30):
    try:
        conn = psycopg2.connect(dsn)
        conn.close()
        print("Postgres is up.")
        sys.exit(0)
    except Exception as exc:
        print(f"  ({attempt + 1}/30) not ready yet: {exc}")
        time.sleep(2)
print("Postgres never became reachable; starting anyway.")
PY

echo "Checking whether the database needs seeding..."
python - <<'PY'
from app.db.postgres import Base, engine, SessionLocal
from app.models import sql_models as m

Base.metadata.create_all(bind=engine)
db = SessionLocal()
try:
    needs_seed = db.query(m.User).count() == 0
finally:
    db.close()

if needs_seed:
    print("Database is empty — running `python -m app.seed`...")
    import subprocess
    subprocess.run(["python", "-m", "app.seed"], check=True)
else:
    print("Database already has data; skipping auto-seed (run "
          "`docker compose exec backend python -m app.seed` manually to reset it).")
PY

echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 5000
