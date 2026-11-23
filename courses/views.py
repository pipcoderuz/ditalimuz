from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from accounts.permissions import student_required, teacher_required
from community import chat
from community.notify import notify, notify_many
from gamification import services as gamification

from .access import CourseState
from .forms import CompetencyForm, CourseForm, ModuleForm, TopicForm
from .models import Certificate, Competency, Course, Enrollment, Module, Topic, TopicProgress
from assessments.forms import OpenAnswerForm
from assessments.models import Assignment, Attempt, OpenAnswer, Quiz, Submission
from .services import build_outline, course_progress, notify_module_unlocked, touch, try_complete


def _manage(request, course):
    if not course.can_manage(request.user):
        raise PermissionDenied
    return course


def _unique_slug(title):
    base = slugify(title) or "kurs"
    slug, n = base, 2
    while Course.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _auto_order(qs, obj):
    if not obj.order:
        obj.order = (qs.aggregate(m=Max("order"))["m"] or 0) + 1


# ------------------------------------------------------------------ Kurslar
@login_required
def course_list(request):
    user, q = request.user, request.GET.get("q", "").strip()
    courses = Course.objects.select_related("teacher").annotate(student_count=Count("enrollments", distinct=True))
    if user.is_student:
        courses = courses.filter(is_published=True)
    elif user.is_teacher:
        courses = courses.filter(Q(is_published=True) | Q(teacher=user))
    if q:
        courses = courses.filter(Q(title__icontains=q) | Q(description__icontains=q))
    mine = set(Enrollment.objects.filter(student=user).values_list("course_id", flat=True)) if user.is_student else set()
    return render(request, "courses/course_list.html", {"courses": courses, "q": q, "enrolled_ids": mine, "today": timezone.localdate()})


@login_required
def course_detail(request, slug):
    course = get_object_or_404(Course.objects.select_related("teacher"), slug=slug)
    user = request.user
    if not course.is_published and not course.can_manage(user):
        raise PermissionDenied
    state = CourseState(user, course)
    ctx = {
        "course": course, "state": state, "outline": build_outline(state), "manage": course.can_manage(user),
        "pretest": state.pretest, "final_quiz": state.final_quiz, "final_project": state.final_assignment, "today": timezone.localdate(),
        "final_sub": None, "final_access": None, "final_quiz_best": None, "final_quiz_passed": False,
    }
    if user.is_student and state.enrolled:
        done, total, percent = course_progress(user, course)
        ctx.update(progress={"done": done, "total": total, "percent": percent},
                   certificate=Certificate.objects.filter(enrollment=state.enrollment).first())
        if state.pretest:
            ctx["pretest_attempt"] = state.pretest.attempts.filter(student=user).first()
        if state.final_quiz or state.final_assignment:
            ctx["final_access"] = state.final_access()
        if state.final_quiz:
            att = list(state.final_quiz.attempts.filter(student=user))
            ctx["final_quiz_best"] = max((a.score for a in att), default=None)
            ctx["final_quiz_passed"] = state.final_quiz.id in state.passed_quizzes
        if state.final_assignment:
            ctx["final_sub"] = state.final_assignment.submissions.filter(student=user).first()
    if ctx["manage"]:
        ctx["student_count"] = course.enrollments.count()
        ctx["pending_count"] = course.assignments.filter(submissions__status="submitted").distinct().count()
        ctx["responders"] = chat.responders(course)
    return render(request, "courses/course_detail.html", ctx)


@teacher_required
def course_create(request):
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        course = form.save(commit=False)
        course.teacher, course.slug = request.user, _unique_slug(course.title)
        course.save()
        messages.success(request, "Kurs yaratildi. Endi modullar, mavzular va testlar qo'shing.")
        return redirect(course)
    return render(request, "form_page.html", {"form": form, "title": "Yangi kurs"})


@teacher_required
def course_edit(request, slug):
    course = _manage(request, get_object_or_404(Course, slug=slug))
    form = CourseForm(request.POST or None, instance=course)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Kurs yangilandi.")
        return redirect(course)
    return render(request, "form_page.html", {"form": form, "title": f"Tahrirlash: {course.title}"})


@teacher_required
@require_POST
def course_delete(request, slug):
    course = _manage(request, get_object_or_404(Course, slug=slug))
    course.delete()
    messages.info(request, "Kurs o'chirildi.")
    return redirect("courses:course_list")


@student_required
@require_POST
def enroll(request, slug):
    course = get_object_or_404(Course, slug=slug, is_published=True)
    if course.end_date and timezone.localdate() > course.end_date:
        messages.warning(request, "Bu kurs tugagan — yozilib bo'lmaydi.")
        return redirect(course)
    _, created = Enrollment.objects.get_or_create(course=course, student=request.user)
    if created:
        notify(course.teacher, f"{request.user.display_name} «{course.title}» kursiga yozildi.", course.get_absolute_url())
        messages.success(request, "Kursga yozildingiz!" + (" Avval kirish testini topshiring." if course.pretest else ""))
    return redirect(course)


# ------------------------------------------------------------------ Modul
@teacher_required
def module_create(request, slug):
    course = _manage(request, get_object_or_404(Course, slug=slug))
    form = ModuleForm(request.POST or None, course=course, initial={"start_date": course.start_date, "end_date": course.end_date})
    if request.method == "POST" and form.is_valid():
        module = form.save(commit=False)
        module.course = course
        _auto_order(course.modules, module)
        module.save()
        messages.success(request, "Modul qo'shildi.")
        return redirect(course)
    return render(request, "form_page.html", {"form": form, "title": f"{course.title}: yangi modul"})


@teacher_required
def module_edit(request, pk):
    module = get_object_or_404(Module.objects.select_related("course"), pk=pk)
    _manage(request, module.course)
    form = ModuleForm(request.POST or None, instance=module, course=module.course)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Modul yangilandi.")
        return redirect(module.course)
    return render(request, "form_page.html", {"form": form, "title": f"Tahrirlash: {module.title}"})


@teacher_required
@require_POST
def module_delete(request, pk):
    module = get_object_or_404(Module.objects.select_related("course"), pk=pk)
    _manage(request, module.course)
    module.delete()
    messages.info(request, "Modul o'chirildi.")
    return redirect(module.course)


# ------------------------------------------------------------------ Mavzu
@teacher_required
def topic_create(request, pk):
    module = get_object_or_404(Module.objects.select_related("course"), pk=pk)
    course = _manage(request, module.course)
    form = TopicForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        topic = form.save(commit=False)
        topic.module = module
        _auto_order(module.topics, topic)
        topic.save()
        students = [e.student for e in course.enrollments.select_related("student")]
        notify_many(students, f"Yangi dars qo'shildi: «{topic.title}» ({course.title}).", topic.get_absolute_url())
        messages.success(request, "Mavzu qo'shildi.")
        return redirect(course)
    return render(request, "form_page.html", {"form": form, "title": f"{module.title}: yangi mavzu", "multipart": True})


@teacher_required
def topic_edit(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("module__course"), pk=pk)
    _manage(request, topic.module.course)
    form = TopicForm(request.POST or None, request.FILES or None, instance=topic)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Mavzu yangilandi.")
        return redirect(topic)
    return render(request, "form_page.html", {"form": form, "title": f"Tahrirlash: {topic.title}", "multipart": True})


@teacher_required
@require_POST
def topic_delete(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("module__course"), pk=pk)
    _manage(request, topic.module.course)
    topic.delete()
    messages.info(request, "Mavzu o'chirildi.")
    return redirect(topic.module.course)


def _topic_items(state, topic, user):
    """Mavzu ichidagi test / topshiriq / ochiq savollar va talabaning har biri bo'yicha bahosi."""
    items = []
    attempts = {}
    for at in Attempt.objects.filter(student=user, quiz__topic=topic).order_by("submitted_at"):
        attempts.setdefault(at.quiz_id, []).append(at)
    for q in topic.quizzes.all():
        at = attempts.get(q.id, [])
        best = max((a.score for a in at), default=None)
        passed = q.id in state.passed_quizzes
        items.append({"kind": "quiz", "label": "Test", "obj": q, "title": q.title, "url": q.get_absolute_url(), "required": q.required,
                      "score": best, "max": q.max_score, "need": q.pass_score, "passed": passed,
                      "status": "passed" if passed else ("failed" if at else "new"), "note": f"{len(at)} urinish" if at else ""})
    subs = {}
    for sb in Submission.objects.filter(student=user, assignment__topic=topic).order_by("submitted_at"):
        subs[sb.assignment_id] = sb
    for a in topic.assignments.all():
        sb = subs.get(a.id)
        passed = a.id in state.passed_assignments
        status = "passed" if passed else ("pending" if sb and sb.status == "submitted" else ("failed" if sb else "new"))
        items.append({"kind": "assignment", "label": "Topshiriq", "obj": a, "title": a.title, "url": a.get_absolute_url(), "required": a.required,
                      "score": sb.total_score if sb and sb.status == "graded" else None, "max": a.max_score, "need": a.pass_score,
                      "passed": passed, "status": status, "note": "tekshirilmoqda" if status == "pending" else ""})
    answers = {oa.question_id: oa for oa in OpenAnswer.objects.filter(student=user, question__topic=topic)}
    for oq in topic.open_questions.all():
        oa = answers.get(oq.id)
        passed = oq.id in state.passed_questions
        status = "passed" if passed else ("pending" if oa and oa.status == "submitted" else ("failed" if oa else "new"))
        items.append({"kind": "question", "label": "Savol", "obj": oq, "title": None, "url": "", "required": oq.required,
                      "score": oa.score if oa and oa.status == "graded" else None, "max": oq.max_score, "need": oq.pass_score,
                      "passed": passed, "status": status, "answer": oa, "feedback": oa.feedback if oa else "",
                      "form": OpenAnswerForm(initial={"text": oa.text if oa else ""}), "note": ""})
    return items


@login_required
def topic_detail(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("module__course__teacher"), pk=pk)
    course, user = topic.module.course, request.user
    state = CourseState(user, course)
    acc = state.topic_access(topic)
    if not acc:
        messages.warning(request, acc.reason)
        return redirect(course)
    topics = list(topic.module.topics.all())
    idx = next(i for i, t in enumerate(topics) if t.id == topic.id)
    done = topic.id in state.done_topics
    manage = course.can_manage(user)
    ctx = {
        "topic": topic, "course": course, "module": topic.module, "done": done,
        "prev_topic": topics[idx - 1] if idx > 0 else None, "next_topic": topics[idx + 1] if idx + 1 < len(topics) else None,
        "read_only": state.read_only, "manage": manage, "can_complete": False, "blocked_by_items": False, "state": state,
    }
    if user.is_student:
        if state.enrolled and not state.read_only:
            touch(user, course)
        items = _topic_items(state, topic, user)
        ctx["items"] = items
        ctx["items_ok"] = state.topic_items_done(topic)
        ctx["can_complete"] = state.can_act and not done and ctx["items_ok"]
        ctx["blocked_by_items"] = state.can_act and not done and not ctx["items_ok"]
        scored = [i for i in items if i["score"] is not None]
        ctx["grades"] = scored
        if state.enrolled and chat.chat_enabled():
            ctx["chat_room"] = chat.topic_room(topic, user)
            ctx["responders"] = chat.responders(course)
            ctx["responders_label"] = "Javob beruvchilar: " + ", ".join(r.display_name for r in ctx["responders"])
    elif manage:
        ctx["quizzes"] = topic.quizzes.all()
        ctx["assignments"] = topic.assignments.all()
        ctx["open_questions"] = topic.open_questions.all()
        ctx["rooms"] = [(r, chat.room_unread(user, r)) for r in topic.chat_rooms.select_related("student")]
    return render(request, "courses/topic_detail.html", ctx)


@student_required
@require_POST
def topic_complete(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("module__course"), pk=pk)
    course, user = topic.module.course, request.user
    state = CourseState(user, course)
    acc = state.topic_access(topic)
    if not acc or not state.can_act:
        messages.warning(request, acc.reason or "Kurs yakunlangan — faqat ko'rish rejimi.")
        return redirect(course)
    if state.progressive and not state.topic_items_done(topic):
        messages.warning(request, "Mavzuni tugatish uchun avval majburiy test, topshiriq va savollardan o'ting.")
        return redirect(topic)
    _, created = TopicProgress.objects.get_or_create(student=user, topic=topic)
    if created:
        touch(user, course)
        gamification.after_topic_complete(user, topic)
        notify_module_unlocked(user, course, topic.module)
        enrollment = Enrollment.objects.filter(course=course, student=user).first()
        if enrollment:
            try_complete(enrollment)
        messages.success(request, "Mavzu tugatildi.")
    topics = list(topic.module.topics.all())
    idx = next(i for i, t in enumerate(topics) if t.id == topic.id)
    if idx + 1 < len(topics):
        return redirect(topics[idx + 1])
    return redirect(course)


# ------------------------------------------------------------------ Kompetensiyalar
@teacher_required
def competencies(request, slug):
    course = _manage(request, get_object_or_404(Course, slug=slug))
    form = CompetencyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            Competency.objects.create(course=course, name=form.cleaned_data["name"])
            messages.success(request, "Kompetensiya qo'shildi.")
        except IntegrityError:
            messages.warning(request, "Bunday kompetensiya allaqachon bor.")
        return redirect("courses:competencies", slug=course.slug)
    return render(request, "courses/competencies.html", {"course": course, "items": course.competencies.annotate(n=Count("questions")), "form": form})


@teacher_required
@require_POST
def competency_delete(request, pk):
    comp = get_object_or_404(Competency.objects.select_related("course"), pk=pk)
    _manage(request, comp.course)
    comp.delete()
    return redirect("courses:competencies", slug=comp.course.slug)


# ------------------------------------------------------------------ Talabalarim, sertifikat
@teacher_required
def my_students(request):
    enrollments = Enrollment.objects.select_related("student", "course")
    if not request.user.is_platform_admin:
        enrollments = enrollments.filter(course__teacher=request.user)
    enrollments = list(enrollments.order_by("course__title", "student__last_name"))
    course_ids = {e.course_id for e in enrollments}
    totals = {r["module__course"]: r["n"] for r in Topic.objects.filter(module__course__in=course_ids).values("module__course").annotate(n=Count("id"))}
    done = defaultdict(int)
    for r in TopicProgress.objects.filter(topic__module__course__in=course_ids).values("student", "topic__module__course").annotate(n=Count("id")):
        done[(r["student"], r["topic__module__course"])] = r["n"]
    rows = []
    for e in enrollments:
        total = totals.get(e.course_id, 0)
        d = done.get((e.student_id, e.course_id), 0)
        rows.append({"e": e, "percent": round(d / total * 100) if total else 0})
    return render(request, "courses/my_students.html", {"rows": rows})


def certificate(request, code):
    """Ochiq sahifa: sertifikatni ko'rish, chop etish va haqiqiyligini tekshirish."""
    cert = get_object_or_404(Certificate.objects.select_related("enrollment__student", "enrollment__course__teacher"), code=code.upper())
    return render(request, "courses/certificate.html", {"cert": cert, "enrollment": cert.enrollment, "course": cert.enrollment.course})
