import hashlib
import time
from collections import Counter, defaultdict
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import student_required, teacher_required
from accounts.richtext import highlight_lines
from community.notify import notify
from courses.access import CourseState
from courses.models import Course, Enrollment, Module, Topic
from courses.services import notify_module_unlocked, touch, try_complete
from gamification import services as gamification

from . import codeutils
from .forms import (
    AssignmentForm, ChoiceFormSet, CriteriaFormSet, GradeForm, OpenAnswerForm, OpenGradeForm, OpenQuestionForm, QuestionForm,
    QuizForm, ReviewCommentForm, SubmissionForm,
)
from .github import fetch_snapshot, parse_repo
from .grading import grade_quiz
from .models import (
    Assignment, Attempt, OpenAnswer, OpenQuestion, PlagiarismFlag, Question, Quiz, ReviewComment, Submission, SubmissionScore,
)
from .services import process_submission


DOC_EXTENSIONS = (".md", ".txt", ".json", ".yml", ".yaml", ".xml")


def _default_review_file(paths):
    """Code review'da birinchi ochiladigan fayl: hujjat/sozlama emas, haqiqiy manba kodi (bo'lsa)."""
    for path in paths:
        if not path.lower().endswith(DOC_EXTENSIONS):
            return path
    return paths[0] if paths else ""


def _manage_course(request, course):
    if not course.can_manage(request.user):
        raise PermissionDenied
    return course


def _auto_order(qs, obj):
    if not obj.order:
        obj.order = (qs.aggregate(m=Max("order"))["m"] or 0) + 1


def _after_pass(student, course, module=None):
    """Biror narsadan o'tilgach: keyingi modul ochilganini bildirish va kurs yakunlanganini tekshirish."""
    if module is not None:
        notify_module_unlocked(student, course, module)
    enrollment = Enrollment.objects.filter(course=course, student=student).first()
    if enrollment:
        try_complete(enrollment)


# =============================================================== TESTLAR (boshqaruv)
@teacher_required
def quiz_create(request, slug):
    """?tur=pretest|final|module|topic  &modul=<id> (modul testi)  &mavzu=<id> (mavzu testi)"""
    course = _manage_course(request, get_object_or_404(Course, slug=slug))
    kind = request.GET.get("tur") or ("pretest" if request.GET.get("pretest") else "module")
    if kind not in Quiz.Kind.values:
        kind = Quiz.Kind.MODULE
    module = topic = None
    if kind == Quiz.Kind.MODULE:
        module = get_object_or_404(Module, pk=request.GET.get("modul"), course=course)
    elif kind == Quiz.Kind.TOPIC:
        topic = get_object_or_404(Topic, pk=request.GET.get("mavzu"), module__course=course)
    form = QuizForm(request.POST or None, course=course, kind=kind, module=module, topic=topic)
    if request.method == "POST" and form.is_valid():
        quiz = form.save()
        _auto_order(course.quizzes, quiz)
        quiz.save()
        messages.success(request, "Test yaratildi. Endi savollar qo'shing.")
        return redirect(quiz)
    label = dict(Quiz.Kind.choices)[kind]
    return render(request, "form_page.html", {"form": form, "title": f"{label}: yangi", "subtitle": course.title})


@teacher_required
def quiz_edit(request, pk):
    quiz = get_object_or_404(Quiz.objects.select_related("course"), pk=pk)
    _manage_course(request, quiz.course)
    form = QuizForm(request.POST or None, instance=quiz, course=quiz.course)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Test yangilandi.")
        return redirect(quiz)
    return render(request, "form_page.html", {"form": form, "title": f"Tahrirlash: {quiz.title}"})


@teacher_required
@require_POST
def quiz_delete(request, pk):
    quiz = get_object_or_404(Quiz.objects.select_related("course"), pk=pk)
    _manage_course(request, quiz.course)
    quiz.delete()
    messages.info(request, "Test o'chirildi.")
    return redirect(quiz.course)


def _question_view(request, quiz, question=None):
    course = quiz.course
    form = QuestionForm(request.POST or None, instance=question, course=course)
    formset = ChoiceFormSet(request.POST or None, instance=question if question else Question(quiz=quiz))
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        if form.cleaned_data["kind"] == Question.Kind.SINGLE and formset.correct_count() != 1:
            form.add_error("kind", "«Bitta to'g'ri javob» turida aynan bitta variant to'g'ri bo'lishi kerak.")
        else:
            with transaction.atomic():
                q = form.save(commit=False)
                q.quiz = quiz
                _auto_order(quiz.questions, q)
                q.save()
                formset.instance = q
                formset.save()
            messages.success(request, "Savol saqlandi.")
            return redirect(quiz)
    return render(request, "assessments/question_form.html", {
        "form": form, "formset": formset, "quiz": quiz, "title": "Savolni tahrirlash" if question else "Yangi savol",
    })


@teacher_required
def question_create(request, pk):
    quiz = get_object_or_404(Quiz.objects.select_related("course"), pk=pk)
    _manage_course(request, quiz.course)
    return _question_view(request, quiz)


@teacher_required
def question_edit(request, pk):
    question = get_object_or_404(Question.objects.select_related("quiz__course"), pk=pk)
    _manage_course(request, question.quiz.course)
    return _question_view(request, question.quiz, question)


@teacher_required
@require_POST
def question_delete(request, pk):
    question = get_object_or_404(Question.objects.select_related("quiz__course"), pk=pk)
    _manage_course(request, question.quiz.course)
    quiz = question.quiz
    question.delete()
    messages.info(request, "Savol o'chirildi.")
    return redirect(quiz)


# =============================================================== TESTLAR (talaba)
@login_required
def quiz_detail(request, pk):
    quiz = get_object_or_404(Quiz.objects.select_related("course", "module", "topic"), pk=pk)
    course, user = quiz.course, request.user
    if user.can_teach:
        _manage_course(request, course)
        questions = quiz.questions.prefetch_related("choices").select_related("competency")
        return render(request, "assessments/quiz_detail.html", {"quiz": quiz, "course": course, "questions": questions, "manage": True})

    state = CourseState(user, course)
    acc = state.quiz_access(quiz)
    if not acc:
        messages.warning(request, acc.reason)
        return redirect(course)
    attempts = list(quiz.attempts.filter(student=user))
    left = None if not quiz.max_attempts else max(0, quiz.max_attempts - len(attempts))
    return render(request, "assessments/quiz_detail.html", {
        "quiz": quiz, "course": course, "attempts": attempts, "left": left, "state": state, "manage": False,
        "best": max((a.score for a in attempts), default=None),
        "can_take": state.can_act and (left is None or left > 0) and quiz.questions.exists(),
    })


@student_required
def quiz_take(request, pk):
    quiz = get_object_or_404(Quiz.objects.select_related("course", "module", "topic"), pk=pk)
    course, user = quiz.course, request.user
    state = CourseState(user, course)
    acc = state.quiz_access(quiz)
    if not acc:
        messages.warning(request, acc.reason)
        return redirect(course)
    if not state.can_act:
        messages.warning(request, "Kurs yakunlangan: testlarni faqat ko'rish rejimida ochish mumkin.")
        return redirect(quiz)
    used = quiz.attempts.filter(student=user).count()
    if quiz.max_attempts and used >= quiz.max_attempts:
        messages.warning(request, "Urinishlar tugagan.")
        return redirect(quiz)
    questions = list(quiz.questions.prefetch_related("choices"))
    if not questions:
        messages.warning(request, "Bu testda hali savollar yo'q.")
        return redirect(quiz)

    if request.method == "POST":
        try:
            payload = signing.loads(request.POST.get("token", ""), salt="quiz", max_age=60 * 60 * 6)
            valid = payload["q"] == quiz.pk and payload["u"] == user.pk
            started = datetime.fromtimestamp(payload["t"], tz=timezone.get_current_timezone()) if valid else timezone.now()
        except (signing.BadSignature, KeyError):
            started = timezone.now()
        if quiz.time_limit_minutes and (timezone.now() - started).total_seconds() > quiz.time_limit_minutes * 60 + 120:
            messages.error(request, "Vaqt tugagan. Testni qaytadan boshlang (bu urinish hisoblanmadi).")
            return redirect("assessments:quiz_take", pk=quiz.pk)
        attempt = grade_quiz(quiz, user, request.POST, started)
        touch(user, course)
        gamification.after_attempt(attempt)
        if attempt.passed and quiz.kind != Quiz.Kind.PRETEST:
            _after_pass(user, course, quiz.module)
        return redirect(attempt)

    touch(user, course)
    token = signing.dumps({"t": time.time(), "q": quiz.pk, "u": user.pk}, salt="quiz")
    return render(request, "assessments/quiz_take.html", {"quiz": quiz, "questions": questions, "token": token, "course": course})


@login_required
def attempt_result(request, pk):
    attempt = get_object_or_404(Attempt.objects.select_related("quiz__course", "student"), pk=pk)
    quiz, user = attempt.quiz, request.user
    manager = quiz.course.can_manage(user)
    if attempt.student_id != user.id and not manager:
        raise PermissionDenied
    used = quiz.attempts.filter(student=attempt.student).count()
    exhausted = bool(quiz.max_attempts) and used >= quiz.max_attempts
    is_pretest = quiz.kind == Quiz.Kind.PRETEST
    reveal = manager or (not is_pretest and (attempt.passed or exhausted))
    answers = attempt.answers.select_related("question__competency").prefetch_related("question__choices")
    return render(request, "assessments/attempt_result.html", {
        "attempt": attempt, "quiz": quiz, "answers": answers, "reveal": reveal, "show_marks": not is_pretest or manager,
        "exhausted": exhausted, "course": quiz.course,
    })


# =============================================================== TOPSHIRIQLAR (boshqaruv)
def _assignment_view(request, course, assignment=None, kind=None, module=None, topic=None):
    form = AssignmentForm(request.POST or None, instance=assignment, kind=kind)
    formset = CriteriaFormSet(request.POST or None, instance=assignment or Assignment())
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        total = formset.total()
        if form.cleaned_data["pass_score"] > total:
            form.add_error("pass_score", f"O'tish bali rubrika yig'indisidan ({total}) katta bo'lishi mumkin emas.")
        else:
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.course = course
                if assignment is None:
                    obj.kind, obj.module, obj.topic = kind, module, topic
                    if kind == Assignment.Kind.FINAL:
                        obj.required = True
                obj.max_score = total
                obj.save()
                formset.instance = obj
                formset.save()
                obj.recalc_max_score()
            messages.success(request, "Topshiriq saqlandi.")
            return redirect(obj)
    label = dict(Assignment.Kind.choices).get(kind or (assignment.kind if assignment else ""), "Topshiriq")
    return render(request, "assessments/assignment_form.html", {
        "form": form, "formset": formset, "course": course, "title": "Topshiriqni tahrirlash" if assignment else f"{label}: yangi",
    })


@teacher_required
def assignment_create(request, slug):
    """?tur=final|module|topic  &modul=<id>  &mavzu=<id>   (eski ?final=1 ham ishlaydi)"""
    course = _manage_course(request, get_object_or_404(Course, slug=slug))
    kind = request.GET.get("tur") or ("final" if request.GET.get("final") == "1" else "topic" if request.GET.get("mavzu") else "module")
    if kind == Assignment.Kind.FINAL:
        existing = course.final_assignment
        if existing:
            messages.info(request, "Bu kursda yakuniy loyiha allaqachon bor.")
            return redirect(existing)
        return _assignment_view(request, course, kind=kind)
    if kind == Assignment.Kind.TOPIC:
        topic = get_object_or_404(Topic, pk=request.GET.get("mavzu"), module__course=course)
        return _assignment_view(request, course, kind=kind, topic=topic)
    module = get_object_or_404(Module, pk=request.GET.get("modul"), course=course)
    return _assignment_view(request, course, kind=Assignment.Kind.MODULE, module=module)


@teacher_required
def assignment_edit(request, pk):
    assignment = get_object_or_404(Assignment.objects.select_related("course"), pk=pk)
    _manage_course(request, assignment.course)
    return _assignment_view(request, assignment.course, assignment=assignment)


@teacher_required
@require_POST
def assignment_delete(request, pk):
    assignment = get_object_or_404(Assignment.objects.select_related("course"), pk=pk)
    _manage_course(request, assignment.course)
    assignment.delete()
    messages.info(request, "Topshiriq o'chirildi.")
    return redirect(assignment.course)


# =============================================================== TOPSHIRIQLAR (talaba)
def _create_submission(request, assignment, form):
    sub = form.save(commit=False)
    sub.assignment, sub.student = assignment, request.user
    due = assignment.effective_due
    sub.is_late = bool(due and timezone.localdate() > due)
    if sub.method == Submission.Method.ZIP:
        f = form.cleaned_data["zip_file"]
        sub.zip_size, sub.zip_sha256 = f.size, codeutils.sha256_of(f)
    else:
        data, error = fetch_snapshot(sub.github_url)
        if data:
            repo = parse_repo(sub.github_url)[1]
            sub.zip_file.save(f"{repo}.zip", ContentFile(data), save=False)
            sub.zip_size, sub.zip_sha256 = len(data), hashlib.sha256(data).hexdigest()
        else:
            sub.snapshot_error = error
    sub.save()
    touch(request.user, assignment.course)
    process_submission(sub)
    return sub


@login_required
def assignment_detail(request, pk):
    assignment = get_object_or_404(Assignment.objects.select_related("course", "module", "topic"), pk=pk)
    course, user = assignment.course, request.user
    criteria = assignment.criteria.all()

    if user.can_teach:
        _manage_course(request, course)
        subs = assignment.submissions.select_related("student").order_by("-submitted_at")
        latest = {}
        for s in subs:
            latest.setdefault(s.student_id, s)
        return render(request, "assessments/assignment_detail.html", {
            "assignment": assignment, "course": course, "criteria": criteria, "manage": True,
            "latest": list(latest.values()), "open_flags": assignment.plagiarism_flags.filter(status="open").count(),
        })

    state = CourseState(user, course)
    acc = state.assignment_access(assignment)
    if not acc:
        messages.warning(request, acc.reason)
        return redirect(course)
    mine = list(assignment.submissions.filter(student=user).order_by("-submitted_at"))
    latest = mine[0] if mine else None
    blocked = ""
    if not state.can_act:
        blocked = "Kurs yakunlangan: topshiriq topshirib bo'lmaydi (faqat ko'rish rejimi)."
    elif latest and latest.passed:
        blocked = "Siz bu topshiriqdan muvaffaqiyatli o'tgansiz."
    elif latest and latest.status == Submission.Status.SUBMITTED:
        blocked = "Oxirgi ishingiz tekshirilmoqda. Baholangach qayta topshirish mumkin."
    form = None
    if not blocked:
        form = SubmissionForm(request.POST or None, request.FILES or None, initial={"method": "zip"})
        if request.method == "POST" and form.is_valid():
            sub = _create_submission(request, assignment, form)
            messages.success(request, "Ishingiz yuborildi.")
            if sub.snapshot_error:
                messages.warning(request, sub.snapshot_error)
            return redirect(sub)
    return render(request, "assessments/assignment_detail.html", {
        "assignment": assignment, "course": course, "criteria": criteria, "form": form, "blocked": blocked, "mine": mine, "manage": False,
    })


# =============================================================== TEKSHIRISH, CODE REVIEW
@login_required
def submission_detail(request, pk):
    sub = get_object_or_404(Submission.objects.select_related("assignment__course", "student", "graded_by"), pk=pk)
    assignment, course, user = sub.assignment, sub.assignment.course, request.user
    manager = course.can_manage(user)
    if sub.student_id != user.id and not manager:
        raise PermissionDenied

    files = codeutils.submission_sources(sub)
    paths = [p for p, _ in files]
    path = request.GET.get("path") or _default_review_file(paths)
    text = dict(files).get(path, "")
    comments = list(sub.review_comments.select_related("author"))
    by_line = defaultdict(list)
    for c in comments:
        if c.file_path == path:
            by_line[c.line_start].append(c)
    # Kod Pygments bilan ranglanadi; har qator mustaqil, yopiq HTML
    html_lines = highlight_lines(text, filename=path)[:3000]
    rows = [{"n": i, "html": h, "comments": by_line.get(i, [])} for i, h in enumerate(html_lines, start=1)]
    counts = Counter(c.file_path for c in comments)
    flags = []
    if manager:
        flags = PlagiarismFlag.objects.filter(Q(submission_a=sub) | Q(submission_b=sub)).select_related(
            "submission_a__student", "submission_b__student"
        )
    prefill = {"file_path": path, "line_start": request.GET.get("line") or ""}
    return render(request, "assessments/submission_detail.html", {
        "sub": sub, "assignment": assignment, "course": course, "manage": manager,
        "files": [(p, counts.get(p, 0)) for p in paths], "path": path, "rows": rows,
        "scores": sub.scores.select_related("criterion"),
        "extra_comments": [c for c in comments if c.file_path not in paths],
        "comment_form": ReviewCommentForm(initial=prefill) if manager else None,
        "flags": flags, "has_files": bool(files),
    })


@teacher_required
def submission_grade(request, pk):
    sub = get_object_or_404(Submission.objects.select_related("assignment__course", "student"), pk=pk)
    assignment, course = sub.assignment, sub.assignment.course
    _manage_course(request, course)
    criteria = list(assignment.criteria.all())
    if not criteria:
        messages.warning(request, "Avval topshiriqqa rubrika mezonlarini qo'shing.")
        return redirect("assessments:assignment_edit", pk=assignment.pk)
    initial = {s.criterion_id: (s.score, s.comment) for s in sub.scores.all()}
    form = GradeForm(request.POST or None, criteria=criteria, initial_scores=initial, initial={"teacher_comment": sub.teacher_comment})
    if request.method == "POST" and form.is_valid():
        total = 0
        with transaction.atomic():
            for criterion, score, note in form.scores():
                SubmissionScore.objects.update_or_create(submission=sub, criterion=criterion, defaults={"score": score, "comment": note})
                total += score
            max_total = sum(c.max_score for c in criteria)
            sub.total_score = total
            sub.percent = round(total / max_total * 100, 1) if max_total else 0
            sub.passed = total >= assignment.pass_score
            sub.status = Submission.Status.GRADED
            sub.graded_by, sub.graded_at = request.user, timezone.now()
            sub.teacher_comment = form.cleaned_data["teacher_comment"]
            sub.save()
        verdict = "o'tdingiz" if sub.passed else "o'tish balini ololmadingiz"
        notify(sub.student, f"«{assignment.title}» baholandi: {total}/{assignment.max_score} — {verdict}.", sub.get_absolute_url())
        if sub.passed:
            _after_pass(sub.student, course, assignment.module)
        messages.success(request, "Baho saqlandi.")
        return redirect(sub)
    return render(request, "assessments/submission_grade.html", {"form": form, "sub": sub, "assignment": assignment, "course": course})


@teacher_required
@require_POST
def review_comment_add(request, pk):
    sub = get_object_or_404(Submission.objects.select_related("assignment__course"), pk=pk)
    _manage_course(request, sub.assignment.course)
    form = ReviewCommentForm(request.POST)
    path = request.POST.get("file_path", "")
    if form.is_valid():
        d = form.cleaned_data
        ReviewComment.objects.create(submission=sub, author=request.user, file_path=d["file_path"], line_start=d["line_start"],
                                     line_end=d["line_end"], text=d["text"])
        notify(sub.student, f"O'qituvchi «{sub.assignment.title}» kodingizga izoh qoldirdi.", sub.get_absolute_url())
        messages.success(request, "Izoh qo'shildi.")
    else:
        messages.error(request, "Izoh qo'shilmadi: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect(f"{sub.get_absolute_url()}?path={path}")


@teacher_required
@require_POST
def review_comment_delete(request, pk):
    comment = get_object_or_404(ReviewComment.objects.select_related("submission__assignment__course"), pk=pk)
    _manage_course(request, comment.submission.assignment.course)
    sub, path = comment.submission, comment.file_path
    comment.delete()
    return redirect(f"{sub.get_absolute_url()}?path={path}")


# =============================================================== OCHIQ SAVOLLAR (mavzu ichida)
@teacher_required
def open_question_create(request, pk):
    topic = get_object_or_404(Topic.objects.select_related("module__course"), pk=pk)
    course = _manage_course(request, topic.module.course)
    form = OpenQuestionForm(request.POST or None, initial={"max_score": 10, "pass_score": 6})
    if request.method == "POST" and form.is_valid():
        q = form.save(commit=False)
        q.course, q.topic = course, topic
        _auto_order(topic.open_questions, q)
        q.save()
        messages.success(request, "Savol qo'shildi.")
        return redirect(topic)
    return render(request, "form_page.html", {"form": form, "title": f"{topic.title}: yangi savol"})


@teacher_required
def open_question_edit(request, pk):
    q = get_object_or_404(OpenQuestion.objects.select_related("course", "topic"), pk=pk)
    _manage_course(request, q.course)
    form = OpenQuestionForm(request.POST or None, instance=q)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Savol yangilandi.")
        return redirect(q.topic)
    return render(request, "form_page.html", {"form": form, "title": "Savolni tahrirlash"})


@teacher_required
@require_POST
def open_question_delete(request, pk):
    q = get_object_or_404(OpenQuestion.objects.select_related("course", "topic"), pk=pk)
    _manage_course(request, q.course)
    topic = q.topic
    q.delete()
    messages.info(request, "Savol o'chirildi.")
    return redirect(topic)


@student_required
@require_POST
def open_answer_submit(request, pk):
    q = get_object_or_404(OpenQuestion.objects.select_related("course", "topic"), pk=pk)
    user = request.user
    state = CourseState(user, q.course)
    acc = state.open_question_access(q)
    if not acc:
        messages.warning(request, acc.reason)
        return redirect(q.course)
    if not state.can_act:
        messages.warning(request, "Kurs yakunlangan — faqat ko'rish rejimi.")
        return redirect(q.topic)
    existing = OpenAnswer.objects.filter(question=q, student=user).first()
    if existing and existing.passed:
        messages.info(request, "Siz bu savoldan o'tgansiz.")
        return redirect(q.topic)
    form = OpenAnswerForm(request.POST)
    if form.is_valid():
        OpenAnswer.objects.update_or_create(question=q, student=user, defaults={
            "text": form.cleaned_data["text"], "status": OpenAnswer.Status.SUBMITTED, "score": None, "passed": None,
            "feedback": "", "graded_by": None, "graded_at": None,
        })
        touch(user, q.course)
        notify(q.course.teacher, f"{user.display_name} «{q.topic.title}» mavzusidagi savolga javob berdi.",
               f"/ochiq-savol/{q.pk}/javoblar/")
        messages.success(request, "Javobingiz yuborildi.")
    else:
        messages.error(request, "Javob bo'sh bo'lishi mumkin emas.")
    return redirect(q.topic)


@teacher_required
def open_question_answers(request, pk):
    q = get_object_or_404(OpenQuestion.objects.select_related("course", "topic"), pk=pk)
    _manage_course(request, q.course)
    rows = [(a, OpenGradeForm(question=q, initial={"score": a.score, "feedback": a.feedback})) for a in q.answers.select_related("student")]
    return render(request, "assessments/open_answers.html", {"q": q, "rows": rows, "course": q.course})


@teacher_required
@require_POST
def open_answer_grade(request, pk):
    answer = get_object_or_404(OpenAnswer.objects.select_related("question__course", "question__topic", "student"), pk=pk)
    q = answer.question
    _manage_course(request, q.course)
    form = OpenGradeForm(request.POST, question=q)
    if form.is_valid():
        answer.score = form.cleaned_data["score"]
        answer.feedback = form.cleaned_data["feedback"]
        answer.passed = answer.score >= q.pass_score
        answer.status = OpenAnswer.Status.GRADED
        answer.graded_by, answer.graded_at = request.user, timezone.now()
        answer.save()
        verdict = "o'tdingiz" if answer.passed else "o'tish balini ololmadingiz"
        notify(answer.student, f"Savolingiz baholandi: {answer.score}/{q.max_score} — {verdict}.", q.topic.get_absolute_url())
        if answer.passed:
            _after_pass(answer.student, q.course)
        messages.success(request, "Baho saqlandi.")
    else:
        messages.error(request, "Bahoni saqlab bo'lmadi: " + "; ".join(e for errs in form.errors.values() for e in errs))
    return redirect("assessments:open_question_answers", pk=q.pk)


# =============================================================== PLAGIAT
@teacher_required
def plagiarism_list(request):
    flags = PlagiarismFlag.objects.select_related("assignment__course", "submission_a__student", "submission_b__student")
    if not request.user.is_platform_admin:
        flags = flags.filter(assignment__course__teacher=request.user)
    status = request.GET.get("holat", "open")
    if status in ("open", "dismissed", "confirmed"):
        flags = flags.filter(status=status)
    return render(request, "assessments/plagiarism_list.html", {"flags": flags, "status": status})


@teacher_required
@require_POST
def plagiarism_update(request, pk):
    flag = get_object_or_404(PlagiarismFlag.objects.select_related("assignment__course"), pk=pk)
    _manage_course(request, flag.assignment.course)
    status = request.POST.get("status")
    if status in ("open", "dismissed", "confirmed"):
        flag.status = status
        flag.save(update_fields=["status"])
    return redirect("assessments:plagiarism_list")
