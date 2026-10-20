from django.urls import path

from . import views

urlpatterns = [
    path("notifications/", views.NotificationList.as_view()),
    path("notifications/unread-count/", views.unread_count),
    path("notifications/mark-all-read/", views.mark_all_read),
    path("notifications/<int:pk>/read/", views.mark_read),
]
