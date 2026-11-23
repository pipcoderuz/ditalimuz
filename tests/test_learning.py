import time
from datetime import timedelta
from unittest import mock

from django.core import signing
from django.urls import reverse
from django.utils import timezone

from accounts.models import PlatformSettings
from assessments.models import Attempt, Submission
from community.models import Notification
from courses.access import CourseState
from courses.models import Certificate, Enrollment, TopicProgress
from gamification.models import UserBadge

from .helpers import (
    FakePost, BaseTest, answers, enroll, full_course, mk_assignment, mk_quiz, mk_user, pass_pretest, take, zip_upload,
)


def set_progressive(on):
    s = PlatformSettings.get()
    s.progressive_learning = on
    s.save()


class AccessRulesTests(BaseTest):
    def setUp(self):
        self.teacher = mk_user("t1", "teacher")
        self.student = mk_user("s1")
        self.ctx = full_course(self.teacher)
        self.login(self.student)

    def topic_status(self, topic):
        return self.client.get(topic.get_absolute_url()).status_code

    def test_not_enrolled_cannot_open_topic(self):
        self.assertEqual(self.topic_status(self.ctx.t1), 302)
        self.assertFalse(CourseState(self.student, self.ctx.course).topic_access(self.ctx.t1))

    def test_pretest_is_mandatory_before_modules(self):
        enroll(self.ctx.course, self.student)
        self.assertEqual(self.topic_status(self.ctx.t1), 302)
        resp = self.client.get(self.ctx.t1.get_absolute_url(), follow=True)
        self.assertContains(resp, "kirish testini")
        pass_pretest(self.ctx, self.student)
        self.assertEqual(self.topic_status(self.ctx.t1), 200)

    def test_course_not_started_blocks_content(self):
        ctx = full_course(self.teacher, start=10, slug="kelajak")
        enroll(ctx.course, self.student)
        self.assertEqual(self.client.get(ctx.t1.get_absolute_url()).status_code, 302)
        self.assertIn("boshlanadi", CourseState(self.student, ctx.course).module_access(ctx.m1).reason)

    def test_progressive_topic_sequence(self):
        enroll(self.ctx.course, self.student)
        pass_pretest(self.ctx, self.student)
        self.assertEqual(self.topic_status(self.ctx.t2), 302)  # t1 tugatilmagan
        resp = self.client.post(reverse("courses:topic_complete", args=[self.ctx.t1.pk]))
        self.assertRedirects(resp, self.ctx.t2.get_absolute_url())
        self.assertEqual(self.topic_status(self.ctx.t2), 200)
        self.assertTrue(TopicProgress.objects.filter(student=self.student, topic=self.ctx.t1).exists())

    def test_cannot_complete_locked_topic_by_post(self):
        enroll(self.ctx.course, self.student)
        pass_pretest(self.ctx, self.student)
        self.client.post(reverse("courses:topic_complete", args=[self.ctx.t2.pk]))
        self.assertFalse(TopicProgress.objects.filter(topic=self.ctx.t2).exists())

    def test_module2_requires_module1_topics_quiz_and_assignment(self):
        ctx = self.ctx
        # m2 sanasi ham o'tgan bo'lsin — baribir progressiv rejimda mastery talab qilinadi
        ctx.m2.start_date = timezone.localdate() - timedelta(days=1)
        ctx.m2.save()
        enroll(ctx.course, self.student)
        pass_pretest(ctx, self.student)
        state = lambda: CourseState(self.student, ctx.course)
        self.assertFalse(state().module_access(ctx.m2))
        TopicProgress.objects.create(student=self.student, topic=ctx.t1)
        TopicProgress.objects.create(student=self.student, topic=ctx.t2)
        self.assertFalse(state().module_access(ctx.m2))           # test va topshiriq hali yo'q
        take(self.client, ctx.quiz1, answers(ctx.q1_items, [True, True]))
        self.assertFalse(state().module_access(ctx.m2))           # topshiriqdan o'tilmagan
        Submission.objects.create(assignment=ctx.a1, student=self.student, passed=True, status="graded", total_score=90, percent=90)
        self.assertTrue(state().module_access(ctx.m2))
        self.assertEqual(self.topic_status(ctx.t3), 200)

    def test_failed_quiz_does_not_unlock(self):
        ctx = self.ctx
        enroll(ctx.course, self.student)
        pass_pretest(ctx, self.student)
        for t in (ctx.t1, ctx.t2):
            TopicProgress.objects.create(student=self.student, topic=t)
        Submission.objects.create(assignment=ctx.a1, student=self.student, passed=True, status="graded")
        take(self.client, ctx.quiz1, answers(ctx.q1_items, [False, False]))
        self.assertFalse(CourseState(self.student, ctx.course).module_access(ctx.m2))

    def test_quiz_locked_until_topics_done_in_progressive_mode(self):
        enroll(self.ctx.course, self.student)
        pass_pretest(self.ctx, self.student)
        resp = self.client.get(self.ctx.quiz1.get_absolute_url(), follow=True)
        self.assertContains(resp, "mavzularini tugating")
        self.assertEqual(self.client.get(reverse("assessments:quiz_take", args=[self.ctx.quiz1.pk])).status_code, 302)

    def test_non_progressive_mode_frees_topics_but_keeps_schedule(self):
        ctx = self.ctx
        set_progressive(False)
        enroll(ctx.course, self.student)
        pass_pretest(ctx, self.student)  # kirish testi baribir majburiy
        self.assertEqual(self.topic_status(ctx.t2), 200)          # ketma-ketlik talab qilinmaydi
        self.assertEqual(self.client.get(reverse("assessments:quiz_take", args=[ctx.quiz1.pk])).status_code, 200)
        self.assertEqual(self.topic_status(ctx.t3), 302)          # m2 sanasi hali kelmagan (+40 kun)
        ctx.m2.start_date = timezone.localdate()
        ctx.m2.save()
        self.assertEqual(self.topic_status(ctx.t3), 200)          # sanasi kelgach, mastery'siz ochiladi

    def test_non_progressive_pretest_still_mandatory(self):
        set_progressive(False)
        enroll(self.ctx.course, self.student)
        self.assertEqual(self.topic_status(self.ctx.t1), 302)

    def test_toggle_takes_effect_immediately(self):
        enroll(self.ctx.course, self.student)
        pass_pretest(self.ctx, self.student)
        self.assertEqual(self.topic_status(self.ctx.t2), 302)
        admin = mk_user("boss", "admin")
        self.login(admin)
        self.client.post(reverse("accounts:settings_update"), {"plagiarism_threshold": 70})  # o'chirish
        self.login(self.student)
        self.assertEqual(self.topic_status(self.ctx.t2), 200)

    def test_final_requires_all_modules_when_progressive(self):
        enroll(self.ctx.course, self.student)
        pass_pretest(self.ctx, self.student)
        self.assertFalse(CourseState(self.student, self.ctx.course).final_access())
        resp = self.client.get(self.ctx.final.get_absolute_url(), follow=True)
        self.assertContains(resp, "barcha modullarni")

    def test_final_open_when_not_progressive(self):
        set_progressive(False)
        enroll(self.ctx.course, self.student)
        pass_pretest(self.ctx, self.student)
        self.assertTrue(CourseState(self.student, self.ctx.course).final_access())

    def test_teacher_and_admin_unrestricted(self):
        for u in (self.teacher, mk_user("boss", "admin")):
            self.login(u)
            self.assertEqual(self.client.get(self.ctx.t3.get_absolute_url()).status_code, 200)
            self.assertEqual(self.client.get(self.ctx.final.get_absolute_url()).status_code, 200)

    def test_other_teacher_cannot_manage(self):
        other = mk_user("t2", "teacher")
        self.login(other)
        self.assertEqual(self.client.get(reverse("courses:course_edit", args=[self.ctx.course.slug])).status_code, 403)
        self.assertEqual(self.client.get(self.ctx.quiz1.get_absolute_url()).status_code, 403)
        self.assertEqual(self.client.get(self.ctx.a1.get_absolute_url()).status_code, 403)


class ReadOnlyTests(BaseTest):
    def setUp(self):
        self.teacher = mk_user("t1", "teacher")
        self.student = mk_user("s1")
        self.ctx = full_course(self.teacher)
        self.enr = enroll(self.ctx.course, self.student)
        self.login(self.student)

    def test_after_completion_materials_open_but_no_submissions(self):
        ctx = self.ctx
        self.enr.status = Enrollment.Status.COMPLETED
        self.enr.save()
        state = CourseState(self.student, ctx.course)
        self.assertTrue(state.read_only)
        # progressiv qoidalar va kirish testidan qat'i nazar, materiallar ochiq
        self.assertEqual(self.client.get(ctx.t3.get_absolute_url()).status_code, 200)
        self.assertContains(self.client.get(ctx.t3.get_absolute_url()), "Faqat ko'rish rejimi")
        resp = self.client.get(reverse("assessments:quiz_take", args=[ctx.quiz1.pk]), follow=True)
        self.assertContains(resp, "ko&#x27;rish rejimida")
        self.assertEqual(Attempt.objects.count(), 0)
        resp = self.client.post(ctx.a1.get_absolute_url(), {"method": "zip", "zip_file": zip_upload({"a.py": "x=1"})}, follow=True)
        self.assertEqual(Submission.objects.count(), 0)
        self.assertContains(resp, "ko&#x27;rish rejimi")
        # mavzuni "tugatdim" deb belgilab bo'lmaydi
        self.client.post(reverse("courses:topic_complete", args=[ctx.t1.pk]))
        self.assertFalse(TopicProgress.objects.exists())

    def test_after_course_end_date_read_only(self):
        ctx = self.ctx
        ctx.course.end_date = timezone.localdate() - timedelta(days=1)
        ctx.course.save()
        self.assertTrue(CourseState(self.student, ctx.course).read_only)
        self.assertEqual(self.client.get(ctx.t1.get_absolute_url()).status_code, 200)
        take(self.client, ctx.pre, answers(ctx.pre_items, [True] * 4))
        self.assertEqual(Attempt.objects.count(), 0)

    def test_cannot_enroll_in_finished_course(self):
        ctx = full_course(self.teacher, start=-50, end=-1, slug="eski")
        self.client.post(reverse("courses:enroll", args=[ctx.course.slug]))
        self.assertFalse(Enrollment.objects.filter(course=ctx.course, student=self.student).exists())


class QuizTests(BaseTest):
    def setUp(self):
        self.teacher = mk_user("t1", "teacher")
        self.student = mk_user("s1")
        self.ctx = full_course(self.teacher)
        enroll(self.ctx.course, self.student)
        pass_pretest(self.ctx, self.student)
        for t in (self.ctx.t1, self.ctx.t2):
            TopicProgress.objects.create(student=self.student, topic=t)
        self.login(self.student)

    def test_auto_grading_and_score_scaling(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1, n=4, max_score=50, pass_score=30)
        resp = take(self.client, quiz, answers(items, [True, True, True, False]))
        attempt = Attempt.objects.get(quiz=quiz)
        self.assertRedirects(resp, attempt.get_absolute_url())
        self.assertEqual((attempt.score, attempt.percent, attempt.passed), (37.5, 75.0, True))
        self.assertEqual(attempt.answers.filter(is_correct=True).count(), 3)

    def test_fail_below_pass_score(self):
        take(self.client, self.ctx.quiz1, answers(self.ctx.q1_items, [True, False]))
        a = Attempt.objects.get(quiz=self.ctx.quiz1)
        self.assertEqual((a.score, a.passed), (50.0, False))  # 50 < 60

    def test_multiple_choice_is_all_or_nothing(self):
        from assessments.models import Choice, Question
        quiz, _ = mk_quiz(self.ctx.course, self.ctx.m1, n=0)
        q = Question.objects.create(quiz=quiz, text="Ko'p", kind="multiple")
        a = Choice.objects.create(question=q, text="a", is_correct=True)
        b = Choice.objects.create(question=q, text="b", is_correct=True)
        c = Choice.objects.create(question=q, text="c", is_correct=False)
        take(self.client, quiz, {f"q_{q.pk}": [a.id]})
        take(self.client, quiz, {f"q_{q.pk}": [a.id, b.id, c.id]})
        take(self.client, quiz, {f"q_{q.pk}": [a.id, b.id]})
        scores = list(Attempt.objects.filter(quiz=quiz).order_by("id").values_list("score", flat=True))
        self.assertEqual(scores, [0.0, 0.0, 100.0])

    def test_attempt_limit(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1, max_attempts=2)
        for _ in range(3):
            take(self.client, quiz, answers(items, [False, False]))
        self.assertEqual(Attempt.objects.filter(quiz=quiz).count(), 2)

    def test_unlimited_attempts(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1, max_attempts=0)
        for _ in range(5):
            take(self.client, quiz, answers(items, [False, False]))
        self.assertEqual(Attempt.objects.filter(quiz=quiz).count(), 5)

    def test_pretest_only_once(self):
        take(self.client, self.ctx.pre, answers(self.ctx.pre_items, [True] * 4))
        self.assertEqual(Attempt.objects.filter(quiz=self.ctx.pre).count(), 1)  # setUp'dagi bitta

    def test_invalid_and_foreign_choices_ignored(self):
        other, other_items = mk_quiz(self.ctx.course, self.ctx.m1)
        data = {f"q_{q.pk}": other_items[0][1] for q, _, _ in self.ctx.q1_items}  # boshqa test variantlari
        take(self.client, self.ctx.quiz1, data)
        self.assertEqual(Attempt.objects.get(quiz=self.ctx.quiz1).score, 0)

    def test_correct_answers_hidden_until_passed_or_exhausted(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1, max_attempts=2)
        take(self.client, quiz, answers(items, [False, False]))
        att = Attempt.objects.get(quiz=quiz)
        self.assertNotContains(self.client.get(att.get_absolute_url()), "to'g'ri ✓")
        take(self.client, quiz, answers(items, [False, False]))      # urinishlar tugadi
        self.assertContains(self.client.get(att.get_absolute_url()), "✓")

    def test_pretest_result_does_not_reveal_answers(self):
        att = Attempt.objects.get(quiz=self.ctx.pre)
        resp = self.client.get(att.get_absolute_url())
        self.assertContains(resp, "Kirish testi topshirildi")
        self.assertNotContains(resp, "sizning javobingiz")

    def test_others_cannot_see_result(self):
        att = Attempt.objects.get(quiz=self.ctx.pre)
        self.login(mk_user("s2"))
        self.assertEqual(self.client.get(att.get_absolute_url()).status_code, 403)
        self.login(self.teacher)
        self.assertEqual(self.client.get(att.get_absolute_url()).status_code, 200)

    def test_time_limit_enforced_server_side(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1, time_limit_minutes=5)
        url = reverse("assessments:quiz_take", args=[quiz.pk])
        stale = signing.dumps({"t": time.time() - 3600, "q": quiz.pk, "u": self.student.pk}, salt="quiz")
        resp = self.client.post(url, {"token": stale, **answers(items, [True, True])}, follow=True)
        self.assertContains(resp, "Vaqt tugagan")
        self.assertEqual(Attempt.objects.filter(quiz=quiz).count(), 0)
        fresh = self.client.get(url).context["token"]
        self.client.post(url, {"token": fresh, **answers(items, [True, True])})
        self.assertEqual(Attempt.objects.filter(quiz=quiz).count(), 1)

    def test_tampered_token_treated_as_now(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1)
        self.client.post(reverse("assessments:quiz_take", args=[quiz.pk]), {"token": "bad", **answers(items, [True, True])})
        self.assertEqual(Attempt.objects.get(quiz=quiz).score, 100)

    def test_quiz_without_questions_not_takeable(self):
        quiz, _ = mk_quiz(self.ctx.course, self.ctx.m1, n=0)
        self.assertEqual(self.client.get(reverse("assessments:quiz_take", args=[quiz.pk])).status_code, 302)


class CompletionTests(BaseTest):
    def setUp(self):
        self.teacher = mk_user("t1", "teacher")
        self.student = mk_user("s1")
        self.ctx = full_course(self.teacher)
        self.enr = enroll(self.ctx.course, self.student)
        set_progressive(False)  # to'g'ridan-to'g'ri yakuniy loyihaga o'tish uchun
        pass_pretest(self.ctx, self.student)

    def submit_and_grade(self, scores):
        self.login(self.student)
        self.client.post(self.ctx.final.get_absolute_url(), {"method": "zip", "zip_file": zip_upload({"main.py": "print(1)\n"})})
        sub = Submission.objects.get(assignment=self.ctx.final)
        self.login(self.teacher)
        data = {f"s_{c.pk}": sc for c, sc in zip(self.ctx.final.criteria.all(), scores)}
        self.client.post(reverse("assessments:submission_grade", args=[sub.pk]), {**data, "teacher_comment": "ok"})
        return Submission.objects.get(pk=sub.pk)

    def test_pass_final_completes_course_and_issues_certificate(self):
        sub = self.submit_and_grade([40, 25, 25])  # 90 >= 60
        self.assertTrue(sub.passed)
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.status, "completed")
        cert = Certificate.objects.get(enrollment=self.enr)
        self.assertEqual(cert.final_percent, 90.0)
        self.assertTrue(UserBadge.objects.filter(user=self.student, code="graduate").exists())
        self.assertTrue(Notification.objects.filter(user=self.student, text__contains="Sertifikatingiz").exists())
        # sertifikat ochiq sahifa
        self.client.logout()
        resp = self.client.get(cert.get_absolute_url())
        self.assertContains(resp, "S1 Test")
        self.assertContains(resp, cert.code)
        self.assertEqual(self.client.get(cert.get_absolute_url().replace(cert.code, "NOPE12345X")).status_code, 404)
        # endi read-only
        self.assertTrue(CourseState(self.student, self.ctx.course).read_only)

    def test_fail_final_does_not_complete(self):
        sub = self.submit_and_grade([10, 10, 10])  # 30 < 60
        self.assertFalse(sub.passed)
        self.enr.refresh_from_db()
        self.assertEqual(self.enr.status, "active")
        self.assertFalse(Certificate.objects.exists())
        # qayta topshirish mumkin
        self.login(self.student)
        resp = self.client.get(self.ctx.final.get_absolute_url())
        self.assertContains(resp, "Ishni topshirish")

    def test_regrade_does_not_duplicate_certificate(self):
        sub = self.submit_and_grade([40, 30, 30])
        self.login(self.teacher)
        data = {f"s_{c.pk}": 20 for c in self.ctx.final.criteria.all()}
        self.client.post(reverse("assessments:submission_grade", args=[sub.pk]), data)
        self.assertEqual(Certificate.objects.count(), 1)

    def test_module_unlock_notification_not_duplicated(self):
        from courses.services import notify_module_unlocked
        set_progressive(True)
        ctx = self.ctx
        for t in (ctx.t1, ctx.t2):
            TopicProgress.objects.create(student=self.student, topic=t)
        self.login(self.student)
        take(self.client, ctx.quiz1, answers(ctx.q1_items, [True, True]))
        Submission.objects.create(assignment=ctx.a1, student=self.student, passed=True, status="graded")
        notify_module_unlocked(self.student, ctx.course, ctx.m1)
        notify_module_unlocked(self.student, ctx.course, ctx.m1)
        self.assertEqual(Notification.objects.filter(user=self.student, text__contains="Yangi modul ochildi").count(), 1)

    def test_new_topic_notifies_enrolled_students(self):
        from courses.models import Topic
        self.login(self.teacher)
        self.client.post(reverse("courses:topic_create", args=[self.ctx.m2.pk]), {"title": "Yangi dars", "content": "x", "order": ""})
        self.assertTrue(Topic.objects.filter(title="Yangi dars").exists())
        self.assertTrue(Notification.objects.filter(user=self.student, text__contains="Yangi dars qo'shildi").exists())


class CourseManagementTests(BaseTest):
    def setUp(self):
        self.teacher = mk_user("t1", "teacher")
        self.login(self.teacher)

    def test_create_course_module_topic(self):
        today = timezone.localdate()
        resp = self.client.post(reverse("courses:course_create"), {
            "title": "Yangi Kurs!", "description": "d", "start_date": today, "end_date": today + timedelta(days=60), "is_published": "on"})
        from courses.models import Course
        course = Course.objects.get(title="Yangi Kurs!")
        self.assertRedirects(resp, course.get_absolute_url())
        self.assertEqual((course.teacher, course.slug), (self.teacher, "yangi-kurs"))
        resp = self.client.post(reverse("courses:module_create", args=[course.slug]), {
            "title": "M", "description": "", "order": "", "start_date": today, "end_date": today + timedelta(days=20)})
        module = course.modules.get()
        self.assertEqual(module.order, 1)
        self.client.post(reverse("courses:topic_create", args=[module.pk]), {"title": "T", "content": "c", "order": "", "video_url": "https://youtu.be/abc123"})
        topic = module.topics.get()
        self.assertEqual(topic.embed_url, "https://www.youtube.com/embed/abc123")

    def test_module_dates_must_fit_course(self):
        ctx = full_course(self.teacher)
        today = timezone.localdate()
        base = {"title": "X", "description": "", "order": ""}
        self.client.post(reverse("courses:module_create", args=[ctx.course.slug]), {**base, "start_date": today - timedelta(days=500), "end_date": today})
        self.client.post(reverse("courses:module_create", args=[ctx.course.slug]), {**base, "start_date": today, "end_date": today - timedelta(days=1)})
        self.assertEqual(ctx.course.modules.count(), 2)

    def test_course_end_before_start_rejected(self):
        today = timezone.localdate()
        self.client.post(reverse("courses:course_create"), {"title": "Z", "description": "d", "start_date": today, "end_date": today - timedelta(days=1)})
        from courses.models import Course
        self.assertFalse(Course.objects.filter(title="Z").exists())

    def test_unique_slug(self):
        today = timezone.localdate()
        data = {"title": "Bir xil", "description": "d", "start_date": today, "end_date": today + timedelta(days=5)}
        self.client.post(reverse("courses:course_create"), data)
        self.client.post(reverse("courses:course_create"), data)
        from courses.models import Course
        self.assertEqual(sorted(Course.objects.values_list("slug", flat=True)), ["bir-xil", "bir-xil-2"])

    def test_students_cannot_create(self):
        self.login(mk_user("s1"))
        self.assertEqual(self.client.get(reverse("courses:course_create")).status_code, 403)

    def test_unpublished_course_hidden_from_students(self):
        ctx = full_course(self.teacher)
        ctx.course.is_published = False
        ctx.course.save()
        self.login(mk_user("s1"))
        self.assertEqual(self.client.get(ctx.course.get_absolute_url()).status_code, 403)
        self.assertNotContains(self.client.get(reverse("courses:course_list")), "Kurs</a>")

    def test_single_pretest_per_course(self):
        ctx = full_course(self.teacher)
        resp = self.client.post(reverse("assessments:quiz_create", args=[ctx.course.slug]) + "?tur=pretest", {
            "kind": "pretest", "title": "Ikkinchi", "max_score": 100, "pass_score": 0, "max_attempts": 1, "required": "on"})
        self.assertEqual(ctx.course.quizzes.filter(kind="pretest").count(), 1)
        self.assertContains(resp, "allaqachon mavjud")
