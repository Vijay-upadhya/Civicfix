from django.contrib import admin
from .models import PrivacyPolicyAcceptance, UserProfile

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "department", "ward", "is_verified")
    list_filter = ("role", "department")
    search_fields = ("user__email", "user__first_name")

admin.site.register(PrivacyPolicyAcceptance)
