from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from .models import PrivacyPolicyAcceptance

User = get_user_model()
REG = {"email": "new@example.com", "password": "Str0ngPass!word", "first_name": "New", "accept_policy": True}


class AuthTests(TestCase):
    def test_register_login_me_logout(self):
        c = APIClient()
        r = c.post("/api/auth/register/", REG, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["user"]["role"], "citizen")
        self.assertNotIn("password", r.data["user"])
        self.assertTrue(PrivacyPolicyAcceptance.objects.filter(user__email="new@example.com").exists())
        r = c.post("/api/auth/login/", {"email": "NEW@example.com", "password": REG["password"]}, format="json")
        self.assertEqual(r.status_code, 200)
        c.credentials(HTTP_AUTHORIZATION="Token " + r.data["token"])
        self.assertEqual(c.get("/api/auth/me/").data["email"], "new@example.com")
        self.assertEqual(c.patch("/api/auth/me/", {"ward": "Ward 9", "role": "admin"}, format="json").status_code, 200)
        me = c.get("/api/auth/me/").data
        self.assertEqual((me["ward"], me["role"]), ("Ward 9", "citizen"))  # role cannot be self-assigned
        self.assertEqual(c.post("/api/auth/logout/").status_code, 204)
        self.assertEqual(c.get("/api/auth/me/").status_code, 401)

    def test_registration_validation(self):
        c = APIClient()
        self.assertEqual(c.post("/api/auth/register/", {**REG, "accept_policy": False}, format="json").status_code, 400)
        self.assertEqual(c.post("/api/auth/register/", {**REG, "password": "123"}, format="json").status_code, 400)
        c.post("/api/auth/register/", REG, format="json")
        self.assertEqual(c.post("/api/auth/register/", REG, format="json").status_code, 400)

    def test_bad_login_and_unauthenticated(self):
        User.objects.create_user("u@example.com", "u@example.com", "pw12345678")
        c = APIClient()
        self.assertEqual(c.post("/api/auth/login/", {"email": "u@example.com", "password": "wrong"}, format="json").status_code, 400)
        self.assertEqual(c.get("/api/auth/me/").status_code, 401)


from django.test import RequestFactory, override_settings
from allauth.socialaccount.models import SocialAccount, SocialLogin

from .adapters import AccountAdapter, SocialAccountAdapter


class LocationConsentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("l@example.com", "l@example.com", "Str0ngPass!word")
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def test_grant_and_withdraw(self):
        self.assertFalse(self.c.get("/api/auth/me/").data["location_consent"])
        self.assertTrue(self.c.post("/api/auth/location-consent/", {"granted": True}, format="json").data["location_consent"])
        self.assertTrue(self.c.get("/api/auth/me/").data["location_consent"])
        self.user.profile.refresh_from_db()
        self.assertIsNotNone(self.user.profile.location_consent_at)
        self.c.post("/api/auth/location-consent/", {"granted": False}, format="json")
        self.assertFalse(self.c.get("/api/auth/me/").data["location_consent"])

    def test_requires_login_and_is_audited(self):
        self.assertEqual(APIClient().post("/api/auth/location-consent/", {"granted": True}, format="json").status_code, 401)
        self.c.post("/api/auth/location-consent/", {"granted": True}, format="json")
        from complaints.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action="LOCATION_CONSENT", entity_id=self.user.pk).exists())


class SocialLoginTests(TestCase):
    def test_login_page_shows_only_configured_providers(self):
        r = self.client.get("/login/")
        self.assertNotContains(r, "Continue with Facebook")
        self.assertNotContains(r, "Continue with Google")
        with override_settings(SOCIAL_LOGIN_ENABLED={"google": True, "facebook": True, "twitter_oauth2": False}):
            r = self.client.get("/login/")
            self.assertContains(r, "Continue with Facebook")
            self.assertContains(r, 'action="/auth/google/login/"')
            self.assertNotContains(r, "Continue with X")
            self.assertContains(r, 'action="/auth/facebook/login/"')

    def test_local_signup_through_allauth_is_closed(self):
        self.client.post("/auth/signup/", {"email": "x@example.com", "password1": "Str0ngPass!word", "password2": "Str0ngPass!word"})
        self.assertFalse(User.objects.filter(email="x@example.com").exists())
        self.assertFalse(AccountAdapter().is_open_for_signup(RequestFactory().get("/")))

    def test_social_signup_creates_citizen_with_email_username_and_policy_record(self):
        req = RequestFactory().get("/")
        req.session = {}
        sl = SocialLogin(user=User(), account=SocialAccount(provider="facebook", uid="1234"))
        adapter = SocialAccountAdapter()
        adapter.populate_user(req, sl, {"email": "Fb.User@Example.com", "first_name": "Fb"})
        user = adapter.save_user(req, sl)
        user.refresh_from_db()
        self.assertEqual((user.username, user.email), ("fb.user@example.com", "fb.user@example.com"))
        self.assertEqual(user.profile.role, "citizen")
        self.assertFalse(user.has_usable_password())
        self.assertTrue(PrivacyPolicyAcceptance.objects.filter(user=user).exists())

    def test_social_user_without_email_gets_provider_username(self):
        req = RequestFactory().get("/")
        req.session = {}
        sl = SocialLogin(user=User(), account=SocialAccount(provider="twitter_oauth2", uid="99"))
        adapter = SocialAccountAdapter()
        adapter.populate_user(req, sl, {})
        user = adapter.save_user(req, sl)
        self.assertEqual(user.username, "twitter_oauth2_99")
        self.assertEqual(user.profile.role, "citizen")


class MapTileRefererTests(TestCase):
    def test_referrer_policy_lets_openstreetmap_tiles_receive_a_referer(self):
        r = self.client.get("/")
        self.assertEqual(r["Referrer-Policy"], "strict-origin-when-cross-origin")


class GoogleMapsConfigTests(TestCase):
    def test_google_scripts_only_load_when_key_is_set(self):
        self.assertNotContains(self.client.get("/login/"), "maps.googleapis.com")
        with override_settings(GOOGLE_MAPS_API_KEY="TESTKEY123"):
            r = self.client.get("/login/")
        self.assertContains(r, "maps.googleapis.com/maps/api/js?key=TESTKEY123")
        self.assertContains(r, "Leaflet.GoogleMutant.js")
