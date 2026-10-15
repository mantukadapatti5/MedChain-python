import { useState } from "react";
import { Shuffle, ArrowRight } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { api } from "../../api/api";
import ErrorBanner from "../../components/ErrorBanner";

export default function DistributorRedistribution() {
  const { data, loading, error, refresh } = usePoll(() => api.get("/distributor/redistribution/recommendations"), { intervalMs: 15000 });
  const [executing, setExecuting] = useState(null);
  const [message, setMessage] = useState("");

  async function execute(rec) {
    setExecuting(rec.id);
    setMessage("");
    try {
      await api.post("/distributor/redistribution/execute", {
        drugName: rec.drugName,
        fromRegion: rec.fromRegion,
        toRegion: rec.toRegion,
        qty: rec.suggestedQty,
      });
      setMessage(`Moved ${rec.suggestedQty} units of ${rec.drugName} from ${rec.fromRegion} to ${rec.toRegion}.`);
      refresh();
    } catch (err) {
      setMessage(err.message);
    } finally {
      setExecuting(null);
    }
  }

  if (loading) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;
  if (error) return <ErrorBanner message={error} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Shuffle size={18} className="text-distributor" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">Stock Redistribution</h2>
          <p className="text-sm text-slate-500">Automatic suggestions for moving surplus stock from over-supplied regions to under-supplied ones.</p>
        </div>
      </div>

      {message && <div className="rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-700 text-sm px-4 py-3">{message}</div>}

      {data.length === 0 && <div className="card p-6 text-sm text-slate-500">No redistribution needed right now — regional stock levels are balanced.</div>}

      <div className="space-y-3">
        {data.map((rec) => (
          <div key={rec.id} className="card p-5 flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="font-semibold text-ink-900">{rec.drugName}</div>
              <div className="mt-1 flex items-center gap-2 text-sm text-slate-600">
                <span className="badge bg-slate-100 text-slate-600">{rec.fromRegion} ({rec.fromStock})</span>
                <ArrowRight size={14} />
                <span className="badge bg-slate-100 text-slate-600">{rec.toRegion} ({rec.toStock})</span>
              </div>
              <p className="mt-1 text-xs text-slate-500">{rec.reason}</p>
            </div>
            <button
              disabled={executing === rec.id}
              onClick={() => execute(rec)}
              className="rounded-xl bg-distributor px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
            >
              {executing === rec.id ? "Moving…" : `Move ${rec.suggestedQty} units`}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
