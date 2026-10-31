import { Link } from "react-router-dom";
import Icon from "../Icon";
import PaymentStatusBanner from "./PaymentStatusBanner";
import { Badge, Button, Card } from "../ui";
import { money } from "../../lib/format";

export default function ReceiptSuccessCard({
  receipt,
  shop,
  onPrint,
  onStk,
  onSettle,
  payment,
  checkingPayment,
  onCheckPayment,
}) {
  if (!receipt) return null;
  const balance = Number(receipt.balance);
  const account = receipt.id.slice(0, 8).toUpperCase();
  const statusLabels = {
    paid: "Paid",
    payment_pending: "Waiting for M-Pesa",
    partially_paid: "Part paid",
    on_credit: "On credit - not paid",
  };

  return (
    <Card className="animate-rise border-brand-200 bg-brand-50/50 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-brand-900">Receipt {account}</p>
          <p className="text-xs text-brand-800/70">
            {receipt.customer_name || "Walk-in customer"} · {receipt.branch_name} ·{" "}
            {new Date(receipt.created_at).toLocaleTimeString()}
          </p>
        </div>
        <Badge tone={receipt.payment_status === "paid" ? "success" : "warning"}>
          {statusLabels[receipt.payment_status] || receipt.payment_status}
        </Badge>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl bg-white/70 px-2 py-2">
          <p className="text-[10px] uppercase tracking-wide text-ink-400">Total</p>
          <p className="text-sm font-bold tabular text-ink-900">{money(receipt.total)}</p>
        </div>
        <div className="rounded-xl bg-white/70 px-2 py-2">
          <p className="text-[10px] uppercase tracking-wide text-ink-400">Paid</p>
          <p className="text-sm font-bold tabular text-emerald-700">{money(receipt.amount_paid)}</p>
        </div>
        <div className="rounded-xl bg-white/70 px-2 py-2">
          <p className="text-[10px] uppercase tracking-wide text-ink-400">Balance</p>
          <p className="text-sm font-bold tabular text-amber-700">{money(receipt.balance)}</p>
        </div>
      </div>

      {balance > 0 && shop?.paybill && (
        <div className="mt-3 flex items-start gap-2 rounded-xl border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900">
          <Icon name="bank" size={15} className="mt-0.5 shrink-0" />
          <p>
            Pay <strong>KES {money(balance)}</strong> to Paybill{" "}
            <strong>{shop.paybill}</strong>, account <strong>{account}</strong>. The payment goes
            to the shop bank account.
          </p>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" icon="printer" onClick={() => onPrint(receipt)}>
          Print receipt
        </Button>
        {balance > 0 && (
          <Button variant="brand" size="sm" icon="phone" onClick={() => onStk(receipt)}>
            Prompt M-Pesa
          </Button>
        )}
        {balance > 0 && (
          <Button variant="secondary" size="sm" icon="wallet" onClick={() => onSettle(receipt)}>
            Record payment
          </Button>
        )}
        <Link to="/transactions">
          <Button variant="ghost" size="sm" iconRight="arrowUpRight">
            Open ledger
          </Button>
        </Link>
      </div>

      <div className="mt-3">
        <PaymentStatusBanner
          status={payment}
          checking={checkingPayment}
          onCheck={balance > 0 ? onCheckPayment : null}
          onSendAgain={
            payment?.state === "not_paid" || payment?.state === "unknown" || payment?.state === "not_sent"
              ? () => onStk(receipt)
              : null
          }
        />
      </div>
    </Card>
  );
}
