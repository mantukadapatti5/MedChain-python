# Changes applied in this version

## 1. Drug-availability check when a request is raised
- **Distributor -> Vendor** (`POST /api/distributor/stock-requests`): the drug must be in the
  Vendor inventory list with stock > 0. Otherwise the request is NOT created and the user gets a pop-up, e.g.
  `Drug "Aspirin" is not available in the Vendor inventory list, so the request was not sent. Available drugs: ...`
  (or "... is listed in the Vendor inventory but is currently out of stock").
- **Client -> Distributor** (`POST /api/client/requests`): the drug must be in the Distributor inventory for the
  client's own region (the same pool the Distributor's FEFO approval uses). Otherwise the request is NOT created,
  e.g. `"Insulin" is not available in the Distributor stock for North Zone ... It is currently available in: Central Zone, East Zone, South Zone.`
- When the drug IS available, the success pop-up says so and shows the units in stock.
- Matching ignores upper/lower case and extra spaces, and the stored request uses the inventory's exact drug
  name (FEFO allocation needs an exact name match, so "amoxicillin" now works like "Amoxicillin").
- Quantity must be a number greater than zero.
- New file: `backend/app/services/availability.py`. Edited: `routers/distributor.py`, `routers/client.py`.

## 2. Frontend fixes needed for the pop-ups to work
- `src/api/api.js` now reads FastAPI's `detail` error field (it only read `error` before, so every backend
  message was replaced by "Request failed with status 400"). Added `api.patch` and `api.delete`
  (`Notifications.jsx` calls `api.patch`, which did not exist, so "Mark read" crashed).
- `ToastContext.jsx`: error pop-ups stay 8 seconds (was 4.2) so the longer messages can be read.
- Success pop-ups in `DistributorRequests.jsx`, `ClientRequests.jsx`, `ClientRequestMedicine.jsx`.

## 3. Other fixes found while checking every page
- "Central Zone" was missing from the Distributor request / inventory / client / sales region lists, although
  the seed data has a Central Zone client and Central Zone stock.
- "Run ML Anomaly Scan" (`AdminAnomalies.jsx`) only ran the rule-based scan; it now runs the Isolation Forest
  scan first and then the rule checks.

## 5. Admin verification of newly added clients (new feature)
**Flow:** Distributor > Clients > *Add Client* -> client is saved as **pending** and cannot sign in ->
the Admin gets a notification + a banner on the System Health page -> Admin opens
**Client Verification** (new item in the Admin sidebar) -> **Approve** or **Reject (reason required)**.
- Approved: the client can sign in and use the Client Portal; the client and the distributor are notified.
- Rejected: the client cannot sign in (the login screen shows the reason); the distributor sees the
  reason on the Clients page. A rejected client can be re-approved, and an approved client can be suspended.
- A client added directly by an Admin is approved immediately.
- Every decision is written to the blockchain ledger (`CLIENT_VERIFIED` / `CLIENT_REJECTED`).
- A client who is already signed in and is suspended/rejected is blocked on their next request.

**Backend:** `services/client_verification.py` (rules), new columns on `clients`
(`verification_status`, `onboarded_by`, `verified_by`, `verified_at`, `rejection_reason`),
`ensure_schema_updates()` in `db/postgres.py` (adds the columns to an already-existing database on start-up
and keeps old rows correct), new admin endpoints `GET /api/admin/client-verifications`,
`POST /api/admin/client-verifications/{id}/approve|reject`, `pendingClientVerifications` on the admin dashboard,
login check in `routers/auth.py`, access check in `routers/client.py`, seed data updated.

**Frontend:** new page `pages/admin/AdminClientVerification.jsx` + sidebar link + route in `App.jsx`;
attention banner on `AdminDashboard.jsx`; real status (Verified / Pending Admin Verification / Rejected + reason)
on `DistributorClients.jsx`; "Approved/Rejected" badges; ledger colours for the new block types; notifications now have an
"Open ->" link (their `actionPath` was never used before); login hint text.

**Seed data note:** the two demo clients that were already unverified (client4@gmail.com Lakeside Medical
Institute and client8@gmail.com Riverside Institution) are now *pending* - they appear in the Admin queue and
cannot sign in until the Admin approves them. The other six demo clients are unchanged.

## 6. Honest ML evaluation (response to the IEEE reviewer comment)
Reviewer: *"Rework the shortage/anomaly evaluation so results are not presented as validated real-world forecasting or anomaly detection without suitable ground truth."*
Full numbers and suggested paper wording: **`EVALUATION.md`** (regenerate with `python -m app.ml.evaluate_models`).

**What was wrong (verified on the code and data):**
- Shortage: 99.8% of the training labels were "shortage" (simulated stock was always below the demand it was compared to); the
  held-out test set had 1,546 positives and 0 negatives from 2 drugs, so the reported 100% accuracy equalled always answering "shortage";
  the model still said 84.5% shortage probability with a year of stock.
- Anomaly: Isolation Forest forced 5-20% of records to be flagged (5 of 100 even in a fault-free population), mixed vendor/distributor/client
  tiers, min-max rescaled scores per scan, and showed rule-based text as if it explained the model. The only labelled anomaly file
  (`module13`) has labels unrelated to its features (ROC-AUC 0.49).
- Interface/README presented these as validated results and described an LSTM+RF+XGBoost ensemble although only the Random Forest is trained.

**What changed:**
- `ml/train_shortage.py`: simulated stock-out labels with a balanced range (44.7% shortage), features from past data only, chronological hold-out
  **with a 14-day gap**, leave-one-drug-out test, majority-class and "days of supply < lead time + 7" baselines, ROC-AUC / PR-AUC / Brier,
  and a report that states `groundTruth: simulated` and `validatedOnRealData: false`. Result: Random Forest F1 about 0.95 vs the rule about 0.95
  (the model adds little over the rule); 365 days of stock now gives about 3% shortage probability.
- `ml/anomaly_detector.py` + `routers/admin.py`: tiers scanned separately (tiers with < 20 records skipped), log-scaled features, absolute score
  threshold (0.60) instead of a forced flag rate, unrescaled scores, flags described as *review candidates*, ledger entries marked
  "unsupervised review candidate (no ground truth)".
- New `ml/evaluate_models.py`: synthetic injected-fault benchmark for the anomaly detector (first version: precision/recall about 0.12, ROC-AUC 0.88;
  now: precision 0.75, recall 0.56, ROC-AUC 0.99, but 3.2% of a fault-free population is still flagged), demand model vs naive baselines
  (R2 0.84 vs 0.71; median per-drug R2 0.61; one-day-ahead only), writes `evaluation_report.json` and `EVALUATION.md`.
- Interface: new `components/ModelNotice.jsx` shown on every page with ML output (shortage, anomaly, forecasts); vendor analytics text no longer
  claims a trained ensemble or "2022-2026"; shortage predictions are labelled "trained on simulated stock-outs".
- README: new "Evaluation and limitations" section; seeded demo anomaly cases are tagged as demo data.
- New `backend/tests/test_ml_honesty.py` (6 regression tests: label balance, test set has both classes, safe vs unsafe stock, no forced flagging, etc.).
- Retrained `shortage_model.joblib` / `shortage_training_report.json` are included (Docker rebuilds them anyway); if you run locally with a
  different scikit-learn version, run `python -m app.ml.train_shortage` once.
