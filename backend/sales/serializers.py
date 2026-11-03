from decimal import Decimal

from rest_framework import serializers

from .models import (
    Customer,
    Payment,
    Sale,
    SaleReceipt,
    SaleReturn,
    SaleReturnItem,
    normalize_customer_phone,
)
from products.models import Product


class SaleSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    receipt_id = serializers.UUIDField(source="receipt.id", read_only=True, allow_null=True)

    class Meta:
        model = Sale
        fields = [
            "id", "product", "product_name", "quantity", "cost_price_at_sale", "price_sold_at",
            "total", "profit", "receipt_id", "created_at",
        ]
        read_only_fields = ["cost_price_at_sale", "total", "profit"]

    def validate(self, data):
        product = data.get("product")
        quantity = data.get("quantity")
        if product and quantity and quantity > product.stock_quantity:
            raise serializers.ValidationError(
                f"Only {product.stock_quantity} units of {product.name} left in stock."
            )
        price = data.get("price_sold_at")
        if product and price is not None and price < product.cost_price:
            raise serializers.ValidationError({
                "price_sold_at": (
                    f"{product.name} cannot be sold below its wholesale cost of "
                    f"KES {product.cost_price}. The retail price is only a guide."
                )
            })
        return data


class PaymentSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id", "amount", "method", "reference", "status", "result_description",
            "created_by_name", "created_at",
        ]
        read_only_fields = fields

    def get_created_by_name(self, payment):
        if not payment.created_by:
            return ""
        return payment.created_by.get_full_name() or payment.created_by.get_username()


class SaleReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    sale_id = serializers.UUIDField(source="sale.id", read_only=True)

    class Meta:
        model = SaleReturnItem
        fields = [
            "id", "sale_id", "product", "product_name", "quantity",
            "unit_price", "total", "created_at",
        ]
        read_only_fields = fields


class SaleReturnSerializer(serializers.ModelSerializer):
    items = SaleReturnItemSerializer(many=True, read_only=True)
    taken_by_name = serializers.SerializerMethodField()
    method_label = serializers.SerializerMethodField()

    class Meta:
        model = SaleReturn
        fields = [
            "id", "value", "refund", "method", "method_label", "reference", "reason",
            "taken_by_name", "items", "created_at",
        ]
        read_only_fields = fields

    def get_taken_by_name(self, entry_return):
        if not entry_return.created_by:
            return ""
        return entry_return.created_by.get_full_name() or entry_return.created_by.get_username()

    def get_method_label(self, entry_return):
        if not entry_return.method:
            return ""
        return dict(Payment.Method.choices).get(entry_return.method, entry_return.method)


class SaleReceiptSerializer(serializers.ModelSerializer):
    items = SaleSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    returns = SaleReturnSerializer(many=True, read_only=True)
    total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    returned_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    net_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    refunded_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    # What the till holds beyond this bill: a cash payment that an M-Pesa prompt
    # later doubled. A balance floors at zero, so this is the only place the shop
    # is told it is carrying someone's change.
    overpaid_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    payment_status = serializers.CharField(read_only=True)
    branch_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SaleReceipt
        fields = [
            "id", "branch", "branch_name", "created_by_name", "customer", "customer_name",
            "customer_phone", "items", "payments", "returns", "total", "returned_total",
            "net_total", "refunded_total", "amount_paid", "balance", "overpaid_amount",
            "payment_status", "created_at", "closed_at",
        ]

    def get_branch_name(self, receipt):
        return receipt.branch.name if receipt.branch else "Main shop"

    def get_created_by_name(self, receipt):
        if not receipt.created_by:
            return ""
        return receipt.created_by.get_full_name() or receipt.created_by.get_username()


class CustomerSerializer(serializers.ModelSerializer):
    """A credit account. The shop sets the ceiling; the receipts set the debt.

    A customer's name and number are typed at the counter, so the two are checked
    here rather than at the database: a duplicate ledger is worse than a typo,
    because the debt then sits on the wrong person.
    """

    outstanding = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    credit_headroom = serializers.DecimalField(
        max_digits=12, decimal_places=2, read_only=True, allow_null=True
    )
    branch_name = serializers.SerializerMethodField()
    last_purchase = serializers.SerializerMethodField()
    receipt_count = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id", "branch", "branch_name", "name", "phone", "credit_limit",
            "credit_headroom", "notes", "is_active", "outstanding", "last_purchase",
            "receipt_count", "created_at",
        ]
        # branch comes from the logged-in user's shop, never from the form.
        read_only_fields = [
            "id", "branch", "outstanding", "credit_headroom", "last_purchase",
            "receipt_count", "created_at",
        ]

    def get_branch_name(self, customer):
        return customer.branch.name if customer.branch else "Main shop"

    def get_last_purchase(self, customer):
        # Set by the list query; a freshly saved row has no annotation to read.
        moment = getattr(customer, "last_purchase", None)
        return moment.isoformat() if moment else None

    def get_receipt_count(self, customer):
        return getattr(customer, "receipt_count", None)

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Enter the customer's name.")
        return name

    def validate_phone(self, value):
        phone = (value or "").strip()
        key = normalize_customer_phone(phone)
        if not key:
            return phone
        branch = self.context.get("branch")
        clash = Customer.objects.filter(phone_key=key)
        if branch is not None:
            clash = clash.filter(branch=branch)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        clash = clash.first()
        if clash:
            raise serializers.ValidationError(
                f"{clash.name} is already on this shop's book with that number. "
                "Open their account instead of starting a second one."
            )
        return phone

    def validate_credit_limit(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("A credit limit cannot be negative.")
        return value


class CustomerPaymentSerializer(serializers.Serializer):
    """Money handed in against an account rather than against one bill."""

    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=[
        choice for choice in Payment.Method.choices
        if choice[0] != Payment.Method.MPESA_STK
    ])
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate(self, data):
        return _validate_payment_reference(data)


class CheckoutItemSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    price_sold_at = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))


PAYBILL_REFERENCE_ERROR = "Enter the M-Pesa confirmation code for this Paybill payment."


def _validate_payment_reference(data):
    if data.get("method") == Payment.Method.MPESA_PAYBILL and not (data.get("reference") or "").strip():
        raise serializers.ValidationError({"reference": PAYBILL_REFERENCE_ERROR})
    return data


class CheckoutPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=[
        choice for choice in Payment.Method.choices
        if choice[0] != Payment.Method.MPESA_STK
    ])
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate(self, data):
        return _validate_payment_reference(data)


class ReceiptPaymentSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    method = serializers.ChoiceField(choices=[
        choice for choice in Payment.Method.choices
        if choice[0] != Payment.Method.MPESA_STK
    ])
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate(self, data):
        return _validate_payment_reference(data)


class ReturnItemSerializer(serializers.Serializer):
    """One line of a return: which sale line came back, and how many of it."""

    sale = serializers.PrimaryKeyRelatedField(queryset=Sale.objects.all())
    quantity = serializers.IntegerField(min_value=1)


class ReturnCreateSerializer(serializers.Serializer):
    """The basket a customer brought back.

    Only the lines and the reason are typed. What the goods are worth comes off the
    bill at their original price, and how much cash goes back over the counter is
    worked out from what was paid against what is now owed - a refund the till can
    choose is a refund the till can get wrong.
    """

    items = ReturnItemSerializer(many=True, allow_empty=False)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
    refund_method = serializers.ChoiceField(
        choices=[
            choice for choice in Payment.Method.choices
            if choice[0] != Payment.Method.MPESA_STK
        ],
        required=False,
        allow_blank=True,
    )
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(max_length=64, required=False, allow_blank=True)

    def validate(self, data):
        if (
            data.get("refund_method") == Payment.Method.MPESA_PAYBILL
            and not (data.get("reference") or "").strip()
        ):
            raise serializers.ValidationError({
                "reference": "Enter the M-Pesa confirmation code for this refund."
            })
        return data


class StkPushSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=30)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1.00"), required=False)


class CheckoutSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    customer_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    # The account the goods go on, picked at the till. The two fields above stay:
    # they are what got printed on the receipt and must never change afterwards.
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.filter(is_active=True), required=False, allow_null=True
    )
    idempotency_key = serializers.CharField(max_length=64, required=False, allow_blank=True)
    items = CheckoutItemSerializer(many=True, allow_empty=False)
    payments = CheckoutPaymentSerializer(many=True, required=False, allow_empty=True)

    def validate(self, data):
        total = Decimal("0.00")
        for item in data["items"]:
            product = item["product"]
            price = item["price_sold_at"]
            if price < product.cost_price:
                raise serializers.ValidationError({
                    "items": [
                        f"Sale price for {product.name} cannot be below its wholesale cost "
                        f"of KES {product.cost_price}. The retail price is only a guide."
                    ]
                })
            total += price * item["quantity"]

        amount_paid = sum((payment["amount"] for payment in data.get("payments", [])), Decimal("0.00"))
        if amount_paid > total:
            raise serializers.ValidationError({"payments": "Payments cannot exceed the receipt total."})
        if amount_paid < total and not (
            data.get("customer") or data.get("customer_name") or data.get("customer_phone")
        ):
            raise serializers.ValidationError({
                "customer": "Customer name or phone is required when a balance is unpaid."
            })
        return data
