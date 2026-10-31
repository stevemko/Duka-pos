from decimal import Decimal

from rest_framework import serializers

from .models import Payment, Sale, SaleReceipt
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


class SaleReceiptSerializer(serializers.ModelSerializer):
    items = SaleSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    payment_status = serializers.CharField(read_only=True)
    branch_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SaleReceipt
        fields = [
            "id", "branch", "branch_name", "created_by_name", "customer_name",
            "customer_phone", "items", "payments", "total", "amount_paid", "balance",
            "payment_status", "created_at",
        ]

    def get_branch_name(self, receipt):
        return receipt.branch.name if receipt.branch else "Main shop"

    def get_created_by_name(self, receipt):
        if not receipt.created_by:
            return ""
        return receipt.created_by.get_full_name() or receipt.created_by.get_username()


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


class StkPushSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=30)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("1.00"), required=False)


class CheckoutSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    customer_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
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
        if amount_paid < total and not (data.get("customer_name") or data.get("customer_phone")):
            raise serializers.ValidationError({
                "customer": "Customer name or phone is required when a balance is unpaid."
            })
        return data
