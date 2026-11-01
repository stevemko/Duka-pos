"""The shop's credit book: who owes what, and which bill a payment settles.

Receipts stay the source of truth. A customer row is an index onto them, so a debt
is written once, at the till, and money paid against the account settles the real
receipts instead of living beside them as a number someone typed in.
"""

from decimal import Decimal

from django.db.models import Count
from rest_framework.exceptions import ValidationError

from .models import Customer, Payment, SaleReceipt, SaleReturn, normalize_customer_phone


def _return_description(entry_return):
    goods = ", ".join(
        f"{item.quantity} x {item.product.name}" for item in entry_return.items.all()
    )
    reason = f" ({entry_return.reason})" if entry_return.reason else ""
    # Say so when part of the goods had already been paid for: the bill only came
    # down by the rest, and the reader needs to know where the other part went.
    handed_back = (
        f" - {entry_return.refund:.2f} handed back" if entry_return.refund else ""
    )
    return f"Returned: {goods}{reason}{handed_back}"


def find_customer(branch, customer_id=None, phone=""):
    """Pick the account a sale belongs to, or None when nobody was named.

    A customer chosen at the till wins. Otherwise the number decides, because two
    tills must not open two ledgers for one person over how a phone number was
    typed. Matching by name is left to the cashier: too many customers share a name
    for the server to pick one safely.
    """
    if customer_id:
        return Customer.objects.filter(pk=customer_id).first()
    key = normalize_customer_phone(phone)
    if not key:
        return None
    queryset = Customer.objects.filter(phone_key=key)
    if branch:
        queryset = queryset.filter(branch=branch)
    return queryset.first()


def check_credit_limit(customer, new_debt):
    """Refuse a sale that would take an account past the ceiling the owner set.

    An account with no limit is the shop's own decision to trust that customer, so
    it must never block a sale: only a stated limit is enforced.
    """
    if customer is None or customer.credit_limit is None or new_debt <= 0:
        return
    owed = customer.outstanding
    headroom = customer.credit_limit - owed
    if new_debt <= headroom:
        return
    shortfall = new_debt - headroom if headroom > 0 else new_debt
    raise ValidationError({
        "customer": [
            f"{customer.name} already owes {owed:.2f} of the agreed "
            f"{customer.credit_limit:.2f} credit. Take at least {shortfall:.2f} as payment "
            "on this sale, or raise the limit for them."
        ]
    })


def settle_account_payment(customer, amount, method, reference="", taken_by=None):
    """Pay money into an account, settling the oldest bills first.

    Returns the receipts written and the money left over. The remainder has to be
    said out loud at the counter: cash handed over for an account is not all owed to
    the shop, and quietly keeping the change would be a hole in the takings.
    """
    open_receipts = (
        SaleReceipt.objects.with_totals().filter(customer=customer).order_by("created_at")
    )
    remaining = amount
    settled = []
    for receipt in open_receipts:
        if remaining <= 0:
            break
        # The net, not the billed total: goods the shop took back are no longer a
        # debt, and settling them again would take money the customer does not owe.
        due = receipt.net_total - receipt.amount_paid
        if due <= 0:
            continue
        part = due if due < remaining else remaining
        Payment.objects.create(
            receipt=receipt,
            created_by=taken_by,
            amount=part,
            method=method,
            reference=reference,
            status=Payment.Status.SUCCEEDED,
            result_description="Paid against the customer's account.",
        )
        remaining -= part
        settled.append(receipt)
    return settled, remaining


def ledger(customer, limit=400):
    """The account as the customer and the manager need to read it together.

    Goods going out and money coming in, oldest first, with the running debt after
    each line. A debt is proved by the bills behind it, not by one total the shop
    typed in, so every line points back at a real receipt or payment.
    """
    entries = []
    receipts = (
        SaleReceipt.objects.with_totals()
        .filter(customer=customer)
        .annotate(line_count=Count("items", distinct=True))
        .order_by("created_at")[:limit]
    )
    for receipt in receipts:
        entries.append(
            {
                "date": receipt.created_at,
                "type": "sale",
                "reference": str(receipt.id),
                "description": f"{receipt.line_count} line(s) on this bill",
                "debit": receipt.total,
                # The money handed in at the till is a Payment row of its own, and
                # it appears below on its own line. Counting it here too would
                # settle the same note twice and understate what is owed.
                "credit": Decimal("0.00"),
            }
        )
    payments = (
        Payment.objects.filter(
            receipt__customer=customer, status=Payment.Status.SUCCEEDED
        )
        .order_by("created_at")[:limit]
    )
    for payment in payments:
        entries.append(
            {
                "date": payment.created_at,
                "type": "payment",
                "reference": str(payment.receipt_id),
                "description": payment.reference or payment.get_method_display(),
                "debit": Decimal("0.00"),
                "credit": payment.amount,
            }
        )

    returns = (
        SaleReturn.objects.filter(receipt__customer=customer)
        .prefetch_related("items__product")
        .order_by("created_at")[:limit]
    )
    for entry_return in returns:
        # Only the part that was still owed clears the debt. Cash already taken for
        # these goods went back over the counter with them, so counting the whole
        # return as a credit would clear a debt the customer never had on this bill
        # and could hide what another bill still owes.
        entries.append(
            {
                "date": entry_return.created_at,
                "type": "return",
                "reference": str(entry_return.receipt_id),
                "description": _return_description(entry_return),
                "debit": Decimal("0.00"),
                "credit": entry_return.value - entry_return.refund,
            }
        )

    entries.sort(key=lambda entry: entry["date"])
    running = Decimal("0.00")
    for entry in entries:
        running += entry["debit"] - entry["credit"]
        entry["balance"] = running if running > 0 else Decimal("0.00")

    return entries
