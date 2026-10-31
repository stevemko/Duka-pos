import logging

from decouple import config
from twilio.rest import Client

logger = logging.getLogger(__name__)


def send_restock_whatsapp(product):
    """
    Sends a WhatsApp message via Twilio's WhatsApp API when a product
    needs restocking. Returns True if the message was sent successfully.
    """
    account_sid = config("TWILIO_ACCOUNT_SID", default="")
    auth_token = config("TWILIO_AUTH_TOKEN", default="")
    from_whatsapp = config("TWILIO_WHATSAPP_FROM", default="")
    to_whatsapp = config("OWNER_WHATSAPP_NUMBER", default="")

    if not all([account_sid, auth_token, from_whatsapp, to_whatsapp]):
        # Not configured yet — skip silently so local dev doesn't crash.
        return False

    # The alert is sent after the sale has committed, so it must never be able to
    # hold a worker open waiting on Twilio.
    client = Client(account_sid, auth_token, timeout=10)
    message_body = (
        f"Restock alert: {product.name} is down to {product.stock_quantity} units "
        f"(threshold: {product.reorder_threshold}). Time to reorder."
    )

    try:
        client.messages.create(
            from_=f"whatsapp:{from_whatsapp}",
            to=f"whatsapp:{to_whatsapp}",
            body=message_body,
        )
        return True
    except Exception:
        logger.exception("WhatsApp restock alert failed for %s", product.name)
        return False
