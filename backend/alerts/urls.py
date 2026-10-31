from rest_framework.routers import DefaultRouter
from .views import StockAlertViewSet

router = DefaultRouter()
router.register(r"alerts", StockAlertViewSet, basename="alert")

urlpatterns = router.urls
