from rest_framework import generics, serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    complaint_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "complaint_id", "notification_type", "title", "message", "is_read", "created_at"]


class NotificationList(generics.ListAPIView):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        if self.request.query_params.get("unread") in ("1", "true"):
            qs = qs.filter(is_read=False)
        return qs


@api_view(["PATCH"])
def mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    return Response(NotificationSerializer(n).data)


@api_view(["POST"])
def mark_all_read(request):
    count = Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return Response({"marked": count})


@api_view(["GET"])
def unread_count(request):
    return Response({"unread": Notification.objects.filter(recipient=request.user, is_read=False).count()})
