import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import require_roles
from app.models.sql_models import (
    VendorInventory, StockRequest, Billing, ColdChainLog, Anomaly, Sale,
    Settings, ProductionRun, ProcurementSelection,
)
from app.serializers import row_to_dict, rows_to_list
from app.services import ml_engine, fefo, inventory_guard, blockchain, notifications, telemetry, supplier_ranking

router = APIRouter(prefix="/api/vendor", tags=["vendor"], dependencies=[Depends(require_roles("vendor", "admin"))])

PRIORITY_WEIGHT = {"critical": 3, "urgent": 2, "routine": 1}


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


# ---------- Dashboard ----------
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    inv = db.query(VendorInventory).all()
    inv_dicts = rows_to_list(inv)
    low_stock = [i for i in inv_dicts if i["stock"] <= i["reorderPoint"]]
    near_expiry = [i for i in inv_dicts if any(a["type"] in ("near-expiry", "expired") for a in ml_engine.detect_inventory_anomalies(i))]
    pending = db.query(StockRequest).filter(StockRequest.status == "pending").count()
    in_transit = db.query(StockRequest).filter(StockRequest.status == "dispatched").count()
    total_value = sum(i["stock"] * i["unitPrice"] for i in inv_dicts)
    outstanding_billing = sum(b.amount for b in db.query(Billing).filter(Billing.status == "pending").all())

    return {
        "totalDrugs": len({i["drugName"] for i in inv_dicts}),
        "totalBatches": len(inv_dicts),
        "totalStockUnits": sum(i["stock"] for i in inv_dicts),
        "lowStockCount": len(low_stock),
        "nearExpiryCount": len(near_expiry),
        "pendingRequests": pending,
        "inTransit": in_transit,
        "inventoryValue": round(total_value, 2),
        "outstandingBilling": round(outstanding_billing, 2),
        "lowStockItems": low_stock,
        "emergencyMode": _settings(db).emergency_mode,
    }


# ---------- Inventory ----------
@router.get("/inventory")
def list_inventory(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(VendorInventory).all())
    for r in rows:
        r["flags"] = ml_engine.detect_inventory_anomalies(r)
    return rows


@router.post("/inventory", status_code=201)
def create_inventory(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("vendor", "admin"))):
    if not body.get("drugName") or not body.get("batch") or body.get("stock") is None or not body.get("expiryDate"):
        raise HTTPException(status_code=400, detail="drugName, batch, stock and expiryDate are required.")
    item = VendorInventory(
        drug_name=body["drugName"], category=body.get("category") or "General", batch=body["batch"],
        manufacturer=body.get("manufacturer") or "Sunrise Pharma", stock=float(body["stock"]),
        reorder_point=float(body.get("reorderPoint") or 50), unit_price=float(body.get("unitPrice") or 0),
        expiry_date=body["expiryDate"], cold_chain=bool(body.get("coldChain")),
        provenance_checksum=ml_engine.compute_provenance_checksum(body["batch"], body.get("manufacturer")),
    )
    db.add(item)
    db.flush()
    blockchain.add_block("INVENTORY_UPDATE", user["email"], {"portal": "vendor", "action": "batch-created",
                          "drugName": item.drug_name, "batch": item.batch, "stock": item.stock})
    db.commit()
    db.refresh(item)
    return row_to_dict(item)


@router.put("/inventory/{item_id}")
def update_inventory(item_id: int, body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("vendor", "admin"))):
    item = db.query(VendorInventory).filter(VendorInventory.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    before = item.stock
    error = inventory_guard.apply_safe_inventory_update(item, body)
    if error:
        raise HTTPException(status_code=400, detail=error)
    blockchain.add_block("INVENTORY_UPDATE", user["email"], {"portal": "vendor", "action": "stock-adjusted",
                          "drugName": item.drug_name, "batch": item.batch, "stockBefore": before, "stockAfter": item.stock})
    db.commit()
    db.refresh(item)
    return row_to_dict(item)


# ---------- Incoming Stock Requests (from Distributor) ----------
@router.get("/stock-requests")
def list_stock_requests(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(StockRequest).all())
    rows.sort(key=lambda r: (-(PRIORITY_WEIGHT.get(r["priority"], 0)), r["createdAt"]))
    return rows


@router.post("/stock-requests/{request_id}/approve")
def approve_stock_request(request_id: int, db: Session = Depends(get_db), user: dict = Depends(require_roles("vendor", "admin"))):
    request = db.query(StockRequest).filter(StockRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Stock request not found.")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail=f"Only pending requests can be approved. Current status: {request.status}.")

    inventory_rows = db.query(VendorInventory).all()
    result = fefo.allocate_fefo(inventory_rows, request.drug_name, request.qty_requested)
    if result["totalAllocated"] == 0:
        raise HTTPException(status_code=400, detail=f"No available stock for {request.drug_name}. Add inventory before approving.")

    now = _now()
    request.status = "dispatched"
    request.approved_at = now
    request.dispatched_at = now
    request.qty_dispatched = result["totalAllocated"]
    request.batches_allocated = result["allocated"]
    gps_log = list(request.gps_log or [])
    gps_log.append({"lat": 12.9716, "lng": 77.5946, "timestamp": now, "label": "Departed Vendor Warehouse"})
    request.gps_log = gps_log
    telemetry.record_gps_ping(request.id, "Vendor \u2192 Distributor", 12.9716, 77.5946, now, "Departed Vendor Warehouse")

    is_cold_chain = any(a["coldChain"] for a in result["allocated"])
    if is_cold_chain:
        cc_log = list(request.cold_chain_log or [])
        cc_log.append({"temp": 4.6, "humidity": 39, "timestamp": now, "alert": False})
        request.cold_chain_log = cc_log

    avg_unit_price = sum(a["unitPrice"] * a["qty"] for a in result["allocated"]) / result["totalAllocated"]
    invoice = Billing(request_id=request.id, drug_name=request.drug_name,
                       amount=round(avg_unit_price * result["totalAllocated"], 2), status="pending", date=now)
    db.add(invoice)

    blockchain.add_block("STOCK_REQUEST_APPROVED", user["email"], {
        "portal": "vendor", "requestId": request.id, "drugName": request.drug_name, "region": request.region,
        "qtyRequested": request.qty_requested, "qtyDispatched": result["totalAllocated"], "shortfall": result["shortfall"],
        "batchesAllocated": [{"batch": a["batch"], "qty": a["qty"], "expiryDate": a["expiryDate"]} for a in result["allocated"]],
    })
    blockchain.add_block("ORDER_DISPATCHED", user["email"], {"portal": "vendor", "requestId": request.id,
                          "drugName": request.drug_name, "qty": result["totalAllocated"]})

    if request.priority == "critical":
        notifications.create_notification(db, role="distributor", type="SHIPMENT", severity="critical",
            title=f"Shipment dispatched: {request.drug_name}",
            message=f"Stock request #{request.id} has been dispatched with {result['totalAllocated']} unit(s) to {request.region}.",
            related_drug=request.drug_name, related_request_id=request.id, action_path="/distributor/requests",
            event_key=f"dispatch:{request.id}:{now}")
    else:
        notifications.create_notification(db, role="distributor", type="SHIPMENT", severity="info",
            title=f"Shipment dispatched: {request.drug_name}",
            message=f"Stock request #{request.id} has been dispatched with {result['totalAllocated']} unit(s) to {request.region}.",
            related_drug=request.drug_name, related_request_id=request.id, action_path="/distributor/requests",
            event_key=f"dispatch:{request.id}:{now}")

    db.commit()
    db.refresh(request)
    message = (f"Partially fulfilled: {result['totalAllocated']}/{request.qty_requested} units (insufficient stock)."
               if result["shortfall"] > 0 else "Request fully approved and dispatched via FEFO allocation.")
    return {"request": row_to_dict(request), "shortfall": result["shortfall"], "message": message}


@router.post("/stock-requests/{request_id}/reject")
def reject_stock_request(request_id: int, body: dict = None, db: Session = Depends(get_db), user: dict = Depends(require_roles("vendor", "admin"))):
    body = body or {}
    request = db.query(StockRequest).filter(StockRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Stock request not found.")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail=f"Only pending requests can be rejected. Current status: {request.status}.")
    request.status = "rejected"
    request.rejection_reason = body.get("reason", "Not specified")
    blockchain.add_block("STOCK_REQUEST_REJECTED", user["email"], {"portal": "vendor", "requestId": request.id,
                          "drugName": request.drug_name, "reason": request.rejection_reason})
    db.commit()
    db.refresh(request)
    return row_to_dict(request)


# ---------- Billing ----------
@router.get("/billing")
def list_billing(db: Session = Depends(get_db)):
    return rows_to_list(db.query(Billing).all())


# ---------- Cold Chain Monitoring ----------
@router.get("/cold-chain")
def cold_chain(db: Session = Depends(get_db)):
    cold_batches = db.query(VendorInventory).filter(VendorInventory.cold_chain.is_(True)).all()
    out = []
    for item in cold_batches:
        readings = db.query(ColdChainLog).filter(ColdChainLog.portal == "vendor", ColdChainLog.batch == item.batch).order_by(ColdChainLog.timestamp.desc()).all()
        d = row_to_dict(item)
        d["latestReading"] = row_to_dict(readings[0]) if readings else None
        d["readingCount"] = len(readings)
        out.append(d)
    return out


@router.post("/cold-chain/{batch}/reading")
def cold_chain_reading(batch: str, body: dict = None, db: Session = Depends(get_db)):
    import random
    body = body or {}
    item = db.query(VendorInventory).filter(VendorInventory.batch == batch).first()
    if not item:
        raise HTTPException(status_code=404, detail="Batch not found in vendor inventory.")
    if not item.cold_chain:
        raise HTTPException(status_code=400, detail="This batch is not marked as cold-chain.")

    temp = float(body["temp"]) if body.get("temp") is not None else round(4 + random.random() * 6, 1)
    humidity = float(body["humidity"]) if body.get("humidity") is not None else round(35 + random.random() * 30)
    result = ml_engine.check_cold_chain(temp, humidity)
    now = _now()
    reading = ColdChainLog(portal="vendor", batch=item.batch, temp=temp, humidity=humidity, timestamp=now, alert=result["breached"])
    db.add(reading)
    telemetry.record_cold_chain_reading("vendor", item.batch, temp, humidity, now, result["breached"])

    if result["breached"]:
        anomaly = Anomaly(type="cold-chain-breach", drug_name=item.drug_name, batch=item.batch, severity="high",
                           detected_at=now, status="open", source="vendor", message="; ".join(result["alerts"]))
        db.add(anomaly)
        blockchain.add_block("COLD_CHAIN_ALERT", "system:iot-sensor", {"portal": "vendor", "drugName": item.drug_name,
                              "batch": item.batch, "temp": temp, "humidity": humidity, "timestamp": now})
        notifications.create_notification(db, role="admin", type="COLD_CHAIN", severity="high",
            title=f"Cold-chain breach: {item.drug_name}", message="; ".join(result["alerts"]),
            related_drug=item.drug_name, related_batch=item.batch, action_path="/admin/anomalies",
            event_key=f"cold-chain:{item.batch}:{now[:16]}")

    db.commit()
    return {"reading": row_to_dict(reading), "breached": result["breached"], "alerts": result["alerts"]}


@router.get("/demand-forecast-v2/catalog")
def demand_forecast_v2_catalog():
    """Drugs/regions available in the new dataset, for the UI's dropdowns."""
    from app.ml.demand.predict import catalog
    return catalog()


@router.get("/demand-forecast-v2")
def demand_forecast_v2(drugId: str, region: str, days: int = 7):
    """
    New vendor demand-forecasting endpoint: LSTM + Random Forest + XGBoost
    ensemble, trained on module5_drug_consumption_history.csv (182K+ rows,
    2022-2026, 20 drugs x 10 regions). Returns historical actuals plus a
    multi-day-ahead forecast from each model and the combined ensemble,
    ready to plot as a line chart.
    """
    from app.ml.demand.predict import forecast_series
    if days not in (7, 14, 30):
        raise HTTPException(status_code=400, detail="days must be 7, 14, or 30")
    result = forecast_series(drugId, region, days_ahead=days)
    if not result.get("available"):
        raise HTTPException(status_code=404, detail=result.get("reason"))
    return result


@router.get("/demand-forecast-v2/model-info")
def demand_forecast_v2_model_info():
    """Training status + held-out test metrics for RF/XGBoost/LSTM, so the
    UI can show which models actually contributed to the ensemble."""
    from app.ml.demand.model_registry import get_registry
    return get_registry()


@router.post("/demand-forecast-v2/train/{model_name}")
def demand_forecast_v2_train(model_name: str, user: dict = Depends(require_roles("admin"))):
    """Admin-only retrain trigger. Runs synchronously -- fine for now, but
    move to a background worker/scheduler before relying on this in
    production, matching the "never train on request" principle used
    elsewhere in this project."""
    if model_name == "rf":
        from app.ml.demand.train_rf import train
    elif model_name == "xgboost":
        from app.ml.demand.train_xgboost import train
    elif model_name == "lstm":
        from app.ml.demand.train_lstm import train
    else:
        raise HTTPException(status_code=400, detail="model_name must be one of: rf, xgboost, lstm")
    try:
        report = train()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=str(e))
    from app.ml.demand.ensemble import compute_weights
    compute_weights()
    return report


# ---------- Demand Forecasting, Surge Detection & Auto-Procure ----------
@router.get("/demand-forecast/{drug_name}")
def demand_forecast(drug_name: str, db: Session = Depends(get_db)):
    history = rows_to_list(db.query(Sale).filter(Sale.drug_name == drug_name).order_by(Sale.date).all())
    return {"forecast": ml_engine.get_ai_forecast(drug_name, history), "surge": ml_engine.detect_surge(history)}


@router.get("/model-info")
def model_info():
    from app.ml.predict import get_training_report
    report = get_training_report()
    if not report:
        raise HTTPException(status_code=404, detail="No trained model found. Run `python -m app.ml.train_demand`.")
    return report


@router.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    inv = rows_to_list(db.query(VendorInventory).all())
    sales = rows_to_list(db.query(Sale).all())
    by_drug = {}
    for name in {i["drugName"] for i in inv}:
        history = [s for s in sales if s["drugName"] == name]
        batches = [i for i in inv if i["drugName"] == name]
        current_stock = sum(b["stock"] for b in batches)
        reorder_point = max(b["reorderPoint"] for b in batches)
        surge = ml_engine.detect_surge(history)
        avg_daily = (sum(h["qty"] for h in history) / max(len(history), 1) / 3 if history else 5) * (surge["ratio"] if surge["isSurge"] else 1)
        by_drug[name] = {
            "currentStock": current_stock, "reorderPoint": reorder_point,
            "forecast": ml_engine.get_ai_forecast(name, history), "surge": surge,
            "recommendedROP": ml_engine.dynamic_reorder_point(avg_daily),
        }
    return by_drug


@router.post("/auto-procure/run")
def auto_procure_run(db: Session = Depends(get_db)):
    settings = _settings(db)
    emergency = settings.emergency_mode
    created = []
    sales = rows_to_list(db.query(Sale).all())

    for item in db.query(VendorInventory).all():
        if item.stock <= item.reorder_point:
            history = [s for s in sales if s["drugName"] == item.drug_name]
            surge = ml_engine.detect_surge(history)
            multiplier = 4 if emergency else (min(surge["ratio"], 6) if surge["isSurge"] else 2)
            qty = math.ceil(max(item.reorder_point * multiplier - item.stock, item.reorder_point))
            reason = "Emergency Mode active" if emergency else (f"surge ratio {surge['ratio']}x detected" if surge["isSurge"] else "routine replenishment")

            run = ProductionRun(drug_name=item.drug_name, batch=item.batch, qty_produced=qty, stock_before=item.stock,
                                 stock_after=item.stock + qty, reason=reason, triggered_by="smart-contract",
                                 emergency_mode=emergency, created_at=_now())
            db.add(run)
            db.flush()
            created.append(row_to_dict(run))

            blockchain.add_block("SMART_CONTRACT_AUTO_PROCURE", "system:smart-contract", {
                "portal": "vendor", "productionRunId": run.id, "drugName": item.drug_name, "batch": item.batch,
                "qty": qty, "emergencyMode": emergency, "surge": surge,
                "reason": f"Stock {item.stock} <= reorder point {item.reorder_point}",
            })
            item.stock += qty

    if created:
        db.commit()
    message = (f"{len(created)} production run(s) recorded and added to stock by the smart contract"
               + (" under Emergency Mode." if emergency else ".")) if created else "All stock levels are healthy. No auto-procurement needed."
    return {"createdOrders": created, "message": message}


@router.get("/fefo-allocations")
def fefo_allocations(db: Session = Depends(get_db)):
    rows = db.query(StockRequest).all()
    out = []
    for r in rows:
        if r.batches_allocated:
            out.append({
                "requestId": r.id, "drugName": r.drug_name, "region": r.region, "qtyRequested": r.qty_requested,
                "qtyDispatched": r.qty_dispatched, "shortfall": max(0, (r.qty_requested or 0) - (r.qty_dispatched or 0)),
                "allocatedAt": r.approved_at, "batches": r.batches_allocated,
            })
    out.sort(key=lambda r: r["allocatedAt"] or "", reverse=True)
    return out


# ---------- Supplier Performance & Procurement ----------
@router.get("/supplier-performance")
def supplier_performance(drugName: str = None):
    try:
        return {"source": "6_supplier_vendor_performance.csv", "suppliers": supplier_ranking.rank_suppliers(drugName)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e) or "Supplier dataset unavailable.")


@router.get("/procurement")
def list_procurement(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(ProcurementSelection).all())
    rows.sort(key=lambda r: r["createdAt"], reverse=True)
    return rows


@router.post("/procurement", status_code=201)
def create_procurement(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("vendor", "admin"))):
    if not body.get("drugName") or not body.get("supplierName") or not body.get("qty"):
        raise HTTPException(status_code=400, detail="drugName, qty and supplierName are required.")
    selection = ProcurementSelection(
        drug_name=body["drugName"], qty=float(body["qty"]), region=body.get("region"),
        supplier_name=body["supplierName"], reason=body.get("reason") or "Selected by supplier performance score",
        created_at=_now(), created_by=user["email"],
    )
    db.add(selection)
    db.flush()
    blockchain.add_block("SUPPLIER_SELECTED", user["email"], row_to_dict(selection))
    db.commit()
    db.refresh(selection)
    return row_to_dict(selection)


@router.get("/production-runs")
def production_runs(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(ProductionRun).all())
    rows.sort(key=lambda r: r["createdAt"], reverse=True)
    return rows
