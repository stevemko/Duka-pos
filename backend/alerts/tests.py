from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
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
