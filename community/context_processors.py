from .chat import unread_count
from .models import Notification


def counters(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    return {
        "unread_notifications": Notification.objects.filter(user=user, is_read=False).count(),
        "unread_messages": unread_count(user),
    }
