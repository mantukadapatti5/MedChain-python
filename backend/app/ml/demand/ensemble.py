"""
Combines RF, XGBoost, and LSTM into one ensemble forecast. Weights come from
each model's validation-set MAE (lower error -> higher weight) -- never
arbitrary. If a model's artifact is missing (e.g. XGBoost/LSTM not yet
trained in this environment), it's left out and the rest are re-normalized,
so the ensemble degrades gracefully instead of failing outright.
"""
import json
from pathlib import Path

import joblib
import numpy as np

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
METRICS_DIR = Path(__file__).resolve().parent / "metrics"
WEIGHTS_PATH = ARTIFACT_DIR / "ensemble_weights.json"

_cache = {}


def compute_weights() -> dict:
    maes = {}
    for name, fname in [("rf", "rf.json"), ("xgboost", "xgboost.json"), ("lstm", "lstm.json")]:
        path = METRICS_DIR / fname
        if path.exists():
            report = json.loads(path.read_text())
            mae = report["metrics"]["validation"]["mae"]
            if mae:
                maes[name] = mae
    if not maes:
        return {}
    inv = {name: 1.0 / mae for name, mae in maes.items()}
    total = sum(inv.values())
    weights = {name: round(v / total, 4) for name, v in inv.items()}
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(json.dumps({"weights": weights, "based_on_validation_mae": maes}, indent=2))
    return weights


def get_weights() -> dict:
    if WEIGHTS_PATH.exists():
        return json.loads(WEIGHTS_PATH.read_text())["weights"]
    return compute_weights()


def _load(name):
    if name in _cache:
        return _cache[name]
    if name == "lstm":
        path = ARTIFACT_DIR / "lstm.keras"
        if not path.exists():
            _cache[name] = None
            return None
        import tensorflow as tf
        _cache[name] = tf.keras.models.load_model(path)
    else:
        path = ARTIFACT_DIR / f"{name}.joblib"
        if not path.exists():
            _cache[name] = None
            return None
        _cache[name] = joblib.load(path)
    return _cache[name]


def models_available() -> dict:
    return {
        "rf": (ARTIFACT_DIR / "rf.joblib").exists(),
        "xgboost": (ARTIFACT_DIR / "xgboost.joblib").exists(),
        "lstm": (ARTIFACT_DIR / "lstm.keras").exists(),
    }


def predict_one(feature_row: dict, lstm_sequence: np.ndarray = None) -> dict:
    """Single-step prediction from whichever models are trained."""
    weights = get_weights()
    predictions = {}

    rf_bundle = _load("rf")
    if rf_bundle:
        x = np.array([[feature_row[c] for c in rf_bundle["feature_cols"]]])
        predictions["rf"] = max(0.0, float(rf_bundle["model"].predict(x)[0]))

    xgb_bundle = _load("xgboost")
    if xgb_bundle:
        x = np.array([[feature_row[c] for c in xgb_bundle["feature_cols"]]])
        predictions["xgboost"] = max(0.0, float(xgb_bundle["model"].predict(x)[0]))

    lstm_model = _load("lstm")
    if lstm_model is not None and lstm_sequence is not None:
        pred = lstm_model.predict(lstm_sequence[np.newaxis, ...], verbose=0)[0][0]
        predictions["lstm"] = max(0.0, float(pred))

    active_weights = {k: weights.get(k, 0) for k in predictions}
    total_w = sum(active_weights.values())
    if total_w > 0:
        ensemble = sum(predictions[k] * active_weights[k] for k in predictions) / total_w
    else:
        ensemble = float(np.mean(list(predictions.values()))) if predictions else None

    return {"models": predictions, "weightsUsed": active_weights,
            "ensemble": round(ensemble, 2) if ensemble is not None else None}
