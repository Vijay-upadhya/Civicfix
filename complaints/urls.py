from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("complaints", views.ComplaintViewSet, basename="complaint")

urlpatterns = router.urls + [
    path("comments/<int:pk>/hide/", views.hide_comment),
    path("images/<int:pk>/hide/", views.hide_image),
    path("audit-logs/", views.audit_logs),
    path("intelligence/classify/", views.classify),
    path("intelligence/check-duplicates/", views.check_duplicates),
    path("intelligence/calculate-priority/", views.calculate_priority),
]
