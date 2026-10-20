from .permissions import get_role


def role_context(request):
    user = getattr(request, "user", None)
    return {"role": get_role(user) if user and user.is_authenticated else None}


def social_context(request):
    from django.conf import settings
    return {"social_providers": [name for name, on in settings.SOCIAL_LOGIN_ENABLED.items() if on]}


def maps_context(request):
    from django.conf import settings
    return {"google_maps_key": settings.GOOGLE_MAPS_API_KEY}
