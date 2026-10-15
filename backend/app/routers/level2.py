from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import require_roles
from app.models.sql_models import DistributorInventory, Sale, ScenarioRun, RedistributionTransfer, ProcurementSelection
from app.serializers import row_to_dict, rows_to_list
from app.services import ml_engine, blockchain, batch_verify
from app.ml import predict as ml_predict
from app.ml import predict_shortage

router = APIRouter(prefix="/api/level2", tags=["level2"], dependencies=[Depends(require_roles("admin"))])


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.get("/scenarios")
def list_scenarios(db: Session = Depends(get_db)):
    rows = rows_to_list(db.query(ScenarioRun).all())
    rows.sort(key=lambda r: r["createdAt"], reverse=True)
    return rows[:50]


@router.post("/scenarios", status_code=201)
def run_scenario(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    drug_name, batch = body.get("drugName"), body.get("batch")
    increase = float(body.get("demandIncreasePercent") or 0)
    safe_days = max(1, min(int(body.get("daysAhead") or 7), 30))
    if not drug_name or not (-90 <= increase <= 500):
        raise HTTPException(status_code=400, detail="drugName is required and demandIncreasePercent must be between -90 and 500.")

    q = db.query(DistributorInventory).filter(DistributorInventory.drug_name == drug_name)
    if batch:
        q = q.filter(DistributorInventory.batch == batch)
    candidates = sorted(q.all(), key=lambda i: i.stock, reverse=True)
    item = candidates[0] if candidates else None
    if not item:
        raise HTTPException(status_code=404, detail="No matching distributor inventory found for this drug/batch.")

    history = sorted(rows_to_list(db.query(Sale).filter(Sale.drug_name == drug_name).all()), key=lambda s: s["date"])
    forecast = ml_predict.predict_next_period(drug_name, history, safe_days)
    if not forecast.get("available"):
        raise HTTPException(status_code=400, detail=forecast.get("reason") or "Demand model is not available. Train the model first.")

    multiplier = 1 + increase / 100
    baseline_demand = float(forecast.get("forecastNextPeriod") or 0)
    scenario_demand = max(0, round(baseline_demand * multiplier))
    qty_history = [s["qty"] for s in history]
    avg_daily = (sum(qty_history) / 21) if qty_history else max(1, baseline_demand / safe_days)
    baseline_risk = ml_engine.shortage_risk(item.stock or 0, max(avg_daily, baseline_demand / safe_days))
    try:
        classifier = predict_shortage.predict(item.stock or 0, qty_history, scenario_demand, item.lead_time_days or 3)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Shortage model unavailable: {e}")

    result = ScenarioRun(
        source="live", drug_name=drug_name, batch=item.batch, region=item.region, current_stock=item.stock or 0,
        demand_increase_percent=increase, days_ahead=safe_days, baseline_forecast=baseline_demand,
        scenario_forecast=scenario_demand, additional_demand_units=max(0, scenario_demand - baseline_demand),
        baseline_risk=baseline_risk["level"], baseline_days_of_supply=baseline_risk["daysOfSupply"],
        scenario_shortage_probability=classifier.get("shortageProbability"), scenario_risk_level=classifier.get("riskLevel"),
        model="Random Forest demand forecast + Random Forest shortage classifier", created_at=_now(), created_by=user["email"],
    )
    db.add(result)
    db.flush()
    blockchain.add_block("WHAT_IF_SCENARIO_RUN", user["email"], row_to_dict(result))
    db.commit()
    db.refresh(result)
    return row_to_dict(result)


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
        if source[0] == target[0] or source[1] <= average * 1.25 or target[1] >= average * 0.75:
            continue
        recommendations.append({
            "id": f"{drug_name}:{source[0]}:{target[0]}", "drugName": drug_name, "fromRegion": source[0],
            "toRegion": target[0], "fromStock": source[1], "toStock": target[1],
            "suggestedQty": max(1, int((source[1] - average) * 0.5)),
            "reason": f"{source[0]} has surplus stock while {target[0]} has the lowest regional stock.",
        })
    return recommendations


@router.post("/redistribution/execute", status_code=201)
def redistribution_execute(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    drug_name, from_region, to_region = body.get("drugName"), body.get("fromRegion"), body.get("toRegion")
    quantity = float(body.get("qty") or 0)
    if not drug_name or not from_region or not to_region or quantity <= 0 or from_region == to_region:
        raise HTTPException(status_code=400, detail="drugName, fromRegion, toRegion and a positive qty are required.")

    remaining = quantity
    sources = sorted(db.query(DistributorInventory).filter(DistributorInventory.drug_name == drug_name,
              DistributorInventory.region == from_region, DistributorInventory.stock > 0).all(), key=lambda i: i.expiry_date or "")
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


@router.get("/suppliers")
def suppliers(db: Session = Depends(get_db)):
    from app.models.sql_models import SupplierPerformance
    performance = rows_to_list(db.query(SupplierPerformance).all())
    names = sorted({p.get("vendorName") for p in performance if p.get("vendorName")})
    results = []
    for i, name in enumerate(names):
        p = next((x for x in performance if x.get("vendorName") == name), {})
        quality = float(p.get("qualityScore", 90))
        on_time = float(p.get("onTimeDeliveryRate", 90))
        delivery = 3.0
        price = 100 + i * 3
        rejection = 2.0
        price_score = max(0, min(100, 100 - max(0, price - 90) * 2))
        delivery_score = max(0, min(100, 100 - max(0, delivery - 1) * 12))
        score = round(quality * 0.35 + on_time * 0.30 + delivery_score * 0.20 + price_score * 0.10 + (100 - rejection) * 0.05, 1)
        results.append({"id": name, "name": name, "price": price, "qualityScore": quality, "onTimeRate": on_time,
                         "averageDeliveryDays": delivery, "rejectionRate": rejection, "overallScore": score})
    results.sort(key=lambda r: r["overallScore"], reverse=True)
    return results


@router.post("/procurement-selection", status_code=201)
def procurement_selection(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    if not body.get("drugName") or not body.get("supplierName") or not body.get("qty"):
        raise HTTPException(status_code=400, detail="drugName, qty and supplierName are required.")
    selection = ProcurementSelection(drug_name=body["drugName"], qty=float(body["qty"]), region=body.get("region"),
                                      supplier_name=body["supplierName"], reason=body.get("reason") or "Selected by supplier performance score",
                                      created_at=_now(), created_by=user["email"])
    db.add(selection)
    db.flush()
    blockchain.add_block("SUPPLIER_SELECTED", user["email"], row_to_dict(selection))
    db.commit()
    db.refresh(selection)
    return row_to_dict(selection)


@router.get("/batch/{batch}/verify")
def verify_batch(batch: str, db: Session = Depends(get_db)):
    return batch_verify.verify_batch_everywhere(db, batch)
