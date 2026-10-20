"""Allauth adapters: social login creates citizens only; local sign-up stays on our own API."""
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings

from .models import PrivacyPolicyAcceptance


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False  # registration happens through /register/ (our API), not allauth's own form


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        return True

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        email = (data.get("email") or "").strip().lower()
        user.email = email
        # Our email/password login uses the email as username; keep social users consistent.
        user.username = email or f"{sociallogin.account.provider}_{sociallogin.account.uid}"
        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        email = (user.email or "").lower()
        wanted = email or f"{sociallogin.account.provider}_{sociallogin.account.uid}"
        if user.username != wanted:
            user.username = wanted
            user.save(update_fields=["username"])
        # New accounts are always citizens (the profile default); roles change only via an administrator.
        fwd = request.META.get("HTTP_X_FORWARDED_FOR") if request else None
        ip = (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) if request else None
        PrivacyPolicyAcceptance.objects.create(user=user, policy_version=settings.POLICY_VERSION, ip_address=ip or None)
        return user
