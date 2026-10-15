"""Direct port of backend/utils/batchVerify.js — single source of truth for
"verify this batch" across every portal: live Postgres inventory, the CSV
dataset, and the MongoDB blockchain ledger."""
from sqlalchemy.orm import Session

from app.models.sql_models import VendorInventory, DistributorInventory, ClientInventory, Recall
from app.services.dataset_loader import load_datasets
from app.services import blockchain


def verify_batch_everywhere(db: Session, batch: str) -> dict:
    live_matches = []
    for model, extra in [(VendorInventory, {}), (DistributorInventory, {}), (ClientInventory, {})]:
        rows = db.query(model).filter(model.batch == batch).all()
        for r in rows:
            live_matches.append(r)

    csv_match = None
    try:
        inventory = load_datasets()["inventory"]
        csv_match = next((r for r in inventory if r.get("batch_id") == batch), None)
    except Exception:
        csv_match = None

    history = blockchain.get_by_batch(batch)
    recall = db.query(Recall).filter(Recall.batch == batch, Recall.status == "active").first()
    first = live_matches[0] if live_matches else None

    found = bool(live_matches) or bool(history) or bool(csv_match)

    holders = set()
    for m in live_matches:
        holders.add(getattr(m, "client_name", None) or getattr(m, "region", None) or "Vendor")

    return {
        "batch": batch,
        "found": found,
        "drugName": getattr(first, "drug_name", None) or (csv_match or {}).get("drug_name") or (history[0]["data"].get("drugName") if history else None),
        "manufacturer": getattr(first, "manufacturer", None) or (csv_match or {}).get("manufacturer"),
        "expiryDate": getattr(first, "expiry_date", None) or (csv_match or {}).get("expiry_date"),
        "holders": list(holders),
        "activeRecall": {
            "id": recall.id, "batch": recall.batch, "drugName": recall.drug_name, "reason": recall.reason,
            "severity": recall.severity, "status": recall.status,
        } if recall else None,
        "blockchainVerified": len(history) > 0,
        "blockchainEvents": len(history),
        "datasetRecord": {
            "source": "2_inventory_batch.csv",
            "region": csv_match.get("region"),
            "currentStock": csv_match.get("current_stock"),
            "coldChainRequired": csv_match.get("cold_chain_required"),
            "manufactureDate": csv_match.get("manufacture_date"),
        } if csv_match else None,
        "history": history,
    }
