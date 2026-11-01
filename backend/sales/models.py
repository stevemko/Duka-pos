import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, DecimalField, F, IntegerField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from products.models import Product


def stk_pending_cutoff():
    return timezone.now() - timedelta(minutes=settings.MPESA_STK_PENDING_TIMEOUT_MINUTES)


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
    idempotency_key = models.CharField(max_length=64, blank=True, null=True, unique=True)
    # A digest of the basket the key was first used with. A retry after a lost
    # answer must replay that same sale; the same key carrying a different
    # customer or tender is a mistake at the counter, not a duplicate request.
    idempotency_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
    def balance(self):
        return self.total - self.amount_paid

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
