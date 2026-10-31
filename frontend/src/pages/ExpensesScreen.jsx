import { useEffect, useMemo, useState } from "react";
import { apiErrorMessage, expensesApi } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { cleanMoney, currentMonth, money } from "../lib/format";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  IconButton,
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
  Textarea,
} from "../components/ui";

const categories = [
  { id: "rent", label: "Rent" },
  { id: "utilities", label: "Utilities" },
  { id: "salaries", label: "Salaries" },
  { id: "stock", label: "Stock purchases" },
  { id: "transport", label: "Transport" },
  { id: "maintenance", label: "Maintenance" },
  { id: "marketing", label: "Marketing" },
  { id: "other", label: "Other" },
];

const methods = [
  { id: "cash", label: "Cash" },
  { id: "mobile_money", label: "Mobile money" },
  { id: "card", label: "Card" },
  { id: "bank_transfer", label: "Bank transfer" },
];

function categoryLabel(value) {
  return categories.find((category) => category.id === value)?.label || value;
}

function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
}

function emptyForm(branchId) {
  return {
    date: today(),
    category: "stock",
    description: "",
    amount: "",
    payment_method: "cash",
    reference: "",
    branch: branchId || "",
  };
}

export default function ExpensesScreen() {
  const { branchQuery, branches, activeBranch, canManage, canViewAllBranches } = useAuth();
  // A branch-less record is stored against the main shop, so the form always
  // carries a real branch id instead of an ambiguous blank choice.
  const expenseBranchDefault =
    branchQuery || branches.find((branch) => branch.code === "MAIN")?.id || "";
  const [month, setMonth] = useState(currentMonth);
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [expenses, setExpenses] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(emptyForm(expenseBranchDefault));
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const params = useMemo(
    () => ({
      month,
      ...(category ? { category } : {}),
      ...(debouncedSearch ? { search: debouncedSearch } : {}),
      ...(branchQuery ? { branch: branchQuery } : {}),
    }),
    [month, category, debouncedSearch, branchQuery],
  );

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    Promise.all([expensesApi.list(params), expensesApi.summary(params)])
      .then(([list, totals]) => {
        if (!active) return;
        setExpenses(list);
        setSummary(totals);
      })
      .catch((requestError) => {
        if (!active) return;
        setError(apiErrorMessage(requestError, "Could not load expenses."));
        setExpenses([]);
        setSummary(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [params]);

  function startAdd() {
    setEditing(null);
    setForm(emptyForm(expenseBranchDefault));
    setStatus(null);
    setFormOpen(true);
  }

  function startEdit(expense) {
    setEditing(expense);
    setForm({
      date: expense.date,
      category: expense.category,
      description: expense.description,
      amount: String(expense.amount),
      payment_method: expense.payment_method,
      reference: expense.reference || "",
      branch: expense.branch || expenseBranchDefault,
    });
    setStatus(null);
    setFormOpen(true);
  }

  async function submit(event) {
    event.preventDefault();
    setStatus(null);
    const amount = Number(form.amount);
    if (!form.description.trim()) {
      setStatus({ tone: "error", message: "Describe what the money was spent on." });
      return;
    }
    if (!Number.isFinite(amount) || amount <= 0) {
      setStatus({ tone: "error", message: "Enter an expense amount greater than zero." });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        date: form.date,
        category: form.category,
        description: form.description.trim(),
        amount: amount.toFixed(2),
        payment_method: form.payment_method,
        reference: form.reference.trim(),
        ...(form.branch ? { branch: form.branch } : {}),
      };
      if (editing) {
        await expensesApi.update(editing.id, payload);
      } else {
        await expensesApi.create(payload);
      }
      setFormOpen(false);
      setEditing(null);
      setStatus({
        tone: "success",
        message: editing ? "Expense updated." : "Expense recorded.",
      });
      const [list, totals] = await Promise.all([
        expensesApi.list(params),
        expensesApi.summary(params),
      ]);
      setExpenses(list);
      setSummary(totals);
    } catch (requestError) {
      setStatus({
        tone: "error",
        message: apiErrorMessage(requestError, "Could not save the expense."),
      });
    } finally {
      setSaving(false);
    }
  }

  async function remove(expense) {
    if (!window.confirm(`Delete this ${categoryLabel(expense.category).toLowerCase()} expense of KES ${money(expense.amount)}?`)) {
      return;
    }
    try {
      await expensesApi.remove(expense.id);
      setStatus({ tone: "success", message: "Expense deleted." });
      const [list, totals] = await Promise.all([
        expensesApi.list(params),
        expensesApi.summary(params),
      ]);
      setExpenses(list);
      setSummary(totals);
    } catch (requestError) {
      setStatus({
        tone: "error",
        message: apiErrorMessage(requestError, "Could not delete the expense."),
      });
    }
  }

  const breakdown = summary?.by_category || [];
  const maxCategory = Math.max(1, ...breakdown.map((row) => Number(row.total)));
  const average = summary?.entries ? Number(summary.total) / summary.entries : 0;

  if (!canManage) {
    return (
      <Alert tone="warning" title="Managers only">
        Expenses record money leaving the business, so only manager accounts can view or change them.
      </Alert>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Money out"
        title="Expenses"
        subtitle={
          activeBranch
            ? `Costs recorded for ${activeBranch.name}. Every entry reduces the month's net profit.`
            : "Rent, salaries, stock purchases and every other cost of running the shops."
        }
        actions={
          <Button icon="plus" onClick={startAdd}>
            Record expense
          </Button>
        }
      />

      {status && !formOpen && (
        <Alert tone={status.tone} onClose={() => setStatus(null)}>
          {status.message}
        </Alert>
      )}
      {error && (
        <Alert tone="error" title="Expenses unavailable" onClose={() => setError("")}>
          {error}
        </Alert>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Spent this month"
          value={`KES ${money(summary?.total)}`}
          icon="wallet"
          tone="danger"
          emphasis
        />
        <StatCard label="Entries" value={summary?.entries ?? 0} icon="clipboard" tone="neutral" />
        <StatCard
          label="Largest category"
          value={breakdown[0] ? categoryLabel(breakdown[0].category) : "None"}
          hint={breakdown[0] ? `KES ${money(breakdown[0].total)}` : "No expenses yet"}
          icon="filter"
          tone="warning"
        />
        <StatCard
          label="Average entry"
          value={`KES ${money(average)}`}
          hint="Total divided by number of entries"
          icon="dashboard"
          tone="info"
        />
      </div>

      <Card>
        <CardHeader
          title="Where the money went"
          subtitle="Category totals for the selected month and filters."
          icon="filter"
        />
        <div className="px-5 pb-5 pt-4">
          {breakdown.length === 0 ? (
            <p className="text-sm text-ink-500">No expenses match these filters.</p>
          ) : (
            <div className="space-y-3">
              {breakdown.map((row) => (
                <div
                  key={row.category}
                  className="grid grid-cols-[minmax(0,1fr)_minmax(80px,2fr)_auto] items-center gap-3 text-sm"
                >
                  <span className="truncate font-medium text-ink-700">
                    {categoryLabel(row.category)}
                  </span>
                  <div className="h-2.5 overflow-hidden rounded-full bg-ink-100">
                    <div
                      className="h-full rounded-full bg-brand-600"
                      style={{ width: `${(Number(row.total) / maxCategory) * 100}%` }}
                    />
                  </div>
                  <span className="tabular whitespace-nowrap text-right text-xs font-semibold text-ink-800">
                    KES {money(row.total)} · {row.entries}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Expense register"
          subtitle="Newest entries first. Edit or delete an entry if it was recorded wrongly."
          icon="wallet"
        />
        <div className="grid gap-3 px-5 pb-4 pt-4 lg:grid-cols-[160px_190px_minmax(0,1fr)]">
          <Field label="Month">
            <Input type="month" value={month} onChange={(event) => setMonth(event.target.value || currentMonth())} />
          </Field>
          <Field label="Category">
            <Select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option value="">All categories</option>
              {categories.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Search">
            <SearchInput value={search} onChange={setSearch} placeholder="Search description..." />
          </Field>
        </div>

        {loading ? (
          <Spinner label="Loading expenses" />
        ) : expenses.length === 0 ? (
          <EmptyState
            icon="wallet"
            title="No expenses recorded"
            message="Record rent, salaries, stock purchases and other costs so profit reports stay accurate."
            action={<Button icon="plus" onClick={startAdd}>Record expense</Button>}
          />
        ) : (
          <TableShell minWidth="860px">
            <thead>
              <tr>
                <Th>Date</Th>
                <Th>Category</Th>
                <Th>Description</Th>
                <Th>Method</Th>
                <Th>Reference</Th>
                <Th>Branch</Th>
                <Th>Recorded by</Th>
                <Th align="right">Amount</Th>
                <Th align="right">Actions</Th>
              </tr>
            </thead>
            <tbody>
              {expenses.map((expense) => (
                <tr key={expense.id} className="transition-colors hover:bg-ink-50/70">
                  <Td className="whitespace-nowrap text-xs text-ink-500">{expense.date}</Td>
                  <Td>
                    <Badge tone="neutral">{categoryLabel(expense.category)}</Badge>
                  </Td>
                  <Td className="max-w-64">
                    <p className="truncate font-medium text-ink-800">{expense.description}</p>
                  </Td>
                  <Td className="whitespace-nowrap text-xs capitalize text-ink-500">
                    {expense.method_label || expense.payment_method.replaceAll("_", " ")}
                  </Td>
                  <Td className="whitespace-nowrap text-xs text-ink-500">
                    {expense.reference || "—"}
                  </Td>
                  <Td className="whitespace-nowrap text-xs text-ink-500">
                    {expense.branch_name || "Main shop"}
                  </Td>
                  <Td className="whitespace-nowrap text-xs text-ink-500">
                    {expense.recorded_by_name || "—"}
                  </Td>
                  <Td align="right" className="tabular whitespace-nowrap font-semibold text-ink-900">
                    KES {money(expense.amount)}
                  </Td>
                  <Td align="right">
                    <div className="flex justify-end gap-1">
                      <IconButton icon="edit" label="Edit expense" onClick={() => startEdit(expense)} />
                      <IconButton
                        icon="trash"
                        label="Delete expense"
                        variant="dangerGhost"
                        onClick={() => remove(expense)}
                      />
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </TableShell>
        )}
      </Card>

      <Modal
        open={formOpen}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        title={editing ? "Edit expense" : "Record expense"}
        subtitle="Money out is subtracted from gross profit to show the month's net profit."
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                setFormOpen(false);
                setEditing(null);
              }}
            >
              Cancel
            </Button>
            <Button type="submit" form="expense-form" loading={saving}>
              {editing ? "Save changes" : "Record expense"}
            </Button>
          </>
        }
      >
        <form id="expense-form" onSubmit={submit} className="space-y-3">
          {status?.tone === "error" && <Alert tone="error">{status.message}</Alert>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Date" required>
              <Input
                type="date"
                value={form.date}
                onChange={(event) => setForm({ ...form, date: event.target.value })}
              />
            </Field>
            <Field label="Category" required>
              <Select
                value={form.category}
                onChange={(event) => setForm({ ...form, category: event.target.value })}
              >
                {categories.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Amount (KES)" required className="sm:col-span-2">
              <Input
                inputMode="decimal"
                value={form.amount}
                onChange={(event) => setForm({ ...form, amount: cleanMoney(event.target.value) })}
                placeholder="0.00"
              />
            </Field>
            <Field label="Description" required className="sm:col-span-2">
              <Textarea
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
                placeholder="e.g. Monthly rent for October"
              />
            </Field>
            <Field label="Paid with">
              <Select
                value={form.payment_method}
                onChange={(event) => setForm({ ...form, payment_method: event.target.value })}
              >
                {methods.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field
              label="Branch"
              hint={canViewAllBranches && branches.length > 1 ? "Which shop paid?" : undefined}
            >
              <Select
                value={form.branch}
                onChange={(event) => setForm({ ...form, branch: event.target.value })}
                disabled={!canViewAllBranches}
              >
                {(canViewAllBranches
                  ? branches
                  : branches.filter((branch) => branch.id === activeBranch?.id)
                ).map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Reference (optional)" className="sm:col-span-2">
              <Input
                value={form.reference}
                onChange={(event) => setForm({ ...form, reference: event.target.value })}
                placeholder="Receipt no, M-Pesa code, invoice..."
              />
            </Field>
          </div>
        </form>
      </Modal>
    </div>
  );
}
