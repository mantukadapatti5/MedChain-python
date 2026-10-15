"""
Isolation Forest screening of inventory records.

IMPORTANT - what this is and is not
-----------------------------------
This is an UNSUPERVISED screening aid. There is no labelled real-world data of
"true inventory anomalies" in this project, so the detector has NOT been
validated against real faults and its flags must be treated as *review
candidates*, not confirmed detections.

Its behaviour is checked only against a synthetic injected-fault benchmark
(see app/ml/evaluate_models.py and EVALUATION.md), which shows the method can
recover faults that we defined ourselves - not that it finds real-world ones.

Design (changed from the first version, see EVALUATION.md for the numbers):
  * Each tier (vendor / distributor / client) is scanned SEPARATELY. Mixing tiers
    made the model mostly learn the difference in stock scale between tiers.
  * Features are log-transformed (stock levels are heavy-tailed).
  * Records are flagged when their ABSOLUTE Isolation Forest score is at least
    REVIEW_THRESHOLD. The first version forced a fixed fraction of records
    (contamination 5-20%) to be flagged, so it "found" anomalies even in a
    population without any, and it min-max rescaled scores inside every scan.
  * A tier with fewer than MIN_POPULATION records is skipped (too few records
    for an unsupervised scan to mean anything).
  * The text in `reason` is a rule-based description of the record's numbers,
    it is NOT an explanation produced by the model.
"""
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import IsolationForest

MIN_POPULATION = 20
REVIEW_THRESHOLD = 0.60          # calibrated on synthetic fault-free populations (~3% flagged)
HIGH_SEVERITY_SCORE = 0.70
MEDIUM_SEVERITY_SCORE = 0.62
N_ESTIMATORS = 200
RANDOM_STATE = 314159


def _days_to_expiry(expiry_date) -> float:
    if not expiry_date:
        return 365
    try:
        expiry = datetime.fromisoformat(str(expiry_date).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return (expiry - datetime.now(timezone.utc)).days
    except Exception:
        return 365


def _safe_number(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def feature_vector(stock, avg_daily_demand, reorder_point, days_to_expiry) -> list:
    """[stock, avg daily demand, days of supply, reorder point, days to expiry, shortfall below reorder point]"""
    stock = max(0.0, float(stock))
    demand = max(0.0, float(avg_daily_demand))
    reorder_point = max(0.0, float(reorder_point))
    days_supply = stock / demand if demand > 0 else stock
    return [stock, demand, days_supply, reorder_point, max(0.0, float(days_to_expiry)), max(0.0, reorder_point - stock)]


def _inventory_features(item: dict, sales_history: list) -> list:
    history = [s for s in sales_history if s.get("drugName") == item.get("drugName")]
    recent = sorted(history, key=lambda s: s.get("date", ""), reverse=True)[:14]
    total = sum(_safe_number(s.get("qty")) for s in recent)
    avg_daily_demand = total / len(recent) if recent else 0.0
    return feature_vector(
        _safe_number(item.get("stock")), avg_daily_demand,
        _safe_number(item.get("reorderPoint")), _days_to_expiry(item.get("expiryDate")),
    )


def score_population(vectors) -> np.ndarray:
    """Isolation Forest anomaly score s in (0, 1) for each row (the score from the original paper:
    around 0.5 = typical, closer to 1 = easier to isolate = more unusual). The score is NOT rescaled
    per scan, so it can be compared between scans."""
    vectors = np.asarray(vectors, dtype=float)
    transformed = np.log1p(np.maximum(vectors, 0.0))
    model = IsolationForest(n_estimators=N_ESTIMATORS, max_samples=min(256, len(transformed)),
                            contamination="auto", random_state=RANDOM_STATE)
    model.fit(transformed)
    return -model.score_samples(transformed)


def _severity_from_score(score: float) -> str:
    if score >= HIGH_SEVERITY_SCORE:
        return "high"
    if score >= MEDIUM_SEVERITY_SCORE:
        return "medium"
    return "low"


def _reason_for(score: float, vector: list) -> str:
    stock, demand, days_supply, reorder_point, expiry = vector[0], vector[1], vector[2], vector[3], vector[4]
    reasons = []
    if demand > 0 and stock < demand * 3:
        reasons.append("stock is unusually low compared with recent demand")
    if reorder_point > 0 and stock < reorder_point:
        reasons.append("stock is below the reorder point")
    if expiry <= 30:
        reasons.append("batch is close to expiry")
    if days_supply > 60:
        reasons.append("stock is unusually high relative to recent demand")
    if not reasons:
        reasons.append("inventory pattern differs from the other records in this tier")
    return (f"Isolation Forest score {score:.2f} (unsupervised review candidate, not a validated detection): "
            f"{'; '.join(reasons)}.")


def scan_inventory_with_isolation_forest(inventory: list, sales_history: list = None) -> list:
    """`inventory`: camelCase dicts of ONE tier (drugName, batch, stock, reorderPoint, expiryDate, ...).
    Returns one result per item: {item, score, anomaly, severity, reason, features}, or [] when the
    tier has fewer than MIN_POPULATION records."""
    sales_history = sales_history or []
    if len(inventory) < MIN_POPULATION:
        return []

    vectors = np.array([_inventory_features(item, sales_history) for item in inventory])
    scores = score_population(vectors)

    results = []
    for i, item in enumerate(inventory):
        score = float(scores[i])
        results.append({
            "item": item,
            "score": round(score, 4),
            "anomaly": bool(score >= REVIEW_THRESHOLD),
            "severity": _severity_from_score(score),
            "reason": _reason_for(score, vectors[i].tolist()),
            "features": {
                "stock": vectors[i][0], "avgDailyDemand": round(vectors[i][1], 2),
                "daysOfSupply": round(vectors[i][2], 1), "reorderPoint": vectors[i][3],
                "daysToExpiry": vectors[i][4],
            },
        })
    return results
