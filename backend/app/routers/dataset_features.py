from datetime import datetime

from fastapi import APIRouter, Depends

from app.deps import require_roles
from app.services.dataset_loader import load_datasets

router = APIRouter(prefix="/api/level2/dataset", tags=["dataset-features"], dependencies=[Depends(require_roles("admin"))])


@router.get("/regional-forecast")
def regional_forecast(drugName: str = None, region: str = None, hospitalId: str = None, days: int = 7):
    data = load_datasets()
    sales, hospital_demand, inventory = data["sales"], data["hospitalDemand"], data["inventory"]
    horizon = max(1, min(int(days or 7), 30))
    rows = [r for r in hospital_demand
            if (not drugName or r.get("drug_name") == drugName)
            and (not region or r.get("region") == region)
            and (not hospitalId or str(r.get("hospital_id")) == str(hospitalId))]

    grouped = {}
    for r in rows:
        key = f"{r.get('hospital_id')}|{r.get('drug_name')}"
        grouped.setdefault(key, []).append(r)

    results = []
    for key, history in grouped.items():
        hospital_id, drug_name = key.split("|")
        ordered = sorted(history, key=lambda r: r.get("date") or "")
        recent = ordered[-min(4, len(ordered)):]
        avg_weekly = sum(float(r.get("quantity_used") or 0) for r in recent) / len(recent) if recent else 0
        forecast_demand = max(0, round(avg_weekly * (horizon / 7)))
        hospital = ordered[-1]
        inv = sum(float(r.get("current_stock") or 0) for r in inventory if r.get("drug_name") == drug_name and r.get("region") == hospital.get("region"))
        daily_rate = forecast_demand / horizon if horizon else 0
        days_of_supply = round(inv / daily_rate, 1) if daily_rate else None
        shortage = ("unknown" if days_of_supply is None else "critical" if days_of_supply < 3 else "high" if days_of_supply < 7 else "medium" if days_of_supply < 14 else "low")
        results.append({
            "hospitalId": hospital_id if hospital_id not in ("None", "") else None, "hospitalName": hospital.get("hospital_name"),
            "region": hospital.get("region"), "drugName": drug_name, "currentRegionalStock": inv,
            "forecastDemand": forecast_demand, "horizonDays": horizon, "daysOfSupply": days_of_supply,
            "shortageRisk": shortage, "historyRecords": len(ordered), "method": "Hospital demand history moving-average baseline",
        })
    results.sort(key=lambda r: (-r["forecastDemand"], r["daysOfSupply"] if r["daysOfSupply"] is not None else 9999))

    regional_summary = {}
    for row in results:
        rs = regional_summary.setdefault(row["region"], {"region": row["region"], "forecastDemand": 0, "currentStock": 0, "criticalItems": 0, "highRiskItems": 0})
        rs["forecastDemand"] += row["forecastDemand"]
        rs["currentStock"] += row["currentRegionalStock"]
        if row["shortageRisk"] == "critical":
            rs["criticalItems"] += 1
        if row["shortageRisk"] == "high":
            rs["highRiskItems"] += 1
    regional_summary_list = sorted(regional_summary.values(), key=lambda r: r["forecastDemand"], reverse=True)

    return {"source": "3_hospital_client_demand.csv + 2_inventory_batch.csv", "horizonDays": horizon, "results": results,
            "regionalSummary": regional_summary_list, "salesRowsAvailable": len(sales)}


@router.get("/supplier-ranking")
def supplier_ranking_route(drugName: str = None):
    from app.services.supplier_ranking import rank_suppliers
    return {"source": "6_supplier_vendor_performance.csv", "suppliers": rank_suppliers(drugName)}


@router.get("/shipment-summary")
def shipment_summary():
    rows = load_datasets()["shipments"]
    summary = {}
    for r in rows:
        status = str(r.get("status") or "Unknown")
        summary[status] = summary.get(status, 0) + 1
    return {"source": "4_shipment_history.csv", "total": len(rows), "statusCounts": summary, "shipments": rows[:100]}


@router.get("/cold-chain-summary")
def cold_chain_summary():
    rows = load_datasets()["coldChain"]
    breaches = [r for r in rows if str(r.get("status", "")).lower() == "breach"]
    return {"source": "5_cold_chain.csv", "totalReadings": len(rows), "breachCount": len(breaches),
            "normalCount": len(rows) - len(breaches),
            "breachRate": round(len(breaches) / len(rows) * 100, 1) if rows else 0,
            "recentBreaches": breaches[-100:]}
