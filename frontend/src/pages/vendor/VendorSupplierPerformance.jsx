import { Award } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { api } from "../../api/api";
import ErrorBanner from "../../components/ErrorBanner";

export default function VendorSupplierPerformance() {
  const { data, loading, error } = usePoll(() => api.get("/vendor/supplier-performance"), { intervalMs: 15000 });
  if (loading) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;
  if (error) return <ErrorBanner message={error} />;

  const suppliers = data.suppliers || [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Award size={18} className="text-vendor" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">Supplier Performance</h2>
          <p className="text-sm text-slate-500">Ranked from {data.source}, scored on quality, on-time delivery, price and rejection rate — use this before selecting who to procure from.</p>
        </div>
      </div>

      <div className="card overflow-x-auto">
        <table className="table-shell">
          <thead><tr><th>Rank</th><th>Supplier</th><th>Drugs Supplied</th><th>Avg Price</th><th>Avg Delivery</th><th>On-Time Rate</th><th>Quality</th><th>Rejection Rate</th><th>Score</th></tr></thead>
          <tbody>
            {suppliers.map((s, i) => (
              <tr key={s.supplierId}>
                <td className="font-semibold">{i + 1}</td>
                <td className="font-medium text-ink-900">{s.supplierName}</td>
                <td className="text-xs text-slate-500">{s.drugsSupplied.length} products</td>
                <td>₹{s.averagePrice}</td>
                <td>{s.averageDeliveryDays} days</td>
                <td>{s.onTimeRate}%</td>
                <td>{s.qualityScore}</td>
                <td className={s.rejectionRate > 5 ? "text-red-600 font-semibold" : ""}>{s.rejectionRate}%</td>
                <td>
                  <span className={`badge ${i === 0 ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-slate-100 text-slate-600 border border-slate-200"}`}>
                    {s.overallScore}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
