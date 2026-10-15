from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.postgres import get_db
from app.deps import require_roles
from app.models.sql_models import ScenarioRun
from app.serializers import row_to_dict
from app.services import blockchain
from app.services.dataset_loader import load_datasets
from app.ml import predict as ml_predict
from app.ml import predict_shortage

router = APIRouter(prefix="/api/level2/dataset-actions", tags=["dataset-actions"], dependencies=[Depends(require_roles("admin"))])


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.post("/scenario", status_code=201)
def dataset_scenario(body: dict, db: Session = Depends(get_db), user: dict = Depends(require_roles("admin"))):
    data = load_datasets()
    sales, inventory = data["sales"], data["inventory"]
    drug_name = body.get("drugName")
    increase = float(body.get("demandIncreasePercent") or 0)
    horizon = max(1, min(int(body.get("daysAhead") or 7), 30))
    if not drug_name or not (-90 <= increase <= 500):
        raise HTTPException(status_code=400, detail="drugName and demandIncreasePercent (-90 to 500) are required.")

    stock_rows = [r for r in inventory if r.get("drug_name") == drug_name]
    if not stock_rows:
        raise HTTPException(status_code=404, detail="Medicine not found in inventory dataset.")
    stock = sum(float(r.get("current_stock") or 0) for r in stock_rows)
    # lead_time_days lives in 1_sales_demand_history.csv, not 2_inventory_batch.csv —
    # pull it from the matching sales rows for this drug instead of the (nonexistent)
    # inventory column, so this reflects the real dataset instead of a hardcoded default.
    lead_time_rows = [r for r in sales if r.get("drug_name") == drug_name and r.get("lead_time_days") is not None]
    lead = (sum(float(r["lead_time_days"]) for r in lead_time_rows) / len(lead_time_rows)) if lead_time_rows else 3

    rows = sorted([r for r in sales if r.get("drug_name") == drug_name], key=lambda r: r.get("date") or "")
    history = [{"date": r.get("date"), "qty": float(r.get("quantity_sold") or 0)} for r in rows]
    forecast = ml_predict.predict_next_period(drug_name, history, horizon)
    if not forecast.get("available"):
        raise HTTPException(status_code=400, detail=forecast.get("reason"))

    baseline = float(forecast.get("forecastNextPeriod") or 0)
    scenario = max(0, round(baseline * (1 + increase / 100)))
    qty_history = [h["qty"] for h in history]
    base_classifier = predict_shortage.predict(stock, qty_history, baseline, lead)
    scenario_classifier = predict_shortage.predict(stock, qty_history, scenario, lead)

    result = ScenarioRun(
        source="CSV dataset", drug_name=drug_name, current_stock=stock, demand_increase_percent=increase,
        days_ahead=horizon, baseline_forecast=baseline, scenario_forecast=scenario,
        additional_demand_units=max(0, scenario - baseline),
        baseline_risk=base_classifier["riskLevel"], baseline_days_of_supply=None,
        scenario_shortage_probability=scenario_classifier["shortageProbability"],
        scenario_risk_level=scenario_classifier["riskLevel"], model="Random Forest (CSV dataset)",
        created_at=_now(), created_by=user["email"],
    )
    db.add(result)
    db.flush()
    payload = row_to_dict(result)
    payload["baselineShortageProbability"] = base_classifier["shortageProbability"]
    blockchain.add_block("WHAT_IF_DATASET_SCENARIO", user["email"], payload)
    db.commit()
    db.refresh(result)
    return payload


@router.get("/redistribution-recommendations")
def redistribution_recommendations():
    inventory = load_datasets()["inventory"]
    grouped = {}
    for r in inventory:
        drug, region = r.get("drug_name"), r.get("region") or "Unassigned"
        grouped.setdefault(drug, {})
        grouped[drug][region] = grouped[drug].get(region, 0) + float(r.get("current_stock") or 0)

    recommendations = []
    for drug_name, regions in grouped.items():
        entries = list(regions.items())
        if len(entries) < 2:
            continue
        total = sum(v for _, v in entries)
        avg = total / len(entries)
        source = max(entries, key=lambda kv: kv[1])
        target = min(entries, key=lambda kv: kv[1])
        if source[1] <= avg * 1.25 or target[1] >= avg * 0.75:
            continue
        recommendations.append({
            "id": f"{drug_name}:{source[0]}:{target[0]}", "source": "2_inventory_batch.csv", "drugName": drug_name,
            "fromRegion": source[0], "toRegion": target[0], "fromStock": source[1], "toStock": target[1],
            "suggestedQty": max(1, int((source[1] - avg) * 0.5)),
            "reason": f"{source[0]} has surplus stock while {target[0]} has the lowest stock.",
        })
    return recommendations
