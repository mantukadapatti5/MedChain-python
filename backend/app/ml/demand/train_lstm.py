"""
LSTM — third of the three vendor demand-forecasting models.

Works on raw per-day sequences rather than the flat feature table: for each
(Drug_ID, Region) series, a sliding 30-day window of
[Daily_Consumption_Units, day_of_week, month, doy_sin, doy_cos] predicts the
next day's consumption.

Requires tensorflow (see backend/requirements-ml.txt).

Chronological split rule (same principle as RF/XGBoost, applied to
sequences): a sequence's LABEL date decides its split. Scaling statistics
are fit on the training portion only, never on validation/test, so no
future information leaks backward into training.
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.ml.demand.data_preparation import load_clean_dataset
from app.ml.demand.split import VAL_START, TEST_START

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
METRICS_DIR = Path(__file__).resolve().parent / "metrics"

LOOKBACK = 30
SEQ_FEATURES = ["Daily_Consumption_Units", "day_of_week", "month", "doy_sin", "doy_cos"]


def _prep_series(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["day_of_week"] = df["Date"].dt.dayofweek
    df["month"] = df["Date"].dt.month
    doy = df["Date"].dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365)
    return df


def _build_sequences(df: pd.DataFrame, scaler_mean: float, scaler_std: float):
    X_list, y_list, dates = [], [], []
    for (_drug, _region), g in df.groupby(["Drug_ID", "Region"]):
        g = g.sort_values("Date")
        values = g[SEQ_FEATURES].to_numpy(dtype=float)
        values[:, 0] = (values[:, 0] - scaler_mean) / scaler_std
        dates_arr = g["Date"].to_numpy()
        for i in range(LOOKBACK, len(g)):
            X_list.append(values[i - LOOKBACK:i])
            y_list.append(values[i, 0])
            dates.append(dates_arr[i])
    return np.array(X_list), np.array(y_list), np.array(dates)


def train():
    try:
        import tensorflow as tf
        from tensorflow.keras import layers, models, callbacks
    except ImportError as e:
        raise ImportError("tensorflow not installed. Run: pip install -r backend/requirements-ml.txt") from e

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_DIR.mkdir(parents=True, exist_ok=True)

    clean = _prep_series(load_clean_dataset())

    train_mask = clean["Date"] < VAL_START
    scaler_mean = clean.loc[train_mask, "Daily_Consumption_Units"].mean()
    scaler_std = clean.loc[train_mask, "Daily_Consumption_Units"].std()

    X, y, label_dates = _build_sequences(clean, scaler_mean, scaler_std)
    train_idx = label_dates < np.datetime64(VAL_START)
    val_idx = (label_dates >= np.datetime64(VAL_START)) & (label_dates < np.datetime64(TEST_START))
    test_idx = label_dates >= np.datetime64(TEST_START)

    X_train, y_train = X[train_idx], y[train_idx]
    X_val, y_val = X[val_idx], y[val_idx]
    X_test, y_test = X[test_idx], y[test_idx]
    print(f"[demand.lstm] sequences -> train={len(X_train)} val={len(X_val)} test={len(X_test)}")

    model = models.Sequential([
        layers.Input(shape=(LOOKBACK, len(SEQ_FEATURES))),
        layers.LSTM(32, return_sequences=False),
        layers.Dropout(0.2),
        layers.Dense(16, activation="relu"),
        layers.Dense(1),
    ])
    model.compile(optimizer="adam", loss="mse", metrics=["mae"])

    start = datetime.now()
    model.fit(X_train, y_train, validation_data=(X_val, y_val), epochs=50, batch_size=256, verbose=0,
              callbacks=[callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True)])
    train_seconds = round((datetime.now() - start).total_seconds(), 1)

    def evaluate(Xs, ys):
        if len(Xs) == 0:
            return {"n": 0, "mae": None, "rmse": None, "mape": None, "r2": None}
        pred_scaled = model.predict(Xs, verbose=0).flatten()
        pred = np.maximum(0, pred_scaled * scaler_std + scaler_mean)
        true = ys * scaler_std + scaler_mean
        mae = float(np.mean(np.abs(true - pred)))
        rmse = float(np.sqrt(np.mean((true - pred) ** 2)))
        mask = true > 0
        mape = float(np.mean(np.abs(true[mask] - pred[mask]) / true[mask]) * 100) if mask.any() else None
        ss_res, ss_tot = np.sum((true - pred) ** 2), np.sum((true - true.mean()) ** 2)
        r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else None
        return {"n": int(len(Xs)), "mae": round(mae, 3), "rmse": round(rmse, 3),
                "mape": round(mape, 2) if mape is not None else None,
                "r2": round(r2, 4) if r2 is not None else None}

    metrics = {"train": evaluate(X_train, y_train), "validation": evaluate(X_val, y_val),
               "test": evaluate(X_test, y_test)}

    model.save(ARTIFACT_DIR / "lstm.keras")
    report = {"model": "demand_lstm", "algorithm": "LSTM(32) -> Dropout -> Dense(16) -> Dense(1)",
              "trained_at": datetime.utcnow().isoformat(), "train_seconds": train_seconds,
              "lookback_days": LOOKBACK, "seq_features": SEQ_FEATURES,
              "scaler_mean": float(scaler_mean), "scaler_std": float(scaler_std), "metrics": metrics}
    (METRICS_DIR / "lstm.json").write_text(json.dumps(report, indent=2))

    print("\n=== LSTM — held-out TEST metrics ===")
    print(json.dumps(metrics["test"], indent=2))
    return report


if __name__ == "__main__":
    train()
