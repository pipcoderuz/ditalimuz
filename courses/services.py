from statistics import mean

from django.db import transaction
from django.utils import timezone

from .models import Certificate, Enrollment


def course_progress(student, course):
    """Talabaning mavzular bo'yicha progressi: (tugatilgan, jami, foiz)."""
    from .models import Topic, TopicProgress

    total = Topic.objects.filter(module__course=course).count()
    done = TopicProgress.objects.filter(student=student, topic__module__course=course).count()
    return done, total, round(done / total * 100) if total else 0


def touch(student, course):
    """Talaba faoliyatini qayd etadi (birinchi faoliyat — kursni boshlagan payt)."""
    enrollment = Enrollment.objects.filter(student=student, course=course).first()
    if enrollment:
        enrollment.touch()
    return enrollment


@transaction.atomic
def try_complete(enrollment):
    """Kurs yakunlash shartlari bajarilgan bo'lsa — kursni yakunlaydi va sertifikat beradi.

    Shartlar: yakuniy test va/yoki yakuniy loyiha QO'SHILGAN bo'lsa — qo'shilganlarining hammasidan o'tilgan bo'lishi kerak.
    Hech biri qo'shilmagan bo'lsa — barcha modullar tugatilgan bo'lishi kerak.
    """
    from assessments.models import Attempt, Submission
    from community.notify import notify
    from gamification import services as gamification

    from .access import CourseState

    if enrollment.status == Enrollment.Status.COMPLETED:
        return None
    course, student = enrollment.course, enrollment.student
    state = CourseState(student, course)
    fq, fa = state.final_quiz, state.final_assignment
    percents = []
    if fq or fa:
        if fq:
            if fq.id not in state.passed_quizzes:
                return None
            percents.append(max(a.percent for a in Attempt.objects.filter(student=student, quiz=fq)))
        if fa:
            if fa.id not in state.passed_assignments:
                return None
            percents.append(max(s.percent or 0 for s in Submission.objects.filter(student=student, assignment=fa, passed=True)))
    else:
        if not state.modules or not state.all_modules_passed():
            return None
        quiz_best = [a.percent for a in Attempt.objects.filter(student=student, quiz__course=course, passed=True)]
        percents = [mean(quiz_best)] if quiz_best else [100.0]

    enrollment.status = Enrollment.Status.COMPLETED
    enrollment.completed_at = timezone.now()
    enrollment.save(update_fields=["status", "completed_at"])
    cert, _ = Certificate.objects.get_or_create(enrollment=enrollment, defaults={"final_percent": round(mean(percents), 1)})
    notify(student, f"Tabriklaymiz! «{course.title}» kursini yakunladingiz. Sertifikatingiz tayyor.", cert.get_absolute_url())
    gamification.after_course_complete(enrollment)
    return cert


def build_outline(state):
    """Kurs sahifasi uchun modul/mavzu/test/topshiriq holatlari."""
    from assessments.models import Assignment, Attempt, OpenQuestion, Quiz, Submission

    user, course = state.user, state.course
    best, count, latest = {}, {}, {}
    if not state.staff:
        for a in Attempt.objects.filter(student=user, quiz__course=course).order_by("submitted_at"):
            best[a.quiz_id] = max(best.get(a.quiz_id, 0), a.score)
            count[a.quiz_id] = count.get(a.quiz_id, 0) + 1
        for s in Submission.objects.filter(student=user, assignment__course=course).order_by("submitted_at"):
            latest[s.assignment_id] = s

    quizzes_by_module, assigns_by_module = {}, {}
    topic_counts = {}
    for q in course.quizzes.filter(kind=Quiz.Kind.MODULE):
        quizzes_by_module.setdefault(q.module_id, []).append(q)
    for a in course.assignments.filter(kind=Assignment.Kind.MODULE):
        assigns_by_module.setdefault(a.module_id, []).append(a)
    for q in course.quizzes.filter(kind=Quiz.Kind.TOPIC):
        topic_counts.setdefault(q.topic_id, {"quiz": 0, "assignment": 0, "question": 0})["quiz"] += 1
    for a in course.assignments.filter(kind=Assignment.Kind.TOPIC):
        topic_counts.setdefault(a.topic_id, {"quiz": 0, "assignment": 0, "question": 0})["assignment"] += 1
    for oq in course.open_questions.all():
        topic_counts.setdefault(oq.topic_id, {"quiz": 0, "assignment": 0, "question": 0})["question"] += 1

    outline = []
    for module in state.modules:
        topics = [
            {"topic": t, "done": t.id in state.done_topics, "access": state.topic_access(t),
             "counts": topic_counts.get(t.id, {"quiz": 0, "assignment": 0, "question": 0})}
            for t in module.topics.all()
        ]
        outline.append(
            {
                "module": module,
                "access": state.module_access(module),
                "passed": state.module_passed(module) if not state.staff else False,
                "topics": topics,
                "quizzes": [
                    {"quiz": q, "access": state.quiz_access(q), "best": best.get(q.id), "attempts": count.get(q.id, 0),
                     "passed": q.id in state.passed_quizzes}
                    for q in quizzes_by_module.get(module.id, [])
                ],
                "assignments": [
                    {"assignment": a, "access": state.assignment_access(a), "submission": latest.get(a.id),
                     "passed": a.id in state.passed_assignments}
                    for a in assigns_by_module.get(module.id, [])
                ],
            }
        )
    return outline


def notify_module_unlocked(student, course, module):
    """Modul tugallansa — keyingi modul (yoki yakuniy bosqich) ochilgani haqida bildirishnoma (takrorlanmaydi)."""
    from community.models import Notification
    from community.notify import notify

    from .access import CourseState

    state = CourseState(student, course)
    ids = [m.id for m in state.modules]
    if module is None or module.id not in ids:
        return
    idx = ids.index(module.id)
    if not state.module_passed(state.modules[idx]):
        return
    if idx + 1 < len(state.modules):
        text = f"Yangi modul ochildi: «{state.modules[idx + 1].title}» ({course.title})."
    elif (state.final_quiz or state.final_assignment) and state.all_modules_passed():
        text = f"Yakuniy bosqich ochildi ({course.title}): " + " va ".join(
            x.title for x in (state.final_quiz, state.final_assignment) if x
        ) + "."
    else:
        return
    if not Notification.objects.filter(user=student, text=text).exists():
        notify(student, text, course.get_absolute_url())
