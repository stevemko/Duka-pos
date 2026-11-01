# Greenlight LED Accessories POS

Point-of-sale and shop management for Greenlight LED Accessories
(greenlightledaccessories.com): sales, stock, credits, expenses, staff
accounts, branches, daily/monthly charts and M-Pesa Paybill/STK payments.

- Backend: Django 6 + Django REST Framework (token auth)
- Frontend: React 19 + Vite + Tailwind CSS 4
- Database: SQLite in development, PostgreSQL in production

```
duka-pos/
├── backend/    Django API
└── frontend/   React single-page app
```

## What the system does

| Area | What you get |
| --- | --- |
| Sell | Server-paginated product picker with search, category filter and Enter-to-scan SKU; cart, cash/change, Paybill, STK prompt, mobile money, card, bank, credit and part-payment; printable receipt after every sale. |
| Wholesale cost floor | Retail is the marked price; wholesale is the initial cost. Selling below retail is allowed (with a discount note), but a sale below wholesale cost is blocked in the browser, the API and the database with a red alert. |
| Inventory | Thousands of products with fast server search and "load more"; stock, wholesale cost, retail price, margin, images, low-stock filters, CSV price-list import and template, per-branch stock. |
| Transactions | Every receipt is kept forever: date, customer, cashier, items, payments, balance, status. Filter by day/week/month, search, export CSV. |
| Credits | Outstanding balances per customer, one-click settle, M-Pesa prompt from the receipt. |
| Expenses | Rent, salaries, stock, transport and other money-out entries, with category summaries and net profit. |
| Team & passwords | Only the super admin creates logins, assigns roles and reset passwords. Managers open branches and oversee shop operations; everyone can change their own password. |
| Dashboard | Sales, gross profit, expenses, net profit, money collected, credit outstanding, daily records, product movement, restock list, credit register, and donut charts with exact amounts and percentages for sales by category, payment mix and expenses. |
| Branches | Stock, receipts, cashiers and expenses are scoped per branch; managers can view all branches or one branch. |

## Roles

- **Super admin** (`is_superuser=True`): the only role that creates accounts,
  assigns roles, resets passwords and deactivates logins. Also has full access
  to money, expenses, branches and all reports.
- **Manager** (`is_staff=True`): full shop oversight: sells, manages
  inventory, expenses, branches and all-branch reports. Cannot create staff
  accounts or reset other people's passwords.
- **Cashier**: sells and views inventory/records for their assigned branch.
  Wholesale cost and profit are hidden; they still see the minimum sell price
  (wholesale cost) so loss-making sales are blocked.
- An account with no branch assigned is treated as a manager who can see all
  branches. Keep at least one active manager at all times.

### Super admin: create or reset a staff password

1. Sign in as the super admin.
2. Open **Team & branches → Team logins**.
3. **Add team member**: username, name, phone, role, branch and a password of
   at least 8 characters. Share the password privately; ask the cashier to
   change it on first sign-in (top bar **Password**).
4. **Reset password** on any row signs the member out everywhere and requires
   the new password at the next sign-in.
5. **Deactivate** stops sign-in immediately without deleting their sales
   history. Reactivate with the same button when they return.
6. You cannot remove your own super admin status or deactivate yourself, and
   the system refuses to leave the shop with zero active managers.
7. Managers can still open/edit branches from **Branches**, but the Team logins
   tab and the users API are super-admin only.

## Local setup

Requirements: Python 3.14+, Node.js 20+.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Vite serves <http://localhost:5173> and proxies `/api` to the backend. If the
backend runs on another port, set `VITE_PROXY_TARGET` in `frontend/.env` and
restart Vite.

## Daily operation

- **Morning**: open the app, check **Dashboard → Needs restock**, record any
  opening expenses (transport, stock purchases).
- **During the day**: sell from **Sell**. Scan or type an exact SKU and press
  Enter to add it instantly. You may discount below the retail marked price;
  the cart shows the discount. A price below **wholesale cost** is blocked in
  red and cannot be checked out. Fix the price or correct the cost in
  **Inventory** if it is genuinely wrong.
- **Paybill sales**: choose **Paybill** as the method, ask the customer to pay
  the Paybill number shown on screen (account: their phone number or
  `GREENLIGHT`), then enter the M-Pesa confirmation code from their SMS. The
  receipt and printer copy show the Paybill and account for any balance.
- **Credit sales**: enter the customer name or phone. Settle later from
  **Transactions → Credits & balances → Open → Record payment** (cash, mobile
  money, card, bank) or **M-Pesa prompt**.
- **If the till restarts mid-sale** (browser crash, power blip, sign-out on
  idle): reopen the app and the basket comes back for that cashier at that
  branch, with a warning to check it before completing. A basket left over more
  than six hours is dropped, because its prices and stock are no longer true.
  Switching branch always starts a fresh basket.
- **End of day**: **Transactions** defaults to today. Check the totals in view,
  open any receipt to print, then **Export CSV** for your records/accountant.- **Month end**: **Dashboard**, choose the month, export the transaction CSV
  and review gross profit, expenses and net profit.

Sales and payments are immutable: once saved they cannot be edited or deleted,
which keeps the books auditable. Mistakes are corrected with a new entry, not
by erasing history.

## M-Pesa: sandbox → real Paybill

The code supports Safaricom Daraja **STK Push / Lipa na M-Pesa Online** for a
Paybill. Sandbox (`174379`) proves the flow; production needs the shop's own
Paybill credentials.

### 1. Get production Daraja credentials

1. Create/sign in at <https://developer.safaricom.co.ke> with the M-Pesa
   business account.
2. Create an app and request **Lipa na M-Pesa Online** (STK Push).
3. Apply for **Go Live**. Safaricom links the app to the business shortcode
   (the Paybill number) after KYC. Production is not available on the sandbox
   shortcode.
4. In the Daraja portal (production), copy:
   - Consumer Key
   - Consumer Secret
   - Business Shortcode (the Paybill number)
   - Lipa na M-Pesa Online Passkey (specific to that shortcode)
5. Set the callback URL to your public HTTPS endpoint:
   `https://pos.yourdomain.com/api/mpesa/callback/`

### 2. Configure the server

`backend/.env`:

```ini
MPESA_ENVIRONMENT=production
MPESA_CONSUMER_KEY=<production consumer key>
MPESA_CONSUMER_SECRET=<production consumer secret>
MPESA_SHORTCODE=<paybill number>
MPESA_PASSKEY=<production passkey>
MPESA_CALLBACK_URL=https://pos.yourdomain.com/api/mpesa/callback/
MPESA_CALLBACK_TOKEN=<long random value>
MPESA_TRANSACTION_TYPE=CustomerPayBillOnline
MPESA_ACCOUNT_REFERENCE=GreenLight
MPESA_TRANSACTION_DESCRIPTION=POS payment
```

Also set:

```ini
DEBUG=False
ALLOWED_HOSTS=pos.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://pos.yourdomain.com
```

Restart the backend after changing `.env`. The app appends
`?token=MPESA_CALLBACK_TOKEN` to the callback URL and rejects callbacks with a
missing or wrong token.

### 3. Test the real Paybill

**STK prompt (customer enters PIN on the phone):**

1. Use a real phone and the real Paybill.
2. Open **Transactions → Credits & balances** (or after a credit sale),
   **Open → M-Pesa prompt**, enter the customer's phone.
3. The customer receives the Safaricom prompt and enters their M-Pesa PIN.
4. The receipt updates from `payment_pending` to `paid` when Safaricom calls
   back. Check **payment history** for the M-Pesa receipt code.
5. Test failure paths too: cancel the prompt, enter a wrong PIN, use an
   unregistered number, and turn the phone off. Failed prompts stay visible in
   the payment history with Safaricom's reason.

**Manual Paybill at the counter (customer pays from their phone):**

1. On **Sell**, choose **Paybill**. The screen shows the Paybill number from
   `MPESA_SHORTCODE` and the account (customer phone, or `GREENLIGHT`).
2. The customer pays with M-Pesa Paybill on their own phone; the money settles
   into the bank account linked to that Paybill.
3. Enter the confirmation code from the customer's SMS in the required field.
   The payment is saved with that reference for reconciliation.
4. The printed receipt and the on-screen receipt carry the same Paybill and
   account, so an unpaid balance can be settled later the same way.

### 4. Go-live checklist

- [ ] Production consumer key/secret and passkey are in `backend/.env`, never in
      git or the frontend build.
- [ ] `MPESA_ENVIRONMENT=production` and `MPESA_SHORTCODE` is the real Paybill.
- [ ] Callback URL is public HTTPS, reachable without login, and ends in
      `/api/mpesa/callback/`.
- [ ] Firewall/WAF allows Safaricom's callback IPs; no basic-auth or bot
      challenge on that path.
- [ ] `ALLOWED_HOSTS` includes the public domain; `DEBUG=False`.
- [ ] A KES 1 live STK payment succeeds and appears on the receipt.
- [ ] A KES 1 manual Paybill payment is recorded with its confirmation code.
- [ ] `reconcile_mpesa` runs every 5 minutes (see below).
- [ ] Staff know that STK requests are whole shillings; cents stay on the
      balance and can be settled in cash.

The same day, on the shop machine:

- [ ] `SECRET_KEY` and `MPESA_CALLBACK_TOKEN` are freshly generated values, not
      the ones used while setting this up.
- [ ] `DEBUG=False`, and `manage.py check --deploy` is read through.
- [ ] The database is not inside a synced folder (`manage.py check` shows no
      `config.W001`).
- [ ] `backup_shop` is scheduled, has written at least one copy to a second disk,
      and that copy has been opened as a restore test.
- [ ] `deliver_alerts` is scheduled if the shop uses WhatsApp restock messages.
- [ ] Every till was opened once from the shop's own address, installed as an app,
      and one sale was completed on each.
- [ ] Each cashier has their own login; no shared password, and the wholesale cost
      is hidden from them.

Secrets were pasted in chat during setup: rotate the consumer key/secret and
passkey in Daraja before go-live, then update `.env`.

## Deployment

### One computer in the shop (this is the usual setup)

The backend serves the built app, the API and the product photos from one port,
so there is no nginx and no second machine to administer. Trading does not need
the internet; only M-Pesa prompts do.

```bat
cd frontend
npm install
npm run build

cd ..\backend
python -m venv backend_venv
backend_venv\Scripts\python -m pip install -r requirements.txt
backend_venv\Scripts\python manage.py createsuperuser
start-shop.bat
```

`start-shop.bat` applies any pending migrations and then serves port 8000 on
every network address of that machine, so the other tills in the shop open
`http://<that computer's name or its 192.168.x.x address>:8000`. Windows asks
once whether to allow it - choose allow on **Private** networks.

Notes for this setup:

- Keep `DEBUG=False` in `backend/.env` and never put the built `dist` folder on
  OneDrive or Google Drive while trading.
- The machine's own IP addresses and its computer name are added to
  `ALLOWED_HOSTS` automatically, so the LAN address works without editing `.env`.
- `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` stay `False` on plain
  `http://192.168.x.x`; a Secure cookie is never sent there and would lock the
  admin out. Turn both on the day the shop gets HTTPS.
- If the browser shows "The shop app has not been built yet", `frontend/dist` is
  missing - run `npm run build` in `frontend`.

Install it as an app on each till: open the address in Chrome or Edge, then the
**Install app** / **Install this site as an app** icon in the address bar (or
the three-dot menu). That gives a desktop icon and its own window. After the
first full sign-in, the till's screen and product photos load even if the shop's
internet or the server link drops - stock, prices and payments always come from
the server, so an unreachable server means "cannot sell right now", never a
stale answer.

### VPS + PostgreSQL + nginx + gunicorn (only if the shop wants a public URL)

1. Install Python 3.14, PostgreSQL and nginx on the server.
2. Create the database and a dedicated OS user, then clone the project.
3. `backend/.env` with production values (`DEBUG=False`, `DATABASE_URL`,
   `SECRET_KEY`, `ALLOWED_HOSTS`, M-Pesa).
4. Install dependencies, then:

```bash
cd backend
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

Run gunicorn under systemd (restart on failure) or a process manager. With a
multi-core server use `(2 × cores) + 1` workers; each worker is an independent
process.

5. Build the frontend and copy `frontend/dist` to the web root:

```bash
cd frontend
npm ci
npm run build
```

6. nginx serves the SPA and proxies the API:

```nginx
server {
    listen 443 ssl;
    server_name pos.yourdomain.com;
    client_max_body_size 10m;

    root /srv/duka-pos/frontend/dist;
    index index.html;

    location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto $scheme; }
    location /admin/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; proxy_set_header X-Forwarded-Proto $scheme; }
    location /static/ { alias /srv/duka-pos/backend/staticfiles/; }
    location /media/ { alias /srv/duka-pos/backend/media/; }
    location / { try_files $uri /index.html; }
}
```

Use certbot/Let's Encrypt for TLS. Keep `SECURE_SSL_REDIRECT=True`,
`SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True` and
`SECURE_HSTS_SECONDS` as in `.env.example`.

A PaaS (Render, Railway, Fly.io) works too: run migrations in the release
command, serve the built frontend from the same platform or a static host, and
set the same environment variables. The callback URL must be stable HTTPS.

### Backups and durability

The shop trades from one machine with one database file, so the copy is the plan.

1. **Keep the file outside any synced folder.** A OneDrive or Dropbox copy taken
   while the server is writing gives a database that will not open, and a second
   till pointed at the same file through a sync loses sales. `manage.py check`
   warns (`config.W001`) when it spots one. To move it: stop the server, set
   `DATABASE_PATH=C:\ShopData\greenlight.sqlite3` in `backend/.env`, copy
   `db.sqlite3` there, then start again and sign in.
2. **Copy the books every night** with a scheduled job:

```bat
backend_venv\Scripts\python.exe manage.py backup_shop --destination D:\ShopBackups
```

   `backup_shop` writes a consistent copy through SQLite's own backup API (a plain
   file copy can catch a page half-written or leave its WAL behind), copies the
   product photos, opens the copy again to prove it reads, and keeps the newest 30
   copies. Put the destination on a second disk and carry a copy off the machine
   weekly; `--dry-run` and `--keep` are there for when you want to look first.
3. **Test a restore twice a year**: stop the server, set `DATABASE_PATH` to one of
   the copies, start, and check the receipts and the ledger are there. Then put
   `DATABASE_PATH` back to the live file.

The database runs in write-ahead logging mode, so a sale being written does not
freeze the product search on another till; `db.sqlite3-wal` is part of the database
and must never be deleted on its own.

- Keep receipts append-only: the app never updates or deletes recorded sales
  or payments, prices are copied at sale time, and products/branches with
  history cannot be deleted.
- Checkout runs in one database transaction, every stock movement is written with
  the availability check inside the same statement, and an idempotency key means a
  retry after a timeout cannot create a second receipt or sell the last unit twice.
- Indexes cover receipts by date/branch, sales by product/date, payments by
  status/date and expenses by branch/category/date. Lists are paginated.
- A hosted PostgreSQL install (see the VPS section) is backed up with `pg_dump`
  instead of `backup_shop`, and the same 30-copy rule applies.

### Growing to several branches

1. **Branches → Add branch**: name, unique code, phone, address, open/closed.
2. Ask the super admin to add cashiers and assign them to that branch; add a
   manager for oversight.
3. Stock is per branch: open **Inventory**, switch the branch in the top bar,
   and add/adjust the branch's products and quantities.
4. Managers with all-branch access use the branch switcher to view one branch
   or **All branches** in dashboard, transactions and exports.
5. Receipts, payments, expenses and cashier attribution are stored with the
   branch, so reports stay separated but can be combined.
6. Close a branch by setting it to **Closed**; do not delete branches that
   already have records.

### Scheduled jobs the shop needs

Three housekeeping jobs keep the shop running. None of them is on the checkout
path, so a slow Safaricom or Twilio can never hold a cashier waiting at the counter.

| Job | What it does | Every |
| --- | --- | --- |
| `reconcile_mpesa` | Asks Daraja what happened to STK prompts whose callback was lost, and settles or fails them. | 5 minutes |
| `deliver_alerts` | Sends the restock WhatsApp messages that sales queued, and closes the ones that no longer apply (product restocked, or the alert is a day old). | 15 minutes |
| `backup_shop` | Copies the database and the product photos to a backup folder, checks the copy opens, and prunes the oldest. | Nightly, after closing |

On the shop Windows machine, register all three once from an elevated prompt:

```bat
schtasks /Create /TN "Duka POS reconcile" /SC MINUTE /MO 5 ^
  /TR "cd /d C:\duka-pos\backend && backend_venv\Scripts\python.exe manage.py reconcile_mpesa --older-than 5 >> logs\reconcile.log 2>&1"
schtasks /Create /TN "Duka POS alerts" /SC MINUTE /MO 15 ^
  /TR "cd /d C:\duka-pos\backend && backend_venv\Scripts\python.exe manage.py deliver_alerts >> logs\alerts.log 2>&1"
schtasks /Create /TN "Duka POS backup" /SC DAILY /ST 21:30 ^
  /TR "cd /d C:\duka-pos\backend && backend_venv\Scripts\python.exe manage.py backup_shop --destination D:\ShopBackups >> logs\backup.log 2>&1"
```

Use the folder you actually copied the project to. On a Linux host the same three
lines go in cron:

```bash
*/5  * * * * cd /srv/duka-pos/backend && .venv/bin/python manage.py reconcile_mpesa --older-than 5
*/15 * * * * cd /srv/duka-pos/backend && .venv/bin/python manage.py deliver_alerts
30 21 * * *  cd /srv/duka-pos/backend && .venv/bin/python manage.py backup_shop --destination /srv/backups
```

All three accept `--dry-run` to print what they would change without touching
anything. A sale recorded while M-Pesa or Twilio is unreachable is never lost:
the receipt and the alert row are already committed, and the next run picks
them up.

## Tests and checks

```bash
cd backend && .venv/bin/python manage.py test     # or .venv\Scripts\python.exe
cd frontend && npm test && npm run lint && npm run build
```

Backend coverage includes money paths, wholesale cost-floor enforcement,
branch isolation, cashier cost masking, CSV import, super-admin permissions,
expenses and M-Pesa callbacks. Run all three after any change and before
deploying.

## Environment variables

See `backend/.env.example` and `frontend/.env.example`. Important:

- `SECRET_KEY`, `DATABASE_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
- `MPESA_*` (production credentials, Paybill shortcode and public callback URL)
- `TWILIO_*` and `OWNER_WHATSAPP_NUMBER` for restock WhatsApp alerts
- `AUTH_TOKEN_TTL_DAYS` (default 14) — signed-in sessions expire after this
- `SHOP_NAME`, `SHOP_WEBSITE`, `SHOP_PHONE` — branding returned to the app
- `VITE_SHOP_NAME`, `VITE_SHOP_PHONE`, `VITE_SHOP_WEBSITE` — receipt header
- `VITE_IDLE_TIMEOUT_MINUTES` (default 30, minimum 5) — the till signs out
  automatically after this much inactivity
- `VITE_PROXY_TARGET` — dev-only backend URL for Vite

Never commit `.env` files or real M-Pesa/Twilio secrets.

## Troubleshooting M-Pesa

| Symptom | Check |
| --- | --- |
| `Invalid Access Token` / 401 from Daraja | Wrong consumer key/secret or sandbox vs production mismatch. |
| `Bad Request - Invalid Shortcode` | `MPESA_SHORTCODE` is not the production Paybill or the app is still sandbox. |
| Prompt arrives but receipt never updates | Callback URL unreachable, wrong `MPESA_CALLBACK_TOKEN`, or `ALLOWED_HOSTS` rejects the host. Run the reconciler and check server logs. |
| `The security credential is invalid` | Wrong passkey for this shortcode/environment. |
| "An M-Pesa payment prompt is already pending" | Wait for the 5-minute timeout or let the reconciler expire the old prompt. |
| Customer paid but amount mismatch | The callback amount is compared with the requested amount; mismatches are failed and shown with Safaricom's description. |

## License

Private project for GreenLight LED Accessories.
