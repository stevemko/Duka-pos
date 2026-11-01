from decimal import Decimal
from datetime import timedelta
from io import BytesIO, StringIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from products.models import Product
from .models import (
    Customer,
    Payment,
    Sale,
    SaleReceipt,
    SaleReturn,
    SaleReturnItem,
    normalize_customer_phone,
)
from .mpesa import MpesaError, MpesaUnconfirmed, initiate_stk_push


class SaleStockTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(username="cashier", password="test-password")
		self.client.force_authenticate(user=user)
		self.product = Product.objects.create(
			name="Rice",
			sku="RICE-001",
			cost_price="100.00",
			selling_price="125.00",
			stock_quantity=10,
		)

	def test_sale_deducts_stock(self):
		response = self.client.post(
			reverse("sale-list"),
			{
				"product": str(self.product.id),
				"quantity": 3,
				"price_sold_at": "125.00",
			},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		self.product.refresh_from_db()
		self.assertEqual(self.product.stock_quantity, 7)
		self.assertEqual(Sale.objects.count(), 1)

	def test_sale_cannot_exceed_available_stock(self):
		response = self.client.post(
			reverse("sale-list"),
			{
				"product": str(self.product.id),
				"quantity": 11,
				"price_sold_at": "125.00",
			},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.product.refresh_from_db()
		self.assertEqual(self.product.stock_quantity, 10)
		self.assertEqual(Sale.objects.count(), 0)

	def test_sale_below_cost_is_rejected(self):
		response = self.client.post(
			reverse("sale-list"),
			{
				"product": str(self.product.id),
				"quantity": 1,
				"price_sold_at": "99.99",
			},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(Sale.objects.count(), 0)

	def test_sale_profit_uses_cost_snapshot(self):
		response = self.client.post(
			reverse("sale-list"),
			{
				"product": str(self.product.id),
				"quantity": 2,
				"price_sold_at": "125.00",
			},
			format="json",
		)
		sale = Sale.objects.get(pk=response.data["id"])
		self.product.cost_price = Decimal("110.00")
		self.product.save(update_fields=["cost_price"])
		sale.refresh_from_db()

		self.assertEqual(sale.cost_price_at_sale, Decimal("100.00"))
		self.assertEqual(sale.profit, Decimal("50.00"))

	def test_recorded_sale_cannot_be_changed_or_deleted_in_application_code(self):
		sale = Sale.objects.create(
			product=self.product,
			quantity=1,
			price_sold_at=Decimal("125.00"),
		)
		sale.quantity = 2

		with self.assertRaises(ValidationError):
			sale.save()
		with self.assertRaises(ValidationError):
			sale.delete()

	def test_recorded_sale_cannot_be_edited_or_deleted(self):
		create_response = self.client.post(
			reverse("sale-list"),
			{
				"product": str(self.product.id),
				"quantity": 3,
				"price_sold_at": "125.00",
			},
			format="json",
		)
		sale_url = reverse("sale-detail", kwargs={"pk": create_response.data["id"]})

		update_response = self.client.patch(sale_url, {"quantity": 1}, format="json")
		delete_response = self.client.delete(sale_url)

		self.assertEqual(update_response.status_code, 405)
		self.assertEqual(delete_response.status_code, 405)
		self.product.refresh_from_db()
		self.assertEqual(self.product.stock_quantity, 7)
		self.assertEqual(Sale.objects.count(), 1)

	def test_daily_summary_includes_sales_beyond_first_page(self):
		self.product.refresh_from_db()
		for _ in range(60):
			Sale.objects.create(
				product=self.product,
				quantity=1,
				price_sold_at=Decimal("125.00"),
			)

		response = self.client.get(reverse("sale-summary"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["total_sales"], Decimal("7500.00"))
		self.assertEqual(response.data["gross_profit"], Decimal("1500.00"))
		self.assertEqual(response.data["items_sold"], 60)


class CartCheckoutTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(username="cashier", password="test-password")
		self.client.force_authenticate(user=user)
		self.rice = Product.objects.create(
			name="Rice",
			sku="CHECKOUT-RICE",
			cost_price="100.00",
			selling_price="125.00",
			stock_quantity=10,
		)
		self.sugar = Product.objects.create(
			name="Sugar",
			sku="CHECKOUT-SUGAR",
			cost_price="80.00",
			selling_price="100.00",
			stock_quantity=5,
		)
		self.checkout_url = reverse("sale-checkout")

	def test_multi_item_paid_checkout_creates_receipt_and_deducts_stock(self):
		response = self.client.post(
			self.checkout_url,
			{
				"items": [
						{"product": str(self.rice.id), "quantity": 2, "price_sold_at": "125.00"},
						{"product": str(self.sugar.id), "quantity": 1, "price_sold_at": "100.00"},
				],
				"payments": [{"amount": "350.00", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.data["total"], "350.00")
		self.assertEqual(response.data["amount_paid"], "350.00")
		self.assertEqual(response.data["balance"], "0.00")
		self.assertEqual(response.data["payment_status"], "paid")
		self.assertEqual(len(response.data["items"]), 2)
		self.assertEqual(SaleReceipt.objects.count(), 1)
		self.assertEqual(Payment.objects.count(), 1)
		self.rice.refresh_from_db()
		self.sugar.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 8)
		self.assertEqual(self.sugar.stock_quantity, 4)

	def test_partial_payment_requires_customer_and_tracks_balance(self):
		payload = {
			"customer_name": "Amina",
			"items": [{"product": str(self.rice.id), "quantity": 2, "price_sold_at": "125.00"}],
			"payments": [{"amount": "100.00", "method": "mobile_money", "reference": "TX-1"}],
		}

		response = self.client.post(self.checkout_url, payload, format="json")

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.data["payment_status"], "partially_paid")
		self.assertEqual(response.data["balance"], "150.00")
		self.assertEqual(response.data["payments"][0]["reference"], "TX-1")

	def test_unpaid_checkout_is_marked_on_credit(self):
		response = self.client.post(
			self.checkout_url,
			{
				"customer_phone": "+254700000000",
				"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.data["payment_status"], "on_credit")
		self.assertEqual(response.data["amount_paid"], "0.00")

	def test_insufficient_stock_rejects_entire_cart(self):
		response = self.client.post(
			self.checkout_url,
			{
				"items": [
					{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"},
					{"product": str(self.sugar.id), "quantity": 6, "price_sold_at": "100.00"},
				],
				"payments": [{"amount": "225.00", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(SaleReceipt.objects.count(), 0)
		self.assertEqual(Sale.objects.count(), 0)
		self.rice.refresh_from_db()
		self.sugar.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 10)
		self.assertEqual(self.sugar.stock_quantity, 5)

	def test_unpaid_and_overpaid_checkout_payloads_are_rejected(self):
		missing_customer = self.client.post(
			self.checkout_url,
			{"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}]},
			format="json",
		)
		overpayment = self.client.post(
			self.checkout_url,
			{
				"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
				"payments": [{"amount": "126.00", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(missing_customer.status_code, 400)
		self.assertEqual(overpayment.status_code, 400)
		self.assertEqual(SaleReceipt.objects.count(), 0)

	def test_checkout_rejects_sale_price_below_cost(self):
		response = self.client.post(
			self.checkout_url,
			{
				"items": [{
					"product": str(self.rice.id),
					"quantity": 1,
					"price_sold_at": "99.99",
				}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(SaleReceipt.objects.count(), 0)
		self.assertEqual(Sale.objects.count(), 0)

	def test_checkout_requires_actual_charged_price(self):
		response = self.client.post(
			self.checkout_url,
			{"items": [{"product": str(self.rice.id), "quantity": 1}]},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(SaleReceipt.objects.count(), 0)

	def test_monthly_analytics_separates_sales_from_collections(self):
		checkout = self.client.post(
			self.checkout_url,
			{
				"customer_name": "Amina",
				"customer_phone": "0700000000",
				"items": [{"product": str(self.rice.id), "quantity": 2, "price_sold_at": "125.00"}],
				"payments": [{"amount": "100.00", "method": "cash"}],
			},
			format="json",
		)
		month = timezone.localdate().strftime("%Y-%m")

		response = self.client.get(reverse("sale-analytics"), {"month": month})
		credit_response = self.client.get(reverse("receipt-credits"))
		manager = get_user_model().objects.create_user(
			username="finance-manager", password="test-password", is_staff=True
		)
		manager_client = APIClient()
		manager_client.force_authenticate(manager)
		manager_response = manager_client.get(reverse("sale-analytics"), {"month": month})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["total_sales"], Decimal("250.00"))
		self.assertIsNone(response.data["gross_profit"])
		self.assertEqual(manager_response.data["gross_profit"], Decimal("50.00"))
		self.assertEqual(response.data["items_sold"], 2)
		self.assertEqual(response.data["daily_totals"][0]["amount_collected"], Decimal("100.00"))
		self.assertEqual(response.data["top_product"]["product_name"], "Rice")
		self.assertEqual(credit_response.data["outstanding_total"], Decimal("150.00"))
		self.assertEqual(credit_response.data["credits"][0]["customer_name"], "Amina")
		self.assertEqual(credit_response.data["credits"][0]["customer_phone"], "0700000000")

	def test_analytics_breaks_sales_by_category_and_payment_method(self):
		self.rice.category = "Grains"
		self.rice.save(update_fields=["category"])
		self.sugar.category = "Pantry"
		self.sugar.save(update_fields=["category"])
		self.client.post(
			self.checkout_url,
			{
				"items": [
					{"product": str(self.rice.id), "quantity": 2, "price_sold_at": "125.00"},
					{"product": str(self.sugar.id), "quantity": 1, "price_sold_at": "100.00"},
				],
				"payments": [
					{"amount": "200.00", "method": "cash"},
					{"amount": "150.00", "method": "bank_transfer"},
				],
			},
			format="json",
		)

		response = self.client.get(
			reverse("sale-analytics"), {"month": timezone.localdate().strftime("%Y-%m")}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["total_sales"], Decimal("350.00"))
		self.assertIsNone(response.data["gross_profit"])
		categories = {row["category"]: row for row in response.data["sales_by_category"]}
		self.assertEqual(categories["Grains"]["sales_total"], Decimal("250.00"))
		self.assertEqual(categories["Pantry"]["sales_total"], Decimal("100.00"))
		self.assertEqual(categories["Grains"]["share"], Decimal("71.4"))
		methods = {row["method"]: row for row in response.data["payment_mix"]}
		self.assertEqual(methods["cash"]["amount"], Decimal("200.00"))
		self.assertEqual(methods["bank_transfer"]["amount"], Decimal("150.00"))
		self.assertEqual(methods["cash"]["share"], Decimal("57.1"))
		self.assertEqual(len(response.data["product_performance"]), 2)
		self.assertEqual(response.data["stagnant_count"], 0)

	def test_sales_can_be_filtered_by_date_and_product(self):
		Sale.objects.create(product=self.rice, quantity=1, price_sold_at=Decimal("125.00"))
		Sale.objects.create(product=self.sugar, quantity=1, price_sold_at=Decimal("100.00"))
		date_value = timezone.localdate().isoformat()

		response = self.client.get(reverse("sale-list"), {
			"start_date": date_value,
			"end_date": date_value,
			"product": str(self.rice.id),
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["count"], 1)
		self.assertEqual(response.data["results"][0]["product_name"], "Rice")

	def test_checkout_cannot_claim_an_stk_payment_as_already_paid(self):
		response = self.client.post(
			self.checkout_url,
			{
				"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
				"payments": [{"amount": "125.00", "method": "mpesa_stk"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(SaleReceipt.objects.count(), 0)

	def test_paybill_payment_requires_confirmation_code(self):
		payload = {
			"items": [{"product": str(self.rice.id), "quantity": 2, "price_sold_at": "125.00"}],
			"payments": [{"amount": "250.00", "method": "mpesa_paybill"}],
		}

		missing_reference = self.client.post(self.checkout_url, payload, format="json")

		self.assertEqual(missing_reference.status_code, 400)
		self.assertIn("reference", missing_reference.data["payments"][0])
		self.assertEqual(SaleReceipt.objects.count(), 0)

		payload["payments"][0]["reference"] = "SLK7XYZ12A"
		recorded = self.client.post(self.checkout_url, payload, format="json")

		self.assertEqual(recorded.status_code, 201)
		self.assertEqual(recorded.data["payment_status"], "paid")
		self.assertEqual(recorded.data["payments"][0]["method"], "mpesa_paybill")
		self.assertEqual(recorded.data["payments"][0]["reference"], "SLK7XYZ12A")

	def test_receipt_payment_settles_balance_and_updates_status(self):
		checkout = self.client.post(
			self.checkout_url,
			{
				"customer_name": "Amina",
				"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
			},
			format="json",
		)
		payment_response = self.client.post(
			reverse("receipt-payments", kwargs={"pk": checkout.data["id"]}),
			{"amount": "125.00", "method": "mobile_money"},
			format="json",
		)

		self.assertEqual(payment_response.status_code, 201)
		self.assertEqual(payment_response.data["payment_status"], "paid")
		self.assertEqual(payment_response.data["balance"], "0.00")

	def test_receipt_payment_cannot_exceed_balance(self):
		checkout = self.client.post(
			self.checkout_url,
			{
				"customer_name": "Amina",
				"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
			},
			format="json",
		)
		payment_response = self.client.post(
			reverse("receipt-payments", kwargs={"pk": checkout.data["id"]}),
			{"amount": "126.00", "method": "cash"},
			format="json",
		)

		self.assertEqual(payment_response.status_code, 400)
		self.assertEqual(Payment.objects.count(), 0)

	def create_credit_receipt(self):
		return self.client.post(
			self.checkout_url,
			{
				"customer_name": "Amina",
				"customer_phone": "0794671494",
				"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
			},
			format="json",
		)

	@patch("sales.views.initiate_stk_push")
	def test_stk_push_creates_pending_payment_without_counting_it_paid(self, initiate):
		initiate.return_value = {
			"ResponseCode": "0",
			"MerchantRequestID": "merchant-1",
			"CheckoutRequestID": "checkout-1",
			"CustomerMessage": "Prompt sent",
		}
		receipt = self.create_credit_receipt()
		response = self.client.post(
			reverse("receipt-stk-push", kwargs={"pk": receipt.data["id"]}),
			{"phone": "0794671494"},
			format="json",
		)

		self.assertEqual(response.status_code, 202)
		self.assertEqual(response.data["receipt"]["payment_status"], "payment_pending")
		self.assertEqual(response.data["receipt"]["amount_paid"], "0.00")
		self.assertEqual(response.data["receipt"]["payments"][0]["status"], "pending")
		self.assertEqual(Payment.objects.get().checkout_request_id, "checkout-1")

	@patch("sales.views.initiate_stk_push")
	def test_cash_over_an_open_prompt_settles_the_receipt(self, initiate):
		initiate.return_value = {
			"ResponseCode": "0",
			"MerchantRequestID": "merchant-1",
			"CheckoutRequestID": "checkout-1",
			"CustomerMessage": "Prompt sent",
		}
		receipt_id = self.create_credit_receipt().data["id"]
		self.client.post(reverse("receipt-stk-push", kwargs={"pk": receipt_id}), {"phone": "0794671494"}, format="json")

		payment_response = self.client.post(
			reverse("receipt-payments", kwargs={"pk": receipt_id}),
			{"amount": "125.00", "method": "cash"},
			format="json",
		)
		check_response = self.client.post(
			reverse("receipt-check-payment", kwargs={"pk": receipt_id}), {}, format="json"
		)

		self.assertEqual(payment_response.data["payment_status"], "paid")
		self.assertEqual(check_response.data["state"], "paid")
		listed = self.client.get(reverse("receipt-list"), {"status": "paid"}, format="json")
		self.assertEqual(
			[entry["id"] for entry in listed.data["results"]], [str(receipt_id)]
		)

	@patch("sales.views.config", return_value="test-callback-token")
	@patch("sales.views.initiate_stk_push")
	def test_successful_mpesa_callback_marks_payment_paid(self, initiate, _callback_config):
		initiate.return_value = {
			"ResponseCode": "0",
			"CheckoutRequestID": "checkout-success",
			"MerchantRequestID": "merchant-success",
		}
		receipt = self.create_credit_receipt()
		self.client.post(
			reverse("receipt-stk-push", kwargs={"pk": receipt.data["id"]}),
			{"phone": "0794671494"},
			format="json",
		)

		callback = self.client.post(
			reverse("mpesa-callback") + "?token=test-callback-token",
			{
				"Body": {
					"stkCallback": {
						"CheckoutRequestID": "checkout-success",
						"ResultCode": 0,
						"ResultDesc": "Success",
						"CallbackMetadata": {"Item": [
							{"Name": "Amount", "Value": 125},
							{"Name": "MpesaReceiptNumber", "Value": "QAB123XYZ"},
						]},
					}
				}
			},
			format="json",
		)

		self.assertEqual(callback.status_code, 200)
		payment = Payment.objects.get(checkout_request_id="checkout-success")
		self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
		self.assertEqual(payment.reference, "QAB123XYZ")
		self.assertEqual(payment.receipt.payment_status, "paid")

	@patch("sales.views.config", return_value="test-callback-token")
	@patch("sales.views.initiate_stk_push")
	def test_callback_rejects_amount_mismatch_and_invalid_token(self, initiate, _callback_config):
		initiate.return_value = {"ResponseCode": "0", "CheckoutRequestID": "checkout-mismatch"}
		receipt = self.create_credit_receipt()
		self.client.post(
			reverse("receipt-stk-push", kwargs={"pk": receipt.data["id"]}),
			{"phone": "0794671494"},
			format="json",
		)
		callback_url = reverse("mpesa-callback")
		callback_body = {
			"Body": {
				"stkCallback": {
					"CheckoutRequestID": "checkout-mismatch",
					"ResultCode": 0,
					"CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 124}]},
				}
			}
		}

		unauthorized = self.client.post(callback_url, callback_body, format="json")
		accepted = self.client.post(callback_url + "?token=test-callback-token", callback_body, format="json")

		self.assertEqual(unauthorized.status_code, 403)
		self.assertEqual(accepted.status_code, 200)
		payment = Payment.objects.get(checkout_request_id="checkout-mismatch")
		self.assertEqual(payment.status, Payment.Status.FAILED)
		self.assertEqual(payment.receipt.amount_paid, Decimal("0.00"))

	def test_more_than_100_checkouts_are_recorded_and_receipts_are_paginated(self):
		self.rice.stock_quantity = 110
		self.rice.save(update_fields=["stock_quantity"])

		for _ in range(105):
			response = self.client.post(
				self.checkout_url,
				{
					"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
					"payments": [{"amount": "125.00", "method": "cash"}],
				},
				format="json",
			)
			self.assertEqual(response.status_code, 201)

		receipt_page = self.client.get(reverse("receipt-list"))
		self.assertEqual(SaleReceipt.objects.count(), 105)
		self.assertEqual(Sale.objects.count(), 105)
		self.assertEqual(receipt_page.data["count"], 105)
		self.assertEqual(len(receipt_page.data["results"]), 50)
		self.assertIsNotNone(receipt_page.data["next"])


class IdempotentCheckoutTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(username="cashier", password="test-password")
		self.client.force_authenticate(user=user)
		self.rice = Product.objects.create(
			name="Rice", cost_price="100.00", selling_price="125.00", stock_quantity=10,
		)
		self.checkout_url = reverse("sale-checkout")
		self.payload = {
			"items": [{"product": str(self.rice.id), "quantity": 2, "price_sold_at": "125.00"}],
			"payments": [{"amount": "250.00", "method": "cash"}],
		}

	def test_repeated_checkout_with_same_key_returns_the_same_receipt(self):
		first = self.client.post(
			self.checkout_url, self.payload, format="json",
			HTTP_IDEMPOTENCY_KEY="cart-123",
		)
		second = self.client.post(
			self.checkout_url, self.payload, format="json",
			HTTP_IDEMPOTENCY_KEY="cart-123",
		)

		self.assertEqual(first.status_code, 201)
		self.assertEqual(second.status_code, 200)
		self.assertEqual(first.data["id"], second.data["id"])
		self.assertEqual(SaleReceipt.objects.count(), 1)
		self.rice.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 8)

	def test_different_keys_create_separate_receipts(self):
		self.client.post(self.checkout_url, self.payload, format="json", HTTP_IDEMPOTENCY_KEY="cart-a")
		second = self.client.post(
			self.checkout_url, self.payload, format="json", HTTP_IDEMPOTENCY_KEY="cart-b"
		)

		self.assertEqual(second.status_code, 201)
		self.assertEqual(SaleReceipt.objects.count(), 2)

	def test_same_key_with_a_different_basket_is_rejected(self):
		# A retained key is a retry only while the basket behind it is the same. If
		# the cashier rings up a different customer or tender under the old
		# reference, replaying the first receipt would hand this customer someone
		# else's goods - so the server says no instead.
		self.client.post(
			self.checkout_url, self.payload, format="json", HTTP_IDEMPOTENCY_KEY="cart-123"
		)

		changed = dict(self.payload, customer_name="Wanjiru")
		response = self.client.post(
			self.checkout_url, changed, format="json", HTTP_IDEMPOTENCY_KEY="cart-123"
		)

		self.assertEqual(response.status_code, 409)
		self.assertIn("different basket", response.data["detail"])
		self.assertEqual(SaleReceipt.objects.count(), 1)
		self.rice.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 8)

	def test_same_key_after_a_change_of_tender_is_rejected(self):
		self.client.post(
			self.checkout_url, self.payload, format="json", HTTP_IDEMPOTENCY_KEY="cart-555"
		)

		# Same key, same goods - but the customer paid by card, not cash. That is a
		# different sale, and the books cannot show 250 in cash for it.
		response = self.client.post(
			self.checkout_url,
			{
				"items": self.payload["items"],
				"payments": [{"amount": "250.00", "method": "card"}],
			},
			format="json",
			HTTP_IDEMPOTENCY_KEY="cart-555",
		)

		self.assertEqual(response.status_code, 409)
		self.assertEqual(SaleReceipt.objects.count(), 1)

	def test_a_receipt_saved_before_the_digest_replays_without_argument(self):
		# Rows already in the books carry no digest, so they have nothing to argue
		# about: a retry gets the receipt back instead of a 409.
		legacy = SaleReceipt.objects.create(idempotency_key="cart-old")

		response = self.client.post(
			self.checkout_url, self.payload, format="json", HTTP_IDEMPOTENCY_KEY="cart-old"
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["id"], str(legacy.id))


class CustomerTestsBase:
	def setUp(self):
		self.client = APIClient()
		self.cashier = get_user_model().objects.create_user(
			username="till", password="credit-pass"
		)
		self.owner = get_user_model().objects.create_user(
			username="owner", password="credit-pass", is_superuser=True, is_staff=True
		)
		self.client.force_authenticate(user=self.cashier)
		self.bulb = Product.objects.create(
			name="Bulb",
			sku="CREDIT-1",
			cost_price="100.00",
			selling_price="200.00",
			stock_quantity=20,
		)
		self.customers_url = reverse("customer-list")
		self.checkout_url = reverse("sale-checkout")

	def _add_customer(self, name="Amina Hassan", phone="0794671494", **extra):
		return self.client.post(
			self.customers_url, {"name": name, "phone": phone, **extra}, format="json"
		)

	def _credit_sale(self, units=1, customer=None, phone="", name="Amina"):
		return self.client.post(
			self.checkout_url,
			{
				"items": [
					{"product": str(self.bulb.id), "quantity": units, "price_sold_at": "200.00"}
				],
				"payments": [],
				"customer_name": name,
				"customer_phone": phone,
				**({"customer": str(customer)} if customer else {}),
			},
			format="json",
		)

class CustomerAccountTests(CustomerTestsBase, TestCase):
	def test_a_credit_sale_sits_on_the_account_not_only_on_the_receipt(self):
		created = self._add_customer()
		self.assertEqual(created.status_code, 201)

		sale = self._credit_sale(customer=created.data["id"])
		self.assertEqual(sale.status_code, 201)
		self.assertEqual(str(sale.data["customer"]), created.data["id"])

		book = self.client.get(reverse("customer-ledger", args=[created.data["id"]]))
		self.assertEqual(book.data["customer"]["outstanding"], "200.00")
		self.assertEqual([entry["type"] for entry in book.data["entries"]], ["sale"])
		self.assertEqual(book.data["entries"][0]["balance"], Decimal("200.00"))

	def test_the_note_handed_in_at_the_till_is_counted_once_in_the_book(self):
		# The part paid at the counter is both a payment on the receipt and a line
		# of its own in the book. Reading it in both places would tell the shop the
		# customer has paid twice over.
		created = self._add_customer()
		sale = self.client.post(
			self.checkout_url,
			{
				"items": [
					{"product": str(self.bulb.id), "quantity": 3, "price_sold_at": "200.00"}
				],
				"payments": [{"method": "cash", "amount": "200.00"}],
				"customer_name": "Amina Hassan",
				"customer": str(created.data["id"]),
			},
			format="json",
		)
		self.assertEqual(sale.status_code, 201)

		book = self.client.get(reverse("customer-ledger", args=[created.data["id"]]))
		self.assertEqual(
			[entry["type"] for entry in book.data["entries"]], ["sale", "payment"]
		)
		self.assertEqual(book.data["entries"][-1]["balance"], Decimal("400.00"))
		self.assertEqual(book.data["customer"]["outstanding"], "400.00")

	def test_one_number_typed_two_ways_is_one_account(self):
		created = self._add_customer(phone="0794671494")
		# A second cashier types the same customer the way their phone shows it.
		sale = self._credit_sale(phone="+254794671494", name="")
		self.assertEqual(sale.status_code, 201)
		self.assertEqual(str(sale.data["customer"]), created.data["id"])
		self.assertEqual(Customer.objects.count(), 1)

	def test_a_number_is_recognised_in_every_shape_the_shop_types_it(self):
		for written in (
			"0794671494",
			"+254794671494",
			"254794671494",
			"0794 671 494",
		):
			self.assertEqual(normalize_customer_phone(written), "254794671494", written)
		self.assertEqual(normalize_customer_phone("020 661 0000"), "")
		self.assertEqual(normalize_customer_phone(""), "")

	def test_an_account_the_shop_ever_sold_to_cannot_be_erased(self):
		# PROTECT on the receipt link: a customer row is evidence of a debt, and a
		# till must not be able to delete its way out of the ledger.
		created = self._add_customer()
		self._credit_sale(customer=created.data["id"])
		with self.assertRaises(ProtectedError):
			Customer.objects.get(pk=created.data["id"]).delete()


class CreditLimitTests(CustomerTestsBase, TestCase):
	def test_an_account_with_no_ceiling_is_never_blocked(self):
		created = self._add_customer()
		for _ in range(4):
			self.assertEqual(
				self._credit_sale(units=5, customer=created.data["id"]).status_code, 201
			)
		self.assertEqual(
			Customer.objects.get(pk=created.data["id"]).outstanding, Decimal("4000.00")
		)

	def test_a_paid_bill_is_not_left_on_the_ledger(self):
		# Money already in means the account is settled, however late it arrived: a
		# receipt still open would keep the customer's debt alive forever.
		created = self._add_customer()
		sale = self._credit_sale(customer=created.data["id"])
		self.client.post(
			reverse("receipt-payments", args=[sale.data["id"]]),
			{"amount": "200.00", "method": "cash"},
			format="json",
		)

		self.assertEqual(
			Customer.objects.get(pk=created.data["id"]).outstanding, Decimal("0.00")
		)
		response = self.client.get(reverse("customer-debtors"))
		self.assertEqual(response.data["customer_count"], 0)

	def test_a_ceiling_blocks_only_the_sale_that_crosses_it(self):
		created = self._add_customer()
		self.client.force_authenticate(user=self.owner)
		self.assertEqual(
			self.client.patch(
				reverse("customer-detail", args=[created.data["id"]]),
				{"credit_limit": "300.00"},
				format="json",
			).status_code,
			200,
		)
		self.client.force_authenticate(user=self.cashier)

		self.assertEqual(self._credit_sale(customer=created.data["id"]).status_code, 201)
		blocked = self._credit_sale(customer=created.data["id"])
		self.assertEqual(blocked.status_code, 400)
		self.assertIn("credit", str(blocked.data["customer"][0]))

		# Take part of it back and the same sale is allowed again.
		paid = self.client.post(
			reverse("customer-payments", args=[created.data["id"]]),
			{"amount": "150.00", "method": "cash"},
			format="json",
		)
		self.assertEqual(paid.status_code, 201)
		self.assertEqual(paid.data["still_owing"], Decimal("50.00"))
		self.assertEqual(self._credit_sale(customer=created.data["id"]).status_code, 201)


class CustomerPaymentTests(CustomerTestsBase, TestCase):
	def test_a_payment_clears_the_oldest_bill_first(self):
		created = self._add_customer()
		first = self._credit_sale(customer=created.data["id"])
		second = self._credit_sale(customer=created.data["id"])
		self.client.post(
			reverse("customer-payments", args=[created.data["id"]]),
			{"amount": "300.00", "method": "cash"},
			format="json",
		)

		self.assertEqual(
			SaleReceipt.objects.get(pk=first.data["id"]).payment_status, "paid"
		)
		self.assertEqual(
			SaleReceipt.objects.get(pk=second.data["id"]).payment_status, "partially_paid"
		)
		self.assertEqual(
			Customer.objects.get(pk=created.data["id"]).outstanding, Decimal("100.00")
		)

	def test_paying_more_than_the_account_owes_is_refused(self):
		created = self._add_customer()
		self._credit_sale(customer=created.data["id"])

		response = self.client.post(
			reverse("customer-payments", args=[created.data["id"]]),
			{"amount": "500.00", "method": "cash"},
			format="json",
		)
		self.assertEqual(response.status_code, 400)
		self.assertIn("owes 200.00", str(response.data["amount"][0]))
		self.assertEqual(Payment.objects.filter(receipt__customer=created.data["id"]).count(), 0)

class CustomerBookTests(CustomerTestsBase, TestCase):
	def test_a_name_without_a_number_is_still_a_book(self):
		# Plenty of regulars are only known by name. The number is how a sale finds
		# its account on its own, but a name is a book the shop may keep.
		created = self._add_customer(name="Mama Ntilie", phone="")
		self.assertEqual(created.status_code, 201)

		sale = self._credit_sale(customer=created.data["id"], name="Mama Ntilie")
		self.assertEqual(sale.status_code, 201)
		self.assertEqual(
			Customer.objects.get(pk=created.data["id"]).outstanding, Decimal("200.00")
		)

	def test_a_sale_with_no_account_picked_opens_no_book(self):
		# A walk-up on a till with nothing typed but a name is not a debtor: making
		# one would fill the book with half-remembered names.
		response = self._credit_sale(name="Walk-in")
		self.assertEqual(response.status_code, 201)
		self.assertIsNone(response.data["customer"])
		self.assertEqual(Customer.objects.count(), 0)

	def test_a_second_account_for_one_number_is_refused(self):
		self._add_customer(name="Amina Hassan", phone="0794671494")
		response = self._add_customer(name="Hassan Amina", phone="+254 794 671 494")
		self.assertEqual(response.status_code, 400)
		self.assertIn("Amina Hassan", str(response.data["phone"][0]))

	def test_only_a_manager_moves_a_ceiling(self):
		created = self._add_customer()
		response = self.client.patch(
			reverse("customer-detail", args=[created.data["id"]]),
			{"credit_limit": "500.00"},
			format="json",
		)
		self.assertEqual(response.status_code, 403)

	def test_closing_an_account_keeps_the_money_owed_visible(self):
		created = self._add_customer()
		self._credit_sale(customer=created.data["id"])
		self.client.force_authenticate(user=self.owner)

		response = self.client.delete(reverse("customer-detail", args=[created.data["id"]]))
		self.assertEqual(response.status_code, 200)
		self.assertIn("closed for new credit", str(response.data["detail"]))
		self.assertTrue(Customer.objects.filter(pk=created.data["id"], is_active=False).exists())
		self.assertEqual(SaleReceipt.objects.filter(customer_id=created.data["id"]).count(), 1)

		# Out of the till's picker, still readable in the book.
		self.client.force_authenticate(user=self.cashier)
		listed = self.client.get(self.customers_url)
		self.assertEqual([row["id"] for row in listed.data["results"]], [])
		book = self.client.get(reverse("customer-ledger", args=[created.data["id"]]))
		self.assertEqual(book.data["customer"]["outstanding"], "200.00")

	def test_the_debtors_page_adds_up_across_accounts(self):
		first = self._add_customer(name="Amina", phone="0794671494")
		second = self._add_customer(name="Otieno", phone="0700000001")
		self._credit_sale(units=2, customer=first.data["id"], name="Amina")
		self._credit_sale(units=1, customer=second.data["id"], name="Otieno")

		response = self.client.get(reverse("customer-debtors"))
		self.assertEqual(response.data["outstanding_total"], Decimal("600.00"))
		self.assertEqual(
			[row["name"] for row in response.data["customers"]], ["Amina", "Otieno"]
		)


class MpesaCallbackEdgeTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(username="cashier", password="test-password")
		self.client.force_authenticate(user=user)
		self.rice = Product.objects.create(
			name="Rice", cost_price="100.00", selling_price="125.00", stock_quantity=5,
		)
		checkout = self.client.post(
			reverse("sale-checkout"),
			{
				"customer_name": "Amina",
				"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
			},
			format="json",
		)
		self.receipt = SaleReceipt.objects.get(pk=checkout.data["id"])

	@patch("sales.views.config", return_value="test-callback-token")
	@patch("sales.views.initiate_stk_push")
	def test_callback_with_null_metadata_fails_the_payment_cleanly(self, initiate, _config):
		initiate.return_value = {"ResponseCode": "0", "CheckoutRequestID": "checkout-null"}
		self.client.post(
			reverse("receipt-stk-push", kwargs={"pk": self.receipt.id}),
			{"phone": "0794671494"},
			format="json",
		)

		callback = self.client.post(
			reverse("mpesa-callback") + "?token=test-callback-token",
			{"Body": {"stkCallback": {
				"CheckoutRequestID": "checkout-null",
				"ResultCode": 0,
				"ResultDesc": "Success",
				"CallbackMetadata": None,
			}}},
			format="json",
		)

		self.assertEqual(callback.status_code, 200)
		payment = Payment.objects.get(checkout_request_id="checkout-null")
		self.assertEqual(payment.status, Payment.Status.FAILED)
		self.assertEqual(payment.receipt.amount_paid, Decimal("0.00"))

	@patch("sales.views.config", return_value="test-callback-token")
	@patch("sales.views.initiate_stk_push")
	def test_duplicate_callback_does_not_double_count(self, initiate, _config):
		initiate.return_value = {"ResponseCode": "0", "CheckoutRequestID": "checkout-dup"}
		self.client.post(
			reverse("receipt-stk-push", kwargs={"pk": self.receipt.id}),
			{"phone": "0794671494"},
			format="json",
		)
		body = {"Body": {"stkCallback": {
			"CheckoutRequestID": "checkout-dup",
			"ResultCode": 0,
			"CallbackMetadata": {"Item": [
				{"Name": "Amount", "Value": 125},
				{"Name": "MpesaReceiptNumber", "Value": "QAB1"},
			]},
		}}}
		url = reverse("mpesa-callback") + "?token=test-callback-token"

		self.client.post(url, body, format="json")
		second = self.client.post(url, body, format="json")

		self.assertEqual(second.status_code, 200)
		self.assertEqual(self.receipt.payments.filter(status=Payment.Status.SUCCEEDED).count(), 1)
		self.assertEqual(self.receipt.amount_paid, Decimal("125.00"))

	@patch("sales.views.config", return_value="test-callback-token")
	def test_callback_rejects_malformed_payload(self, _config):
		response = self.client.post(
			reverse("mpesa-callback") + "?token=test-callback-token",
			{"unexpected": True},
			format="json",
		)

		self.assertEqual(response.status_code, 400)


class StaleStkPaymentTests(TestCase):
	def setUp(self):
		self.product = Product.objects.create(
			name="Rice", cost_price="100.00", selling_price="125.00", stock_quantity=5,
		)
		self.receipt = SaleReceipt.objects.create(customer_name="Amina")
		Sale.objects.create(
			receipt=self.receipt,
			product=self.product,
			quantity=1,
			price_sold_at=Decimal("125.00"),
		)
		self.payment = Payment.objects.create(
			receipt=self.receipt,
			amount=Decimal("125.00"),
			method=Payment.Method.MPESA_STK,
			status=Payment.Status.PENDING,
		)

	def test_old_prompt_no_longer_keeps_receipt_pending(self):
		Payment.objects.filter(pk=self.payment.pk).update(
			created_at=timezone.now() - timedelta(minutes=10)
		)

		self.receipt.refresh_from_db()
		self.assertEqual(self.receipt.payment_status, "on_credit")

	def test_expire_stale_marks_old_prompts_failed(self):
		Payment.objects.filter(pk=self.payment.pk).update(
			created_at=timezone.now() - timedelta(minutes=10)
		)

		updated = self.receipt.expire_stale_stk_payments()

		self.assertEqual(updated, 1)
		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.FAILED)

	def test_recent_prompt_is_not_expired(self):
		self.assertEqual(self.receipt.expire_stale_stk_payments(), 0)
		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.PENDING)


class ReconcileMpesaCommandTests(TestCase):
	def setUp(self):
		self.receipt = SaleReceipt.objects.create(customer_name="Amina")
		self.payment = Payment.objects.create(
			receipt=self.receipt,
			amount=Decimal("125.00"),
			method=Payment.Method.MPESA_STK,
			status=Payment.Status.PENDING,
			checkout_request_id="checkout-reconcile",
		)
		Payment.objects.filter(pk=self.payment.pk).update(
			created_at=timezone.now() - timedelta(minutes=10)
		)

	@patch("sales.management.commands.reconcile_mpesa.query_stk_push")
	def test_successful_query_marks_payment_succeeded(self, query):
		query.return_value = {"ResultCode": "0", "ResultDesc": "The service request is processed successfully."}

		call_command("reconcile_mpesa", stdout=StringIO())

		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)

	@patch("sales.management.commands.reconcile_mpesa.query_stk_push")
	def test_timed_out_prompt_marks_payment_failed(self, query):
		query.return_value = {"ResultCode": "1037", "ResultDesc": "DS timeout user cannot be reached"}

		call_command("reconcile_mpesa", stdout=StringIO())

		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.FAILED)

	@patch("sales.management.commands.reconcile_mpesa.query_stk_push")
	def test_dry_run_does_not_change_status(self, query):
		query.return_value = {"ResultCode": "0", "ResultDesc": "Success"}

		call_command("reconcile_mpesa", stdout=StringIO(), dry_run=True)

		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.PENDING)

	@patch("sales.management.commands.reconcile_mpesa.query_stk_push")
	def test_successful_query_records_the_mpesa_receipt_code(self, query):
		query.return_value = {
			"ResultCode": "0",
			"ResultDesc": "The service request is processed successfully.",
			"CallbackMetadata": {
				"Item": [{"Name": "MpesaReceiptNumber", "Value": "SLK7XYZ12A"}]
			},
		}

		call_command("reconcile_mpesa", stdout=StringIO())

		self.payment.refresh_from_db()
		self.assertEqual(self.payment.reference, "SLK7XYZ12A")


class CheckPaymentStatusTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(
			username="till", password="test-password", is_staff=True
		)
		self.client.force_authenticate(user)
		self.product = Product.objects.create(
			name="Rice", sku="CHECK-RICE", cost_price="100.00",
			selling_price="125.00", stock_quantity=10,
		)
		self.receipt = SaleReceipt.objects.create(customer_name="Amina")
		Sale.objects.create(
			receipt=self.receipt, product=self.product, quantity=1,
			price_sold_at=Decimal("125.00"),
		)
		self.payment = Payment.objects.create(
			receipt=self.receipt, amount=Decimal("125.00"),
			method=Payment.Method.MPESA_STK, status=Payment.Status.PENDING,
			checkout_request_id="checkout-check",
		)

	def check(self):
		return self.client.post(
			reverse("receipt-check-payment", kwargs={"pk": self.receipt.pk}), {}, format="json"
		)

	@patch("sales.views.query_stk_push")
	def test_confirmed_prompt_reports_paid_with_the_mpesa_code(self, query):
		query.return_value = {
			"ResultCode": "0",
			"ResultDesc": "The service request is processed successfully.",
			"CallbackMetadata": {
				"Item": [
					{"Name": "Amount", "Value": 125},
					{"Name": "MpesaReceiptNumber", "Value": "SLK9C1P2QX"},
				]
			},
		}

		response = self.check()

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["state"], "paid")
		self.assertEqual(response.data["mpesa_code"], "SLK9C1P2QX")
		self.assertEqual(response.data["receipt"]["balance"], "0.00")
		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)

	@patch("sales.views.query_stk_push")
	def test_pin_never_entered_reports_not_paid(self, query):
		query.return_value = {
			"ResultCode": "1032",
			"ResultDesc": "Request timed out. Customer never entered the PIN.",
		}

		response = self.check()

		self.assertEqual(response.data["state"], "not_paid")
		self.assertEqual(response.data["balance"], "125.00")
		self.assertIn("never entered the PIN", response.data["result_description"])
		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.FAILED)

	@patch("sales.views.query_stk_push")
	def test_prompt_the_customer_has_not_answered_yet_reports_waiting(self, query):
		query.return_value = {"ResultCode": "2025", "ResultDesc": ""}

		response = self.check()

		self.assertEqual(response.data["state"], "waiting")
		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.PENDING)

	@patch("sales.views.query_stk_push")
	def test_unreachable_daraja_leaves_the_prompt_pending(self, query):
		query.side_effect = MpesaError("Could not reach Safaricom. The payment request was not confirmed.")

		response = self.check()

		self.assertEqual(response.data["state"], "waiting")
		self.assertIn("Could not reach Safaricom", response.data["note"])
		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.PENDING)

	@patch("sales.views.query_stk_push")
	def test_expired_prompt_is_reported_without_calling_daraja(self, query):
		Payment.objects.filter(pk=self.payment.pk).update(
			created_at=timezone.now() - timedelta(minutes=10)
		)

		response = self.check()

		self.assertEqual(response.data["state"], "not_paid")
		query.assert_not_called()
		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, Payment.Status.FAILED)


class TokenExpiryTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(username="cashier", password="test-password")
		self.token = Token.objects.create(user=self.user)
		self.client = APIClient()

	@override_settings(AUTH_TOKEN_TTL_DAYS=30)
	def test_expired_token_is_rejected_and_removed(self):
		Token.objects.filter(pk=self.token.pk).update(
			created=timezone.now() - timedelta(days=31)
		)
		self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

		response = self.client.get(reverse("product-list"))

		self.assertEqual(response.status_code, 401)
		self.assertFalse(Token.objects.filter(pk=self.token.pk).exists())

	@override_settings(AUTH_TOKEN_TTL_DAYS=30)
	def test_fresh_token_is_accepted(self):
		self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

		response = self.client.get(reverse("product-list"))

		self.assertEqual(response.status_code, 200)


class AnalyticsWindowTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(username="cashier", password="test-password")
		self.client.force_authenticate(user=user)

	def test_weekly_income_covers_eight_monday_aligned_weeks(self):
		response = self.client.get(reverse("sale-analytics"))

		self.assertEqual(response.status_code, 200)
		weeks = response.data["weekly_income"]
		today = timezone.localdate()
		current_monday = today - timedelta(days=today.weekday())

		self.assertEqual(len(weeks), 8)
		self.assertEqual(weeks[-1]["week_start"], current_monday.isoformat())
		self.assertEqual(
			weeks[0]["week_start"],
			(current_monday - timedelta(weeks=7)).isoformat(),
		)



class MarkedPriceAndBranchTests(TestCase):
	def setUp(self):
		from accounts.models import Branch, StaffProfile
		from expenses.models import Expense

		self.Branch = Branch
		self.StaffProfile = StaffProfile
		self.Expense = Expense
		self.main = Branch.objects.get(code="MAIN")
		self.town = Branch.objects.create(name="Town branch", code="TOWN")

		self.manager = get_user_model().objects.create_user(
			username="town-manager", password="manager-pass-1", is_staff=True
		)
		StaffProfile.objects.create(user=self.manager, branch=self.town)
		self.cashier = get_user_model().objects.create_user(
			username="town-cashier", password="cashier-pass-1"
		)
		StaffProfile.objects.create(user=self.cashier, branch=self.town)

		self.main_product = Product.objects.create(
			name="Main rice", cost_price="100.00", selling_price="125.00", stock_quantity=20,
		)
		self.town_product = Product.objects.create(
			name="Town rice", branch=self.town,
			cost_price="100.00", selling_price="125.00", stock_quantity=20,
		)

	def test_sale_between_cost_and_retail_price_is_allowed(self):
		client = APIClient()
		client.force_authenticate(self.cashier)

		response = client.post(
			reverse("sale-checkout"),
			{
				"items": [{"product": str(self.town_product.id), "quantity": 1, "price_sold_at": "120.00"}],
				"payments": [{"amount": "120.00", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		sale = Sale.objects.get()
		self.assertEqual(sale.price_sold_at, Decimal("120.00"))
		self.assertEqual(sale.profit, Decimal("20.00"))
		self.assertEqual(SaleReceipt.objects.count(), 1)

	def test_checkout_below_wholesale_cost_is_still_blocked(self):
		client = APIClient()
		client.force_authenticate(self.cashier)

		response = client.post(
			reverse("sale-checkout"),
			{
				"items": [{"product": str(self.town_product.id), "quantity": 1, "price_sold_at": "99.99"}],
				"payments": [{"amount": "99.99", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertIn("wholesale cost", str(response.data))
		self.assertEqual(SaleReceipt.objects.count(), 0)
		self.assertEqual(Sale.objects.count(), 0)

	def test_legacy_sale_endpoint_allows_discounts_above_cost(self):
		client = APIClient()
		client.force_authenticate(self.cashier)

		response = client.post(
			reverse("sale-list"),
			{"product": str(self.town_product.id), "quantity": 1, "price_sold_at": "110.00"},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		self.assertEqual(Sale.objects.count(), 1)

	def test_cashier_checkout_records_branch_and_cashier(self):
		client = APIClient()
		client.force_authenticate(self.cashier)

		response = client.post(
			reverse("sale-checkout"),
			{
				"items": [{"product": str(self.town_product.id), "quantity": 2, "price_sold_at": "125.00"}],
				"payments": [{"amount": "250.00", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		receipt = SaleReceipt.objects.get(pk=response.data["id"])
		self.assertEqual(receipt.branch, self.town)
		self.assertEqual(receipt.created_by, self.cashier)
		self.assertEqual(receipt.payments.get().created_by, self.cashier)
		self.assertEqual(response.data["created_by_name"], "town-cashier")

	def test_cashier_may_send_their_own_branch_explicitly(self):
		client = APIClient()
		client.force_authenticate(self.cashier)

		response = client.post(
			reverse("sale-checkout"),
			{
				"branch": str(self.town.id),
				"items": [{"product": str(self.town_product.id), "quantity": 1, "price_sold_at": "125.00"}],
				"payments": [{"amount": "125.00", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		self.assertEqual(SaleReceipt.objects.get().branch, self.town)

	def test_cashier_cannot_choose_another_branch(self):
		client = APIClient()
		client.force_authenticate(self.cashier)

		response = client.post(
			reverse("sale-checkout"),
			{
				"branch": str(self.main.id),
				"items": [{"product": str(self.main_product.id), "quantity": 1, "price_sold_at": "125.00"}],
				"payments": [{"amount": "125.00", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 403)
		self.assertEqual(SaleReceipt.objects.count(), 0)

	def test_checkout_cannot_sell_another_branch_product(self):
		client = APIClient()
		client.force_authenticate(self.cashier)

		response = client.post(
			reverse("sale-checkout"),
			{
				"items": [{"product": str(self.main_product.id), "quantity": 1, "price_sold_at": "125.00"}],
				"payments": [{"amount": "125.00", "method": "cash"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertIn("not stocked at", str(response.data))

	def test_receipts_and_analytics_are_scoped_to_the_manager_branch(self):
		cashier_client = APIClient()
		cashier_client.force_authenticate(self.cashier)
		town_checkout = cashier_client.post(
			reverse("sale-checkout"),
			{
				"items": [{"product": str(self.town_product.id), "quantity": 1, "price_sold_at": "125.00"}],
				"payments": [{"amount": "125.00", "method": "cash"}],
			},
			format="json",
		)
		main_checkout = APIClient()
		main_cashier = get_user_model().objects.create_user(
			username="main-cashier", password="cashier-pass-2"
		)
		main_checkout.force_authenticate(main_cashier)
		main_response = main_checkout.post(
			reverse("sale-checkout"),
			{
				"items": [{"product": str(self.main_product.id), "quantity": 1, "price_sold_at": "125.00"}],
				"payments": [{"amount": "125.00", "method": "cash"}],
			},
			format="json",
		)

		manager_client = APIClient()
		manager_client.force_authenticate(self.manager)
		receipts = manager_client.get(reverse("receipt-list"))
		analytics = manager_client.get(reverse("sale-analytics"))
		blocked_payment = manager_client.post(
			reverse("receipt-payments", kwargs={"pk": main_response.data["id"]}),
			{"amount": "1.00", "method": "cash"},
			format="json",
		)

		self.assertEqual(receipts.status_code, 200)
		self.assertEqual(receipts.data["count"], 1)
		self.assertEqual(receipts.data["results"][0]["id"], town_checkout.data["id"])
		self.assertEqual(analytics.status_code, 200)
		self.assertEqual(analytics.data["total_sales"], Decimal("125.00"))
		self.assertEqual(blocked_payment.status_code, 403)

	def test_analytics_nets_expenses_out_of_profit(self):
		client = APIClient()
		client.force_authenticate(self.cashier)
		client.post(
			reverse("sale-checkout"),
			{
				"items": [{"product": str(self.town_product.id), "quantity": 2, "price_sold_at": "125.00"}],
				"payments": [{"amount": "250.00", "method": "cash"}],
			},
			format="json",
		)
		self.Expense.objects.create(
			date=timezone.localdate(), category="rent", description="Rent",
			amount=Decimal("15.00"), branch=self.town,
		)

		cashier_view = client.get(reverse("sale-analytics"))
		manager_view = APIClient()
		manager_view.force_authenticate(self.manager)
		response = manager_view.get(reverse("sale-analytics"))

		self.assertIsNone(cashier_view.data["gross_profit"])
		self.assertIsNone(cashier_view.data["total_expenses"])
		self.assertEqual(response.data["gross_profit"], Decimal("50.00"))
		self.assertEqual(response.data["total_expenses"], Decimal("15.00"))
		self.assertEqual(response.data["net_profit"], Decimal("35.00"))

	def test_transactions_csv_export_contains_receipts(self):
		client = APIClient()
		client.force_authenticate(self.cashier)
		client.post(
			reverse("sale-checkout"),
			{
				"customer_name": "Amina",
				"items": [{"product": str(self.town_product.id), "quantity": 1, "price_sold_at": "125.00"}],
			},
			format="json",
		)

		response = client.get(reverse("receipt-export"))

		self.assertEqual(response.status_code, 200)
		self.assertIn("text/csv", response["Content-Type"])
		body = response.content.decode("utf-8-sig")
		self.assertIn("Amina", body)
		self.assertIn("Town branch", body)


class ReportPeriodTests(TestCase):
	"""A named period is the shop's answer to "which day", so it is worked out on
	the server. Dates computed by a till whose machine sits in another zone would
	move real trade into the wrong report."""

	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(username="reporter", password="report-pass")
		self.client.force_authenticate(user=user)
		self.product = Product.objects.create(
			name="Cooking fat",
			sku="PERIOD-FAT",
			cost_price="100.00",
			selling_price="150.00",
			stock_quantity=20,
		)

	def _checkout(self):
		response = self.client.post(
			reverse("sale-checkout"),
			{
				"items": [
					{"product": str(self.product.id), "quantity": 1, "price_sold_at": "150.00"}
				],
				"payments": [{"amount": "150.00", "method": "cash"}],
			},
			format="json",
		)
		self.assertEqual(response.status_code, 201)
		return response.data["id"]

	def test_named_period_outranks_dates_from_the_till(self):
		today_id = self._checkout()
		old_id = self._checkout()
		SaleReceipt.objects.filter(pk=old_id).update(created_at=timezone.now() - timedelta(days=3))

		response = self.client.get(reverse("receipt-list"), {
			"period": "today",
			"start_date": (timezone.localdate() - timedelta(days=10)).isoformat(),
			"end_date": (timezone.localdate() - timedelta(days=3)).isoformat(),
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual({row["id"] for row in response.data["results"]}, {today_id})

	def test_yesterday_period_returns_only_yesterday(self):
		today_id = self._checkout()
		yesterday_id = self._checkout()
		SaleReceipt.objects.filter(pk=yesterday_id).update(
			created_at=timezone.now() - timedelta(days=1)
		)

		response = self.client.get(reverse("receipt-list"), {"period": "yesterday"})

		self.assertEqual({row["id"] for row in response.data["results"]}, {yesterday_id})
		self.assertNotIn(today_id, {row["id"] for row in response.data["results"]})

	def test_unknown_period_is_rejected(self):
		response = self.client.get(reverse("receipt-list"), {"period": "last tuesday"})
		self.assertEqual(response.status_code, 400)

	def test_analytics_names_the_shop_today(self):
		self._checkout()
		response = self.client.get(
			reverse("sale-analytics"), {"month": timezone.localdate().strftime("%Y-%m")}
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["today"], timezone.localdate().isoformat())


class MpesaFailureClassTests(TestCase):
	"""A cashier is told either "nothing was charged" or "we do not know".

	Those are different facts, and mixing them makes a shop send a second prompt
	over a customer whose phone is already ringing."""

	def _raise(self, error, status_code=None):
		def fake_urlopen(*args, **kwargs):
			if status_code is not None:
				raise HTTPError("https://x", status_code, "boom", {}, BytesIO(b"gateway"))
			raise error

		with patch("sales.mpesa.urlopen", fake_urlopen), patch(
			"sales.mpesa._load_config",
			return_value={
				"consumer_key": "k",
				"consumer_secret": "s",
				"shortcode": "12345",
				"passkey": "p",
				"callback_url": "https://shop.example/callback",
				"callback_token": "a-long-random-token",
				"environment": "sandbox",
			},
		), patch("sales.mpesa._access_token", return_value="token"):
			try:
				initiate_stk_push(
					Payment(amount=Decimal("100.00")), "0794671494"
				)
			except MpesaError as error:
				return error
		return None

	def test_gateway_answer_of_five_hundred_is_unconfirmed(self):
		self.assertIsInstance(self._raise(None, 500), MpesaUnconfirmed)

	def test_timeout_is_unconfirmed(self):
		self.assertIsInstance(self._raise(TimeoutError(), None), MpesaUnconfirmed)

	def test_no_connection_at_all_is_a_clean_no(self):
		error = self._raise(URLError("no route to host"), None)
		self.assertIsInstance(error, MpesaError)
		self.assertNotIsInstance(error, MpesaUnconfirmed)
		self.assertIn("Nothing has been charged", str(error))

	def test_refused_request_is_a_clean_no(self):
		error = self._raise(None, 400)
		self.assertNotIsInstance(error, MpesaUnconfirmed)
		self.assertIn("refused", str(error))


class UnconfirmedStkPushTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		user = get_user_model().objects.create_user(username="stk", password="stk-pass")
		self.client.force_authenticate(user=user)
		self.product = Product.objects.create(
			name="Bulb",
			sku="STK-BULB",
			cost_price="50.00",
			selling_price="100.00",
			stock_quantity=10,
		)

	@patch("sales.views.initiate_stk_push")
	def test_prompt_safaricom_never_answered_is_reported_as_unconfirmed(self, initiate):
		initiate.side_effect = MpesaUnconfirmed(
			"Safaricom did not answer (HTTP 500). Nothing is confirmed by this response."
		)
		receipt = self.client.post(
			reverse("sale-checkout"),
			{
				"customer_name": "Amina",
				"customer_phone": "0794671494",
				"items": [{"product": str(self.product.id), "quantity": 1, "price_sold_at": "100.00"}],
			},
			format="json",
		)
		response = self.client.post(
			reverse("receipt-stk-push", kwargs={"pk": receipt.data["id"]}),
			{"phone": "0794671494"},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertIs(response.data["confirmed"], False)
		payment = Payment.objects.get(receipt_id=receipt.data["id"])
		self.assertEqual(payment.status, Payment.Status.FAILED)
		self.assertIn("Nothing is confirmed", payment.result_description)

	@patch("sales.views.initiate_stk_push")
	def test_prompt_safaricom_refused_keeps_the_plain_message(self, initiate):
		initiate.side_effect = MpesaError("Safaricom refused the request (HTTP 400).")
		receipt = self.client.post(
			reverse("sale-checkout"),
			{
				"customer_name": "Amina",
				"customer_phone": "0794671494",
				"items": [{"product": str(self.product.id), "quantity": 1, "price_sold_at": "100.00"}],
			},
			format="json",
		)
		response = self.client.post(
			reverse("receipt-stk-push", kwargs={"pk": receipt.data["id"]}),
			{"phone": "0794671494"},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertNotIn("confirmed", response.data)


class ClosePeriodTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.cashier = get_user_model().objects.create_user(
			username="till", password="archive-pass"
		)
		self.owner = get_user_model().objects.create_user(
			username="owner", password="archive-pass", is_superuser=True, is_staff=True
		)
		self.client.force_authenticate(user=self.owner)
		self.rice = Product.objects.create(
			name="Rice",
			sku="ARCHIVE-1",
			cost_price="100.00",
			selling_price="125.00",
			stock_quantity=40,
		)
		self.close_url = reverse("receipt-close-period")

	def _old_bill(self, paid="125.00", days_ago=40):
		bill = self.client.post(
			reverse("sale-checkout"),
			{
				"customer_name": "Amina",
				"customer_phone": "0794671494",
				"items": [{"product": str(self.rice.id), "quantity": 1, "price_sold_at": "125.00"}],
				**({"payments": [{"amount": paid, "method": "cash"}]} if paid else {}),
			},
			format="json",
		)
		self.assertEqual(bill.status_code, 201, bill.data)
		moment = timezone.now() - timedelta(days=days_ago)
		pk = bill.data["id"]
		SaleReceipt.objects.filter(pk=pk).update(created_at=moment)
		Sale.objects.filter(receipt_id=pk).update(created_at=moment)
		Payment.objects.filter(receipt_id=pk).update(created_at=moment)
		return pk

	def _day_ago(self, days_ago):
		return (timezone.localdate() - timedelta(days=days_ago)).isoformat()

	def test_a_closed_day_leaves_the_list_but_still_counts_in_the_totals(self):
		pk = self._old_bill()
		month = (timezone.localdate() - timedelta(days=40)).strftime("%Y-%m")

		closed = self.client.post(
			self.close_url, {"start_date": self._day_ago(45), "end_date": self._day_ago(35)}, format="json"
		)
		self.assertEqual(closed.status_code, 200, closed.data)
		self.assertEqual(closed.data["closed"], 1)

		self.assertEqual(self.client.get(reverse("receipt-list")).data["count"], 0)
		archived = self.client.get(reverse("receipt-list"), {"include_closed": "1"})
		self.assertEqual(archived.data["count"], 1)
		self.assertEqual(str(archived.data["results"][0]["id"]), str(pk))

		totals = self.client.get(reverse("sale-analytics"), {"month": month})
		self.assertEqual(totals.data["total_sales"], Decimal("125.00"))
		self.assertEqual(totals.data["items_sold"], 1)

	def test_a_bill_still_owed_is_never_archived(self):
		pk = self._old_bill(paid="")

		closed = self.client.post(self.close_url, {"end_date": self._day_ago(35)}, format="json")
		self.assertEqual(closed.data["closed"], 0)
		self.assertEqual(closed.data["left_open"], 1)

		listed = self.client.get(reverse("receipt-list"))
		self.assertEqual(listed.data["count"], 1)
		self.assertEqual(str(listed.data["results"][0]["id"]), str(pk))
		credits = self.client.get(reverse("receipt-credits"))
		self.assertEqual(credits.data["outstanding_total"], Decimal("125.00"))

	def test_an_archived_bill_can_still_be_paid(self):
		# A note handed over after the shop closed its paperwork on the day still
		# has to be accepted, or the customer's debt would have nowhere to go.
		pk = self._old_bill(paid="25.00")
		self.client.post(self.close_url, {"end_date": self._day_ago(35)}, format="json")

		self.assertEqual(
			self.client.get(reverse("receipt-detail", kwargs={"pk": pk})).status_code, 200
		)
		paid = self.client.post(
			reverse("receipt-payments", kwargs={"pk": pk}),
			{"amount": "100.00", "method": "cash"},
			format="json",
		)
		self.assertEqual(paid.status_code, 201, paid.data)
		self.assertEqual(paid.data["balance"], "0.00")

	def test_only_the_super_admin_can_close_a_period(self):
		self.client.force_authenticate(user=self.cashier)
		refused = self.client.post(self.close_url, {"end_date": self._day_ago(35)}, format="json")
		self.assertEqual(refused.status_code, 403)

	def test_the_day_still_trading_cannot_be_closed(self):
		blocked = self.client.post(self.close_url, {"end_date": self._day_ago(0)}, format="json")
		self.assertEqual(blocked.status_code, 400)
		self.assertIn("end_date", blocked.data)

	def test_reopening_a_period_brings_its_bills_back(self):
		pk = self._old_bill()
		period = {"start_date": self._day_ago(45), "end_date": self._day_ago(35)}
		self.client.post(self.close_url, period, format="json")
		self.assertEqual(self.client.get(reverse("receipt-list")).data["count"], 0)

		undone = self.client.post(self.close_url, {**period, "undo": "true"}, format="json")
		self.assertEqual(undone.data["reopened"], 1)
		self.assertIsNone(SaleReceipt.objects.get(pk=pk).closed_at)
		self.assertEqual(self.client.get(reverse("receipt-list")).data["count"], 1)

	def test_a_cashier_cannot_call_archived_bills_back(self):
		self._old_bill()
		self.client.post(self.close_url, {"end_date": self._day_ago(35)}, format="json")
		self.client.force_authenticate(user=self.cashier)

		self.assertEqual(self.client.get(reverse("receipt-list")).data["count"], 0)
		self.assertEqual(
			self.client.get(reverse("receipt-list"), {"include_closed": "1"}).data["count"], 0
		)


class ReturnTests(TestCase):
	def setUp(self):
		from accounts.services import main_branch

		self.client = APIClient()
		self.cashier = get_user_model().objects.create_user(
			username="till", password="return-pass"
		)
		self.owner = get_user_model().objects.create_user(
			username="owner", password="return-pass", is_superuser=True, is_staff=True
		)
		self.client.force_authenticate(user=self.owner)
		self.rice = Product.objects.create(
			name="Rice",
			sku="RETURN-1",
			cost_price="100.00",
			selling_price="125.00",
			stock_quantity=40,
		)
		self.customer = Customer.objects.create(
			name="Amina", phone="0794671494", branch=main_branch()
		)

	def _bill(self, quantity=3, paid="375.00", name="Amina", phone="0794671494"):
		body = {
			"customer_name": name,
			"customer_phone": phone,
			"items": [
				{"product": str(self.rice.id), "quantity": quantity, "price_sold_at": "125.00"}
			],
		}
		if paid:
			body["payments"] = [{"amount": paid, "method": "cash"}]
		created = self.client.post(reverse("sale-checkout"), body, format="json")
		self.assertEqual(created.status_code, 201, created.data)
		return created.data["id"]

	def _return(self, receipt, quantity, key="", **body):
		sale = Sale.objects.filter(receipt_id=receipt).first()
		return self.client.post(
			reverse("receipt-returns", kwargs={"pk": receipt}),
			{"items": [{"sale": str(sale.id), "quantity": quantity}], **body},
			format="json",
			**({"HTTP_IDEMPOTENCY_KEY": key} if key else {}),
		)

	def test_a_return_puts_the_goods_back_and_the_money_over(self):
		receipt = self._bill()
		self.rice.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 37)

		taken = self._return(receipt, 1, reason="Customer changed their mind")
		self.assertEqual(taken.status_code, 201, taken.data)
		self.rice.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 38)

		self.assertEqual(taken.data["total"], "375.00")
		self.assertEqual(taken.data["returned_total"], "125.00")
		self.assertEqual(taken.data["net_total"], "250.00")
		self.assertEqual(taken.data["refunded_total"], "125.00")
		self.assertEqual(taken.data["balance"], "0.00")
		self.assertEqual(taken.data["payment_status"], "paid")
		self.assertEqual(len(taken.data["returns"]), 1)
		line = taken.data["returns"][0]["items"][0]
		self.assertEqual(line["product_name"], "Rice")
		self.assertEqual(line["unit_price"], "125.00")

	def test_the_sale_line_is_never_rewritten(self):
		receipt = self._bill()
		before = Sale.objects.get(receipt_id=receipt)
		self._return(receipt, 2)

		after = Sale.objects.get(pk=before.pk)
		self.assertEqual(after.quantity, 3)
		self.assertEqual(after.total, Decimal("375.00"))
		self.assertEqual(Sale.objects.filter(receipt_id=receipt).count(), 1)
		with self.assertRaises(ValidationError):
			after.delete()
		with self.assertRaises(ValidationError):
			SaleReturnItem.objects.get(sale_return=SaleReturn.objects.get(receipt_id=receipt)).delete()

	def test_the_refund_is_worked_out_not_typed_in(self):
		receipt = self._bill(paid="375.00")
		# A till that tries to hand back more than the shop holds is overruled:
		# the number comes from what was paid against what is now owed.
		taken = self._return(receipt, 1, refund="9999.00")
		self.assertEqual(taken.data["refunded_total"], "125.00")

	def test_a_return_on_a_credit_bill_clears_the_debt_without_any_cash(self):
		receipt = self._bill(paid="100.00")
		taken = self._return(receipt, 1)
		self.assertEqual(taken.status_code, 201, taken.data)
		self.assertEqual(taken.data["net_total"], "250.00")
		self.assertEqual(taken.data["refunded_total"], "0.00")
		self.assertEqual(taken.data["balance"], "150.00")
		self.assertEqual(taken.data["payment_status"], "partially_paid")
		self.customer.refresh_from_db()
		self.assertEqual(self.customer.outstanding, Decimal("150.00"))

	def test_nothing_can_come_back_that_is_not_still_out(self):
		receipt = self._bill(quantity=2, paid="250.00")
		first = self._return(receipt, 1)
		self.assertEqual(first.status_code, 201, first.data)

		too_many = self._return(receipt, 2)
		self.assertEqual(too_many.status_code, 400)
		self.assertIn("items", too_many.data)
		self.assertEqual(SaleReturn.objects.filter(receipt_id=receipt).count(), 1)

	def test_a_line_from_another_bill_cannot_be_returned_here(self):
		receipt = self._bill()
		other_line = Sale.objects.get(receipt_id=self._bill(phone="0700000111"))
		refused = self.client.post(
			reverse("receipt-returns", kwargs={"pk": receipt}),
			{"items": [{"sale": str(other_line.id), "quantity": 1}]},
			format="json",
		)
		self.assertEqual(refused.status_code, 400)
		self.assertEqual(SaleReturn.objects.count(), 0)

	def test_only_a_manager_can_take_a_return(self):
		receipt = self._bill()
		self.client.force_authenticate(user=self.cashier)
		refused = self._return(receipt, 1)
		self.assertEqual(refused.status_code, 403)
		self.assertEqual(SaleReturn.objects.count(), 0)
		self.rice.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 37)

	def test_a_return_is_written_once_even_if_the_answer_is_lost(self):
		receipt = self._bill()
		first = self._return(receipt, 1, key="return-abc")
		self.assertEqual(first.status_code, 201, first.data)

		retry = self._return(receipt, 1, key="return-abc")
		self.assertEqual(retry.status_code, 200, retry.data)
		self.assertEqual(SaleReturn.objects.filter(receipt_id=receipt).count(), 1)
		self.rice.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 38)

		clash = self._return(receipt, 2, key="return-abc")
		self.assertEqual(clash.status_code, 409)

	def test_a_closed_period_cannot_be_edited_by_a_return(self):
		receipt = self._bill()
		# The archive is paperwork the owner has already signed off on, so a return
		# cannot quietly move its numbers.
		SaleReceipt.objects.filter(pk=receipt).update(
			closed_at=timezone.now(), closed_by=self.owner
		)
		refused = self._return(receipt, 1)
		self.assertEqual(refused.status_code, 400)
		self.assertEqual(SaleReturn.objects.count(), 0)
		self.rice.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 37)

	def test_a_refund_leaves_a_different_bill_still_owed(self):
		# Two bills on one account: one paid up, one still on credit. Handing cash
		# back on the paid-up bill must not quietly clear what the other still owes.
		settled = self._bill(quantity=2, paid="250.00")
		self._bill(quantity=3, paid="25.00")

		taken = self._return(settled, 1)
		self.assertEqual(taken.data["refunded_total"], "125.00")

		book = self.client.get(
			reverse("customer-ledger", kwargs={"pk": self.customer.id})
		).data
		self.assertEqual(book["customer"]["outstanding"], "350.00")
		returned = next(entry for entry in book["entries"] if entry["type"] == "return")
		self.assertEqual(returned["credit"], Decimal("0.00"))
		self.assertIn("125.00 handed back", returned["description"])
		self.assertEqual(book["entries"][-1]["balance"], Decimal("350.00"))

	def test_the_export_shows_what_stayed_in_the_till(self):
		receipt = self._bill()
		self._return(receipt, 1)

		body = self.client.get(reverse("receipt-export")).content.decode("utf-8-sig")
		self.assertIn("Collected (KES)", body)
		# Billed 375, 125 came back, 375 was paid and 125 handed over: the drawer
		# kept 250, and that is the figure the owner has to be able to count.
		self.assertIn("375.00,125.00,375.00,125.00,250.00,0.00", body)

	def test_a_return_waits_for_an_unanswered_mpesa_prompt(self):
		# Money still on its way in answers to the old total. Taking goods back
		# underneath that prompt would let the payment land against goods the
		# shop already has, so the counter is told to wait.
		receipt = self._bill(paid="125.00")
		Payment.objects.create(
			receipt_id=receipt,
			created_by=self.owner,
			amount=Decimal("250.00"),
			method=Payment.Method.MPESA_STK,
			status=Payment.Status.PENDING,
		)

		refused = self._return(receipt, 1)
		self.assertEqual(refused.status_code, 400)
		self.assertIn("M-Pesa", str(refused.data))
		self.assertEqual(SaleReturn.objects.count(), 0)
		self.rice.refresh_from_db()
		self.assertEqual(self.rice.stock_quantity, 37)

	def test_the_ledger_shows_what_came_back(self):
		receipt = self._bill(paid="100.00")
		self._return(receipt, 1, reason="Damaged")

		entries = self.client.get(
			reverse("customer-ledger", kwargs={"pk": self.customer.id})
		).data["entries"]
		returned = next(entry for entry in entries if entry["type"] == "return")
		self.assertEqual(returned["credit"], Decimal("125.00"))
		self.assertIn("Damaged", returned["description"])
		self.assertEqual(entries[-1]["balance"], Decimal("150.00"))

	def test_the_day_takings_lose_what_was_handed_back(self):
		receipt = self._bill()
		self._return(receipt, 1)

		summary = self.client.get(reverse("sale-summary")).data
		self.assertEqual(summary["total_sales"], Decimal("250.00"))
		self.assertEqual(summary["items_sold"], 2)
		self.assertEqual(summary["gross_profit"], Decimal("50.00"))
		self.assertEqual(summary["amount_refunded"], Decimal("125.00"))

		month = timezone.localdate().strftime("%Y-%m")
		analytics = self.client.get(reverse("sale-analytics"), {"month": month}).data
		self.assertEqual(analytics["total_sales"], Decimal("250.00"))
		self.assertEqual(analytics["returned_value"], Decimal("125.00"))
		self.assertEqual(analytics["items_sold"], 2)
		today_row = next(
			row for row in analytics["daily_totals"]
			if row["date"] == timezone.localdate().isoformat()
		)
		# Collected less refunded is what stayed in the till, which is the number
		# the owner counts against the cash drawer at close.
		self.assertEqual(today_row["amount_collected"], Decimal("250.00"))
		product_row = next(
			row for row in analytics["product_performance"] if row["product_id"] == self.rice.id
		)
		self.assertEqual(product_row["quantity_sold"], 2)
		self.assertEqual(product_row["sales_total"], Decimal("250.00"))

	def test_a_full_return_leaves_nothing_owed_and_no_second_debt(self):
		receipt = self._bill(paid="375.00")
		taken = self._return(receipt, 3)
		self.assertEqual(taken.data["net_total"], "0.00")
		self.assertEqual(taken.data["balance"], "0.00")
		self.assertEqual(taken.data["payment_status"], "paid")
		self.assertEqual(taken.data["refunded_total"], "375.00")

		listed = self.client.get(reverse("receipt-list"), {"status": "paid"})
		self.assertEqual(listed.data["count"], 1)
		self.assertEqual(self.client.get(reverse("receipt-credits")).data["receipt_count"], 0)
