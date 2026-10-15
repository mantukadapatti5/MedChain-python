import { Info } from "lucide-react";

// Honest-use notices shown next to ML outputs. The project has no real-world ground truth:
// its data is synthetic, shortage labels are simulated and anomalies are unlabelled.
// See EVALUATION.md for the evidence behind each statement.
const NOTICES = {
  shortage:
    "Shortage risk is a simulation-based score. The model was trained on synthetic sales history and simulated stock-outs and has not been validated on real shortages. Use it as a decision aid next to the days-of-supply figures, not as a validated forecast.",
  anomaly:
    "Isolation Forest is unsupervised. Flagged cases are review candidates, not confirmed detections: there is no labelled real-world data to validate it, and even fault-free data produces some flags. Each tier (vendor, distributor, client) is scanned separately.",
  forecast:
    "Forecasts come from a model trained on synthetic consumption data and checked on one-day-ahead predictions only. Treat them as illustrative, not as validated real-world demand forecasting.",
};

export default function ModelNotice({ kind = "forecast" }) {
  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50 text-sky-800 text-xs px-3.5 py-2.5 flex items-start gap-2">
      <Info size={14} className="mt-0.5 shrink-0" />
      <p>{NOTICES[kind] || NOTICES.forecast}</p>
    </div>
  );
}
