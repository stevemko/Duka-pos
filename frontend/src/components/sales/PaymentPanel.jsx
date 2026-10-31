import Icon from "../Icon";
import { Button, Card, Field, Input, cn } from "../ui";
import { cleanMoney, fromCents, money, toCents } from "../../lib/format";

const PAYMENT_METHODS = [
  { id: "cash", label: "Cash", icon: "wallet" },
  { id: "mpesa_paybill", label: "Paybill", icon: "bank" },
  { id: "mpesa_stk", label: "STK prompt", icon: "phone" },
  { id: "mobile_money", label: "Mobile money", icon: "phone" },
  { id: "card", label: "Card", icon: "card" },
  { id: "bank_transfer", label: "Bank", icon: "store" },
];

export default function PaymentPanel({
  totalCents,
  paymentMode,
  onPaymentModeChange,
  partialAmount,
  onPartialAmountChange,
  paymentMethod,
  onPaymentMethodChange,
  paymentReference,
  onPaymentReferenceChange,
  cashReceived,
  onCashReceivedChange,
  customerName,
  onCustomerNameChange,
  customerPhone,
  onCustomerPhoneChange,
  onSubmit,
  loading,
  blocked,
  shop,
  branchName,
}) {
  const partialCents = toCents(partialAmount);
  const tenderedCents =
    paymentMode === "paid" ? totalCents : paymentMode === "partial" ? partialCents : 0;
  const balanceCents = Math.max(0, totalCents - tenderedCents);
  const changeCents =
    paymentMethod === "cash" && paymentMode === "paid"
      ? Math.max(0, toCents(cashReceived) - totalCents)
      : 0;
  const paybill = shop?.paybill || "";
  const account = customerPhone.trim() || "GREENLIGHT";

  return (
    <Card className="p-4">
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="grid grid-cols-3 gap-1.5">
          {[
            { id: "paid", label: "Paid" },
            { id: "partial", label: "Part" },
            { id: "credit", label: "Credit" },
          ].map((mode) => (
            <button
              key={mode.id}
              type="button"
              onClick={() => onPaymentModeChange(mode.id)}
              className={cn(
                "h-9 rounded-xl text-sm font-semibold transition",
                paymentMode === mode.id
                  ? "bg-ink-950 text-white shadow-sm"
                  : "bg-ink-100 text-ink-500 hover:text-ink-800",
              )}
            >
              {mode.label}
            </button>
          ))}
        </div>

        {paymentMode === "partial" && (
          <Field label="Amount received (KES)">
            <Input
              inputMode="decimal"
              value={partialAmount}
              onChange={(event) => onPartialAmountChange(cleanMoney(event.target.value))}
              placeholder="0.00"
            />
          </Field>
        )}

        {tenderedCents > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-500">
              Payment method
            </p>
            <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
              {PAYMENT_METHODS.map((method) => (
                <button
                  key={method.id}
                  type="button"
                  onClick={() => onPaymentMethodChange(method.id)}
                  className={cn(
                    "flex h-10 items-center justify-center gap-1.5 rounded-xl border text-xs font-semibold transition",
                    paymentMethod === method.id
                      ? "border-brand-500 bg-brand-50 text-brand-800 ring-1 ring-brand-200"
                      : "border-ink-200 bg-white text-ink-500 hover:border-ink-300 hover:text-ink-800",
                  )}
                >
                  <Icon name={method.icon} size={14} />
                  {method.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {paymentMethod === "mpesa_paybill" && tenderedCents > 0 && (
          <div className="space-y-2 rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900">
            <p className="flex items-start gap-2">
              <Icon name="bank" size={15} className="mt-0.5 shrink-0" />
              <span>
                Customer pays <strong>KES {money(fromCents(tenderedCents))}</strong> to Paybill{" "}
                <strong>{paybill || "not configured"}</strong>, account{" "}
                <strong>{account}</strong>. The money goes straight to the shop bank account.
              </span>
            </p>
            {!paybill && (
              <p className="rounded-lg bg-amber-100 px-2 py-1 font-semibold text-amber-900">
                Paybill is not configured yet. Ask the super admin to set MPESA_SHORTCODE.
              </p>
            )}
            <Field label="M-Pesa confirmation code" required hint="Shown on the customer's SMS.">
              <Input
                value={paymentReference}
                onChange={(event) => onPaymentReferenceChange(event.target.value.toUpperCase())}
                placeholder="e.g. SLK7XYZ12A"
                autoComplete="off"
              />
            </Field>
          </div>
        )}

        {(paymentMethod === "mobile_money" ||
          paymentMethod === "card" ||
          paymentMethod === "bank_transfer") &&
          tenderedCents > 0 && (
            <Field label="Reference / confirmation code" hint="Optional, for the daily reconciliation.">
              <Input
                value={paymentReference}
                onChange={(event) => onPaymentReferenceChange(event.target.value)}
                placeholder="Transaction reference"
                autoComplete="off"
              />
            </Field>
          )}

        {paymentMode === "paid" && paymentMethod === "cash" && tenderedCents > 0 && (
          <div className="grid grid-cols-2 gap-2">
            <Field label="Cash received">
              <Input
                inputMode="decimal"
                value={cashReceived}
                onChange={(event) => onCashReceivedChange(cleanMoney(event.target.value))}
                placeholder={money(fromCents(totalCents))}
              />
            </Field>
            <div className="rounded-xl bg-ink-50 px-3 py-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
                Change
              </p>
              <p className="font-display text-lg font-semibold tabular text-ink-950">
                KES {money(fromCents(changeCents))}
              </p>
            </div>
          </div>
        )}

        {paymentMode === "paid" &&
          paymentMethod === "cash" &&
          cashReceived !== "" &&
          toCents(cashReceived) < totalCents && (
            <p className="rounded-xl bg-red-50 px-3 py-2 text-sm font-semibold text-red-700">
              Short by KES {money(fromCents(totalCents - toCents(cashReceived)))}. Cash sales must
              be fully paid — use Part for a credit sale.
            </p>
          )}

        <div className="grid grid-cols-2 gap-2">
          <Field label="Customer name">
            <Input
              value={customerName}
              onChange={(event) => onCustomerNameChange(event.target.value)}
              autoComplete="name"
              placeholder="Optional for paid sale"
            />
          </Field>
          <Field label="Customer phone">
            <Input
              type="tel"
              value={customerPhone}
              onChange={(event) => onCustomerPhoneChange(event.target.value)}
              autoComplete="tel"
              placeholder="07XXXXXXXX"
            />
          </Field>
        </div>

        {paymentMode !== "paid" && (
          <div className="flex items-center justify-between rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800">
            <span>Balance on credit</span>
            <span className="font-bold tabular">KES {money(fromCents(balanceCents))}</span>
          </div>
        )}

        {paymentMode === "paid" && paymentMethod === "mpesa_stk" && tenderedCents > 0 && (
          <p className="rounded-xl bg-sky-50 px-3 py-2 text-xs text-sky-800">
            The sale is saved first, then an M-Pesa prompt is sent for{" "}
            <strong>KES {money(fromCents(tenderedCents))}</strong> to the customer phone.
          </p>
        )}

        <Button
          type="submit"
          variant="brand"
          size="lg"
          loading={loading}
          disabled={totalCents <= 0 || blocked}
          className="w-full"
          icon={blocked ? "alert" : "checkCircle"}
        >
          {loading
            ? "Completing sale..."
            : blocked
              ? "Blocked: price below wholesale cost"
              : totalCents <= 0
                ? "Add products to start"
                : `Complete sale · KES ${money(fromCents(totalCents))}`}
        </Button>
        {branchName && (
          <p className="text-center text-[11px] text-ink-400">Recording at {branchName}</p>
        )}
      </form>
    </Card>
  );
}
