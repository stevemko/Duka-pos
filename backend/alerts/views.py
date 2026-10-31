from rest_framework import viewsets

from accounts.services import branch_queryset, user_branch

from .models import StockAlert
from .serializers import StockAlertSerializer


class StockAlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockAlertSerializer

    def get_queryset(self):
        # A branch manager or cashier only sees restock alerts for their own shop.
        queryset = StockAlert.objects.select_related("product", "product__branch")
        return branch_queryset(queryset, user_branch(self.request.user), field="product__branch")
