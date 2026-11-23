from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from accounts.permissions import teacher_required
from courses.models import Course

from . import chat
from .forms import PostForm, ThreadForm
from .models import ChatRoom, Notification, Post, Thread
from .notify import notify


# ------------------------------------------------------------------ Forum
@login_required
def thread_list(request):
    threads = Thread.objects.select_related("author", "course").annotate(post_count=Count("posts"))
    course_id, q = request.GET.get("kurs", ""), request.GET.get("q", "").strip()
    if course_id.isdigit():
        threads = threads.filter(course_id=course_id)
    if q:
        threads = threads.filter(Q(title__icontains=q) | Q(body__icontains=q))
    return render(request, "community/thread_list.html", {"threads": threads, "courses": Course.objects.filter(is_published=True), "q": q, "course_id": course_id})


@login_required
def thread_create(request):
    initial = {"course": request.GET["kurs"]} if request.GET.get("kurs", "").isdigit() else {}
    form = ThreadForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        thread = form.save(commit=False)
        thread.author = request.user
        thread.save()
        if thread.course and thread.course.teacher_id and thread.course.teacher_id != request.user.id:
            notify(thread.course.teacher, f"Forumda yangi savol: «{thread.title}» ({thread.course.title})", thread.get_absolute_url())
        return redirect(thread)
    return render(request, "form_page.html", {"form": form, "title": "Yangi savol / mavzu"})


@login_required
def thread_detail(request, pk):
    thread = get_object_or_404(Thread.objects.select_related("author", "course"), pk=pk)
    form = PostForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        post.thread, post.author = thread, request.user
        post.save()
        # Savol egasiga va avval javob yozganlarga bildirishnoma
        people = {thread.author_id} | set(thread.posts.values_list("author_id", flat=True))
        people.discard(request.user.id)
        for user in User.objects.filter(pk__in=people):
            notify(user, f"«{thread.title}» mavzusiga {request.user.display_name} javob yozdi.", thread.get_absolute_url())
        messages.success(request, "Javobingiz qo'shildi.")
        return redirect(thread)
    return render(request, "community/thread_detail.html", {"thread": thread, "posts": thread.posts.select_related("author"), "form": form})


@teacher_required
@require_POST
def thread_delete(request, pk):
    """Moderatsiya: nomaqbul savolni o'qituvchi yoki administrator o'chiradi."""
    thread = get_object_or_404(Thread, pk=pk)
    thread.delete()
    messages.info(request, "Mavzu o'chirildi.")
    return redirect("community:thread_list")


@teacher_required
@require_POST
def post_delete(request, pk):
    post = get_object_or_404(Post, pk=pk)
    thread = post.thread
    post.delete()
    messages.info(request, "Javob o'chirildi.")
    return redirect(thread)


# ------------------------------------------------------------------ Bildirishnomalar
@login_required
def notifications(request):
    items = Notification.objects.filter(user=request.user)[:100]
    return render(request, "community/notifications.html", {"items": items})


@login_required
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    return redirect(n.url if n.url.startswith("/") else "community:notifications")


@login_required
@require_POST
def notifications_read_all(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return redirect("community:notifications")


# ------------------------------------------------------------------ Chat (real-time)
def _contacts(user):
    """Yangi suhbat boshlash mumkin bo'lgan foydalanuvchilar (admin belgilagan javobgarlik asosida)."""
    if user.is_student:
        courses = Course.objects.filter(enrollments__student=user)
        users = {r for c in courses for r in chat.responders(c)}
        return sorted(users, key=lambda u: u.display_name.lower())
    if user.can_teach:
        ids = chat.responder_course_ids(user)
        return list(User.objects.filter(enrollments__course_id__in=ids, is_active=True).distinct().order_by("last_name", "username"))
    return []


@login_required
def inbox(request):
    user = request.user
    everything = user.is_platform_admin and request.GET.get("hammasi") == "1"
    rooms = chat.rooms_for_user(user, everything).select_related("user_a", "user_b", "student", "topic__module__course")
    rows = []
    for room in rooms:
        last = room.messages.select_related("sender").order_by("-id").first()
        if not last and not everything:
            continue
        rows.append({"room": room, "title": chat.room_title(room, user), "last": last, "unread": chat.room_unread(user, room)})
    rows.sort(key=lambda r: r["last"].created_at if r["last"] else r["room"].created_at, reverse=True)
    q = request.GET.get("q", "").strip()
    found = []
    if user.is_platform_admin and q:
        found = list(User.objects.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)).exclude(pk=user.pk)[:15])
    return render(request, "community/inbox.html", {
        "rows": rows, "contacts": _contacts(user), "everything": everything, "q": q, "found": found,
        "chat_on": chat.chat_enabled(),
    })


@login_required
def start_chat(request, user_id):
    other = get_object_or_404(User, pk=user_id)
    if not chat.can_message(request.user, other):
        raise PermissionDenied
    return redirect("community:chat_room", room_id=chat.direct_room(request.user, other).pk)


def _room_or_403(request, room_id):
    room = get_object_or_404(ChatRoom.objects.select_related("user_a", "user_b", "student", "topic__module__course__teacher"), pk=room_id)
    if not chat.can_access_room(request.user, room):
        raise PermissionDenied
    return room


@login_required
def chat_room(request, room_id):
    room = _room_or_403(request, room_id)
    chat.mark_read(request.user, room)
    context = None
    if room.kind == ChatRoom.Kind.TOPIC:
        context = {"topic": room.topic, "course": room.course}
    return render(request, "community/chat_room.html", {"room": room, "title": chat.room_title(room, request.user), "context": context})


@login_required
def chat_history(request, room_id):
    """HTTP orqali tarix (WebSocket ishlamasa zaxira yo'li): ?after=<oxirgi_id>"""
    room = _room_or_403(request, room_id)
    after = request.GET.get("after", "0")
    qs = room.messages.select_related("sender")
    qs = qs.filter(id__gt=int(after)) if after.isdigit() else qs.order_by("-id")[:100][::-1]
    if after.isdigit():
        qs = qs[:200]
    msgs = list(qs)
    chat.mark_read(request.user, room)
    return JsonResponse({"messages": [chat.serialize(m) for m in msgs], "me": request.user.id})


@login_required
@require_POST
def chat_send(request, room_id):
    room = _room_or_403(request, room_id)
    try:
        msg = chat.send_message(room, request.user, request.POST.get("body", ""))
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages)}, status=400)
    return JsonResponse({"message": chat.serialize(msg)})
