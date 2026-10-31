import uuid
from django.db import models
from products.models import Product


class StockAlert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="alerts")
    stock_at_trigger = models.PositiveIntegerField()
    whatsapp_sent = models.BooleanField(default=False)
    triggered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-triggered_at"]

    def __str__(self):
        return f"Restock alert: {self.product.name} ({self.stock_at_trigger} left)"
