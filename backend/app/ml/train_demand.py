"""
Trains the demand-forecasting model and honestly evaluates it — a Python
port of backend/ml/train.js, upgraded to use scikit-learn's
RandomForestRegressor (per the "Python gives you a much stronger ML
ecosystem" recommendation) instead of the hand-rolled JS decision trees.
The methodology is unchanged and just as important as before:

The train/test split is done BY DATE per drug, not by randomly shuffling
rows: the model only ever trains on the earlier ~80% of each drug's
history and is tested on the later ~20% it has never seen. Shuffling
randomly would let the model "peek" at values close in time to what it's
tested on, inflating accuracy in a way that wouldn't hold up on genuinely
future data — this project deliberately avoids that shortcut.
"""
import json
from datetime import date, datetime

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from app.config import ML_ARTIFACT_DIR
from app.ml.features import compute_features
from app.ml.generate_dataset import generate_dataset, DRUGS

TEST_FRACTION = 0.2
MODEL_PATH = ML_ARTIFACT_DIR / "model.joblib"
REPORT_PATH = ML_ARTIFACT_DIR / "training_report.json"
SALES_HISTORY_PATH = ML_ARTIFACT_DIR / "sales_history.json"


def _build_supervised_rows(raw_rows: list):
    by_drug = {}
    for r in raw_rows:
        by_drug.setdefault(r["drugName"], []).append(r)

    supervised = []
    for drug_name, rows in by_drug.items():
        rows.sort(key=lambda r: r["date"])
        category = rows[0]["category"]
        history = []
        total = len(rows)
        for i, row in enumerate(rows):
            d = date.fromisoformat(row["date"])
            features = compute_features(d, category, i, history)
            supervised.append({"drugName": drug_name, "date": row["date"], "features": features,
                                "target": row["qty"], "rowIndex": i, "totalRows": total})
            history.append(row["qty"])
    return supervised


def _split_train_test(supervised: list):
    train, test = [], []
    for row in supervised:
        cutoff = int(row["totalRows"] * (1 - TEST_FRACTION))
        (train if row["rowIndex"] < cutoff else test).append(row)
    return train, test


def _evaluate(model, rows):
    if not rows:
        return {"n": 0, "mae": 0, "rmse": 0, "mape": 0, "r2": 0}
    X = np.array([r["features"] for r in rows])
    y_true = np.array([r["target"] for r in rows])
    y_pred = np.maximum(0, model.predict(X))

    mae = mean_absolute_error(y_true, y_pred)
    rmse = mean_squared_error(y_true, y_pred) ** 0.5
    positive_mask = y_true > 0
    mape = float(np.mean(np.abs(y_true[positive_mask] - y_pred[positive_mask]) / y_true[positive_mask]) * 100) if positive_mask.any() else 0.0
    r2 = r2_score(y_true, y_pred) if len(y_true) > 1 else 0.0

    return {"n": len(rows), "mae": round(float(mae), 2), "rmse": round(float(rmse), 2),
            "mape": round(mape, 2), "r2": round(float(r2), 3)}


def _evaluate_per_drug(model, rows):
    by_drug = {}
    for r in rows:
        by_drug.setdefault(r["drugName"], []).append(r)
    return {drug: _evaluate(model, drug_rows) for drug, drug_rows in by_drug.items()}


def train():
    print("Generating fresh synthetic dataset...")
    raw_rows = generate_dataset()
    ML_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    SALES_HISTORY_PATH.write_text(json.dumps(raw_rows), encoding="utf-8")

    print(f"Building supervised training rows from {len(raw_rows)} raw records...")
    supervised = _build_supervised_rows(raw_rows)
    train_rows, test_rows = _split_train_test(supervised)
    print(f"Time-based split: {len(train_rows)} train rows / {len(test_rows)} test rows "
          f"(test = last {int(TEST_FRACTION * 100)}% of each drug's calendar, strictly after training data)")

    X_train = np.array([r["features"] for r in train_rows])
    y_train = np.array([r["target"] for r in train_rows])

    print("Training Random Forest Regressor (scikit-learn, 100 trees)...")
    start = datetime.now()
    model = RandomForestRegressor(n_estimators=100, max_depth=6, min_samples_leaf=12, max_features=0.7, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    train_seconds = round((datetime.now() - start).total_seconds(), 1)
    print(f"Training complete in {train_seconds}s.")

    print("Evaluating on held-out test data the model never trained on...")
    overall = _evaluate(model, test_rows)
    per_drug = _evaluate_per_drug(model, test_rows)
    train_fit = _evaluate(model, train_rows)

    report = {
        "trainedAt": datetime.utcnow().isoformat(),
        "method": "Random Forest Regressor (scikit-learn, 100 trees, max depth 6)",
        "datasetSize": len(raw_rows),
        "drugCount": len(DRUGS),
        "trainRows": len(train_rows),
        "testRows": len(test_rows),
        "testSplitStrategy": f"Chronological per-drug split — last {int(TEST_FRACTION * 100)}% of each drug's "
                             "date range held out; model never saw these dates during training",
        "trainSeconds": train_seconds,
        "metrics": {"onTrainingData": train_fit, "onHeldOutTestData": overall},
        "perDrugTestMetrics": per_drug,
    }

    joblib.dump(model, MODEL_PATH)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== Held-out test set results (data the model never trained on) ===")
    print(f"MAE: {overall['mae']} units | RMSE: {overall['rmse']} | MAPE: {overall['mape']}% | R2: {overall['r2']}")
    print("\nPer-drug breakdown:")
    for drug, m in per_drug.items():
        print(f"  {drug}: MAE={m['mae']}, R2={m['r2']}, n={m['n']}")
    print(f"\nModel saved to {MODEL_PATH}, report saved to {REPORT_PATH}")
    return report


if __name__ == "__main__":
    train()
