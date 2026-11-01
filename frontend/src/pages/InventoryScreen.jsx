import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { productsApi, apiErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { cleanMoney, cleanWholeNumber, money } from "../lib/format";
import Icon from "../components/Icon";
import {
  Alert,
  Badge,
  Button,
  Card,
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
  cn,
} from "../components/ui";

const PAGE_SIZE = 40;

const emptyForm = {
  name: "",
  sku: "",
  category: "",
  branch: "",
  cost_price: "",
  selling_price: "",
  stock_quantity: "",
  reorder_threshold: "5",
};

// Legacy products are stored with no branch and labelled "Main shop" by the API,
// so the dropdown only needs a blank entry when there is no MAIN branch row.
function branchChoices(branches) {
  if (branches.some((branch) => branch.code === "MAIN")) return branches;
  return [{ id: "", name: "Main shop" }, ...branches];
}

function mainBranchId(branches) {
  return branches.find((branch) => branch.code === "MAIN")?.id || "";
}

export default function InventoryScreen() {
  const { canManage, canManageUsers, branches, branchQuery, canViewAllBranches } = useAuth();
  const [catalog, setCatalog] = useState({ results: [], count: 0, next: null });
  const [categories, setCategories] = useState([]);
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [category, setCategory] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [status, setStatus] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [editing, setEditing] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [merging, setMerging] = useState(null);
  const requestId = useRef(0);

  const branchParams = useMemo(
    () => (branchQuery ? { branch: branchQuery } : {}),
    [branchQuery],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const id = requestId.current + 1;
    requestId.current = id;
    setLoading(true);
    productsApi
      .list({
        ...branchParams,
        q: debouncedSearch || undefined,
        category: category || undefined,
        low: lowOnly ? "1" : undefined,
        page_size: PAGE_SIZE,
      })
      .then((data) => {
        if (requestId.current === id) setCatalog(data);
      })
      .catch(() => {
        if (requestId.current === id) {
          setStatus({ type: "error", message: "Could not load inventory for this branch." });
        }
      })
      .finally(() => {
        if (requestId.current === id) setLoading(false);
      });
  }, [branchParams, debouncedSearch, category, lowOnly, refreshKey]);

  useEffect(() => {
    productsApi
      .categories(branchParams)
      .then(setCategories)
      .catch(() => setCategories([]));
    productsApi
      .overview(branchParams)
      .then(setOverview)
      .catch(() => setOverview(null));
  }, [branchParams, refreshKey]);

  const reload = useCallback(() => setRefreshKey((value) => value + 1), []);

  async function loadMore() {
    if (!catalog.next || loadingMore) return;
    setLoadingMore(true);
    try {
      const nextPage = await productsApi.page(catalog.next);
      setCatalog((current) => ({
        results: [...current.results, ...nextPage.results],
        count: nextPage.count,
        next: nextPage.next,
      }));
    } catch {
      setStatus({ type: "error", message: "Could not load more products." });
    } finally {
      setLoadingMore(false);
    }
  }

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(product) {
    setEditing(product);
    setFormOpen(true);
  }

  async function handleDelete(product) {
    if (!window.confirm(`Delete ${product.name}? This cannot be undone.`)) return;
    try {
      await productsApi.remove(product.id);
      setStatus({ type: "success", message: `${product.name} deleted.` });
      reload();
    } catch (error) {
      const message = apiErrorMessage(
        error,
        "Could not delete the product. It may have recorded sales.",
      );
      setStatus({
        type: "error",
        message:
          error?.response?.status === 409 && canManageUsers
            ? `${message} To remove a duplicate, use Merge.`
            : message,
      });
    }
  }

  const stats = useMemo(() => {
    const products = overview?.products ?? catalog.count ?? 0;
    return {
      products,
      units: overview?.units ?? 0,
      low: overview?.low ?? 0,
      costValue: overview?.cost_value ?? null,
      retailValue: overview?.retail_value ?? 0,
      categories: categories.length,
    };
  }, [overview, catalog.count, categories.length]);

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Stock control"
        title="Inventory"
        subtitle="Retail marked prices are a guide. The till only blocks a sale below the wholesale cost."
        actions={
          canManage && (
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" icon="upload" onClick={() => setImportOpen(true)}>
                Import CSV
              </Button>
              <Button variant="brand" icon="plus" onClick={openCreate}>
                Add product
              </Button>
            </div>
          )
        }
      />

      {status && (
        <Alert tone={status.type} onClose={() => setStatus(null)}>
          {status.message}
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="Products"
          value={stats.products.toLocaleString()}
          icon="package"
          hint={`${Number(stats.units).toLocaleString()} units on hand`}
        />
        <StatCard
          label="Needs restock"
          value={stats.low}
          icon="alert"
          tone={stats.low ? "danger" : "success"}
          hint={stats.low ? "At or below reorder level" : "All products healthy"}
        />
        {canManage && stats.costValue !== null ? (
          <StatCard
            label="Stock at wholesale"
            value={`KES ${money(stats.costValue)}`}
            icon="wallet"
            hint="Cash tied up in stock"
          />
        ) : (
          <StatCard
            label="Categories"
            value={stats.categories}
            icon="tag"
            tone="info"
            hint="Grouped product lines"
          />
        )}
        <StatCard
          label="Retail value"
          value={`KES ${money(stats.retailValue)}`}
          icon="spark"
          tone="brand"
          hint="If everything sells at the marked price"
        />
      </div>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-100 p-3">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search name, SKU or category..."
            className="min-w-0 flex-1 sm:max-w-xs"
          />
          <Select
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            className="w-full sm:w-44"
            aria-label="Filter by category"
          >
            <option value="">All categories</option>
            {categories.map((item) => (
              <option key={item.category} value={item.category}>
                {item.category} ({item.products})
              </option>
            ))}
          </Select>
          <button
            type="button"
            onClick={() => setLowOnly((value) => !value)}
            className={cn(
              "inline-flex h-10 items-center gap-2 rounded-xl border px-3 text-sm font-semibold transition",
              lowOnly
                ? "border-red-300 bg-red-50 text-red-700"
                : "border-ink-200 bg-white text-ink-600 hover:border-ink-300",
            )}
          >
            <Icon name="alert" size={15} />
            Low stock only
          </button>
          <span className="ml-auto text-xs text-ink-400">
            {loading ? "Searching..." : `${catalog.results.length} of ${catalog.count} shown`}
          </span>
        </div>

        {loading ? (
          <Spinner label="Loading inventory" />
        ) : catalog.results.length === 0 ? (
          <EmptyState
            icon="package"
            title={search || category || lowOnly ? "No products match this filter" : "No products yet"}
            message={
              search || category || lowOnly
                ? "Clear the search or filters to see more stock."
                : "Add a product manually or import your full price list from a CSV file."
            }
            action={
              canManage && !search && !category && !lowOnly ? (
                <div className="flex flex-wrap justify-center gap-2">
                  <Button variant="brand" icon="plus" onClick={openCreate}>
                    Add product
                  </Button>
                  <Button variant="secondary" icon="upload" onClick={() => setImportOpen(true)}>
                    Import CSV
                  </Button>
                </div>
              ) : null
            }
          />
        ) : (
          <>
            <TableShell minWidth="920px">
              <thead>
                <tr>
                  <Th>Product</Th>
                  <Th align="right">Stock</Th>
                  {canManage ? (
                    <Th align="right">Wholesale cost</Th>
                  ) : (
                    <Th align="right">Minimum sell</Th>
                  )}
                  <Th align="right">Retail price</Th>
                  {canManage && <Th align="right">Margin</Th>}
                  <Th align="right">Actions</Th>
                </tr>
              </thead>
              <tbody>
                {catalog.results.map((product) => {
                  const cost = Number(product.cost_price ?? product.price_floor ?? 0);
                  const price = Number(product.selling_price);
                  const margin = price > 0 ? ((price - cost) / price) * 100 : 0;
                  return (
                    <tr
                      key={product.id}
                      className={cn(
                        "transition hover:bg-ink-50/70",
                        product.needs_restock && "bg-red-50/40",
                      )}
                    >
                      <Td>
                        <div className="flex items-center gap-3">
                          <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-ink-100 text-xs font-bold text-ink-400">
                            {product.image ? (
                              <img
                                src={product.image}
                                alt=""
                                className="h-full w-full object-cover"
                                loading="lazy"
                              />
                            ) : (
                              (product.name || "?").slice(0, 2).toUpperCase()
                            )}
                          </span>
                          <div className="min-w-0">
                            <p className="truncate font-semibold text-ink-900">{product.name}</p>
                            <p className="text-xs text-ink-400">
                              {product.sku ? `${product.sku} · ` : ""}
                              {product.category || "Uncategorised"}
                              {canViewAllBranches ? ` · ${product.branch_name}` : ""}
                            </p>
                          </div>
                        </div>
                      </Td>
                      <Td align="right">
                        <div className="flex flex-col items-end">
                          <span
                            className={cn(
                              "text-sm font-bold tabular",
                              product.needs_restock ? "text-red-600" : "text-ink-900",
                            )}
                          >
                            {product.stock_quantity}
                          </span>
                          {product.needs_restock && <Badge tone="danger">Reorder</Badge>}
                        </div>
                      </Td>
                      <Td align="right" className="tabular text-ink-500">
                        {money(cost)}
                      </Td>
                      <Td align="right" className="tabular font-semibold text-ink-900">
                        {money(price)}
                      </Td>
                      {canManage && (
                        <Td align="right">
                          <span
                            className={cn(
                              "text-sm font-semibold tabular",
                              margin >= 25
                                ? "text-emerald-600"
                                : margin >= 10
                                  ? "text-amber-600"
                                  : "text-red-600",
                            )}
                          >
                            {margin.toFixed(1)}%
                          </span>
                        </Td>
                      )}
                      <Td align="right">
                        {canManage ? (
                          <div className="flex justify-end gap-1">
                            <IconButton
                              icon="edit"
                              label={`Edit ${product.name}`}
                              onClick={() => openEdit(product)}
                            />
                            {canManageUsers && (
                              <IconButton
                                icon="merge"
                                label={`Merge ${product.name} into another product`}
                                onClick={() => setMerging(product)}
                              />
                            )}
                            <IconButton
                              icon="trash"
                              label={`Delete ${product.name}`}
                              variant="dangerGhost"
                              onClick={() => handleDelete(product)}
                            />
                          </div>
                        ) : (
                          <span className="text-xs text-ink-300">View only</span>
                        )}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </TableShell>
            {catalog.next && (
              <div className="border-t border-ink-100 p-3 text-center">
                <Button variant="secondary" loading={loadingMore} onClick={loadMore}>
                  Load {Math.min(PAGE_SIZE, catalog.count - catalog.results.length)} more
                </Button>
              </div>
            )}
          </>
        )}
      </Card>

      {!canManage && (
        <p className="flex items-center gap-2 text-xs text-ink-500">
          <Icon name="lock" size={14} />
          You can view stock, retail prices and the minimum sell price. Only managers can change
          products or see wholesale costs.
        </p>
      )}

      <ProductFormModal
        open={formOpen}
        product={editing}
        branches={branches}
        canViewAllBranches={canViewAllBranches}
        defaultBranch={branchQuery}
        onClose={() => setFormOpen(false)}
        onSaved={(message) => {
          setFormOpen(false);
          setStatus({ type: "success", message });
          reload();
        }}
      />

      <ImportProductsModal
        open={importOpen}
        branches={branches}
        defaultBranch={branchQuery || branches[0]?.id || ""}
        canChooseBranch={canViewAllBranches}
        onClose={() => setImportOpen(false)}
        onImported={reload}
      />

      <MergeProductsModal
        open={Boolean(merging)}
        product={merging}
        canViewAllBranches={canViewAllBranches}
        onClose={() => setMerging(null)}
        onMerged={(outcome) => {
          setMerging(null);
          setStatus({
            type: "success",
            message: `Merged ${outcome.merged_name} into ${outcome.into.name}. ${outcome.stock_moved} units and ${outcome.sales_moved} recorded sales moved; the duplicate is gone.`,
          });
          reload();
        }}
      />
    </div>
  );
}

function ProductFormModal({ open, product, branches, canViewAllBranches, defaultBranch, onClose, onSaved }) {
  const [form, setForm] = useState(emptyForm);
  const [imageFile, setImageFile] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError("");
    setImageFile(null);
    if (product) {
      setForm({
        name: product.name || "",
        sku: product.sku || "",
        category: product.category || "",
        branch: product.branch || mainBranchId(branches),
        cost_price: product.cost_price ?? product.price_floor ?? "",
        selling_price: product.selling_price ?? "",
        stock_quantity: product.stock_quantity ?? "",
        reorder_threshold: product.reorder_threshold ?? 5,
      });
    } else {
      setForm({
        ...emptyForm,
        branch:
          defaultBranch ||
          (canViewAllBranches ? mainBranchId(branches) : branches[0]?.id || ""),
      });
    }
  }, [open, product, defaultBranch, canViewAllBranches, branches]);

  const cost = Number(form.cost_price) || 0;
  const selling = Number(form.selling_price) || 0;
  const belowCost = form.cost_price !== "" && form.selling_price !== "" && selling < cost;
  const margin = selling > 0 ? ((selling - cost) / selling) * 100 : 0;

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (!form.name.trim()) {
      setError("Enter the product name.");
      return;
    }
    if (!form.cost_price) {
      setError("Enter the wholesale cost.");
      return;
    }
    if (!form.selling_price) {
      setError("Enter the retail marked price.");
      return;
    }
    if (belowCost) {
      setError("The retail marked price cannot be below the wholesale cost.");
      return;
    }

    setSaving(true);
    const payload = {
      name: form.name.trim(),
      sku: form.sku.trim() || null,
      category: form.category.trim(),
      cost_price: Number(form.cost_price).toFixed(2),
      selling_price: Number(form.selling_price).toFixed(2),
      stock_quantity: Number(form.stock_quantity) || 0,
      reorder_threshold: Number(form.reorder_threshold) || 0,
      image: imageFile || undefined,
    };
    if (form.branch) payload.branch = form.branch;
    try {
      if (product) {
        // Tell the server the number this form opened with. Stock then moves by
        // the difference the manager typed, so a sale completed while the dialog
        // was open is not overwritten by a price edit.
        payload.stock_quantity_from = Number(product.stock_quantity) || 0;
        await productsApi.update(product.id, payload);
        onSaved(`${payload.name} updated.`);
      } else {
        await productsApi.create(payload);
        onSaved(`${payload.name} added to inventory.`);
      }
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not save the product."));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={product ? "Edit product" : "New product"}
      subtitle="Wholesale cost is the hard floor. The retail price is what you normally charge and can be discounted."
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="brand" loading={saving} onClick={submit} type="submit" form="product-form">
            {product ? "Save changes" : "Add product"}
          </Button>
        </>
      }
    >
      <form id="product-form" onSubmit={submit} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Product name" required className="sm:col-span-2">
            <Input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="e.g. LED bulb 9W"
              autoFocus
            />
          </Field>
          <Field label="SKU / barcode" hint="Unique within the branch. Scan-ready.">
            <Input
              value={form.sku}
              onChange={(event) => setForm({ ...form, sku: event.target.value })}
              placeholder="LED-9W"
            />
          </Field>
          <Field label="Category">
            <Input
              value={form.category}
              onChange={(event) => setForm({ ...form, category: event.target.value })}
              placeholder="Bulbs"
            />
          </Field>
          {branches.length > 0 && (
            <Field
              label="Branch"
              hint={canViewAllBranches ? "Where this stock sits." : "Your assigned branch."}
            >
              <Select
                value={form.branch}
                onChange={(event) => setForm({ ...form, branch: event.target.value })}
                disabled={!canViewAllBranches}
              >
                {branchChoices(branches).map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Field label="Product image" hint="JPG, PNG or WebP up to 5 MB.">
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(event) => setImageFile(event.target.files?.[0] || null)}
              className="block w-full text-sm text-ink-600 file:mr-3 file:rounded-lg file:border-0 file:bg-ink-100 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-ink-700 hover:file:bg-ink-200"
            />
            {imageFile && <p className="mt-1 text-xs text-ink-400">{imageFile.name}</p>}
          </Field>
          <Field label="Wholesale cost (KES)" required hint="The lowest the till will allow.">
            <Input
              inputMode="decimal"
              value={form.cost_price}
              onChange={(event) => setForm({ ...form, cost_price: cleanMoney(event.target.value) })}
              placeholder="0.00"
            />
          </Field>
          <Field label="Retail marked price (KES)" required hint="Normal selling price.">
            <Input
              inputMode="decimal"
              value={form.selling_price}
              onChange={(event) => setForm({ ...form, selling_price: cleanMoney(event.target.value) })}
              placeholder="0.00"
              className={cn(belowCost && "border-red-400 bg-red-50 text-red-700")}
            />
          </Field>
          <Field label="Stock quantity">
            <Input
              inputMode="numeric"
              value={form.stock_quantity}
              onChange={(event) =>
                setForm({ ...form, stock_quantity: cleanWholeNumber(event.target.value) })
              }
              placeholder="0"
            />
          </Field>
          <Field label="Reorder level" hint="Alert when stock falls to this number.">
            <Input
              inputMode="numeric"
              value={form.reorder_threshold}
              onChange={(event) =>
                setForm({ ...form, reorder_threshold: cleanWholeNumber(event.target.value) })
              }
              placeholder="5"
            />
          </Field>
        </div>

        {form.cost_price && form.selling_price && !belowCost && (
          <div className="flex items-center justify-between rounded-xl bg-brand-50 px-4 py-2.5 text-sm">
            <span className="text-brand-800">Profit per unit at retail price</span>
            <span className="font-semibold tabular text-brand-900">
              KES {money(selling - cost)} · {margin.toFixed(1)}% margin
            </span>
          </div>
        )}

        {error && <Alert tone="error">{error}</Alert>}
      </form>
    </Modal>
  );
}

function ImportProductsModal({ open, branches, defaultBranch, canChooseBranch, onClose, onImported }) {
  const [file, setFile] = useState(null);
  const [branch, setBranch] = useState(defaultBranch || mainBranchId(branches));
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setBranch(defaultBranch || mainBranchId(branches));
    setResult(null);
    setError("");
  }, [open, defaultBranch, branches]);

  async function downloadTemplate() {
    setDownloading(true);
    setError("");
    try {
      const blob = await productsApi.importTemplate();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "greenlight-products-template.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Could not download the template.");
    } finally {
      setDownloading(false);
    }
  }

  async function upload() {
    if (!file) {
      setError("Choose a CSV file first.");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const outcome = await productsApi.importCsv(file, branch || undefined);
      setResult(outcome);
      onImported();
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not import this file."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Import products from CSV"
      subtitle="Load hundreds of products at once. Existing SKUs in the branch are skipped."
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {result ? "Done" : "Cancel"}
          </Button>
          <Button variant="brand" loading={busy} icon="upload" onClick={upload}>
            Import file
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-ink-50 px-4 py-3 text-sm text-ink-600">
          <Icon name="clipboard" size={16} className="text-ink-400" />
          <span className="flex-1">
            Required columns: <strong>name</strong>, <strong>cost_price</strong>. Optional: sku,
            category, selling_price, stock_quantity, reorder_threshold.
          </span>
          <Button size="sm" variant="secondary" icon="download" loading={downloading} onClick={downloadTemplate}>
            Template
          </Button>
        </div>

        {branches.length > 0 && (
          <Field label="Import into branch" hint={canChooseBranch ? "Pick the shop receiving this stock." : "Your assigned branch."}>
            <Select
              value={branch}
              onChange={(event) => setBranch(event.target.value)}
              disabled={!canChooseBranch}
            >
              {branchChoices(branches).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <Field label="CSV file" required hint="UTF-8, up to 5 MB and 5,000 rows.">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
            className="block w-full text-sm text-ink-600 file:mr-3 file:rounded-lg file:border-0 file:bg-ink-100 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-ink-700 hover:file:bg-ink-200"
          />
          {file && <p className="mt-1 text-xs text-ink-400">{file.name}</p>}
        </Field>

        {error && <Alert tone="error">{error}</Alert>}

        {result && (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-xl bg-brand-50 px-3 py-2">
                <p className="text-[10px] font-bold uppercase text-brand-700">Created</p>
                <p className="font-display text-xl font-semibold text-brand-900">{result.created}</p>
              </div>
              <div className="rounded-xl bg-amber-50 px-3 py-2">
                <p className="text-[10px] font-bold uppercase text-amber-700">Skipped</p>
                <p className="font-display text-xl font-semibold text-amber-900">{result.skipped}</p>
              </div>
              <div className="rounded-xl bg-red-50 px-3 py-2">
                <p className="text-[10px] font-bold uppercase text-red-700">Errors</p>
                <p className="font-display text-xl font-semibold text-red-900">{result.error_count}</p>
              </div>
            </div>
            {result.errors?.length > 0 && (
              <div className="scrollbar-thin max-h-48 overflow-y-auto rounded-xl border border-red-100 bg-red-50/60 p-3">
                <p className="mb-2 text-xs font-bold uppercase tracking-wide text-red-700">
                  Rows that need attention
                </p>
                <ul className="space-y-1 text-xs text-red-800">
                  {result.errors.map((row) => (
                    <li key={`${row.row}-${row.message}`}>
                      Row {row.row}: {row.message}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-xs text-ink-500">
              Imported into <strong>{result.branch}</strong>. Refresh the list to see the new stock.
            </p>
          </div>
        )}
      </div>
    </Modal>
  );
}

function MergeProductsModal({ open, product, canViewAllBranches, onClose, onMerged }) {
  const [choices, setChoices] = useState([]);
  const [query, setQuery] = useState("");
  const [targetId, setTargetId] = useState("");
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const searchId = useRef(0);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setTargetId("");
    setError("");
    setChoices([]);
  }, [open, product?.id]);

  // Search the whole branch rather than only the page currently on screen, so a
  // duplicate can be merged into a product found further down the list.
  useEffect(() => {
    if (!open) return;
    const id = searchId.current + 1;
    searchId.current = id;
    const timer = window.setTimeout(() => {
      setSearching(true);
      productsApi
        .list({
          q: query.trim() || undefined,
          branch: product?.branch || undefined,
          page_size: 40,
        })
        .then((data) => {
          if (searchId.current !== id) return;
          setChoices(data.results.filter((item) => item.id !== product?.id));
        })
        .catch(() => {
          if (searchId.current === id) setChoices([]);
        })
        .finally(() => {
          if (searchId.current === id) setSearching(false);
        });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [open, query, product]);

  const target = choices.find((item) => item.id === targetId) || null;
  const pricesDiffer =
    target &&
    (String(target.selling_price) !== String(product?.selling_price) ||
      String(target.cost_price) !== String(product?.cost_price));

  async function submit() {
    if (!target) {
      setError("Choose the product you want to keep.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      onMerged(await productsApi.merge(product.id, target.id));
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "Could not merge these products."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Merge duplicate product"
      subtitle="Use this when the same item was entered twice under different names. The stock and sales history move into the product you keep."
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="brand" icon="merge" loading={busy} onClick={submit}>
            Merge and remove the duplicate
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="rounded-xl border border-red-200 bg-red-50/70 px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-wide text-red-700">Remove this entry</p>
          <p className="mt-0.5 font-semibold text-ink-900">{product?.name}</p>
          <p className="text-xs text-ink-500">
            {product?.sku ? `${product.sku} · ` : ""}
            {product?.stock_quantity ?? 0} units · wholesale {money(product?.cost_price ?? 0)} ·
            retail {money(product?.selling_price ?? 0)}
          </p>
        </div>

        <Field
          label="Keep this product"
          required
          hint="Every sale and unit from the duplicate is moved onto this one."
        >
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="Search the product to keep..."
            className="mb-2"
          />
          <Select
            value={targetId}
            onChange={(event) => setTargetId(event.target.value)}
            disabled={searching && choices.length === 0}
          >
            <option value="">
              {searching ? "Searching..." : `${choices.length ? "Choose a product" : "No products found"}`}
            </option>
            {choices.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
                {item.sku ? ` · ${item.sku}` : ""} · {item.stock_quantity} units
                {canViewAllBranches ? ` · ${item.branch_name}` : ""}
              </option>
            ))}
          </Select>
        </Field>

        {target && (
          <div className="rounded-xl border border-ink-200 bg-ink-50 px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-ink-500">
              Product you keep
            </p>
            <p className="mt-0.5 font-semibold text-ink-900">{target.name}</p>
            <p className="text-xs text-ink-500">
              {target.sku ? `${target.sku} · ` : ""}
              {target.stock_quantity} units · wholesale {money(target.cost_price ?? 0)} · retail{" "}
              {money(target.selling_price)}
            </p>
            <p className="mt-2 text-sm font-semibold text-brand-900">
              Stock after the merge:{" "}
              {Number(product?.stock_quantity ?? 0) + Number(target.stock_quantity ?? 0)} units
            </p>
            {pricesDiffer && (
              <p className="mt-2 flex items-start gap-2 text-xs text-amber-800">
                <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
                The two entries have different prices. The kept product keeps its own prices, so
                check them if you want the merged stock sold differently.
              </p>
            )}
          </div>
        )}

        <p className="flex items-start gap-2 text-xs text-ink-500">
          <Icon name="receipt" size={14} className="mt-0.5 shrink-0" />
          Receipts are not rewritten or lost. Old sales simply show under the product you keep, so
          your totals stay the same.
        </p>

        {error && <Alert tone="error">{error}</Alert>}
      </div>
    </Modal>
  );
}
