# Putting the shop on a public server

This is the runbook for the VPS option: the tills open `https://pos.yourdomain.co.ke`,
the shop keeps its one SQLite file, and Safaricom can reach the callback. It assumes
Ubuntu 24.04 and a 2 vCPU / 2 GB server with 20 GB of disk - more than a shop with a
few counters needs.

Read the whole thing before starting. Steps 1 to 4 are done while the shop keeps
trading on the machine it uses today; nothing here interrupts trading until step 9.

## What you end up with

```
tills (phones, laptops, the counter terminal)
   |
   |  https://pos.example.co.ke
   v
nginx  ────────── serves / , /static/ and /media/ straight off disk
   |                 and holds the TLS certificate
   v
gunicorn, 1 process, 8 threads  (deploy/duka-pos.service)
   |
   +-- /srv/duka-pos/data/greenlight.sqlite3     the shop's books, one file
   +-- /srv/duka-pos/backend/media/              product photos
   ^
   |
Safaricom Daraja  ── POST /api/mpesa/callback/?token=...
```

One process, not several, because the books are one file: two workers writing the
same sale is how a counter gets `database is locked` and a half-recorded bill. The
8 threads cover the tills. This changes when the shop moves to PostgreSQL.

## Before you spend anything

- [ ] A domain or subdomain you own, with an A record pointing at the server's IP.
      `check_mpesa` and `manage.py check --deploy` both complain without it.
- [ ] The VPS created, and `ssh` working as a normal user with sudo.
- [ ] Daraja **production** keys from an approved Go Live request (live shortcode,
      passkey, consumer key and secret). Sandbox keys do not work on the live
      address and the shop will look broken while the customer's money moves.
- [ ] A current copy of the shop's books (`backend_venv\Scripts\python manage.py
      backup_shop --destination D:\ShopBackups` on the machine trading today).
- [ ] An hour when the shop is closed.

## 1. Rotate the secrets you have already typed into a chat

The sandbox keys, passkey and callback token used while building this system are no
longer secret. Do this before the server goes public:

1. Daraja dashboard → regenerate the production consumer secret.
2. A new passkey from the Safaricom merchant portal.
3. A new `SECRET_KEY` and `MPESA_CALLBACK_TOKEN` on the server:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The callback token is the only thing between a stranger and a page of bills marked
paid, so it is never a word, never reused, and never committed.

## 2. The server, ready for the app

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install python3.12-venv postgresql-client nginx certbot python3-certbot-nginx rsync git ufw
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable

sudo adduser --system --group --home /srv/duka-pos --shell /usr/sbin/nologin duka
sudo mkdir -p /srv/duka-pos /srv/duka-pos/data /srv/backups
sudo chown -R duka:duka /srv/duka-pos /srv/backups
```

`postgresql-client` is installed even while the shop uses SQLite, because
`backup_shop` needs `pg_dump`/`pg_restore` the day the books move.

## 3. Put the code on the server

From the shop machine, with Git Bash in the project root:

```bash
rsync -av --delete \
  --exclude '.git' --exclude 'backend/.env*' --exclude 'backend/backend_venv' \
  --exclude 'backend/db*.sqlite3' --exclude 'backend/logs' --exclude 'backend/media' \
  --exclude 'backend/backups' --exclude 'frontend/node_modules' --exclude 'pos-upload' \
  --exclude '*.zip' --exclude 'duka-pos-db-backup-*' \
  ./ duka@pos.example.co.ke:/tmp/duka-deploy/
ssh duka@pos.example.co.ke 'sudo rsync -a /tmp/duka-deploy/ /srv/duka-pos/ && sudo chown -R duka:duka /srv/duka-pos'
```

The exclusions are not tidiness. `.env` holds the shop's keys and must never travel
or sit in a world-readable temp folder; the `.sqlite3` files inside the project are
spares and old snapshots, and copying one of them over the live books silently
deletes trading history. `pos-upload/` and the archives are leftovers from the
import and belong on neither machine.

## 4. Settings on the server

`/srv/duka-pos/backend/.env`, owned by `duka`, mode `600`:

```ini
SECRET_KEY=<the long random one from step 1>
DEBUG=False
ALLOWED_HOSTS=pos.example.co.ke
CSRF_TRUSTED_ORIGINS=https://pos.example.co.ke
CORS_ALLOWED_ORIGINS=

DATABASE_URL=
DATABASE_PATH=/srv/duka-pos/data/greenlight.sqlite3
MEDIA_ROOT=/srv/duka-pos/backend/media

TIME_ZONE=Africa/Nairobi
LOG_LEVEL=INFO
AUTH_TOKEN_TTL_DAYS=14
SHOP_NAME=Greenlight LED Accessories
SHOP_PHONE=

# This server is only reached over HTTPS, so the cookies say so.
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000

MPESA_ENVIRONMENT=production
MPESA_CONSUMER_KEY=<live key>
MPESA_CONSUMER_SECRET=<live secret>
MPESA_SHORTCODE=<the shop's paybill or shortcode>
MPESA_PASSKEY=<the live passkey>
MPESA_CALLBACK_URL=https://pos.example.co.ke/api/mpesa/callback/
MPESA_CALLBACK_TOKEN=<the long random one from step 1>
MPESA_TRANSACTION_TYPE=CustomerPayBillOnline
MPESA_ACCOUNT_REFERENCE=GreenLight

# Only if the shop wants restock messages on WhatsApp.
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=
OWNER_WHATSAPP_NUMBER=
```

`DATABASE_URL` stays empty while the books are one file; setting it is the Postgres
switch, and the last section says what else changes with it.

`CORS_ALLOWED_ORIGINS` is left empty on purpose: the built app is served from this
same address, so it needs no cross-origin permission, and an entry there is a door.

`SHOP_PAYBILL` is not a key - the paybill printed on a receipt is read from
`MPESA_SHORTCODE`, so the number the customer pays and the number the till charges
are the same by construction.

## 5. Install the app

```bash
cd /srv/duka-pos/backend
sudo -u duka python3.12 -m venv backend_venv
sudo -u duka backend_venv/bin/pip install -r requirements.txt
sudo -u duka backend_venv/bin/python manage.py check --deploy
```

Read every warning that comes back before going on. Then the built app:

Node is not needed on the server. Build it on the shop machine (`npm ci && npm run
build` in `frontend`) and copy the result:

```bash
rsync -av --delete frontend/dist/ duka@pos.example.co.ke:/srv/duka-pos/frontend/dist/
```

## 6. systemd, so it comes back by itself

```bash
sudo cp /srv/duka-pos/deploy/duka-pos.service /etc/systemd/system/duka-pos.service
sudo systemctl daemon-reload
sudo systemctl enable --now duka-pos
systemctl status duka-pos
journalctl -u duka-pos -n 50
```

The unit runs `check --deploy --fail-level ERROR`, `migrate` and `collectstatic`
before gunicorn starts. If it refuses to start, the reason is in `journalctl`, and
it is almost always one of the two errors the check is there to catch: a media
folder `duka` cannot write, or a callback URL that is not public HTTPS.

## 7. nginx and the certificate

```bash
sudo cp /srv/duka-pos/deploy/nginx-duka.conf /etc/nginx/sites-available/duka-pos
sudo ln -s /etc/nginx/sites-available/duka-pos /etc/nginx/sites-enabled/duka-pos
sudo rm -f /etc/nginx/sites-enabled/default
# replace the four pos.example.co.ke occurrences with the real address first
sudo sed -i 's/pos\.example\.co\.ke/pos.yourdomain.co.ke/g' /etc/nginx/sites-available/duka-pos
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d pos.yourdomain.co.ke
```

Then confirm the app answers from outside the server:

```bash
curl -I https://pos.yourdomain.co.ke/
curl -o /dev/null -w '%{http_code}\n' https://pos.yourdomain.co.ke/api/mpesa/callback/
```

The second must print `405` - the route exists and refuses GET. A `404` means nginx
is not passing the API, and every M-Pesa payment will then sit unpaid on the shelf.
`manage.py check_mpesa` makes the same two calls for you.

## 8. The pre-flight that matters

```bash
cd /srv/duka-pos/backend
sudo -u duka backend_venv/bin/python manage.py check_mpesa
```

It reads `.env`, names each setting without printing any of them, asks Daraja for a
token with the real keys, and checks the public callback URL answers. A 401 from
Daraja almost always means keys from one environment pasted into the other. When it
says the configuration is ready, send yourself a prompt:

```bash
sudo -u duka backend_venv/bin/python manage.py check_mpesa --test-stk 07XXXXXXXX
```

Decline it on the phone. It proves the shortcode, the passkey and the address
without recording a payment anywhere.

## 9. Move the books across, then open

Do this with the shop's current machine stopped, so nothing is written mid-copy.

```bash
# from the shop machine
scp C:/ShopData/greenlight.sqlite3 duka@pos.example.co.ke:/tmp/
ssh duka@pos.example.co.ke 'install -o duka -g duka -m 600 /tmp/greenlight.sqlite3 /srv/duka-pos/data/greenlight.sqlite3'
```

The server reads only the file `DATABASE_PATH` names. It never opens the `.sqlite3`
files that sit in the project folder - those are spares, and two servers pointed at
two files is two sets of books.

Then product photos, first run, and the schedule:

```bash
rsync -av --delete 'C:/Users/HP/OneDrive/Documents/duka-pos/backend/media/' \
  duka@pos.example.co.ke:/srv/duka-pos/backend/media/

sudo -u duka bash -c 'cd /srv/duka-pos/backend && backend_venv/bin/python manage.py backup_shop --destination /srv/backups'
sudo crontab -u duka -e
```

```cron
*/5  * * * *  cd /srv/duka-pos/backend && backend_venv/bin/python manage.py reconcile_mpesa --older-than 5 >> /srv/duka-pos/backend/logs/reconcile.log 2>&1
*/15 * * * *  cd /srv/duka-pos/backend && backend_venv/bin/python manage.py deliver_alerts >> /srv/duka-pos/backend/logs/alerts.log 2>&1
30 21 * * *   cd /srv/duka-pos/backend && backend_venv/bin/python manage.py backup_shop --destination /srv/backups >> /srv/duka-pos/backend/logs/backup.log 2>&1
```

`reconcile_mpesa` is not optional. A callback lost between Safaricom and nginx
leaves a customer who has paid and a bill that still says "waiting"; this is what
finds them.

Copy the `/srv/backups` folder off the server weekly (`rsync -a duka@pos...:/srv/backups /backups/duka/`). A
backup that lives on the same disk as the database is a second copy of the same
risk.

## 10. Smoke test before the first customer

1. Sign in on a till, sell one item for cash, print it. One receipt on the roll, not two.
2. Sell on credit, then settle it from the ledger.
3. Take goods back (return) and check stock and the refund line move together.
4. Prompt M-Pesa on a small bill, pay it, and confirm the receipt flips to Paid
   **without** pressing Check status - that is the callback arriving through nginx.
5. Prompt again, let it sit past five minutes, then press *Check payment now*: it
   asks Daraja and settles.
6. `python manage.py check_mpesa` again, and read `/srv/duka-pos/backend/logs/shop.log`
   for anything you did not expect.
7. Restore drill: take yesterday's copy, put it somewhere else, and open it. The
   manifest written beside it says how many receipts it should hold.

## Rollback

The shop machine is untouched until step 9 and keeps working throughout. If the
server misbehaves, stop it (`sudo systemctl stop duka-pos`), point the tills back at
`http://<shop machine>:8000`, and copy the server's `greenlight.sqlite3` back to
`C:\ShopData\` before anything trades again - the server will have taken sales the
laptop has never seen.

## When the shop outgrows one file

The move is to PostgreSQL, and the code is already ready for it: set `DATABASE_URL`
instead of `DATABASE_PATH`, use `--workers 3` or more in
`/etc/systemd/system/duka-pos.service`, and `backup_shop` already runs `pg_dump` and
verifies it with `pg_restore`. The tables then need copying across once, with the
server stopped - see the `Postgres` section in the project plan, deliberately
deferred until the counters actually stall.
