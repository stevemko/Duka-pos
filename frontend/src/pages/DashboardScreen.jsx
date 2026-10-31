import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { productsApi, receiptsApi, salesApi, apiErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { currentMonth, fromCents, money, monthBounds, toCents } from "../lib/format";
import Icon from "../components/Icon";
import { DonutChart } from "../components/charts";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  PageHeader,
  Spinner,
  StatCard,
  TableShell,
  Td,
  Th,
  cn,
} from "../components/ui";

const PAYMENT_COLORS = {
  cash: "#059669",
  mpesa_paybill: "#0ea5e9",
  mpesa_stk: "#34d399",
  mobile_money: "#f59e0b",
  card: "#8b5cf6",
  bank_transfer: "#64748b",
};

function labelize(value = "") {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function sumCents(values) {
  return values.reduce((sum, value) => sum + toCents(value), 0);
}

export default function DashboardScreen() {
  const { canManage, branchQuery, activeBranch, canViewAllBranches } = useAuth();
  const [month, setMonth] = useState(currentMonth);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const branch = branchQuery || (canViewAllBranches ? "all" : undefined);
    setLoading(true);
    setError("");

    Promise.all([
      salesApi.analytics(month, branch ? { branch } : {}),
      receiptsApi.credits(branch ? { branch } : {}),
      productsApi
        .lowStock(branch && branch !== "all" ? { branch } : {})
        .catch(() => ({ results: [] })),
    ])
      .then(([analytics, credits, lowStock]) => {
        if (!active) return;
        setData({ analytics, credits, lowStock: lowStock.results || [] });
      })
      .catch((requestError) => {
        if (active) setError(apiErrorMessage(requestError, "Dashboard data could not be loaded."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [month, branchQuery, canViewAllBranches]);

  const analytics = data?.analytics;
  const credits = data?.credits || { outstanding_total: 0, customer_count: 0, credits: [] };
  const lowStock = data?.lowStock || [];

  const now = new Date();
  const todayKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
  const today = analytics?.daily_totals?.find((day) => day.date === todayKey);

  const daily = analytics?.daily_totals || [];
  const totals = useMemo(() => {
    const days = analytics?.daily_totals || [];
    return {
      sales: analytics ? toCents(analytics.total_sales) : 0,
      collected: sumCents(days.map((day) => day.amount_collected)),
      spent: sumCents(days.map((day) => day.amount_spent)),
      profit: sumCents(days.map((day) => day.gross_profit)),
      units: days.reduce((sum, day) => sum + Number(day.items_sold || 0), 0),
    };
  }, [analytics]);

  const movers = analytics?.product_performance || [];
  const stagnant = analytics?.stagnant_products || [];
  const maxUnits = Math.max(1, ...movers.map((row) => row.quantity_sold));
  const weekly = analytics?.weekly_income || [];
  const maxWeekly = Math.max(
    1,
    ...weekly.flatMap((week) => [toCents(week.sales_total), toCents(week.amount_collected)]),
  );
  const { start, end } = monthBounds(month);

  const categoryData = (analytics?.sales_by_category || []).map((row) => ({
    label: row.category,
    value: row.sales_total,
    quantity: row.quantity_sold,
  }));
  const paymentData = (analytics?.payment_mix || []).map((row) => ({
    label: row.label,
    value: row.amount,
    color: PAYMENT_COLORS[row.method],
  }));
  const expenseData = (analytics?.expenses_by_category || []).map((row) => ({
    label: labelize(row.category),
    value: row.amount,
  }));

  const charts = [
    {
      title: "Sales by category",
      subtitle: "Share of this month's sales value",
      data: categoryData,
      labelKey: "label",
      valueKey: "value",
      centerLabel: "Sales",
      emptyText: "No sales recorded this month.",
    },
    {
      title: "Payment mix",
      subtitle: "How customers settled their receipts",
      data: paymentData,
      labelKey: "label",
      valueKey: "value",
      centerLabel: "Collected",
      emptyText: "No payments collected this month.",
    },
  ];
  if (canManage) {
    charts.push({
      title: "Expenses by category",
      subtitle: "Money out of the business",
      data: expenseData,
      labelKey: "label",
      valueKey: "value",
      centerLabel: "Expenses",
      emptyText: "No expenses recorded this month.",
    });
  }

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Insights"
        title="Business dashboard"
        subtitle={
          activeBranch
            ? `${activeBranch.name} · ${start} to ${end}`
            : canViewAllBranches
              ? `All branches · ${start} to ${end}`
              : `${start} to ${end}`
        }
        actions={
          <label className="flex items-center gap-2 rounded-xl border border-ink-200 bg-white px-3 shadow-sm">
            <Icon name="clock" size={16} className="text-ink-400" />
            <input
              type="month"
              value={month}
              onChange={(event) => setMonth(event.target.value || currentMonth())}
              className="h-10 border-0 bg-transparent text-sm font-semibold text-ink-800 focus:outline-none"
              aria-label="Reporting month"
            />
          </label>
        }
      />

      {error && <Alert tone="error">{error}</Alert>}

      {loading ? (
        <Spinner label="Building this month's picture" />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatCard
              label="Sales this month"
              value={`KES ${money(analytics?.total_sales)}`}
              icon="cart"
              tone="brand"
              hint={`${Number(analytics?.items_sold || 0).toLocaleString()} units sold`}
            />
            <StatCard
              label="Money collected"
              value={`KES ${money(fromCents(totals.collected))}`}
              icon="wallet"
              tone="info"
              hint="Cash, M-Pesa and other payments"
            />
            <StatCard
              label="Outstanding credit"
              value={`KES ${money(credits.outstanding_total)}`}
              icon="clock"
              tone="warning"
              hint={`${credits.customer_count ?? credits.credits.length} customers owing`}
            />
            <StatCard
              label="Today so far"
              value={`KES ${money(today?.total_sales || 0)}`}
              icon="spark"
              tone="brand"
              hint={`${today?.items_sold || 0} units · collected KES ${money(today?.amount_collected || 0)}`}
            />
          </div>

          {canManage && (
            <div className="grid gap-3 sm:grid-cols-3">
              <StatCard
                label="Gross profit"
                value={`KES ${money(analytics?.gross_profit)}`}
                icon="spark"
                tone="success"
                hint="Sales value minus wholesale cost"
              />
              <StatCard
                label="Expenses"
                value={`KES ${money(analytics?.total_expenses)}`}
                icon="wallet"
                tone="danger"
                hint="Money out this month"
              />
              <StatCard
                label="Net profit"
                value={`KES ${money(analytics?.net_profit)}`}
                icon="arrowUpRight"
                tone={Number(analytics?.net_profit) >= 0 ? "success" : "danger"}
                emphasis
                hint="Gross profit minus expenses"
              />
            </div>
          )}

          <div
            className={cn(
              "grid gap-5",
              canManage ? "xl:grid-cols-3" : "xl:grid-cols-2",
            )}
          >
            {charts.map((chart) => (
              <Card key={chart.title} className="p-5">
                <DonutChart
                  title={chart.title}
                  subtitle={chart.subtitle}
                  data={chart.data}
                  labelKey={chart.labelKey}
                  valueKey={chart.valueKey}
                  centerLabel={chart.centerLabel}
                  emptyText={chart.emptyText}
                />
              </Card>
            ))}
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]">
            <Card>
              <CardHeader
                icon="dashboard"
                title="Weekly income"
                subtitle="Sales value versus money actually collected — last 8 weeks"
              />
              <div className="px-5 pb-5 pt-4">
                {weekly.length === 0 ? (
                  <p className="py-8 text-center text-sm text-ink-500">No weekly data yet.</p>
                ) : (
                  <div className="flex h-52 items-end gap-2 sm:gap-3">
                    {weekly.map((week) => (
                      <div key={week.week_start} className="flex min-w-0 flex-1 flex-col items-center gap-1">
                        <div className="flex h-40 w-full items-end justify-center gap-1">
                          <div
                            title={`Sales KES ${money(week.sales_total)}`}
                            className="w-2.5 rounded-t-md bg-sky-500/80 transition sm:w-3"
                            style={{
                              height: `${Math.max(2, (toCents(week.sales_total) / maxWeekly) * 100)}%`,
                            }}
                          />
                          <div
                            title={`Collected KES ${money(week.amount_collected)}`}
                            className="w-2.5 rounded-t-md bg-brand-500 transition sm:w-3"
                            style={{
                              height: `${Math.max(2, (toCents(week.amount_collected) / maxWeekly) * 100)}%`,
                            }}
                          />
                        </div>
                        <p className="text-[10px] font-medium text-ink-400">
                          {week.week_start.slice(5)}
                        </p>
                        <p className="hidden text-[10px] font-semibold tabular text-ink-600 sm:block">
                          {money(week.amount_collected)}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-4 flex flex-wrap gap-4 text-xs text-ink-500">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm bg-sky-500" /> Sales value
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm bg-brand-500" /> Cash collected
                  </span>
                </div>
              </div>
            </Card>

            <Card>
              <CardHeader
                icon="package"
                title="Needs restock"
                subtitle={`${lowStock.length} products at or below reorder level`}
                action={
                  <Link to="/inventory">
                    <Button variant="ghost" size="sm" iconRight="chevronRight">
                      Stock
                    </Button>
                  </Link>
                }
              />
              <div className="px-5 pb-5 pt-3">
                {lowStock.length === 0 ? (
                  <div className="flex items-center gap-3 rounded-xl bg-brand-50 px-4 py-3 text-sm text-brand-800">
                    <Icon name="checkCircle" size={18} />
                    Everything is well stocked.
                  </div>
                ) : (
                  <ul className="divide-y divide-ink-100">
                    {lowStock.slice(0, 6).map((product) => (
                      <li key={product.id} className="flex items-center justify-between gap-3 py-3">
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-50 text-red-500">
                            <Icon name="alert" size={15} />
                          </span>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-ink-900">{product.name}</p>
                            <p className="text-[11px] text-ink-400">
                              Reorder at {product.reorder_threshold}
                            </p>
                          </div>
                        </div>
                        <Badge tone="danger">{product.stock_quantity} left</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Card>
          </div>

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <Card className="overflow-hidden">
              <CardHeader
                icon="receipt"
                title="Daily records"
                subtitle="Every day with activity this month"
              />
              <div className="mt-4">
                {daily.length === 0 ? (
                  <EmptyState
                    icon="receipt"
                    title="No activity this month"
                    message="Sales and expenses will appear here as they are recorded."
                  />
                ) : (
                  <TableShell minWidth="560px">
                    <thead>
                      <tr>
                        <Th>Date</Th>
                        <Th align="right">Sales</Th>
                        {canManage && <Th align="right">Profit</Th>}
                        {canManage && <Th align="right">Expenses</Th>}
                        <Th align="right">Collected</Th>
                        <Th align="right">Units</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {daily.map((day) => (
                        <tr key={day.date} className="hover:bg-ink-50/70">
                          <Td className="font-medium text-ink-800">
                            {new Date(`${day.date}T00:00:00`).toLocaleDateString(undefined, {
                              weekday: "short",
                              day: "numeric",
                              month: "short",
                            })}
                          </Td>
                          <Td align="right" className="tabular">
                            {money(day.total_sales)}
                          </Td>
                          {canManage && (
                            <Td align="right" className="tabular text-emerald-700">
                              {money(day.gross_profit)}
                            </Td>
                          )}
                          {canManage && (
                            <Td align="right" className="tabular text-red-600">
                              {money(day.amount_spent || 0)}
                            </Td>
                          )}
                          <Td align="right" className="tabular text-sky-700">
                            {money(day.amount_collected)}
                          </Td>
                          <Td align="right" className="tabular text-ink-500">
                            {day.items_sold}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </TableShell>
                )}
              </div>
              {daily.length > 0 && (
                <div className="flex flex-wrap justify-end gap-4 border-t border-ink-100 bg-ink-50/60 px-5 py-3 text-xs font-semibold text-ink-600">
                  <span>Sales {money(fromCents(totals.sales))}</span>
                  {canManage && (
                    <span className="text-emerald-700">Profit {money(fromCents(totals.profit))}</span>
                  )}
                  {canManage && (
                    <span className="text-red-600">Expenses {money(fromCents(totals.spent))}</span>
                  )}
                  <span className="text-sky-700">Collected {money(fromCents(totals.collected))}</span>
                </div>
              )}
            </Card>

            <Card>
              <CardHeader
                icon="package"
                title="Product movement"
                subtitle="Units sold this month, highest first"
                action={
                  analytics?.top_product && (
                    <Badge tone="brand">Top: {analytics.top_product.product_name}</Badge>
                  )
                }
              />
              <div className="space-y-3 px-5 pb-4 pt-4">
                {movers.length === 0 ? (
                  <p className="py-6 text-center text-sm text-ink-500">
                    No products sold this month yet.
                  </p>
                ) : (
                  movers.slice(0, 8).map((product) => (
                    <div key={product.product_id}>
                      <div className="flex items-center justify-between gap-2 text-sm">
                        <span className="truncate font-medium text-ink-800">
                          {product.product_name}
                        </span>
                        <span className="shrink-0 font-semibold tabular text-ink-900">
                          {product.quantity_sold} units
                        </span>
                      </div>
                      <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink-100">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-brand-400 to-brand-600"
                          style={{ width: `${(product.quantity_sold / maxUnits) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))
                )}
              </div>
              {stagnant.length > 0 && (
                <div className="border-t border-ink-100 px-5 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-ink-400">
                    No movement ({analytics?.stagnant_count ?? stagnant.length})
                  </p>
                  <p className="mt-1 line-clamp-2 text-xs text-ink-500">
                    {stagnant.map((product) => product.name).join(" · ")}
                  </p>
                </div>
              )}
            </Card>
          </div>

          <Card className="overflow-hidden">
            <CardHeader
              icon="clock"
              title="Credit register"
              subtitle="Customers with an unpaid balance"
              action={
                <Link to="/transactions?tab=credits">
                  <Button variant="ghost" size="sm" iconRight="chevronRight">
                    Manage credits
                  </Button>
                </Link>
              }
            />
            <div className="mt-4">
              {credits.credits.length === 0 ? (
                <EmptyState
                  icon="checkCircle"
                  title="No outstanding credit"
                  message="Every receipt is fully settled."
                />
              ) : (
                <TableShell minWidth="640px">
                  <thead>
                    <tr>
                      <Th>Customer</Th>
                      <Th>Items</Th>
                      <Th>Date</Th>
                      <Th align="right">Balance</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {credits.credits.slice(0, 8).map((receipt) => (
                      <tr key={receipt.id} className="hover:bg-ink-50/70">
                        <Td>
                          <p className="font-semibold text-ink-900">
                            {receipt.customer_name || "Walk-in"}
                          </p>
                          <p className="text-xs text-ink-400">{receipt.customer_phone || "No phone"}</p>
                        </Td>
                        <Td className="max-w-72 truncate text-xs text-ink-500">
                          {receipt.items
                            .map((item) => `${item.quantity} × ${item.product_name}`)
                            .join(", ")}
                        </Td>
                        <Td className="text-xs text-ink-500">
                          {new Date(receipt.created_at).toLocaleDateString()}
                        </Td>
                        <Td align="right" className="font-bold tabular text-amber-700">
                          {money(receipt.balance)}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </TableShell>
              )}
            </div>
          </Card>

          <p className="text-center text-xs text-ink-400">
            Records are read-only once saved. Use Transactions to print, settle credit or prompt
            M-Pesa.
          </p>
        </>
      )}
    </div>
  );
}
