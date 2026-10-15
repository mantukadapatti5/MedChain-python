"""
Honest evaluation of the three ML components. Run:

    cd backend && python -m app.ml.evaluate_models

Writes  app/ml/artifacts/evaluation_report.json  and  app/ml/artifacts/EVALUATION.md.

What this does and does NOT show
--------------------------------
There is no real-world ground truth in this project (no observed stock-outs, no labelled
inventory faults) and the sales data is synthetic. So:

  * Shortage   : evaluated against SIMULATED stock-outs, always next to simple baselines.
  * Anomaly    : evaluated on a synthetic INJECTED-FAULT benchmark (faults we define ourselves).
                 It shows the method can recover such faults, not that it finds real ones.
  * Demand     : evaluated on a chronological hold-out against naive baselines. The data is
                 synthetic/undocumented and the test is one-step-ahead.

None of these numbers are validation on real data and the paper must not present them as such.
"""
import contextlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from app.config import ML_ARTIFACT_DIR
from app.ml import anomaly_detector as ad
from app.ml import train_shortage as ts

REPORT_JSON = ML_ARTIFACT_DIR / "evaluation_report.json"
REPORT_MD = ML_ARTIFACT_DIR / "EVALUATION.md"


# --------------------------------------------------------------------------- anomaly benchmark
def _make_population(n, fault_rate, rng):
    """Synthetic inventory records of one tier with a known set of injected faults."""
    demand = np.exp(rng.normal(3.5, 0.9, n))
    days_supply = rng.uniform(12, 45, n)
    expiry = rng.uniform(120, 540, n)
    reorder = demand * rng.uniform(5, 10, n)
    labels = np.zeros(n, dtype=int)
    k = int(round(n * fault_rate))
    faulty = rng.choice(n, k, replace=False) if k else []
    for j, i in enumerate(faulty):
        labels[i] = 1
        kind = j % 3
        if kind == 0:
            days_supply[i] = rng.uniform(0.2, 3)       # imminent stock-out
        elif kind == 1:
            days_supply[i] = rng.uniform(100, 250)     # severe overstock
        else:
            expiry[i] = rng.uniform(1, 25)             # near expiry
    stock = demand * days_supply
    vectors = np.array([ad.feature_vector(stock[i], demand[i], reorder[i], expiry[i]) for i in range(n)])
    return vectors, labels


def _first_version_detector(vectors):
    """The original configuration: raw features and a forced 5-20% flag rate."""
    n = len(vectors)
    contamination = min(0.2, max(0.05, 3 / n))
    model = IsolationForest(n_estimators=80, max_samples=min(32, n), contamination=contamination, random_state=314159)
    model.fit(vectors)
    return (model.predict(vectors) == -1).astype(int), -model.score_samples(vectors)


def anomaly_benchmark(sizes=(260, 60), fault_rate=0.05, repetitions=30) -> dict:
    out = {"faultRate": fault_rate, "repetitions": repetitions, "faultTypes": ["imminent stock-out", "severe overstock", "near expiry"],
           "reviewThreshold": ad.REVIEW_THRESHOLD, "bySize": {}}
    thresholds = [0.55, 0.58, ad.REVIEW_THRESHOLD, 0.62, 0.65]
    for n in sizes:
        rows = {"firstVersion_raw_features_forced_flag_rate": []}
        for t in thresholds:
            rows[f"logFeatures_scoreAtLeast_{t}"] = []
        control = {k: [] for k in rows}
        for rep in range(repetitions):
            X, y = _make_population(n, fault_rate, np.random.default_rng(100 + rep))
            Xc, _ = _make_population(n, 0.0, np.random.default_rng(500 + rep))
            pred, score = _first_version_detector(X)
            rows["firstVersion_raw_features_forced_flag_rate"].append((precision_score(y, pred, zero_division=0), recall_score(y, pred), f1_score(y, pred, zero_division=0), roc_auc_score(y, score)))
            control["firstVersion_raw_features_forced_flag_rate"].append(float(_first_version_detector(Xc)[0].mean()))
            scores, scores_c = ad.score_population(X), ad.score_population(Xc)
            for t in thresholds:
                key = f"logFeatures_scoreAtLeast_{t}"
                pred = (scores >= t).astype(int)
                rows[key].append((precision_score(y, pred, zero_division=0), recall_score(y, pred), f1_score(y, pred, zero_division=0), roc_auc_score(y, scores)))
                control[key].append(float((scores_c >= t).mean()))
        out["bySize"][str(n)] = {
            key: {
                "precision": round(float(np.mean([r[0] for r in vals])), 3),
                "recall": round(float(np.mean([r[1] for r in vals])), 3),
                "f1": round(float(np.mean([r[2] for r in vals])), 3),
                "rocAuc": round(float(np.mean([r[3] for r in vals])), 3),
                "flaggedInFaultFreePopulation": round(float(np.mean(control[key])), 3),
            } for key, vals in rows.items()
        }
    return out


# --------------------------------------------------------------------------- demand baselines
def demand_baselines() -> dict:
    try:
        import joblib
        from sklearn.metrics import mean_absolute_error, r2_score
        from app.ml.demand import features, split
        from app.ml.demand.data_preparation import load_clean_dataset

        with contextlib.redirect_stdout(io.StringIO()):
            df = load_clean_dataset()
            built = features.build_feature_table(df)
            _, _, test = split.chronological_split(built[0] if isinstance(built, tuple) else built)
        artifact = joblib.load(ML_ARTIFACT_DIR.parent / "demand" / "artifacts" / "rf.joblib")
        y = test["Daily_Consumption_Units"].values

        def mape(a, p):
            m = a > 0
            return float(100 * np.mean(np.abs(a[m] - p[m]) / a[m]))

        methods = {
            "randomForest": artifact["model"].predict(test[artifact["feature_cols"]]),
            "naive_yesterday": test["lag_1"].values,
            "seasonalNaive_sameWeekdayLastWeek": test["lag_7"].values,
            "rollingMean7": test["rolling_mean_7"].values,
            "rollingMean30": test["rolling_mean_30"].values,
        }
        result = {
            "testPeriod": f"{test.Date.min().date()} .. {test.Date.max().date()}",
            "rows": int(len(test)),
            "series": int(test.groupby(["Drug_ID", "Region"]).ngroups),
            "horizon": "one day ahead (the application forecasts several days ahead recursively; that is not evaluated)",
            "methods": {k: {"r2": round(float(r2_score(y, p)), 3), "mae": round(float(mean_absolute_error(y, p)), 1),
                            "mape": round(mape(y, p), 2)} for k, p in methods.items()},
        }
        per_drug = []
        for _, g in test.assign(p=methods["randomForest"], b=methods["rollingMean7"]).groupby("Drug_Name"):
            per_drug.append((r2_score(g.Daily_Consumption_Units, g.p), r2_score(g.Daily_Consumption_Units, g.b)))
        result["perDrugR2_randomForest"] = {"median": round(float(np.median([a for a, _ in per_drug])), 3),
                                            "min": round(float(min(a for a, _ in per_drug)), 3),
                                            "max": round(float(max(a for a, _ in per_drug)), 3)}
        result["perDrugR2_rollingMean7"] = {"median": round(float(np.median([b for _, b in per_drug])), 3)}
        result["dataNote"] = ("Fully balanced panel (every drug x region x day present) with sequential identifiers: "
                              "the data appears synthetic and its origin is not documented.")
        return result
    except Exception as exc:  # data folder not available, etc.
        return {"skipped": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- markdown
def _row(label, m, extra=""):
    return f"| {label} | {m.get('accuracy', '')} | {m.get('balancedAccuracy', '')} | {m.get('f1', '')} | {m.get('rocAuc', '-')} |{extra}"


def build_markdown(rep: dict) -> str:
    sh = rep["shortage"]
    ch = sh["metrics"]["chronologicalHoldout"]
    lodo = sh["metrics"]["leaveOneDrugOut"]
    rf = ch["randomForest"]
    rule = ch["ruleBaseline_daysOfSupply_lt_leadTime_plus_7"]
    maj = ch["majorityClassBaseline"]
    an = rep["anomaly"]
    sizes = an["bySize"]
    big = sizes[str(max(int(k) for k in sizes))]
    thr = f"logFeatures_scoreAtLeast_{an['reviewThreshold']}"
    old = big["firstVersion_raw_features_forced_flag_rate"]
    new = big[thr]
    dm = rep["demand"]
    trained_demand_models = {}
    for name, filename in [("XGBoost", "xgboost.json"), ("LSTM", "lstm.json")]:
        path = Path(__file__).resolve().parent / "demand" / "metrics" / filename
        if path.exists():
            trained_demand_models[name] = json.loads(path.read_text(encoding="utf-8"))["metrics"]["test"]

    lines = [
        "# Model evaluation and limitations",
        "",
        f"Generated {rep['generatedAt']} by `python -m app.ml.evaluate_models`. "
        "The synthetic sales history is regenerated when the models are retrained, so shortage figures can move by about 0.01.",
        "",
        "> **Status: every result below uses synthetic data and simulated or injected ground truth. "
        "None of it is validation on real-world data and it must not be presented as validated real-world forecasting "
        "or anomaly detection.**",
        "",
        "## 1. Shortage-risk classifier (simulated stock-outs)",
        "",
        f"Label: 1 if synthetic demand over the next (lead time + 7) days exceeds a randomly drawn stock level. "
        f"Class balance: {sh['classBalance']['shortageRate']*100:.1f}% shortage ({sh['classBalance']['examples']} examples). "
        f"Features use past data only.",
        "",
        f"**Chronological hold-out** ({ch['trainDates']} train; test {ch['testDates']}; n={ch['testRows']}):",
        "",
        "| Method | Accuracy | Balanced acc. | F1 | ROC-AUC |",
        "|---|---|---|---|---|",
        _row("Random Forest", rf),
        _row("Rule: days of supply < lead time + 7", rule),
        _row("Majority class", maj),
        "",
        f"**Leave-one-drug-out** (train on 6 drugs, test on the 7th): Random Forest F1 mean {lodo['randomForest']['f1']['mean']} "
        f"(min {lodo['randomForest']['f1']['min']}, max {lodo['randomForest']['f1']['max']}); "
        f"ROC-AUC mean {lodo['randomForest']['rocAuc']['mean']}; rule baseline F1 mean {lodo['ruleBaseline']['f1']['mean']}.",
        "",
        "**Reading:** the Random Forest is only marginally better than the transparent rule on the same inputs, because the "
        "simulated label is mostly determined by days of supply versus lead time. The earlier version of this model reported "
        "100% accuracy on a test set that contained only positive cases; that number was meaningless and has been removed.",
        "",
        "## 2. Anomaly detection (Isolation Forest, unsupervised)",
        "",
        "There are no labelled real inventory anomalies. The detector is therefore evaluated on a synthetic injected-fault "
        f"benchmark ({int(an['faultRate']*100)}% faults: imminent stock-out, severe overstock, near expiry; "
        f"{an['repetitions']} random populations per size). This only shows the method can recover faults we defined ourselves.",
        "",
        f"Population of {max(int(k) for k in sizes)} records:",
        "",
        "| Configuration | Precision | Recall | F1 | ROC-AUC | Flagged when there are NO faults |",
        "|---|---|---|---|---|---|",
        f"| First version (raw features, forced 5-20% flag rate) | {old['precision']} | {old['recall']} | {old['f1']} | {old['rocAuc']} | {old['flaggedInFaultFreePopulation']*100:.1f}% |",
        f"| Current (log features, score >= {an['reviewThreshold']}) | {new['precision']} | {new['recall']} | {new['f1']} | {new['rocAuc']} | {new['flaggedInFaultFreePopulation']*100:.1f}% |",
        "",
        "Other changes: tiers are scanned separately, tiers with fewer than 20 records are skipped, scores are not rescaled per scan, "
        "and flags are described as *review candidates*. The `reason` text is a rule-based description, not a model explanation. "
        "Even now, a fault-free population still produces some flags, so flags need human review.",
        "",
        "## 3. Demand forecasting",
        "",
    ]
    if "skipped" in dm:
        lines.append(f"Not evaluated in this run ({dm['skipped']}).")
    else:
        lines += [
            f"Chronological hold-out {dm['testPeriod']} ({dm['rows']} rows, {dm['series']} drug-region series), {dm['horizon']}.",
            "",
            "| Model / baseline | R2 | MAE | MAPE % |",
            "|---|---|---|---|",
        ]
        names = {"randomForest": "Random Forest", "naive_yesterday": "Naive (yesterday)",
                 "seasonalNaive_sameWeekdayLastWeek": "Same weekday last week",
                 "rollingMean7": "Rolling mean 7 days", "rollingMean30": "Rolling mean 30 days"}
        for k, v in dm["methods"].items():
            lines.append(f"| {names[k]} | {v['r2']} | {v['mae']} | {v['mape']} |")
        for name, metrics in trained_demand_models.items():
            lines.append(f"| {name} | {metrics['r2']} | {metrics['mae']} | {metrics['mape']} |")
        lines += [
            "",
            f"Per-drug R2 of the Random Forest: median {dm['perDrugR2_randomForest']['median']} "
            f"(min {dm['perDrugR2_randomForest']['min']}, max {dm['perDrugR2_randomForest']['max']}).",
            "The pooled R2 above includes differences between drugs and regions; the median per-drug R2 is the more conservative figure "
            f"(Random Forest {dm['perDrugR2_randomForest']['median']} vs {dm['perDrugR2_rollingMean7']['median']} for the 7-day rolling mean).",
            f"{dm['dataNote']} XGBoost and LSTM, where listed, were trained separately on the same synthetic chronological split.",
        ]
        if not trained_demand_models:
            lines.append("XGBoost and LSTM are not trained in this environment; their rows are omitted.")
    lines += [
        "",
        "## 4. Suggested wording for the paper",
        "",
        "**Data.** \"All experiments use synthetic data generated for this study (sales/consumption histories, inventory records and "
        "blockchain events). No real pharmacy, hospital or distributor records were used. Results therefore characterise the behaviour "
        "of the methods in a controlled simulation and do not constitute validation on real-world data.\"",
        "",
        f"**Shortage risk.** \"As real stock-out records are unavailable, shortage labels were simulated: a stock level was drawn at random "
        f"and a shortage was recorded if the following lead-time-plus-7-day demand exceeded it. On a chronological hold-out with a gap, the "
        f"Random Forest reached F1 = {rf['f1']} and ROC-AUC = {rf.get('rocAuc')}, compared with F1 = {rule['f1']} for a transparent "
        f"days-of-supply rule, so the learned model offers little advantage over the rule in this setting.\"",
        "",
        f"**Anomaly detection.** \"The Isolation Forest is used as an unsupervised screening aid; no ground-truth anomalies exist, so we do not claim "
        f"detection accuracy. On a synthetic injected-fault benchmark it achieved ROC-AUC = {new['rocAuc']} (precision {new['precision']}, "
        f"recall {new['recall']} at a score threshold of {an['reviewThreshold']}), while still flagging {new['flaggedInFaultFreePopulation']*100:.1f}% "
        f"of fault-free records. Flags are presented as candidates for human review.\"",
        "",
    ]
    if "skipped" not in dm:
        lines += [
            f"**Demand forecasting.** \"On a chronological hold-out the Random Forest achieved R2 = {dm['methods']['randomForest']['r2']} and "
            f"MAPE = {dm['methods']['randomForest']['mape']}% for one-day-ahead prediction, versus R2 = {dm['methods']['seasonalNaive_sameWeekdayLastWeek']['r2']} "
            f"for a same-weekday-last-week baseline; the median per-drug R2 was {dm['perDrugR2_randomForest']['median']}. Multi-day recursive forecasts were not evaluated, and the data are synthetic.\"",
            "",
        ]
    lines += [
        "## 5. Limitations to state explicitly",
        "",
        "- Synthetic data; origin and generating process of the consumption dataset are not documented.",
        "- Simulated (shortage) and injected (anomaly) ground truth; no real stock-outs or real faults.",
        "- Shortage label is mostly a function of days of supply versus lead time; a simple rule is competitive.",
        "- Isolation Forest is unsupervised and flags a tail of records even in fault-free data.",
        "- Demand: one-step-ahead evaluation only; single chronological split; no prediction intervals.",
        "- The blockchain is a single-process, hash-chained log on one server; it is not a distributed consensus ledger.",
        "",
    ]
    return "\n".join(lines)


def main():
    examples = ts.build_examples(ts._load_sales())
    shortage = {"classBalance": ts.class_balance(examples), "metrics": ts.evaluate(examples)}
    report = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "status": "synthetic data; simulated/injected ground truth; not validated on real data",
        "shortage": shortage,
        "anomaly": anomaly_benchmark(),
        "demand": demand_baselines(),
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_MD.write_text(build_markdown(report), encoding="utf-8")
    print(f"wrote {REPORT_JSON}\nwrote {REPORT_MD}")


if __name__ == "__main__":
    main()
