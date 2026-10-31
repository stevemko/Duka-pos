import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { productsApi, receiptsApi, salesApi, apiErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { fromCents, money, toCents } from "../lib/format";
import PrintableReceipt from "../components/PrintableReceipt";
import { Alert, Badge, Select } from "../components/ui";
import ProductPicker from "../components/sales/ProductPicker";
import BasketPanel from "../components/sales/BasketPanel";
import PaymentPanel from "../components/sales/PaymentPanel";
import RecentReceipts from "../components/sales/RecentReceipts";
import ReceiptSuccessCard from "../components/sales/ReceiptSuccessCard";
import StkModal from "../components/sales/StkModal";
import SettlePaymentModal from "../components/sales/SettlePaymentModal";

const PAGE_SIZE = 40;
const DRAFT_KEY = "duka_pos_draft_sale";

const SETTLED_LABELS = {
  cash: "Cash",
  mobile_money: "Mobile money",
  mpesa_stk: "M-Pesa",
  mpesa_paybill: "M-Pesa Paybill",
  card: "Card",
  bank_transfer: "Bank transfer",
};

// A half-entered sale is real work: the counter must not lose it to a page
// refresh, an idle sign-out or a lost connection.
function readSavedDraft() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null");
    return saved && Array.isArray(saved.cart) ? saved : null;
  } catch {
    return null;
  }
}

function floorOf(product) {
  return Number(product?.price_floor ?? product?.cost_price ?? 0);
}

// Daraja replies with terse internal phrasing such as "DS timeout user cannot be
// reached", which reads like a system log to a cashier.
function safaricomReason(text) {
  const cleaned = String(text || "")
    .replace(/^ds\s+/i, "")
    .trim()
    .replace(/\.+$/, "");
  if (!cleaned) return "";
  return `${cleaned.charAt(0).toUpperCase()}${cleaned.slice(1)}.`;
}

export default function SalesScreen() {
  const { branches, branchQuery, canViewAllBranches, user, shop } = useAuth();
  const [savedDraft] = useState(readSavedDraft);
  const [catalog, setCatalog] = useState({ results: [], count: 0, next: null });
  const [known, setKnown] = useState({});
  const [categories, setCategories] = useState([]);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [category, setCategory] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [cart, setCart] = useState(savedDraft?.cart ?? []);
  const [customerName, setCustomerName] = useState(savedDraft?.customerName ?? "");
  const [customerPhone, setCustomerPhone] = useState(savedDraft?.customerPhone ?? "");
  const [paymentMode, setPaymentMode] = useState(savedDraft?.paymentMode ?? "paid");
  const [partialAmount, setPartialAmount] = useState("");
  const [paymentMethod, setPaymentMethod] = useState("cash");
  const [paymentReference, setPaymentReference] = useState("");
  const [cashReceived, setCashReceived] = useState("");
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState(null);
  const [lastReceipt, setLastReceipt] = useState(null);
  const [printReceipt, setPrintReceipt] = useState(null);
  const [recentReceipts, setRecentReceipts] = useState([]);
  const [manualBranch, setManualBranch] = useState("");
  const [stkTarget, setStkTarget] = useState(null);
  const [stkPhone, setStkPhone] = useState("");
  const [payStatus, setPayStatus] = useState(null);
  const [sendingStk, setSendingStk] = useState(false);
  const [checkingPay, setCheckingPay] = useState(false);
  const [settleTarget, setSettleTarget] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const checkoutKeyRef = useRef("");
  const payTimerRef = useRef(0);
  const requestId = useRef(0);

  const fallbackBranchId = branches.find((branch) => branch.is_active)?.id || "";
  const sellingBranchId = branchQuery || manualBranch || fallbackBranchId;
  const sellingBranch = branches.find((branch) => branch.id === sellingBranchId) || null;
  const branchParams = useMemo(
    () => (sellingBranchId ? { branch: sellingBranchId } : {}),
    [sellingBranchId],
  );

  useEffect(() => {
    if (branchQuery) setManualBranch("");
  }, [branchQuery]);

  useEffect(() => {
    if (cart.length === 0 && !customerName && !customerPhone) {
      sessionStorage.removeItem(DRAFT_KEY);
      return;
    }
    sessionStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ cart, customerName, customerPhone, paymentMode }),
    );
  }, [cart, customerName, customerPhone, paymentMode]);

  useEffect(() => {
    if (savedDraft?.cart?.length) {
      setStatus((current) =>
        current || {
          type: "warning",
          message: "Your unfinished sale was restored after the page reloaded. Check the basket before completing it.",
        },
      );
    }
    // Only on mount: the restored draft must be announced exactly once.
  }, [savedDraft]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const rememberProducts = useCallback((products) => {
    setKnown((current) => {
      const next = { ...current };
      products.forEach((product) => {
        next[product.id] = product;
      });
      return next;
    });
  }, []);

  useEffect(() => {
    const id = requestId.current + 1;
    requestId.current = id;
    setLoadingProducts(true);
    productsApi
      .list({
        ...branchParams,
        q: debouncedSearch || undefined,
        category: category || undefined,
        low: lowOnly ? "1" : undefined,
        page_size: PAGE_SIZE,
      })
      .then((page) => {
        if (requestId.current !== id) return;
        setCatalog(page);
        rememberProducts(page.results);
      })
      .catch(() => {
        if (requestId.current === id) {
          setCatalog({ results: [], count: 0, next: null });
          setStatus({ type: "error", message: "Could not load products for this branch." });
        }
      })
      .finally(() => {
        if (requestId.current === id) setLoadingProducts(false);
      });
  }, [branchParams, debouncedSearch, category, lowOnly, refreshKey, rememberProducts]);

  useEffect(() => {
    productsApi
      .categories(branchParams)
      .then(setCategories)
      .catch(() => setCategories([]));
  }, [branchParams]);

  const previousBranchRef = useRef(sellingBranchId);

  useEffect(() => {
    const previous = previousBranchRef.current;
    previousBranchRef.current = sellingBranchId;
    // Branches arrive after the first render, so an empty previous value is the
    // app loading rather than the cashier switching shop. Clearing here would
    // also wipe a basket restored from the saved draft.
    if (!previous || previous === sellingBranchId) return;
    stopPayWatch();
    setCart([]);
    setLastReceipt(null);
    setStatus(null);
    setPayStatus(null);
    checkoutKeyRef.current = "";
  }, [sellingBranchId]);

  useEffect(() => stopPayWatch, []);

  const loadRecentReceipts = useCallback(async () => {
    try {
      const params = new URLSearchParams({ page_size: "6" });
      if (sellingBranchId) params.set("branch", sellingBranchId);
      const page = await receiptsApi.page(`/receipts/?${params.toString()}`);
      setRecentReceipts(page.results);
    } catch {
      setRecentReceipts([]);
    }
  }, [sellingBranchId]);

  useEffect(() => {
    loadRecentReceipts();
  }, [loadRecentReceipts]);

  const productMap = useMemo(
    () => new Map(Object.values(known).map((product) => [product.id, product])),
    [known],
  );

  const cartQuantities = useMemo(
    () => new Map(cart.map((item) => [item.product, Number(item.quantity) || 0])),
    [cart],
  );

  const totalCents = cart.reduce(
    (sum, item) => sum + toCents(item.price_sold_at) * (Number(item.quantity) || 0),
    0,
  );
  const itemCount = cart.reduce((sum, item) => sum + (Number(item.quantity) || 0), 0);

  const blocked = cart.some((item) => {
    const floor = floorOf(productMap.get(item.product));
    return floor > 0 && toCents(item.price_sold_at) < toCents(floor);
  });

  const tenderedCents =
    paymentMode === "paid"
      ? totalCents
      : paymentMode === "partial"
        ? toCents(partialAmount)
        : 0;

  function invalidateKey() {
    checkoutKeyRef.current = "";
  }

  function addProduct(product) {
    if (!product || product.stock_quantity < 1) return;
    setStatus(null);
    invalidateKey();
    setCart((items) => {
      const existing = items.find((item) => item.product === product.id);
      if (existing) {
        if (existing.quantity >= product.stock_quantity) return items;
        return items.map((item) =>
          item.product === product.id ? { ...item, quantity: item.quantity + 1 } : item,
        );
      }
      return [
        ...items,
        {
          product: product.id,
          quantity: 1,
          price_sold_at: String(
            product.selling_price ?? product.price_floor ?? product.cost_price ?? "",
          ),
        },
      ];
    });
  }

  async function handleScan(term) {
    const value = term.trim();
    if (!value) return;
    try {
      const page = await productsApi.list({ ...branchParams, sku: value, page_size: 5 });
      if (page.results.length === 1) {
        addProduct(page.results[0]);
        rememberProducts(page.results);
        setSearch("");
        return;
      }
      setStatus({
        type: "warning",
        message: `No exact SKU match for "${value}". Showing name matches below.`,
      });
    } catch {
      setStatus({ type: "error", message: "Could not look up that SKU right now." });
    }
  }

  async function loadMoreProducts() {
    if (!catalog.next || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await productsApi.page(catalog.next);
      setCatalog((current) => ({
        ...page,
        results: [...current.results, ...page.results],
      }));
      rememberProducts(page.results);
    } catch {
      setStatus({ type: "error", message: "Could not load more products." });
    } finally {
      setLoadingMore(false);
    }
  }

  function updateCartItem(productId, changes) {
    invalidateKey();
    setCart((items) =>
      items.map((item) => (item.product === productId ? { ...item, ...changes } : item)),
    );
  }

  function removeCartItem(productId) {
    invalidateKey();
    setCart((items) => items.filter((item) => item.product !== productId));
  }

  function resetCheckout() {
    setCart([]);
    setCustomerName("");
    setCustomerPhone("");
    setPaymentMode("paid");
    setPartialAmount("");
    setPaymentMethod("cash");
    setPaymentReference("");
    setCashReceived("");
    invalidateKey();
  }

  function clearBasket() {
    resetCheckout();
    setStatus(null);
  }

  function changePaymentMode(mode) {
    setPaymentMode(mode);
    setPartialAmount("");
    setCashReceived("");
    setPaymentReference("");
    invalidateKey();
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (loading) return;
    setStatus(null);
    setLastReceipt(null);

    if (cart.length === 0) {
      setStatus({ type: "error", message: "Add at least one product to the basket." });
      return;
    }
    if (blocked) {
      setStatus({
        type: "error",
        title: "Wholesale cost floor",
        message: "One or more lines are below wholesale cost. Raise the price to unlock checkout.",
      });
      return;
    }
    const badQuantity = cart.find((item) => {
      const product = productMap.get(item.product);
      const quantity = Number(item.quantity);
      return (
        !Number.isInteger(quantity) ||
        quantity < 1 ||
        quantity > Number(product?.stock_quantity ?? 0)
      );
    });
    if (badQuantity) {
      const product = productMap.get(badQuantity.product);
      setStatus({
        type: "error",
        message: `Enter a valid quantity for ${product?.name || "the product"} (max ${
          product?.stock_quantity ?? 0
        }).`,
      });
      return;
    }
    if (totalCents <= 0) {
      setStatus({ type: "error", message: "The basket total must be above zero." });
      return;
    }
    if (paymentMode === "partial" && (tenderedCents <= 0 || tenderedCents >= totalCents)) {
      setStatus({
        type: "error",
        message: "Part payment must be above zero and below the total.",
      });
      return;
    }
    if (paymentMode !== "paid" && !customerName.trim() && !customerPhone.trim()) {
      setStatus({
        type: "error",
        message: "Add the customer's name or phone to track the unpaid balance.",
      });
      return;
    }
    if (paymentMethod === "mpesa_stk" && !customerPhone.trim()) {
      setStatus({
        type: "error",
        message: "Add the customer's M-Pesa phone number before sending a prompt.",
      });
      return;
    }
    if (
      tenderedCents > 0 &&
      paymentMethod === "mpesa_paybill" &&
      !paymentReference.trim()
    ) {
      setStatus({
        type: "error",
        message: "Enter the M-Pesa confirmation code for the Paybill payment.",
      });
      return;
    }

    const wantsStk = tenderedCents > 0 && paymentMethod === "mpesa_stk";
    const stkPhoneForSale = customerPhone.trim();

    setLoading(true);
    if (!checkoutKeyRef.current) checkoutKeyRef.current = crypto.randomUUID();

    try {
      const receipt = await salesApi.checkout(
        {
          branch: canViewAllBranches ? sellingBranchId || undefined : undefined,
          customer_name: customerName.trim(),
          customer_phone: customerPhone.trim(),
          items: cart.map(({ product, quantity, price_sold_at }) => ({
            product,
            quantity: Number(quantity),
            price_sold_at: fromCents(toCents(price_sold_at)),
          })),
          payments:
            tenderedCents > 0 && paymentMethod !== "mpesa_stk"
              ? [
                  {
                    amount: fromCents(tenderedCents),
                    method: paymentMethod,
                    reference: paymentReference.trim(),
                  },
                ]
              : [],
        },
        checkoutKeyRef.current,
      );
      invalidateKey();
      setLastReceipt(receipt);
      resetCheckout();
      setRefreshKey((key) => key + 1);
      loadRecentReceipts();
      if (wantsStk) askStk(receipt, Number(fromCents(tenderedCents)), stkPhoneForSale);
    } catch (error) {
      if (!error.response || error.response.status >= 500) {
        // The receipt may already be saved server-side. Keep the idempotency key
        // so the retry replays it instead of charging the customer twice.
        loadRecentReceipts();
        setStatus({
          type: "warning",
          title: "Sale not confirmed",
          message:
            "The server did not answer, so this sale may already be recorded. The basket is kept and retrying will not create a second receipt. Check Recent receipts first.",
        });
      } else {
        setStatus({
          type: "error",
          title: "Checkout blocked",
          message: apiErrorMessage(
            error,
            "Could not complete checkout. Check stock and payment details.",
          ),
        });
      }
    } finally {
      setLoading(false);
    }
  }

  function printReceiptDocument(receipt) {
    setPrintReceipt(receipt);
    window.setTimeout(() => window.print(), 100);
  }

  // A printed receipt holds a customer's phone number. Unmount it once the print
  // dialog closes so a later Ctrl+P cannot reprint someone else's sale.
  useEffect(() => {
    if (!printReceipt) return undefined;
    const clear = () => setPrintReceipt(null);
    window.addEventListener("afterprint", clear);
    return () => window.removeEventListener("afterprint", clear);
  }, [printReceipt]);

  function askStk(receipt, amount, phone) {
    if (!(amount > 0)) return;
    setStkPhone(phone ?? receipt.customer_phone ?? "");
    setStkTarget({ receipt, amount });
    // Keep an earlier verdict for the same receipt on screen; a prompt for a new
    // receipt starts with a clean slate.
    setPayStatus((current) => (current?.receiptId === receipt.id ? current : null));
  }

  async function sendStk() {
    if (!stkTarget) return;
    const receiptId = stkTarget.receipt.id;
    if (!stkPhone.trim()) {
      setPayStatus({
        receiptId,
        state: "not_sent",
        balance: Number(stkTarget.amount || stkTarget.receipt.balance || 0),
        code: "",
        message: "Enter the M-Pesa phone number, then send the prompt.",
      });
      return;
    }
    setSendingStk(true);
    try {
      const response = await receiptsApi.stkPush(receiptId, {
        phone: stkPhone.trim(),
        amount: Number(stkTarget.amount).toFixed(2),
      });
      setRecentReceipts((list) => [
        response.receipt,
        ...list.filter((entry) => entry.id !== response.receipt.id),
      ]);
      if (lastReceipt?.id === response.receipt.id) setLastReceipt(response.receipt);
      setPayStatus({
        receiptId,
        state: "waiting",
        balance: Number(response.receipt.balance),
        code: "",
        message: `Prompt sent to ${stkPhone.trim()}. ${response.message} The customer must enter their M-Pesa PIN and press OK on their own phone.`,
      });
      watchPayment(receiptId);
    } catch (error) {
      setPayStatus({
        receiptId,
        state: "not_sent",
        balance: Number(stkTarget.amount || stkTarget.receipt.balance || 0),
        code: "",
        message: `${apiErrorMessage(error, "Could not send the M-Pesa prompt.")} Nothing has been charged.`,
      });
    } finally {
      setSendingStk(false);
    }
  }

  function describePayment(receiptId, outcome) {
    const balance = Number(outcome.balance || 0);
    const reason = safaricomReason(outcome.note || outcome.result_description);

    if (outcome.state === "paid") {
      return {
        receiptId,
        state: "paid",
        balance: 0,
        code: outcome.mpesa_code || "",
        message: `KES ${money(outcome.amount_paid)} received. Hand over the goods and print the receipt.`,
      };
    }
    if (outcome.state === "waiting") {
      return {
        receiptId,
        state: "waiting",
        balance,
        code: "",
        message: `The prompt is still on the customer's phone.${reason ? ` ${reason}` : ""} Nothing is received until they enter their PIN.`,
      };
    }
    return {
      receiptId,
      state: "not_paid",
      balance,
      code: "",
      message: `No M-Pesa money has arrived for this sale.${reason ? ` ${reason}` : ""} Keep the goods until they pay. Take cash and use Record payment, check the phone number, or send the prompt again.`,
    };
  }

  async function checkPayment(receiptId) {
    setCheckingPay(true);
    try {
      const outcome = await receiptsApi.checkPayment(receiptId);
      // A watch on an older receipt must not overwrite the till's current verdict.
      setPayStatus((current) =>
        !current || current.receiptId === receiptId ? describePayment(receiptId, outcome) : current,
      );
      updateReceipt(outcome.receipt);
      return outcome.state;
    } catch (error) {
      setPayStatus((current) => ({
        receiptId,
        state: "unknown",
        code: "",
        balance: current?.receiptId === receiptId ? Number(current.balance || 0) : 0,
        message: `${apiErrorMessage(
          error,
          "Could not reach Safaricom for a status check.",
        )} The payment may still come through - check again in a moment.`,
      }));
      return null;
    } finally {
      setCheckingPay(false);
    }
  }

  function stopPayWatch() {
    if (payTimerRef.current) window.clearTimeout(payTimerRef.current);
    payTimerRef.current = 0;
  }

  // The M-Pesa callback is not guaranteed to reach a local server, so the till
  // asks Safaricom itself until the prompt turns paid or fails.
  function watchPayment(receiptId, attempt = 0) {
    stopPayWatch();
    payTimerRef.current = window.setTimeout(async () => {
      const state = await checkPayment(receiptId);
      if (state && state !== "waiting") return;
      if (attempt >= 5) {
        payTimerRef.current = 0;
        setPayStatus((current) =>
          current?.receiptId === receiptId && current.state === "waiting"
            ? {
                ...current,
                message:
                  "Still waiting for the customer to enter their PIN. This message keeps its place until the money arrives or Safaricom cancels the prompt. Press Check payment now to ask again.",
              }
            : current,
        );
        return;
      }
      watchPayment(receiptId, attempt + 1);
    }, 5000);
  }

  function updateReceipt(updated) {
    setRecentReceipts((list) =>
      list.map((entry) => (entry.id === updated.id ? updated : entry)),
    );
    if (lastReceipt?.id === updated.id) setLastReceipt(updated);
    // A message that contradicts the receipt is what confuses the counter, so any
    // payment recorded another way settles the M-Pesa verdict as well.
    setPayStatus((current) => {
      if (current?.receiptId !== updated.id || Number(updated.balance) > 0) return current;
      stopPayWatch();
      const last = updated.payments?.at(-1);
      const label = SETTLED_LABELS[last?.method] || "Payment";
      return {
        receiptId: updated.id,
        state: "paid",
        balance: 0,
        code: last?.reference || "",
        message: `${label} of KES ${money(last?.amount ?? updated.amount_paid)} received. This sale is fully paid - hand over the goods.`,
      };
    });
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand-700">
            Counter
          </p>
          <h1 className="mt-1 font-display text-2xl font-semibold tracking-tight text-ink-950">
            New sale
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {sellingBranch ? (
              <>
                Selling at <span className="font-semibold text-ink-800">{sellingBranch.name}</span>
              </>
            ) : (
              "Pick a branch before selling."
            )}{" "}
            · Signed in as {user?.full_name || user?.username}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {canViewAllBranches && !branchQuery && (
            <label className="flex items-center gap-2 text-sm text-ink-600">
              <span className="hidden sm:inline">Selling branch</span>
              <Select
                value={sellingBranchId}
                onChange={(event) => setManualBranch(event.target.value)}
                aria-label="Selling branch"
                className="h-10 w-44"
              >
                {branches
                  .filter((branch) => branch.is_active)
                  .map((branch) => (
                    <option key={branch.id} value={branch.id}>
                      {branch.name}
                    </option>
                  ))}
              </Select>
            </label>
          )}
          <Badge tone="brand" dot>
            {itemCount} items
          </Badge>
        </div>
      </div>

      {status && (
        <Alert tone={status.type} title={status.title} onClose={() => setStatus(null)}>
          {status.message}
        </Alert>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.95fr)]">
        <ProductPicker
          products={catalog.results}
          totalCount={catalog.count}
          categories={categories}
          loading={loadingProducts}
          loadingMore={loadingMore}
          onLoadMore={catalog.next ? loadMoreProducts : null}
          search={search}
          onSearchChange={setSearch}
          onSearchSubmit={handleScan}
          category={category}
          onCategoryChange={setCategory}
          lowOnly={lowOnly}
          onLowOnlyChange={setLowOnly}
          onAdd={addProduct}
          cartQuantities={cartQuantities}
          branchName={sellingBranch?.name || ""}
        />

        <div className="space-y-4">
          <BasketPanel
            cart={cart}
            productMap={productMap}
            onChange={updateCartItem}
            onRemove={removeCartItem}
            onClear={clearBasket}
            totalCents={totalCents}
            itemCount={itemCount}
            blocked={blocked}
          />

          <PaymentPanel
            totalCents={totalCents}
            paymentMode={paymentMode}
            onPaymentModeChange={changePaymentMode}
            partialAmount={partialAmount}
            onPartialAmountChange={setPartialAmount}
            paymentMethod={paymentMethod}
            onPaymentMethodChange={(method) => {
              setPaymentMethod(method);
              setCashReceived("");
              setPaymentReference("");
              invalidateKey();
            }}
            paymentReference={paymentReference}
            onPaymentReferenceChange={setPaymentReference}
            cashReceived={cashReceived}
            onCashReceivedChange={setCashReceived}
            customerName={customerName}
            onCustomerNameChange={setCustomerName}
            customerPhone={customerPhone}
            onCustomerPhoneChange={setCustomerPhone}
            onSubmit={handleSubmit}
            loading={loading}
            blocked={blocked}
            shop={shop}
            branchName={sellingBranch?.name || ""}
          />

          {lastReceipt && (
            <ReceiptSuccessCard
              receipt={lastReceipt}
              shop={shop}
              onPrint={printReceiptDocument}
              onStk={(receipt) => askStk(receipt, Number(receipt.balance))}
              onSettle={setSettleTarget}
              payment={payStatus?.receiptId === lastReceipt.id ? payStatus : null}
              checkingPayment={checkingPay}
              onCheckPayment={() => checkPayment(lastReceipt.id)}
            />
          )}
        </div>
      </div>

      <RecentReceipts
        receipts={recentReceipts}
        onPrint={printReceiptDocument}
        onStk={(receipt) => askStk(receipt, Number(receipt.balance))}
        onSettle={setSettleTarget}
      />

      <StkModal
        target={stkTarget}
        phone={stkPhone}
        onPhoneChange={setStkPhone}
        status={stkTarget && payStatus?.receiptId === stkTarget.receipt.id ? payStatus : null}
        saving={sendingStk}
        checking={checkingPay}
        onCheck={() => stkTarget && checkPayment(stkTarget.receipt.id)}
        onSend={sendStk}
        onClose={() => setStkTarget(null)}
      />

      <SettlePaymentModal
        receipt={settleTarget}
        onClose={() => setSettleTarget(null)}
        onSaved={(updated) => {
          updateReceipt(updated);
          setSettleTarget(null);
        }}
      />

      {printReceipt && <PrintableReceipt receipt={printReceipt} />}
    </div>
  );
}
