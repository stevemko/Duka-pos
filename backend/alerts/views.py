from rest_framework import viewsets

from accounts.services import branch_queryset, main_branch, sees_all_branches, user_branch

from .models import StockAlert
from .serializers import StockAlertSerializer


class StockAlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StockAlertSerializer

    def get_queryset(self):
        # A branch manager or cashier only sees restock alerts for their own shop.
        # A cashier who has not been given a branch belongs to the main shop, not
        # to every shop: only managers with no branch see the whole chain.
        user = self.request.user
        branch = user_branch(user)
        if branch is None and not sees_all_branches(user):
            branch = main_branch()
        queryset = StockAlert.objects.select_related("product", "product__branch")
        return branch_queryset(queryset, branch, field="product__branch")
