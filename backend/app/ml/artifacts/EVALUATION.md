# Model evaluation and limitations

Generated 2026-10-15 07:17 UTC by `python -m app.ml.evaluate_models`. The synthetic sales history is regenerated when the models are retrained, so shortage figures can move by about 0.01.

> **Status: every result below uses synthetic data and simulated or injected ground truth. None of it is validation on real-world data and it must not be presented as validated real-world forecasting or anomaly detection.**

## 1. Shortage-risk classifier (simulated stock-outs)

Label: 1 if synthetic demand over the next (lead time + 7) days exceeds a randomly drawn stock level. Class balance: 44.7% shortage (11298 examples). Features use past data only.

**Chronological hold-out** (2025-03-02 .. 2026-05-05 train; test after 2026-05-19 (gap of 14 days so no label overlaps training); n=1974):

| Method | Accuracy | Balanced acc. | F1 | ROC-AUC |
|---|---|---|---|---|
| Random Forest | 0.9605 | 0.9582 | 0.9547 | 0.9835 |
| Rule: days of supply < lead time + 7 | 0.9574 | 0.9559 | 0.9516 | - |
| Majority class | 0.5562 | 0.5 | 0.0 | - |

**Leave-one-drug-out** (train on 6 drugs, test on the 7th): Random Forest F1 mean 0.9536 (min 0.9153, max 0.9877); ROC-AUC mean 0.9804; rule baseline F1 mean 0.9543.

**Reading:** the Random Forest is only marginally better than the transparent rule on the same inputs, because the simulated label is mostly determined by days of supply versus lead time. The earlier version of this model reported 100% accuracy on a test set that contained only positive cases; that number was meaningless and has been removed.

## 2. Anomaly detection (Isolation Forest, unsupervised)

There are no labelled real inventory anomalies. The detector is therefore evaluated on a synthetic injected-fault benchmark (5% faults: imminent stock-out, severe overstock, near expiry; 30 random populations per size). This only shows the method can recover faults we defined ourselves.

Population of 260 records:

| Configuration | Precision | Recall | F1 | ROC-AUC | Flagged when there are NO faults |
|---|---|---|---|---|---|
| First version (raw features, forced 5-20% flag rate) | 0.121 | 0.121 | 0.121 | 0.876 | 5.0% |
| Current (log features, score >= 0.6) | 0.746 | 0.556 | 0.635 | 0.989 | 3.2% |

Other changes: tiers are scanned separately, tiers with fewer than 20 records are skipped, scores are not rescaled per scan, and flags are described as *review candidates*. The `reason` text is a rule-based description, not a model explanation. Even now, a fault-free population still produces some flags, so flags need human review.

## 3. Demand forecasting (Random Forest, XGBoost, and LSTM)

Chronological hold-out 2024-02-01 .. 2024-06-30 (30200 rows, 200 drug-region series), one day ahead (the application forecasts several days ahead recursively; that is not evaluated).

| Model / baseline | R2 | MAE | MAPE % |
|---|---|---|---|
| Random Forest | 0.841 | 67.1 | 7.59 |
| XGBoost | 0.842 | 66.4 | 7.48 |
| LSTM | 0.840 | 67.3 | 8.10 |
| Naive (yesterday) | 0.543 | 137.0 | 18.67 |
| Same weekday last week | 0.697 | 92.9 | 11.5 |
| Rolling mean 7 days | 0.71 | 121.4 | 16.58 |
| Rolling mean 30 days | 0.711 | 122.2 | 16.78 |

Per-drug R2 of the Random Forest: median 0.611 (min 0.556, max 0.714).
The pooled R2 above includes differences between drugs and regions; the median per-drug R2 is the more conservative figure (Random Forest 0.611 vs 0.261 for the 7-day rolling mean).
Fully balanced panel (every drug x region x day present) with sequential identifiers: the data appears synthetic and its origin is not documented. XGBoost and LSTM were trained separately on the same synthetic chronological hold-out; their scores are not validation on real-world data.

## 4. Suggested wording for the paper

**Data.** "All experiments use synthetic data generated for this study (sales/consumption histories, inventory records and blockchain events). No real pharmacy, hospital or distributor records were used. Results therefore characterise the behaviour of the methods in a controlled simulation and do not constitute validation on real-world data."

**Shortage risk.** "As real stock-out records are unavailable, shortage labels were simulated: a stock level was drawn at random and a shortage was recorded if the following lead-time-plus-7-day demand exceeded it. On a chronological hold-out with a gap, the Random Forest reached F1 = 0.9547 and ROC-AUC = 0.9835, compared with F1 = 0.9516 for a transparent days-of-supply rule, so the learned model offers little advantage over the rule in this setting."

**Anomaly detection.** "The Isolation Forest is used as an unsupervised screening aid; no ground-truth anomalies exist, so we do not claim detection accuracy. On a synthetic injected-fault benchmark it achieved ROC-AUC = 0.989 (precision 0.746, recall 0.556 at a score threshold of 0.6), while still flagging 3.2% of fault-free records. Flags are presented as candidates for human review."

**Demand forecasting.** "On a chronological hold-out the Random Forest achieved R2 = 0.841 and MAPE = 7.59% for one-day-ahead prediction, versus R2 = 0.697 for a same-weekday-last-week baseline; the median per-drug R2 was 0.611. Multi-day recursive forecasts were not evaluated, and the data are synthetic."

## 5. Limitations to state explicitly

- Synthetic data; origin and generating process of the consumption dataset are not documented.
- Simulated (shortage) and injected (anomaly) ground truth; no real stock-outs or real faults.
- Shortage label is mostly a function of days of supply versus lead time; a simple rule is competitive.
- Isolation Forest is unsupervised and flags a tail of records even in fault-free data.
- Demand: one-step-ahead evaluation only; single chronological split; no prediction intervals. The XGBoost and LSTM metrics are from separately trained models on the same synthetic hold-out and are not real-world validation.
- The blockchain is a single-process, hash-chained log on one server; it is not a distributed consensus ledger.
