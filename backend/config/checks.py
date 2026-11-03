"""Startup validation for the settings a shop cannot trade on.

Two audiences, so two sets of checks:

* `manage.py check` - which every start, migrate and test run does - reports only
  what stops the shop from taking money: an unwritable photo folder and an M-Pesa
  setup that would lose a payment without saying so.
* `manage.py check --deploy` - which the service unit runs before it lets the
  server boot - adds the hosting shape: DEBUG, the host names, the CORS origins.
  Those are warnings about a laptop setup, and a laptop setup is honest work.
"""

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from decouple import config
from django.conf import settings
from django.core.checks import Error, Warning, register

# Values left in an example file, or too short to be a real secret.
PLACEHOLDERS = {
    "",
    "changeme",
    "change-me",
    "replace-me",
    "secret",
    "your-secret-key-here",
    "generate-a-long-random-value",
}

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
LOCAL_SUFFIXES = (".local", ".internal", ".lan", ".home", ".localdomain")

# Where the till is expected to be opened from while it is still being built.
DEV_ORIGINS = ("localhost", "127.0.0.1", "5173", "5174", "3000")


def host_is_public(host):
    """True when a name or address could be reached from outside the shop.

    Safaricom posts payment callbacks from its own network, so an address the shop
    opens in a browser is not proof of anything. An address literal is judged
    against the reserved ranges; a name is judged on its shape, because resolving
    it here would only prove this machine can see it.
    """
    host = (host or "").strip().lower().rstrip(".")
    if not host or host in LOCAL_HOSTS or host.endswith(LOCAL_SUFFIXES):
        return False
    # A name with no dot is a LAN hostname (`duka-office`), not a public domain.
    if "." not in host and ":" not in host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_loopback
        or address.is_link_local
        or address.is_private
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _is_dev_origin(origin):
    if not origin.strip():
        # An empty entry is what `CORS_ALLOWED_ORIGINS=` reads as on a hosted
        # shop, and it means "no other origin needs permission".
        return False
    host = (urlsplit(origin if "//" in origin else f"//{origin}").hostname or "").lower()
    return host == "*" or any(marker in host for marker in DEV_ORIGINS)


def _value(name):
    """Read a setting the same way sales/mpesa.py does.

    Both must see one answer, or a check can pass while the payment path is broken.
    """
    return str(config(name, default="")).strip()


def _callback_problem(message, hint, warning_id, error_id):
    """One sentence about a lost payment, at the severity this machine deserves.

    A laptop being built towards opening has a tunnel address that changes daily,
    so it gets a warning and still starts. A server that trades gets an error, and
    the service unit refuses to boot it until the callback can actually arrive.
    """
    if settings.DEBUG:
        return Warning(message, hint=hint, id=warning_id)
    return Error(message, hint=hint, id=error_id)


@register(deploy=True)
def check_opening_settings(app_configs, **kwargs):
    """Report the settings that only work on one machine."""
    problems = []

    if settings.DEBUG:
        problems.append(Warning(
            "The shop is running with DEBUG=True.",
            hint=(
                "DEBUG shows the internals of a failure to whoever is looking at the screen "
                "and keeps a copy of every request in memory. Set DEBUG=False in backend/.env "
                "before opening."
            ),
            id="config.W010",
        ))

    if len(settings.SECRET_KEY.strip()) < 50 or settings.SECRET_KEY.strip().lower() in PLACEHOLDERS:
        problems.append(Warning(
            "SECRET_KEY is short or still the example value.",
            hint=(
                "Generate one with `python -c \"from django.core.management.utils import "
                "get_random_secret_key;print(get_random_secret_key())\"` and put it in "
                "backend/.env. Anyone who has it can forge a signed session."
            ),
            id="config.W011",
        ))

    if not [host for host in settings.ALLOWED_HOSTS if host != "*" and host_is_public(host)]:
        problems.append(Warning(
            f"ALLOWED_HOSTS ({', '.join(settings.ALLOWED_HOSTS)}) names no public address.",
            hint=(
                "Add the domain or public IP the counters will type, for example "
                "ALLOWED_HOSTS=pos.example.co.ke. A hosted shop that answers to no public "
                "host refuses its own customers."
            ),
            id="config.W012",
        ))

    dev_origins = [origin for origin in settings.CORS_ALLOWED_ORIGINS if _is_dev_origin(origin)]
    if dev_origins and not settings.DEBUG:
        problems.append(Warning(
            f"CORS_ALLOWED_ORIGINS still lists the development machine: {', '.join(dev_origins)}.",
            hint=(
                "The built app is served from this same server, so it needs no CORS entry "
                "at all. Leave only the origins that genuinely live elsewhere."
            ),
            id="config.W013",
        ))
    if not settings.DEBUG and not settings.CSRF_TRUSTED_ORIGINS:
        problems.append(Warning(
            "CSRF_TRUSTED_ORIGINS is empty.",
            hint=(
                "List the public origin, e.g. CSRF_TRUSTED_ORIGINS=https://pos.example.co.ke, "
                "so the admin and the login page keep working behind HTTPS."
            ),
            id="config.W014",
        ))

    environment = _value("MPESA_ENVIRONMENT").lower() or "sandbox"
    if _value("MPESA_CONSUMER_KEY") and environment != "production" and not settings.DEBUG:
        problems.append(Warning(
            "M-Pesa is pointed at the Daraja sandbox while the server runs with DEBUG=False.",
            hint="Sandbox prompts never settle real money. Set MPESA_ENVIRONMENT=production to open.",
            id="config.W015",
        ))
    return problems


@register()
def check_trade_blockers(app_configs, **kwargs):
    """Report what stops this machine from taking money at all."""
    return _check_media_writable() + _check_mpesa()


def _check_media_writable():
    """Product photos are written by the till, so the folder has to accept them."""
    media_root = Path(str(settings.MEDIA_ROOT))
    if not media_root.exists():
        try:
            media_root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return [Error(
                f"MEDIA_ROOT ({media_root}) could not be created: {error}",
                hint="Give the account that runs the server write access to the media folder.",
                id="config.E010",
            )]
    probe = media_root / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError as error:
        return [Error(
            f"MEDIA_ROOT ({media_root}) is not writable: {error}",
            hint=(
                "Product photos are written here. Run the server as an account that can write "
                "the folder, or point MEDIA_ROOT somewhere it can."
            ),
            id="config.E011",
        )]
    finally:
        probe.unlink(missing_ok=True)
    return []


def _check_mpesa():
    """An M-Pesa setup that is half-configured loses payments without saying so."""
    if not _value("MPESA_CONSUMER_KEY") and not _value("MPESA_CALLBACK_URL"):
        # No M-Pesa at all is a choice, not a fault: the till keeps the cash and
        # Paybill paths and never pretends a prompt went out.
        return []

    problems = []
    missing = [
        name
        for name in (
            "MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET", "MPESA_SHORTCODE", "MPESA_PASSKEY",
        )
        if not _value(name)
    ]
    if missing:
        problems.append(Warning(
            f"M-Pesa STK Push is partly configured; these are still empty: {', '.join(missing)}.",
            hint="Fill them in backend/.env, or leave the till to cash and Paybill.",
            id="config.W016",
        ))

    callback_url = _value("MPESA_CALLBACK_URL")
    if not callback_url:
        problems.append(_callback_problem(
            "MPESA_CALLBACK_URL is empty while M-Pesa keys are set.",
            (
                "Safaricom needs the public HTTPS address of this shop's callback route, for "
                "example https://pos.example.co.ke/api/mpesa/callback/. Without it a customer "
                "pays and the bill stays open."
            ),
            "config.W017", "config.E012",
        ))
    elif (
        not callback_url.startswith("https://")
        or not host_is_public(urlsplit(callback_url).hostname or "")
    ):
        problems.append(_callback_problem(
            f"MPESA_CALLBACK_URL ({callback_url}) is not a public HTTPS address.",
            (
                "Safaricom posts the confirmation from outside the shop network. A localhost or "
                "192.168.x.x address means the money leaves the customer and nothing ever marks "
                "the bill paid."
            ),
            "config.W018", "config.E013",
        ))

    if _value("MPESA_CALLBACK_TOKEN") in PLACEHOLDERS:
        problems.append(_callback_problem(
            "MPESA_CALLBACK_TOKEN is empty or still the example value.",
            (
                "Generate one with `python -c \"import secrets;print(secrets.token_urlsafe(32))\"`. "
                "It is the only thing stopping a stranger from marking any bill paid."
            ),
            "config.W019", "config.E014",
        ))

    environment = _value("MPESA_ENVIRONMENT").lower() or "sandbox"
    if environment not in {"sandbox", "production"}:
        problems.append(Error(
            f"MPESA_ENVIRONMENT is '{environment}'.",
            hint="It must be sandbox or production.",
            id="config.E015",
        ))
    return problems
