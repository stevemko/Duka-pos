"""Tests for the checks that decide whether this machine may open for trade."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.checks import ERROR, WARNING
from django.test import SimpleTestCase, override_settings

from .checks import check_opening_settings, check_trade_blockers, host_is_public


class PublicAddressTests(SimpleTestCase):
    def test_public_names_and_addresses_are_recognised(self):
        for host in (
            "pos.greenlightledaccessories.co.ke",
            "159.89.201.44",
            "2a02:2470:1b0:1::42",
            "replace-evaluate-sake-authentication.trycloudflare.com",
        ):
            self.assertTrue(host_is_public(host), host)

    def test_addresses_that_only_exist_in_the_shop_are_rejected(self):
        for host in (
            "localhost",
            "127.0.0.1",
            "::1",
            "192.168.1.20",
            "10.40.3.138",
            "172.16.5.9",
            "169.254.1.1",
            "duka-office",
            "duka-pc.local",
            "",
        ):
            self.assertFalse(host_is_public(host), host)


class TradeBlockerTests(SimpleTestCase):
    """`manage.py check` has to catch the settings that lose a payment."""

    def setUp(self):
        # Media is checked on the way in; keep it out of these assertions so a
        # failure here always means something about M-Pesa.
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.media_root = Path(holder.name)

    def check(self, values):
        with \
            patch(
                "config.checks.config",
                side_effect=lambda name, default="": values.get(name, default),
            ), \
            override_settings(MEDIA_ROOT=str(self.media_root)):
            return check_trade_blockers(None)

    def test_a_shop_without_mpesa_is_not_reported(self):
        self.assertEqual(self.check({}), [])

    def test_a_callback_url_inside_the_shop_network_is_an_error(self):
        problems = self.check({
            "MPESA_CONSUMER_KEY": "key",
            "MPESA_CONSUMER_SECRET": "secret",
            "MPESA_SHORTCODE": "174344",
            "MPESA_PASSKEY": "passkey",
            "MPESA_CALLBACK_URL": "https://192.168.1.20:8000/api/mpesa/callback/",
            "MPESA_CALLBACK_TOKEN": "a-long-random-callback-token",
            "MPESA_ENVIRONMENT": "production",
        })

        self.assertIn("config.E013", [problem.id for problem in problems])
        self.assertEqual(
            [problem.level for problem in problems if problem.id == "config.E013"], [ERROR]
        )

    def test_a_missing_callback_url_is_an_error(self):
        problems = self.check({"MPESA_CONSUMER_KEY": "key", "MPESA_CALLBACK_TOKEN": "t" * 32})

        self.assertIn("config.E012", [problem.id for problem in problems])

    def test_a_placeholder_callback_token_is_an_error(self):
        problems = self.check({
            "MPESA_CONSUMER_KEY": "key",
            "MPESA_CALLBACK_URL": "https://pos.example.co.ke/api/mpesa/callback/",
            "MPESA_CALLBACK_TOKEN": "generate-a-long-random-value",
        })

        self.assertIn("config.E014", [problem.id for problem in problems])

    def test_a_callback_url_that_is_ready_for_trade_is_not_reported(self):
        problems = self.check({
            "MPESA_CONSUMER_KEY": "key",
            "MPESA_CONSUMER_SECRET": "secret",
            "MPESA_SHORTCODE": "174344",
            "MPESA_PASSKEY": "passkey",
            "MPESA_CALLBACK_URL": "https://pos.example.co.ke/api/mpesa/callback/",
            "MPESA_CALLBACK_TOKEN": "a-long-random-callback-token",
            "MPESA_ENVIRONMENT": "production",
        })

        self.assertEqual(problems, [])

    def test_a_laptop_with_a_tunnel_address_still_starts(self):
        """The same sentence, a warning while the shop is still being built.

        A development machine reaches the callback through a tunnel whose address
        changes daily; refusing to boot over that would only teach the owner to run
        the server with --skip-checks.
        """
        with override_settings(DEBUG=True):
            problems = self.check({
                "MPESA_CONSUMER_KEY": "key",
                "MPESA_CALLBACK_URL": "http://192.168.1.5:8000/api/mpesa/callback/",
                "MPESA_CALLBACK_TOKEN": "generate-a-long-random-value",
            })

        levels = {problem.id: problem.level for problem in problems}
        self.assertEqual(levels.get("config.W018"), WARNING)
        self.assertEqual(levels.get("config.W019"), WARNING)
        self.assertNotIn("config.E013", levels)

    def test_a_media_folder_that_cannot_be_written_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            blocking_file = Path(folder) / "a-file"
            blocking_file.write_text("not a folder", encoding="utf-8")
            with override_settings(MEDIA_ROOT=str(blocking_file / "media")):
                problems = check_trade_blockers(None)

        self.assertIn("config.E010", [problem.id for problem in problems])


class OpeningSettingsTests(SimpleTestCase):
    """The --deploy check reads like a shop checklist, not a framework complaint."""

    def test_debug_on_a_laptop_is_reported_as_a_warning(self):
        with override_settings(DEBUG=True, ALLOWED_HOSTS=["localhost", "127.0.0.1"]):
            problems = check_opening_settings(None)

        ids = {problem.id: problem.level for problem in problems}
        self.assertEqual(ids.get("config.W010"), WARNING)
        self.assertIn("config.W012", ids)

    def test_a_public_host_and_origin_clear_the_hosting_warnings(self):
        with \
            override_settings(
                DEBUG=False,
                SECRET_KEY="x" * 60,
                ALLOWED_HOSTS=["pos.example.co.ke"],
                # An empty list is the right answer for an app served from the same
                # address, and must not read as "the development machine".
                CORS_ALLOWED_ORIGINS=[""],
                CSRF_TRUSTED_ORIGINS=["https://pos.example.co.ke"],
            ), \
            patch("config.checks.config", side_effect=lambda name, default="": "production"):
            problems = check_opening_settings(None)

        self.assertEqual([problem.id for problem in problems], [])
