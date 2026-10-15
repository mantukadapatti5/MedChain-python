from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import require_roles
from app.models.sql_models import Client, ClientRequest, ClientInventory, ClientUsageLog, DistributorInventory
from app.serializers import row_to_dict, rows_to_list
from app.services import ml_engine, fefo, blockchain, batch_verify, availability, client_verification
from app.ml import predict as ml_predict

router = APIRouter(prefix="/api/client", tags=["client"], dependencies=[Depends(require_roles("client", "admin"))])


def _now():
    return datetime.now(timezone.utc).isoformat()


def _my_client(db: Session, user: dict):
    client = db.query(Client).filter(Client.user_id == user["id"]).first()
    if client and user.get("role") == "client":
        blocked = client_verification.login_block_message(
            client.verification_status, client.rejection_reason, client.license_verified)
        if blocked:
            raise HTTPException(status_code=403, detail=blocked)
    return client


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: dict = Depends(require_roles("client", "admin"))):
    client = _my_client(db, user)
    if not client:
        raise HTTPException(status_code=404, detail="No client profile linked to this account.")
    my_requests = rows_to_list(db.query(ClientRequest).filter(ClientRequest.client_id == client.id).all())
    my_inventory = rows_to_list(db.query(ClientInventory).filter(ClientInventory.client_id == client.id).all())
    near_expiry = [i for i in my_inventory if any(a["type"] in ("near-expiry", "expired") for a in ml_engine.detect_inventory_anomalies(i))]
    recent = sorted(my_requests, key=lambda r: r["createdAt"], reverse=True)[:5]

    return {
        "client": row_to_dict(client),
        "pendingRequests": len([r for r in my_requests if r["status"] == "pending"]),
        "inTransit": len([r for r in my_requests if r["status"] == "dispatched"]),
        "totalReceived": len([r for r in my_requests if r["status"] == "received"]),
        "onHandStockUnits": sum(i["stock"] for i in my_inventory),
        "nearExpiryCount": len(near_expiry),
        "recentRequests": recent,
    }


@router.get("/requests")
def list_requests(db: Session = Depends(get_db), user: dict = Depends(require_roles("client", "admin"))):
    client = _my_client(db, user)
    if not client:
        raise HTTPException(status_code=404, detail="No client profile linked to this account.")
    rows = rows_to_list(db.query(ClientRequest).filter(ClientRequest.client_id == client.id).all())
    rows.sort(key=lambda r: r["createdAt"], reverse=True)
    return rows


@router.post("/requests", status_code=201)
def create_request(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("client", "admin"))):
    client = _my_client(db, user)
    if not client:
        raise HTTPException(status_code=404, detail="No client profile linked to this account.")
    if not body.get("drugName") or not body.get("qty"):
        raise HTTPException(status_code=400, detail="drugName and qty are required.")
    try:
        qty = float(body["qty"])
    except (TypeError, ValueError):
        qty = 0
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be a number greater than zero.")

    # The drug must exist in the Distributor's inventory (for this client's region) before a request can be sent.
    drug_name, available_units, problem = availability.check_distributor_availability(
        db.query(DistributorInventory).all(), body["drugName"], client.region)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    priority = body.get("priority") if body.get("priority") in ("routine", "urgent", "critical") else "routine"

    request = ClientRequest(client_id=client.id, client_name=client.name, drug_name=drug_name,
                             qty_requested=qty, region=client.region, priority=priority,
                             status="pending", created_at=_now(), batches_allocated=[], gps_log=[], cold_chain_log=[])
    db.add(request)
    db.flush()
    blockchain.add_block("CLIENT_REQUEST_RAISED", user["email"], {"portal": "client", "requestId": request.id,
                          "clientName": client.name, "drugName": body["drugName"], "qty": request.qty_requested,
                          "region": client.region, "priority": priority})
    db.commit()
    db.refresh(request)
    result = row_to_dict(request)
    result["availableStock"] = available_units  # drug is in the Distributor inventory; shown in the success message
    return result


@router.post("/requests/{request_id}/receive")
def receive_request(request_id: int, body: dict = None, db: Session = Depends(get_db), user: dict = Depends(require_roles("client", "admin"))):
    body = body or {}
    client = _my_client(db, user)
    if not client:
        raise HTTPException(status_code=404, detail="No client profile linked to this account.")
    request = db.query(ClientRequest).filter(ClientRequest.id == request_id, ClientRequest.client_id == client.id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found for this client.")
    if request.status != "dispatched":
        raise HTTPException(status_code=400, detail=f"Request must be dispatched before it can be received. Current status: {request.status}.")

    qty_received = float(body["qtyReceived"]) if body.get("qtyReceived") is not None else request.qty_dispatched
    request.qty_received = qty_received
    request.status = "received"
    now = _now()
    request.received_at = now

    proportion = (qty_received / request.qty_dispatched) if request.qty_dispatched else 0
    for b in (request.batches_allocated or []):
        qty_for_batch = round(b["qty"] * proportion)
        if qty_for_batch <= 0:
            continue
        inv_item = db.query(ClientInventory).filter(ClientInventory.client_id == client.id, ClientInventory.batch == b["batch"]).first()
        if inv_item:
            inv_item.stock += qty_for_batch
        else:
            db.add(ClientInventory(
                client_id=client.id, client_name=client.name, drug_name=request.drug_name, batch=b["batch"],
                manufacturer=b.get("manufacturer") or "Sunrise Pharma", stock=qty_for_batch, reorder_point=10,
                unit_price=b.get("unitPrice"), expiry_date=b.get("expiryDate"), cold_chain=bool(b.get("coldChain")),
                provenance_checksum=ml_engine.compute_provenance_checksum(b["batch"], b.get("manufacturer") or "Sunrise Pharma"),
            ))

    mismatch = ml_engine.evaluate_quantity_mismatch(request.qty_dispatched, qty_received)
    if mismatch.get("mismatch"):
        batch = (request.batches_allocated or [{}])[0].get("batch", "N/A")
        from app.models.sql_models import Anomaly
        db.add(Anomaly(type="quantity-mismatch", drug_name=request.drug_name, batch=batch, severity=mismatch["severity"],
                        detected_at=now, status="open", source="client",
                        message=(f"Client request #{request.id} ({client.name}): {request.qty_dispatched} units dispatched "
                                 f"but only {qty_received} confirmed received ({mismatch['diffPercent']}% {mismatch['direction']}).")))
        blockchain.add_block("CLIENT_QUANTITY_MISMATCH_DETECTED", user["email"], {"portal": "client", "requestId": request.id,
                              "clientName": client.name, "drugName": request.drug_name, "qtyDispatched": request.qty_dispatched,
                              "qtyReceived": qty_received, "diffPercent": mismatch["diffPercent"], "direction": mismatch["direction"]})

    blockchain.add_block("CLIENT_ORDER_RECEIVED", user["email"], {"portal": "client", "requestId": request.id,
                          "clientName": client.name, "drugName": request.drug_name, "qtyReceived": qty_received})
    db.commit()
    db.refresh(request)
    return {"request": row_to_dict(request), "mismatch": mismatch}


@router.get("/inventory")
def list_inventory(db: Session = Depends(get_db), user: dict = Depends(require_roles("client", "admin"))):
    client = _my_client(db, user)
    if not client:
        raise HTTPException(status_code=404, detail="No client profile linked to this account.")
    rows = rows_to_list(db.query(ClientInventory).filter(ClientInventory.client_id == client.id).all())
    for r in rows:
        r["flags"] = ml_engine.detect_inventory_anomalies(r)
    return rows


@router.post("/usage", status_code=201)
def record_usage(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("client", "admin"))):
    client = _my_client(db, user)
    if not client:
        raise HTTPException(status_code=404, detail="No client profile linked to this account.")
    if not body.get("drugName") or not body.get("qty"):
        raise HTTPException(status_code=400, detail="drugName and qty are required.")

    pool = db.query(ClientInventory).filter(ClientInventory.client_id == client.id).all()
    result = fefo.allocate_fefo(pool, body["drugName"], float(body["qty"]))
    if result["totalAllocated"] == 0:
        raise HTTPException(status_code=400, detail=f"No on-hand stock of {body['drugName']} to record usage against.")
    if result["shortfall"] > 0:
        raise HTTPException(status_code=400, detail=f"Only {result['totalAllocated']} of {body['qty']} units on hand; usage not recorded.")

    usage = ClientUsageLog(client_id=client.id, client_name=client.name, drug_name=body["drugName"],
                            qty=result["totalAllocated"], note=body.get("note", ""),
                            batches_used=[{"batch": a["batch"], "qty": a["qty"]} for a in result["allocated"]],
                            recorded_at=_now())
    db.add(usage)
    db.flush()
    blockchain.add_block("CLIENT_USAGE_RECORDED", user["email"], {"portal": "client", "clientName": client.name,
                          "drugName": body["drugName"], "qty": result["totalAllocated"], "batchesUsed": usage.batches_used})
    db.commit()
    db.refresh(usage)
    return row_to_dict(usage)


@router.get("/provenance/{batch}")
def provenance(batch: str, db: Session = Depends(get_db)):
    return batch_verify.verify_batch_everywhere(db, batch)


@router.get("/demand-forecast")
def demand_forecast(db: Session = Depends(get_db), user: dict = Depends(require_roles("client", "admin"))):
    client = _my_client(db, user)
    if not client:
        raise HTTPException(status_code=404, detail="No client profile linked to this account.")
    my_requests = rows_to_list(db.query(ClientRequest).filter(ClientRequest.client_id == client.id).all())
    my_drugs = sorted({r["drugName"] for r in my_requests})
    if not my_drugs:
        return {"client": client.name, "forecasts": [], "message": "No request history yet to forecast from. Place a few requests first."}

    inventory = rows_to_list(db.query(ClientInventory).filter(ClientInventory.client_id == client.id).all())
    forecasts = []
    for drug_name in my_drugs:
        history = sorted(
            [{"date": r["createdAt"], "qty": float(r["qtyRequested"] or 0)} for r in my_requests if r["drugName"] == drug_name and r["status"] != "rejected"],
            key=lambda r: r["date"],
        )
        forecast = ml_predict.predict_next_period(drug_name, history, 7)
        current_stock = sum(i["stock"] for i in inventory if i["drugName"] == drug_name)
        forecasts.append({
            "drugName": drug_name, "currentStock": current_stock, "requestsOnRecord": len(history),
            "forecastNext7Days": forecast["forecastNextPeriod"] if forecast.get("available") else None,
            "method": forecast.get("method") if forecast.get("available") else "Not enough history yet (need at least 3 data points)",
            "available": forecast.get("available", False),
        })
    return {"client": client.name, "forecasts": forecasts}
