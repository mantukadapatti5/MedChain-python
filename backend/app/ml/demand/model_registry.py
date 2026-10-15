"""Consolidated view of RF/XGBoost/LSTM training status + test metrics,
read from the metrics/*.json reports each train_*.py script writes."""
import json
from pathlib import Path

METRICS_DIR = Path(__file__).resolve().parent / "metrics"

REPORTS = {"rf": "rf.json", "xgboost": "xgboost.json", "lstm": "lstm.json"}


def get_registry() -> dict:
    registry = {}
    for name, fname in REPORTS.items():
        path = METRICS_DIR / fname
        if path.exists():
            report = json.loads(path.read_text())
            registry[name] = {
                "status": "trained",
                "algorithm": report.get("algorithm"),
                "trained_at": report.get("trained_at"),
                "test_metrics": report.get("metrics", {}).get("test"),
            }
        else:
            registry[name] = {"status": "not_trained"}

    weights_path = Path(__file__).resolve().parent / "artifacts" / "ensemble_weights.json"
    registry["ensemble_weights"] = (
        json.loads(weights_path.read_text())["weights"] if weights_path.exists() else {}
    )
    return registry


if __name__ == "__main__":
    print(json.dumps(get_registry(), indent=2))
