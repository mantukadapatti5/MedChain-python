import { Layers } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { api } from "../../api/api";
import ErrorBanner from "../../components/ErrorBanner";
import StatCard from "../../components/StatCard";

export default function VendorFEFO() {
  const { data, loading, error } = usePoll(() => api.get("/vendor/fefo-allocations"), { intervalMs: 10000 });
  if (loading) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;
  if (error) return <ErrorBanner message={error} />;

  const totalUnits = data.reduce((s, r) => s + Number(r.qtyDispatched || 0), 0);
  const totalShortfall = data.reduce((s, r) => s + Number(r.shortfall || 0), 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Layers size={18} className="text-vendor" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">FEFO Allocation</h2>
          <p className="text-sm text-slate-500">Earliest-expiry-first stock allocation history, generated automatically whenever an incoming request is approved.</p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Requests Allocated" value={data.length} accent="vendor" />
        <StatCard label="Units Dispatched (FEFO)" value={totalUnits} accent="vendor" />
        <StatCard label="Total Shortfall" value={totalShortfall} accent={totalShortfall > 0 ? "red" : "slate"} />
      </div>

      {data.length === 0 && <div className="card p-6 text-sm text-slate-500">No allocations yet — approve an incoming request to see FEFO batch breakdowns here.</div>}

      <div className="space-y-3">
        {data.map((r) => (
          <div key={r.requestId} className="card p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="font-semibold text-ink-900">{r.drugName}</span>
                <span className="ml-2 text-xs text-slate-500">Request #{r.requestId} · {r.region}</span>
              </div>
              <span className="text-xs text-slate-500">{new Date(r.allocatedAt).toLocaleString()}</span>
            </div>
            <div className="mt-1 text-xs text-slate-500">
              Requested {r.qtyRequested} · Dispatched {r.qtyDispatched}
              {r.shortfall > 0 && <span className="ml-2 font-semibold text-red-600">Shortfall {r.shortfall}</span>}
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="table-shell">
                <thead><tr><th>Batch (earliest expiry first)</th><th>Qty</th><th>Expiry</th><th>Unit Price</th><th>Cold Chain</th></tr></thead>
                <tbody>
                  {r.batches.map((b, i) => (
                    <tr key={i}>
                      <td className="font-mono text-xs">{b.batch}</td>
                      <td>{b.qty}</td>
                      <td>{b.expiryDate}</td>
                      <td>₹{b.unitPrice}</td>
                      <td>{b.coldChain ? "❄️ Yes" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
