from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, DepartmentViewSet

router = DefaultRouter()
router.register("departments", DepartmentViewSet)
router.register("categories", CategoryViewSet)
urlpatterns = router.urls
