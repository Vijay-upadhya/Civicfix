from django.urls import path

from . import views

urlpatterns = [
    path("analytics/overview/", views.overview),
    path("analytics/by-category/", views.by_category),
    path("analytics/by-ward/", views.by_ward),
    path("analytics/by-department/", views.by_department),
    path("analytics/resolution-time/", views.resolution_time),
    path("analytics/overdue/", views.overdue),
    path("analytics/sla-compliance/", views.sla_compliance),
    path("analytics/prediction-accuracy/", views.prediction_accuracy),
    path("public/stats/", views.public_stats),
]
