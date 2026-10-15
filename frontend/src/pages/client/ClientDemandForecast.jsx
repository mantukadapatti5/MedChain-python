import { TrendingUp } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { api } from "../../api/api";
import ErrorBanner from "../../components/ErrorBanner";
import ModelNotice from "../../components/ModelNotice";

export default function ClientDemandForecast() {
  const { data, loading, error } = usePoll(() => api.get("/client/demand-forecast"), { intervalMs: 15000 });
  if (loading) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;
  if (error) return <ErrorBanner message={error} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <TrendingUp size={18} className="text-client" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">My Demand Forecast</h2>
          <p className="text-sm text-slate-500">Predicted 7-day demand for medicines you've requested, based on your own request history.</p>
        </div>
      </div>

      <ModelNotice kind="forecast" />

      {data.message && <div className="card p-6 text-sm text-slate-500">{data.message}</div>}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(data.forecasts || []).map((f) => (
          <div key={f.drugName} className="card p-5">
            <div className="font-semibold text-ink-900">{f.drugName}</div>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="text-2xl font-display font-semibold text-ink-900">{f.available ? f.forecastNext7Days : "—"}</span>
              <span className="text-xs text-slate-500">units / 7 days</span>
            </div>
            <div className="mt-2 text-xs text-slate-500">Current stock: {f.currentStock} · {f.requestsOnRecord} request(s) on record</div>
            <div className="mt-1 text-xs text-slate-400">{f.method}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
