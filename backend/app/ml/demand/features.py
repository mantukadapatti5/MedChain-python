"""
Feature engineering shared by the Random Forest and XGBoost demand models
(the LSTM uses its own raw-sequence representation, see train_lstm.py).

Every drug/region combination is its own time series. Lag and rolling
features are always computed strictly from the past relative to the row
being predicted -- no leakage.
"""
import numpy as np
import pandas as pd

CATEGORICAL_COLS = ["Drug_ID", "Region", "Category"]
LAG_DAYS = [1, 3, 7, 14, 28]
ROLLING_WINDOWS = [7, 14, 30]


def build_feature_table(df: pd.DataFrame):
    df = df.copy()
    grp = df.groupby(["Drug_ID", "Region"], group_keys=False)

    for lag in LAG_DAYS:
        df[f"lag_{lag}"] = grp["Daily_Consumption_Units"].shift(lag)

    for window in ROLLING_WINDOWS:
        df[f"rolling_mean_{window}"] = grp["Daily_Consumption_Units"].apply(
            lambda s: s.shift(1).rolling(window).mean()
        )
        df[f"rolling_std_{window}"] = grp["Daily_Consumption_Units"].apply(
            lambda s: s.shift(1).rolling(window).std()
        )

    df["day_of_week"] = df["Date"].dt.dayofweek
    df["week_of_year"] = df["Date"].dt.isocalendar().week.astype(int)
    df["month"] = df["Date"].dt.month
    doy = df["Date"].dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365)
    df["days_since_start"] = grp["Date"].transform(lambda s: (s - s.min()).dt.days)
    df["demand_trend"] = df["rolling_mean_7"] / df["rolling_mean_30"].replace(0, np.nan)

    for col in CATEGORICAL_COLS:
        df[f"{col}_code"] = df[col].astype("category").cat.codes

    feature_cols = (
        [f"lag_{l}" for l in LAG_DAYS]
        + [f"rolling_mean_{w}" for w in ROLLING_WINDOWS]
        + [f"rolling_std_{w}" for w in ROLLING_WINDOWS]
        + ["day_of_week", "week_of_year", "month", "doy_sin", "doy_cos",
           "days_since_start", "demand_trend"]
        + [f"{col}_code" for col in CATEGORICAL_COLS]
    )

    before = len(df)
    df = df.dropna(subset=feature_cols + ["Daily_Consumption_Units"]).reset_index(drop=True)
    print(f"[demand.features] {before} rows -> {len(df)} rows after dropping warm-up rows")

    return df, feature_cols
