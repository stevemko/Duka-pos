import { Link } from "react-router-dom";
import { Badge, Button, Card, IconButton } from "../ui";
import { money } from "../../lib/format";

export default function RecentReceipts({ receipts, onPrint, onStk, onSettle }) {
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-ink-100 px-5 py-4">
        <div>
          <h2 className="font-display text-base font-semibold text-ink-950">Recent receipts</h2>
          <p className="text-xs text-ink-400">Latest sales for this branch</p>
        </div>
        <Link to="/transactions">
          <Button variant="ghost" size="sm" iconRight="chevronRight">
            View all
          </Button>
        </Link>
      </div>
      {receipts.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-ink-500">
          No receipts yet. Complete your first sale above.
        </p>
      ) : (
        <div className="divide-y divide-ink-100">
          {receipts.slice(0, 6).map((receipt) => (
            <div
              key={receipt.id}
              className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-ink-900">
                  {receipt.customer_name || receipt.customer_phone || "Walk-in customer"}
                </p>
                <p className="truncate text-xs text-ink-400">
                  {receipt.items.map((item) => `${item.quantity} × ${item.product_name}`).join(", ")}
                </p>
                <p className="mt-0.5 text-[11px] text-ink-400">
                  {new Date(receipt.created_at).toLocaleString()} ·{" "}
                  {receipt.created_by_name || "counter"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <div className="text-right">
                  <p className="text-sm font-bold tabular text-ink-950">KES {money(receipt.total)}</p>
                  <Badge
                    tone={
                      receipt.payment_status === "paid"
                        ? "success"
                        : receipt.payment_status === "payment_pending"
                          ? "info"
                          : "warning"
                    }
                  >
                    {receipt.payment_status.replaceAll("_", " ")}
                  </Badge>
                </div>
                <div className="flex gap-1">
                  <IconButton
                    icon="printer"
                    label="Print receipt"
                    onClick={() => onPrint(receipt)}
                  />
                  {Number(receipt.balance) > 0 && receipt.payment_status !== "payment_pending" && (
                    <>
                      <IconButton
                        icon="phone"
                        label="Prompt M-Pesa"
                        onClick={() => onStk(receipt)}
                      />
                      <IconButton
                        icon="wallet"
                        label="Record payment"
                        onClick={() => onSettle(receipt)}
                      />
                    </>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
