"""
Inference for the vendor demand-forecasting subsystem. Produces:
  - catalog(): the drugs/regions available in the dataset (for the UI's
    dropdowns)
  - forecast_series(): historical actual values PLUS a multi-day-ahead
    forecast from each trained model and the ensemble, in a single
    date-ordered array the frontend can plot directly as a line chart.

Multi-day forecasts are produced recursively: predict day+1, feed that
prediction back in as if it were observed to build day+2's lag/rolling
features, and so on. This is standard practice for lag-feature models
forecasting beyond a single step, and is clearly labeled as "forecast"
(not "actual") in the returned series.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from app.ml.demand.data_preparation import load_clean_dataset
from app.ml.demand.features import build_feature_table, LAG_DAYS, ROLLING_WINDOWS, CATEGORICAL_COLS
from app.ml.demand import ensemble as ens

_cache = {"clean": None, "feat_df": None, "feature_cols": None}

HISTORY_DAYS_FOR_CHART = 60
LSTM_SEQ_FEATURES = ["Daily_Consumption_Units", "day_of_week", "month", "doy_sin", "doy_cos"]
LSTM_LOOKBACK = 30


def _get_clean():
    if _cache["clean"] is None:
        _cache["clean"] = load_clean_dataset()
    return _cache["clean"]


def _get_features():
    if _cache["feat_df"] is None:
        feat_df, feature_cols = build_feature_table(_get_clean())
        _cache["feat_df"] = feat_df
        _cache["feature_cols"] = feature_cols
    return _cache["feat_df"], _cache["feature_cols"]


def catalog() -> dict:
    clean = _get_clean()
    drugs = (clean[["Drug_ID", "Drug_Name", "Category"]]
             .drop_duplicates()
             .sort_values("Drug_Name")
             .to_dict(orient="records"))
    regions = sorted(clean["Region"].unique().tolist())
    return {"drugs": drugs, "regions": regions, "modelsAvailable": ens.models_available()}


def _build_lstm_window(series_df: pd.DataFrame) -> np.ndarray:
    tail = series_df.sort_values("Date").tail(LSTM_LOOKBACK)
    return tail[LSTM_SEQ_FEATURES].to_numpy(dtype=float)


def _recursive_forecast(drug_id: str, region: str, days_ahead: int) -> dict:
    feat_df, feature_cols = _get_features()
    clean = _get_clean()

    series = clean[(clean["Drug_ID"] == drug_id) & (clean["Region"] == region)].sort_values("Date")
    if series.empty:
        return None

    weights = ens.get_weights()
    available = ens.models_available()

    # Working copy of raw history we extend day by day with each model's own prediction.
    working = series[["Date", "Daily_Consumption_Units"]].copy()

    per_model_daily = {name: [] for name in ["rf", "xgboost", "lstm"] if available.get(name)}
    ensemble_daily = []
    forecast_dates = []

    last_date = series["Date"].max()

    for step in range(1, days_ahead + 1):
        next_date = last_date + pd.Timedelta(days=step)
        forecast_dates.append(next_date)

        # --- Build flat features (for RF/XGBoost) from `working` history so far ---
        tmp = working.copy()
        tmp["Drug_ID"], tmp["Region"] = drug_id, region
        tmp["Category"] = series["Category"].iloc[0]
        # append a placeholder row for the day being predicted so lag/rolling
        # features referencing "yesterday" resolve correctly
        placeholder = pd.DataFrame([{
            "Date": next_date, "Daily_Consumption_Units": np.nan,
            "Drug_ID": drug_id, "Region": region, "Category": series["Category"].iloc[0],
        }])
        tmp = pd.concat([tmp, placeholder], ignore_index=True).sort_values("Date")

        grp = tmp.groupby(["Drug_ID", "Region"], group_keys=False)
        row = {}
        for lag in LAG_DAYS:
            shifted = grp["Daily_Consumption_Units"].shift(lag)
            row[f"lag_{lag}"] = shifted.iloc[-1]
        for window in ROLLING_WINDOWS:
            rolling_mean = grp["Daily_Consumption_Units"].apply(lambda s: s.shift(1).rolling(window).mean())
            rolling_std = grp["Daily_Consumption_Units"].apply(lambda s: s.shift(1).rolling(window).std())
            row[f"rolling_mean_{window}"] = rolling_mean.iloc[-1]
            row[f"rolling_std_{window}"] = rolling_std.iloc[-1]
        row["day_of_week"] = next_date.dayofweek
        row["week_of_year"] = int(next_date.isocalendar()[1])
        row["month"] = next_date.month
        doy = next_date.dayofyear
        row["doy_sin"] = np.sin(2 * np.pi * doy / 365)
        row["doy_cos"] = np.cos(2 * np.pi * doy / 365)
        row["days_since_start"] = (next_date - series["Date"].min()).days
        row["demand_trend"] = (row["rolling_mean_7"] / row["rolling_mean_30"]
                                if row.get("rolling_mean_30") else np.nan)
        cat_source = feat_df[(feat_df["Drug_ID"] == drug_id) & (feat_df["Region"] == region)]
        for col in CATEGORICAL_COLS:
            code_col = f"{col}_code"
            row[code_col] = cat_source[code_col].iloc[0] if not cat_source.empty else 0
        for c in feature_cols:
            if c not in row or pd.isna(row[c]):
                row[c] = 0.0

        lstm_seq = None
        if available.get("lstm"):
            window_df = working.tail(LSTM_LOOKBACK).copy()
            if len(window_df) == LSTM_LOOKBACK:
                window_df["day_of_week"] = window_df["Date"].dt.dayofweek
                window_df["month"] = window_df["Date"].dt.month
                wdoy = window_df["Date"].dt.dayofyear
                window_df["doy_sin"] = np.sin(2 * np.pi * wdoy / 365)
                window_df["doy_cos"] = np.cos(2 * np.pi * wdoy / 365)
                lstm_seq = window_df[LSTM_SEQ_FEATURES].to_numpy(dtype=float)

        result = ens.predict_one(row, lstm_sequence=lstm_seq)

        for name in per_model_daily:
            if name in result["models"]:
                per_model_daily[name].append(round(result["models"][name], 2))
            else:
                per_model_daily[name].append(None)
        ensemble_daily.append(result["ensemble"])

        # Extend working history with the ENSEMBLE prediction so the next
        # step's lag features are built on our best estimate so far.
        next_value = result["ensemble"] if result["ensemble"] is not None else 0.0
        working = pd.concat([working, pd.DataFrame([{"Date": next_date, "Daily_Consumption_Units": next_value}])],
                             ignore_index=True)

    return {
        "forecastDates": [d.strftime("%Y-%m-%d") for d in forecast_dates],
        "perModel": per_model_daily,
        "ensemble": ensemble_daily,
        "weightsUsed": {k: weights.get(k, 0) for k in per_model_daily},
    }


def forecast_series(drug_id: str, region: str, days_ahead: int = 7) -> dict:
    clean = _get_clean()
    series = clean[(clean["Drug_ID"] == drug_id) & (clean["Region"] == region)].sort_values("Date")
    if series.empty:
        return {"available": False, "reason": f"No history for Drug_ID={drug_id}, Region={region}"}

    history = series.tail(HISTORY_DAYS_FOR_CHART)
    history_points = [
        {"date": row["Date"].strftime("%Y-%m-%d"), "actual": round(float(row["Daily_Consumption_Units"]), 1)}
        for _, row in history.iterrows()
    ]

    fc = _recursive_forecast(drug_id, region, days_ahead)
    if fc is None:
        return {"available": False, "reason": "Could not build forecast."}

    drug_name = series["Drug_Name"].iloc[0]
    return {
        "available": True,
        "drugId": drug_id, "drugName": drug_name, "region": region,
        "asOfDate": str(series["Date"].max().date()),
        "history": history_points,
        "forecastDates": fc["forecastDates"],
        "forecast": {
            "rf": fc["perModel"].get("rf"),
            "xgboost": fc["perModel"].get("xgboost"),
            "lstm": fc["perModel"].get("lstm"),
            "ensemble": fc["ensemble"],
        },
        "weightsUsed": fc["weightsUsed"],
        "forecastTotalNextPeriod": round(sum(v for v in fc["ensemble"] if v is not None), 1),
        "modelsAvailable": ens.models_available(),
    }
