"""Direct port of backend/ml/predictShortage.js."""
import joblib

from app.config import ML_ARTIFACT_DIR
from app.ml.shortage_features import build_features

MODEL_PATH = ML_ARTIFACT_DIR / "shortage_model.joblib"
_cached_model = None


def _load_model():
    global _cached_model
    if _cached_model is not None:
        return _cached_model
    if not MODEL_PATH.exists():
        raise FileNotFoundError("Shortage model is not trained. Run `python -m app.ml.train_shortage`.")
    _cached_model = joblib.load(MODEL_PATH)
    return _cached_model


def classify(probability: float) -> str:
    if probability >= 80:
        return "critical"
    if probability >= 60:
        return "high"
    if probability >= 35:
        return "medium"
    return "low"


def predict(stock: float, history: list, forecast_demand: float, lead_time_days: float) -> dict:
    model = _load_model()
    features = build_features(stock, history, forecast_demand, lead_time_days)
    proba = model.predict_proba([features])[0]
    classes = list(model.classes_)
    shortage_probability = round(float(proba[classes.index(1)]) * 100, 1) if 1 in classes else 0.0
    return {
        "shortageProbability": shortage_probability,
        "riskLevel": classify(shortage_probability),
        "model": "Random Forest Classifier (trained on simulated stock-outs)",
        "validation": "simulation-only, not validated on real shortages",
        "features": features,
    }
