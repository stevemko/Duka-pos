import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { receiptsApi, apiErrorMessage, queryString } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { cleanMoney, money } from "../lib/format";
import Icon from "../components/Icon";
import PrintableReceipt from "../components/PrintableReceipt";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  Modal,
  PageHeader,
  SearchInput,
  Select,
  Spinner,
  StatCard,
  TableShell,
  Tabs,
  Td,
  Th,
  statusLabel,
  statusTone,
} from "../components/ui";

const statusOptions = [
  { id: "", label: "All statuses" },
  { id: "paid", label: "Paid" },
  { id: "partially_paid", label: "Partially paid" },
  { id: "on_credit", label: "On credit" },
  { id: "payment_pending", label: "M-Pesa pending" },
];

const datePresets = [
  { id: "today", label: "Today" },
  { id: "yesterday", label: "Yesterday" },
  { id: "week", label: "Last 7 days" },
  { id: "month", label: "This month" },
  { id: "all", label: "All time" },
  { id: "custom", label: "Custom" },
];

function isoDate(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")}`;
}

// Named periods are resolved by the server from the shop's clock. Dates worked
// out on a till whose machine is in another zone would silently move a day's
// trade into the next report.
function presetRange(preset, customStart, customEnd) {
  const periods = { today: "today", yesterday: "yesterday", week: "last7", month: "month" };
  if (periods[preset]) return { period: periods[preset] };
  if (preset === "all") return { period: "all" };
  return { start_date: customStart || undefined, end_date: customEnd || undefined };
}

function formatDateTime(value) {
  return new Date(value).toLocaleString("en-KE", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function shortId(id) {
  return String(id).slice(0, 8).toUpperCase();
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function TransactionsScreen() {
  const { branchQuery, canViewAllBranches, activeBranch, canManageUsers } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") === "credits" ? "credits" : "receipts";

  const [preset, setPreset] = useState("today");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const [periodDialog, setPeriodDialog] = useState(false);

  const [receipts, setReceipts] = useState([]);
  const [nextUrl, setNextUrl] = useState(null);
  const [credits, setCredits] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const range = useMemo(
    () => presetRange(preset, customStart, customEnd),
    [preset, customStart, customEnd],
  );

  const receiptParams = useMemo(
    () => ({
      ...(tab === "receipts" ? range : {}),
      ...(tab === "receipts" && status ? { status } : {}),
      ...(debouncedSearch ? { q: debouncedSearch } : {}),
      ...(branchQuery ? { branch: branchQuery } : {}),
      ...(tab === "receipts" && showClosed && canManageUsers ? { include_closed: "1" } : {}),
    }),
    [tab, range, status, debouncedSearch, branchQuery, showClosed, canManageUsers],
  );

  const loadReceipts = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const page = tab === "credits"
        ? await receiptsApi.credits(receiptParams)
        : await receiptsApi.page(`/receipts/${queryString(receiptParams)}`);
      if (tab === "credits") {
        setCredits(page);
        setReceipts(page.credits || []);
        setNextUrl(null);
      } else {
        setReceipts(page.results);
        setNextUrl(page.next);
        setCredits(null);
      }
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load transactions. Check the server and try again."));
      setReceipts([]);
      setNextUrl(null);
    } finally {
      setLoading(false);
    }
  }, [tab, receiptParams]);

  useEffect(() => {
    loadReceipts();
  }, [loadReceipts]);

  async function loadMore() {
    if (!nextUrl || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await receiptsApi.page(nextUrl);
      setReceipts((current) => [...current, ...page.results]);
      setNextUrl(page.next);
    } catch {
      setError("Could not load more transactions.");
    } finally {
      setLoadingMore(false);
    }
  }

  async function exportCsv() {
    setExporting(true);
    setError("");
    try {
      const params = tab === "receipts" ? receiptParams : { ...receiptParams };
      const blob = await receiptsApi.exportCsv(params);
      downloadBlob(blob, `transactions-${isoDate(new Date())}.csv`);
    } catch {
      setError("Could not export the transactions file.");
    } finally {
      setExporting(false);
    }
  }

  function updateSelected(receipt) {
    setSelected(receipt);
    setReceipts((current) =>
      current.map((entry) => (entry.id === receipt.id ? receipt : entry)),
    );
  }

  const visibleTotals = useMemo(
    () =>
      receipts.reduce(
        (totals, receipt) => ({
          total: totals.total + Number(receipt.total || 0),
          paid: totals.paid + Number(receipt.amount_paid || 0),
          balance: totals.balance + Number(receipt.balance || 0),
        }),
        { total: 0, paid: 0, balance: 0 },
      ),
    [receipts],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Records"
        title="Daily transactions"
        subtitle={
          activeBranch
            ? `Receipts recorded at ${activeBranch.name}. Every sale, payment and balance is kept forever.`
            : canViewAllBranches
              ? "All receipts across branches. Filter by date, status or customer."
              : "Every sale, payment and outstanding balance recorded by this shop."
        }
        actions={
          <>
            <Button variant="secondary" icon="refresh" onClick={loadReceipts}>
              Refresh
            </Button>
            {canManageUsers && (
              <Button variant="secondary" icon="lock" onClick={() => setPeriodDialog(true)}>
                Close period
              </Button>
            )}
            <Button icon="download" loading={exporting} onClick={exportCsv}>
              Export CSV
            </Button>
          </>
        }
      />

      {error && (
        <Alert tone="error" title="Records unavailable" onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label={tab === "credits" ? "Outstanding credit" : "Sales in view"}
          value={`KES ${money(tab === "credits" ? credits?.outstanding_total : visibleTotals.total)}`}
          icon="receipt"
          tone="brand"
        />
        <StatCard
          label={tab === "credits" ? "Customers owing" : "Collected in view"}
          value={tab === "credits" ? credits?.customer_count ?? 0 : `KES ${money(visibleTotals.paid)}`}
          icon="wallet"
          tone="success"
        />
        <StatCard
          label={tab === "credits" ? "Credit receipts" : "Balance in view"}
          value={tab === "credits" ? credits?.receipt_count ?? 0 : `KES ${money(visibleTotals.balance)}`}
          icon="clock"
          tone="warning"
        />
        <StatCard
          label="Receipts in view"
          value={receipts.length}
          hint="Scroll the list or load more for the full range."
          icon="clipboard"
          tone="info"
        />
      </div>

      <Card>
        <CardHeader
          title="Transaction ledger"
          subtitle={
            tab === "receipts"
              ? "Filter the period you want to review, then export it for your books."
              : "Customers with an unpaid balance. Record a payment from any row."
          }
          action={
            <Button
              size="sm"
              variant="secondary"
              icon="download"
              loading={exporting}
              onClick={exportCsv}
            >
              CSV
            </Button>
          }
        />

        <div className="space-y-4 px-5 pb-5 pt-4">
          <Tabs
            items={[
              { id: "receipts", label: "All receipts" },
              {
                id: "credits",
                label: "Credits & balances",
                count: credits?.receipt_count,
              },
            ]}
            value={tab}
            onChange={(nextTab) => {
              const params = new URLSearchParams(searchParams);
              if (nextTab === "credits") params.set("tab", "credits");
              else params.delete("tab");
              setSearchParams(params, { replace: true });
            }}
          />

          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px_190px]">
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search customer name or phone..."
            />
            {tab === "receipts" ? (
              <>
                <Select value={preset} onChange={(event) => setPreset(event.target.value)}>
                  {datePresets.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </Select>
                <Select value={status} onChange={(event) => setStatus(event.target.value)}>
                  {statusOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </>
            ) : (
              <div className="lg:col-span-2 flex items-center rounded-xl bg-amber-50 px-3 text-xs font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
                Credits are listed for all dates, including old balances.
              </div>
            )}
            <div className="flex items-center gap-2 rounded-xl bg-ink-100/70 px-3 text-xs font-semibold text-ink-600">
              <Icon name="store" size={14} className="text-ink-400" />
              {activeBranch?.name || (canViewAllBranches ? "All branches" : "Your branch")}
            </div>
          </div>

          {canManageUsers && tab === "receipts" && (
            <label className="flex w-fit items-center gap-2 text-xs font-semibold text-ink-600">
              <input
                type="checkbox"
                checked={showClosed}
                onChange={(event) => setShowClosed(event.target.checked)}
              />
              Show receipts from closed periods
            </label>
          )}

          {preset === "custom" && tab === "receipts" && (
            <div className="grid gap-3 sm:grid-cols-2 lg:max-w-md">
              <Field label="From">
                <Input
                  type="date"
                  value={customStart}
                  onChange={(event) => setCustomStart(event.target.value)}
                />
              </Field>
              <Field label="To">
                <Input
                  type="date"
                  value={customEnd}
                  onChange={(event) => setCustomEnd(event.target.value)}
                />
              </Field>
            </div>
          )}
        </div>

        {loading ? (
          <Spinner label="Loading receipts" />
        ) : receipts.length === 0 ? (
          <EmptyState
            icon="receipt"
            title={tab === "credits" ? "No outstanding balances" : "No receipts for this filter"}
            message={
              tab === "credits"
                ? "Every customer has cleared their balance. New credit sales will appear here."
                : showClosed || !canManageUsers
                  ? "Try a wider date range or clear the search and status filters."
                  : "Try a wider date range or clear the filters. Bills from a period the owner closed stay out of this list until 'Show receipts from closed periods' is ticked."
            }
          />
        ) : (
          <>
            <TableShell minWidth="900px">
              <thead>
                <tr>
                  <Th>Receipt</Th>
                  <Th>Date</Th>
                  <Th>Customer</Th>
                  <Th>Items</Th>
                  <Th align="right">Total</Th>
                  <Th align="right">Paid</Th>
                  <Th align="right">Balance</Th>
                  <Th>Status</Th>
                  <Th>Branch</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {receipts.map((receipt) => (
                  <tr key={receipt.id} className="transition-colors hover:bg-ink-50/70">
                    <Td className="font-semibold text-ink-900">
                      {shortId(receipt.id)}
                      {receipt.closed_at && (
                        <Badge tone="neutral" className="ml-2">
                          closed
                        </Badge>
                      )}
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-ink-500">
                      {formatDateTime(receipt.created_at)}
                    </Td>
                    <Td>
                      <p className="font-medium text-ink-800">
                        {receipt.customer_name || "Walk-in customer"}
                      </p>
                      <p className="text-xs text-ink-400">
                        {receipt.customer_phone || "No phone"}
                      </p>
                    </Td>
                    <Td className="max-w-56 truncate text-xs text-ink-500">
                      {receipt.items.map((item) => `${item.quantity}× ${item.product_name}`).join(", ")}
                    </Td>
                    <Td align="right" className="tabular whitespace-nowrap">
                      KES {money(receipt.total)}
                    </Td>
                    <Td align="right" className="tabular whitespace-nowrap text-emerald-700">
                      KES {money(receipt.amount_paid)}
                    </Td>
                    <Td
                      align="right"
                      className={`tabular whitespace-nowrap ${
                        Number(receipt.balance) > 0 ? "font-semibold text-amber-700" : "text-ink-400"
                      }`}
                    >
                      KES {money(receipt.balance)}
                    </Td>
                    <Td>
                      <Badge tone={statusTone(receipt.payment_status)} dot>
                        {statusLabel(receipt.payment_status)}
                      </Badge>
                    </Td>
                    <Td className="whitespace-nowrap text-xs text-ink-500">
                      {receipt.branch_name || "Main shop"}
                    </Td>
                    <Td align="right">
                      <Button
                        size="sm"
                        variant="secondary"
                        iconRight="chevronRight"
                        onClick={() => setSelected(receipt)}
                      >
                        Open
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </TableShell>

            {nextUrl && (
              <div className="flex justify-center border-t border-ink-100 px-5 py-4">
                <Button variant="secondary" loading={loadingMore} onClick={loadMore}>
                  Load more receipts
                </Button>
              </div>
            )}
          </>
        )}
      </Card>

      <ReceiptDetail
        key={selected?.id || "none"}
        receipt={selected}
        onClose={() => setSelected(null)}
        onUpdated={updateSelected}
        onRefresh={loadReceipts}
      />

      {periodDialog && (
        <ClosePeriodDialog
          branchQuery={branchQuery}
          onClose={() => setPeriodDialog(false)}
          onClosed={loadReceipts}
        />
      )}
    </div>
  );
}

function ClosePeriodDialog({ onClose, branchQuery, onClosed }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [notice, setNotice] = useState(null);

  const yesterday = useMemo(() => {
    const day = new Date();
    day.setDate(day.getDate() - 1);
    return isoDate(day);
  }, []);

  function period() {
    if (!end) return null;
    return {
      ...(start ? { start_date: start } : {}),
      end_date: end,
      ...(branchQuery ? { branch: branchQuery } : {}),
    };
  }

  async function downloadCsv() {
    const body = period();
    if (!body) {
      setNotice({ tone: "error", message: "Pick the last day of the period first." });
      return;
    }
    setDownloading(true);
    try {
      const blob = await receiptsApi.exportCsv(body);
      downloadBlob(blob, `transactions-${body.start_date || "start"}-to-${body.end_date}.csv`);
      setNotice(null);
    } catch {
      setNotice({ tone: "error", message: "Could not download the file for that period." });
    } finally {
      setDownloading(false);
    }
  }

  async function closePeriod(undo) {
    const body = period();
    if (!body) {
      setNotice({
        tone: "error",
        message: "Pick the last day of the period you want to put away.",
      });
      return;
    }
    setBusy(true);
    setNotice(null);
    try {
      const result = await receiptsApi.closePeriod({
        ...body,
        ...(undo ? { undo: "true" } : {}),
      });
      onClosed();
      setNotice(
        undo
          ? { tone: "success", message: `${result.reopened} receipt(s) are back in the daily list.` }
          : {
              tone: "success",
              message: result.left_open
                ? `${result.closed} settled receipt(s) put away. ${result.left_open} still owed stay in the list.`
                : `${result.closed} settled receipt(s) put away. Nothing owed was hidden.`,
            },
      );
    } catch (requestError) {
      setNotice({ tone: "error", message: apiErrorMessage(requestError, "Could not close that period.") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Close a trading period"
      subtitle="Settled bills leave the daily list. Totals, credit and the receipts themselves are kept."
      footer={
        <>
          <Button variant="ghost" onClick={() => closePeriod(true)} disabled={busy}>
            Reopen it instead
          </Button>
          <Button variant="secondary" icon="download" loading={downloading} onClick={downloadCsv}>
            Export first
          </Button>
          <Button icon="lock" loading={busy} onClick={() => closePeriod(false)}>
            Close period
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="From (optional)">
            <Input
              type="date"
              value={start}
              max={end || yesterday}
              onChange={(event) => setStart(event.target.value)}
            />
          </Field>
          <Field label="Last day of the period" required hint="Today is still being traded, so it cannot be closed.">
            <Input
              type="date"
              value={end}
              max={yesterday}
              onChange={(event) => setEnd(event.target.value)}
            />
          </Field>
        </div>

        {notice && <Alert tone={notice.tone}>{notice.message}</Alert>}

        <p className="rounded-xl bg-ink-50 px-4 py-3 text-xs text-ink-600">
          Download the period before closing it and keep the file. A closed bill is still on the
          books and can still be paid; only the daily list stops showing it.
        </p>
      </div>
    </Modal>
  );
}

function ReceiptDetail({ receipt, onClose, onUpdated, onRefresh }) {
  const [mode, setMode] = useState("view");
  const [amount, setAmount] = useState(receipt ? String(receipt.balance || "") : "");
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [phone, setPhone] = useState(receipt?.customer_phone || "");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);
  const [printReceipt, setPrintReceipt] = useState(null);
  const [stkPolling, setStkPolling] = useState(false);

  // A printed receipt holds a customer's phone number. Unmount it once the print
  // dialog closes so a later Ctrl+P cannot reprint someone else's sale.
  useEffect(() => {
    if (!printReceipt) return undefined;
    const clear = () => setPrintReceipt(null);
    window.addEventListener("afterprint", clear);
    return () => window.removeEventListener("afterprint", clear);
  }, [printReceipt]);

  if (!receipt) return null;

  const balance = Number(receipt.balance || 0);

  function print() {
    setPrintReceipt(receipt);
    window.setTimeout(() => window.print(), 100);
  }

  async function recordPayment(event) {
    event.preventDefault();
    setNotice(null);
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0 || value > balance) {
      setNotice({ tone: "error", message: "Enter an amount within the outstanding balance." });
      return;
    }
    setSaving(true);
    try {
      const updated = await receiptsApi.addPayment(receipt.id, {
        amount: value.toFixed(2),
        method,
        ...(reference.trim() ? { reference: reference.trim() } : {}),
      });
      onUpdated(updated);
      setMode("view");
      setNotice({ tone: "success", message: "Payment recorded and the balance updated." });
      onRefresh?.();
    } catch (requestError) {
      setNotice({
        tone: "error",
        message: apiErrorMessage(requestError, "Could not record the payment."),
      });
    } finally {
      setSaving(false);
    }
  }

  function pollStk(attempt = 0) {
    if (attempt >= 12) {
      setStkPolling(false);
      setNotice({
        tone: "warning",
        message: "The M-Pesa prompt is still pending. Refresh this receipt in a minute to confirm.",
      });
      return;
    }
    window.setTimeout(async () => {
      try {
        const fresh = await receiptsApi.get(receipt.id);
        onUpdated(fresh);
        const latest = fresh.payments.at(-1);
        if (latest?.status === "pending") {
          pollStk(attempt + 1);
          return;
        }
        setStkPolling(false);
        if (latest?.status === "succeeded") {
          setNotice({ tone: "success", message: `M-Pesa payment confirmed. Code ${latest.reference}.` });
          onRefresh?.();
        } else {
          setNotice({
            tone: "error",
            message: latest?.result_description || "The M-Pesa payment was not completed.",
          });
        }
      } catch {
        if (attempt < 11) pollStk(attempt + 1);
        else setStkPolling(false);
      }
    }, 5000);
  }

  async function sendStk(event) {
    event.preventDefault();
    setNotice(null);
    if (!phone.trim()) {
      setNotice({ tone: "error", message: "Enter the customer's M-Pesa phone number." });
      return;
    }
    setSaving(true);
    try {
      const response = await receiptsApi.stkPush(receipt.id, {
        phone: phone.trim(),
        amount: balance.toFixed(2),
      });
      onUpdated(response.receipt);
      setMode("view");
      setStkPolling(true);
      setNotice({
        tone: "info",
        message: "Prompt sent. Ask the customer to enter their M-Pesa PIN. This page checks automatically.",
      });
      pollStk();
    } catch (requestError) {
      setNotice({
        tone: "error",
        message: apiErrorMessage(requestError, "Could not send the M-Pesa prompt."),
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Modal
        open
        onClose={onClose}
        size="lg"
        title={`Receipt ${shortId(receipt.id)}`}
        subtitle={`${formatDateTime(receipt.created_at)} · ${receipt.branch_name || "Main shop"}`}
        footer={
          <>
            <Button variant="secondary" icon="printer" onClick={print}>
              Print
            </Button>
            {balance > 0 && mode === "view" && (
              <>
                <Button variant="secondary" icon="spark" onClick={() => setMode("stk")}>
                  M-Pesa prompt
                </Button>
                <Button icon="wallet" onClick={() => setMode("payment")}>
                  Record payment
                </Button>
              </>
            )}
          </>
        }
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 rounded-xl bg-ink-50 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink-900">
                {receipt.customer_name || "Walk-in customer"}
              </p>
              <p className="text-xs text-ink-500">
                {receipt.customer_phone || "No phone recorded"} · Served by{" "}
                {receipt.created_by_name || "counter"}
              </p>
            </div>
            <Badge tone={statusTone(receipt.payment_status)} dot>
              {statusLabel(receipt.payment_status)}
            </Badge>
          </div>

          {notice && <Alert tone={notice.tone}>{notice.message}</Alert>}
          {stkPolling && (
            <div className="flex items-center gap-2 rounded-xl bg-sky-50 px-4 py-3 text-sm text-sky-800 ring-1 ring-inset ring-sky-200">
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-sky-600 border-t-transparent" />
              Waiting for M-Pesa confirmation...
            </div>
          )}

          <TableShell minWidth="420px">
            <thead>
              <tr>
                <Th>Item</Th>
                <Th align="right">Qty</Th>
                <Th align="right">Unit price</Th>
                <Th align="right">Line total</Th>
              </tr>
            </thead>
            <tbody>
              {receipt.items.map((item) => (
                <tr key={item.id}>
                  <Td className="font-medium text-ink-800">{item.product_name}</Td>
                  <Td align="right" className="tabular">
                    {item.quantity}
                  </Td>
                  <Td align="right" className="tabular">
                    KES {money(item.price_sold_at)}
                  </Td>
                  <Td align="right" className="tabular font-semibold">
                    KES {money(item.total)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableShell>

          <div className="grid gap-3 rounded-xl border border-ink-100 bg-white p-4 text-sm sm:grid-cols-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-ink-400">Total</p>
              <p className="tabular mt-1 text-lg font-semibold text-ink-950">KES {money(receipt.total)}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-ink-400">Paid</p>
              <p className="tabular mt-1 text-lg font-semibold text-emerald-700">
                KES {money(receipt.amount_paid)}
              </p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wide text-ink-400">Balance</p>
              <p className={`tabular mt-1 text-lg font-semibold ${balance > 0 ? "text-amber-700" : "text-ink-950"}`}>
                KES {money(receipt.balance)}
              </p>
            </div>
          </div>

          {receipt.payments.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-400">
                Payment history
              </p>
              <ul className="divide-y divide-ink-100 rounded-xl border border-ink-100">
                {receipt.payments.map((payment) => (
                  <li key={payment.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
                    <div className="min-w-0">
                      <p className="font-medium capitalize text-ink-800">
                        {payment.method.replaceAll("_", " ")}
                        {payment.reference ? ` · ${payment.reference}` : ""}
                      </p>
                      <p className="text-xs text-ink-400">
                        {formatDateTime(payment.created_at)}
                        {payment.created_by_name ? ` · ${payment.created_by_name}` : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge tone={statusTone(payment.status)}>{payment.status}</Badge>
                      <span className="tabular font-semibold text-ink-900">KES {money(payment.amount)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {mode === "payment" && (
            <form onSubmit={recordPayment} className="space-y-3 rounded-xl border border-brand-200 bg-brand-50/50 p-4">
              <p className="text-sm font-semibold text-ink-900">Record a payment</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Amount (KES)" required>
                  <Input
                    inputMode="decimal"
                    value={amount}
                    onChange={(event) => setAmount(cleanMoney(event.target.value))}
                    autoFocus
                  />
                </Field>
                <Field label="Method">
                  <Select value={method} onChange={(event) => setMethod(event.target.value)}>
                    <option value="cash">Cash</option>
                    <option value="mobile_money">Mobile money</option>
                    <option value="card">Card</option>
                    <option value="bank_transfer">Bank transfer</option>
                  </Select>
                </Field>
                <Field label="Reference (optional)" className="sm:col-span-2">
                  <Input
                    value={reference}
                    onChange={(event) => setReference(event.target.value)}
                    placeholder="M-Pesa code, receipt no..."
                  />
                </Field>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setMode("view")}>
                  Cancel
                </Button>
                <Button type="submit" loading={saving}>
                  Save payment
                </Button>
              </div>
            </form>
          )}

          {mode === "stk" && (
            <form onSubmit={sendStk} className="space-y-3 rounded-xl border border-sky-200 bg-sky-50/60 p-4">
              <p className="text-sm font-semibold text-ink-900">Send an M-Pesa prompt</p>
              <p className="text-xs text-ink-500">
                The customer receives a prompt on their phone for KES {money(balance)}.
              </p>
              <Field label="M-Pesa phone" required hint="Format: 07XX XXX XXX or 2547XXXXXXXX.">
                <Input
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                  inputMode="tel"
                  autoFocus
                  placeholder="0712 345 678"
                />
              </Field>
              <div className="flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setMode("view")}>
                  Cancel
                </Button>
                <Button type="submit" icon="phone" loading={saving && !stkPolling}>
                  Send prompt
                </Button>
              </div>
            </form>
          )}
        </div>
      </Modal>

      {printReceipt && <PrintableReceipt receipt={printReceipt} />}
    </>
  );
}
