"""Random Forest Regressor — one of the three vendor demand-forecasting models."""
import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from app.ml.demand.data_preparation import load_clean_dataset
from app.ml.demand.features import build_feature_table
from app.ml.demand.split import chronological_split

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
METRICS_DIR = Path(__file__).resolve().parent / "metrics"


def evaluate(model, X, y):
    if len(X) == 0:
        return {"n": 0, "mae": None, "rmse": None, "mape": None, "r2": None}
    pred = np.maximum(0, model.predict(X))
    mae = mean_absolute_error(y, pred)
    rmse = mean_squared_error(y, pred) ** 0.5
    mask = y > 0
    mape = float(np.mean(np.abs(y[mask] - pred[mask]) / y[mask]) * 100) if mask.any() else None
    r2 = r2_score(y, pred) if len(y) > 1 else None
    return {"n": int(len(X)), "mae": round(float(mae), 3), "rmse": round(float(rmse), 3),
            "mape": round(mape, 2) if mape is not None else None,
            "r2": round(float(r2), 4) if r2 is not None else None}


def train():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    clean = load_clean_dataset()
    feat_df, feature_cols = build_feature_table(clean)
    train_df, val_df, test_df = chronological_split(feat_df)

    X_train, y_train = train_df[feature_cols].values, train_df["Daily_Consumption_Units"].values
    X_val, y_val = val_df[feature_cols].values, val_df["Daily_Consumption_Units"].values
    X_test, y_test = test_df[feature_cols].values, test_df["Daily_Consumption_Units"].values

    print("Training Random Forest Regressor (200 trees)...")
    start = datetime.now()
    model = RandomForestRegressor(n_estimators=200, max_depth=10, min_samples_leaf=5,
                                   max_features=0.7, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    train_seconds = round((datetime.now() - start).total_seconds(), 1)

    metrics = {"train": evaluate(model, X_train, y_train), "validation": evaluate(model, X_val, y_val),
               "test": evaluate(model, X_test, y_test)}

    joblib.dump({"model": model, "feature_cols": feature_cols}, ARTIFACT_DIR / "rf.joblib")
    report = {"model": "demand_rf", "algorithm": "RandomForestRegressor",
              "trained_at": datetime.utcnow().isoformat(), "train_seconds": train_seconds,
              "feature_cols": feature_cols, "metrics": metrics}
    (METRICS_DIR / "rf.json").write_text(json.dumps(report, indent=2))

    print("\n=== Random Forest — held-out TEST metrics ===")
    print(json.dumps(metrics["test"], indent=2))
    return report


if __name__ == "__main__":
    train()
