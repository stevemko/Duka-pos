import { useCallback, useEffect, useMemo, useState } from "react";
import { apiErrorMessage, customersApi } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { cleanMoney, money } from "../lib/format";
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
  Td,
  Th,
} from "../components/ui";

const methods = [
  { id: "cash", label: "Cash" },
  { id: "mobile_money", label: "Mobile money" },
  { id: "mpesa_paybill", label: "M-Pesa Paybill" },
  { id: "card", label: "Card" },
  { id: "bank_transfer", label: "Bank transfer" },
];

function day(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" });
}

function emptyForm() {
  return { name: "", phone: "", credit_limit: "", notes: "" };
}

export default function CreditScreen() {
  const { branchQuery, canManage } = useAuth();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [onlyOwing, setOnlyOwing] = useState(false);
  const [customers, setCustomers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  const [paying, setPaying] = useState(null);
  const [payment, setPayment] = useState({ amount: "", method: "cash", reference: "" });
  const [viewing, setViewing] = useState(null);
  const [ledger, setLedger] = useState(null);
  const [ledgerLoading, setLedgerLoading] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const params = useMemo(
    () => ({
      ...(debouncedSearch ? { search: debouncedSearch } : {}),
      ...(onlyOwing ? { owing: "1" } : {}),
      ...(branchQuery ? { branch: branchQuery } : {}),
    }),
    [debouncedSearch, onlyOwing, branchQuery],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const page = await customersApi.list(params);
      setCustomers(page.results);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not load the credit book."));
      setCustomers([]);
    } finally {
      setLoading(false);
    }
  }, [params]);

  useEffect(() => {
    load();
  }, [load]);

  const totals = useMemo(() => {
    const owed = customers.reduce((sum, customer) => sum + Number(customer.outstanding || 0), 0);
    const debtors = customers.filter((customer) => Number(customer.outstanding) > 0).length;
    return { owed, debtors };
  }, [customers]);

  function startAdd() {
    setEditing(null);
    setForm(emptyForm());
    setStatus(null);
    setFormOpen(true);
  }

  function startEdit(customer) {
    setEditing(customer);
    setForm({
      name: customer.name,
      phone: customer.phone || "",
      credit_limit: customer.credit_limit ? String(customer.credit_limit) : "",
      notes: customer.notes || "",
    });
    setStatus(null);
    setFormOpen(true);
  }

  async function submit(event) {
    event.preventDefault();
    setStatus(null);
    if (!form.name.trim()) {
      setStatus({ tone: "error", message: "Enter the customer's name." });
      return;
    }
    const limit = form.credit_limit.trim();
    if (limit && !(Number(limit) > 0)) {
      setStatus({ tone: "error", message: "A credit limit must be a number above zero, or blank." });
      return;
    }
    setSaving(true);
    const payload = {
      name: form.name.trim(),
      phone: form.phone.trim(),
      // Blank means "no ceiling", which the shop chooses on purpose.
      credit_limit: limit ? Number(limit).toFixed(2) : null,
      notes: form.notes.trim(),
    };
    try {
      if (editing) {
        await customersApi.update(editing.id, payload);
      } else {
        await customersApi.create(payload);
      }
      setFormOpen(false);
      setEditing(null);
      setStatus({ tone: "success", message: editing ? "Account updated." : "Account opened." });
      await load();
    } catch (requestError) {
      setStatus({
        tone: "error",
        message: apiErrorMessage(requestError, "Could not save the account."),
      });
    } finally {
      setSaving(false);
    }
  }

  function openPayment(customer) {
    setPaying(customer);
    setPayment({ amount: String(customer.outstanding), method: "cash", reference: "" });
  }

  async function takePayment(event) {
    event.preventDefault();
    const amount = Number(payment.amount);
    if (!(amount > 0)) {
      setStatus({ tone: "error", message: "Enter the amount handed in." });
      return;
    }
    setSaving(true);
    try {
      const result = await customersApi.pay(paying.id, {
        amount: amount.toFixed(2),
        method: payment.method,
        reference: payment.reference.trim(),
      });
      setPaying(null);
      setStatus({
        tone: "success",
        message: `KES ${money(amount)} received. ${paying.name} now owes KES ${money(
          result.still_owing,
        )}.`,
      });
      await load();
    } catch (requestError) {
      setStatus({
        tone: "error",
        message: apiErrorMessage(requestError, "Could not record the payment."),
      });
    } finally {
      setSaving(false);
    }
  }

  async function openLedger(customer) {
    setViewing(customer);
    setLedger(null);
    setLedgerLoading(true);
    try {
      setLedger(await customersApi.ledger(customer.id));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not read this account."));
      setViewing(null);
    } finally {
      setLedgerLoading(false);
    }
  }

  async function closeAccount(customer) {
    if (!window.confirm(`Close ${customer.name}'s account? Sales already on the book stay visible.`)) {
      return;
    }
    try {
      const result = await customersApi.remove(customer.id);
      setStatus({
        tone: "success",
        message: typeof result === "string" ? result : "Account closed.",
      });
      await load();
    } catch (requestError) {
      setStatus({
        tone: "error",
        message: apiErrorMessage(requestError, "Could not close the account."),
      });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Money not yet in"
        title="Credit book"
        subtitle="Every account the shop has lent goods to, with the bills behind the balance. A payment here settles the oldest receipt first."
        actions={<Button icon="plus" onClick={startAdd}>New account</Button>}
      />

      {status && !formOpen && !paying && (
        <Alert tone={status.tone} onClose={() => setStatus(null)}>
          {status.message}
        </Alert>
      )}
      {error && (
        <Alert tone="error" title="Credit book unavailable" onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <StatCard
          label="Owed to the shop"
          value={`KES ${money(totals.owed)}`}
          icon="wallet"
          tone="danger"
          emphasis
        />
        <StatCard
          label="Accounts still owing"
          value={totals.debtors}
          hint={`${customers.length} account(s) listed`}
          icon="users"
          tone="info"
        />
      </div>

      <Card>
        <CardHeader
          title="Accounts"
          subtitle="Search by name or phone number. The number is how a till finds the right book."
          icon="users"
          action={
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-2 text-xs font-semibold text-ink-600">
                <input
                  type="checkbox"
                  checked={onlyOwing}
                  onChange={(event) => setOnlyOwing(event.target.checked)}
                />
                Only owing
              </label>
              <SearchInput
                value={search}
                onChange={setSearch}
                placeholder="Name or 07XXXXXXXX"
              />
            </div>
          }
        />
        <div className="px-5 pb-5">
          {loading ? (
            <Spinner label="Loading the book" />
          ) : customers.length === 0 ? (
            <EmptyState
              icon="users"
              title="No accounts match"
              message="Nobody on this filter, or the shop has not lent goods to a named customer yet."
            />
          ) : (
            <TableShell minWidth="760px">
              <thead>
                <tr>
                  <Th>Customer</Th>
                  <Th>Phone</Th>
                  <Th align="right">Owes</Th>
                  <Th align="right">Credit limit</Th>
                  <Th>Last purchase</Th>
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {customers.map((customer) => {
                  const owed = Number(customer.outstanding) > 0;
                  return (
                    <tr key={customer.id}>
                      <Td>
                        <span className="font-semibold text-ink-800">{customer.name}</span>
                        {!customer.is_active && (
                          <Badge tone="neutral" className="ml-2">
                            Closed
                          </Badge>
                        )}
                      </Td>
                      <Td className="tabular">{customer.phone || "-"}</Td>
                      <Td align="right">
                        <span
                          className={
                            owed
                              ? "font-bold tabular text-rose-700"
                              : "tabular text-ink-500"
                          }
                        >
                          KES {money(customer.outstanding)}
                        </span>
                      </Td>
                      <Td align="right" className="tabular">
                        {customer.credit_limit ? `KES ${money(customer.credit_limit)}` : "None"}
                      </Td>
                      <Td>{day(customer.last_purchase)}</Td>
                      <Td align="right">
                        <div className="flex justify-end gap-2">
                          <Button variant="ghost" onClick={() => openLedger(customer)}>
                            Ledger
                          </Button>
                          {/* Whoever is handed the money records it; only a manager
                              moves the ceiling or closes the account. */}
                          {owed && (
                            <Button onClick={() => openPayment(customer)}>Take payment</Button>
                          )}
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableShell>
          )}
        </div>
      </Card>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? `Edit ${editing.name}` : "New credit account"}
        subtitle="The name and number print on receipts only as typed at the counter; this book is what they owe."
      >
        <form onSubmit={submit} className="space-y-4">
          {status && formOpen && (
            <Alert tone={status.tone} onClose={() => setStatus(null)}>
              {status.message}
            </Alert>
          )}
          <Field label="Name" required>
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="Amina Hassan"
            />
          </Field>
          <Field label="Phone" hint="Two accounts cannot share one number in the same shop.">
            <Input
              value={form.phone}
              onChange={(event) => setForm({ ...form, phone: event.target.value })}
              placeholder="07XXXXXXXX"
              type="tel"
            />
          </Field>
          <Field
            label="Credit limit"
            hint={
              canManage
                ? "Leave blank for no ceiling. A sale past this number is refused at the till."
                : "Only a manager sets or changes this."
            }
            error={form.credit_limit && !canManage ? "Managers only" : ""}
          >
            <Input
              value={form.credit_limit}
              onChange={(event) =>
                setForm({ ...form, credit_limit: cleanMoney(event.target.value) })
              }
              inputMode="decimal"
              disabled={!canManage}
              placeholder="Blank means no limit"
            />
          </Field>
          <Field label="Notes">
            <Input
              value={form.notes}
              onChange={(event) => setForm({ ...form, notes: event.target.value })}
              placeholder="Pays every Friday"
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" type="button" onClick={() => setFormOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              {editing ? "Save account" : "Open account"}
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(paying)}
        onClose={() => setPaying(null)}
        title={`Payment from ${paying?.name || ""}`}
        subtitle={`Owes KES ${money(paying?.outstanding)}. Money goes against the oldest bills first.`}
      >
        <form onSubmit={takePayment} className="space-y-4">
          {status && paying && (
            <Alert tone={status.tone} onClose={() => setStatus(null)}>
              {status.message}
            </Alert>
          )}
          <Field label="Amount" required>
            <Input
              value={payment.amount}
              onChange={(event) =>
                setPayment({ ...payment, amount: cleanMoney(event.target.value) })
              }
              inputMode="decimal"
            />
          </Field>
          <Field label="Method">
            <Select
              value={payment.method}
              onChange={(event) => setPayment({ ...payment, method: event.target.value })}
            >
              {methods.map((method) => (
                <option key={method.id} value={method.id}>
                  {method.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Reference"
            hint="The M-Pesa code or slip number, so the payment can be proved later."
          >
            <Input
              value={payment.reference}
              onChange={(event) => setPayment({ ...payment, reference: event.target.value })}
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" type="button" onClick={() => setPaying(null)}>
              Cancel
            </Button>
            <Button type="submit" loading={saving}>
              Record payment
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(viewing)}
        onClose={() => {
          setViewing(null);
          setLedger(null);
        }}
        title={`${viewing?.name || ""} · account`}
        subtitle="Every bill and every payment, oldest first, with what was owed after each one."
        size="lg"
        footer={
          canManage && viewing?.is_active ? (
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  setViewing(null);
                  setLedger(null);
                  startEdit(viewing);
                }}
              >
                Edit details
              </Button>
              <Button variant="danger" onClick={() => closeAccount(viewing)}>
                Close account
              </Button>
            </>
          ) : null
        }
      >
        {ledgerLoading ? (
          <Spinner label="Reading the book" />
        ) : !ledger ? null : (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <span>
                Owes{" "}
                <strong className="tabular text-rose-700">
                  KES {money(ledger.customer.outstanding)}
                </strong>
              </span>
              <span>
                Limit{" "}
                <strong className="tabular">
                  {ledger.customer.credit_limit
                    ? `KES ${money(ledger.customer.credit_limit)}`
                    : "None"}
                </strong>
              </span>
              <span>
                Phone <strong>{ledger.customer.phone || "-"}</strong>
              </span>
            </div>
            {ledger.entries.length === 0 ? (
              <p className="text-sm text-ink-500">Nothing on this account yet.</p>
            ) : (
              <TableShell minWidth="620px">
                <thead>
                  <tr>
                    <Th>Date</Th>
                    <Th>Entry</Th>
                    <Th align="right">Added to debt</Th>
                    <Th align="right">Taken off debt</Th>
                    <Th align="right">Owed after</Th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.entries.map((entry, index) => (
                    <tr key={`${entry.reference}-${index}`}>
                      <Td>{day(entry.date)}</Td>
                      <Td>
                        {entry.type === "sale"
                          ? "Goods billed"
                          : entry.type === "return"
                            ? "Goods returned"
                            : "Payment"}
                        <span className="block text-xs text-ink-500">{entry.description}</span>
                      </Td>
                      <Td align="right" className="tabular">
                        {Number(entry.debit) > 0 ? money(entry.debit) : "-"}
                      </Td>
                      <Td align="right" className="tabular">
                        {Number(entry.credit) > 0 ? money(entry.credit) : "-"}
                      </Td>
                      <Td align="right" className="font-semibold tabular">
                        {money(entry.balance)}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </TableShell>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
