"""Chat mantig'i: kim kimga yoza oladi (admin belgilagan javobgarlar), xonalar, xabar yuborish, real-time tarqatish."""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import F, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from accounts.models import PlatformSettings, User
from courses.models import Course

from .models import ChatMessage, ChatReadState, ChatRoom

MAX_LEN = 2000


# ------------------------------------------------------------------ Kim kimga yozadi
def responders(course):
    """Kursning chat javobgarlari: admin belgilagan foydalanuvchilar; bo'sh bo'lsa — kurs o'qituvchisi; u ham bo'lmasa — adminlar."""
    chosen = list(course.chat_responders.filter(is_active=True))
    if chosen:
        return chosen
    if course.teacher and course.teacher.is_active:
        return [course.teacher]
    return list(User.objects.filter(role=User.Role.ADMIN, is_active=True))


def responder_course_ids(user):
    qs = Course.objects.filter(Q(chat_responders=user) | Q(chat_responders__isnull=True, teacher=user))
    return set(qs.values_list("id", flat=True))


def is_responder(user, course):
    return user.is_authenticated and any(r.id == user.id for r in responders(course))


def chat_enabled():
    return PlatformSettings.get().chat_enabled


def can_message(a, b):
    """Shaxsiy yozishish: administrator hamma bilan; talaba — o'zi yozilgan kurslarning javobgarlari bilan."""
    if a.pk == b.pk or not (a.is_active and b.is_active) or not chat_enabled():
        return False
    if a.is_platform_admin or b.is_platform_admin:
        return True
    student, other = (a, b) if a.is_student else (b, a)
    if not student.is_student or not other.can_teach:
        return False
    return Course.objects.filter(enrollments__student=student).filter(
        Q(chat_responders=other) | Q(chat_responders__isnull=True, teacher=other)
    ).exists()


def can_access_room(user, room):
    if not user.is_authenticated or not chat_enabled():
        return False
    if user.is_platform_admin:
        return True
    if room.kind == ChatRoom.Kind.DIRECT:
        return user.id in (room.user_a_id, room.user_b_id)
    return user.id == room.student_id or is_responder(user, room.course)


def participant_ids(room):
    if room.kind == ChatRoom.Kind.DIRECT:
        return {room.user_a_id, room.user_b_id}
    return {room.student_id} | {r.id for r in responders(room.course)}


def participant_rooms(user):
    """Foydalanuvchi ishtirokchi bo'lgan xonalar (admin barcha xonani ko'rish huquqiga ega, lekin ishtirokchi emas)."""
    q = Q(user_a=user) | Q(user_b=user) | Q(student=user)
    if user.can_teach:
        ids = responder_course_ids(user)
        if ids:
            q |= Q(kind=ChatRoom.Kind.TOPIC, topic__module__course_id__in=ids)
    return ChatRoom.objects.filter(q).distinct()


def rooms_for_user(user, everything=False):
    if user.is_platform_admin and everything:
        return ChatRoom.objects.all()
    return participant_rooms(user)


# ------------------------------------------------------------------ Xonalar
def direct_room(a, b):
    lo, hi = sorted([a, b], key=lambda u: u.pk)
    room, _ = ChatRoom.objects.get_or_create(kind=ChatRoom.Kind.DIRECT, user_a=lo, user_b=hi)
    return room


def topic_room(topic, student):
    room, _ = ChatRoom.objects.get_or_create(kind=ChatRoom.Kind.TOPIC, topic=topic, student=student)
    return room


def room_title(room, viewer):
    if room.kind == ChatRoom.Kind.DIRECT:
        other = room.user_b if room.user_a_id == viewer.id else room.user_a
        return other.display_name
    who = room.student.display_name if viewer.id != room.student_id else "Javobgarlar"
    return f"{who} · {room.topic.title}"


# ------------------------------------------------------------------ O'qilganlik
def mark_read(user, room):
    last = room.messages.order_by("-id").values_list("id", flat=True).first() or 0
    state, _ = ChatReadState.objects.get_or_create(room=room, user=user)
    if state.last_message_id < last:
        state.last_message_id = last
        state.save(update_fields=["last_message_id"])


def unread_count(user):
    read_upto = Coalesce(
        Subquery(ChatReadState.objects.filter(room=OuterRef("room_id"), user=user).values("last_message_id")[:1]), Value(0)
    )
    return (
        ChatMessage.objects.filter(room__in=participant_rooms(user)).exclude(sender=user)
        .annotate(read_upto=read_upto).filter(id__gt=F("read_upto")).count()
    )


def room_unread(user, room):
    state = ChatReadState.objects.filter(room=room, user=user).first()
    return room.messages.exclude(sender=user).filter(id__gt=state.last_message_id if state else 0).count()


# ------------------------------------------------------------------ Xabarlar
def serialize(msg):
    local = timezone.localtime(msg.created_at)
    return {
        "id": msg.id, "room": msg.room_id, "sender_id": msg.sender_id, "sender_name": msg.sender.display_name,
        "sender_role": msg.sender.role, "body": msg.body, "time": local.strftime("%H:%M"), "date": local.strftime("%d.%m.%Y"),
    }


def push_user(user_id, payload):
    """Foydalanuvchining ochiq sahifalariga real-time hodisa yuboradi (bildirishnoma, yangi xabar belgisi)."""
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(f"user_{user_id}", {"type": "user.push", "payload": payload})
    except Exception:  # real-time yetkazilmasa ham asosiy amal buzilmasin
        pass


def send_message(room, sender, body):
    """Xabarni saqlaydi va real-time tarqatadi (WebSocket va HTTP yo'li uchun umumiy)."""
    if not can_access_room(sender, room):
        raise PermissionDenied("Bu chatga yozish huquqingiz yo'q.")
    body = (body or "").strip()
    if not body:
        raise ValidationError("Xabar bo'sh bo'lishi mumkin emas.")
    if len(body) > MAX_LEN:
        raise ValidationError(f"Xabar {MAX_LEN} belgidan oshmasligi kerak.")
    msg = ChatMessage.objects.create(room=room, sender=sender, body=body)
    mark_read(sender, room)
    data = serialize(msg)
    layer = get_channel_layer()
    if layer is not None:
        try:
            async_to_sync(layer.group_send)(f"chat_{room.id}", {"type": "chat.message", "message": data})
        except Exception:
            pass
    url = reverse("community:chat_room", args=[room.id])
    for uid in participant_ids(room) - {sender.id}:
        push_user(uid, {"kind": "chat", "room": room.id, "sender": sender.display_name, "preview": body[:90], "url": url})
    return msg
