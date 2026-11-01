from rest_framework.routers import DefaultRouter
from django.urls import path
from .customer_views import CustomerViewSet
from .views import SaleReceiptViewSet, SaleViewSet, mpesa_callback

router = DefaultRouter()
router.register(r"sales", SaleViewSet, basename="sale")
router.register(r"receipts", SaleReceiptViewSet, basename="receipt")
router.register(r"customers", CustomerViewSet, basename="customer")

urlpatterns = router.urls
urlpatterns += [path("mpesa/callback/", mpesa_callback, name="mpesa-callback")]
