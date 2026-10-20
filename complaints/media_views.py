from django.http import FileResponse, Http404
from django.contrib.auth.decorators import login_required
from django.conf import settings

from accounts.permissions import ADMIN, get_role

from .models import ComplaintImage
from .services import visible_complaints


@login_required
def protected_media(request, path):
    """Serve complaint images only to users who may see the complaint (hidden images: admins only)."""
    if ".." in path:
        raise Http404
    if path.startswith("complaints/"):
        img = ComplaintImage.objects.filter(image=path).select_related("complaint").first()
        if not img or not visible_complaints(request.user).filter(pk=img.complaint_id).exists():
            raise Http404
        if img.is_hidden and get_role(request.user) != ADMIN:
            raise Http404
    file_path = (settings.MEDIA_ROOT / path).resolve()
    if settings.MEDIA_ROOT.resolve() not in file_path.parents or not file_path.is_file():
        raise Http404
    return FileResponse(open(file_path, "rb"))
