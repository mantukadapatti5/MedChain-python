"""
Direct port of backend/utils/blockchain.js, restructured to persist every
block in MongoDB (per the polyglot-persistence design: audit/provenance
events are document-shaped, MongoDB is the store of record for them)
instead of an in-memory array inside db.json.

Every state-changing action across every portal (order placed, dispatched,
received, sale recorded, inventory updated, anomaly raised, quarantine
triggered, compliance verified, cold-chain alert...) is written here as a
block. Each block hashes the previous block's hash, so any tampering with
historical data is detectable via verify_chain().
"""
import hashlib
import json
from datetime import datetime, timezone

from app.db.mongo import get_collection

COLLECTION = "blockchain_blocks"
GENESIS_TIMESTAMP = "2026-01-01T00:00:00+00:00"


def _compute_hash(block: dict) -> str:
    # NOTE: must byte-for-byte match JS's `JSON.stringify(data)` — no sorted
    # keys (JS preserves insertion order, same as Python dicts from
    # json.loads) and no spaces after ',' / ':' (JS's stringify has none by
    # default, while Python's json.dumps defaults to ", "/": "). Getting
    # this wrong silently breaks verify_chain() for every block migrated
    # from the original db.json, since their hashes were computed by JS.
    payload = (
        str(block["index"])
        + block["timestamp"]
        + block["type"]
        + block["actor"]
        + json.dumps(block["data"], separators=(",", ":"), default=str)
        + block["prevHash"]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _genesis_block() -> dict:
    block = {
        "index": 0,
        "timestamp": GENESIS_TIMESTAMP,
        "type": "GENESIS",
        "actor": "system",
        "data": {"message": "Drug Supply Chain Ledger Initialized"},
        "prevHash": "0",
    }
    block["hash"] = _compute_hash(block)
    return block


def _all_blocks() -> list:
    col = get_collection(COLLECTION)
    blocks = list(col.find({}, {"_id": 0})) if hasattr(col, "count_documents") else col.find()
    if not blocks:
        genesis = _genesis_block()
        col.insert_one(dict(genesis))
        return [genesis]
    return sorted(blocks, key=lambda b: b["index"])


def get_all() -> list:
    return _all_blocks()


def add_block(block_type: str, actor: str, data: dict) -> dict:
    blocks = _all_blocks()
    prev = blocks[-1]
    block = {
        "index": prev["index"] + 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": block_type,
        "actor": actor,
        "data": data,
        "prevHash": prev["hash"],
    }
    block["hash"] = _compute_hash(block)
    get_collection(COLLECTION).insert_one(dict(block))
    return block


def verify_chain() -> dict:
    blocks = _all_blocks()
    if not blocks:
        return {"valid": False, "brokenAt": 0, "reason": "Ledger is empty"}
    genesis = blocks[0]
    if genesis.get("hash") != _compute_hash(genesis) or genesis.get("prevHash") != "0":
        return {"valid": False, "brokenAt": 0, "reason": "Genesis block invalid or tampered"}

    for i in range(1, len(blocks)):
        current, previous = blocks[i], blocks[i - 1]
        if current.get("hash") != _compute_hash(current):
            return {"valid": False, "brokenAt": current["index"], "reason": "Hash mismatch (data tampered)"}
        if current.get("prevHash") != previous.get("hash"):
            return {"valid": False, "brokenAt": current["index"], "reason": "Chain link broken (prevHash mismatch)"}
    return {"valid": True}


def _matches_batch(value, batch_no) -> bool:
    if value is None or not isinstance(value, (dict, list)):
        return False
    if isinstance(value, dict):
        if value.get("batch") == batch_no or value.get("batchNo") == batch_no:
            return True
        return any(_matches_batch(v, batch_no) for v in value.values())
    if isinstance(value, list):
        return any(_matches_batch(v, batch_no) for v in value)
    return False


def get_by_batch(batch_no: str) -> list:
    return [b for b in _all_blocks() if _matches_batch(b.get("data"), batch_no)]
