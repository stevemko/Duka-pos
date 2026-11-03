import io
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from products.models import Product

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


class BackupShopCommandTests(TransactionTestCase):
    """A copy of the books that cannot be reopened is not a copy.

    These run outside a wrapping transaction because SQLite will not take a
    backup snapshot through a connection that is itself mid-write, which is also
    how the command runs in the shop: a separate process, in autocommit.
    """

    def setUp(self):
        Product.objects.create(
            name="Backup bulb", sku="BACKUP-1",
            cost_price="180.00", selling_price="250.00", stock_quantity=4,
        )
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.destination = Path(folder.name)
        self.output = io.StringIO()

    def back_up(self, *extra):
        call_command(
            "backup_shop",
            "--destination",
            str(self.destination),
            "--without-media",
            *extra,
            stdout=self.output,
        )
        return sorted(path.name for path in self.destination.glob("shop-*.sqlite3"))

    def test_writes_a_copy_that_opens_and_holds_the_records(self):
        copies = self.back_up()

        self.assertEqual(len(copies), 1)
        with closing(sqlite3.connect(self.destination / copies[0])) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM products_product WHERE sku='BACKUP-1'"
                ).fetchone()[0],
                1,
            )
        self.assertIn("opens cleanly", self.output.getvalue())

    def test_dry_run_writes_nothing(self):
        copies = self.back_up("--dry-run")

        self.assertEqual(copies, [])

    def test_only_the_newest_copies_are_kept(self):
        for name in (
            "shop-2026-01-01-000000.sqlite3",
            "shop-2026-01-02-000000.sqlite3",
            "shop-2026-01-03-000000.sqlite3",
        ):
            (self.destination / name).write_bytes(b"old")

        copies = self.back_up("--keep", "2")

        self.assertEqual(len(copies), 2)
        self.assertIn("shop-2026-01-03-000000.sqlite3", copies)
        self.assertNotIn("shop-2026-01-01-000000.sqlite3", copies)
        self.assertNotIn("shop-2026-01-02-000000.sqlite3", copies)

    def test_product_photos_travel_with_the_books(self):
        media = self.destination / "media-root"
        (media / "products").mkdir(parents=True)
        (media / "products" / "bulb.jpg").write_bytes(b"photo")
        (media / "products" / "spot.jpg").write_bytes(b"photo")

        with override_settings(MEDIA_ROOT=str(media)):
            call_command(
                "backup_shop", "--destination", str(self.destination), stdout=self.output
            )

        self.assertTrue((self.destination / "media" / "products" / "bulb.jpg").exists())
        self.assertIn("2 photo file(s) copied", self.output.getvalue())

    def test_a_note_is_left_beside_the_copy_saying_what_it_holds(self):
        copies = self.back_up()

        manifest = next(self.destination.glob("shop-*.manifest.txt"))
        text = manifest.read_text(encoding="utf-8")

        self.assertIn("engine: sqlite", text)
        self.assertIn(copies[0], text)
        self.assertIn("restore:", text)

    def test_pruning_takes_a_copy_and_its_note_together(self):
        for name in ("shop-2026-01-01-000000", "shop-2026-01-02-000000"):
            (self.destination / f"{name}.sqlite3").write_bytes(b"old")
            (self.destination / f"{name}.manifest.txt").write_text("old", encoding="utf-8")

        self.back_up("--keep", "2")

        self.assertFalse((self.destination / "shop-2026-01-01-000000.sqlite3").exists())
        self.assertFalse((self.destination / "shop-2026-01-01-000000.manifest.txt").exists())
        self.assertTrue((self.destination / "shop-2026-01-02-000000.manifest.txt").exists())

    def test_a_postgres_database_is_copied_with_pg_dump(self):
        """The branch written before the shop ever moves engines.

        A backup job that dies with an error on the night of a migration is how a
        shop loses a month of books, so the Postgres path has to work the first
        time it is needed.
        """
        database = SimpleNamespace(
            vendor="postgresql",
            settings_dict={
                "NAME": "greenlight", "USER": "duka", "PASSWORD": "db-secret",
                "HOST": "10.0.0.5", "PORT": "5432",
            },
        )
        calls = []

        def run(argv, *args, **kwargs):
            calls.append((argv, kwargs.get("env")))
            for argument in argv:
                if argument.startswith("--file="):
                    Path(argument.split("=", 1)[1]).write_bytes(b"dump")
                elif argument.startswith("--list="):
                    Path(argument.split("=", 1)[1]).write_text(
                        "TABLE sales_salereceipt", encoding="utf-8"
                    )
            return SimpleNamespace(stdout="", stderr="")

        with \
            patch("accounts.management.commands.backup_shop.connections", {"default": database}), \
            patch("accounts.management.commands.backup_shop.subprocess.run", side_effect=run):
            call_command(
                "backup_shop", "--destination", str(self.destination),
                "--without-media", stdout=self.output,
            )

        argv, env = calls[0]
        self.assertEqual(argv[0], "pg_dump")
        self.assertIn("--format=custom", argv)
        # A password typed on a command line is readable by every other process on
        # the machine, so it travels in the environment instead.
        self.assertNotIn("db-secret", " ".join(argv))
        self.assertEqual(env["PGPASSWORD"], "db-secret")
        self.assertTrue(list(self.destination.glob("shop-*.dump")))
        self.assertIn("opens cleanly", self.output.getvalue())
        manifest = next(self.destination.glob("shop-*.manifest.txt"))
        self.assertIn("engine: postgresql", manifest.read_text(encoding="utf-8"))
        self.assertNotIn("db-secret", manifest.read_text(encoding="utf-8"))
