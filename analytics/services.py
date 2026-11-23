from collections import defaultdict

from django.db.models import Avg, Count, Max, Q

from assessments.models import Attempt, AttemptAnswer, OpenAnswer, Quiz, Submission
from courses.models import Enrollment, Topic, TopicProgress


def _pct(earned, possible):
    return round(earned / possible * 100, 1) if possible else None


def competency_growth(student, course):
    """Kirish testi (pre-test) va yakuniy holat (modul testlarining eng yaxshi natijalari) bo'yicha kompetensiyalar o'sishi."""
    pre, fin = defaultdict(lambda: [0.0, 0.0]), defaultdict(lambda: [0.0, 0.0])
    pre_attempt = Attempt.objects.filter(quiz__course=course, quiz__kind=Quiz.Kind.PRETEST, student=student).order_by("submitted_at").first()
    if pre_attempt:
        for a in pre_attempt.answers.select_related("question"):
            pre[a.question.competency_id][0] += a.points_earned
            pre[a.question.competency_id][1] += a.question.points
    best = {}
    for att in Attempt.objects.filter(quiz__course=course, student=student).exclude(quiz__kind=Quiz.Kind.PRETEST):
        if att.quiz_id not in best or att.score > best[att.quiz_id].score:
            best[att.quiz_id] = att
    for att in best.values():
        for a in att.answers.select_related("question"):
            fin[a.question.competency_id][0] += a.points_earned
            fin[a.question.competency_id][1] += a.question.points

    names = {c.id: c.name for c in course.competencies.all()}
    names[None] = "Umumiy (kompetensiyasiz savollar)"
    rows = []
    for cid in [*names.keys()]:
        p, f = _pct(*pre[cid]) if cid in pre else None, _pct(*fin[cid]) if cid in fin else None
        if p is None and f is None:
            continue
        rows.append({"name": names[cid], "pre": p, "final": f, "delta": round(f - p, 1) if p is not None and f is not None else None})
    final_pcts = [a.percent for a in best.values()]
    overall_final = round(sum(final_pcts) / len(final_pcts), 1) if final_pcts else None
    overall_pre = pre_attempt.percent if pre_attempt else None
    return {
        "overall_delta": round(overall_final - overall_pre, 1) if overall_final is not None and overall_pre is not None else None,
        "rows": rows,
        "pre_attempt": pre_attempt,
        "overall_pre": pre_attempt.percent if pre_attempt else None,
        "overall_final": round(sum(final_pcts) / len(final_pcts), 1) if final_pcts else None,
    }


def dropoff(course):
    """O'qituvchi uchun: qaysi mavzu/testda talabalar eng ko'p yiqilayotgani."""
    total = Enrollment.objects.filter(course=course).count()
    done = {r["topic"]: r["n"] for r in TopicProgress.objects.filter(topic__module__course=course).values("topic").annotate(n=Count("student", distinct=True))}
    funnel = [
        {"topic": t, "done": done.get(t.id, 0), "percent": round(done.get(t.id, 0) / total * 100) if total else 0}
        for t in Topic.objects.filter(module__course=course).select_related("module").order_by("module__order", "module_id", "order", "id")
    ]

    quizzes = []
    for quiz in course.quizzes.select_related("module"):
        attempts = Attempt.objects.filter(quiz=quiz)
        tried = attempts.values("student").distinct().count()
        passed = attempts.filter(passed=True).values("student").distinct().count()
        failed = tried - passed
        quizzes.append({"quiz": quiz, "tried": tried, "passed": passed, "failed": failed,
                        "fail_rate": round(failed / tried * 100) if tried else 0})

    hardest = (
        AttemptAnswer.objects.filter(question__quiz__course=course)
        .values("question", "question__text", "question__quiz__title")
        .annotate(total=Count("id"), wrong=Count("id", filter=Q(is_correct=False)))
    )
    hardest = sorted(
        ({**r, "wrong_rate": round(r["wrong"] / r["total"] * 100)} for r in hardest if r["total"]),
        key=lambda r: (-r["wrong_rate"], -r["total"]),
    )[:10]

    assignments = []
    for a in course.assignments.select_related("module"):
        subs = Submission.objects.filter(assignment=a)
        students = subs.values("student").distinct().count()
        passed = subs.filter(passed=True).values("student").distinct().count()
        graded = subs.filter(status=Submission.Status.GRADED)
        avg = graded.aggregate(avg=Avg("percent"))["avg"]
        assignments.append({"assignment": a, "students": students, "passed": passed,
                            "pending": subs.filter(status=Submission.Status.SUBMITTED).count(),
                            "avg": round(avg, 1) if avg is not None else None})
    open_qs = []
    for oq in course.open_questions.select_related("topic"):
        answers = OpenAnswer.objects.filter(question=oq)
        graded = answers.filter(status="graded")
        avg = graded.aggregate(avg=Avg("score"))["avg"]
        open_qs.append({"q": oq, "answered": answers.count(), "passed": answers.filter(passed=True).count(),
                        "pending": answers.filter(status="submitted").count(), "avg": round(avg, 1) if avg is not None else None})
    return {"total": total, "funnel": funnel, "quizzes": quizzes, "hardest": hardest, "assignments": assignments, "open_questions": open_qs}


# ====================================================================== UMUMIY STATISTIKA
def _scope_courses(user):
    from courses.models import Course

    if user.is_platform_admin:
        return Course.objects.all()
    if user.is_teacher:
        return Course.objects.filter(teacher=user)
    return Course.objects.filter(enrollments__student=user)


def _enrollment_rows(enrollments):
    """Har bir yozilish uchun: progress %, o'rtacha ball, davomiylik."""
    from collections import defaultdict as dd

    from django.utils import timezone

    enrollments = list(enrollments)
    course_ids = {e.course_id for e in enrollments}
    totals = {r["module__course"]: r["n"] for r in Topic.objects.filter(module__course__in=course_ids).values("module__course").annotate(n=Count("id"))}
    done = {(r["student"], r["topic__module__course"]): r["n"]
            for r in TopicProgress.objects.filter(topic__module__course__in=course_ids).values("student", "topic__module__course").annotate(n=Count("id"))}
    best = dd(list)
    for r in (Attempt.objects.filter(quiz__course__in=course_ids).exclude(quiz__kind=Quiz.Kind.PRETEST)
              .values("student", "quiz__course", "quiz").annotate(b=Max("percent"))):
        best[(r["student"], r["quiz__course"])].append(r["b"])
    for r in (Submission.objects.filter(assignment__course__in=course_ids, status=Submission.Status.GRADED)
              .values("student", "assignment__course", "assignment").annotate(b=Max("percent"))):
        best[(r["student"], r["assignment__course"])].append(r["b"] or 0)
    now = timezone.now()
    rows = []
    for e in enrollments:
        total = totals.get(e.course_id, 0)
        d = done.get((e.student_id, e.course_id), 0)
        scores = best.get((e.student_id, e.course_id), [])
        end = e.completed_at or now
        rows.append({
            "e": e, "progress": round(d / total * 100) if total else 0,
            "score": round(sum(scores) / len(scores), 1) if scores else None,
            "days": (end - e.started_at).days if e.started_at else None,
            "idle_days": (now - e.last_activity_at).days if e.last_activity_at else None,
            "state": "completed" if e.status == "completed" else ("not_started" if not e.started_at else "learning"),
        })
    return rows


def overview(user, course_id=None, date_from=None, date_to=None, state=None):
    """Umumiy statistika. Admin — butun platforma; o'qituvchi — o'z kurslari; talaba — shaxsiy.
    date_from/date_to — talaba kursni BOSHLAGAN sana oralig'i (started_at) bo'yicha filtr."""
    from datetime import timedelta

    from django.db.models.functions import TruncMonth
    from django.utils import timezone

    from accounts.models import User
    from courses.models import Certificate, Enrollment

    courses = _scope_courses(user).distinct()
    if course_id:
        courses = courses.filter(pk=course_id)
    enr = Enrollment.objects.filter(course__in=courses).select_related("student", "course")
    if user.is_student:
        enr = enr.filter(student=user)
    if date_from:
        enr = enr.filter(started_at__date__gte=date_from)
    if date_to:
        enr = enr.filter(started_at__date__lte=date_to)
    rows = _enrollment_rows(enr.order_by("-started_at", "-enrolled_at"))
    if state in ("completed", "learning", "not_started"):
        rows = [r for r in rows if r["state"] == state]

    now = timezone.now()
    n = len(rows)
    completed = [r for r in rows if r["state"] == "completed"]
    started = [r for r in rows if r["e"].started_at]
    durations = [r["days"] for r in completed if r["days"] is not None]
    scores = [r["score"] for r in rows if r["score"] is not None]
    totals = {
        "enrollments": n, "students": len({r["e"].student_id for r in rows}), "started": len(started),
        "completed": len(completed), "completion_rate": round(len(completed) / n * 100) if n else 0,
        "avg_progress": round(sum(r["progress"] for r in rows) / n) if n else 0,
        "avg_days_to_finish": round(sum(durations) / len(durations), 1) if durations else None,
        "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
        "active_7d": sum(1 for r in rows if r["e"].last_activity_at and r["e"].last_activity_at >= now - timedelta(days=7)),
        "courses": courses.count(),
    }
    ids = [r["e"].id for r in rows]
    totals["certificates"] = Certificate.objects.filter(enrollment_id__in=ids).count()
    totals["submissions"] = Submission.objects.filter(assignment__course__in=courses).count() if not user.is_student else Submission.objects.filter(student=user).count()
    totals["attempts"] = Attempt.objects.filter(quiz__course__in=courses).count() if not user.is_student else Attempt.objects.filter(student=user).count()

    per_course = []
    for c in courses.select_related("teacher"):
        cr = [r for r in rows if r["e"].course_id == c.id]
        done_c = [r for r in cr if r["state"] == "completed"]
        dur = [r["days"] for r in done_c if r["days"] is not None]
        per_course.append({
            "course": c, "enrolled": len(cr), "started": sum(1 for r in cr if r["e"].started_at), "completed": len(done_c),
            "rate": round(len(done_c) / len(cr) * 100) if cr else 0,
            "avg_progress": round(sum(r["progress"] for r in cr) / len(cr)) if cr else 0,
            "avg_days": round(sum(dur) / len(dur), 1) if dur else None,
        })
    per_course.sort(key=lambda r: -r["enrolled"])

    def monthly(qs, field):
        since = now - timedelta(days=365)
        data = {r["m"].strftime("%Y-%m"): r["n"] for r in qs.filter(**{f"{field}__gte": since}).annotate(m=TruncMonth(field)).values("m").annotate(n=Count("id"))}
        months, y, m = [], now.year, now.month
        for _ in range(12):
            months.append(f"{y}-{m:02d}")
            m -= 1
            if m == 0:
                y, m = y - 1, 12
        months.reverse()
        return months, [data.get(k, 0) for k in months]

    months, enrolled_series = monthly(Enrollment.objects.filter(course__in=courses), "enrolled_at")
    _, started_series = monthly(Enrollment.objects.filter(course__in=courses, started_at__isnull=False), "started_at")
    _, completed_series = monthly(Enrollment.objects.filter(course__in=courses, completed_at__isnull=False), "completed_at")
    series = {"months": months, "enrolled": enrolled_series, "started": started_series, "completed": completed_series}
    if user.is_platform_admin:
        _, reg = monthly(User.objects.all(), "date_joined")
        series["registered"] = reg
    users_by_role = {}
    if user.is_platform_admin:
        users_by_role = {r["role"]: r["n"] for r in User.objects.values("role").annotate(n=Count("id"))}
    return {"totals": totals, "per_course": per_course, "rows": rows, "series": series, "courses": list(_scope_courses(user).distinct()),
            "users_by_role": users_by_role}


def student_stats(student, course):
    """Bitta talabaning kurs bo'yicha batafsil statistikasi: qachon yozildi, QACHON BOSHLADI, tezligi, modullar vaqt chizig'i."""
    from django.utils import timezone

    from courses.models import Certificate, Enrollment
    from gamification.models import UserBadge

    enrollment = Enrollment.objects.filter(student=student, course=course).first()
    if not enrollment:
        return None
    row = _enrollment_rows([enrollment])[0]
    now = timezone.now()

    progress = {tp.topic_id: tp.completed_at for tp in TopicProgress.objects.filter(student=student, topic__module__course=course)}
    first_pass = {}
    for a in Attempt.objects.filter(student=student, quiz__course=course, passed=True).order_by("submitted_at"):
        first_pass.setdefault(("quiz", a.quiz_id), a.submitted_at)
    for s in Submission.objects.filter(student=student, assignment__course=course, passed=True).order_by("graded_at"):
        first_pass.setdefault(("assignment", s.assignment_id), s.graded_at or s.submitted_at)

    modules = []
    prev_end = enrollment.started_at
    for m in course.modules.prefetch_related("topics"):
        topics = list(m.topics.all())
        stamps = [progress[t.id] for t in topics if t.id in progress]
        for q in course.quizzes.filter(module=m):
            if ("quiz", q.id) in first_pass:
                stamps.append(first_pass[("quiz", q.id)])
        for a in course.assignments.filter(module=m):
            if ("assignment", a.id) in first_pass:
                stamps.append(first_pass[("assignment", a.id)])
        done_topics = sum(1 for t in topics if t.id in progress)
        finished = max(stamps) if stamps and done_topics == len(topics) else None
        modules.append({"module": m, "topics_done": done_topics, "topics_total": len(topics), "finished_at": finished,
                        "days": (finished - prev_end).days if finished and prev_end else None})
        if finished:
            prev_end = finished

    pre = Attempt.objects.filter(student=student, quiz__course=course, quiz__kind=Quiz.Kind.PRETEST).first()
    others = _enrollment_rows(Enrollment.objects.filter(course=course).exclude(pk=enrollment.pk))
    course_avg_progress = round(sum(r["progress"] for r in others) / len(others)) if others else None
    cert = Certificate.objects.filter(enrollment=enrollment).first()
    return {
        "enrollment": enrollment, "row": row, "modules": modules, "pretest": pre,
        "days_to_start": (enrollment.started_at - enrollment.enrolled_at).days if enrollment.started_at else None,
        "course_avg_progress": course_avg_progress, "certificate": cert,
        "badges": UserBadge.objects.filter(user=student, course=course).count(),
        "attempts": Attempt.objects.filter(student=student, quiz__course=course).count(),
        "submissions": Submission.objects.filter(student=student, assignment__course=course).count(),
        "open_answers": OpenAnswer.objects.filter(student=student, question__course=course).count(),
        "now": now,
    }
