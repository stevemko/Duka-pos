from rest_framework.routers import DefaultRouter
from django.urls import path
from .views import SaleReceiptViewSet, SaleViewSet, mpesa_callback

router = DefaultRouter()
router.register(r"sales", SaleViewSet, basename="sale")
router.register(r"receipts", SaleReceiptViewSet, basename="receipt")

urlpatterns = router.urls
urlpatterns += [path("mpesa/callback/", mpesa_callback, name="mpesa-callback")]
