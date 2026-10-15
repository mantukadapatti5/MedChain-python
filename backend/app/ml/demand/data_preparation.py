"""
Cleans module5_drug_consumption_history.csv into a reliable training table
for the vendor demand-forecasting subsystem (LSTM + Random Forest + XGBoost).

Never modifies the original CSV -- pure raw -> clean pipeline, safe to
re-run any time the source file changes.

Known issues in the supplied file that this fixes:
  - A handful of trailing rows are corrupted: `Drug_ID` holds a malformed
    composite string (e.g. "DRUG|Amoxicillin 250mg|Ahmedabad") instead of a
    clean ID, the region value has leaked into Category, and most other
    columns are null on those rows. Dropped, not repaired.
  - One exact duplicate row.
  - Dates arrive as plain strings needing real parsing before any
    time-based feature or chronological split can be trusted.
"""
from pathlib import Path

import pandas as pd

RAW_COLUMNS = [
    "Date", "Drug_ID", "Drug_Name", "Category", "Region", "Daily_Consumption_Units",
    "Weekday", "Month", "Year", "Quarter", "Season", "Is_Weekend",
    "Stockout_Event", "Reorder_Triggered", "Moving_Avg_7Day",
]

VALID_DRUG_ID_RE = r"^DRG\d{4}$"


def load_and_clean(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    missing = set(RAW_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Dataset is missing expected columns: {missing}")

    before = len(df)

    df = df[df["Drug_ID"].astype(str).str.match(VALID_DRUG_ID_RE, na=False)].copy()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])

    df = df.drop_duplicates()
    df = df.drop_duplicates(subset=["Date", "Drug_ID", "Region"], keep="first")

    for col in ["Drug_ID", "Drug_Name", "Category", "Region", "Weekday", "Quarter", "Season"]:
        df[col] = df[col].astype(str).str.strip()

    numeric_cols = ["Daily_Consumption_Units", "Month", "Year", "Moving_Avg_7Day"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Daily_Consumption_Units", "Month", "Year"])

    for col in ["Is_Weekend", "Stockout_Event", "Reorder_Triggered"]:
        s = df[col].astype(str).str.strip().str.lower()
        s = s.map({"yes": "1", "no": "0"}).fillna(s)  # leaves already-numeric strings untouched
        df[col] = pd.to_numeric(s, errors="coerce")
    df = df.dropna(subset=["Is_Weekend", "Stockout_Event", "Reorder_Triggered"])
    for col in ["Is_Weekend", "Stockout_Event", "Reorder_Triggered"]:
        df[col] = df[col].astype(int)

    df = df.sort_values(["Drug_ID", "Region", "Date"]).reset_index(drop=True)

    after = len(df)
    print(f"[demand.data_preparation] {before} raw rows -> {after} clean rows "
          f"({before - after} dropped: malformed IDs, bad dates, duplicates, or nulls)")

    return df


CSV_FILENAME = "module5_drug_consumption_history.csv"


def data_dir() -> Path:
    """Reuses config.DATA_DIR (overridable via the DATA_DIR env var) so this
    resolves correctly both locally and inside Docker -- see the note in
    app/config.py about BASE_DIR breaking under the backend's Docker build
    context. New-dataset CSVs live in DATA_DIR/new_dataset."""
    from app.config import DATA_DIR
    return DATA_DIR / "new_dataset"


def load_clean_dataset() -> pd.DataFrame:
    return load_and_clean(data_dir() / CSV_FILENAME)
