import re
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import (
    Count,
    DecimalField,
    F,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from products.models import Product


def stk_pending_cutoff():
    return timezone.now() - timedelta(minutes=settings.MPESA_STK_PENDING_TIMEOUT_MINUTES)


def normalize_customer_phone(phone):
    """Put a shop-floor phone number in one shape, or return "" if it is not one.

    Customers are matched by number, so 07XX, 07XX written as +2547XX, 0017XX and
    2547XX must all land on the same ledger. A number that does not look like a
    Kenyan mobile is left unkeyed rather than guessed at, and the profile stays
    findable by name instead.
    """
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("254") and len(digits) >= 12:
        digits = digits[3:]
    if len(digits) == 10 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 9 and digits[0] in "17":
        return f"254{digits}"
    return ""


CENTS = DecimalField(max_digits=14, decimal_places=2)


def receipt_owed_expression(receipt_ref="pk"):
    """What one bill still owes, floored at zero, as a SQL expression.

    A refund or a payment bigger than the bill leaves cash in the customer's
    favour, but that is settled over the counter - it is never carried as a credit
    note against the account or against a different bill.
    """
    bought = (
        Sale.objects.filter(receipt=OuterRef(receipt_ref))
        .values("receipt")
        .annotate(amount=Sum("total"))
        .values("amount")
    )
    returned = (
        SaleReturn.objects.filter(receipt=OuterRef(receipt_ref))
        .values("receipt")
        .annotate(amount=Sum("value"))
        .values("amount")
    )
    paid = (
        Payment.objects.filter(
            receipt=OuterRef(receipt_ref), status=Payment.Status.SUCCEEDED
        )
        .values("receipt")
        .annotate(amount=Sum("amount"))
        .values("amount")
    )
    net = (
        Coalesce(Subquery(bought, output_field=CENTS), Decimal("0.00"), output_field=CENTS)
        - Coalesce(Subquery(returned, output_field=CENTS), Decimal("0.00"), output_field=CENTS)
        - Coalesce(Subquery(paid, output_field=CENTS), Decimal("0.00"), output_field=CENTS)
    )
    return Greatest(Decimal("0.00"), net, output_field=CENTS)


class CustomerQuerySet(models.QuerySet):
    def with_balances(self):
        """Attach what each account owes, so a list of debtors costs one query.

        Every bill is floored on its own before the debts are added up. Summing
        bought, returned and paid for the whole account instead would let an
        overpayment or a refund on one bill cancel what is owed on another, and
        the shop would report money coming in that nobody owes.
        """
        owed_per_bill = (
            SaleReceipt.objects.filter(customer=OuterRef("pk"))
            .values("customer")
            .annotate(amount=Sum(receipt_owed_expression(), output_field=CENTS))
            .values("amount")
        )
        return self.annotate(
            outstanding_amount=Coalesce(
                Subquery(owed_per_bill, output_field=CENTS),
                Decimal("0.00"),
                output_field=CENTS,
            ),
            # The receipts join is the only multi-row path here, so the sums stay
            # inside subqueries: joining items and payments as well would multiply
            # the rows underneath both aggregates and invent money.
            last_purchase=Max("receipts__created_at"),
            receipt_count=Count("receipts", distinct=True),
        )


class Customer(models.Model):
    """A person the shop sells to, and the account their debts sit on.

    The name and number printed on a receipt are the snapshot taken at the counter
    and are never rewritten. This row is the running book underneath them, so a debt
    still belongs to the same customer after a spelling correction or a new phone.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Each shop keeps its own credit book: the same person owing at two branches is
    # two ledgers, because the money is owed to whichever shop let the goods go.
    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.PROTECT,
        related_name="customers",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    # Derived from phone by save(); empty when the number is not a recognisable
    # Kenyan mobile, which keeps those rows out of the uniqueness check.
    phone_key = models.CharField(max_length=30, blank=True)
    # Left blank, the account has no ceiling: the shop decides per customer how much
    # to let them carry, and an unset limit must not block a sale.
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomerQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "phone_key"],
                condition=~Q(phone_key=""),
                name="unique_customer_phone_per_branch",
            ),
        ]
        indexes = [
            models.Index(fields=["phone_key"], name="customer_phone_key_idx"),
            models.Index(fields=["branch", "name"], name="customer_branch_name_idx"),
        ]

    def save(self, *args, **kwargs):
        self.phone_key = normalize_customer_phone(self.phone)
        super().save(*args, **kwargs)

    @property
    def outstanding(self):
        """What the shop is still waiting for on this account.

        Each bill is settled on its own and only then added up, so a refund on a
        paid-up bill cannot hide what a different bill still owes.
        """
        if hasattr(self, "outstanding_amount"):
            return self.outstanding_amount
        owed = Decimal("0.00")
        for receipt in self.receipts.with_totals():
            owed += receipt.balance
        return owed if owed > 0 else Decimal("0.00")

    @property
    def credit_headroom(self):
        """How much more this account may take on credit, or None if uncapped."""
        if self.credit_limit is None:
            return None
        headroom = self.credit_limit - self.outstanding
        return headroom if headroom > 0 else Decimal("0.00")

    def __str__(self):
        return self.name


class SaleReceiptQuerySet(models.QuerySet):
    def with_totals(self):
        item_total = (
            Sale.objects.filter(receipt=OuterRef("pk"))
            .values("receipt")
            .annotate(total=Sum("total"))
            .values("total")
        )
        amount_paid = (
            Payment.objects.filter(receipt=OuterRef("pk"), status=Payment.Status.SUCCEEDED)
            .values("receipt")
            .annotate(total=Sum("amount"))
            .values("total")
        )
        active_pending = (
            Payment.objects.filter(
                receipt=OuterRef("pk"),
                status=Payment.Status.PENDING,
                created_at__gte=stk_pending_cutoff(),
            )
            .values("receipt")
            .annotate(total=Count("id"))
            .values("total")
        )
        returned = (
            SaleReturn.objects.filter(receipt=OuterRef("pk"))
            .values("receipt")
            .annotate(total=Sum("value"))
            .values("total")
        )
        return self.annotate(
            annotated_total=Coalesce(
                Subquery(item_total, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Decimal("0.00"),
            ),
            annotated_amount_paid=Coalesce(
                Subquery(amount_paid, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Decimal("0.00"),
            ),
            annotated_pending_count=Coalesce(
                Subquery(active_pending, output_field=IntegerField()),
                0,
            ),
            annotated_returned=Coalesce(
                Subquery(returned, output_field=DecimalField(max_digits=12, decimal_places=2)),
                Decimal("0.00"),
            ),
        ).annotate(
            # What the customer still has to settle: the bill less whatever came
            # back on it. Every payment check and credit figure reads this.
            annotated_net_total=F("annotated_total") - F("annotated_returned"),
        )


class SaleReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.PROTECT,
        related_name="receipts",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="receipts_created",
        null=True,
        blank=True,
    )
    customer_name = models.CharField(max_length=200, blank=True)
    customer_phone = models.CharField(max_length=30, blank=True)
    # The account this sale belongs to, when the till picked one. PROTECT: a
    # customer with a receipt in the books cannot be deleted out of the ledger.
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="receipts",
        null=True,
        blank=True,
    )
    idempotency_key = models.CharField(max_length=64, blank=True, null=True, unique=True)
    # A digest of the basket the key was first used with. A retry after a lost
    # answer must replay that same sale; the same key carrying a different
    # customer or tender is a mistake at the counter, not a duplicate request.
    idempotency_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # A period the owner has put away. The row stays exactly as it was: the money
    # owed on it still belongs to a customer, the totals still count, and it can
    # still be paid. Closing only takes it out of the day-to-day list.
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="receipts_closed",
        null=True,
        blank=True,
    )

    objects = SaleReceiptQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="receipt_created_idx"),
            models.Index(fields=["branch", "-created_at"], name="receipt_branch_created_idx"),
        ]

    @property
    def total(self):
        if hasattr(self, "annotated_total"):
            return self.annotated_total
        return sum((item.total for item in self.items.all()), Decimal("0.00"))

    @property
    def amount_paid(self):
        if hasattr(self, "annotated_amount_paid"):
            return self.annotated_amount_paid
        return sum(
            (payment.amount for payment in self.payments.filter(status=Payment.Status.SUCCEEDED)),
            Decimal("0.00"),
        )

    @property
    def returned_total(self):
        if hasattr(self, "annotated_returned"):
            return self.annotated_returned
        return sum(
            (entry.value for entry in self.returns.all()), Decimal("0.00")
        )

    @property
    def net_total(self):
        """What the bill is worth now: what left the shelf less what came back."""
        if hasattr(self, "annotated_net_total"):
            return self.annotated_net_total
        return self.total - self.returned_total

    @property
    def refunded_total(self):
        return sum(
            (entry.refund for entry in self.returns.all()), Decimal("0.00")
        )

    @property
    def balance(self):
        owed = self.net_total - self.amount_paid
        # Cash handed back with a return sits on that return row, not as a debt the
        # bill carries back to the counter. A settled bill reads zero, never a
        # negative figure the till would try to collect.
        return owed if owed > 0 else Decimal("0.00")

    @property
    def payment_status(self):
        # Money that already covers the bill wins over an open prompt: a customer
        # who pays cash while their M-Pesa request still sits on the phone has
        # paid, and the till must not keep saying "waiting".
        if self.balance <= 0:
            return "paid"
        if hasattr(self, "annotated_pending_count"):
            has_active_pending = self.annotated_pending_count > 0
        else:
            has_active_pending = self.payments.filter(
                status=Payment.Status.PENDING,
                created_at__gte=stk_pending_cutoff(),
            ).exists()
        if has_active_pending:
            return "payment_pending"
        if self.amount_paid > 0:
            return "partially_paid"
        return "on_credit"

    def expire_stale_stk_payments(self):
        return self.payments.filter(
            method=Payment.Method.MPESA_STK,
            status=Payment.Status.PENDING,
            created_at__lt=stk_pending_cutoff(),
        ).update(
            status=Payment.Status.FAILED,
            result_description="M-Pesa confirmation timed out. Prompt the customer again if needed.",
        )

    def __str__(self):
        return f"Receipt {self.id}"


class Sale(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="sales")
    receipt = models.ForeignKey(
        SaleReceipt,
        on_delete=models.PROTECT,
        related_name="items",
        blank=True,
        null=True,
    )
    quantity = models.PositiveIntegerField()
    cost_price_at_sale = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    price_sold_at = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    profit = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="sale_created_idx"),
            models.Index(fields=["product", "created_at"], name="sale_product_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0) & Q(price_sold_at__gte=F("cost_price_at_sale")),
                name="sale_quantity_positive_and_no_loss",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Recorded sales cannot be changed.")
        self.cost_price_at_sale = Decimal(str(self.product.cost_price))
        self.price_sold_at = Decimal(str(self.price_sold_at))
        if self.price_sold_at < self.cost_price_at_sale:
            raise ValidationError("A sale price cannot be below the wholesale cost.")
        self.total = self.price_sold_at * self.quantity
        self.profit = (self.price_sold_at - self.cost_price_at_sale) * self.quantity
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Recorded sales cannot be deleted.")

    def __str__(self):
        return f"{self.quantity} x {self.product.name} @ {self.price_sold_at}"


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        MOBILE_MONEY = "mobile_money", "Mobile money"
        MPESA_STK = "mpesa_stk", "M-Pesa STK Push"
        MPESA_PAYBILL = "mpesa_paybill", "M-Pesa Paybill"
        CARD = "card", "Card"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt = models.ForeignKey(SaleReceipt, on_delete=models.PROTECT, related_name="payments")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="payments_recorded",
        null=True,
        blank=True,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices)
    reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUCCEEDED)
    checkout_request_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    merchant_request_id = models.CharField(max_length=100, blank=True)
    result_description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="payment_status_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payment_amount_positive",
            ),
        ]

    def __str__(self):
        return f"{self.method}: {self.amount}"


class SaleReturn(models.Model):
    """Goods a customer brought back and the money that went with them.

    A return never rewrites the bill it belongs to. The sale line stays exactly as
    it was rung up, this row says what came back, and the shelf is put right in the
    same write. Two rows the shop can point at is what keeps a refund auditable:
    the takings lose only what was actually handed over the counter.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    receipt = models.ForeignKey(SaleReceipt, on_delete=models.PROTECT, related_name="returns")
    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.PROTECT,
        related_name="returns",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="returns_taken",
        null=True,
        blank=True,
    )
    # What the goods came back at: the price they were sold for, never today's.
    value = models.DecimalField(max_digits=10, decimal_places=2)
    # Money actually put back in the customer's hand. The shop works this out from
    # what was paid against what they now owe, so a refund cannot be typed in.
    refund = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    method = models.CharField(max_length=20, choices=Payment.Method.choices, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    # The same guard the till uses for a sale: a return whose answer was lost must
    # replay, not hand over the money twice.
    idempotency_key = models.CharField(max_length=64, blank=True, null=True, unique=True)
    idempotency_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["-created_at"], name="return_created_idx"),
            models.Index(fields=["receipt", "-created_at"], name="return_receipt_created_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(value__gte=0) & Q(refund__gte=0),
                name="return_amounts_never_negative",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Recorded returns cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Recorded returns cannot be deleted.")

    def __str__(self):
        return f"Return of {self.value} against receipt {self.receipt_id}"


class SaleReturnItem(models.Model):
    """One line of a return: how many of what came back, at what it went out for."""

    sale_return = models.ForeignKey(
        SaleReturn, on_delete=models.PROTECT, related_name="items"
    )
    # The sale line this came off, so the shop can prove the goods were actually
    # sold here and cannot return more than left the shelf.
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="returns")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_returns")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    total = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    profit = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0), name="return_item_quantity_positive"
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Recorded return lines cannot be changed.")
        self.unit_price = self.sale.price_sold_at
        self.unit_cost = self.sale.cost_price_at_sale
        self.total = self.unit_price * self.quantity
        self.profit = (self.unit_price - self.unit_cost) * self.quantity
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Recorded return lines cannot be deleted.")

    def __str__(self):
        return f"{self.quantity} x {self.product.name} back"
