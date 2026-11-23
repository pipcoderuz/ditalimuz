"""Eski yozuvlar uchun «kursni boshlagan vaqt»ni mavjud faoliyatdan tiklaydi.

Avvalgi versiyada started_at / last_activity_at yo'q edi, shuning uchun progressi bor talabalar ham
«boshlamagan» ko'rinardi. Bu migratsiya birinchi va oxirgi faoliyat (mavzu, test, topshiriq, ochiq savol) vaqtlaridan to'ldiradi.
"""
from django.db import migrations


def backfill_started_at(apps, schema_editor):
    Enrollment = apps.get_model("courses", "Enrollment")
    TopicProgress = apps.get_model("courses", "TopicProgress")
    Attempt = apps.get_model("assessments", "Attempt")
    Submission = apps.get_model("assessments", "Submission")
    OpenAnswer = apps.get_model("assessments", "OpenAnswer")

    for e in Enrollment.objects.filter(started_at__isnull=True):
        times = list(TopicProgress.objects.filter(student_id=e.student_id, topic__module__course_id=e.course_id).values_list("completed_at", flat=True))
        times += Attempt.objects.filter(student_id=e.student_id, quiz__course_id=e.course_id).values_list("submitted_at", flat=True)
        times += Submission.objects.filter(student_id=e.student_id, assignment__course_id=e.course_id).values_list("submitted_at", flat=True)
        times += OpenAnswer.objects.filter(student_id=e.student_id, question__course_id=e.course_id).values_list("submitted_at", flat=True)
        times = [t for t in times if t]
        if not times:
            continue
        e.started_at = min(times)
        if e.last_activity_at is None:
            e.last_activity_at = max(times)
        e.save(update_fields=["started_at", "last_activity_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("courses", "0002_course_chat_responders_enrollment_last_activity_at_and_more"),
        ("assessments", "0002_assignment_topic_question_code_language_quiz_topic_and_more"),
    ]
    operations = [migrations.RunPython(backfill_started_at, migrations.RunPython.noop)]
