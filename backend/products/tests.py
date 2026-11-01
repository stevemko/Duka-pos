from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from .models import Product
from .services import move_stock


class ProductCostEntryTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.user = get_user_model().objects.create_user(
			username="owner", password="test-password", is_staff=True
		)
		self.client.force_authenticate(user=self.user)

	def test_product_api_requires_authentication(self):
		response = APIClient().get(reverse("product-list"))

		self.assertEqual(response.status_code, 401)

	def test_owner_can_log_in_and_receive_an_api_token(self):
		response = APIClient().post(
			reverse("api-login"),
			{"username": "owner", "password": "test-password"},
			format="json",
		)

		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.data["token"])

	def test_product_can_be_created_with_cost_without_catalog_selling_price(self):
		response = self.client.post(
			reverse("product-list"),
			{"name": "Cooking oil", "cost_price": "180.00", "stock_quantity": 8},
			format="json",
		)

		self.assertEqual(response.status_code, 201)
		product = Product.objects.get(pk=response.data["id"])
		self.assertEqual(product.cost_price, Decimal("180.00"))
		self.assertEqual(product.selling_price, Decimal("180.00"))

	def test_non_staff_user_cannot_create_products(self):
		cashier = get_user_model().objects.create_user(
			username="cashier", password="test-password"
		)
		client = APIClient()
		client.force_authenticate(user=cashier)

		response = client.post(
			reverse("product-list"),
			{"name": "Cooking oil", "cost_price": "180.00", "stock_quantity": 8},
			format="json",
		)

		self.assertEqual(response.status_code, 403)

	def test_deleting_a_product_with_sales_returns_conflict(self):
		product = Product.objects.create(
			name="Cooking oil", cost_price=Decimal("180.00"),
			selling_price=Decimal("200.00"), stock_quantity=3,
		)
		from sales.models import Sale, SaleReceipt

		receipt = SaleReceipt.objects.create()
		Sale.objects.create(
			receipt=receipt, product=product, quantity=1,
			price_sold_at=Decimal("200.00"),
		)

		response = self.client.delete(reverse("product-detail", args=[product.pk]))

		self.assertEqual(response.status_code, 409)
		self.assertTrue(Product.objects.filter(pk=product.pk).exists())

	def test_invalid_image_content_is_rejected(self):
		upload = SimpleUploadedFile("fake.png", b"not really an image", content_type="image/png")

		response = self.client.post(
			reverse("product-list"),
			{
				"name": "LED bulb",
				"cost_price": "100.00",
				"selling_price": "150.00",
				"stock_quantity": 4,
				"image": upload,
			},
			format="multipart",
		)

		self.assertEqual(response.status_code, 400)
		self.assertIn("image", response.data)
		self.assertEqual(Product.objects.count(), 0)

	def test_selling_price_below_cost_is_rejected(self):
		response = self.client.post(
			reverse("product-list"),
			{"name": "LED bulb", "cost_price": "100.00", "selling_price": "90.00", "stock_quantity": 4},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertIn("selling_price", response.data)


class ProductCatalogTests(TestCase):
	def setUp(self):
		from accounts.models import Branch

		self.branch = Branch.objects.get_or_create(
			code="MAIN", defaults={"name": "Main shop"}
		)[0]
		self.manager = get_user_model().objects.create_user(
			username="manager", password="test-password", is_staff=True
		)
		self.cashier = get_user_model().objects.create_user(
			username="cashier", password="test-password"
		)
		self.client = APIClient()
		self.client.force_authenticate(self.manager)
		self.bulb = Product.objects.create(
			name="LED bulb 9W", sku="LED-9W", category="Bulbs",
			cost_price="180.00", selling_price="250.00", stock_quantity=3, reorder_threshold=5,
		)
		self.spot = Product.objects.create(
			name="LED spotlight", sku="SPOT-12", category="Spotlights",
			cost_price="400.00", selling_price="600.00", stock_quantity=40, reorder_threshold=5,
		)
		self.mirror = Product.objects.create(
			name="Side mirror", sku="MIR-01", category="Mirrors",
			cost_price="300.00", selling_price="450.00", stock_quantity=8, reorder_threshold=2,
		)

	def test_search_category_and_low_stock_filters(self):
		by_search = self.client.get(reverse("product-list"), {"q": "spot"})
		by_sku = self.client.get(reverse("product-list"), {"sku": "mir-01"})
		by_category = self.client.get(reverse("product-list"), {"category": "Mirrors"})
		low = self.client.get(reverse("product-list"), {"low": "1"})

		self.assertEqual(by_search.data["count"], 1)
		self.assertEqual(by_search.data["results"][0]["name"], "LED spotlight")
		self.assertEqual(by_sku.data["count"], 1)
		self.assertEqual(by_sku.data["results"][0]["name"], "Side mirror")
		self.assertEqual(by_category.data["count"], 1)
		self.assertEqual(low.data["count"], 1)
		self.assertEqual(low.data["results"][0]["name"], "LED bulb 9W")

	def test_pagination_respects_page_size(self):
		response = self.client.get(reverse("product-list"), {"page": 2, "page_size": 2})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["count"], 3)
		self.assertEqual(len(response.data["results"]), 1)
		self.assertTrue(response.data["next"] is None)

	def test_categories_and_overview(self):
		categories = self.client.get(reverse("product-categories"))
		overview = self.client.get(reverse("product-overview"))

		self.assertEqual(categories.status_code, 200)
		self.assertEqual(
			[{"category": row["category"], "products": row["products"]} for row in categories.data],
			[
				{"category": "Bulbs", "products": 1},
				{"category": "Mirrors", "products": 1},
				{"category": "Spotlights", "products": 1},
			],
		)
		self.assertEqual(overview.data["products"], 3)
		self.assertEqual(overview.data["units"], 51)
		self.assertEqual(overview.data["low"], 1)
		self.assertEqual(overview.data["cost_value"], Decimal("180.00") * 3 + Decimal("400.00") * 40 + Decimal("300.00") * 8)
		self.assertEqual(overview.data["retail_value"], Decimal("250.00") * 3 + Decimal("600.00") * 40 + Decimal("450.00") * 8)

	def test_cashier_sees_price_floor_but_not_wholesale_cost(self):
		client = APIClient()
		client.force_authenticate(self.cashier)

		response = client.get(reverse("product-list"))
		row = next(item for item in response.data["results"] if item["id"] == str(self.bulb.id))

		self.assertNotIn("cost_price", row)
		self.assertEqual(Decimal(str(row["price_floor"])), Decimal("180.00"))
		self.assertEqual(Decimal(str(row["selling_price"])), Decimal("250.00"))

		overview = client.get(reverse("product-overview"))
		self.assertIsNone(overview.data["cost_value"])
		self.assertEqual(
			overview.data["retail_value"],
			Decimal("250.00") * 3 + Decimal("600.00") * 40 + Decimal("450.00") * 8,
		)

	def test_csv_import_creates_products_and_reports_bad_rows(self):
		csv_body = (
			"name,sku,category,cost_price,selling_price,stock_quantity,reorder_threshold\n"
			"LED strip,STRIP-1,Strips,100.00,160.00,20,5\n"
			"Bad row,BAD-1,Strips,100.00,90.00,5,2\n"
			"Bad number,NUM-1,Strips,abc,100.00,5,2\n"
			"Duplicate,LED-9W,Bulbs,10.00,20.00,1,1\n"
			"\n"
		)
		upload = SimpleUploadedFile("products.csv", csv_body.encode("utf-8"), content_type="text/csv")

		response = self.client.post(reverse("product-import"), {"file": upload}, format="multipart")

		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.data["created"], 1)
		self.assertEqual(response.data["error_count"], 3)
		self.assertTrue(Product.objects.filter(sku="STRIP-1").exists())
		stripped = Product.objects.get(sku="STRIP-1")
		self.assertEqual(stripped.selling_price, Decimal("160.00"))
		self.assertEqual(stripped.stock_quantity, 20)

	def test_cashier_cannot_import_products(self):
		client = APIClient()
		client.force_authenticate(self.cashier)
		upload = SimpleUploadedFile(
			"products.csv",
			b"name,cost_price\nNope,10.00\n",
			content_type="text/csv",
		)

		response = client.post(reverse("product-import"), {"file": upload}, format="multipart")

		self.assertEqual(response.status_code, 403)


class ProductMergeTests(TestCase):
	def setUp(self):
		from accounts.models import Branch

		self.main = Branch.objects.get_or_create(code="MAIN", defaults={"name": "Main shop"})[0]
		self.upstream = Branch.objects.create(code="UPSTREAM", name="Upstream shop")
		self.super_user = get_user_model().objects.create_user(
			username="boss", password="test-password", is_staff=True, is_superuser=True
		)
		self.manager = get_user_model().objects.create_user(
			username="manager", password="test-password", is_staff=True
		)
		self.client = APIClient()
		self.client.force_authenticate(self.super_user)
		self.kept = Product.objects.create(
			branch=self.main, name="Side mirror", sku="SM-001",
			cost_price="300.00", selling_price="450.00", stock_quantity=5,
		)
		self.duplicate = Product.objects.create(
			branch=self.main, name="Sidemirror", sku="SM-002",
			cost_price="310.00", selling_price="500.00", stock_quantity=12,
		)

	def test_merge_moves_stock_and_history_into_the_kept_product(self):
		from alerts.models import StockAlert
		from sales.models import Sale, SaleReceipt

		receipt = SaleReceipt.objects.create(branch=self.main)
		sale = Sale.objects.create(
			receipt=receipt, product=self.duplicate, quantity=2,
			price_sold_at=Decimal("500.00"),
		)
		StockAlert.objects.create(product=self.duplicate, stock_at_trigger=1)

		response = self.client.post(
			reverse("product-merge", args=[self.duplicate.pk]),
			{"target": str(self.kept.pk)},
			format="json",
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["stock_moved"], 12)
		self.assertEqual(response.data["sales_moved"], 1)
		self.assertFalse(Product.objects.filter(pk=self.duplicate.pk).exists())

		kept = Product.objects.get(pk=self.kept.pk)
		self.assertEqual(kept.stock_quantity, 17)
		sale.refresh_from_db()
		self.assertEqual(sale.product_id, kept.pk)
		self.assertEqual(sale.price_sold_at, Decimal("500.00"))
		self.assertEqual(kept.sales.count(), 1)
		self.assertEqual(StockAlert.objects.count(), 0)

	def test_merge_carries_taken_back_goods_with_the_product(self):
		"""Goods already handed back belong to the same shelf item, so a merge has
		to move them too - otherwise the duplicate is protected and cannot go."""
		from sales.models import Sale, SaleReceipt, SaleReturn, SaleReturnItem

		receipt = SaleReceipt.objects.create(branch=self.main)
		sale = Sale.objects.create(
			receipt=receipt, product=self.duplicate, quantity=2,
			price_sold_at=Decimal("500.00"),
		)
		entry_return = SaleReturn.objects.create(
			receipt=receipt, branch=self.main, value=Decimal("500.00")
		)
		returned = SaleReturnItem.objects.create(
			sale_return=entry_return, sale=sale, product=self.duplicate, quantity=1
		)

		response = self.client.post(
			reverse("product-merge", args=[self.duplicate.pk]),
			{"target": str(self.kept.pk)},
			format="json",
		)

		self.assertEqual(response.status_code, 200, response.data)
		self.assertEqual(response.data["returns_moved"], 1)
		self.assertFalse(Product.objects.filter(pk=self.duplicate.pk).exists())
		returned.refresh_from_db()
		self.assertEqual(returned.product_id, self.kept.pk)

	def test_manager_cannot_merge_products(self):
		client = APIClient()
		client.force_authenticate(self.manager)

		response = client.post(
			reverse("product-merge", args=[self.duplicate.pk]),
			{"target": str(self.kept.pk)},
			format="json",
		)

		self.assertEqual(response.status_code, 403)
		self.assertTrue(Product.objects.filter(pk=self.duplicate.pk).exists())

	def test_merge_needs_a_target_in_the_same_shop(self):
		other_shop = Product.objects.create(
			branch=self.upstream, name="Side mirror", sku="SM-001",
			cost_price="300.00", selling_price="450.00", stock_quantity=3,
		)

		missing = self.client.post(
			reverse("product-merge", args=[self.duplicate.pk]), {}, format="json"
		)
		into_self = self.client.post(
			reverse("product-merge", args=[self.duplicate.pk]),
			{"target": str(self.duplicate.pk)},
			format="json",
		)
		across_shops = self.client.post(
			reverse("product-merge", args=[self.duplicate.pk]),
			{"target": str(other_shop.pk)},
			format="json",
		)

		self.assertEqual(missing.status_code, 400)
		self.assertEqual(into_self.status_code, 400)
		self.assertEqual(across_shops.status_code, 400)
		self.assertIn("same shop", str(across_shops.data["target"]))
		self.assertEqual(Product.objects.count(), 3)

	def test_legacy_product_can_merge_into_the_main_shop_row(self):
		# Old rows were saved with no branch, which the list still labels "Main shop".
		legacy = Product.objects.create(
			name="side mirror", sku="SM-003",
			cost_price="300.00", selling_price="450.00", stock_quantity=4,
		)

		response = self.client.post(
			reverse("product-merge", args=[legacy.pk]),
			{"target": str(self.kept.pk)},
			format="json",
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(Product.objects.get(pk=self.kept.pk).stock_quantity, 9)


class StockMovementTests(TestCase):
	"""Stock only ever moves by a number of units, checked in the write itself.

	An absolute overwrite - the shape a stale edit form produces - undoes whatever
	the tills sold while it was open."""

	def setUp(self):
		self.manager = get_user_model().objects.create_user(
			username="stock-manager", password="test-password", is_staff=True
		)
		self.client = APIClient()
		self.client.force_authenticate(self.manager)
		self.bulb = Product.objects.create(
			name="LED bulb 9W", sku="STOCK-9W",
			cost_price="180.00", selling_price="250.00", stock_quantity=10, reorder_threshold=2,
		)

	def sell_behind_the_form(self, units):
		"""Stand in for another till: change the shelf without touching this object."""
		Product.objects.filter(pk=self.bulb.pk).update(stock_quantity=10 - units)

	def test_movement_cannot_take_more_than_the_shelf_holds(self):
		self.bulb.refresh_from_db()

		self.assertIsNone(move_stock(self.bulb, -11))
		self.assertEqual(Product.objects.get(pk=self.bulb.pk).stock_quantity, 10)

	def test_movement_adds_to_what_the_shelf_holds_now(self):
		self.sell_behind_the_form(4)

		moved = move_stock(self.bulb, 3)

		self.assertIsNotNone(moved)
		self.assertEqual(Product.objects.get(pk=self.bulb.pk).stock_quantity, 9)

	def test_editing_prices_leaves_sold_stock_alone(self):
		self.sell_behind_the_form(3)

		response = self.client.patch(
			reverse("product-detail", args=[self.bulb.pk]),
			{
				"selling_price": "260.00",
				"stock_quantity": 10,
				"stock_quantity_from": 10,
			},
			format="json",
		)

		self.assertEqual(response.status_code, 200)
		shelf = Product.objects.get(pk=self.bulb.pk)
		self.assertEqual(shelf.stock_quantity, 7)
		self.assertEqual(shelf.selling_price, Decimal("260.00"))

	def test_a_counted_number_moves_stock_by_the_difference(self):
		# The shelf was counted at 12 while the system said 10, and a till sold 3
		# of those 10 before the manager pressed save.
		self.sell_behind_the_form(3)

		response = self.client.patch(
			reverse("product-detail", args=[self.bulb.pk]),
			{"stock_quantity": 12, "stock_quantity_from": 10},
			format="json",
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(Product.objects.get(pk=self.bulb.pk).stock_quantity, 9)

	def test_a_count_the_shelf_cannot_surrender_is_refused(self):
		self.sell_behind_the_form(9)

		response = self.client.patch(
			reverse("product-detail", args=[self.bulb.pk]),
			{"stock_quantity": 0, "stock_quantity_from": 10},
			format="json",
		)

		self.assertEqual(response.status_code, 400)
		self.assertIn("Reload the product", str(response.data["stock_quantity"]))
		self.assertEqual(Product.objects.get(pk=self.bulb.pk).stock_quantity, 1)

	def test_a_sale_takes_stock_from_what_the_shelf_holds(self):
		# The units come off the current number, not the one this request read, so
		# a movement that happened in between is not lost.
		self.sell_behind_the_form(2)

		response = self.client.post(
			reverse("sale-checkout"),
			{
				"customer_name": "Amina",
				"items": [{"product": str(self.bulb.pk), "quantity": 3, "price_sold_at": "250.00"}],
			},
			format="json",
		)

		self.assertEqual(response.status_code, 201, response.data)
		self.assertEqual(Product.objects.get(pk=self.bulb.pk).stock_quantity, 5)
