"""seed_demo ma'lumotlari bilan barcha sahifalar rollar bo'yicha xatosiz ochilishini va
shablonlarda aniqlanmagan (nomi noto'g'ri yozilgan) o'zgaruvchi yo'qligini tekshiradi."""
from collections import Counter
from contextlib import contextmanager

from django.core.management import call_command
from django.template import base
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from assessments.models import Assignment, Attempt, PlagiarismFlag, Question, Quiz, Submission
from courses.models import Course, Module, Topic

# Ixtiyoriy (zararsiz) o'zgaruvchilar: vidjet turi har doim ham bo'lmaydi, multipart faqat fayl formalarida beriladi
ALLOWED_MISSING = {"field.field.widget.input_type", "multipart", "subtitle"}


def unexpected(misses):
    """So'rovda berilmagan filtr kalitlari (f.kurs, f.dan, ...) ham zararsiz."""
    return {m for m in set(misses) - ALLOWED_MISSING if not m.startswith("f.")}


@contextmanager
def track_missing_variables():
    misses, original = Counter(), base.Variable._resolve_lookup

    def patched(self, context):
        try:
            return original(self, context)
        except base.VariableDoesNotExist:
            misses[self.var] += 1
            raise

    base.Variable._resolve_lookup = patched
    try:
        yield misses
    finally:
        base.Variable._resolve_lookup = original


class SmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", verbosity=0)
        cls.course = Course.objects.get(slug="python-asoslari")
        cls.s1, cls.s2 = User.objects.get(username="student1"), User.objects.get(username="student2")
        cls.teacher = User.objects.get(username="teacher")
        cls.sub = Submission.objects.order_by("id").first()
        cls.quiz = Quiz.objects.filter(kind="module").first()
        cls.pre = Quiz.objects.get(kind="pretest")
        cls.module1 = Module.objects.filter(course=cls.course).order_by("order", "id").first()
        cls.topic1 = Topic.objects.filter(module__course=cls.course).order_by("id").first()
        cls.a1 = Assignment.objects.filter(kind="module").first()
        cls.final = Assignment.objects.filter(kind="final").first()
        from community import chat
        cls.room = chat.direct_room(cls.teacher, cls.s1)

    def check(self, user, urls, expect=200):
        self.client.force_login(user)
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, expect, f"{user.username}: {url}")

    def test_student_pages(self):
        c, att = self.course, Attempt.objects.filter(student=self.s1).first()
        urls = [
            reverse("home"), reverse("courses:course_list"), c.get_absolute_url(), self.topic1.get_absolute_url(),
            self.quiz.get_absolute_url(), self.pre.get_absolute_url(), att.get_absolute_url(), self.a1.get_absolute_url(),
            self.sub.get_absolute_url(), reverse("gamification:leaderboard", args=[c.slug]), reverse("analytics:growth", args=[c.slug]),
            reverse("community:thread_list"), reverse("community:thread_create"), reverse("community:notifications"),
            reverse("community:inbox"), reverse("community:chat_room", args=[self.room.pk]),
            reverse("accounts:profile"), reverse("accounts:profile_public", args=["student1"]),
        ]
        with track_missing_variables() as misses:
            self.check(self.s1, urls)
            self.check(self.s2, [reverse("home"), c.get_absolute_url(), self.pre.get_absolute_url()])
        self.assertEqual(unexpected(misses), set(), "Shablonlarda aniqlanmagan o'zgaruvchi bor")

    def test_student_locked_pages_redirect(self):
        # progressiv rejim: 2-modul va yakuniy loyiha 1-modul tugamagan talabaga yopiq
        self.check(self.s2, [self.final.get_absolute_url(), reverse("assessments:quiz_take", args=[self.quiz.pk])], expect=302)

    def test_teacher_pages(self):
        c, q = self.course, Question.objects.first()
        urls = [
            reverse("home"), c.get_absolute_url(), self.topic1.get_absolute_url(), reverse("courses:my_students"),
            reverse("courses:course_create"), reverse("courses:course_edit", args=[c.slug]), reverse("courses:competencies", args=[c.slug]),
            reverse("courses:module_create", args=[c.slug]), reverse("courses:module_edit", args=[self.module1.pk]),
            reverse("courses:topic_create", args=[self.module1.pk]), reverse("courses:topic_edit", args=[self.topic1.pk]),
            self.quiz.get_absolute_url(), self.pre.get_absolute_url(), reverse("assessments:quiz_create", args=[c.slug]) + "?tur=pretest",
            reverse("assessments:quiz_edit", args=[self.quiz.pk]), reverse("assessments:question_create", args=[self.quiz.pk]),
            reverse("assessments:question_edit", args=[q.pk]), Attempt.objects.first().get_absolute_url(),
            self.a1.get_absolute_url(), self.final.get_absolute_url(), reverse("assessments:assignment_edit", args=[self.a1.pk]),
            reverse("assessments:assignment_create", args=[c.slug]) + f"?tur=module&modul={self.module1.pk}",
            self.sub.get_absolute_url(), self.sub.get_absolute_url() + "?path=project/main.py&line=3",
            reverse("assessments:submission_grade", args=[self.sub.pk]), reverse("assessments:plagiarism_list"),
            reverse("gamification:leaderboard", args=[c.slug]), reverse("analytics:course_analytics", args=[c.slug]),
            reverse("analytics:growth_student", args=[c.slug, self.s1.pk]), reverse("community:thread_list"),
            reverse("community:inbox"), reverse("community:chat_room", args=[self.room.pk]), reverse("accounts:profile"),
            reverse("accounts:profile_public", args=["student1"]),
        ]
        with track_missing_variables() as misses:
            self.check(self.teacher, urls)
        self.assertEqual(unexpected(misses), set(), "Shablonlarda aniqlanmagan o'zgaruvchi bor")

    def test_teacher_sees_grade_flags_and_comment_controls(self):
        """Regressiya: o'qituvchi uchun Baholash tugmasi, plagiat bo'limi va izoh formasi ko'rinishi shart."""
        flag_sub = PlagiarismFlag.objects.first().submission_a
        self.client.force_login(self.teacher)
        resp = self.client.get(flag_sub.get_absolute_url())
        self.assertContains(resp, reverse("assessments:submission_grade", args=[flag_sub.pk]))
        self.assertContains(resp, "Plagiat ogohlantirishlari")
        self.assertContains(resp, 'id="cform"')
        self.client.force_login(self.s1)
        resp = self.client.get(self.sub.get_absolute_url())
        self.assertNotContains(resp, 'id="cform"')
        self.assertNotContains(resp, "Plagiat ogohlantirishlari")

    def test_admin_pages(self):
        admin = User.objects.get(username="admin")
        urls = [reverse("home"), reverse("accounts:admin_panel"), reverse("accounts:admin_panel") + "?holat=pending&rol=teacher&q=teacher",
                self.course.get_absolute_url(), reverse("analytics:course_analytics", args=[self.course.slug]),
                reverse("assessments:plagiarism_list"), reverse("courses:my_students"), reverse("analytics:overview"),
                reverse("accounts:design_center"), reverse("accounts:chat_routing")]
        with track_missing_variables() as misses:
            self.check(admin, urls)
        self.assertEqual(unexpected(misses), set())
        self.check(admin, [reverse("admin:index")])   # Unfold sahifalari — o'z shablonlari, faqat 200 tekshiriladi

    def test_public_pages(self):
        for url in (reverse("home"), reverse("accounts:login"), reverse("accounts:register")):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_seed_demo_is_idempotent(self):
        before = User.objects.count()
        call_command("seed_demo", verbosity=0)
        self.assertEqual(User.objects.count(), before)
