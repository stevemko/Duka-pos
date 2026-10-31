from django.contrib import admin
from .models import Payment, Sale, SaleReceipt


class LedgerReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Sale)
class SaleAdmin(LedgerReadOnlyAdmin):
    list_display = ["product", "quantity", "price_sold_at", "total", "profit", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["product__name"]


@admin.register(SaleReceipt)
class SaleReceiptAdmin(LedgerReadOnlyAdmin):
    list_display = ["id", "customer_name", "customer_phone", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["customer_name", "customer_phone", "id"]


@admin.register(Payment)
class PaymentAdmin(LedgerReadOnlyAdmin):
    list_display = ["receipt", "amount", "method", "status", "reference", "created_at"]
    list_filter = ["method", "status", "created_at"]
    search_fields = ["reference", "receipt__customer_name", "receipt__customer_phone"]
