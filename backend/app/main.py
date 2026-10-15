import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.db.postgres import Base, engine, ensure_schema_updates
from app.events_bus import broadcast_update
from app.routers import (
    auth, vendor, distributor, admin, client, blockchain_router, notifications_router,
    level2, datasets, dataset_features, dataset_actions, batch, events,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("medchain")

# Creates every Postgres table on boot if it doesn't already exist — the
# equivalent of the original's "load the JSON file" step, just for a real
# relational schema. Run `python -m app.seed` separately to populate it
# from the legacy db.json + CSV datasets.
Base.metadata.create_all(bind=engine)
ensure_schema_updates()

app = FastAPI(title="MedChain API (Python / FastAPI)", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logger_and_update_broadcaster(request: Request, call_next):
    """Port of server.js's request logger + the 'anything changed -> push an
    SSE update to every tab' behaviour, generalized to any mutating request
    instead of the original's response-body sniffing for specific routes."""
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000)
    logger.info("%s %s -> %s (%sms)", request.method, request.url.path, response.status_code, duration_ms)

    if request.method in ("POST", "PUT", "PATCH", "DELETE") and 200 <= response.status_code < 300 and request.url.path.startswith("/api/"):
        broadcast_update()
    return response


app.include_router(events.router)
app.include_router(notifications_router.router)
app.include_router(auth.router)
app.include_router(vendor.router)
app.include_router(distributor.router)
app.include_router(admin.router)
app.include_router(blockchain_router.router)
app.include_router(client.router)
app.include_router(level2.router)
app.include_router(datasets.router)
app.include_router(dataset_features.router)
app.include_router(dataset_actions.router)
app.include_router(batch.router)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Only rewrites GENUINE routing 404s (no endpoint matched this path)
    into a friendlier message. Explicit `raise HTTPException(404, detail=...)`
    calls inside business logic (e.g. "Batch not found") keep their own
    detail message instead of being clobbered by this handler."""
    from fastapi.responses import JSONResponse
    detail = getattr(exc, "detail", None)
    if not detail or detail == "Not Found":
        detail = f"Route not found: {request.method} {request.url.path}"
    return JSONResponse(status_code=404, content={"detail": detail})


@app.get("/")
def root():
    return {
        "service": "MedChain Drug Supply Chain API (Python / FastAPI)",
        "portals": ["/api/vendor", "/api/distributor", "/api/admin", "/api/client"],
        "blockchainLedger": "/api/blockchain/ledger",
        "docs": "/docs",
    }
