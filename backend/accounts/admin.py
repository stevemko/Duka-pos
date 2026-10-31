from django.contrib import admin

from .models import Branch, StaffProfile


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "phone", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "code"]


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "branch", "phone"]
    list_filter = ["branch"]
    search_fields = ["user__username", "user__first_name", "user__last_name"]
