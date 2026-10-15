"""Direct port of backend/utils/datasetLoader.js — reads the 6 CSVs, with
in-process caching keyed on file mtimes, same as the original."""
import os
import pandas as pd

from app.config import DATASET_DIR

FILES = {
    "sales": "1_sales_demand_history.csv",
    "inventory": "2_inventory_batch.csv",
    "hospitalDemand": "3_hospital_client_demand.csv",
    "shipments": "4_shipment_history.csv",
    "coldChain": "5_cold_chain.csv",
    "suppliers": "6_supplier_vendor_performance.csv",
}

# The CSVs use short region names ("East", "West", ...) while the live,
# Postgres-seeded app data (clients, distributor inventory, the `regions`
# table) uses "East Zone", "West Zone", etc. Normalizing here means every
# `region` field anywhere in the app — whether it originated from a CSV or
# from the database — uses the same string, so the two can be safely
# compared/joined instead of silently never matching.
_SHORT_REGIONS = {"North", "South", "East", "West", "Central"}


def _normalize_region(value):
    if isinstance(value, str) and value in _SHORT_REGIONS:
        return f"{value} Zone"
    return value


_cache = None
_cache_stamp = 0


def _read_csv(filename: str) -> list:
    path = DATASET_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {filename}")
    df = pd.read_csv(path)
    df = df.where(pd.notnull(df), None)
    rows = df.to_dict(orient="records")
    for row in rows:
        if "region" in row:
            row["region"] = _normalize_region(row["region"])
    return rows


def load_datasets(force: bool = False) -> dict:
    global _cache, _cache_stamp
    stamp = max((os.path.getmtime(DATASET_DIR / f) for f in FILES.values() if (DATASET_DIR / f).exists()), default=0)
    if not force and _cache is not None and stamp == _cache_stamp:
        return _cache
    _cache = {key: _read_csv(filename) for key, filename in FILES.items()}
    _cache_stamp = stamp
    return _cache


def dataset_summary() -> dict:
    data = load_datasets()
    return {key: {"rows": len(rows), "columns": list(rows[0].keys()) if rows else []} for key, rows in data.items()}
