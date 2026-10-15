from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import require_roles
from app.models.sql_models import (
    User, StockRequest, Anomaly, Sale, VendorInventory, DistributorInventory,
    ClientInventory, Settings, Recall, Client,
)
from app.serializers import row_to_dict, rows_to_list
from app.services import ml_engine, blockchain, notifications, client_verification
from app.ml import predict as ml_predict
from app.ml import predict_shortage

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_roles("admin"))])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _settings(db: Session) -> Settings:
    s = db.query(Settings).first()
    if not s:
        s = Settings(id=1, emergency_mode=False)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    chain_status = blockchain.verify_chain()
    anomalies = db.query(Anomaly).all()
    open_anomalies = [a for a in anomalies if a.status in ("open", "investigating")]
    users = db.query(User).all()
    sales = db.query(Sale).all()
    vendor_inv = db.query(VendorInventory).all()
    dist_inv = db.query(DistributorInventory).all()

    return {
        "totalUsers": len(users),
        "usersByRole": {role: len([u for u in users if u.role == role]) for role in ("admin", "vendor", "distributor", "client")},
        "totalStockRequests": db.query(StockRequest).count(),
        "requestsInTransit": db.query(StockRequest).filter(StockRequest.status == "dispatched").count(),
        "pendingRequests": db.query(StockRequest).filter(StockRequest.status == "pending").count(),
        "totalBlocks": len(blockchain.get_all()),
        "chainValid": chain_status["valid"],
        "chainStatus": chain_status,
        "openAnomalies": len(open_anomalies),
        "totalAnomalies": len(anomalies),
        "escalatedAnomalies": len([a for a in anomalies if a.status == "escalated"]),
        "totalSalesAmount": round(sum(s.amount or 0 for s in sales), 2),
        "totalInventoryValueVendor": round(sum((i.stock or 0) * (i.unit_price or 0) for i in vendor_inv), 2),
        "totalInventoryValueDistributor": round(sum((i.stock or 0) * (i.unit_price or 0) for i in dist_inv), 2),
        "emergencyMode": _settings(db).emergency_mode,
        "pendingClientVerifications": client_verification.count_by_status(db.query(Client).all())["pending"],
    }


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(User).all())
    for r in rows:
        r.pop("passwordHash", None)
    return rows


@router.get("/blockchain")
def get_blockchain():
    return blockchain.get_all()


@router.get("/blockchain/verify")
def verify_blockchain():
    return blockchain.verify_chain()


@router.get("/blockchain/provenance/{batch}")
def blockchain_provenance(batch: str):
    return blockchain.get_by_batch(batch)


@router.get("/emergency-mode")
def get_emergency_mode(db: Session = Depends(get_db)):
    return row_to_dict(_settings(db))


@router.post("/emergency-mode")
def set_emergency_mode(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    settings = _settings(db)
    active = bool(body.get("active"))
    settings.emergency_mode = active
    settings.updated_at = _now()
    settings.updated_by = user["email"]
    blockchain.add_block("EMERGENCY_MODE_TOGGLED", user["email"], {
        "active": active,
        "reason": body.get("reason") or ("Regulator activated crisis response mode." if active else "Regulator deactivated crisis response mode."),
    })
    db.commit()
    db.refresh(settings)
    return row_to_dict(settings)


@router.get("/shortage-risk")
def shortage_risk(db: Session = Depends(get_db)):
    sales = rows_to_list(db.query(Sale).all())
    rows = []
    for item in db.query(DistributorInventory).all():
        history = sorted([s for s in sales if s["drugName"] == item.drug_name], key=lambda s: s["date"])
        qty_history = [s["qty"] for s in history]
        avg_daily_demand = (sum(qty_history) / 21) if qty_history else 1
        baseline = ml_engine.shortage_risk(item.stock, avg_daily_demand)
        ml = {"available": False, "reason": "Shortage model not trained yet."}
        try:
            forecast = ml_predict.predict_next_period(item.drug_name, history, 7)
            if forecast.get("available"):
                ml = predict_shortage.predict(item.stock, qty_history, forecast["forecastNextPeriod"], item.lead_time_days or 3)
                ml["forecastDemand"] = forecast["forecastNextPeriod"]
                ml["forecastMethod"] = forecast["method"]
        except Exception as e:
            ml = {"available": False, "reason": str(e)}

        rows.append({
            "drugName": item.drug_name, "batch": item.batch, "region": item.region, "stock": item.stock,
            "avgDailyDemand": round(avg_daily_demand, 1), **baseline,
            "mlShortageProbability": ml.get("shortageProbability"), "mlRiskLevel": ml.get("riskLevel"),
            "mlModel": ml.get("model", "Random Forest Classifier"), "mlAvailable": ml.get("available", True) is not False,
            "forecastDemand": ml.get("forecastDemand"), "modelFeatures": ml.get("features"),
            "modelError": ml.get("reason") if ml.get("available") is False else None,
        })
    rows.sort(key=lambda r: (-(r["mlShortageProbability"] or 0), r["daysOfSupply"]))

    created_any = False
    for row in rows:
        if row["mlRiskLevel"] in ("high", "critical"):
            _, created = notifications.create_notification(
                db, role="admin", type="SHORTAGE", severity=row["mlRiskLevel"],
                title=f"{'Critical' if row['mlRiskLevel'] == 'critical' else 'High'} shortage risk: {row['drugName']}",
                message=f"{row['drugName']} ({row['batch']}) has {row.get('mlShortageProbability', 'unknown')}% ML shortage "
                        f"probability with about {row['daysOfSupply']} day(s) of supply.",
                related_drug=row["drugName"], related_batch=row["batch"], action_path="/admin/shortage-risk",
                event_key=f"shortage:{row['batch']}:{row['mlRiskLevel']}:{round(float(row.get('mlShortageProbability') or 0))}",
            )
            created_any = created_any or created
    if created_any:
        db.commit()
    return rows


@router.get("/anomalies")
def list_anomalies(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(Anomaly).all())
    rows.sort(key=lambda a: a["detectedAt"], reverse=True)
    return rows


@router.post("/anomalies/scan")
def scan_anomalies(db: Session = Depends(get_db)):
    created = []
    for model, portal in [(VendorInventory, "vendor"), (DistributorInventory, "distributor"), (ClientInventory, "client")]:
        for item in db.query(model).all():
            item_dict = row_to_dict(item)
            for f in ml_engine.detect_inventory_anomalies(item_dict):
                already_open = db.query(Anomaly).filter(Anomaly.batch == item.batch, Anomaly.type == f["type"],
                                                          Anomaly.status.in_(["open", "investigating"])).first()
                if already_open:
                    continue
                anomaly = Anomaly(type=f["type"], drug_name=item.drug_name, batch=item.batch, severity=f["severity"],
                                   detected_at=_now(), status="open", source=portal, message=f["message"])
                db.add(anomaly)
                db.flush()
                created.append(row_to_dict(anomaly))
                if f["type"] == "counterfeit-flag":
                    blockchain.add_block("QUARANTINE_TRIGGERED", "system:ml-engine", {"portal": portal, "drugName": item.drug_name, "batch": item.batch, "reason": f["message"]})
                else:
                    blockchain.add_block("ANOMALY_DETECTED", "system:ml-engine", {"portal": portal, "drugName": item.drug_name, "batch": item.batch, "type": f["type"], "severity": f["severity"]})
    if created:
        db.commit()
    message = f"{len(created)} new anomaly case(s) raised." if created else "No new anomalies detected. All batches compliant."
    return {"created": created, "message": message}


@router.post("/anomalies/scan-isolation-forest")
def scan_anomalies_isolation_forest(db: Session = Depends(get_db)):
    """Unsupervised Isolation Forest screening, run separately for each tier (vendor / distributor / client).
    The cases it raises are REVIEW CANDIDATES: there is no labelled real-world ground truth for this
    detector, so they are not validated detections (see EVALUATION.md)."""
    from app.ml import anomaly_detector as ad
    tiers = [("vendor", VendorInventory), ("distributor", DistributorInventory), ("client", ClientInventory)]
    sales_history = rows_to_list(db.query(Sale).all())

    created, tier_summary, flagged_total, scanned_total = [], [], 0, 0
    for portal, model in tiers:
        items = db.query(model).all()
        dicts = [row_to_dict(i) for i in items]
        results = ad.scan_inventory_with_isolation_forest(dicts, sales_history)
        if not results:
            tier_summary.append({"tier": portal, "records": len(items), "scanned": False,
                                  "note": f"skipped: fewer than {ad.MIN_POPULATION} records"})
            continue
        scanned_total += len(items)
        flagged = [r for r in results if r["anomaly"]]
        flagged_total += len(flagged)
        tier_summary.append({"tier": portal, "records": len(items), "scanned": True, "flagged": len(flagged)})

        for item, result in zip(items, results):
            if not result["anomaly"]:
                continue
            already_open = db.query(Anomaly).filter(Anomaly.batch == item.batch, Anomaly.type == "ml-inventory-anomaly",
                                                      Anomaly.status.in_(["open", "investigating"])).first()
            if already_open:
                continue
            anomaly = Anomaly(type="ml-inventory-anomaly", drug_name=item.drug_name, batch=item.batch,
                               severity=result["severity"], detected_at=_now(), status="open", source=portal,
                               message=result["reason"], model="Isolation Forest", anomaly_score=result["score"],
                               features=result["features"])
            db.add(anomaly)
            db.flush()
            created.append(row_to_dict(anomaly))
            blockchain.add_block("ANOMALY_DETECTED", "system:isolation-forest", {
                "portal": portal, "drugName": item.drug_name, "batch": item.batch, "severity": result["severity"],
                "anomalyScore": result["score"], "model": "Isolation Forest",
                "validation": "unsupervised review candidate (no ground truth)"})
    if created:
        db.commit()

    skipped = [t["tier"] for t in tier_summary if not t["scanned"]]
    message = (f"{len(created)} new review candidate(s) raised by Isolation Forest (unsupervised, not a validated detection)."
               if created else "Isolation Forest found no new unusual inventory patterns.")
    if skipped:
        message += f" Skipped (too few records): {', '.join(skipped)}."
    return {"model": "Isolation Forest", "scannedRecords": scanned_total, "anomaliesFound": flagged_total,
            "created": created, "tiers": tier_summary, "message": message,
            "note": "Unsupervised screening; no labelled real-world anomalies exist to validate it."}


@router.put("/anomalies/{anomaly_id}")
def update_anomaly(anomaly_id: int, body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    anomaly = db.query(Anomaly).filter(Anomaly.id == anomaly_id).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly case not found.")
    status = body.get("status")
    allowed = ["open", "investigating", "escalated", "resolved"]
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {', '.join(allowed)}.")
    anomaly.status = status
    anomaly.updated_at = _now()
    anomaly.updated_by = user["email"]
    if status == "resolved":
        blockchain.add_block("COMPLIANCE_VERIFIED", user["email"], {"drugName": anomaly.drug_name, "batch": anomaly.batch,
                              "type": anomaly.type, "resolution": "Case reviewed and resolved by regulator."})
    elif status == "escalated":
        blockchain.add_block("CASE_ESCALATED", user["email"], {"drugName": anomaly.drug_name, "batch": anomaly.batch, "type": anomaly.type})
    db.commit()
    db.refresh(anomaly)
    return row_to_dict(anomaly)


@router.get("/recalls")
def list_recalls(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(Recall).all())
    rows.sort(key=lambda r: r["issuedAt"], reverse=True)
    return rows


@router.post("/recalls", status_code=201)
def issue_recall(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    batch, drug_name, reason = body.get("batch"), body.get("drugName"), body.get("reason")
    if not batch or not drug_name or not reason:
        raise HTTPException(status_code=400, detail="batch, drugName and reason are required to issue a recall.")
    vendor_holds = db.query(VendorInventory).filter(VendorInventory.batch == batch).all()
    dist_holds = db.query(DistributorInventory).filter(DistributorInventory.batch == batch).all()
    client_holds = db.query(ClientInventory).filter(ClientInventory.batch == batch).all()
    severity = body.get("severity") if body.get("severity") in ("high", "critical") else "high"

    recall = Recall(batch=batch, drug_name=drug_name, reason=reason, severity=severity, issued_by=user["email"],
                     issued_at=_now(), status="active",
                     affected_holders={"vendor": len(vendor_holds) > 0,
                                        "distributorRegions": list({h.region for h in dist_holds}),
                                        "clients": list({h.client_name for h in client_holds})},
                     acknowledged_by=[])
    db.add(recall)
    db.flush()
    blockchain.add_block("DRUG_RECALL_ISSUED", user["email"], {"recallId": recall.id, "batch": batch, "drugName": drug_name,
                          "reason": reason, "severity": severity, "affectedHolders": recall.affected_holders})
    notifications.create_notification(db, role=None, type="RECALL", severity=severity,
        title=f"Drug recall issued: {drug_name}", message=f"Batch {batch} was recalled. Reason: {reason}",
        related_drug=drug_name, related_batch=batch, action_path="/admin/recalls", event_key=f"recall:{recall.id}")
    db.commit()
    db.refresh(recall)
    return row_to_dict(recall)


@router.post("/recalls/{recall_id}/resolve")
def resolve_recall(recall_id: int, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    recall = db.query(Recall).filter(Recall.id == recall_id).first()
    if not recall:
        raise HTTPException(status_code=404, detail="Recall not found.")
    if recall.status != "active":
        raise HTTPException(status_code=400, detail="Only active recalls can be resolved.")
    recall.status = "resolved"
    recall.resolved_at = _now()
    recall.resolved_by = user["email"]
    blockchain.add_block("DRUG_RECALL_RESOLVED", user["email"], {"recallId": recall.id, "batch": recall.batch, "drugName": recall.drug_name})
    db.commit()
    db.refresh(recall)
    return row_to_dict(recall)


# ---------- Client verification (Distributor adds a client -> Admin approves / rejects) ----------
def _client_or_404(db: Session, client_id: int) -> Client:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found.")
    return client


@router.get("/client-verifications")
def list_client_verifications(status: str = "all", db: Session = Depends(get_db)):
    """The Admin's verification queue. `status` = pending | approved | rejected | all."""
    clients = db.query(Client).all()
    items = []
    for c in clients:
        s = client_verification.effective_status(c.verification_status, c.license_verified)
        if status in client_verification.STATUSES and s != status:
            continue
        row = row_to_dict(c)
        row["verificationStatus"] = s
        items.append(row)
    items.sort(key=lambda r: r.get("onboardedAt") or "", reverse=True)
    counts = client_verification.count_by_status(clients)
    return {"counts": counts, "total": len(clients), "items": items}


@router.post("/client-verifications/{client_id}/approve")
def approve_client(client_id: int, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    client = _client_or_404(db, client_id)
    current = client_verification.effective_status(client.verification_status, client.license_verified)
    if not client_verification.can_approve(current):
        raise HTTPException(status_code=400, detail=f"{client.name} is already {current}.")

    now = _now()
    client.verification_status = "approved"
    client.license_verified = True
    client.verified_by = user["email"]
    client.verified_at = now
    client.rejection_reason = None
    account = db.query(User).filter(User.id == client.user_id).first()
    if account:
        account.license_verified = True

    blockchain.add_block("CLIENT_VERIFIED", user["email"], {
        "clientId": client.id, "clientName": client.name, "type": client.type, "region": client.region,
        "onboardedBy": client.onboarded_by, "decision": "approved"})
    notifications.create_notification(
        db, user_id=client.user_id, type="SYSTEM", severity="info",
        title="Your account was approved",
        message="The Admin verified your account. You now have full access to the client portal.",
        action_path="/client")
    notifications.create_notification(
        db, role="distributor", type="SYSTEM", severity="info",
        title="Client approved by Admin",
        message=f"{client.name} ({client.region}) was verified and can now sign in and place requests.",
        action_path="/distributor/clients")
    db.commit()
    db.refresh(client)
    return row_to_dict(client)


@router.post("/client-verifications/{client_id}/reject")
def reject_client(client_id: int, body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    reason = str((body or {}).get("reason") or "").strip()
    if len(reason) < 3:
        raise HTTPException(status_code=400, detail="A reason is required to reject a client.")
    client = _client_or_404(db, client_id)
    current = client_verification.effective_status(client.verification_status, client.license_verified)
    if not client_verification.can_reject(current):
        raise HTTPException(status_code=400, detail=f"{client.name} is already {current}.")

    now = _now()
    client.verification_status = "rejected"
    client.license_verified = False
    client.verified_by = user["email"]
    client.verified_at = now
    client.rejection_reason = reason
    account = db.query(User).filter(User.id == client.user_id).first()
    if account:
        account.license_verified = False

    blockchain.add_block("CLIENT_REJECTED", user["email"], {
        "clientId": client.id, "clientName": client.name, "type": client.type, "region": client.region,
        "onboardedBy": client.onboarded_by, "decision": "rejected", "reason": reason})
    notifications.create_notification(
        db, role="distributor", type="SYSTEM", severity="high",
        title="Client rejected by Admin",
        message=f"{client.name} ({client.region}) was rejected. Reason: {reason}",
        action_path="/distributor/clients")
    db.commit()
    db.refresh(client)
    return row_to_dict(client)


@router.get("/audit-report")
def audit_report(db: Session = Depends(get_db)):
    from app.models.sql_models import ClientRequest
    chain_status = blockchain.verify_chain()
    return {
        "generatedAt": _now(),
        "chainIntegrity": chain_status,
        "totalTransactionsOnLedger": len(blockchain.get_all()),
        "stockRequests": rows_to_list(db.query(StockRequest).all()),
        "clientRequests": rows_to_list(db.query(ClientRequest).all()),
        "sales": rows_to_list(db.query(Sale).all()),
        "anomalies": rows_to_list(db.query(Anomaly).all()),
        "recalls": rows_to_list(db.query(Recall).all()),
        "vendorInventorySnapshot": rows_to_list(db.query(VendorInventory).all()),
        "distributorInventorySnapshot": rows_to_list(db.query(DistributorInventory).all()),
        "clientInventorySnapshot": rows_to_list(db.query(ClientInventory).all()),
        "emergencyMode": _settings(db).emergency_mode,
    }
