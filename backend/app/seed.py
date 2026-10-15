"""
One-time migration: reads the ORIGINAL project's data/db_seed_source.json
(a straight copy of the old Node.js backend's db.json) and loads every
collection into its new home:

  - Every business collection (users, clients, inventories, requests, sales,
    billing, anomalies, recalls, ...) -> PostgreSQL, via the SQLAlchemy
    models in app/models/sql_models.py.
  - The `blockchain` array -> MongoDB (or its local-file fallback), via
    app/services/blockchain.py, preserving the original chain's blocks and
    hash links exactly rather than re-generating a new genesis block.

The 6 CSV datasets are NOT migrated into a database — per the architecture
decision they stay as the read-only seed/training/import data they already
are (see app/services/dataset_loader.py), consistent with "the existing
CSV datasets can continue to serve as seed/training/import data; they do
not need to disappear."

Run with:  python -m app.seed
Safe to re-run: it clears and reloads every Postgres table each time
(this is a fresh migration script for setting up a new environment, not an
incremental sync).
"""
import json

from app.config import DATA_DIR
from app.db.postgres import Base, engine, SessionLocal
from app.db.mongo import get_collection
from app.services.blockchain import COLLECTION as BLOCKCHAIN_COLLECTION
from app.models import sql_models as m

SOURCE_PATH = DATA_DIR / "db_seed_source.json"


def _load_source() -> dict:
    return json.loads(SOURCE_PATH.read_text(encoding="utf-8"))


def _reset_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed():
    data = _load_source()
    _reset_schema()
    db = SessionLocal()

    try:
        for u in data.get("users", []):
            db.add(m.User(id=u["id"], name=u["name"], email=u["email"], password_hash=u["passwordHash"],
                           role=u["role"], mfa_enabled=u.get("mfaEnabled", False),
                           license_verified=u.get("licenseVerified", False)))
        db.flush()

        for c in data.get("clients", []):
            db.add(m.Client(id=c["id"], user_id=c["userId"], name=c["name"], type=c.get("type"), region=c.get("region"),
                             contact_person=c.get("contactPerson"), phone=c.get("phone"), email=c.get("email"),
                             license_verified=c.get("licenseVerified", False), onboarded_at=c.get("onboardedAt"),
                             verification_status="approved" if c.get("licenseVerified", False) else "pending",
                             onboarded_by=c.get("onboardedBy") or "dis@gmail.com",
                             verified_by="seed-data" if c.get("licenseVerified", False) else None))
        db.flush()

        for r in data.get("regions", []):
            db.add(m.Region(id=r["id"], name=r["name"]))

        for i in data.get("vendorInventory", []):
            db.add(m.VendorInventory(id=i["id"], drug_name=i["drugName"], category=i.get("category"), batch=i["batch"],
                                      manufacturer=i.get("manufacturer"), manufacture_date=i.get("manufactureDate"),
                                      stock=i.get("stock", 0), reorder_point=i.get("reorderPoint", 50),
                                      unit_price=i.get("unitPrice", 0), expiry_date=i.get("expiryDate"),
                                      cold_chain=i.get("coldChain", False), provenance_checksum=i.get("provenanceChecksum")))

        for i in data.get("distributorInventory", []):
            db.add(m.DistributorInventory(id=i["id"], drug_name=i["drugName"], category=i.get("category"), batch=i["batch"],
                                           manufacturer=i.get("manufacturer"), region=i.get("region"), stock=i.get("stock", 0),
                                           reorder_point=i.get("reorderPoint", 50), unit_price=i.get("unitPrice", 0),
                                           expiry_date=i.get("expiryDate"), cold_chain=i.get("coldChain", False),
                                           provenance_checksum=i.get("provenanceChecksum")))

        for i in data.get("clientInventory", []):
            db.add(m.ClientInventory(id=i["id"], client_id=i["clientId"], client_name=i.get("clientName"),
                                      drug_name=i["drugName"], batch=i["batch"], manufacturer=i.get("manufacturer"),
                                      stock=i.get("stock", 0), reorder_point=i.get("reorderPoint", 10),
                                      unit_price=i.get("unitPrice", 0), expiry_date=i.get("expiryDate"),
                                      cold_chain=i.get("coldChain", False), provenance_checksum=i.get("provenanceChecksum")))

        for r in data.get("stockRequests", []):
            db.add(m.StockRequest(id=r["id"], drug_name=r["drugName"], qty_requested=r["qtyRequested"], region=r.get("region"),
                                   priority=r.get("priority", "routine"), status=r.get("status", "pending"),
                                   requested_by=r.get("requestedBy"), created_at=r.get("createdAt"), approved_at=r.get("approvedAt"),
                                   dispatched_at=r.get("dispatchedAt"), received_at=r.get("receivedAt"),
                                   qty_dispatched=r.get("qtyDispatched"), qty_received=r.get("qtyReceived"),
                                   batches_allocated=r.get("batchesAllocated", []), gps_log=r.get("gpsLog", []),
                                   cold_chain_log=r.get("coldChainLog", []), rejection_reason=r.get("rejectionReason"),
                                   destination=r.get("destination") or {}))

        for r in data.get("clientRequests", []):
            db.add(m.ClientRequest(id=r["id"], client_id=r["clientId"], client_name=r.get("clientName"), drug_name=r["drugName"],
                                    qty_requested=r["qtyRequested"], region=r.get("region"), priority=r.get("priority", "routine"),
                                    status=r.get("status", "pending"), created_at=r.get("createdAt"), approved_at=r.get("approvedAt"),
                                    dispatched_at=r.get("dispatchedAt"), received_at=r.get("receivedAt"),
                                    qty_dispatched=r.get("qtyDispatched"), qty_received=r.get("qtyReceived"),
                                    batches_allocated=r.get("batchesAllocated", []), gps_log=r.get("gpsLog", []),
                                    cold_chain_log=r.get("coldChainLog", []), rejection_reason=r.get("rejectionReason"),
                                    destination=r.get("destination") or {}))

        for s in data.get("sales", []):
            db.add(m.Sale(id=s["id"], drug_name=s["drugName"], batch=s.get("batch"), qty=s["qty"],
                           unit_price=s.get("unitPrice"), amount=s.get("amount"), buyer=s.get("buyer"),
                           region=s.get("region"), date=s.get("date")))

        for b in data.get("billing", []):
            db.add(m.Billing(id=b["id"], request_id=b.get("requestId"), drug_name=b.get("drugName"),
                              amount=b.get("amount"), status=b.get("status", "pending"), date=b.get("date")))

        for a in data.get("anomalies", []):
            db.add(m.Anomaly(id=a["id"], type=a["type"], drug_name=a.get("drugName"), batch=a.get("batch"),
                              severity=a.get("severity"), detected_at=a.get("detectedAt"), status=a.get("status", "open"),
                              source=a.get("source"), message=a.get("message"), model=a.get("model"),
                              anomaly_score=a.get("anomalyScore"), features=a.get("features") or {}))

        for c in data.get("coldChainLogs", []):
            db.add(m.ColdChainLog(id=c["id"], portal=c.get("portal"), batch=c.get("batch"), temp=c.get("temp"),
                                   humidity=c.get("humidity"), timestamp=c.get("timestamp"), alert=c.get("alert", False)))

        for i, p in enumerate(data.get("supplierPerformance", []), start=1):
            db.add(m.SupplierPerformance(id=i, vendor_name=p.get("vendorName"), on_time_delivery_rate=p.get("onTimeDeliveryRate"),
                                          quality_score=p.get("qualityScore"), avg_response_hours=p.get("avgResponseHours"),
                                          orders_fulfilled=p.get("ordersFulfilled")))

        settings = data.get("settings") or {}
        db.add(m.Settings(id=1, emergency_mode=settings.get("emergencyMode", False),
                           updated_at=settings.get("updatedAt"), updated_by=settings.get("updatedBy")))

        for r in data.get("recalls", []):
            db.add(m.Recall(id=r["id"], batch=r.get("batch"), drug_name=r.get("drugName"), reason=r.get("reason"),
                             severity=r.get("severity", "high"), issued_by=r.get("issuedBy"), issued_at=r.get("issuedAt"),
                             status=r.get("status", "active"), resolved_at=r.get("resolvedAt"), resolved_by=r.get("resolvedBy"),
                             affected_holders=r.get("affectedHolders") or {}, acknowledged_by=r.get("acknowledgedBy") or []))

        for p in data.get("productionRuns", []):
            db.add(m.ProductionRun(id=p["id"], drug_name=p.get("drugName"), batch=p.get("batch"), qty_produced=p.get("qtyProduced"),
                                    stock_before=p.get("stockBefore"), stock_after=p.get("stockAfter"), reason=p.get("reason"),
                                    triggered_by=p.get("triggeredBy"), emergency_mode=p.get("emergencyMode"), created_at=p.get("createdAt")))

        for u in data.get("clientUsageLog", []):
            db.add(m.ClientUsageLog(id=u["id"], client_id=u.get("clientId"), client_name=u.get("clientName"),
                                     drug_name=u.get("drugName"), qty=u.get("qty"), note=u.get("note"),
                                     batches_used=u.get("batchesUsed") or [], recorded_at=u.get("recordedAt")))

        for n in data.get("notifications", []):
            db.add(m.Notification(id=n["id"], user_id=n.get("userId"), role=n.get("role"), type=n.get("type", "SYSTEM"),
                                   severity=n.get("severity", "info"), title=n["title"], message=n["message"],
                                   related_drug=n.get("relatedDrug"), related_batch=n.get("relatedBatch"),
                                   related_request_id=n.get("relatedRequestId"), action_path=n.get("actionPath"),
                                   event_key=n.get("eventKey"), read=n.get("read", False), created_at=n.get("createdAt"),
                                   read_at=n.get("readAt")))

        for p in data.get("procurementSelections", []) or []:
            db.add(m.ProcurementSelection(id=p["id"], drug_name=p.get("drugName"), qty=p.get("qty"), region=p.get("region"),
                                           supplier_name=p.get("supplierName"), reason=p.get("reason"),
                                           created_at=p.get("createdAt"), created_by=p.get("createdBy")))

        for t in data.get("redistributionTransfers", []) or []:
            db.add(m.RedistributionTransfer(id=t["id"], drug_name=t.get("drugName"), from_region=t.get("fromRegion"),
                                             to_region=t.get("toRegion"), qty=t.get("qty"), moved_batches=t.get("movedBatches") or [],
                                             created_at=t.get("createdAt"), created_by=t.get("createdBy")))

        db.commit()
        print(f"PostgreSQL: seeded {len(data.get('users', []))} users, {len(data.get('vendorInventory', []))} vendor batches, "
              f"{len(data.get('distributorInventory', []))} distributor batches, {len(data.get('sales', []))} sales, "
              f"{len(data.get('stockRequests', []))} stock requests, {len(data.get('clientRequests', []))} client requests.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # ---- Blockchain ledger -> MongoDB (or local fallback) ----
    chain = data.get("blockchain", [])
    if chain:
        col = get_collection(BLOCKCHAIN_COLLECTION)
        if hasattr(col, "delete_many"):
            col.delete_many({})
            col.insert_many([dict(b) for b in chain])
        else:
            col.replace([dict(b) for b in chain])
        print(f"MongoDB (or fallback): seeded {len(chain)} blockchain blocks.")


if __name__ == "__main__":
    seed()
