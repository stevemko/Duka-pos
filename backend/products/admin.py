from django.contrib import admin
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "sku", "category", "cost_price", "selling_price", "stock_quantity", "reorder_threshold", "needs_restock"]
    list_filter = ["category"]
    search_fields = ["name", "sku"]
