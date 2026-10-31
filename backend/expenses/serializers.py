from rest_framework import serializers

from .models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Expense._meta.get_field("branch").related_model.objects.all(),
        required=False,
        allow_null=True,
    )
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="Main shop")
    recorded_by_name = serializers.SerializerMethodField()
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    method_label = serializers.CharField(source="get_payment_method_display", read_only=True)

    class Meta:
        model = Expense
        fields = [
            "id", "date", "category", "category_label", "description", "amount",
            "payment_method", "method_label", "reference", "branch", "branch_name",
            "recorded_by_name", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_recorded_by_name(self, expense):
        if not expense.recorded_by:
            return ""
        return expense.recorded_by.get_full_name() or expense.recorded_by.get_username()

    def validate_amount(self, amount):
        if amount <= 0:
            raise serializers.ValidationError("Expense amount must be greater than zero.")
        return amount
