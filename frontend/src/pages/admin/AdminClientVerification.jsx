import { useState } from "react";
import { UserCheck, Check, X, Loader2, MapPinned, Mail, Phone, Building2 } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { api } from "../../api/api";
import { useToast } from "../../context/ToastContext";
import Badge from "../../components/Badge";
import Modal from "../../components/Modal";
import ErrorBanner from "../../components/ErrorBanner";

const TABS = [
  ["pending", "Pending"],
  ["approved", "Approved"],
  ["rejected", "Rejected"],
  ["all", "All"],
];

const EMPTY_TEXT = {
  pending: "No clients are waiting for verification. You are all caught up.",
  approved: "No approved clients yet.",
  rejected: "No rejected clients.",
  all: "No clients have been added yet.",
};

function formatDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

export default function AdminClientVerification() {
  const { data, loading, error, refresh } = usePoll(() => api.get("/admin/client-verifications"), { intervalMs: 6000 });
  const { push } = useToast();
  const [tab, setTab] = useState("pending");
  const [busyId, setBusyId] = useState(null);
  const [rejecting, setRejecting] = useState(null);
  const [reason, setReason] = useState("");

  const approve = async (client) => {
    setBusyId(client.id);
    try {
      await api.post(`/admin/client-verifications/${client.id}/approve`);
      push(`${client.name} approved. They can now sign in to the Client Portal.`, "success");
      refresh();
    } catch (err) {
      push(err.message, "error");
    } finally {
      setBusyId(null);
    }
  };

  const submitReject = async (e) => {
    e.preventDefault();
    const client = rejecting;
    if (!client) return;
    setBusyId(client.id);
    try {
      await api.post(`/admin/client-verifications/${client.id}/reject`, { reason: reason.trim() });
      push(`${client.name} rejected. The Distributor has been notified.`, "success");
      setRejecting(null);
      setReason("");
      refresh();
    } catch (err) {
      push(err.message, "error");
    } finally {
      setBusyId(null);
    }
  };

  const closeReject = () => {
    setRejecting(null);
    setReason("");
  };

  if (loading) return <div className="h-64 rounded-2xl bg-slate-100 animate-pulse" />;
  if (error) return <ErrorBanner message={error} />;

  const counts = data.counts || { pending: 0, approved: 0, rejected: 0 };
  const items = tab === "all" ? data.items : data.items.filter((c) => c.verificationStatus === tab);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="font-display text-lg font-semibold text-ink-900 flex items-center gap-2">
          <UserCheck size={18} className="text-admin" /> Client Verification
        </h2>
        <p className="text-sm text-slate-500">
          Clients added by a Distributor cannot sign in until you verify them. Approve genuine pharmacies, hospitals
          and clinics, or reject with a reason.
        </p>
      </div>

      {counts.pending > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 text-amber-800 text-sm px-4 py-3">
          {counts.pending} client{counts.pending === 1 ? " is" : "s are"} waiting for your verification.
        </div>
      )}

      <div className="flex gap-2 flex-wrap">
        {TABS.map(([value, label]) => {
          const count = value === "all" ? data.total : counts[value];
          return (
            <button
              key={value}
              onClick={() => setTab(value)}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold border ${
                tab === value ? "bg-ink-900 text-white border-ink-900" : "bg-white text-slate-600 border-slate-200"
              }`}
            >
              {label} ({count})
            </button>
          );
        })}
      </div>

      {items.length === 0 ? (
        <div className="card p-8 text-center text-sm text-slate-500">{EMPTY_TEXT[tab]}</div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="table-shell">
            <thead>
              <tr>
                <th>Client</th>
                <th>Region</th>
                <th>Contact</th>
                <th>Added By</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div className="flex items-center gap-2.5">
                      <div className="h-9 w-9 rounded-lg bg-admin-soft text-admin flex items-center justify-center shrink-0">
                        <Building2 size={16} />
                      </div>
                      <div>
                        <p className="font-medium text-ink-900">{c.name}</p>
                        <p className="text-xs text-slate-500">{c.type}</p>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className="badge bg-slate-100 text-slate-600">
                      <MapPinned size={11} /> {c.region}
                    </span>
                  </td>
                  <td className="text-xs text-slate-600 space-y-0.5">
                    {c.contactPerson && <p className="font-medium text-ink-900">{c.contactPerson}</p>}
                    {c.email && (
                      <p className="flex items-center gap-1"><Mail size={11} /> {c.email}</p>
                    )}
                    {c.phone && (
                      <p className="flex items-center gap-1"><Phone size={11} /> {c.phone}</p>
                    )}
                  </td>
                  <td className="text-xs text-slate-500">
                    <p>{c.onboardedBy || "—"}</p>
                    <p>{formatDate(c.onboardedAt)}</p>
                  </td>
                  <td>
                    <Badge value={c.verificationStatus} />
                    {c.verificationStatus === "rejected" && c.rejectionReason && (
                      <p className="text-xs text-red-600 mt-1 max-w-[220px]">Reason: {c.rejectionReason}</p>
                    )}
                    {c.verificationStatus !== "pending" && c.verifiedBy && (
                      <p className="text-[11px] text-slate-400 mt-1">by {c.verifiedBy}</p>
                    )}
                  </td>
                  <td>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {c.verificationStatus !== "approved" && (
                        <button
                          onClick={() => approve(c)}
                          disabled={busyId === c.id}
                          className="btn bg-emerald-600 text-white hover:bg-emerald-700 !py-1 !px-2.5 text-xs"
                        >
                          {busyId === c.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
                          {c.verificationStatus === "rejected" ? "Re-approve" : "Approve"}
                        </button>
                      )}
                      {c.verificationStatus !== "rejected" && (
                        <button
                          onClick={() => setRejecting(c)}
                          disabled={busyId === c.id}
                          className="btn-outline !py-1 !px-2.5 text-xs text-red-600 border-red-200 hover:bg-red-50"
                        >
                          <X size={12} />
                          {c.verificationStatus === "approved" ? "Suspend" : "Reject"}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal open={!!rejecting} onClose={closeReject} title={rejecting ? `Reject ${rejecting.name}?` : "Reject client"}>
        <form onSubmit={submitReject} className="space-y-3">
          <p className="text-sm text-slate-600">
            The client will not be able to sign in, and the Distributor will see your reason.
          </p>
          <label className="text-xs font-medium text-slate-600 space-y-1 block">
            Reason for rejection
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              required
              minLength={3}
              placeholder="e.g. Drug licence number could not be verified"
              className="input focus:ring-admin/20 focus:border-admin"
            />
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={closeReject} className="btn-outline">Cancel</button>
            <button type="submit" disabled={busyId !== null || reason.trim().length < 3} className="btn-danger">
              {busyId !== null && <Loader2 size={14} className="animate-spin" />}
              Confirm Reject
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
