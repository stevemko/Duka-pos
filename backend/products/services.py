from django.db.models import F
from django.utils import timezone

from products.models import Product


def move_stock(product, delta):
    """Move stock by a number of units, checked and written in one statement.

    Returns the product with its stock re-read, or None when the shelf no longer
    holds what the movement asks for. A read-then-write would let two tills each
    look at the last unit, agree there is enough, and both sell it.
    """
    if delta == 0:
        return product

    queryset = Product.objects.filter(pk=product.pk)
    if delta < 0:
        queryset = queryset.filter(stock_quantity__gte=-delta)

    moved = queryset.update(stock_quantity=F("stock_quantity") + delta, updated_at=timezone.now())
    if not moved:
        return None

    product.refresh_from_db()
    return product
