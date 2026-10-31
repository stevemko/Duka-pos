from django.contrib import admin

from .models import Expense


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["date", "category", "description", "amount", "branch", "recorded_by"]
    list_filter = ["category", "payment_method", "branch", "date"]
    search_fields = ["description", "reference"]
    date_hierarchy = "date"
