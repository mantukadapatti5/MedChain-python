import { BarChart3 } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { api } from "../../api/api";
import ErrorBanner from "../../components/ErrorBanner";
import ModelNotice from "../../components/ModelNotice";
import Badge from "../../components/Badge";

const RISK_TO_BADGE = { critical: "high", high: "high", medium: "medium", low: "low", unknown: "low" };

export default function DistributorHospitalForecast() {
  const { data, loading, error } = usePoll(() => api.get("/distributor/hospital-forecast"), { intervalMs: 15000 });
  if (loading) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;
  if (error) return <ErrorBanner message={error} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <BarChart3 size={18} className="text-distributor" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">Hospital / Regional Forecast</h2>
          <p className="text-sm text-slate-500">Predicted demand per client and region over the next {data.horizonDays} days, from client request history.</p>
        </div>
      </div>

      <ModelNotice kind="forecast" />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(data.regionalSummary || []).map((r) => (
          <div key={r.region} className="stat-card">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{r.region}</span>
            <span className="text-2xl font-display font-semibold text-ink-900">{r.forecastDemand}</span>
            <span className="text-xs text-slate-500">forecast demand · {r.criticalItems} critical, {r.highRiskItems} high risk</span>
          </div>
        ))}
      </div>

      <div className="card overflow-x-auto">
        <table className="table-shell">
          <thead><tr><th>Client</th><th>Region</th><th>Drug</th><th>Current Stock</th><th>{data.horizonDays}-Day Forecast</th><th>Days of Supply</th><th>Risk</th></tr></thead>
          <tbody>
            {(data.results || []).map((r, i) => (
              <tr key={i}>
                <td className="font-medium text-ink-900">{r.clientName}</td>
                <td className="text-xs">{r.region}</td>
                <td>{r.drugName}</td>
                <td>{r.currentStock}</td>
                <td>{r.forecastDemand}</td>
                <td className={r.shortageRisk === "critical" ? "font-semibold text-red-600" : ""}>{r.daysOfSupply ?? "—"}</td>
                <td><Badge value={RISK_TO_BADGE[r.shortageRisk] || "low"} withDot={false} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
