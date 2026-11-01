from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Branch, StaffProfile
from products.models import Product

from .models import StockAlert
from .whatsapp import send_restock_whatsapp


class RestockAlertTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(username="counter", password="alert-pass-1")
		self.client.force_authenticate(user)
		self.product = Product.objects.create(
			name="Spotlight",
			sku="ALERT-001",
			cost_price="100.00",
			selling_price="150.00",
			stock_quantity=3,
			reorder_threshold=5,
		)

	def _checkout(self, quantity):
		return self.client.post(
			reverse("sale-checkout"),
			{
				"items": [
					{
						"product": str(self.product.id),
						"quantity": quantity,
						"price_sold_at": "150.00",
					}
				],
				"payments": [{"amount": str(150 * quantity), "method": "cash"}],
			},
			format="json",
		)

	def test_sale_that_empties_stock_creates_one_alert(self):
		self.assertEqual(self._checkout(3).status_code, 201)
		self.assertEqual(StockAlert.objects.filter(product=self.product).count(), 1)
		alert = StockAlert.objects.get(product=self.product)
		self.assertEqual(alert.stock_at_trigger, 0)
		self.assertFalse(alert.whatsapp_sent)

	def test_alert_is_not_duplicated_on_the_same_day(self):
		self.assertEqual(self._checkout(2).status_code, 201)
		self.assertEqual(self._checkout(1).status_code, 201)
		self.assertEqual(StockAlert.objects.filter(product=self.product).count(), 1)

	def test_healthy_sale_creates_no_alert(self):
		self.product.stock_quantity = 50
		self.product.save(update_fields=["stock_quantity"])
		self.assertEqual(self._checkout(2).status_code, 201)
		self.assertEqual(StockAlert.objects.count(), 0)

	def test_alerts_endpoint_requires_authentication(self):
		unauthenticated = APIClient()
		self.assertEqual(unauthenticated.get(reverse("alert-list")).status_code, 401)

	@patch("alerts.whatsapp.config")
	def test_send_restock_whatsapp_is_skipped_when_twilio_is_not_configured(self, fake_config):
		fake_config.side_effect = lambda *args, **kwargs: ""
		self.assertFalse(send_restock_whatsapp(self.product))

	def test_branch_staff_only_see_alerts_for_their_own_shop(self):
		branch = Branch.objects.create(name="Ring road", code="ALERT-RING")
		other = Product.objects.create(
			name="Dash camera",
			sku="ALERT-002",
			branch=branch,
			cost_price="100.00",
			selling_price="150.00",
			stock_quantity=1,
			reorder_threshold=5,
		)
		StockAlert.objects.create(product=self.product, stock_at_trigger=0)
		StockAlert.objects.create(product=other, stock_at_trigger=1)

		manager = get_user_model().objects.create_user(
			username="ring-manager", password="alert-pass-2", is_staff=True
		)
		StaffProfile.objects.create(user=manager, branch=branch)
		self.client.force_authenticate(manager)

		response = self.client.get(reverse("alert-list"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual([row["product_name"] for row in response.data["results"]], ["Dash camera"])

	def test_a_cashier_without_a_branch_sees_the_main_shop_only(self):
		# Nobody gave this cashier a shop, which is not the same as giving them all
		# of them: only a manager with no branch is meant to read the whole chain.
		# The fallback is the MAIN branch every shop already has, so a product left
		# without a branch counts as the main shop's.
		ring = Branch.objects.create(name="Ring road", code="ALERT-RING2")
		other = Product.objects.create(
			name="Dash camera",
			sku="ALERT-003",
			branch=ring,
			cost_price="100.00",
			selling_price="150.00",
			stock_quantity=1,
			reorder_threshold=5,
		)
		StockAlert.objects.create(product=self.product, stock_at_trigger=0)
		StockAlert.objects.create(product=other, stock_at_trigger=1)

		response = self.client.get(reverse("alert-list"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual([row["product_name"] for row in response.data["results"]], ["Spotlight"])


class DeliverAlertsCommandTests(TestCase):
	def setUp(self):
		self.product = Product.objects.create(
			name="Light strip",
			sku="ALERT-003",
			cost_price="100.00",
			selling_price="150.00",
			stock_quantity=2,
			reorder_threshold=5,
		)

	def _deliver(self, **options):
		with patch("alerts.management.commands.deliver_alerts.send_restock_whatsapp") as send:
			call_command("deliver_alerts", **options)
		return send

	def test_checkout_does_not_message_twilio_itself(self):
		client = APIClient()
		user = get_user_model().objects.create_user(username="till", password="alert-pass-3")
		client.force_authenticate(user)
		with patch("alerts.whatsapp.Client") as twilio:
			response = client.post(
				reverse("sale-checkout"),
				{
					"items": [
						{
							"product": str(self.product.id),
							"quantity": 2,
							"price_sold_at": "150.00",
						}
					],
					"payments": [{"amount": "300.00", "method": "cash"}],
				},
				format="json",
			)
		self.assertEqual(response.status_code, 201)
		twilio.assert_not_called()
		self.assertEqual(StockAlert.objects.filter(whatsapp_sent=False).count(), 1)

	def test_deliver_sends_the_queued_alert_and_marks_it(self):
		StockAlert.objects.create(product=self.product, stock_at_trigger=0)
		send = self._deliver()
		send.assert_called_once_with(self.product)
		self.assertTrue(StockAlert.objects.get().whatsapp_sent)

	def test_a_restock_between_sale_and_delivery_sends_nothing(self):
		StockAlert.objects.create(product=self.product, stock_at_trigger=0)
		self.product.stock_quantity = 40
		self.product.save(update_fields=["stock_quantity"])
		send = self._deliver()
		send.assert_not_called()
		self.assertTrue(StockAlert.objects.get().whatsapp_sent)

	def test_one_shortage_is_one_message(self):
		StockAlert.objects.create(product=self.product, stock_at_trigger=2)
		StockAlert.objects.create(product=self.product, stock_at_trigger=1)
		send = self._deliver()
		self.assertEqual(send.call_count, 1)
		self.assertEqual(StockAlert.objects.filter(whatsapp_sent=False).count(), 0)

	def test_a_failed_send_stays_queued_for_the_next_run(self):
		StockAlert.objects.create(product=self.product, stock_at_trigger=0)
		with patch(
			"alerts.management.commands.deliver_alerts.send_restock_whatsapp", return_value=False
		):
			call_command("deliver_alerts")
		self.assertFalse(StockAlert.objects.get().whatsapp_sent)

	def test_alerts_older_than_a_day_are_left_alone(self):
		alert = StockAlert.objects.create(product=self.product, stock_at_trigger=0)
		StockAlert.objects.filter(pk=alert.pk).update(
			triggered_at=timezone.now() - timedelta(hours=30)
		)
		send = self._deliver()
		send.assert_not_called()
		self.assertFalse(StockAlert.objects.get().whatsapp_sent)
