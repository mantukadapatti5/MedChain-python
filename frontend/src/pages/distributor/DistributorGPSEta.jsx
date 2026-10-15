import { Navigation } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { api } from "../../api/api";
import ErrorBanner from "../../components/ErrorBanner";

export default function DistributorGPSEta() {
  const { data, loading, error } = usePoll(() => api.get("/distributor/gps-eta"), { intervalMs: 8000 });
  if (loading) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;
  if (error) return <ErrorBanner message={error} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Navigation size={18} className="text-distributor" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">GPS + ETA</h2>
          <p className="text-sm text-slate-500">Live distance travelled, remaining distance, and estimated arrival for every shipment currently in transit.</p>
        </div>
      </div>

      {data.length === 0 && <div className="card p-6 text-sm text-slate-500">No shipments currently in transit.</div>}

      <div className="space-y-3">
        {data.map((s) => (
          <div key={`${s.requestId}-${s.direction}`} className="card p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="font-semibold text-ink-900">{s.drugName}</span>
                <span className="ml-2 text-xs text-slate-500">{s.direction} · Request #{s.requestId}</span>
              </div>
              <span className="text-xs font-semibold text-distributor">
                {s.etaMinutes != null ? `ETA ${s.etaMinutes < 60 ? `${s.etaMinutes} min` : `${(s.etaMinutes / 60).toFixed(1)} hr`}` : "ETA unavailable"}
              </span>
            </div>
            <div className="mt-2 h-1.5 bg-slate-200 rounded-full overflow-hidden">
              <div className="h-full bg-distributor transition-all" style={{ width: `${s.progressPercent}%` }} />
            </div>
            <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs text-slate-500">
              <div>Travelled: <span className="font-semibold text-ink-900">{s.travelledKm} km</span></div>
              <div>Remaining: <span className="font-semibold text-ink-900">{s.remainingKm} km</span></div>
              <div>Avg speed: <span className="font-semibold text-ink-900">{s.averageSpeedKmh} km/h</span></div>
              <div>Destination: <span className="font-semibold text-ink-900">{s.destination?.label}</span></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
