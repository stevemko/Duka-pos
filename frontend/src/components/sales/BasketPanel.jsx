import Icon from "../Icon";
import { Button, Card, cn } from "../ui";
import { cleanMoney, cleanWholeNumber, fromCents, money, toCents } from "../../lib/format";

function lineFloor(product) {
  return Number(product?.price_floor ?? product?.cost_price ?? 0);
}

export default function BasketPanel({
  cart,
  productMap,
  onChange,
  onRemove,
  onClear,
  totalCents,
  itemCount,
  blocked,
}) {
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-ink-100 px-5 py-4">
        <div>
          <h2 className="font-display text-base font-semibold text-ink-950">Basket</h2>
          <p className="text-xs text-ink-400">
            {itemCount} units · {cart.length} lines
          </p>
        </div>
        {cart.length > 0 && (
          <Button variant="ghost" size="sm" icon="trash" onClick={onClear}>
            Clear
          </Button>
        )}
      </div>

      {cart.length === 0 ? (
        <div className="px-5 py-10 text-center">
          <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-ink-100 text-ink-400">
            <Icon name="cart" size={22} />
          </span>
          <p className="mt-3 text-sm font-semibold text-ink-800">Basket is empty</p>
          <p className="mt-1 text-sm text-ink-500">
            Search or scan a product to start the order.
          </p>
        </div>
      ) : (
        <div className="scrollbar-thin max-h-[420px] divide-y divide-ink-100 overflow-y-auto">
          {cart.map((item) => {
            const product = productMap.get(item.product);
            const marked = Number(product?.selling_price ?? 0);
            const floor = lineFloor(product);
            const priceCents = toCents(item.price_sold_at);
            const belowFloor = floor > 0 && priceCents < toCents(floor);
            const belowMarked = marked > 0 && priceCents < toCents(marked);
            const discount =
              belowMarked && marked > 0 ? ((marked - priceCents / 100) / marked) * 100 : 0;
            const lineCents = priceCents * Number(item.quantity || 0);

            return (
              <div key={item.product} className="px-4 py-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-ink-900">
                      {product?.name || "Product"}
                    </p>
                    <p className="text-[11px] text-ink-400">
                      Retail KES {money(product?.selling_price)} · Min KES {money(floor)} · Stock{" "}
                      {product?.stock_quantity ?? 0}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => onRemove(item.product)}
                    className="rounded-lg p-1 text-ink-300 transition hover:bg-red-50 hover:text-red-600"
                    aria-label={`Remove ${product?.name || "product"}`}
                  >
                    <Icon name="close" size={15} />
                  </button>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <div className="flex h-9 items-center rounded-xl border border-ink-200 bg-white">
                    <button
                      type="button"
                      onClick={() =>
                        onChange(item.product, {
                          quantity: Math.max(1, Number(item.quantity) - 1),
                        })
                      }
                      className="flex h-full w-8 items-center justify-center text-ink-500 hover:text-ink-900"
                      aria-label="Decrease quantity"
                    >
                      <Icon name="minus" size={13} />
                    </button>
                    <input
                      type="text"
                      inputMode="numeric"
                      value={item.quantity}
                      onChange={(event) => {
                        const digits = cleanWholeNumber(event.target.value);
                        onChange(item.product, {
                          quantity:
                            digits === ""
                              ? ""
                              : Math.min(Number(digits), product?.stock_quantity ?? 0),
                        });
                      }}
                      onBlur={() => {
                        if (!Number(item.quantity) || Number(item.quantity) < 1) {
                          onChange(item.product, { quantity: 1 });
                        }
                      }}
                      className="h-full w-10 border-x border-ink-100 text-center text-sm font-semibold tabular focus:outline-none"
                      aria-label={`Quantity for ${product?.name || "product"}`}
                    />
                    <button
                      type="button"
                      onClick={() =>
                        onChange(item.product, {
                          quantity: Math.min(
                            product?.stock_quantity ?? 0,
                            Number(item.quantity) + 1,
                          ),
                        })
                      }
                      className="flex h-full w-8 items-center justify-center text-ink-500 hover:text-ink-900"
                      aria-label="Increase quantity"
                    >
                      <Icon name="plus" size={13} />
                    </button>
                  </div>
                  <div className="relative flex-1">
                    <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[11px] font-bold text-ink-400">
                      KES
                    </span>
                    <input
                      type="text"
                      inputMode="decimal"
                      value={item.price_sold_at}
                      onChange={(event) =>
                        onChange(item.product, {
                          price_sold_at: cleanMoney(event.target.value),
                        })
                      }
                      className={cn(
                        "h-9 w-full rounded-xl border pl-10 pr-2 text-right text-sm font-semibold tabular shadow-sm focus:outline-none focus:ring-2",
                        belowFloor
                          ? "border-red-400 bg-red-50 text-red-700 ring-red-100"
                          : belowMarked
                            ? "border-amber-300 bg-amber-50 text-amber-800 focus:border-amber-500 focus:ring-amber-100"
                            : "border-ink-200 bg-white text-ink-900 focus:border-brand-500 focus:ring-brand-100",
                      )}
                      aria-label={`Charged unit price for ${product?.name || "product"}`}
                    />
                  </div>
                  <p className="w-20 text-right text-sm font-bold tabular text-ink-950">
                    {money(fromCents(lineCents))}
                  </p>
                </div>
                {belowFloor ? (
                  <p className="mt-1.5 flex items-center gap-1 text-[11px] font-semibold text-red-600">
                    <Icon name="alert" size={12} />
                    Below wholesale cost — checkout is blocked.
                  </p>
                ) : (
                  belowMarked && (
                    <p className="mt-1.5 flex items-center gap-1 text-[11px] font-semibold text-amber-700">
                      <Icon name="tag" size={12} />
                      {discount.toFixed(1)}% below retail price — allowed.
                    </p>
                  )
                )}
              </div>
            );
          })}
        </div>
      )}

      {blocked && (
        <div className="mx-4 mb-3 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
          <Icon name="alert" size={18} className="mt-0.5 shrink-0 text-red-600" />
          <p>
            <strong>Wholesale cost floor.</strong> Raise the price to the wholesale cost or higher
            to unlock checkout.
          </p>
        </div>
      )}

      <div className="border-t border-ink-100 bg-ink-50/60 px-4 py-3">
        <div className="flex items-center justify-between">
          <span className="text-sm text-ink-500">Total</span>
          <span className="font-display text-2xl font-semibold tabular text-ink-950">
            KES {money(fromCents(totalCents))}
          </span>
        </div>
      </div>
    </Card>
  );
}
