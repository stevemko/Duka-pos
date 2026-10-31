import base64
import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from decouple import config
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

PLACEHOLDER_VALUES = {"", "generate-a-long-random-value"}

# Daraja issues tokens valid for one hour; refresh a minute early.
_TOKEN_TTL_SECONDS = 55 * 60


class MpesaError(Exception):
    pass


def normalize_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = f"254{digits[1:]}"
    elif digits.startswith("7") and len(digits) == 9:
        digits = f"254{digits}"
    if not re.fullmatch(r"254[17]\d{8}", digits):
        raise MpesaError("Enter a valid Kenyan mobile number, such as 07XXXXXXXX.")
    return digits


def _timeout():
    return config("MPESA_REQUEST_TIMEOUT_SECONDS", default=15, cast=int)


def _post_json(url, payload, headers):
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=_timeout()) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8", errors="replace")[:300]
        except OSError:
            pass
        logger.warning("Daraja HTTP %s: %s", error.code, detail)
        raise MpesaError(
            f"Safaricom rejected the request (HTTP {error.code}). "
            "Check the Daraja setup and try again."
        ) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        logger.warning("Daraja request failed: %s", error)
        raise MpesaError("Could not reach Safaricom. The payment request was not confirmed.") from error


def _load_config():
    values = {
        "consumer_key": config("MPESA_CONSUMER_KEY", default=""),
        "consumer_secret": config("MPESA_CONSUMER_SECRET", default=""),
        "shortcode": config("MPESA_SHORTCODE", default=""),
        "passkey": config("MPESA_PASSKEY", default=""),
        "callback_url": config("MPESA_CALLBACK_URL", default=""),
        "callback_token": config("MPESA_CALLBACK_TOKEN", default=""),
        "environment": config("MPESA_ENVIRONMENT", default="sandbox").lower(),
    }

    missing = [
        name for name in ("consumer_key", "consumer_secret", "shortcode", "passkey", "callback_url")
        if not values[name]
    ]
    if missing:
        raise MpesaError("M-Pesa STK Push is not configured on the server yet.")
    if values["callback_token"] in PLACEHOLDER_VALUES:
        raise MpesaError("MPESA_CALLBACK_TOKEN must be a long random value.")
    if values["environment"] not in {"sandbox", "production"}:
        raise MpesaError("MPESA_ENVIRONMENT must be sandbox or production.")
    if not values["callback_url"].startswith("https://"):
        raise MpesaError("MPESA_CALLBACK_URL must be a publicly reachable HTTPS URL.")
    return values


def _access_token(settings_values):
    # Daraja tokens last an hour. Re-authenticating for every prompt adds a
    # second round trip to each sale and hits their rate limits at a busy counter.
    cache_key = f"mpesa_access_token:{settings_values['environment']}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    credentials = base64.b64encode(
        f"{settings_values['consumer_key']}:{settings_values['consumer_secret']}".encode("utf-8")
    ).decode("ascii")
    token_request = Request(
        f"https://{_api_host(settings_values)}/oauth/v1/generate?grant_type=client_credentials",
        headers={"Authorization": f"Basic {credentials}"},
    )
    try:
        with urlopen(token_request, timeout=_timeout()) as response:
            token = json.loads(response.read().decode("utf-8"))["access_token"]
    except (HTTPError, URLError, TimeoutError, KeyError, json.JSONDecodeError) as error:
        logger.warning("Daraja authentication failed: %s", error)
        raise MpesaError("Could not authenticate with Safaricom Daraja.") from error

    cache.set(cache_key, token, _TOKEN_TTL_SECONDS)
    return token


def _api_host(settings_values):
    return "api.safaricom.co.ke" if settings_values["environment"] == "production" else "sandbox.safaricom.co.ke"


def _password_and_timestamp(settings_values):
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        f"{settings_values['shortcode']}{settings_values['passkey']}{timestamp}".encode("utf-8")
    ).decode("ascii")
    return password, timestamp


def initiate_stk_push(payment, phone):
    settings_values = _load_config()
    callback_url = settings_values["callback_url"]
    callback_url = (
        f"{callback_url}{'&' if '?' in callback_url else '?'}"
        f"token={settings_values['callback_token']}"
    )

    access_token = _access_token(settings_values)
    password, timestamp = _password_and_timestamp(settings_values)
    amount = int(payment.amount)
    payload = {
        "BusinessShortCode": settings_values["shortcode"],
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": config("MPESA_TRANSACTION_TYPE", default="CustomerPayBillOnline"),
        "Amount": amount,
        "PartyA": normalize_phone(phone),
        "PartyB": settings_values["shortcode"],
        "PhoneNumber": normalize_phone(phone),
        "CallBackURL": callback_url,
        "AccountReference": config("MPESA_ACCOUNT_REFERENCE", default="GreenLight")[:12],
        "TransactionDesc": config("MPESA_TRANSACTION_DESCRIPTION", default="POS payment")[:13],
    }
    return _post_json(
        f"https://{_api_host(settings_values)}/mpesa/stkpush/v1/processrequest",
        payload,
        {"Authorization": f"Bearer {access_token}"},
    )


def query_stk_push(payment):
    """Ask Daraja for the status of an STK request that has not called back."""
    settings_values = _load_config()
    access_token = _access_token(settings_values)
    password, timestamp = _password_and_timestamp(settings_values)
    payload = {
        "BusinessShortCode": settings_values["shortcode"],
        "Password": password,
        "Timestamp": timestamp,
        "CheckoutRequestID": payment.checkout_request_id,
    }
    return _post_json(
        f"https://{_api_host(settings_values)}/mpesa/stkpushquery/v1/query",
        payload,
        {"Authorization": f"Bearer {access_token}"},
    )
