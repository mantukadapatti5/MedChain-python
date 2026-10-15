import { QrCode } from "lucide-react";
import QRBatchVerify from "../../components/QRBatchVerify";

export default function VendorQRVerify() {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <QrCode size={18} className="text-vendor" />
        <div>
          <h2 className="font-display text-lg font-semibold text-ink-900">QR Verification</h2>
          <p className="text-sm text-slate-500">Verify a batch before releasing it — checks live inventory, the blockchain ledger, recalls, and the inventory dataset.</p>
        </div>
      </div>
      <QRBatchVerify accent="vendor" />
    </div>
  );
}
