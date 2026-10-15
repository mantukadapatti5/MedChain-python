import { useState } from "react";
import { QrCode, CheckCircle2, XCircle, ShieldAlert } from "lucide-react";
import { api } from "../api/api";

export default function QRBatchVerify({ accent = "slate" }) {
  const [batch, setBatch] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function verify(e) {
    e.preventDefault();
    if (!batch.trim()) return;
    setLoading(true);
    setError("");
    try {
      setResult(await api.get(`/batch/${encodeURIComponent(batch.trim())}/verify`));
    } catch (err) {
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card p-5">
      <form onSubmit={verify} className="flex gap-3">
        <input
          className="flex-1 rounded-xl border p-3 text-sm font-mono"
          placeholder="Scan or enter a batch number, e.g. AMX-1187"
          value={batch}
          onChange={(e) => setBatch(e.target.value)}
        />
        <button disabled={loading} className={`rounded-xl bg-${accent === "slate" ? "slate-900" : accent} px-5 py-3 text-sm font-semibold text-white disabled:opacity-50 flex items-center gap-2`}>
          <QrCode size={16} /> {loading ? "Verifying…" : "Verify"}
        </button>
      </form>
      {error && <div className="mt-3 text-sm text-red-600">{error}</div>}
      {result && (
        <div className={`mt-4 rounded-xl border p-5 ${result.found ? "border-slate-200" : "border-red-200 bg-red-50"}`}>
          {!result.found ? (
            <div className="flex items-center gap-2 text-red-700 text-sm font-semibold"><XCircle size={16} /> No record found for batch "{result.batch}".</div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <div><span className="text-xs text-slate-500">Medicine</span><div className="font-semibold text-ink-900">{result.drugName || "—"}</div></div>
                <div><span className="text-xs text-slate-500">Manufacturer</span><div>{result.manufacturer || "—"}</div></div>
                <div><span className="text-xs text-slate-500">Expiry</span><div>{result.expiryDate || "—"}</div></div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-4 text-sm">
                <span className="flex items-center gap-1.5">{result.blockchainVerified ? <CheckCircle2 size={15} className="text-emerald-600" /> : <XCircle size={15} className="text-slate-400" />} {result.blockchainVerified ? `Blockchain verified (${result.blockchainEvents} event(s))` : "No blockchain history"}</span>
                <span className="flex items-center gap-1.5">{result.datasetRecord ? <CheckCircle2 size={15} className="text-emerald-600" /> : <XCircle size={15} className="text-slate-400" />} {result.datasetRecord ? "Found in inventory dataset" : "Not in inventory dataset"}</span>
                {result.activeRecall ? (
                  <span className="flex items-center gap-1.5 font-semibold text-red-600"><ShieldAlert size={15} /> Active recall: {result.activeRecall.reason}</span>
                ) : (
                  <span className="flex items-center gap-1.5 text-emerald-700"><CheckCircle2 size={15} /> No active recall</span>
                )}
              </div>
              {result.holders?.length > 0 && <div className="mt-2 text-xs text-slate-500">Currently held at: {result.holders.join(", ")}</div>}
              {result.datasetRecord && <div className="mt-1 text-xs text-slate-500">Dataset: {result.datasetRecord.region} region · {result.datasetRecord.currentStock} units on record · cold chain: {result.datasetRecord.coldChainRequired}</div>}
            </>
          )}
        </div>
      )}
    </div>
  );
}
