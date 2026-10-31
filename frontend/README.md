# Duka POS frontend

React 19 + Vite + Tailwind CSS 4 single-page app for the Duka POS API.

## Development

```bash
npm install
cp .env.example .env
npm run dev
```

`VITE_PROXY_TARGET` (default `http://127.0.0.1:8000`) is the backend Vite
proxies `/api` and `/media` to. Restart Vite after changing `.env`.

Receipt branding comes from `VITE_SHOP_NAME`, `VITE_SHOP_PHONE` and
`VITE_SHOP_WEBSITE`; the API's `/shop/` response can override them. Set
`VITE_IDLE_TIMEOUT_MINUTES` to auto sign out an idle till (default 30,
minimum 5).

## Screens

- `/` — Sell: searchable product picker with SKU scan, cart with retail
  discounts and a wholesale cost floor, Paybill/STK/cash payments, printable
  receipt and recent receipts.
- `/transactions` — all receipts, filters, CSV export, credits, settle and
  print.
- `/inventory` — thousands of products with server search, CSV import,
  stock, wholesale/retail prices, margins, images, per-branch products.
- `/dashboard` — sales, profit, expenses, collections, credits, restock and
  donut charts with amounts and percentages.
- `/expenses` — manager-only money-out register.
- `/team` — super admin manages staff logins and passwords; managers manage
  branches.

## Checks

```bash
npm test
npm run lint
npm run build
```

## Build output

`npm run build` writes static files to `dist/`. Serve `dist` with nginx (or a
static host) and proxy `/api/` to the Django backend; deep links need a
fallback to `index.html`.
