"""
Shortage-risk classifier (Random Forest) - trained and evaluated on SIMULATED stock-outs.

IMPORTANT - what the labels are
-------------------------------
The project has no record of real stock-outs, and its sales history is synthetic
(see generate_dataset.py). The "shortage" label therefore comes from a simulation:

  * For every drug and every day ("origin"), a stock level is drawn at random,
    between 0.5 and 25 days of recent demand (so both safe and unsafe examples exist).
  * A random replenishment lead time of 2-7 days is drawn.
  * Label = 1 if the (synthetic) demand of the NEXT  lead_time + 7  days is larger than
    that stock, i.e. the stock would run out before a replenishment plus a 7-day safety
    window could be covered. Otherwise 0.

The model only sees information available at the origin day (stock, recent demand,
trend, volatility, lead time); the label uses FUTURE demand, so the model has to anticipate
it. But the ground truth is still a simulation - results show how well the model
reproduces that simulated outcome, NOT how well it predicts real shortages.

Because the label is mostly "days of supply < lead time + 7", a transparent rule on the same
inputs is a strong baseline; the report always shows it next to the Random Forest, together
with a majority-class baseline, the class balance, and two harder tests:
  1. chronological hold-out with a gap (no label overlap between train and test), all drugs
  2. leave-one-drug-out (train on 6 drugs, test on the 7th)

The deployed model is refit on all examples after evaluation.
"""
import json
import random
from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score,
                             brier_score_loss, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)

from app.config import ML_ARTIFACT_DIR
from app.ml.shortage_features import FEATURE_NAMES, build_features

DATA_PATH = ML_ARTIFACT_DIR / "sales_history.json"
MODEL_PATH = ML_ARTIFACT_DIR / "shortage_model.joblib"
REPORT_PATH = ML_ARTIFACT_DIR / "shortage_training_report.json"

MIN_HISTORY_DAYS = 28
SAFETY_DAYS = 7
MAX_LEAD_DAYS = 7
MAX_HORIZON_DAYS = MAX_LEAD_DAYS + SAFETY_DAYS      # label looks at most this far into the future
SCENARIOS_PER_ORIGIN = 3
DAYS_OF_SUPPLY_RANGE = (0.5, 25.0)
SEED = 20260831
DOS_INDEX = FEATURE_NAMES.index("daysOfSupply")
LEAD_INDEX = FEATURE_NAMES.index("leadTimeDays")


def _load_sales():
    if not DATA_PATH.exists():
        raise FileNotFoundError("sales_history.json not found. Run train_demand first.")
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def build_examples(rows: list, seed: int = SEED) -> list:
    """Returns [{drug, date, features, target}], one entry per (drug, day, scenario)."""
    by_drug = {}
    for r in rows:
        by_drug.setdefault(r["drugName"], []).append(r)
    rand = random.Random(seed)
    examples = []

    for drug, drug_rows in by_drug.items():
        drug_rows.sort(key=lambda r: r["date"])
        qty = [float(r["qty"]) for r in drug_rows]
        n = len(qty)
        for i in range(MIN_HISTORY_DAYS, n - MAX_HORIZON_DAYS):
            history = qty[:i]
            avg = _mean(history[-7:])
            if avg <= 0:
                continue
            forecast = _mean(history[-14:]) * 7          # naive demand forecast from PAST data only
            for _ in range(SCENARIOS_PER_ORIGIN):
                coverage = rand.uniform(*DAYS_OF_SUPPLY_RANGE)
                stock = max(1, round(avg * coverage))
                lead_time_days = 2 + int(rand.random() * (MAX_LEAD_DAYS - 1))
                horizon = lead_time_days + SAFETY_DAYS
                future_demand = sum(qty[i:i + horizon])
                examples.append({
                    "drug": drug,
                    "date": drug_rows[i]["date"],
                    "features": build_features(stock, history, forecast, lead_time_days),
                    "target": 1 if future_demand > stock else 0,
                })
    return examples


def _new_model():
    return RandomForestClassifier(n_estimators=100, max_depth=8, min_samples_leaf=10, max_features=0.7,
                                  random_state=4242, n_jobs=-1)


def _rule_predict(X):
    """Transparent baseline: shortage if days of supply < lead time + safety window."""
    return (X[:, DOS_INDEX] < X[:, LEAD_INDEX] + SAFETY_DAYS).astype(int)


def _metrics(y_true, y_pred, proba=None) -> dict:
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    out = {
        "n": int(len(y_true)),
        "positiveRate": round(float(y_true.mean()), 4) if len(y_true) else 0.0,
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "balancedAccuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "confusionMatrix": {"truePositive": int(tp), "trueNegative": int(tn),
                            "falsePositive": int(fp), "falseNegative": int(fn)},
    }
    if proba is not None and len(set(y_true.tolist())) == 2:
        out["rocAuc"] = round(float(roc_auc_score(y_true, proba)), 4)
        out["prAuc"] = round(float(average_precision_score(y_true, proba)), 4)
        out["brierScore"] = round(float(brier_score_loss(y_true, proba)), 4)
    return out


def _arrays(examples):
    X = np.array([e["features"] for e in examples], dtype=float)
    y = np.array([e["target"] for e in examples], dtype=int)
    return X, y


def _compare(train_ex, test_ex) -> dict:
    """Fit a Random Forest on train_ex and compare it with the baselines on test_ex."""
    X_train, y_train = _arrays(train_ex)
    X_test, y_test = _arrays(test_ex)
    model = _new_model().fit(X_train, y_train)
    proba = model.predict_proba(X_test)[:, list(model.classes_).index(1)] if 1 in model.classes_ else np.zeros(len(y_test))
    majority = int(round(float(y_train.mean())))
    return {
        "randomForest": _metrics(y_test, model.predict(X_test), proba),
        "ruleBaseline_daysOfSupply_lt_leadTime_plus_7": _metrics(y_test, _rule_predict(X_test)),
        "majorityClassBaseline": _metrics(y_test, np.full(len(y_test), majority)),
    }


def evaluate(examples: list) -> dict:
    """Chronological hold-out (with a gap) and leave-one-drug-out evaluation."""
    dates = sorted({e["date"][:10] for e in examples})
    cutoff_date = dates[int(len(dates) * 0.8) - 1]
    embargo_end = (datetime.fromisoformat(cutoff_date) + timedelta(days=MAX_HORIZON_DAYS)).date().isoformat()
    train_ex = [e for e in examples if e["date"][:10] <= cutoff_date]
    test_ex = [e for e in examples if e["date"][:10] > embargo_end]

    chrono = _compare(train_ex, test_ex)
    chrono["trainRows"], chrono["testRows"] = len(train_ex), len(test_ex)
    chrono["trainPositiveRate"] = round(float(np.mean([e["target"] for e in train_ex])), 4)
    chrono["trainDates"] = f"{dates[0]} .. {cutoff_date}"
    chrono["testDates"] = f"after {embargo_end} (gap of {MAX_HORIZON_DAYS} days so no label overlaps training)"

    drugs = sorted({e["drug"] for e in examples})
    per_drug = {}
    for drug in drugs:
        res = _compare([e for e in examples if e["drug"] != drug], [e for e in examples if e["drug"] == drug])
        per_drug[drug] = {"randomForest": res["randomForest"],
                          "ruleBaseline": res["ruleBaseline_daysOfSupply_lt_leadTime_plus_7"]}

    def summarize(key, metric):
        vals = [per_drug[d][key][metric] for d in drugs if metric in per_drug[d][key]]
        return {"mean": round(float(np.mean(vals)), 4), "min": round(float(np.min(vals)), 4),
                "max": round(float(np.max(vals)), 4)}

    lodo = {
        "drugs": drugs,
        "randomForest": {m: summarize("randomForest", m) for m in ("f1", "balancedAccuracy", "rocAuc", "prAuc")},
        "ruleBaseline": {m: summarize("ruleBaseline", m) for m in ("f1", "balancedAccuracy")},
        "perDrug": per_drug,
    }
    return {"chronologicalHoldout": chrono, "leaveOneDrugOut": lodo}


def class_balance(examples) -> dict:
    return {
        "examples": len(examples),
        "shortageRate": round(float(np.mean([e["target"] for e in examples])), 4),
        "byDrug": {d: round(float(np.mean([e["target"] for e in examples if e["drug"] == d])), 4)
                   for d in sorted({e["drug"] for e in examples})},
    }


CAVEATS = [
    "Ground truth is SIMULATED: the 'shortage' label is computed from synthetic sales and randomly drawn stock levels, not from observed stock-outs.",
    "The sales history is synthetic (generate_dataset.py), so performance reflects the generator, not real demand.",
    "The label is largely determined by days of supply vs. lead time, so a simple rule is a strong baseline; the model adds value only through trend/volatility information.",
    "No validation on real pharmacy or hospital data has been done. Do not present these scores as validated real-world forecasting.",
]


def train():
    examples = build_examples(_load_sales())
    evaluation = evaluate(examples)

    # Deployed model: refit on every example after the evaluation above.
    X_all, y_all = _arrays(examples)
    model = _new_model().fit(X_all, y_all)
    joblib.dump(model, MODEL_PATH)

    report = {
        "trainedAt": datetime.now(timezone.utc).isoformat(),
        "method": "Random Forest Classifier (scikit-learn, 100 trees, max depth 8)",
        "groundTruth": "simulated",
        "validatedOnRealData": False,
        "dataSource": "synthetic sales history (generate_dataset.py) + randomly simulated stock levels",
        "labelDefinition": "1 if synthetic demand over the next (lead_time + 7) days exceeds the simulated stock; features use past data only",
        "datasetSize": len(examples),
        "classBalance": class_balance(examples),
        "splitStrategy": f"chronological hold-out (last 20% of dates) with a {MAX_HORIZON_DAYS}-day gap, plus leave-one-drug-out",
        "metrics": {
            # kept for backwards compatibility: Random Forest on the chronological hold-out
            "heldOutTest": evaluation["chronologicalHoldout"]["randomForest"],
            **evaluation,
        },
        "caveats": CAVEATS,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    r = train()
    chrono = r["metrics"]["chronologicalHoldout"]
    print(json.dumps({
        "shortageRate": r["classBalance"]["shortageRate"],
        "chronological": {k: {m: v[m] for m in ("accuracy", "balancedAccuracy", "f1", "rocAuc") if m in v}
                          for k, v in chrono.items() if isinstance(v, dict) and "accuracy" in v},
        "leaveOneDrugOut": r["metrics"]["leaveOneDrugOut"]["randomForest"],
    }, indent=2))
