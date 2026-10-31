from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Branch, StaffProfile

from .models import Expense


class ExpenseTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = get_user_model().objects.create_user(
            username="manager", password="manager-pass-1", is_staff=True
        )
        self.client.force_authenticate(self.manager)
        self.main = Branch.objects.get(code="MAIN")

    def create_expense(self, **overrides):
        payload = {
            "date": "2026-10-30",
            "category": "rent",
            "description": "October shop rent",
            "amount": "15000.00",
            "payment_method": "cash",
        }
        payload.update(overrides)
        return self.client.post(reverse("expense-list"), payload, format="json")

    def test_manager_records_expense_with_branch_and_recorder(self):
        response = self.create_expense()

        self.assertEqual(response.status_code, 201)
        expense = Expense.objects.get(pk=response.data["id"])
        self.assertEqual(expense.branch, self.main)
        self.assertEqual(expense.recorded_by, self.manager)
        self.assertEqual(response.data["recorded_by_name"], "manager")
        self.assertEqual(response.data["branch_name"], "Main shop")

    def test_cashier_cannot_read_or_write_expenses(self):
        cashier = get_user_model().objects.create_user(
            username="cashier", password="cashier-pass-1"
        )
        client = APIClient()
        client.force_authenticate(cashier)

        self.assertEqual(client.get(reverse("expense-list")).status_code, 403)
        self.assertEqual(
            client.post(
                reverse("expense-list"),
                {"category": "rent", "description": "x", "amount": "10.00"},
                format="json",
            ).status_code,
            403,
        )

    def test_summary_groups_expenses_by_category(self):
        self.create_expense()
        self.create_expense(category="utilities", amount="2500.00", description="Power")

        response = self.client.get(reverse("expense-summary"), {"month": "2026-10"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total"], Decimal("17500.00"))
        self.assertEqual(response.data["entries"], 2)
        categories = {row["category"]: row["total"] for row in response.data["by_category"]}
        self.assertEqual(categories["rent"], Decimal("15000.00"))

    def test_branch_scoped_manager_only_sees_own_branch(self):
        town = Branch.objects.create(name="Town", code="TOWN")
        manager = get_user_model().objects.create_user(
            username="town-manager", password="manager-pass-2", is_staff=True
        )
        StaffProfile.objects.create(user=manager, branch=town)
        client = APIClient()
        client.force_authenticate(manager)

        self.create_expense(branch=str(town.id))
        self.create_expense(description="Main shop rent")

        response = client.get(reverse("expense-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["description"], "October shop rent")

    def test_manager_cannot_record_expense_for_another_branch(self):
        town = Branch.objects.create(name="Town", code="TOWN")
        manager = get_user_model().objects.create_user(
            username="town-manager", password="manager-pass-2", is_staff=True
        )
        StaffProfile.objects.create(user=manager, branch=town)
        client = APIClient()
        client.force_authenticate(manager)

        response = client.post(
            reverse("expense-list"),
            {
                "category": "rent",
                "description": "Elsewhere",
                "amount": "10.00",
                "branch": str(self.main.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_unknown_branch_filter_is_rejected_instead_of_widening_scope(self):
        response = self.client.get(
            reverse("expense-list"), {"branch": "00000000-0000-0000-0000-000000000000"}
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_dates_and_amounts_are_rejected(self):
        bad_date = self.client.get(reverse("expense-list"), {"start_date": "30/10/2026"})
        bad_amount = self.create_expense(amount="0.00")

        self.assertEqual(bad_date.status_code, 400)
        self.assertEqual(bad_amount.status_code, 400)
        self.assertEqual(Expense.objects.count(), 0)
