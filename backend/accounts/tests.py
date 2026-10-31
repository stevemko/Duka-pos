from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import Branch, StaffProfile


class UserManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_superuser(
            username="owner", password="manager-pass-1", email="owner@example.com"
        )
        self.client.force_authenticate(self.admin)
        self.branch = Branch.objects.create(name="Town branch", code="TOWN")

    def test_super_admin_creates_cashier_and_cashier_can_sign_in(self):
        response = self.client.post(
            reverse("user-list"),
            {
                "username": "cashier1",
                "first_name": "Asha",
                "last_name": "Mwikali",
                "role": "cashier",
                "branch": str(self.branch.id),
                "phone": "0700111222",
                "password": "cashier-pass-1",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["role"], "cashier")
        self.assertEqual(response.data["branch"]["code"], "TOWN")
        cashier = get_user_model().objects.get(username="cashier1")
        self.assertFalse(cashier.is_staff)
        login = APIClient().post(
            reverse("api-login"),
            {"username": "cashier1", "password": "cashier-pass-1"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.data["user"]["role"], "cashier")
        self.assertFalse(login.data["user"]["can_manage"])
        self.assertFalse(login.data["can_manage_users"])

    def test_manager_cannot_manage_accounts(self):
        manager = get_user_model().objects.create_user(
            username="manager", password="manager-pass-1", is_staff=True
        )
        StaffProfile.objects.create(user=manager, branch=self.branch)
        client = APIClient()
        client.force_authenticate(manager)

        self.assertEqual(client.get(reverse("user-list")).status_code, 403)
        cashier = get_user_model().objects.create_user(
            username="cashier2", password="cashier-pass-2"
        )
        self.assertEqual(
            client.post(
                reverse("user-set-password", kwargs={"pk": cashier.pk}),
                {"new_password": "new-password-2"},
                format="json",
            ).status_code,
            403,
        )

    def test_cashier_cannot_manage_users_branches_or_products(self):
        cashier = get_user_model().objects.create_user(
            username="cashier3", password="cashier-pass-3"
        )
        StaffProfile.objects.create(user=cashier, branch=self.branch)
        client = APIClient()
        client.force_authenticate(cashier)

        self.assertEqual(client.get(reverse("user-list")).status_code, 403)
        self.assertEqual(
            client.post(reverse("branch-list"), {"name": "X", "code": "X"}).status_code, 403
        )
        self.assertEqual(client.get(reverse("branch-list")).status_code, 200)

    def test_super_admin_resets_a_password_and_old_session_is_revoked(self):
        cashier = get_user_model().objects.create_user(
            username="cashier4", password="old-password-1"
        )
        old_token = Token.objects.create(user=cashier)

        response = self.client.post(
            reverse("user-set-password", kwargs={"pk": cashier.pk}),
            {"new_password": "new-password-2"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        cashier.refresh_from_db()
        self.assertTrue(cashier.check_password("new-password-2"))
        self.assertFalse(Token.objects.filter(pk=old_token.pk).exists())

    def test_super_admin_cannot_deactivate_self_or_remove_last_manager(self):
        self_deactivate = self.client.patch(
            reverse("user-detail", kwargs={"pk": self.admin.pk}),
            {"is_active": False},
            format="json",
        )
        demote = self.client.patch(
            reverse("user-detail", kwargs={"pk": self.admin.pk}),
            {"role": "cashier"},
            format="json",
        )

        self.assertEqual(self_deactivate.status_code, 400)
        self.assertEqual(demote.status_code, 400)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.admin.is_staff)

    def test_changing_a_password_returns_a_fresh_token(self):
        response = self.client.post(
            reverse("api-change-password"),
            {"current_password": "manager-pass-1", "new_password": "manager-pass-2"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["token"])
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("manager-pass-2"))

    def test_login_reports_branch_and_account_rights(self):
        response = APIClient().post(
            reverse("api-login"),
            {"username": "owner", "password": "manager-pass-1"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["user"]["can_manage"])
        self.assertTrue(response.data["user"]["can_view_all_branches"])
        self.assertTrue(response.data["can_manage_users"])

    def test_shop_info_exposes_paybill_to_signed_in_staff(self):
        response = self.client.get(reverse("shop-info"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("paybill", response.data)
        self.assertEqual(response.data["name"], "Greenlight LED Accessories")


class BranchTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.manager = get_user_model().objects.create_user(
            username="manager", password="manager-pass-1", is_staff=True
        )
        self.client.force_authenticate(self.manager)

    def test_branch_codes_are_unique_ignoring_case(self):
        Branch.objects.create(name="Main shop", code="SHOP")

        duplicate = self.client.post(
            reverse("branch-list"), {"name": "Another", "code": "shop"}, format="json"
        )
        created = self.client.post(
            reverse("branch-list"), {"name": "Westlands", "code": "west"}, format="json"
        )

        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data["code"], "WEST")

    def test_branch_with_records_cannot_be_deleted(self):
        branch = Branch.objects.create(name="Town", code="TOWN")
        cashier = get_user_model().objects.create_user(username="cashier", password="cashier-pass-1")
        StaffProfile.objects.create(user=cashier, branch=branch)

        response = self.client.delete(reverse("branch-detail", kwargs={"pk": branch.pk}))

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Branch.objects.filter(pk=branch.pk).exists())
