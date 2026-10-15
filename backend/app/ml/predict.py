"""Direct port of backend/ml/predict.js."""
import json
from datetime import date, datetime, timedelta

import joblib

from app.config import ML_ARTIFACT_DIR
from app.ml.features import compute_features
from app.ml.generate_dataset import DRUGS

MODEL_PATH = ML_ARTIFACT_DIR / "model.joblib"
REPORT_PATH = ML_ARTIFACT_DIR / "training_report.json"

_cached_model = None
_cached_report = None


def _category_for(drug_name: str) -> str:
    match = next((d for d in DRUGS if d["name"] == drug_name), None)
    return match["category"] if match else "Analgesic"


def _baseline_for(drug_name: str) -> float:
    match = next((d for d in DRUGS if d["name"] == drug_name), None)
    return match["base"] if match else 20


def _load_model():
    global _cached_model
    if _cached_model is not None:
        return _cached_model
    if not MODEL_PATH.exists():
        return None
    _cached_model = joblib.load(MODEL_PATH)
    return _cached_model


def _load_report():
    global _cached_report
    if _cached_report is not None:
        return _cached_report
    if not REPORT_PATH.exists():
        return None
    _cached_report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return _cached_report


def predict_next_period(drug_name: str, recent_history: list = None, days_ahead: int = 7) -> dict:
    """recent_history: list of {'date': ..., 'qty': ...} chronological (or unsorted; will be sorted)."""
    recent_history = recent_history or []
    model = _load_model()
    report = _load_report()
    if model is None:
        return {"available": False, "reason": "Model not trained yet. Run `python -m app.ml.train_demand`."}

    category = _category_for(drug_name)
    qty_history = [r["qty"] for r in sorted(recent_history, key=lambda r: r["date"])]

    seed_value = qty_history[-1] if qty_history else _baseline_for(drug_name)
    rolling_history = qty_history[:] if len(qty_history) >= 7 else ([seed_value] * (7 - len(qty_history))) + qty_history

    today = date.today()
    daily = []
    for d_offset in range(days_ahead):
        target_date = today + timedelta(days=d_offset)
        features = compute_features(target_date, category, len(rolling_history), rolling_history)
        pred = max(0.0, float(model.predict([features])[0]))
        daily.append(round(pred, 1))
        rolling_history.append(pred)

    forecast_next_period = round(sum(daily))
    drug_metrics = (report or {}).get("perDrugTestMetrics", {}).get(drug_name)

    return {
        "available": True,
        "forecastNextPeriod": forecast_next_period,
        "dailyBreakdown": daily,
        "method": report["method"] if report else "Random Forest Regressor (trained)",
        "trainedAt": report["trainedAt"] if report else None,
        "testMetrics": drug_metrics or ((report or {}).get("metrics", {}).get("onHeldOutTestData")),
        "isPerDrugMetric": bool(drug_metrics),
    }


def get_training_report():
    return _load_report()
