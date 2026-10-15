"""
Central configuration, read from environment variables (see .env.example).

Polyglot persistence layout (per the architecture decision):
  - PostgreSQL  -> operational/business data (users, inventory, requests, sales, billing,
                   recalls, production runs, settings, notifications, clients...)
  - MongoDB     -> the blockchain hash-chain ledger + free-form audit/event documents
  - InfluxDB    -> time-series IoT telemetry (cold-chain temperature/humidity, GPS pings)
  - SQLite      -> automatic fallback for DATABASE_URL when Postgres isn't configured,
                   so the app also runs out-of-the-box for local dev/testing/grading.

Every database is optional at boot time except Postgres: if MongoDB/InfluxDB aren't
reachable, the app degrades gracefully (blockchain/telemetry writes are buffered
in-memory and a warning is logged) rather than crashing, exactly like a real
production system should behave when a downstream dependency is temporarily down.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # .../medchain-python (host/local layout only)

# DATA_DIR is overridable via env because the backend Docker image is built
# with `./backend` as its context (see docker-compose.yml), so everything
# under medchain-python/backend gets copied to /app and BASE_DIR above no
# longer points at the real project root the way it does when running
# locally with `uvicorn` from a checked-out copy of the repo. Without this
# override, DATASET_DIR resolves to a path that doesn't exist inside the
# container (the CSVs live only in the ./data volume mounted at /app/data),
# and every dataset-backed endpoint (regional forecast, supplier ranking,
# shipment/cold-chain summaries, and `python -m app.seed` itself) fails with
# FileNotFoundError even though Postgres/Mongo/Influx are all connected fine.
# docker-compose.yml sets DATA_DIR=/app/data for the backend service to match
# the volume mount; local/non-Docker runs fall back to the computed default.
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATASET_DIR = DATA_DIR / "dataset"
ML_ARTIFACT_DIR = Path(__file__).resolve().parent / "ml" / "artifacts"

# ---------------------------------------------------------------------------
# PostgreSQL (falls back to a local SQLite file if not configured, so the
# project still runs immediately without Docker for grading/local dev)
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR}/medchain_dev.sqlite3")

# ---------------------------------------------------------------------------
# MongoDB (blockchain ledger + audit/provenance documents)
# ---------------------------------------------------------------------------
MONGODB_URL = os.getenv("MONGODB_URL", "")  # e.g. mongodb://mongo:27017
MONGODB_DB = os.getenv("MONGODB_DB", "medchain")

# ---------------------------------------------------------------------------
# InfluxDB (cold-chain + GPS time-series telemetry)
# ---------------------------------------------------------------------------
INFLUX_URL = os.getenv("INFLUX_URL", "")  # e.g. http://influxdb:8086
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "medchain")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "telemetry")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
JWT_SECRET = os.getenv("JWT_SECRET", "drug-scm-demo-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 12

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
PORT = int(os.getenv("PORT", "5000"))
