import io
import tempfile
import time
import zipfile
from datetime import timedelta
from types import SimpleNamespace

from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from assessments.grading import grade_quiz
from assessments.models import Assignment, Choice, Question, Quiz, RubricCriterion
from courses.models import Competency, Course, Enrollment, Module, Topic

_MEDIA = tempfile.mkdtemp(prefix="lms_test_media_")
PW = "pw12345!xYz"


@override_settings(MEDIA_ROOT=_MEDIA)
class BaseTest(TestCase):
    def login(self, user):
        self.client.force_login(user)


def mk_user(username, role="student", approval="approved", **kw):
    return User.objects.create_user(
        username, password=PW, role=role, approval_status=approval, first_name=username.capitalize(), last_name="Test",
        email=f"{username}@t.uz", **kw
    )


class FakePost:
    """grade_quiz() uchun request.POST o'rniga."""

    def __init__(self, data=None):
        self.data = {k: [str(x) for x in (v if isinstance(v, (list, tuple)) else [v])] for k, v in (data or {}).items()}

    def getlist(self, key):
        return self.data.get(key, [])


def mk_quiz(course, module=None, kind="module", n=2, max_score=100, pass_score=60, comps=None, bug=False, **kw):
    """n ta savolli test; har bir savolda 1 ta to'g'ri va 1 ta noto'g'ri variant. (quiz, [(savol, to'g'ri_id, xato_id)])"""
    quiz = Quiz.objects.create(course=course, module=module, kind=kind, title=f"Test-{kind}-{Quiz.objects.count()}",
                               max_score=max_score, pass_score=pass_score, **kw)
    items = []
    for i in range(n):
        comp = comps[i % len(comps)] if comps else None
        q = Question.objects.create(quiz=quiz, text=f"Savol {i + 1}", competency=comp, order=i + 1, is_bug_hunt=bug)
        good = Choice.objects.create(question=q, text="to'g'ri", is_correct=True)
        bad = Choice.objects.create(question=q, text="xato", is_correct=False)
        items.append((q, good.id, bad.id))
    return quiz, items


def answers(items, correct_flags):
    """correct_flags: har savol uchun True/False -> POST maydonlari."""
    return {f"q_{q.pk}": (good if ok else bad) for (q, good, bad), ok in zip(items, correct_flags)}


def take(client, quiz, data):
    url = reverse("assessments:quiz_take", args=[quiz.pk])
    resp = client.get(url)
    if resp.status_code != 200:  # ilova testni ochishni bloklagan (urinish tugagan, read-only va h.k.)
        return resp
    return client.post(url, {"token": resp.context["token"], **data})


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def zip_upload(files, name="p.zip"):
    return SimpleUploadedFile(name, make_zip(files), content_type="application/zip")


def mk_assignment(course, module=None, kind="module", pass_score=60, criteria=((("To'g'ri ishlashi"), 40), ("Kod tozaligi", 30), ("Xatoliklar", 30)), due_days=30, **kw):
    a = Assignment.objects.create(course=course, module=module, kind=kind, title=f"Topshiriq-{Assignment.objects.count()}",
                                  description="Shart", pass_score=pass_score, due_date=timezone.localdate() + timedelta(days=due_days), **kw)
    for name, mx in criteria:
        RubricCriterion.objects.create(assignment=a, name=name, max_score=mx)
    a.recalc_max_score()
    return a


def full_course(teacher, start=-5, end=100, slug="kurs"):
    """2 modul, 3 mavzu, kirish testi, 1-modul testi va topshirig'i, yakuniy loyiha."""
    today = timezone.localdate()
    course = Course.objects.create(title="Kurs", slug=slug, description="d", teacher=teacher,
                                   start_date=today + timedelta(days=start), end_date=today + timedelta(days=end))
    c_a = Competency.objects.create(course=course, name="A")
    c_b = Competency.objects.create(course=course, name="B")
    m1 = Module.objects.create(course=course, title="M1", order=1, start_date=today + timedelta(days=start), end_date=today + timedelta(days=30))
    m2 = Module.objects.create(course=course, title="M2", order=2, start_date=today + timedelta(days=40), end_date=today + timedelta(days=80))
    t1 = Topic.objects.create(module=m1, title="T1", order=1, content="x")
    t2 = Topic.objects.create(module=m1, title="T2", order=2, content="x")
    t3 = Topic.objects.create(module=m2, title="T3", order=1, content="x")
    pre, pre_items = mk_quiz(course, None, "pretest", n=4, comps=[c_a, c_b], max_attempts=1)
    quiz1, q1_items = mk_quiz(course, m1, "module", n=2, comps=[c_a, c_b])
    a1 = mk_assignment(course, m1)
    final = mk_assignment(course, None, "final")
    return SimpleNamespace(course=course, m1=m1, m2=m2, t1=t1, t2=t2, t3=t3, pre=pre, pre_items=pre_items, quiz1=quiz1,
                           q1_items=q1_items, a1=a1, final=final, comps=(c_a, c_b))


def enroll(course, student):
    return Enrollment.objects.create(course=course, student=student)


def pass_pretest(ctx, student):
    grade_quiz(ctx.pre, student, FakePost(answers(ctx.pre_items, [True, True, False, False])), timezone.now() - timedelta(minutes=2))
