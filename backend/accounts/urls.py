from rest_framework.routers import DefaultRouter

from .views import BranchViewSet, UserViewSet

router = DefaultRouter()
router.register(r"users", UserViewSet, basename="user")
router.register(r"branches", BranchViewSet, basename="branch")

urlpatterns = router.urls
