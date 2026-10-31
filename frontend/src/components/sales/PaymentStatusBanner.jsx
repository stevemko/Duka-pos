import { Button, cn } from "../ui";
import Icon from "../Icon";
import { money } from "../../lib/format";

const TONES = {
  waiting: {
    box: "border-sky-300 bg-sky-50 text-sky-900",
    icon: "clock",
    label: "Waiting for M-Pesa",
  },
  paid: {
    box: "border-emerald-300 bg-emerald-50 text-emerald-900",
    icon: "checkCircle",
    label: "Payment received",
  },
  not_paid: {
    box: "border-red-300 bg-red-50 text-red-900",
    icon: "alert",
    label: "Not paid yet",
  },
  not_sent: {
    box: "border-red-300 bg-red-50 text-red-900",
    icon: "alert",
    label: "Prompt not sent",
  },
  unknown: {
    box: "border-amber-300 bg-amber-50 text-amber-900",
    icon: "alert",
    label: "Payment not confirmed",
  },
};

// One banner, shown both in the prompt dialog and on the receipt card, so the
// seller can always tell whether the money has actually arrived.
export default function PaymentStatusBanner({ status, checking, onCheck, onSendAgain }) {
  if (!status) return null;
  const tone = TONES[status.state] || TONES.unknown;
  const balance = Number(status.balance || 0);

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("rounded-xl border px-3 py-2.5", tone.box)}
    >
      <p className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide">
        <Icon name={tone.icon} size={16} />
        {tone.label}
      </p>
      <p className="mt-1 text-xs font-medium leading-relaxed">{status.message}</p>
      {status.code && (
        <p className="mt-1 text-xs font-semibold">
          M-Pesa code <span className="font-mono tracking-wide">{status.code}</span>
        </p>
      )}
      {status.state !== "paid" && balance > 0 && (
        <p className="mt-1 text-xs font-semibold">Still owed: KES {money(balance)}</p>
      )}

      <div className="mt-2 flex flex-wrap gap-2">
        {onCheck && (
          <Button size="sm" variant="secondary" icon="refresh" loading={checking} onClick={onCheck}>
            {checking ? "Checking with Safaricom..." : "Check payment now"}
          </Button>
        )}
        {onSendAgain && (
          <Button size="sm" variant="brand" icon="phone" onClick={onSendAgain}>
            Send prompt again
          </Button>
        )}
      </div>
    </div>
  );
}
