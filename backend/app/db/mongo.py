"""
MongoDB is the home for the blockchain hash-chain ledger and any other
free-form audit/provenance documents, per the polyglot-persistence design:
event payloads vary block-to-block (an ORDER_DISPATCHED block looks nothing
like a COLD_CHAIN_ALERT block), which is exactly the flexible-schema case
MongoDB is good at and a rigid relational table is not.

If MONGODB_URL isn't set (or Mongo isn't reachable), this transparently
falls back to a local JSON-file-backed store in ./data/blockchain_fallback.json
so the app still runs end-to-end without Docker. Swap in real Mongo by
setting MONGODB_URL — no code changes required anywhere else, since every
caller only ever talks to the BlockchainStore interface below.
"""
import json
import logging
from pathlib import Path
from typing import Optional

from app.config import MONGODB_URL, MONGODB_DB, DATA_DIR

logger = logging.getLogger("medchain.mongo")

_client = None
_db = None
_mongo_available = False

if MONGODB_URL:
    try:
        from pymongo import MongoClient

        _client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=2000)
        _client.admin.command("ping")
        _db = _client[MONGODB_DB]
        _mongo_available = True
        logger.info("Connected to MongoDB at %s", MONGODB_URL)
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.warning("MongoDB unavailable (%s). Falling back to local JSON store.", exc)
        _mongo_available = False
else:
    logger.info("MONGODB_URL not set. Using local JSON fallback store for the ledger/audit data.")

FALLBACK_PATH = DATA_DIR / "blockchain_fallback.json"


class _FallbackCollection:
    """Minimal drop-in replacement for the two Mongo operations we need,
    backed by a single JSON file, keyed by collection name."""

    def __init__(self, name: str):
        self.name = name
        self._path = FALLBACK_PATH
        self._ensure_file()

    def _ensure_file(self):
        if not self._path.exists():
            self._path.write_text(json.dumps({}), encoding="utf-8")

    def _read_all(self) -> dict:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write_all(self, data: dict):
        self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def find(self):
        return self._read_all().get(self.name, [])

    def insert_one(self, doc: dict):
        data = self._read_all()
        data.setdefault(self.name, []).append(doc)
        self._write_all(data)
        return doc

    def replace(self, docs: list):
        data = self._read_all()
        data[self.name] = docs
        self._write_all(data)


def get_collection(name: str):
    """Returns a Mongo collection if connected, otherwise the JSON fallback."""
    if _mongo_available:
        return _db[name]
    return _FallbackCollection(name)


def is_mongo_live() -> bool:
    return _mongo_available
