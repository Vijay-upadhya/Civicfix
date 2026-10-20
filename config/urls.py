from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from complaints import page_views as p
from complaints.media_views import protected_media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("auth/", include("allauth.urls")),  # social login: /auth/facebook/login/, /auth/twitter_oauth2/login/
    path("api/", include("accounts.urls")),
    path("api/", include("complaints.urls")),
    path("api/", include("departments.urls")),
    path("api/", include("analytics.urls")),
    path("api/", include("notifications.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("media/<path:path>", protected_media, name="media"),
    # pages
    path("", p.landing, name="landing"),
    path("explore/", p.explore, name="explore"),
    path("how-it-works/", p.how_it_works, name="how"),
    path("about/", p.static_page("about.html"), name="about"),
    path("privacy/", p.static_page("privacy.html"), name="privacy"),
    path("terms/", p.static_page("terms.html"), name="terms"),
    path("data-deletion/", p.static_page("data_deletion.html"), name="data_deletion"),
    path("login/", p.login_page, name="login"),
    path("register/", p.register_page, name="register"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", p.dashboard, name="dashboard"),
    path("report/", p.report, name="report"),
    path("complaints/<int:pk>/", p.complaint_detail, name="complaint_detail"),
    path("notifications/", p.notifications_page, name="notifications"),
    path("profile/", p.profile_page, name="profile"),
]
