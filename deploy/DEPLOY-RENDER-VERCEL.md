# Render + Vercel deployment

This setup keeps the React app on Vercel, Django and PostgreSQL on Render, and product images on Cloudinary. The backend remains the only source of truth for products, stock, sales, receipts and payments.

## 1. Configure Cloudinary

1. Create a Cloudinary account and open the dashboard's API credentials page.
2. Copy the API environment URL. It has the form `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`.
3. For local testing, add it as `CLOUDINARY_URL=...` to `backend/.env`. Do not put the value in Git, a frontend variable, or a chat message. `.env` is ignored by Git.
4. Install the updated backend requirements with `backend_venv\Scripts\python.exe -m pip install -r requirements.txt` from `backend`.
5. Check the existing images without uploading: from `backend`, run `backend_venv\Scripts\python.exe manage.py upload_product_images --dry-run`.
6. When the list is correct, run `backend_venv\Scripts\python.exe manage.py upload_product_images`. This uploads local files, then changes each product's image path to its Cloudinary asset. The original local image files are left in place as a backup.
7. Check the product list in the app and confirm its photos load from HTTPS Cloudinary URLs.

With no `CLOUDINARY_URL`, development continues to use `backend/media` locally. The product image field and API stay the same.

## 2. Create the Render backend and PostgreSQL database

Create a Render PostgreSQL database and a Render web service from the repository. Keep both in the same Render region and use the database's **internal** connection string for the service's `DATABASE_URL`.

Set these environment variables on the Render web service. Never commit their values:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Render PostgreSQL internal connection string |
| `DEBUG` | `False` |
| `SECRET_KEY` | Fresh, long random Django key |
| `ALLOWED_HOSTS` | Render backend hostname, plus any backend custom domain |
| `CSRF_TRUSTED_ORIGINS` | `https://<your-vercel-domain>` and any Vercel production alias/custom domain |
| `CORS_ALLOWED_ORIGINS` | Exact Vercel frontend origin(s), including `https://` |
| `CLOUDINARY_URL` | Cloudinary API environment URL |
| `MPESA_ENVIRONMENT` | `sandbox` until sandbox is verified; `production` only with approved live credentials |
| `MPESA_CONSUMER_KEY` | Daraja consumer key for the selected environment |
| `MPESA_CONSUMER_SECRET` | Daraja consumer secret for the selected environment |
| `MPESA_SHORTCODE` | Sandbox shortcode for sandbox; shop's approved Paybill shortcode for live |
| `MPESA_PASSKEY` | Lipa na M-Pesa Online passkey for that shortcode/environment |
| `MPESA_CALLBACK_URL` | `https://<render-backend-host>/api/mpesa/callback/` |
| `MPESA_CALLBACK_TOKEN` | Fresh random value, at least 32 URL-safe characters |
| `SESSION_COOKIE_SECURE` | `True` |
| `CSRF_COOKIE_SECURE` | `True` |
| `SECURE_SSL_REDIRECT` | `True` |
| `SECURE_HSTS_SECONDS` | `31536000` after HTTPS is confirmed working |
| `TIME_ZONE` | `Africa/Nairobi` |

Use the Render dashboard's generated secret option for `SECRET_KEY`, or generate one locally. Do not use the example secret. Leave CORS limited to the exact Vercel origins; do not use `*` with authenticated requests.

Render build command (from the repository root):

```sh
pip install -r backend/requirements.txt && npm --prefix frontend install && npm --prefix frontend run build
```

Render start command:

```sh
cd backend && python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4
```

The built `frontend/dist` directory must remain alongside `backend`; the current Django settings locate it relative to the backend directory. Product photos do not use Render's local filesystem once `CLOUDINARY_URL` is set.

## 3. Configure Vercel

Import the repository into Vercel and set the project root to `frontend` with the Vite framework preset. Set this build-time environment variable for Production and Preview as appropriate:

```text
VITE_API_BASE_URL=https://<render-backend-host>/api
```

The frontend variable is public by design and must contain only the backend URL, never a secret. After changing it, redeploy the Vercel frontend. Add the exact Vercel origin to both Render's `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`.

## 4. Move the current SQLite data to PostgreSQL

The active local database is `C:\ShopData\greenlight.sqlite3`, not `backend/db.sqlite3`. Stop local sales before taking the final export. The current source passed SQLite's integrity check and contains products, staff, receipts, payments, expenses and one branch. Do not commit the export fixture; it contains private shop and customer records.

Recommended sequence:

1. Back up the current database and media using the existing command: from `backend`, run `backend_venv\Scripts\python.exe manage.py backup_shop --destination C:\ShopData\backups`.
2. With the local SQLite database still selected, export application records to a private fixture:

```powershell
backend_venv\Scripts\python.exe manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --output C:\ShopData\duka-pos-data.json
```

3. Configure the Render production variables and deploy the app. Let `migrate` create the PostgreSQL schema.
4. Transfer the fixture through a private channel to the deployed service, then run `python manage.py loaddata <fixture-path>` against Render's PostgreSQL database. Do not upload it to a public URL or commit it.
5. Compare model counts, log in with the migrated staff account, inspect several receipts/payments and product quantities, and verify images load. Keep the SQLite database and backup unchanged until these checks pass.
6. Schedule a short cutover window: no sales during the final export/import, and point all users to the deployed Vercel URL only after verification.

If Cloudinary is enabled before export, run `upload_product_images` first so the fixture already contains Cloudinary image paths. Otherwise, transfer photos to Cloudinary before or after import, then run the upload command against the database that holds those products and their local files.

## 5. Verify M-Pesa before real sales

The callback URL must be a public HTTPS Render address and reachable without a login. Configure the Daraja app for the same environment and shortcode as the Render variables. A local or temporary tunnel URL is not the production callback.

After deployment, from the Render service shell run:

```sh
python manage.py check --deploy
python manage.py check_mpesa
```

First prove the sandbox prompt and callback end to end. For production, use the production Daraja consumer key/secret, Paybill shortcode and passkey, then run `check_mpesa` and a low-value live test on a consenting phone. Run `python manage.py reconcile_mpesa --older-than 5` on a schedule (about every five minutes) to recover callbacks that do not arrive. Never treat a prompt request alone as proof that payment succeeded; verify the settled receipt and M-Pesa code.

## Current boundary

The Cloudinary storage backend and safe photo-transfer command are implemented. The current six local photo files remain untouched until `CLOUDINARY_URL` is supplied and the transfer command is run. PostgreSQL migration and real Daraja payments cannot be completed until the Render database/service, Vercel project, Cloudinary account, and appropriate Daraja credentials exist.
