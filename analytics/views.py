from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.permissions import IsStaffRole

from . import services


def _make(fn):
    @api_view(["GET"])
    @permission_classes([IsStaffRole])
    def view(request):
        return Response(fn(request.user, request.query_params))
    view.__name__ = fn.__name__
    return view


overview = _make(services.overview)
by_category = _make(services.by_category)
by_ward = _make(services.by_ward)
by_department = _make(services.by_department)
resolution_time = _make(services.resolution_time)
overdue = _make(services.overdue)
sla_compliance = _make(services.sla_compliance)


@api_view(["GET"])
@permission_classes([IsStaffRole])
def prediction_accuracy(request):
    return Response(services.prediction_accuracy(services.scoped_queryset(request.user, request.query_params)))


@api_view(["GET"])
@permission_classes([AllowAny])
def public_stats(request):
    return Response(services.public_stats())
