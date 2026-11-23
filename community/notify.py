"""Sayt ichidagi bildirishnomalar: bazaga yoziladi va foydalanuvchining ochiq sahifasiga real-time yuboriladi."""
from .models import Notification


def _push(user_id, text, url):
    from .chat import push_user

    push_user(user_id, {"kind": "notification", "text": text, "url": url})


def notify(user, text, url=""):
    if user is None:
        return None
    n = Notification.objects.create(user=user, text=text[:255], url=url)
    _push(user.id, n.text, url)
    return n


def notify_many(users, text, url=""):
    users = list(users)
    Notification.objects.bulk_create([Notification(user=u, text=text[:255], url=url) for u in users])
    for u in users:
        _push(u.id, text[:255], url)
