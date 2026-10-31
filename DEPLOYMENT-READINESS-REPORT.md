# Deployment-readiness report — Greenlight LED Accessories POS

Audit date: 2026-10-30
Copy audited: `C:\Users\HP\Documents\Qoder\2026-10-30\49322d59\duka-pos`
Original zip (`OneDrive\Documents\duka-pos\duka-pos.zip`) was not touched.

---

## 1. Verdict

**Ready to deploy for the shop, with five go-live blockers that are yours to clear, not code defects.**

The money-critical behaviour is correct and covered by tests: a sale either completes
once or not at all, stock can never go negative, a cashier cannot sell below wholesale
cost, credits are tracked and settled, and every receipt stays in the ledger forever.
The till, inventory, expenses, reports and team screens were each driven in a real
browser as super admin and as manager/cashier.

What stops this from being "install and open the shop" is environment and data, not
logic:

| # | Blocker | Why it blocks |
|---|---------|---------------|
| 1 | Rotate the M-Pesa Daraja sandbox keys | The sandbox consumer key/secret were pasted into this chat. Anyone with the transcript can use them. Generate new ones before any production use. |
| 2 | Never ship `backend/.env` | It holds live credentials. Only `backend/.env.example` belongs in the repo/zip. |
| 3 | Deploy with `DEBUG=False`, HTTPS and PostgreSQL | Django's own `check --deploy` reports 5 security items locally; all five disappear once the production env vars from `.env.example` are set behind TLS. SQLite is not the multi-year, multi-branch store. |
| 4 | Replace the demo data | Today's ledger is test sales (see §6). Opening stock, real SKUs and prices must be loaded from your own list before the first customer. |
| 5 | One real M-Pesa test | Paybill, short code and callback URL must be proven with one real KES 1 STK push and one lost-callback reconciliation before you depend on it. |

After those five, the system is fit for a busy counter.

---

## 2. Evidence — the commands and the actual output

Run from the project copy on 2026-10-30:

```text
backend:  .venv\Scripts\python manage.py test
          Ran 85 tests in 268.993s
          OK
          Found 85 test(s). System check identified no issues (0 silenced).

backend:  .venv\Scripts\python manage.py check --deploy
          System check identified 5 issues (0 silenced)
          W004 SECURE_HSTS_SECONDS  W008 SECURE_SSL_REDIRECT
          W012 SESSION_COOKIE_SECURE  W016 CSRF_COOKIE_SECURE  W018 DEBUG=True

frontend: npm test          → vitest 5.0.5 — Test Files 1 passed, Tests 13 passed
frontend: npm run lint      → oxlint — Found 0 warnings and 0 errors (28 files, 103 rules)
frontend: npm run build     → vite 8.3.5 — 105 modules transformed
                              dist/assets/index-DgAXqcLC.css   46.89 kB │ gzip   9.13 kB
                              dist/assets/index-BEGjzeIt.js   437.36 kB │ gzip 131.51 kB
                              ✓ built in 420ms
```

The `W004/W008/W012/W016/W018` warnings and the `No directory at: backend\staticfiles`
notice are local-environment artefacts: the settings only enable those flags when
`DEBUG=False`, and `collectstatic` is a deploy-time step. They are not code defects.

Browser verification (Chrome via the local app at `127.0.0.1:5174`, API at `127.0.0.1:8001`):

- Completed a sale as cashier and as manager; receipt, ledger, dashboard and analytics
  all agreed on the same numbers.
- Repeated the same checkout with the same `Idempotency-Key` → one receipt, not two.
- Tried to sell below wholesale cost → blocked with a clear message.
- Credit sale → appears in Outstanding credit → settled with a part payment →
  balance and payment history correct.
- STK push path validated against the sandbox (prompt reaches Daraja; callback token
  check rejects a forged `?token=`).
- Recorded and deleted a test expense through the UI, then left the ledger clean.
- Reloaded the till mid-sale: the basket came back with the "unfinished sale was
  restored" notice instead of an empty counter.
- Console showed no application errors on login, till, inventory, expenses, dashboard
  or transactions.

---

## 3. What is covered by tests

`backend/` — 85 tests across five apps:

- **sales**: checkout, integer-cent money maths, cost-floor block, stock decrement and
  rollback, idempotent replay, over-sale rejection, credit + payment recording,
  receipt list/detail/export, analytics totals and per-category breakdown, branch
  isolation, M-Pesa STK push, query, callback signature check, amount mismatch →
  FAILED, duplicate callback ignored, reconciler command.
- **products**: CRUD, per-branch SKU uniqueness, CSV import (skip existing, bad rows
  reported, size/encoding guards), low-stock and cost-value masking for cashiers.
- **accounts**: login throttle, token expiry, super-admin-only account and password
  management, manager-only staff writes, branch assignment rules.
- **expenses**: CRUD, month/branch/category summaries, cashier write block, manager
  can only touch their own branch.
- **alerts**: restock alert created when a sale empties stock, no same-day duplicate,
  none when stock is healthy, endpoint requires authentication, WhatsApp send skipped
  when Twilio is unconfigured, branch staff only see their own shop's alerts.

`frontend/` — 13 tests on the money helpers (`toCents`, `fromCents`, `cleanMoney`,
`cleanWholeNumber`, `money`, `monthBounds`, `currentMonth`), including the rounding
cases that used to produce 1-cent drift (`1.005 → 101`, `8.57 → 857`, `0.07 → 7`) and
thousand-separator input (`"1,250.00" → 125000`).

---

## 4. Defects found in this pass and fixed

| Severity | Defect | Fix |
|----------|--------|-----|
| **Blocker** | The till's "Complete sale" button was never disabled while a sale was in flight — `{...props}` overrode the `disabled` attribute in `Button`. A double tap could fire two checkouts. | Spread props first, then compute `disabled` — [frontend/src/components/ui.jsx:50](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/components/ui.jsx#L50) |
| High | A page refresh, an idle sign-out or a network drop lost a half-entered basket. | Basket + customer + payment mode saved to `sessionStorage` and restored with a warning banner — [frontend/src/pages/SalesScreen.jsx:16](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/pages/SalesScreen.jsx#L16) |
| High | The restore above was silently undone by the branch-change effect, which treated "branches still loading" as a branch switch and emptied the basket. | Skip the reset when the previous branch value was empty or unchanged — [frontend/src/pages/SalesScreen.jsx:153](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/pages/SalesScreen.jsx#L153) |
| High | If the server did not answer, the till said "Checkout blocked" and cleared the basket — but the sale may already have been recorded. | Distinguish no-response/5xx from a real rejection: warn "Sale not confirmed", keep the basket, point at Recent receipts — [frontend/src/pages/SalesScreen.jsx](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/pages/SalesScreen.jsx) `handleSubmit` |
| High | Cash typed as `125.005` or `1,250.00` could land 1 cent off, and float drift (`8.57*100 = 856.9999`) truncated to 856. | Round through a fixed-precision step in `toCents` — [frontend/src/lib/format.js:26](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/lib/format.js#L26) |
| Medium | A "paid" sale with too little cash silently created a full-payment receipt for the tendered amount. | Inline warning: "Short by KES … Cash sales must be fully paid — use Part for a credit sale." — [frontend/src/components/sales/PaymentPanel.jsx:175](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/components/sales/PaymentPanel.jsx#L175) |
| Medium | Restock alerts for every branch were visible to any logged-in user, including another branch's cashiers. | Filter by the requester's branch, legacy rows counted as the main shop — [backend/alerts/views.py:12](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/backend/alerts/views.py#L12) |
| Medium | The Daraja OAuth token was re-fetched on every STK push and every status query (a slow, rate-limited call inside the payment path). | Cache the token for 55 minutes — [backend/sales/mpesa.py:95](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/backend/sales/mpesa.py#L95) |
| Medium | WhatsApp alerts sent inside `transaction.on_commit` used the Twilio client's unbounded default timeout. | 10-second client timeout — [backend/alerts/whatsapp.py:25](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/backend/alerts/whatsapp.py#L25) |
| Medium | The Branch picker in Add/Edit product and in CSV import listed "Main shop" twice (one blank option plus the real MAIN row). | Single option list driven from the real branch rows — [frontend/src/pages/InventoryScreen.jsx:41](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/pages/InventoryScreen.jsx#L41) |
| Medium | Editing a legacy product with no branch as a branch manager silently moved it into their branch. | The form now carries the main shop's real id — [frontend/src/pages/InventoryScreen.jsx:463](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/pages/InventoryScreen.jsx#L463) |
| Medium | The expense form let a branch manager pick another shop and only failed on submit. | Select locked to their own branch; no ambiguous blank choice — [frontend/src/pages/ExpensesScreen.jsx:70](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/pages/ExpensesScreen.jsx#L70) |
| Low | Record-payment modal kept a stale validation error while you fixed the amount, method or code. | Error cleared on each field change — [frontend/src/components/sales/SettlePaymentModal.jsx](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/components/sales/SettlePaymentModal.jsx) |
| Low | Receipt print listeners were never removed, so navigating away kept a stray `afterprint` handler. | Cleaned up in both print flows — [frontend/src/pages/TransactionsScreen.jsx](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/pages/TransactionsScreen.jsx) |
| Low | A list endpoint with thousands of rows would spin an unbounded paging loop on the till. | Cap at 40 pages per load — [frontend/src/api/client.js:72](file:///C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos/frontend/src/api/client.js#L72) |
| Low | Selling-branch select had no accessible name on small screens. | `aria-label="Selling branch"` |

Deliberately **not** changed: the frontend audit agent recommended rotating the
idempotency key whenever the basket is edited. That is wrong for a counter — a rotated
key after a timed-out request is exactly how a customer gets charged twice. The same
key is kept until a checkout succeeds or the basket is cleared.

---

## 5. Remaining risks and recommendations

**Do before the shop depends on it**

1. Rotate Daraja keys; keep sandbox keys out of production entirely.
2. Set the production environment exactly as `backend/.env.example`: `DEBUG=False`,
   `SECRET_KEY` (new), `DATABASE_URL` (Postgres), `ALLOWED_HOSTS`,
   `CSRF_TRUSTED_ORIGINS`, `MPESA_*` with the real Paybill and the public callback URL.
3. Run the M-Pesa reconciler every 5 minutes (`manage.py reconcile_mpesa --older-than 5`);
   lost callbacks are otherwise stuck pending.
4. Put the three "must not lose" things in place before day one: nightly `pg_dump`
   offsite, `backend/media/` backed up, and a tested restore.
5. Load your real products and opening stock (Inventory → Import CSV), then correct
   any quantity by hand once.

**Should fix soon (no data risk, usability/perf)**

- Modals do not trap keyboard focus; on a phone-size till, Tab can walk behind the
  dialog.
- Several controls are below the 44 px touch target a cashier needs in a hurry.
- Multi-worker gunicorn with the default local-memory cache means per-worker rate
  limits and per-worker M-Pesa token caches. Use Redis (`CACHES` + throttle storage)
  once you run more than one worker.
- The till has no offline mode: if the network drops mid-sale the basket survives but
  nothing can be recorded until the server answers again.
- Any logged-in user can list branches (names, codes, phone, address). Harmless today;
  trim those fields for non-managers if branches ever carry commercial detail.
- Receipt search/export has no pagination cap of its own; fine at your volume, worth
  an index review past ~500k rows.

**Nice to have**

- Day-close summary per cashier/till, product price-change audit trail, barcode
  scanner quick-start note, receipt printer paper-width setting.

---

## 6. Test data currently in the demo database (needs your decision)

Six receipts are recorded for today (2026-10-30) — **all of them are verification sales
made during this audit, not shop income.** Two large ones were created by a background
agent that posted real checkouts before I stopped it; they also moved stock.

```text
receipt   time    total      customer            items
1af21efc  02:21    600.00    -                   SM-002 x1@600
6ddb896e  09:27    780.00    Cashier Test Sale   SL-001 x1@780
e9a463df  09:29    600.00    -                   SM-002 x1@600
1c8e505d  09:46  2,400.00    Manager Credit Test SM-001 x2@600, SL-002 x1@1200
6dc13fa5  10:17 28,500.00    -                   SM-001 x10@500, SM-002 x10@500,
                                                   SL-002 x10@1100, SL-001 x10@750
9765a08a  10:23 23,500.00    john                SM-002 x10@500, SL-002 x10@1000,
                                                   SL-001 x10@850
```

Effect on the numbers you see today: sales this month KES 121,180, gross profit
KES 21,580, 184 units sold; stock now SL-001 79, SL-002 29, SM-002 10, SM-001 88
(opening figures were 99 / 49 / 30 / 98).

Receipts are immutable on purpose, so removal is deliberate surgery. Say the word and I
will delete the six test receipts with their sale lines and payments and put the four
stock counts back. `Sale` and `Payment` both protect the receipt, so they are removed
first — this is what I would run inside `python manage.py shell`:

```python
from sales.models import SaleReceipt, Sale, Payment
from products.models import Product

prefixes = ["1af21efc", "6ddb896e", "e9a463df", "1c8e505d", "6dc13fa5", "9765a08a"]
for prefix in prefixes:
    for receipt in SaleReceipt.objects.filter(id__startswith=prefix):
        Sale.objects.filter(receipt=receipt).delete()
        Payment.objects.filter(receipt=receipt).delete()
        receipt.delete()

for sku, quantity in {"SL-001": 99, "SL-002": 49, "SM-001": 98, "SM-002": 30}.items():
    Product.objects.filter(sku=sku).update(stock_quantity=quantity)
```

Nothing else in the database needs touching, and a fresh production install never sees
any of this.

---

## 7. Making changes yourself in VS Code

1. **Open the project**: File → Open Folder → `…\duka-pos`. In the terminal panel
   (Ctrl+\`) the two apps are separate folders: `backend` and `frontend`.
2. **Give yourself a safety net first** — the copy is not a git repository yet:
   ```bash
   cd "C:/Users/HP/Documents/Qoder/2026-10-30/49322d59/duka-pos"
   git init && git add -A && git commit -m "Greenlight POS: baseline after full audit"
   ```
   `.gitignore` already excludes `.env`, the SQLite files, `media/`, `node_modules/`
   and `dist/`, so secrets cannot slip in. From now on `git diff` shows every change
   and `git checkout -- <file>` undoes a mistake.
3. **Run it** in two split terminals:
   ```bash
   cd backend  && .venv\Scripts\activate && python manage.py runserver 127.0.0.1:8001
   cd frontend && npm run dev            # opens on http://127.0.0.1:5174
   ```
4. **Where to change what** — the screen you see is the file you edit:
   - counter/till → `frontend/src/pages/SalesScreen.jsx` and the pieces in
     `frontend/src/components/sales/`
   - products → `frontend/src/pages/InventoryScreen.jsx`
   - money formatting → `frontend/src/lib/format.js`
   - dashboard/insights → `frontend/src/pages/DashboardScreen.jsx`
   - receipts/credits → `frontend/src/pages/TransactionsScreen.jsx`
   - expenses → `frontend/src/pages/ExpensesScreen.jsx`
   - staff & branches → `frontend/src/pages/TeamScreen.jsx`
   - API calls → `frontend/src/api/client.js`
   - prices, checkout, M-Pesa → `backend/sales/views.py`, `backend/sales/mpesa.py`
   - stock rules → `backend/products/views.py`
   - permissions & branches → `backend/accounts/services.py`, `permissions.py`
   - overall settings (throttles, CORS, env) → `backend/config/settings.py`
5. **After every change, run the three checks before you trust it:**
   ```bash
   cd backend  && .venv\Scripts\python manage.py test
   cd frontend && npm test && npm run lint && npm run build
   ```
   Expect `Ran 85 tests … OK`, `Tests 13 passed`, `0 warnings and 0 errors`, and a
   successful build. If you change a rule, add a test next to it (backend tests live
   in each app's `tests.py`; frontend tests in `src/lib/*.test.js`).
6. **Schema changes** (only if you edit a `models.py`):
   ```bash
   cd backend && python manage.py makemigrations && python manage.py migrate
   ```
   Never edit a migration that has already run on a server.
7. Do the manual pass in the browser too — press Ctrl+Shift+R, sell one item, try one
   credit, print one receipt. Tests prove the rules; the browser proves the counter.

---

## 8. Deploying it

Full, tested instructions are in `README.md` → **Deployment** (VPS + PostgreSQL +
nginx + gunicorn, the nginx block, backups, PaaS notes, M-Pesa go-live checklist).
Short version:

```bash
# on the server, from the project root
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill in the production values, DEBUG=False
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py createsuperuser
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3

cd ../frontend
npm ci && npm run build         # copy dist/ to the nginx web root
```

Then: certbot for TLS, systemd for gunicorn, the 5-minute reconciler cron, and the
first real KES 1 M-Pesa test. Deploy only when §2's three commands are green.

---

## 9. One-line answer

The code is ready: 85 backend tests, 13 frontend tests, clean lint and build, and every
screen driven in the browser. Deploy it against PostgreSQL with new M-Pesa credentials
and your own opening stock, and treat the six test receipts in this demo database as
yours to delete.
