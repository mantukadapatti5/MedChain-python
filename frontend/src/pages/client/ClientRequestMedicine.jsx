import { useState } from "react";
import { PackagePlus } from "lucide-react";
import { api } from "../../api/api";
import { useToast } from "../../context/ToastContext";

const PRIORITIES = ["routine", "urgent", "critical"];

export default function ClientRequestMedicine() {
  const { push } = useToast();
  const [form, setForm] = useState({ drugName: "", qty: "", priority: "routine" });
  const [submitting, setSubmitting] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const created = await api.post("/client/requests", { ...form, qty: Number(form.qty) });
      push(`${created.drugName} is available with your Distributor (${created.availableStock} units in stock). Request for ${form.qty} units sent.`, "success");
      setForm({ drugName: "", qty: "", priority: "routine" });
    } catch (err) {
      push(err.message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <PackagePlus size={18} className="text-client" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">Request Medicine</h2>
          <p className="text-sm text-slate-500">Quickly raise a new stock request to your distributor. Track it afterwards under "My Requests".</p>
        </div>
      </div>

      <form onSubmit={submit} className="card p-6 max-w-lg space-y-4">
        <div>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Medicine name</label>
          <input required className="mt-1 w-full rounded-xl border p-3 text-sm" placeholder="e.g. Amoxicillin 250mg" value={form.drugName} onChange={(e) => setForm({ ...form, drugName: e.target.value })} />
        </div>
        <div>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Quantity</label>
          <input required type="number" min="1" className="mt-1 w-full rounded-xl border p-3 text-sm" placeholder="e.g. 100" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} />
        </div>
        <div>
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Priority</label>
          <div className="mt-1 flex gap-2">
            {PRIORITIES.map((p) => (
              <button type="button" key={p} onClick={() => setForm({ ...form, priority: p })}
                className={`flex-1 rounded-xl px-3 py-2 text-sm font-semibold capitalize ${form.priority === p ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600"}`}>
                {p}
              </button>
            ))}
          </div>
        </div>
        <button disabled={submitting} className="w-full rounded-xl bg-client px-5 py-3 text-sm font-semibold text-white disabled:opacity-50">
          {submitting ? "Sending…" : "Send Request"}
        </button>
      </form>
    </div>
  );
}
