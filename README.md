# MedChain — Python / FastAPI + Polyglot Persistence

This is the migrated backend for your MedChain project, rebuilt per the two
architecture reviews you had done earlier:

1. **Node.js/Express → Python/FastAPI** (keeping the React/Vite frontend unchanged)
2. **`db.json` → polyglot persistence**: PostgreSQL + MongoDB + InfluxDB + SQLite

Every route, every business rule (FEFO allocation, shortage/anomaly
detection, cold-chain checks, GPS/ETA math, the SHA-256 blockchain ledger,
regional demand forecasting, supplier ranking) and every ML model has been
ported — not stubbed — from the original `backend/` folder, and the demand
and shortage models were **upgraded to scikit-learn** (Random Forest,
Isolation Forest) instead of the original hand-rolled JS trees, as
recommended.

## Architecture

```
React + Vite (frontend/, unchanged)
        │
        ▼
Python + FastAPI (backend/app)
        │
   ┌────┼────────────┬──────────────┐
   ▼    ▼             ▼              ▼
PostgreSQL   MongoDB          InfluxDB         (CSVs)
 (business    (blockchain      (cold-chain +    (read-only
  data)       ledger + audit)  GPS telemetry)    seed/training data)
        │
        ▼
Python ML Engine (scikit-learn)
 Random Forest (demand) · Random Forest (shortage) · Isolation Forest (anomalies)
```

| Store | Owns | Falls back to (no Docker needed) |
|---|---|---|
| **PostgreSQL** | users, clients, inventories, requests, sales, billing, anomalies, recalls, notifications, settings, ... | Local SQLite file at `data/medchain_dev.sqlite3` |
| **MongoDB** | the hash-chained blockchain ledger + audit events (variable-shape documents) | Local JSON file at `data/blockchain_fallback.json` |
| **InfluxDB** | cold-chain temperature/humidity readings, GPS pings (time-series) | Local JSONL files under `data/telemetry/` |
| **6 CSV files** | seed / training / import data (unchanged, per your architecture decision — these don't get migrated into a database) | n/a — they're just files |

Every database is **optional** at boot except the fallback SQLite: if
`MONGODB_URL` / `INFLUX_URL` aren't set or aren't reachable, the app logs a
warning and transparently uses the local-file fallback instead of crashing.
This means the project runs immediately for local dev/grading, and you flip
on the real Postgres/Mongo/InfluxDB services (you said you have Docker) by
setting three environment variables — no code changes anywhere.

## Quick start (with your real Docker databases)

```bash
cp .env.example .env        # edit if you want different credentials
docker compose up --build
```

This starts Postgres, MongoDB, InfluxDB, the FastAPI backend (port 5000)
and the Vite frontend (port 5173). The backend Dockerfile trains both ML
models at build time so the API works immediately, and its entrypoint
script waits for Postgres to be reachable and auto-seeds the database from
`data/db_seed_source.json` the first time it's empty — no manual step
needed. (If you ever want to force a full reset back to the seed data,
`docker compose exec backend python -m app.seed` still works and is safe
to re-run any time.)

Open http://localhost:5173 — the frontend talks to the backend container
by its Docker service name (`API_PROXY_TARGET`, set in docker-compose.yml),
not `localhost`, since they're separate containers on the same network.

## Quick start (no Docker — local dev / SQLite fallback)

```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-ml.txt  # XGBoost/LSTM ensemble models
python -m app.ml.train_demand      # trains the Random Forest demand model
python -m app.ml.train_shortage    # trains the Random Forest shortage classifier (simulated stock-outs)
python -m app.ml.evaluate_models   # optional: regenerates EVALUATION.md / evaluation_report.json
python -m app.seed                 # migrates data/db_seed_source.json into SQLite + local fallback stores
uvicorn app.main:app --reload --port 5000
```

Demo logins (same as the original project — see `data/db_seed_source.json`
for the full list): `admin@gmail.com` / `admin12`, `vendor@gmail.com` /
`vendor12`, `dis@gmail.com` / `dis12`, `client1@gmail.com` / `client123`.

## What's been verified end-to-end (not just written — actually run)

- All 4 portal logins + dashboards (admin/vendor/distributor/client)
- Full order lifecycle: distributor raises a stock request → vendor
  approves via FEFO allocation → distributor receives it → distributor
  inventory updated
- Cold-chain breach detection + alert raised as an anomaly
- Isolation Forest inventory anomaly scan (scikit-learn; unsupervised, flags are
  review candidates - see "Evaluation and limitations")
- Random Forest demand forecast (chronological hold-out, compared with baselines)
  and a shortage-risk classifier trained on simulated stock-outs
- Recall issuance
- Notifications
- GPS/ETA shipment tracking (haversine distance + speed-derived ETA)
- Blockchain hash-chain integrity — verified valid both on the migrated
  historical ledger **and** after new blocks are added live

## Evaluation and limitations (please read before citing any ML number)

All data in this project is synthetic and there is **no real-world ground truth**
(no observed stock-outs, no labelled inventory faults). The ML results therefore
show how the methods behave in a controlled simulation, **not** that they forecast
shortages or detect anomalies in real supply chains. Full numbers, baselines and
suggested paper wording are in [`EVALUATION.md`](EVALUATION.md)
(regenerate with `python -m app.ml.evaluate_models`).

- **Shortage risk**: labels are simulated (random stock level vs. the next
  lead-time + 7 days of synthetic demand). The Random Forest is only marginally
  better than the plain rule "days of supply < lead time + 7" (F1 about 0.95 for both).
  An earlier version reported 100% accuracy on a test set that contained only
  positive cases; that figure was meaningless and has been removed.
- **Anomaly detection**: Isolation Forest is unsupervised. Tiers are scanned
  separately and flags are *review candidates*. On a synthetic injected-fault
  benchmark it reaches ROC-AUC 0.99, but it still flags about 3% of fault-free
  records.
- **Demand forecasting**: chronological hold-out, one-day-ahead only; beats naive
  baselines (Random Forest R² 0.841, XGBoost 0.842, LSTM 0.840; same-weekday
  baseline 0.697, median per-drug Random Forest R² 0.61). All three models are
  trained and their artifacts are included. XGBoost/LSTM require
  `requirements-ml.txt`. These results use synthetic data
  and are not real-world validation; recursive multi-day forecasts are not evaluated.

## Project layout

```
medchain-python/
├── docker-compose.yml
├── .env.example
├── data/
│   ├── dataset/                 # the original 6 CSVs, unchanged
│   └── db_seed_source.json      # copy of your original db.json, used only by app/seed.py
├── backend/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── app/
│       ├── main.py              # FastAPI app, CORS, router wiring (was server.js)
│       ├── config.py            # env-driven settings for all 4 databases
│       ├── security.py          # password hashing + JWT (was utils/security.js)
│       ├── deps.py              # auth + RBAC dependencies (was middleware/auth.js)
│       ├── serializers.py       # snake_case <-> camelCase translation for the frontend
│       ├── seed.py              # one-time db.json -> Postgres/Mongo migration
│       ├── db/
│       │   ├── postgres.py      # SQLAlchemy engine/session
│       │   ├── mongo.py         # blockchain/audit store + local fallback
│       │   └── influx.py        # telemetry store + local fallback
│       ├── models/sql_models.py # every Postgres table (was the db.json shape)
│       ├── services/            # FEFO, geo/ETA, ml_engine, blockchain, notifications,
│       │                        # inventory_guard, telemetry, dataset_loader,
│       │                        # supplier_ranking, regional_forecast, batch_verify
│       ├── ml/                  # features, generate_dataset, train_demand, predict,
│       │                        # shortage_features, train_shortage, predict_shortage,
│       │                        # anomaly_detector (scikit-learn RF/IsolationForest)
│       └── routers/             # auth, vendor, distributor, admin, client, blockchain_router,
│                                 # notifications_router, level2, datasets, dataset_features,
│                                 # dataset_actions, batch, events
└── frontend/                    # your original React/Vite app, byte-for-byte unchanged
```

## Endpoint parity

Every original Express route has a 1:1 FastAPI equivalent at the **same
path** (e.g. `POST /api/vendor/stock-requests/:id/approve` works
identically). The frontend required zero changes because of this. A few
things were consolidated rather than duplicated:

- The old top-level `POST /api/admin/anomalies/scan-isolation-forest`-style
  route now lives under `/api/admin/anomalies/scan-isolation-forest` (was
  previously a special-cased top-level route in `server.js`).
- `routes/regionalForecast.js` was never actually mounted in the original
  `server.js` (dead code) — its logic is preserved in
  `app/services/regional_forecast.py` and is live at
  `GET /api/distributor/hospital-forecast`, which is where the frontend
  actually calls it from.
- The response-body-sniffing notification middleware in the original
  `server.js` was replaced with explicit `create_notification(...)` calls
  at the point of each action (shipment dispatched/received, cold-chain
  breach, shortage risk, recall issued) — same events, clearer code path.

## Next steps if you want to go further

- **Normalize JSON columns**: nested fields (`batchesAllocated`, `gpsLog`,
  `coldChainLog`, `affectedHolders`) are stored as Postgres JSON columns
  rather than fully separate tables, preserving 1:1 behavioural parity with
  the original app cheaply. If your professor wants a fully 3NF schema,
  these are the columns to split out next.
- **Mongo/Influx-native reads**: a couple of read paths (e.g. "latest
  cold-chain reading per batch") still use the lightweight Postgres copy
  for simplicity; `app/services/telemetry.py` already has the Influx
  Flux-query read path if you want dashboards querying Influx directly.
- **Auth hashing**: the password hashing (`app/security.py`) mirrors the
  original demo project's simple salted-SHA256 approach. Swap in `bcrypt`/
  `argon2` before using this anywhere beyond a college project.
