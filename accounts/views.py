import uuid
from pathlib import Path

from django.contrib import messages
from django.contrib.auth import login
from django.core.files.storage import default_storage
from django.http import JsonResponse
from PIL import Image, UnidentifiedImageError
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from community.notify import notify

from .forms import LoginForm, PlatformSettingsForm, ProfileForm, RegistrationForm
from .models import PlatformSettings, User
from .permissions import admin_required


def home(request):
    """Mehmonlar uchun landing page (bloklar admin tomonidan boshqariladi; kirish formasi shu yerda), kirganlar uchun panel."""
    user = request.user
    if not user.is_authenticated:
        return render(request, "landing.html")

    from assessments.models import PlagiarismFlag, Submission
    from courses.models import Course, Enrollment
    from courses.services import course_progress
    from gamification.models import UserBadge

    ctx = {}
    if user.is_student:
        enrollments = list(Enrollment.objects.filter(student=user).select_related("course__teacher"))
        for e in enrollments:
            e.done, e.total, e.percent = course_progress(user, e.course)
        enrolled = {e.course_id for e in enrollments}
        ctx.update(
            enrollments=enrollments,
            badges=UserBadge.objects.filter(user=user).select_related("course")[:12],
            suggestions=Course.objects.filter(is_published=True).exclude(pk__in=enrolled)[:4],
        )
    elif user.can_teach:
        courses = Course.objects.all() if user.is_platform_admin else Course.objects.filter(teacher=user)
        ctx["courses"] = courses.annotate(student_count=Count("enrollments", distinct=True))
        ctx["pending_submissions"] = (
            Submission.objects.filter(status="submitted", assignment__course__in=courses)
            .select_related("student", "assignment__course").order_by("-submitted_at")[:8]
        )
        ctx["open_flags"] = PlagiarismFlag.objects.filter(status="open", assignment__course__in=courses).count()
    if user.is_platform_admin:
        ctx["pending_teachers"] = User.objects.filter(role=User.Role.TEACHER, approval_status="pending").count()
    return render(request, "home_dashboard.html", ctx)


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if user.is_teacher:
            for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
                notify(admin, f"Yangi o'qituvchi arizasi: {user.display_name} (@{user.username}) tasdiq kutmoqda.", reverse("accounts:admin_panel"))
            messages.success(request, "Arizangiz qabul qilindi. Administrator tasdiqlagach tizimga kira olasiz.")
            return redirect("accounts:login")
        login(request, user)
        messages.success(request, "Ro'yxatdan muvaffaqiyatli o'tdingiz!")
        return redirect("home")
    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profil yangilandi.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile_edit.html", {"form": form})


@login_required
def profile_public(request, username):
    from courses.models import Certificate
    from gamification.models import UserBadge

    person = get_object_or_404(User, username=username, is_active=True, approval_status="approved")
    from community import chat as chat_service
    certs = Certificate.objects.filter(enrollment__student=person).select_related("enrollment__course")
    return render(request, "accounts/profile_public.html", {
        "person": person, "badges": UserBadge.objects.filter(user=person).select_related("course"), "certs": certs,
        "own": person.pk == request.user.pk,
        "chat_allowed": chat_service.chat_enabled() and chat_service.can_message(request.user, person),
    })


# ------------------------------------------------------------------ Administrator paneli
@admin_required
def admin_panel(request):
    from assessments.models import Submission
    from courses.models import Course, Enrollment

    users = User.objects.all().order_by("-date_joined")
    role, status, q = request.GET.get("rol", ""), request.GET.get("holat", ""), request.GET.get("q", "").strip()
    if role in User.Role.values:
        users = users.filter(role=role)
    if status == "blocked":
        users = users.filter(is_active=False)
    elif status in User.Approval.values:
        users = users.filter(approval_status=status)
    if q:
        users = users.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    return render(request, "accounts/admin_panel.html", {
        "settings_form": PlatformSettingsForm(instance=PlatformSettings.get()),
        "pending": User.objects.filter(role=User.Role.TEACHER, approval_status=User.Approval.PENDING).order_by("date_joined"),
        "users": users[:200], "role": role, "status": status, "q": q,
        "stats": {
            "students": User.objects.filter(role=User.Role.STUDENT).count(),
            "teachers": User.objects.filter(role=User.Role.TEACHER, approval_status="approved").count(),
            "courses": Course.objects.count(), "enrollments": Enrollment.objects.count(),
            "completed": Enrollment.objects.filter(status="completed").count(),
            "submissions": Submission.objects.count(),
        },
    })


@admin_required
@require_POST
def settings_update(request):
    form = PlatformSettingsForm(request.POST, instance=PlatformSettings.get())
    if form.is_valid():
        form.save()
        state = "YOQILGAN" if form.cleaned_data["progressive_learning"] else "O'CHIRILGAN"
        messages.success(request, f"Sozlamalar saqlandi. Progressiv o'qitish: {state}.")
    else:
        messages.error(request, "Sozlamalarni saqlab bo'lmadi: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("accounts:admin_panel")


@admin_required
@require_POST
def user_action(request, pk, action):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, "O'zingiz ustida bu amalni bajarib bo'lmaydi.")
        return redirect("accounts:admin_panel")
    name = target.display_name
    if action == "approve":
        target.approval_status = User.Approval.APPROVED
        target.save(update_fields=["approval_status"])
        notify(target, "Profilingiz administrator tomonidan tasdiqlandi. Endi kurslar yaratishingiz mumkin.", "/")
        messages.success(request, f"{name} tasdiqlandi.")
    elif action == "reject":
        target.approval_status = User.Approval.REJECTED
        target.save(update_fields=["approval_status"])
        messages.info(request, f"{name} arizasi rad etildi.")
    elif action == "block":
        target.is_active = False
        target.save(update_fields=["is_active"])
        messages.info(request, f"{name} bloklandi.")
    elif action == "unblock":
        target.is_active = True
        target.save(update_fields=["is_active"])
        messages.success(request, f"{name} blokdan chiqarildi.")
    elif action == "delete":
        target.delete()
        messages.info(request, f"{name} tizimdan o'chirildi.")
    else:
        messages.error(request, "Noma'lum amal.")
    return redirect(request.POST.get("next") or "accounts:admin_panel")


# ------------------------------------------------------------------ Rasm yuklash (rich text editor uchun)
MAX_IMAGE_MB = 5
ALLOWED_FORMATS = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}


@login_required
@require_POST
def upload_image(request):
    f = request.FILES.get("image")
    if not f:
        return JsonResponse({"error": "Rasm tanlanmagan."}, status=400)
    if f.size > MAX_IMAGE_MB * 1024 * 1024:
        return JsonResponse({"error": f"Rasm hajmi {MAX_IMAGE_MB} MB dan oshmasligi kerak."}, status=400)
    try:
        img = Image.open(f)
        fmt = img.format
        img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        return JsonResponse({"error": "Bu rasm fayli emas."}, status=400)
    if fmt not in ALLOWED_FORMATS:
        return JsonResponse({"error": "Faqat JPG, PNG, GIF yoki WEBP rasmlari qabul qilinadi."}, status=400)
    f.seek(0)
    name = default_storage.save(f"uploads/rich/{uuid.uuid4().hex}{ALLOWED_FORMATS[fmt]}", f)  # kengaytma formatdan olinadi
    return JsonResponse({"url": default_storage.url(name)})


# ------------------------------------------------------------------ Chat yo'naltirish va dizayn markazi (admin)
@admin_required
def chat_routing(request):
    """Talabalarning kurs bo'yicha chat xabarlari kimga borishini admin belgilaydi."""
    from courses.models import Course

    staff = User.objects.filter(role__in=[User.Role.TEACHER, User.Role.ADMIN], is_active=True, approval_status="approved").order_by("role", "last_name", "username")
    rows = []
    for course in Course.objects.select_related("teacher").prefetch_related("chat_responders"):
        rows.append({"course": course, "selected": {u.id for u in course.chat_responders.all()}})
    return render(request, "accounts/chat_routing.html", {"rows": rows, "staff": staff})


@admin_required
@require_POST
def chat_routing_update(request, course_id):
    from courses.models import Course

    course = get_object_or_404(Course, pk=course_id)
    ids = [int(i) for i in request.POST.getlist("responders") if i.isdigit()]
    allowed = User.objects.filter(pk__in=ids, role__in=[User.Role.TEACHER, User.Role.ADMIN], is_active=True)
    course.chat_responders.set(allowed)
    messages.success(request, f"«{course.title}» chat javobgarlari yangilandi." if allowed else
                     f"«{course.title}»: javobgar tanlanmadi — xabarlar kurs o'qituvchisiga boradi.")
    return redirect("accounts:chat_routing")


@admin_required
def design_center(request):
    from design.models import FormDefinition, NavItem, SiteBlock

    return render(request, "accounts/design_center.html", {
        "counts": {"nav": NavItem.objects.count(), "blocks": SiteBlock.objects.count(),
                   "forms": FormDefinition.objects.filter(purpose="custom").count(),
                   "extra_fields": FormDefinition.objects.exclude(purpose="custom").count()},
    })
