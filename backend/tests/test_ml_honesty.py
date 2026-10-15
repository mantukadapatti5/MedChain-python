"""
Regression tests for the ML evaluation fixes (run from the backend folder):

    python -m pytest tests -q          # or:  python tests/test_ml_honesty.py

They guard against the problems a reviewer flagged: a degenerate shortage label, a model that says
"shortage" for everything, and an anomaly detector that is forced to flag records.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ml import anomaly_detector as ad          # noqa: E402
from app.ml import train_shortage as ts            # noqa: E402
from app.ml.shortage_features import build_features  # noqa: E402


def test_shortage_labels_are_not_degenerate():
    examples = ts.build_examples(ts._load_sales())
    rate = np.mean([e["target"] for e in examples])
    assert 0.25 < rate < 0.65, f"shortage label rate {rate:.2f} is degenerate"
    for drug in {e["drug"] for e in examples}:
        r = np.mean([e["target"] for e in examples if e["drug"] == drug])
        assert 0.15 < r < 0.80, f"{drug}: shortage rate {r:.2f}"


def test_chronological_test_set_has_both_classes_and_a_gap():
    ev = ts.evaluate(ts.build_examples(ts._load_sales()))["chronologicalHoldout"]
    m = ev["majorityClassBaseline"]
    assert 0.2 < m["positiveRate"] < 0.8, "test set must contain both classes"
    assert ev["randomForest"]["rocAuc"] > 0.5


def test_deployed_model_separates_safe_from_unsafe_stock():
    import joblib
    from app.config import ML_ARTIFACT_DIR
    model = joblib.load(ML_ARTIFACT_DIR / "shortage_model.joblib")
    history = [20, 22, 19, 21, 20, 23, 20] * 3
    col = list(model.classes_).index(1)
    low = model.predict_proba([build_features(20 * 1, history, 140, 5)])[0][col]
    high = model.predict_proba([build_features(20 * 365, history, 140, 5)])[0][col]
    assert low > 0.8, f"1 day of stock should be high risk, got {low:.2f}"
    assert high < 0.2, f"a year of stock should be low risk, got {high:.2f}"


def test_anomaly_scan_skips_tiny_tiers():
    items = [{"drugName": "X", "batch": "B1", "stock": 80, "reorderPoint": 20, "expiryDate": "2030-01-01"}] * 2
    assert ad.scan_inventory_with_isolation_forest(items, []) == []


def test_anomaly_detector_is_not_forced_to_flag_a_fixed_fraction():
    rng = np.random.default_rng(5)
    items = [{"drugName": "X", "batch": f"B{i}", "stock": 1000 + rng.normal(0, 20), "reorderPoint": 300,
              "expiryDate": "2030-01-01"} for i in range(100)]
    sales = [{"drugName": "X", "date": "2026-01-01", "qty": 50}] * 14
    flagged = sum(r["anomaly"] for r in ad.scan_inventory_with_isolation_forest(items, sales))
    assert flagged <= 10, f"{flagged} of 100 fault-free records flagged"


def test_anomaly_detector_finds_an_obvious_fault():
    rng = np.random.default_rng(6)
    items = [{"drugName": "X", "batch": f"B{i}", "stock": 1000 + rng.normal(0, 20), "reorderPoint": 300,
              "expiryDate": "2030-01-01"} for i in range(100)]
    items[0].update(stock=5, expiryDate="2026-10-20")   # nearly empty and about to expire
    sales = [{"drugName": "X", "date": "2026-01-01", "qty": 50}] * 14
    results = ad.scan_inventory_with_isolation_forest(items, sales)
    assert results[0]["anomaly"], f"obvious fault scored only {results[0]['score']}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
