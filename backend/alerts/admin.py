from django.contrib import admin
from .models import StockAlert


@admin.register(StockAlert)
class StockAlertAdmin(admin.ModelAdmin):
    list_display = ["product", "stock_at_trigger", "whatsapp_sent", "triggered_at"]
    list_filter = ["whatsapp_sent"]
