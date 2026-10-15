"""Direct port of backend/utils/mlEngine.js."""
import hashlib
from datetime import datetime, date, timezone

from app.ml import predict as ml_predict


def _parse_date(v):
    if isinstance(v, (datetime, date)):
        return v
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def fit_holt_model(series: list):
    if len(series) < 2:
        return None
    best, best_sse = None, float("inf")
    alpha = 0.1
    while alpha <= 0.9 + 1e-9:
        beta = 0.1
        while beta <= 0.9 + 1e-9:
            level, trend = series[0], series[1] - series[0]
            sse = 0.0
            for t in range(1, len(series)):
                forecast = level + trend
                error = series[t] - forecast
                sse += error * error
                new_level = alpha * series[t] + (1 - alpha) * (level + trend)
                new_trend = beta * (new_level - level) + (1 - beta) * trend
                level, trend = new_level, new_trend
            if sse < best_sse:
                best_sse = sse
                best = {"alpha": round(alpha, 1), "beta": round(beta, 1), "level": level, "trend": trend, "sse": sse}
            beta += 0.1
        alpha += 0.1
    return best


def forecast_demand(sales_history: list) -> dict:
    """Holt's exponential smoothing (fitted via grid search) or weighted
    moving average fallback for thin histories. `sales_history`: list of
    dicts with 'date' and 'qty'."""
    if not sales_history:
        return {"forecastNextPeriod": 0, "trend": "flat", "confidence": 0.3, "method": "no sales history available"}

    sorted_hist = sorted(sales_history, key=lambda s: _parse_date(s["date"]))
    qtys = [float(s["qty"]) for s in sorted_hist]
    n = len(qtys)

    if n >= 4:
        fit = fit_holt_model(qtys)
        if fit:
            forecast_next = max(0, round(fit["level"] + fit["trend"]))
            trend = "rising" if fit["trend"] > 0.5 else "falling" if fit["trend"] < -0.5 else "stable"
            confidence = min(0.95, 0.55 + n * 0.04)
            return {
                "forecastNextPeriod": forecast_next,
                "trend": trend,
                "confidence": round(confidence, 2),
                "method": f"Holt's exponential smoothing (fitted: alpha={fit['alpha']}, beta={fit['beta']})",
            }

    weights = list(range(1, n + 1))
    weight_sum = sum(weights)
    wma = sum(q * w for q, w in zip(qtys, weights)) / weight_sum
    x_mean = (n - 1) / 2
    y_mean = sum(qtys) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in enumerate(qtys))
    den = sum((x - x_mean) ** 2 for x in range(n))
    slope = 0 if den == 0 else num / den

    forecast_next = max(0, round(wma + slope))
    trend = "rising" if slope > 0.5 else "falling" if slope < -0.5 else "stable"
    confidence = min(0.95, 0.5 + n * 0.05)
    return {
        "forecastNextPeriod": forecast_next,
        "trend": trend,
        "confidence": round(confidence, 2),
        "method": "weighted moving average (too little history to fit a trend model reliably)",
    }


def get_ai_forecast(drug_name: str, sales_history: list) -> dict:
    """Primary demand forecast: uses the trained Random Forest model when
    available/reliable; otherwise honestly falls back to the statistical
    method and says so."""
    MIN_LIVE_HISTORY = 5
    if len(sales_history) < MIN_LIVE_HISTORY:
        fallback = forecast_demand(sales_history)
        fallback["method"] = (
            f"{fallback['method']} (trained model available, but only {len(sales_history)} live sales "
            "record(s) exist for this drug — too little to trust its lag/rolling-average features yet)"
        )
        fallback["isTrainedModel"] = False
        return fallback

    recent = [{"date": s["date"], "qty": s["qty"]} for s in sales_history]
    trained = ml_predict.predict_next_period(drug_name, recent, 7)

    if trained.get("available"):
        breakdown = trained["dailyBreakdown"]
        if len(breakdown) >= 2 and breakdown[-1] > breakdown[0] * 1.15:
            trend = "rising"
        elif len(breakdown) >= 2 and breakdown[-1] < breakdown[0] * 0.85:
            trend = "falling"
        else:
            trend = "stable"
        test_metrics = trained.get("testMetrics")
        confidence = max(0.3, min(0.97, test_metrics["r2"])) if test_metrics else 0.6
        suffix = " — tested on held-out data for this drug" if trained.get("isPerDrugMetric") else " — tested on held-out data (overall model)"
        return {
            "forecastNextPeriod": trained["forecastNextPeriod"],
            "trend": trend,
            "confidence": confidence,
            "method": trained["method"] + suffix,
            "testMetrics": test_metrics,
            "isTrainedModel": True,
        }

    fallback = forecast_demand(sales_history)
    fallback["isTrainedModel"] = False
    return fallback


def dynamic_reorder_point(avg_daily_usage: float, lead_time_days: float = 3, safety_stock: float = 0.2) -> int:
    base = avg_daily_usage * lead_time_days
    import math
    return math.ceil(base * (1 + safety_stock))


def detect_inventory_anomalies(item: dict) -> list:
    """`item` is a camelCase dict (drugName, batch, expiryDate, stock, reorderPoint, manufacturer, provenanceChecksum)."""
    anomalies = []
    now = datetime.now(timezone.utc)
    try:
        expiry = _parse_date(item["expiryDate"])
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        days_to_expiry = (expiry - now).days
    except Exception:
        days_to_expiry = 9999

    if 0 <= days_to_expiry <= 30:
        anomalies.append({
            "type": "near-expiry",
            "severity": "high" if days_to_expiry <= 7 else "medium",
            "message": f"Batch {item.get('batch')} expires in {days_to_expiry} day(s)",
        })
    if days_to_expiry < 0:
        anomalies.append({
            "type": "expired",
            "severity": "high",
            "message": f"Batch {item.get('batch')} expired {abs(days_to_expiry)} day(s) ago",
        })
    if float(item.get("stock", 0)) <= float(item.get("reorderPoint", 0)):
        anomalies.append({
            "type": "low-stock",
            "severity": "high" if item.get("stock", 0) == 0 else "medium",
            "message": f"{item.get('drugName')} stock ({item.get('stock')}) at/below reorder point ({item.get('reorderPoint')})",
        })

    if item.get("provenanceChecksum"):
        recomputed = compute_provenance_checksum(item.get("batch"), item.get("manufacturer") or "N/A")
        if recomputed != item["provenanceChecksum"]:
            anomalies.append({
                "type": "counterfeit-flag",
                "severity": "high",
                "message": f"Batch {item.get('batch')} failed provenance checksum verification",
            })
    return anomalies


def check_cold_chain(temp: float, humidity: float, min_temp=2, max_temp=8, max_humidity=60) -> dict:
    alerts = []
    if temp < min_temp or temp > max_temp:
        alerts.append(f"Temperature breach: {temp}\u00b0C (safe range {min_temp}-{max_temp}\u00b0C)")
    if humidity > max_humidity:
        alerts.append(f"Humidity breach: {humidity}% (max {max_humidity}%)")
    return {"breached": len(alerts) > 0, "alerts": alerts}


def compute_provenance_checksum(batch: str, manufacturer: str) -> str:
    return hashlib.md5(f"{batch}|{manufacturer or 'N/A'}".encode("utf-8")).hexdigest()[:10]


def detect_surge(sales_history: list, recent_days=3, baseline_days=14) -> dict:
    if not sales_history:
        return {"isSurge": False, "ratio": 1, "recentAvgPerDay": 0, "baselineAvgPerDay": 0}
    now = datetime.now(timezone.utc)
    sorted_hist = sorted(sales_history, key=lambda s: _parse_date(s["date"]))

    def _aware(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    from datetime import timedelta
    recent_cutoff = now - timedelta(days=recent_days)
    baseline_cutoff = now - timedelta(days=recent_days + baseline_days)

    recent = [s for s in sorted_hist if _aware(_parse_date(s["date"])) >= recent_cutoff]
    baseline = [s for s in sorted_hist if baseline_cutoff <= _aware(_parse_date(s["date"])) < recent_cutoff]

    recent_total = sum(float(s["qty"]) for s in recent)
    baseline_total = sum(float(s["qty"]) for s in baseline)

    recent_avg = recent_total / recent_days
    baseline_avg = (baseline_total / baseline_days) or 0.001

    ratio = round(recent_avg / baseline_avg, 2)
    is_surge = len(baseline) > 0 and ratio >= 2.0 and recent_total >= 10

    return {"isSurge": is_surge, "ratio": ratio, "recentAvgPerDay": round(recent_avg, 1), "baselineAvgPerDay": round(baseline_avg, 1)}


def evaluate_quantity_mismatch(qty_dispatched, qty_received) -> dict:
    if qty_dispatched is None or qty_received is None:
        return {"mismatch": False}
    diff = qty_dispatched - qty_received
    if diff == 0:
        return {"mismatch": False, "diff": 0, "diffPercent": 0}
    diff_percent = abs(diff) / qty_dispatched if qty_dispatched else 0
    return {
        "mismatch": True,
        "diff": diff,
        "diffPercent": round(diff_percent * 100, 1),
        "severity": "high" if diff_percent >= 0.2 else "medium",
        "direction": "shortfall" if diff > 0 else "excess",
    }


def shortage_risk(stock: float, avg_daily_demand: float) -> dict:
    demand = avg_daily_demand if avg_daily_demand > 0 else 0.01
    days_of_supply = round(stock / demand, 1)
    level = "low"
    if days_of_supply < 3:
        level = "critical"
    elif days_of_supply < 7:
        level = "high"
    elif days_of_supply < 14:
        level = "medium"
    return {"daysOfSupply": days_of_supply, "level": level}
