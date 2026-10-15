"""Direct port of backend/ml/features.js. train/serve parity matters here —
training (train_demand.py) and inference (predict.py) MUST call this exact
same function so the model sees identically-shaped inputs in both places."""
import math
from datetime import date

FEATURE_NAMES = [
    "dayOfWeek", "month", "dayOfYearSin", "dayOfYearCos", "drugCategoryCode",
    "trendIndexYears", "lag7", "lag14", "rollingAvg7", "rollingAvg30",
]

CATEGORY_CODE = {
    "Analgesic": 0, "Antibiotic": 1, "Hormone": 2, "Rehydration": 3, "Antidiabetic": 4,
}


def _day_of_year(d: date) -> int:
    return (d - date(d.year, 1, 1)).days + 1


def _mean(arr):
    return sum(arr) / len(arr) if arr else 0


def compute_features(d: date, category: str, days_since_dataset_start: float, history: list) -> list:
    doy = _day_of_year(d)
    last7 = history[-7:]
    last30 = history[-30:]

    return [
        js_day_of_week(d),
        d.month,
        math.sin(2 * math.pi * doy / 365),
        math.cos(2 * math.pi * doy / 365),
        CATEGORY_CODE.get(category, 0),
        days_since_dataset_start / 365,
        history[-7] if len(history) >= 7 else _mean(last7),
        history[-14] if len(history) >= 14 else _mean(last30),
        _mean(last7),
        _mean(last30),
    ]


def js_day_of_week(d: date) -> int:
    """JS Date.getDay(): 0=Sunday..6=Saturday. Python's date.weekday() is
    0=Monday..6=Sunday, so this converts to match the original feature
    exactly (kept as a separate helper for clarity/testability)."""
    return (d.weekday() + 1) % 7
