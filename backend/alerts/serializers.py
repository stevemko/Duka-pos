from rest_framework import serializers
from .models import StockAlert


class StockAlertSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = StockAlert
        fields = ["id", "product", "product_name", "stock_at_trigger", "whatsapp_sent", "triggered_at"]
