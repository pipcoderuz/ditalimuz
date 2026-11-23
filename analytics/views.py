import csv
from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from accounts.models import User
from courses.models import Course, Enrollment

from . import services


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _filters(request):
    course = request.GET.get("kurs", "")
    return {
        "course_id": int(course) if course.isdigit() else None,
        "date_from": _parse_date(request.GET.get("dan")),
        "date_to": _parse_date(request.GET.get("gacha")),
        "state": request.GET.get("holat") or None,
    }


@login_required
def overview(request):
    """«Statistika» menyusi: admin — platforma bo'yicha, o'qituvchi — o'z kurslari, talaba — shaxsiy."""
    f = _filters(request)
    data = services.overview(request.user, **f)
    series = data["series"]
    chart = {
        "months": series["months"],
        "enrolled": series["enrolled"], "started": series["started"], "completed": series["completed"],
        "registered": series.get("registered"),
        "courses": {"labels": [c["course"].title for c in data["per_course"][:10]], "enrolled": [c["enrolled"] for c in data["per_course"][:10]],
                    "completed": [c["completed"] for c in data["per_course"][:10]]},
    }
    return render(request, "analytics/overview.html", {**data, "chart": chart, "f": request.GET})


def _csv_safe(value):
    """CSV injection'dan himoya: =, +, -, @ bilan boshlangan matn Excel'da formula sifatida bajarilmasligi uchun."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@login_required
def overview_csv(request):
    if not request.user.can_teach:
        raise PermissionDenied
    f = _filters(request)
    data = services.overview(request.user, **f)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="talabalar_statistikasi.csv"'
    response.write("\ufeff")
    w = csv.writer(response)
    w.writerow(["Talaba", "Kurs", "Yozilgan sana", "Boshlagan sana", "Oxirgi faoliyat", "Progress %", "O'rtacha ball %", "Davomiylik (kun)", "Holat"])
    names = {"completed": "Yakunlagan", "learning": "O'qimoqda", "not_started": "Boshlamagan"}
    for r in data["rows"]:
        e = r["e"]
        fmt = lambda d: d.strftime("%Y-%m-%d") if d else ""
        w.writerow([_csv_safe(c) for c in (
            e.student.display_name, e.course.title, fmt(e.enrolled_at), fmt(e.started_at), fmt(e.last_activity_at),
            r["progress"], r["score"] if r["score"] is not None else "", r["days"] if r["days"] is not None else "", names[r["state"]])])
    return response


@login_required
def student_stats(request, slug, student_id=None):
    course = get_object_or_404(Course, slug=slug)
    user = request.user
    if student_id and user.can_teach:
        if not course.can_manage(user):
            raise PermissionDenied
        student = get_object_or_404(User, pk=student_id, role=User.Role.STUDENT)
    else:
        if not user.is_student:
            raise PermissionDenied
        student = user
    stats = services.student_stats(student, course)
    if stats is None:
        raise PermissionDenied
    return render(request, "analytics/student_stats.html", {"course": course, "student": student, "s": stats})


@login_required
def course_analytics(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not course.can_manage(request.user):
        raise PermissionDenied
    data = services.dropoff(course)
    chart = {
        "quizzes": {"labels": [q["quiz"].title for q in data["quizzes"]], "values": [q["fail_rate"] for q in data["quizzes"]]},
        "funnel": {"labels": [f["topic"].title[:24] for f in data["funnel"]], "values": [f["percent"] for f in data["funnel"]]},
    }
    return render(request, "analytics/course_analytics.html", {"course": course, "d": data, "chart": chart})


@login_required
def growth(request, slug, student_id=None):
    course = get_object_or_404(Course, slug=slug)
    user = request.user
    if student_id and user.can_teach:
        if not course.can_manage(user):
            raise PermissionDenied
        student = get_object_or_404(User, pk=student_id, role=User.Role.STUDENT)
    else:
        student = user
        if not user.is_student:
            raise PermissionDenied
    if not Enrollment.objects.filter(course=course, student=student).exists():
        raise PermissionDenied
    g = services.competency_growth(student, course)
    chart = {"labels": [r["name"] for r in g["rows"]], "pre": [r["pre"] or 0 for r in g["rows"]], "final": [r["final"] or 0 for r in g["rows"]]}
    return render(request, "analytics/growth.html", {"course": course, "student": student, "g": g, "chart": chart})
