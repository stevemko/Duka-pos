import uuid

from django.db import models
from django.db.models import Q


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    branch = models.ForeignKey(
        "accounts.Branch",
        on_delete=models.PROTECT,
        related_name="products",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, blank=True, null=True)
    category = models.CharField(max_length=100, blank=True)
    image = models.FileField(upload_to="products/", blank=True, null=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    stock_quantity = models.PositiveIntegerField(default=0)
    reorder_threshold = models.PositiveIntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["branch", "name"], name="product_branch_name_idx"),
            models.Index(fields=["branch", "category"], name="product_branch_category_idx"),
            models.Index(fields=["branch", "stock_quantity"], name="product_branch_stock_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "sku"],
                condition=Q(sku__isnull=False),
                name="unique_sku_per_branch",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def needs_restock(self):
        return self.stock_quantity <= self.reorder_threshold

    @property
    def branch_label(self):
        return self.branch.name if self.branch else "Main shop"
