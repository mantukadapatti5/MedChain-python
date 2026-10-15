"""Direct port of backend/utils/regionalForecast.js."""
from datetime import datetime
from app.ml import predict as ml_predict


def _parse_date(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def _numeric_qty(row):
    return float(row.get("qty", row.get("quantity", 0)) or 0)


def _normalize_history(rows):
    out = []
    for row in rows:
        date = row.get("date") or row.get("recordedAt") or row.get("createdAt")
        qty = _numeric_qty(row)
        if qty > 0 and date:
            try:
                _parse_date(date)
                out.append({"date": date, "qty": qty})
            except Exception:
                continue
    return sorted(out, key=lambda r: _parse_date(r["date"]))


def _aggregate_by_day(rows):
    by_day = {}
    for row in rows:
        day = _parse_date(row["date"]).date().isoformat()
        by_day[day] = by_day.get(day, 0) + row["qty"]
    return [{"date": d, "qty": q} for d, q in by_day.items()]


def _moving_average_forecast(history, days):
    values = [r["qty"] for r in history]
    if not values:
        return [0] * days
    window = min(7, len(values))
    avg = sum(values[-window:]) / window
    return [round(avg, 1)] * days


def _forecast_series(drug_name, history, horizon):
    daily = _aggregate_by_day(_normalize_history(history))
    if len(daily) >= 3:
        try:
            result = ml_predict.predict_next_period(drug_name, daily, horizon)
            if result.get("available"):
                return result, result.get("method", "Random Forest")
        except Exception:
            pass
    breakdown = _moving_average_forecast(daily, horizon)
    trend = "rising" if len(breakdown) > 1 and breakdown[-1] > breakdown[0] else "stable"
    method = "Moving Average fallback" if len(daily) >= 3 else "Insufficient segment history — baseline estimate"
    return {"available": True, "forecastNextPeriod": round(sum(breakdown)), "dailyBreakdown": breakdown, "trend": trend}, method


def build_regional_forecast(clients: list, drug_names_all: list, usage_log: list, client_requests: list,
                             sales: list, *, drug_name=None, region=None, client_id=None, days=7) -> dict:
    horizon = max(1, min(int(days or 7), 30))
    targets = [c for c in clients if (not region or c["region"] == region) and (not client_id or c["id"] == int(client_id))]
    drug_names = [drug_name] if drug_name else sorted(set(drug_names_all))

    results = []
    for client in targets:
        for name in drug_names:
            usage_history = [r for r in usage_log if r.get("clientId") == client["id"] and r.get("drugName") == name]
            request_history = [r for r in client_requests if r.get("clientId") == client["id"] and r.get("drugName") == name and r.get("status") != "rejected"]
            client_history = usage_history + request_history
            external_sales = [r for r in sales if r.get("drugName") == name and (not region or r.get("region") == region) and (not client.get("name") or r.get("buyer") == client.get("name"))]
            history = client_history if client_history else external_sales
            if not history:
                continue

            forecast, method = _forecast_series(name, history, horizon)
            current_stock = client.get("stockByDrug", {}).get(name, 0)
            forecast_total = float(forecast.get("forecastNextPeriod", 0))
            daily_rate = forecast_total / horizon if horizon else 0
            days_of_supply = round(current_stock / daily_rate, 1) if daily_rate > 0 else None
            if days_of_supply is None:
                shortage = "unknown"
            elif days_of_supply < 3:
                shortage = "critical"
            elif days_of_supply < 7:
                shortage = "high"
            elif days_of_supply < 14:
                shortage = "medium"
            else:
                shortage = "low"

            results.append({
                "clientId": client["id"], "clientName": client.get("name"), "clientType": client.get("type"),
                "region": client.get("region"), "drugName": name, "currentStock": current_stock,
                "forecastDemand": forecast_total, "dailyForecast": forecast.get("dailyBreakdown", []),
                "daysOfSupply": days_of_supply, "shortageRisk": shortage, "historyRecords": len(history),
                "source": "Client usage history" if usage_history else "Client requests / sales history",
                "model": method,
            })

    results.sort(key=lambda r: (-r["forecastDemand"], r["daysOfSupply"] if r["daysOfSupply"] is not None else 9999))
    return {"horizonDays": horizon, "filters": {"drugName": drug_name, "region": region, "clientId": client_id}, "results": results}


def summarize_regions(report: dict) -> list:
    by_region = {}
    for row in report["results"]:
        r = by_region.setdefault(row["region"], {"region": row["region"], "forecastDemand": 0, "currentStock": 0, "criticalItems": 0, "highRiskItems": 0})
        r["forecastDemand"] += row["forecastDemand"]
        r["currentStock"] += row["currentStock"]
        if row["shortageRisk"] == "critical":
            r["criticalItems"] += 1
        if row["shortageRisk"] == "high":
            r["highRiskItems"] += 1
    return sorted(by_region.values(), key=lambda r: r["forecastDemand"], reverse=True)
