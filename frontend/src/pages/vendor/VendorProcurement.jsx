import { useState } from "react";
import { ShoppingBag } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { api } from "../../api/api";
import ErrorBanner from "../../components/ErrorBanner";

export default function VendorProcurement() {
  const { data, loading, error, refresh } = usePoll(() => api.get("/vendor/procurement"), { intervalMs: 10000 });
  const [form, setForm] = useState({ drugName: "", qty: "", region: "", supplierName: "", reason: "" });
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setSubmitting(true);
    setFormError("");
    try {
      await api.post("/vendor/procurement", { ...form, qty: Number(form.qty) });
      setForm({ drugName: "", qty: "", region: "", supplierName: "", reason: "" });
      refresh();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;
  if (error) return <ErrorBanner message={error} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <ShoppingBag size={18} className="text-vendor" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">Procurement</h2>
          <p className="text-sm text-slate-500">Log a purchasing decision against a ranked supplier from Supplier Performance.</p>
        </div>
      </div>

      <form onSubmit={submit} className="card p-5 grid gap-3 sm:grid-cols-5">
        <input required placeholder="Drug name" className="rounded-xl border p-3 text-sm sm:col-span-1" value={form.drugName} onChange={(e) => setForm({ ...form, drugName: e.target.value })} />
        <input required type="number" min="1" placeholder="Qty" className="rounded-xl border p-3 text-sm" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} />
        <input placeholder="Region" className="rounded-xl border p-3 text-sm" value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} />
        <input required placeholder="Supplier name" className="rounded-xl border p-3 text-sm" value={form.supplierName} onChange={(e) => setForm({ ...form, supplierName: e.target.value })} />
        <button disabled={submitting} className="rounded-xl bg-vendor px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">{submitting ? "Saving…" : "Log Procurement"}</button>
        {formError && <div className="sm:col-span-5 text-sm text-red-600">{formError}</div>}
      </form>

      <div className="card overflow-x-auto">
        <table className="table-shell">
          <thead><tr><th>Drug</th><th>Qty</th><th>Region</th><th>Supplier</th><th>Reason</th><th>Logged</th></tr></thead>
          <tbody>
            {(data || []).map((p) => (
              <tr key={p.id}>
                <td className="font-medium text-ink-900">{p.drugName}</td>
                <td>{p.qty}</td>
                <td>{p.region || "—"}</td>
                <td>{p.supplierName}</td>
                <td className="text-xs text-slate-500">{p.reason}</td>
                <td className="text-xs text-slate-500">{new Date(p.createdAt).toLocaleString()}</td>
              </tr>
            ))}
            {(!data || data.length === 0) && <tr><td colSpan={6} className="text-center text-sm text-slate-500 py-6">No procurement decisions logged yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
