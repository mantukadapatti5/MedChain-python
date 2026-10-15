import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import require_roles
from app.models.sql_models import (
    StockRequest, ClientRequest, DistributorInventory, Sale, Anomaly, Client, User,
    SupplierPerformance, Region, Settings, RedistributionTransfer, VendorInventory,
)
from app.serializers import row_to_dict, rows_to_list
from app.security import hash_password
from app.services import ml_engine, fefo, inventory_guard, blockchain, geo, telemetry, regional_forecast, notifications, availability, client_verification
from app.ml import predict as ml_predict
from app.ml import predict_shortage

router = APIRouter(prefix="/api/distributor", tags=["distributor"], dependencies=[Depends(require_roles("distributor", "admin"))])

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
    sales = db.query(Sale).all()
    total_sales_amount = sum(s.amount or 0 for s in sales)
    low_stock = [i for i in db.query(DistributorInventory).all() if i.stock <= i.reorder_point]
    active_queue = rows_to_list(db.query(StockRequest).filter(StockRequest.status.notin_(["received", "rejected"])).all())

    return {
        "pendingRequests": db.query(StockRequest).filter(StockRequest.status == "pending").count(),
        "inTransit": db.query(StockRequest).filter(StockRequest.status == "dispatched").count(),
        "totalSalesAmount": round(total_sales_amount, 2),
        "totalSalesCount": len(sales),
        "lowStockCount": len(low_stock),
        "activeQueue": active_queue,
        "supplierPerformance": rows_to_list(db.query(SupplierPerformance).all()),
        "regions": rows_to_list(db.query(Region).all()),
        "emergencyMode": _settings(db).emergency_mode,
    }


# ---------- Stock Requests (Distributor -> Vendor) ----------
@router.get("/stock-requests")
def list_stock_requests(db: Session = Depends(get_db)):
    return rows_to_list(db.query(StockRequest).all())


@router.post("/stock-requests", status_code=201)
def create_stock_request(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    if not body.get("drugName") or not body.get("qty") or not body.get("region"):
        raise HTTPException(status_code=400, detail="drugName, qty and region are required to raise a stock request.")
    try:
        qty = float(body["qty"])
    except (TypeError, ValueError):
        qty = 0
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be a number greater than zero.")

    # The drug must exist in the Vendor's inventory list before a request can be sent.
    drug_name, available_units, problem = availability.check_vendor_availability(
        db.query(VendorInventory).all(), body["drugName"])
    if problem:
        raise HTTPException(status_code=400, detail=problem)

    priority = body.get("priority") if body.get("priority") in ("routine", "urgent", "critical") else "routine"
    request = StockRequest(drug_name=drug_name, qty_requested=qty, region=body["region"],
                            priority=priority, status="pending", requested_by="distributor", created_at=_now(),
                            batches_allocated=[], gps_log=[], cold_chain_log=[])
    db.add(request)
    db.flush()
    blockchain.add_block("STOCK_REQUEST_RAISED", user["email"], {"portal": "distributor", "requestId": request.id,
                          "drugName": request.drug_name, "qty": request.qty_requested, "region": request.region, "priority": priority})
    db.commit()
    db.refresh(request)
    result = row_to_dict(request)
    result["availableStock"] = available_units  # drug is in the Vendor inventory; shown in the success message
    return result


@router.post("/stock-requests/{request_id}/gps-ping")
def gps_ping(request_id: int, body: dict = None, db: Session = Depends(get_db)):
    body = body or {}
    request = db.query(StockRequest).filter(StockRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Stock request not found.")
    if request.status != "dispatched":
        raise HTTPException(status_code=400, detail="GPS pings can only be added to in-transit shipments.")
    lat = float(body["lat"]) if body.get("lat") is not None else 12.9716 + random.random() * 0.5
    lng = float(body["lng"]) if body.get("lng") is not None else 77.5946 + random.random() * 0.5
    now = _now()
    label = body.get("label") or "In Transit"
    log = list(request.gps_log or [])
    log.append({"lat": lat, "lng": lng, "timestamp": now, "label": label})
    request.gps_log = log
    telemetry.record_gps_ping(request.id, "Vendor \u2192 Distributor", lat, lng, now, label)
    db.commit()
    db.refresh(request)
    return row_to_dict(request)


@router.post("/stock-requests/{request_id}/cold-chain-reading")
def cold_chain_reading(request_id: int, body: dict = None, db: Session = Depends(get_db)):
    body = body or {}
    request = db.query(StockRequest).filter(StockRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Stock request not found.")
    temp = float(body["temp"]) if body.get("temp") is not None else round(4 + random.random() * 6, 1)
    humidity = float(body["humidity"]) if body.get("humidity") is not None else round(35 + random.random() * 30)
    result = ml_engine.check_cold_chain(temp, humidity)
    now = _now()
    reading = {"temp": temp, "humidity": humidity, "timestamp": now, "alert": result["breached"]}
    log = list(request.cold_chain_log or [])
    log.append(reading)
    request.cold_chain_log = log
    telemetry.record_cold_chain_reading("distributor", (request.batches_allocated or [{}])[0].get("batch", "N/A"), temp, humidity, now, result["breached"])

    if result["breached"]:
        batch = (request.batches_allocated or [{}])[0].get("batch", "N/A")
        anomaly = Anomaly(type="cold-chain-breach", drug_name=request.drug_name, batch=batch, severity="high",
                           detected_at=now, status="open", source="distributor", message="; ".join(result["alerts"]))
        db.add(anomaly)
        blockchain.add_block("COLD_CHAIN_ALERT", "system:iot-sensor", {"portal": "distributor", "requestId": request.id,
                              "drugName": request.drug_name, **reading})
        notifications.create_notification(db, role="admin", type="COLD_CHAIN", severity="high",
            title=f"Cold-chain breach: {request.drug_name}", message="; ".join(result["alerts"]),
            related_drug=request.drug_name, related_batch=batch, action_path="/admin/anomalies",
            event_key=f"cold-chain:{batch}:{now[:16]}")

    db.commit()
    return {"request": row_to_dict(request), "breached": result["breached"], "alerts": result["alerts"]}


@router.post("/stock-requests/{request_id}/receive")
def receive_stock_request(request_id: int, body: dict = None, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    body = body or {}
    request = db.query(StockRequest).filter(StockRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Stock request not found.")
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
        inv_item = db.query(DistributorInventory).filter(DistributorInventory.batch == b["batch"], DistributorInventory.region == request.region).first()
        if inv_item:
            inv_item.stock += qty_for_batch
        else:
            db.add(DistributorInventory(
                drug_name=request.drug_name, category="General", batch=b["batch"],
                manufacturer=b.get("manufacturer") or "Sunrise Pharma", region=request.region, stock=qty_for_batch,
                reorder_point=50, unit_price=b.get("unitPrice"), expiry_date=b.get("expiryDate"),
                cold_chain=bool(b.get("coldChain")),
                provenance_checksum=ml_engine.compute_provenance_checksum(b["batch"], b.get("manufacturer") or "Sunrise Pharma"),
            ))

    mismatch = ml_engine.evaluate_quantity_mismatch(request.qty_dispatched, qty_received)
    if mismatch.get("mismatch"):
        batch = (request.batches_allocated or [{}])[0].get("batch", "N/A")
        anomaly = Anomaly(type="quantity-mismatch", drug_name=request.drug_name, batch=batch, severity=mismatch["severity"],
                           detected_at=now, status="open", source="distributor",
                           message=(f"Stock request #{request.id}: {request.qty_dispatched} units dispatched but only "
                                    f"{qty_received} confirmed received ({mismatch['diffPercent']}% {mismatch['direction']})."))
        db.add(anomaly)
        blockchain.add_block("QUANTITY_MISMATCH_DETECTED", user["email"], {"portal": "distributor", "requestId": request.id,
                              "drugName": request.drug_name, "qtyDispatched": request.qty_dispatched, "qtyReceived": qty_received,
                              "diffPercent": mismatch["diffPercent"], "direction": mismatch["direction"]})

    blockchain.add_block("ORDER_RECEIVED", user["email"], {"portal": "distributor", "requestId": request.id,
                          "drugName": request.drug_name, "qtyReceived": qty_received})
    if mismatch.get("mismatch"):
        notifications.create_notification(db, role="vendor", type="SHIPMENT", severity="high",
            title=f"Shipment received: {request.drug_name}",
            message=f"Request #{request.id} was received with a quantity mismatch. Review the shipment.",
            related_drug=request.drug_name, related_request_id=request.id, action_path="/vendor/requests",
            event_key=f"receive:{request.id}:{now}")
    else:
        notifications.create_notification(db, role="vendor", type="SHIPMENT", severity="info",
            title=f"Shipment received: {request.drug_name}",
            message=f"Request #{request.id} was received successfully with {qty_received} unit(s).",
            related_drug=request.drug_name, related_request_id=request.id, action_path="/vendor/requests",
            event_key=f"receive:{request.id}:{now}")

    db.commit()
    db.refresh(request)
    return {"request": row_to_dict(request), "mismatch": mismatch}


# ---------- Inventory ----------
@router.get("/inventory")
def list_inventory(db: Session = Depends(get_db)):
    return rows_to_list(db.query(DistributorInventory).all())


@router.post("/inventory", status_code=201)
def create_inventory(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    required = ["drugName", "batch", "stock", "expiryDate", "region"]
    if any(body.get(k) is None for k in required):
        raise HTTPException(status_code=400, detail="drugName, batch, region, stock and expiryDate are required.")
    item = DistributorInventory(
        drug_name=body["drugName"], category=body.get("category") or "General", batch=body["batch"],
        manufacturer=body.get("manufacturer") or "Sunrise Pharma", region=body["region"], stock=float(body["stock"]),
        reorder_point=float(body.get("reorderPoint") or 50), unit_price=float(body.get("unitPrice") or 0),
        expiry_date=body["expiryDate"], cold_chain=bool(body.get("coldChain")),
        provenance_checksum=ml_engine.compute_provenance_checksum(body["batch"], body.get("manufacturer")),
    )
    db.add(item)
    db.flush()
    blockchain.add_block("INVENTORY_UPDATE", user["email"], {"portal": "distributor", "action": "batch-created",
                          "drugName": item.drug_name, "batch": item.batch, "region": item.region, "stock": item.stock})
    db.commit()
    db.refresh(item)
    return row_to_dict(item)


@router.put("/inventory/{item_id}")
def update_inventory(item_id: int, body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    item = db.query(DistributorInventory).filter(DistributorInventory.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    before = item.stock
    error = inventory_guard.apply_safe_inventory_update(item, body)
    if error:
        raise HTTPException(status_code=400, detail=error)
    blockchain.add_block("INVENTORY_UPDATE", user["email"], {"portal": "distributor", "action": "stock-adjusted",
                          "drugName": item.drug_name, "batch": item.batch, "stockBefore": before, "stockAfter": item.stock})
    db.commit()
    db.refresh(item)
    return row_to_dict(item)


# ---------- Sales (FEFO-aware) ----------
@router.get("/sales")
def list_sales(db: Session = Depends(get_db)):
    return rows_to_list(db.query(Sale).all())


@router.post("/sales", status_code=201)
def create_sale(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    if not body.get("drugName") or not body.get("qty") or not body.get("buyer"):
        raise HTTPException(status_code=400, detail="drugName, qty and buyer are required.")
    region = body.get("region")
    pool_query = db.query(DistributorInventory)
    if region:
        pool_query = pool_query.filter(DistributorInventory.region == region)
    pool = pool_query.all()
    result = fefo.allocate_fefo(pool, body["drugName"], float(body["qty"]))

    if result["totalAllocated"] == 0:
        raise HTTPException(status_code=400, detail=f"No available stock for {body['drugName']}{f' in {region}' if region else ''}.")
    if result["shortfall"] > 0:
        raise HTTPException(status_code=400, detail=f"Insufficient stock. Only {result['totalAllocated']} of {body['qty']} requested units available; sale not recorded.")

    avg_unit_price = float(body["unitPrice"]) if body.get("unitPrice") else sum(a["unitPrice"] * a["qty"] for a in result["allocated"]) / result["totalAllocated"]
    sale = Sale(drug_name=body["drugName"], batch=", ".join(a["batch"] for a in result["allocated"]),
                qty=result["totalAllocated"], unit_price=round(avg_unit_price, 2),
                amount=round(avg_unit_price * result["totalAllocated"], 2), buyer=body["buyer"], region=region, date=_now())
    db.add(sale)
    db.flush()
    blockchain.add_block("SALE_RECORDED", user["email"], {"portal": "distributor", "saleId": sale.id, "drugName": body["drugName"],
                          "qty": result["totalAllocated"], "buyer": body["buyer"],
                          "batchesUsed": [{"batch": a["batch"], "qty": a["qty"]} for a in result["allocated"]]})
    db.commit()
    db.refresh(sale)
    return row_to_dict(sale)


# ---------- Supplier Performance ----------
@router.get("/supplier-performance")
def supplier_performance(db: Session = Depends(get_db)):
    return rows_to_list(db.query(SupplierPerformance).all())


# ---------- Hospital / Regional Demand Forecast ----------
@router.get("/hospital-forecast")
def hospital_forecast(drugName: str = None, region: str = None, clientId: int = None, days: int = 7,
                       db: Session = Depends(get_db)):
    try:
        clients = rows_to_list(db.query(Client).all())
        # Attach on-hand stock per client/drug for the days-of-supply calc.
        from app.models.sql_models import ClientInventory
        inv_rows = rows_to_list(db.query(ClientInventory).all())
        for c in clients:
            stock_by_drug = {}
            for i in inv_rows:
                if i["clientId"] == c["id"]:
                    stock_by_drug[i["drugName"]] = stock_by_drug.get(i["drugName"], 0) + i["stock"]
            c["stockByDrug"] = stock_by_drug

        drug_universe = [r["drugName"] for r in rows_to_list(db.query(DistributorInventory).all())]
        from app.models.sql_models import ClientUsageLog
        usage_log = rows_to_list(db.query(ClientUsageLog).all())
        client_requests = rows_to_list(db.query(ClientRequest).all())
        sales = rows_to_list(db.query(Sale).all())

        report = regional_forecast.build_regional_forecast(
            clients, drug_universe, usage_log, client_requests, sales,
            drug_name=drugName, region=region, client_id=clientId, days=days,
        )
        report["regionalSummary"] = regional_forecast.summarize_regions(report)
        return report
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e) or "Unable to build regional forecast.")


# ---------- Automatic Stock Redistribution ----------
@router.get("/redistribution/recommendations")
def redistribution_recommendations(db: Session = Depends(get_db)):
    inventory = rows_to_list(db.query(DistributorInventory).all())
    grouped = {}
    for item in inventory:
        grouped.setdefault(item["drugName"], {})
        region = item["region"] or "Unassigned"
        grouped[item["drugName"]][region] = grouped[item["drugName"]].get(region, 0) + (item["stock"] or 0)

    recommendations = []
    for drug_name, regions in grouped.items():
        total = sum(regions.values())
        average = total / len(regions) if regions else 0
        source = max(regions.items(), key=lambda kv: kv[1])
        target = min(regions.items(), key=lambda kv: kv[1])
        if source[0] == target[0]:
            continue
        if source[1] <= average * 1.25 or target[1] >= average * 0.75:
            continue
        suggested_qty = max(1, int((source[1] - average) * 0.5))
        recommendations.append({
            "id": f"{drug_name}:{source[0]}:{target[0]}", "drugName": drug_name, "fromRegion": source[0],
            "toRegion": target[0], "fromStock": source[1], "toStock": target[1], "suggestedQty": suggested_qty,
            "reason": f"{source[0]} has surplus stock while {target[0]} has the lowest regional stock.",
        })
    return recommendations


@router.post("/redistribution/execute", status_code=201)
def redistribution_execute(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    drug_name, from_region, to_region = body.get("drugName"), body.get("fromRegion"), body.get("toRegion")
    quantity = float(body.get("qty") or 0)
    if not drug_name or not from_region or not to_region or quantity <= 0 or from_region == to_region:
        raise HTTPException(status_code=400, detail="drugName, fromRegion, toRegion and a positive qty are required.")

    remaining = quantity
    sources = sorted(
        [i for i in db.query(DistributorInventory).filter(DistributorInventory.drug_name == drug_name,
         DistributorInventory.region == from_region, DistributorInventory.stock > 0).all()],
        key=lambda i: i.expiry_date or "",
    )
    target = db.query(DistributorInventory).filter(DistributorInventory.drug_name == drug_name, DistributorInventory.region == to_region).first()
    if not target:
        raise HTTPException(status_code=404, detail="Destination inventory record not found for this medicine and region.")

    moved_batches = []
    for source in sources:
        if remaining <= 0:
            break
        moved = min(source.stock, remaining)
        source.stock -= moved
        remaining -= moved
        moved_batches.append({"batch": source.batch, "qty": moved, "expiryDate": source.expiry_date})
    if remaining > 0:
        raise HTTPException(status_code=400, detail=f"Only {quantity - remaining} units are available in {from_region}; transfer not completed.")

    target.stock += quantity
    transfer = RedistributionTransfer(drug_name=drug_name, from_region=from_region, to_region=to_region, qty=quantity,
                                       moved_batches=moved_batches, created_at=_now(), created_by=user["email"])
    db.add(transfer)
    db.flush()
    blockchain.add_block("STOCK_REDISTRIBUTED", user["email"], row_to_dict(transfer))
    db.commit()
    db.refresh(transfer)
    return row_to_dict(transfer)


@router.get("/stock-requests/{request_id}/tracking")
def stock_request_tracking(request_id: int, db: Session = Depends(get_db)):
    request = db.query(StockRequest).filter(StockRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Stock request not found.")
    return geo.calculate_shipment_tracking(row_to_dict(request))


# ---------- GPS + ETA ----------
@router.get("/gps-eta")
def gps_eta(db: Session = Depends(get_db)):
    in_transit = [{**r, "direction": "Vendor \u2192 Distributor"} for r in rows_to_list(db.query(StockRequest).filter(StockRequest.status == "dispatched").all())]
    in_transit += [{**r, "direction": "Distributor \u2192 Client"} for r in rows_to_list(db.query(ClientRequest).filter(ClientRequest.status == "dispatched").all())]
    shipments = []
    for r in in_transit:
        tracking = geo.calculate_shipment_tracking(r)
        shipments.append({"requestId": r["id"], "direction": r["direction"], "drugName": r["drugName"], "region": r.get("region"), **tracking})
    shipments.sort(key=lambda s: s["etaMinutes"] if s["etaMinutes"] is not None else float("inf"))
    return shipments


# ---------- Shortage Risk ----------
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
            "forecastDemand": ml.get("forecastDemand"), "modelError": ml.get("reason") if ml.get("available") is False else None,
        })
    rows.sort(key=lambda r: (-(r["mlShortageProbability"] or 0), r["daysOfSupply"]))
    return rows


# ---------- Clients Directory ----------
@router.get("/clients")
def list_clients(db: Session = Depends(get_db)):
    return rows_to_list(db.query(Client).all())


@router.post("/clients", status_code=201)
def onboard_client(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    required = ["name", "type", "region", "email", "password"]
    if any(not body.get(k) for k in required):
        raise HTTPException(status_code=400, detail="name, type, region, email and password are required to onboard a client.")
    if db.query(User).filter(User.email.ilike(body["email"])).first():
        raise HTTPException(status_code=400, detail="An account with this email already exists.")

    # A client added by a Distributor must be verified by the Admin before it can sign in.
    # (A client added directly by an Admin is trusted and approved immediately.)
    auto_approved = user.get("role") == "admin"
    now = _now()
    new_user = User(name=body["name"], email=body["email"], password_hash=hash_password(body["password"]), role="client",
                    license_verified=auto_approved)
    db.add(new_user)
    db.flush()

    client = Client(user_id=new_user.id, name=body["name"], type=body["type"], region=body["region"],
                     contact_person=body.get("contactPerson", ""), phone=body.get("phone", ""), email=body["email"],
                     license_verified=auto_approved, onboarded_at=now,
                     verification_status="approved" if auto_approved else "pending",
                     onboarded_by=user["email"],
                     verified_by=user["email"] if auto_approved else None,
                     verified_at=now if auto_approved else None)
    db.add(client)
    db.flush()
    blockchain.add_block("CLIENT_ONBOARDED", user["email"], {"portal": "distributor", "clientName": body["name"],
                          "type": body["type"], "region": body["region"],
                          "verificationStatus": client.verification_status})
    if not auto_approved:
        notifications.create_notification(
            db, role="admin", type="SYSTEM", severity="medium",
            title="New client awaiting verification",
            message=f'{body["name"]} ({body["type"]}, {body["region"]}) was added by {user["email"]} and needs your verification.',
            action_path="/admin/client-verification", event_key=f"client-verification-{client.id}")
    db.commit()
    db.refresh(client)
    return row_to_dict(client)


# ---------- Client Requests (Client -> Distributor, last-mile leg) ----------
@router.get("/client-requests")
def list_client_requests(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(ClientRequest).all())
    rows.sort(key=lambda r: (-(PRIORITY_WEIGHT.get(r["priority"], 0)), r["createdAt"]))
    return rows


@router.post("/client-requests/{request_id}/approve")
def approve_client_request(request_id: int, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    request = db.query(ClientRequest).filter(ClientRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Client request not found.")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail=f"Only pending requests can be approved. Current status: {request.status}.")

    pool = db.query(DistributorInventory).filter(DistributorInventory.region == request.region).all()
    result = fefo.allocate_fefo(pool, request.drug_name, request.qty_requested)
    if result["totalAllocated"] == 0:
        raise HTTPException(status_code=400, detail=f"No available stock for {request.drug_name} in {request.region}.")

    now = _now()
    request.status = "dispatched"
    request.approved_at = now
    request.dispatched_at = now
    request.qty_dispatched = result["totalAllocated"]
    request.batches_allocated = result["allocated"]
    gps_log = list(request.gps_log or [])
    gps_log.append({"lat": 12.9716, "lng": 77.5946, "timestamp": now, "label": "Departed Distributor Hub"})
    request.gps_log = gps_log
    telemetry.record_gps_ping(request.id, "Distributor \u2192 Client", 12.9716, 77.5946, now, "Departed Distributor Hub")

    if any(a["coldChain"] for a in result["allocated"]):
        cc = list(request.cold_chain_log or [])
        cc.append({"temp": 4.9, "humidity": 41, "timestamp": now, "alert": False})
        request.cold_chain_log = cc

    blockchain.add_block("CLIENT_REQUEST_APPROVED", user["email"], {
        "portal": "distributor", "requestId": request.id, "clientName": request.client_name, "drugName": request.drug_name,
        "region": request.region, "qtyRequested": request.qty_requested, "qtyDispatched": result["totalAllocated"],
        "shortfall": result["shortfall"],
        "batchesAllocated": [{"batch": a["batch"], "qty": a["qty"], "expiryDate": a["expiryDate"]} for a in result["allocated"]],
    })
    blockchain.add_block("CLIENT_ORDER_DISPATCHED", user["email"], {"portal": "distributor", "requestId": request.id,
                          "clientName": request.client_name, "drugName": request.drug_name, "qty": result["totalAllocated"]})

    db.commit()
    db.refresh(request)
    message = (f"Partially fulfilled: {result['totalAllocated']}/{request.qty_requested} units (insufficient regional stock)."
               if result["shortfall"] > 0 else "Request approved and dispatched via FEFO allocation.")
    return {"request": row_to_dict(request), "shortfall": result["shortfall"], "message": message}


@router.post("/client-requests/{request_id}/reject")
def reject_client_request(request_id: int, body: dict = None, db: Session = Depends(get_db), user: dict = Depends(require_roles("distributor", "admin"))):
    body = body or {}
    request = db.query(ClientRequest).filter(ClientRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Client request not found.")
    if request.status != "pending":
        raise HTTPException(status_code=400, detail=f"Only pending requests can be rejected. Current status: {request.status}.")
    request.status = "rejected"
    request.rejection_reason = body.get("reason", "Not specified")
    blockchain.add_block("CLIENT_REQUEST_REJECTED", user["email"], {"portal": "distributor", "requestId": request.id,
                          "clientName": request.client_name, "reason": request.rejection_reason})
    db.commit()
    db.refresh(request)
    return row_to_dict(request)


@router.post("/client-requests/{request_id}/gps-ping")
def client_request_gps_ping(request_id: int, body: dict = None, db: Session = Depends(get_db)):
    body = body or {}
    request = db.query(ClientRequest).filter(ClientRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Client request not found.")
    if request.status != "dispatched":
        raise HTTPException(status_code=400, detail="GPS pings can only be added to in-transit shipments.")
    lat = float(body["lat"]) if body.get("lat") is not None else 12.9716 + random.random() * 0.5
    lng = float(body["lng"]) if body.get("lng") is not None else 77.5946 + random.random() * 0.5
    now = _now()
    log = list(request.gps_log or [])
    log.append({"lat": lat, "lng": lng, "timestamp": now, "label": body.get("label") or "In Transit to Client"})
    request.gps_log = log
    telemetry.record_gps_ping(request.id, "Distributor \u2192 Client", lat, lng, now, body.get("label") or "In Transit to Client")
    db.commit()
    db.refresh(request)
    return row_to_dict(request)


@router.post("/client-requests/{request_id}/cold-chain-reading")
def client_request_cold_chain_reading(request_id: int, body: dict = None, db: Session = Depends(get_db)):
    body = body or {}
    request = db.query(ClientRequest).filter(ClientRequest.id == request_id).first()
    if not request:
        raise HTTPException(status_code=404, detail="Client request not found.")
    temp = float(body["temp"]) if body.get("temp") is not None else round(4 + random.random() * 6, 1)
    humidity = float(body["humidity"]) if body.get("humidity") is not None else round(35 + random.random() * 30)
    result = ml_engine.check_cold_chain(temp, humidity)
    now = _now()
    reading = {"temp": temp, "humidity": humidity, "timestamp": now, "alert": result["breached"]}
    log = list(request.cold_chain_log or [])
    log.append(reading)
    request.cold_chain_log = log
    batch = (request.batches_allocated or [{}])[0].get("batch", "N/A")
    telemetry.record_cold_chain_reading("distributor", batch, temp, humidity, now, result["breached"])

    if result["breached"]:
        anomaly = Anomaly(type="cold-chain-breach", drug_name=request.drug_name, batch=batch, severity="high",
                           detected_at=now, status="open", source="distributor", message="; ".join(result["alerts"]))
        db.add(anomaly)
        blockchain.add_block("COLD_CHAIN_ALERT", "system:iot-sensor", {"portal": "distributor", "requestId": request.id,
                              "clientName": request.client_name, "drugName": request.drug_name, **reading})

    db.commit()
    return {"request": row_to_dict(request), "breached": result["breached"], "alerts": result["alerts"]}
