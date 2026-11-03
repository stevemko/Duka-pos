"""Pre-flight check of the Daraja STK Push setup, run before the shop goes live.

Nothing here prints a secret. Every setting is reported by name, and the only
values shown are the ones the shop already knows about - the environment it is
pointed at, the API host that follows from it, and the callback URL.
"""

from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from decouple import config
from django.core.cache import cache
from django.core.management.base import BaseCommand

from config.checks import host_is_public
from sales.mpesa import (
    MpesaError,
    PLACEHOLDER_VALUES,
    _api_host,
    _load_config,
    fetch_access_token,
    initiate_stk_push,
    normalize_phone,
)

# The URL Safaricom must be able to reach on this server, from config/urls.py.
CALLBACK_PATH = "/api/mpesa/callback/"

# Names only. The values are never read into the output.
SETTING_NAMES = (
    "MPESA_ENVIRONMENT",
    "MPESA_CONSUMER_KEY",
    "MPESA_CONSUMER_SECRET",
    "MPESA_SHORTCODE",
    "MPESA_PASSKEY",
    "MPESA_CALLBACK_URL",
    "MPESA_CALLBACK_TOKEN",
)


class Command(BaseCommand):
    help = (
        "Check the M-Pesa Daraja configuration before going live: which settings "
        "are set, whether the callback URL is public and points at this app, and "
        "whether the keys actually authenticate."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-live",
            action="store_true",
            help="Only inspect the configuration; do not call Safaricom.",
        )
        parser.add_argument(
            "--test-stk",
            metavar="PHONE",
            help=(
                "Send a real KES 1 prompt to this phone to prove the shortcode and "
                "passkey. Decline it on the phone - the test prompt is not recorded "
                "against any bill."
            ),
        )

    def handle(self, *args, **options):
        self.failures = 0
        self.warnings = 0

        self.stdout.write("Green Light POS - M-Pesa pre-flight")
        self.stdout.write("=" * 46)
        self._check_presence()
        environment, values = self._check_environment()
        self._check_callback_url(values)
        self._check_token_length(values)
        if not options["skip_live"]:
            self._check_live(values, environment)
        if options["test_stk"]:
            self._check_test_prompt(values, options["test_stk"])

        self.stdout.write("")
        if self.failures:
            self.stdout.write(self.style.ERROR(
                f"{self.failures} problem(s) and {self.warnings} warning(s). "
                "M-Pesa prompts will not work until the problems are fixed."
            ))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(
            "Configuration looks ready for M-Pesa STK Push."
            + (f" {self.warnings} warning(s) noted above." if self.warnings else "")
        ))

    # Reporting helpers -----------------------------------------------------

    def ok(self, message):
        self.stdout.write(self.style.SUCCESS(f"  [ok]   {message}"))

    def warn(self, message):
        self.stdout.write(self.style.WARNING(f"  [warn] {message}"))
        self.warnings += 1

    def fail(self, message):
        self.stdout.write(self.style.ERROR(f"  [fail] {message}"))
        self.failures += 1

    # Checks ----------------------------------------------------------------

    def _check_presence(self):
        self.stdout.write("\nSettings in backend/.env")
        for name in SETTING_NAMES:
            value = config(name, default="")
            if not value:
                if name == "MPESA_ENVIRONMENT":
                    self.warn(
                        "MPESA_ENVIRONMENT is not set. The app assumes sandbox; "
                        "write it out explicitly so nobody opens the shop on test keys."
                    )
                else:
                    self.fail(f"{name} is not set.")
            elif value in PLACEHOLDER_VALUES:
                self.fail(f"{name} is still the example placeholder value.")
            elif name == "MPESA_ENVIRONMENT":
                self.ok(f"{name} = {value.strip().lower()}")
            elif name == "MPESA_CALLBACK_URL":
                self.ok(f"{name} = {value.strip()}")
            else:
                # Length only: it catches a key truncated in a paste without
                # putting the secret in the terminal history.
                self.ok(f"{name} is set ({len(value.strip())} characters).")

    def _check_environment(self):
        self.stdout.write("\nWhich Daraja this shop talks to")
        environment = config("MPESA_ENVIRONMENT", default="sandbox").strip().lower()
        if environment not in {"sandbox", "production"}:
            self.fail(
                f"MPESA_ENVIRONMENT is '{environment}'. It must be sandbox or production."
            )
            return environment, None
        settings_values = {
            "consumer_key": config("MPESA_CONSUMER_KEY", default=""),
            "consumer_secret": config("MPESA_CONSUMER_SECRET", default=""),
            "shortcode": config("MPESA_SHORTCODE", default=""),
            "passkey": config("MPESA_PASSKEY", default=""),
            "callback_url": config("MPESA_CALLBACK_URL", default=""),
            "callback_token": config("MPESA_CALLBACK_TOKEN", default=""),
            "environment": environment,
        }
        host = _api_host(settings_values)
        self.ok(f"Environment '{environment}' uses {host}.")
        if environment == "sandbox":
            self.warn(
                "Sandbox prompts never settle real money. Before opening, set "
                "MPESA_ENVIRONMENT=production and use the keys from the live Daraja app."
            )
        return environment, settings_values

    def _check_callback_url(self, values):
        self.stdout.write("\nCallback URL Safaricom must reach")
        if values is None:
            return
        raw = values["callback_url"].strip()
        if not raw:
            self.fail("MPESA_CALLBACK_URL is not set.")
            return
        if not raw.startswith("https://"):
            self.fail(
                "MPESA_CALLBACK_URL must start with https:// - Safaricom will not "
                "post a callback to a plain http:// or a local address."
            )
            return
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        if not host:
            self.fail("MPESA_CALLBACK_URL has no host name.")
            return
        if not host_is_public(host):
            self.fail(
                f"MPESA_CALLBACK_URL points at {host}, which only exists on the shop "
                "network. Safaricom cannot reach it - use the public domain or IP "
                "of the hosted server."
            )
        else:
            self.ok(f"Host {host} is publicly addressable.")
        path = (parts.path or "/").rstrip("/") + "/"
        if path != CALLBACK_PATH:
            self.fail(
                f"Callback path is {parts.path or '/'}, but this app receives prompts at "
                f"{CALLBACK_PATH}. A wrong path means paid customers never settle their bills."
            )
        else:
            self.ok(f"Path {CALLBACK_PATH} matches the route in this app.")
        if "token=" in raw:
            self.warn(
                "MPESA_CALLBACK_URL already carries a token= query. The app appends its "
                "own, so drop the one typed into the URL."
            )

    def _check_token_length(self, values):
        self.stdout.write("\nCallback secret")
        if values is None:
            return
        token = values["callback_token"]
        if token in PLACEHOLDER_VALUES:
            self.fail("MPESA_CALLBACK_TOKEN is missing or still the placeholder.")
            self.stdout.write(
                "        Generate one: python -c \"import secrets;print(secrets.token_urlsafe(32))\""
            )
            return
        if len(token) < 16:
            self.warn("MPESA_CALLBACK_TOKEN is short. 32 url-safe random characters is the norm.")
        else:
            self.ok(f"MPESA_CALLBACK_TOKEN is set ({len(token)} characters).")

    def _check_live(self, values, environment):
        self.stdout.write("\nLive checks")
        if values is None:
            return
        try:
            _load_config()
        except MpesaError as error:
            self.fail(f"Configuration rejected: {error}")
            return

        cache.delete(f"mpesa_access_token:{environment}")
        try:
            fetch_access_token(values)
        except MpesaError as error:
            self.fail(f"Daraja authentication: {error}")
        else:
            self.ok("Daraja accepted these keys and issued an access token.")

        self._check_reachable(values)

    def _check_reachable(self, values):
        """Ask the public URL for the callback route without completing a payment.

        GET is not a method the callback accepts, so any HTTP answer at all - and
        not a connection error - proves DNS, TLS and the reverse proxy in front of
        this app are all in place for Safaricom.
        """
        url = values["callback_url"].strip()
        try:
            with urlopen(Request(url, method="GET"), timeout=15) as response:
                code = response.status
        except HTTPError as error:
            code = error.code
        except (URLError, TimeoutError, OSError) as error:
            self.fail(
                f"Could not reach {url} from this machine ({error.__class__.__name__}). "
                "Safaricom posts callbacks from outside the shop network, so the "
                "domain must resolve and answer on the public internet."
            )
            return
        if code in (403, 405):
            self.ok(f"{url} answers HTTP {code}, so the callback route is reachable.")
        elif code == 404:
            self.fail(
                f"{url} answered HTTP 404. The route is not there - check the domain "
                "points at this app and that ALLOWED_HOSTS includes it."
            )
        else:
            self.warn(f"{url} answered HTTP {code}; expected 403 or 405 from the callback route.")

    def _check_test_prompt(self, values, phone):
        self.stdout.write("\nTest prompt")
        if values is None:
            self.fail("Cannot send a test prompt while the configuration is incomplete.")
            return
        try:
            msisdn = normalize_phone(phone)
        except MpesaError as error:
            self.fail(str(error))
            return

        class _Prompt:
            """Stand-in for a Payment row: the payload only needs the amount."""

            amount = 1

        # Deliberately not saved. A recorded test payment would sit in the
        # append-only ledger forever, and the till would try to reconcile it.
        try:
            response = initiate_stk_push(_Prompt(), msisdn)
        except MpesaError as error:
            self.fail(str(error))
            return
        result_code = str(response.get("ResponseCode", ""))
        if result_code != "0":
            self.fail(
                f"Safaricom refused the test prompt "
                f"(ResponseCode {result_code or 'missing'}): "
                f"{response.get('ErrorMessage') or response.get('ResponseDescription') or 'no reason given'}"
            )
            return
        self.ok(
            f"Prompt sent to {msisdn} (CheckoutRequestID "
            f"{response.get('CheckoutRequestID', '')}). Decline it on the phone - "
            "this test is not attached to any bill."
        )
