# Fixes applied — why demand forecasting wasn't connecting

You reported: all portal pages loaded, but demand forecasting in the admin
and distributor portals wasn't connecting to the database/API. Root causes
found and fixed:

## 1. `backend/app/config.py` — dataset path broke only inside Docker (main bug)
`DATA_DIR` was computed as "3 folders up from this file," which correctly
finds the project root when you run the backend locally, but the backend's
`Dockerfile` builds with `./backend` as its context — so inside the
container that same math lands one folder too high, pointing at a path that
doesn't exist. Every endpoint that reads the 6 CSV datasets (regional
forecast, supplier ranking, shipment/cold-chain summaries, and
`python -m app.seed` itself) failed with `FileNotFoundError` → the frontend
saw that as a broken/empty connection. Plain database-backed pages never
touch this code path, which is why only forecasting looked broken.
**Fix:** `DATA_DIR` is now read from an environment variable, and
`docker-compose.yml` sets it explicitly to match the `./data:/app/data`
volume mount. Verified locally and by simulating the container's file
layout — see the two path resolutions differ before vs. after the fix.

## 2. `frontend/Dockerfile` was missing entirely
`docker-compose.yml` said `build: ./frontend`, but there was no Dockerfile
there — `docker compose up --build` could not have succeeded for that
service. Added one (Node 20, runs the Vite dev server with `--host
0.0.0.0`, which is also required for the container's dev server to be
reachable from your browser on the host machine).

## 3. `frontend/vite.config.js` proxy target was hardcoded to `localhost:5000`
That's correct when running the frontend outside Docker, but inside its own
container "localhost" refers to the frontend container itself, not the
backend one. Made the proxy target configurable and pointed it at the
backend's Docker service name via `API_PROXY_TARGET` in
`docker-compose.yml`.

## 4. Database was never auto-seeded
The README required a manual `docker compose exec backend python -m
app.seed` step after first boot, easy to miss — an unseeded (but otherwise
fine) database also looks like "not connected." Added
`backend/docker-entrypoint.sh`, which waits for Postgres to actually accept
connections (not just for the container to start) and seeds automatically,
but only the first time the database is empty, so it never wipes data on
later restarts.

## Verified before repackaging
- Every backend `.py` file compiles.
- The full FastAPI app boots in-process (no import/wiring errors).
- Ran `python -m app.seed` against a fresh database, then logged in as
  admin and called the previously-broken endpoints directly:
  `/api/level2/dataset/regional-forecast`, `/api/level2/dataset/supplier-ranking`,
  `/api/datasets/inventory`, and `/api/distributor/hospital-forecast` — all
  returned `200` with real data.
- `npm run build` on the frontend — all 1620 modules across every portal
  page (admin/vendor/distributor/client) transform with no errors.
