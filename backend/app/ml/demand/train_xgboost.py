"""
XGBoost Regressor — second of the three vendor demand-forecasting models.
Uses the identical cleaned data, features, and chronological split as
train_rf.py so results are directly comparable.

Requires `xgboost` (see backend/requirements-ml.txt) -- kept out of the
core requirements.txt so the API doesn't need heavy ML deps just to boot
and serve already-trained artifacts.
"""
import json
from datetime import datetime
from pathlib import Path

import joblib

from app.ml.demand.data_preparation import load_clean_dataset
from app.ml.demand.features import build_feature_table
from app.ml.demand.split import chronological_split
from app.ml.demand.train_rf import evaluate

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
METRICS_DIR = Path(__file__).resolve().parent / "metrics"


def train():
    try:
        from xgboost import XGBRegressor
    except ImportError as e:
        raise ImportError("xgboost not installed. Run: pip install -r backend/requirements-ml.txt") from e

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    clean = load_clean_dataset()
    feat_df, feature_cols = build_feature_table(clean)
    train_df, val_df, test_df = chronological_split(feat_df)

    X_train, y_train = train_df[feature_cols].values, train_df["Daily_Consumption_Units"].values
    X_val, y_val = val_df[feature_cols].values, val_df["Daily_Consumption_Units"].values
    X_test, y_test = test_df[feature_cols].values, test_df["Daily_Consumption_Units"].values

    print("Training XGBoost Regressor...")
    start = datetime.now()
    model = XGBRegressor(n_estimators=400, max_depth=6, learning_rate=0.05, subsample=0.8,
                          colsample_bytree=0.8, reg_lambda=1.0, random_state=42, n_jobs=-1,
                          early_stopping_rounds=30, eval_metric="mae")
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    train_seconds = round((datetime.now() - start).total_seconds(), 1)

    metrics = {"train": evaluate(model, X_train, y_train), "validation": evaluate(model, X_val, y_val),
               "test": evaluate(model, X_test, y_test)}

    joblib.dump({"model": model, "feature_cols": feature_cols}, ARTIFACT_DIR / "xgboost.joblib")
    report = {"model": "demand_xgboost", "algorithm": "XGBRegressor",
              "trained_at": datetime.utcnow().isoformat(), "train_seconds": train_seconds,
              "best_iteration": int(getattr(model, "best_iteration", -1)),
              "feature_cols": feature_cols, "metrics": metrics}
    (METRICS_DIR / "xgboost.json").write_text(json.dumps(report, indent=2))

    print("\n=== XGBoost — held-out TEST metrics ===")
    print(json.dumps(metrics["test"], indent=2))
    return report


if __name__ == "__main__":
    train()
