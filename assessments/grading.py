from django.utils import timezone

from .models import Attempt, AttemptAnswer


def grade_quiz(quiz, student, post, started_at):
    """Testni avtomatik tekshiradi va Attempt yaratadi. Javob: bitta tanlov (single) yoki to'liq to'plam (multiple)."""
    questions = list(quiz.questions.prefetch_related("choices"))
    total = sum(q.points for q in questions)
    now = timezone.now()
    attempt = Attempt.objects.create(
        quiz=quiz, student=student, started_at=started_at,
        duration_seconds=max(0, int((now - started_at).total_seconds())),
    )
    earned = 0.0
    for q in questions:
        valid = {c.id for c in q.choices.all()}
        selected = sorted({int(x) for x in post.getlist(f"q_{q.pk}") if x.isdigit()} & valid)
        correct = {c.id for c in q.choices.all() if c.is_correct}
        ok = bool(correct) and set(selected) == correct
        pts = float(q.points) if ok else 0.0
        earned += pts
        AttemptAnswer.objects.create(attempt=attempt, question=q, selected_ids=selected, is_correct=ok, points_earned=pts)
    attempt.percent = round(earned / total * 100, 1) if total else 0.0
    attempt.score = round(earned / total * quiz.max_score, 1) if total else 0.0
    attempt.passed = attempt.score >= quiz.pass_score
    attempt.save(update_fields=["percent", "score", "passed"])
    return attempt
