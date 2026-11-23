from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Max

from django.urls import reverse

from community.notify import notify

from .models import BADGES, UserBadge

BUG_HUNT_MIN_QUESTIONS = 2          # kamida shuncha «xatoni top» savoli bo'lishi kerak
BUG_HUNT_DEFAULT_LIMIT_SECONDS = 600  # vaqt chegarasi berilmagan testda "tez" = 10 daqiqa ichida
TOPIC_POINTS = 2


def award(user, code, course):
    badge, created = UserBadge.objects.get_or_create(user=user, code=code, course=course)
    if created:
        notify(user, f"Yangi yutuq: {BADGES[code]['icon']} {BADGES[code]['title']}", reverse("accounts:profile_public", args=[user.username]))
    return created


def after_attempt(attempt):
    quiz = attempt.quiz
    if attempt.score >= quiz.max_score and quiz.total_points > 0:
        award(attempt.student, "perfect_score", quiz.course)
    bug = [a for a in attempt.answers.select_related("question") if a.question.is_bug_hunt]
    limit = quiz.time_limit_minutes * 60 / 2 if quiz.time_limit_minutes else BUG_HUNT_DEFAULT_LIMIT_SECONDS
    if len(bug) >= BUG_HUNT_MIN_QUESTIONS and all(a.is_correct for a in bug) and attempt.duration_seconds <= limit:
        award(attempt.student, "bug_hunter", quiz.course)


def after_submission(submission):
    a = submission.assignment
    due = a.effective_due
    if due and submission.submitted_at.astimezone().date() <= due - timedelta(days=1):
        award(submission.student, "fast_coder", a.course)


def after_topic_complete(user, topic):
    from courses.models import TopicProgress

    if TopicProgress.objects.filter(student=user, topic__module__course=topic.module.course).count() == 1:
        award(user, "first_step", topic.module.course)


def after_course_complete(enrollment):
    award(enrollment.student, "graduate", enrollment.course)


def leaderboard(course):
    """Kurs reytingi. Ball = testlar (kirish testidan tashqari, eng yaxshi natija) + baholangan topshiriq va ochiq savollar + mavzular (har biri 2 ball)."""
    from assessments.models import Attempt, OpenAnswer, Quiz, Submission
    from courses.models import Enrollment, TopicProgress

    points = defaultdict(float)
    for row in (
        Attempt.objects.filter(quiz__course=course).exclude(quiz__kind=Quiz.Kind.PRETEST)
        .values("student", "quiz").annotate(best=Max("score"))
    ):
        points[row["student"]] += row["best"]
    for row in OpenAnswer.objects.filter(question__course=course, status="graded").values("student", "question").annotate(best=Max("score")):
        points[row["student"]] += row["best"] or 0
    for row in (
        Submission.objects.filter(assignment__course=course, status=Submission.Status.GRADED)
        .values("student", "assignment").annotate(best=Max("total_score"))
    ):
        points[row["student"]] += row["best"] or 0
    for row in TopicProgress.objects.filter(topic__module__course=course).values("student").annotate(n=Count("id")):
        points[row["student"]] += row["n"] * TOPIC_POINTS
    badge_counts = {r["user"]: r["n"] for r in UserBadge.objects.filter(course=course).values("user").annotate(n=Count("id"))}

    rows = [
        {"student": e.student, "points": round(points.get(e.student_id, 0), 1), "badges": badge_counts.get(e.student_id, 0)}
        for e in Enrollment.objects.filter(course=course).select_related("student")
    ]
    rows.sort(key=lambda r: (-r["points"], r["student"].display_name.lower()))
    rank, prev = 0, None
    for i, row in enumerate(rows, start=1):
        if row["points"] != prev:
            rank, prev = i, row["points"]
        row["rank"] = rank
    return rows
