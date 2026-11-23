"""Mavzu darajasidagi test/topshiriq/savol, kurs yakuni variantlari (test / loyiha / ikkalasi / hech biri),
ixtiyoriy sanalar va talabaning kursni boshlagan vaqti (started_at)."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.models import PlatformSettings
from assessments.models import Assignment, Attempt, OpenAnswer, OpenQuestion, Quiz, Submission
from community.models import Notification
from courses.access import CourseState
from courses.models import Certificate, Course, Enrollment, Module, TopicProgress
from gamification import services as gamification

from .helpers import (
    BaseTest, FakePost, answers, enroll, full_course, mk_assignment, mk_quiz, mk_user, pass_pretest, take, zip_upload,
)


def make_open_question(ctx, topic, text="Sikl nima?", max_score=10, pass_score=6, required=True):
    return OpenQuestion.objects.create(course=ctx.course, topic=topic, text=text, max_score=max_score, pass_score=pass_score, required=required)


class TopicBase(BaseTest):
    def setUp(self):
        self.teacher, self.other_teacher = mk_user("t1", "teacher"), mk_user("t2", "teacher")
        self.s1, self.s2 = mk_user("s1"), mk_user("s2")
        self.ctx = full_course(self.teacher)
        self.course, self.t1, self.t2 = self.ctx.course, self.ctx.t1, self.ctx.t2
        self.enr = enroll(self.course, self.s1)
        pass_pretest(self.ctx, self.s1)
        self.login(self.s1)

    def page(self, topic=None):
        return self.client.get((topic or self.t1).get_absolute_url())

    def complete(self, topic=None):
        return self.client.post(reverse("courses:topic_complete", args=[(topic or self.t1).pk]))

    def answer(self, q, text="Sikl — takrorlash"):
        return self.client.post(reverse("assessments:open_answer_submit", args=[q.pk]), {"text": text})

    def grade_answer(self, a, score, feedback="Izoh", as_user=None):
        self.login(as_user or self.teacher)
        return self.client.post(reverse("assessments:open_answer_grade", args=[a.pk]), {"score": score, "feedback": feedback})


class TopicQuizTests(TopicBase):
    def test_required_topic_quiz_blocks_completion_until_passed(self):
        quiz, items = mk_quiz(self.course, None, "topic", topic=self.t1)
        resp = self.page()
        self.assertTrue(resp.context["blocked_by_items"])
        self.assertFalse(resp.context["can_complete"])
        self.assertContains(resp, "majburiy topshiriqlardan")
        self.complete()
        self.assertFalse(TopicProgress.objects.filter(student=self.s1, topic=self.t1).exists())
        take(self.client, quiz, answers(items, [False, False]))      # o'tmadi
        self.assertFalse(self.page().context["can_complete"])
        take(self.client, quiz, answers(items, [True, True]))        # o'tdi
        resp = self.page()
        self.assertTrue(resp.context["can_complete"])
        self.assertFalse(resp.context["blocked_by_items"])
        self.assertRedirects(self.complete(), self.t2.get_absolute_url())
        self.assertTrue(TopicProgress.objects.filter(student=self.s1, topic=self.t1).exists())

    def test_optional_item_does_not_block(self):
        mk_quiz(self.course, None, "topic", topic=self.t1, required=False)
        resp = self.page()
        self.assertTrue(resp.context["can_complete"])

    def test_grades_panel_shows_each_item_score(self):
        quiz, items = mk_quiz(self.course, None, "topic", topic=self.t1, max_score=50, pass_score=30)
        take(self.client, quiz, answers(items, [True, False]))
        resp = self.page()
        grades = resp.context["grades"]
        self.assertEqual(len(grades), 1)
        self.assertEqual((grades[0]["score"], grades[0]["max"]), (25.0, 50))
        self.assertContains(resp, "Mening baholarim")
        item = next(i for i in resp.context["items"] if i["kind"] == "quiz")
        self.assertEqual(item["status"], "failed")

    def test_items_are_locked_with_their_topic(self):
        quiz, _ = mk_quiz(self.course, None, "topic", topic=self.t2)   # t2 ochiq emas (t1 tugatilmagan)
        self.assertEqual(self.client.get(quiz.get_absolute_url()).status_code, 302)
        self.assertEqual(self.client.get(reverse("assessments:quiz_take", args=[quiz.pk])).status_code, 302)
        self.assertFalse(CourseState(self.s1, self.course).quiz_access(quiz))

    def test_topic_quiz_passing_does_not_complete_module_alone(self):
        quiz, items = mk_quiz(self.course, None, "topic", topic=self.t1)
        take(self.client, quiz, answers(items, [True, True]))
        self.assertFalse(CourseState(self.s1, self.course).module_passed(self.ctx.m1))


class TopicAssignmentTests(TopicBase):
    def test_topic_assignment_flow_and_completion(self):
        a = mk_assignment(self.course, None, "topic", topic=self.t1)
        self.assertTrue(self.page().context["blocked_by_items"])
        self.client.post(a.get_absolute_url(), {"method": "zip", "zip_file": zip_upload({"main.py": "print(1)\n"})})
        sub = Submission.objects.get()
        item = next(i for i in self.page().context["items"] if i["kind"] == "assignment")
        self.assertEqual(item["status"], "pending")
        self.login(self.teacher)
        data = {f"s_{c.pk}": m for c, m in zip(a.criteria.all(), [40, 30, 30])}
        self.client.post(reverse("assessments:submission_grade", args=[sub.pk]), data)
        self.login(self.s1)
        resp = self.page()
        self.assertTrue(resp.context["can_complete"])
        self.assertEqual(resp.context["grades"][0]["score"], 100)

    def test_failed_topic_assignment_keeps_topic_blocked(self):
        a = mk_assignment(self.course, None, "topic", topic=self.t1)
        self.client.post(a.get_absolute_url(), {"method": "zip", "zip_file": zip_upload({"main.py": "x=1\n"})})
        sub = Submission.objects.get()
        self.login(self.teacher)
        self.client.post(reverse("assessments:submission_grade", args=[sub.pk]), {f"s_{c.pk}": 1 for c in a.criteria.all()})
        self.login(self.s1)
        self.assertTrue(self.page().context["blocked_by_items"])

    def test_topic_assignment_due_falls_back_to_module(self):
        a = mk_assignment(self.course, None, "topic", topic=self.t1, due_days=0)
        a.due_date = None
        a.save()
        self.assertEqual(a.effective_due, self.ctx.m1.end_date)


class OpenQuestionTests(TopicBase):
    def test_answer_grade_pass_flow(self):
        q = make_open_question(self.ctx, self.t1)
        self.answer(q)
        a = OpenAnswer.objects.get()
        self.assertEqual((a.status, a.passed), ("submitted", None))
        self.assertTrue(Notification.objects.filter(user=self.teacher, text__contains="savolga javob berdi").exists())
        item = next(i for i in self.page().context["items"] if i["kind"] == "question")
        self.assertEqual(item["status"], "pending")
        self.assertTrue(self.page().context["blocked_by_items"])
        self.grade_answer(a, 8, "Yaxshi javob")
        a.refresh_from_db()
        self.assertEqual((a.status, a.score, a.passed, a.graded_by), ("graded", 8, True, self.teacher))
        self.assertTrue(Notification.objects.filter(user=self.s1, text__contains="8/10").exists())
        self.login(self.s1)
        resp = self.page()
        self.assertContains(resp, "Yaxshi javob")                   # o'qituvchi izohi mavzu sahifasida
        self.assertTrue(resp.context["can_complete"])
        self.assertEqual(resp.context["grades"][0]["score"], 8)

    def test_fail_then_resubmit_then_pass(self):
        q = make_open_question(self.ctx, self.t1)
        self.answer(q, "Birinchi")
        a = OpenAnswer.objects.get()
        self.grade_answer(a, 2)
        self.login(self.s1)
        self.answer(q, "Yaxshilangan javob")
        a.refresh_from_db()
        self.assertEqual((a.text, a.status, a.score, a.passed), ("Yaxshilangan javob", "submitted", None, None))  # baho tozalandi
        self.assertEqual(OpenAnswer.objects.count(), 1)
        self.grade_answer(a, 9)
        self.login(self.s1)
        self.answer(q, "O'tgandan keyin o'zgartirmoqchi")
        a.refresh_from_db()
        self.assertEqual(a.text, "Yaxshilangan javob")              # o'tgan javobni o'zgartirib bo'lmaydi

    def test_validation_and_permissions(self):
        q = make_open_question(self.ctx, self.t1)
        self.answer(q, "   ")
        self.assertEqual(OpenAnswer.objects.count(), 0)
        self.answer(q)
        a = OpenAnswer.objects.get()
        self.grade_answer(a, 11)                                    # maksimaldan katta
        a.refresh_from_db()
        self.assertEqual(a.status, "submitted")
        self.assertEqual(self.grade_answer(a, 5, as_user=self.s1).status_code, 403)
        self.assertEqual(self.grade_answer(a, 5, as_user=self.other_teacher).status_code, 403)
        self.assertEqual(self.client.get(reverse("assessments:open_question_answers", args=[q.pk])).status_code, 403)
        self.login(self.teacher)
        self.assertContains(self.client.get(reverse("assessments:open_question_answers", args=[q.pk])), "Sikl — takrorlash")

    def test_cannot_answer_locked_topic_or_when_read_only(self):
        q2 = make_open_question(self.ctx, self.t2)                  # t2 yopiq
        self.answer(q2)
        self.assertEqual(OpenAnswer.objects.count(), 0)
        q1 = make_open_question(self.ctx, self.t1)
        self.enr.status = Enrollment.Status.COMPLETED
        self.enr.save()
        self.answer(q1)
        self.assertEqual(OpenAnswer.objects.count(), 0)

    def test_teacher_manages_open_questions(self):
        self.login(self.teacher)
        url = reverse("assessments:open_question_create", args=[self.t1.pk])
        self.client.post(url, {"text": "<p>Yangi <script>x</script>savol</p>", "max_score": 10, "pass_score": 20, "required": "on"})
        self.assertEqual(OpenQuestion.objects.count(), 0)           # o'tish bali maksimaldan katta
        self.client.post(url, {"text": "<p>Yangi <script>x</script>savol</p>", "max_score": 10, "pass_score": 6, "required": "on"})
        q = OpenQuestion.objects.get()
        self.assertNotIn("script", q.text)                          # rich text tozalangan
        self.assertEqual((q.course, q.topic, q.order), (self.course, self.t1, 1))
        self.client.post(reverse("assessments:open_question_edit", args=[q.pk]), {"text": "Tahrirlandi", "max_score": 20, "pass_score": 10, "required": "on"})
        q.refresh_from_db()
        self.assertEqual((q.text, q.max_score), ("Tahrirlandi", 20))
        self.login(self.other_teacher)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.teacher)
        self.client.post(reverse("assessments:open_question_delete", args=[q.pk]))
        self.assertEqual(OpenQuestion.objects.count(), 0)

    def test_manager_topic_page_lists_all_item_types(self):
        mk_quiz(self.course, None, "topic", topic=self.t1)
        mk_assignment(self.course, None, "topic", topic=self.t1)
        make_open_question(self.ctx, self.t1)
        self.login(self.teacher)
        resp = self.client.get(self.t1.get_absolute_url())
        self.assertEqual((len(resp.context["quizzes"]), len(resp.context["assignments"]), len(resp.context["open_questions"])), (1, 1, 1))

    def test_open_answers_count_in_leaderboard(self):
        q = make_open_question(self.ctx, self.t1)
        self.answer(q)
        self.grade_answer(OpenAnswer.objects.get(), 8)
        row = next(r for r in gamification.leaderboard(self.course) if r["student"] == self.s1)
        self.assertEqual(row["points"], 8)


class QuizCreationTargetsTests(TopicBase):
    def create(self, query, **extra):
        self.login(self.teacher)
        data = {"title": "Yangi test", "description": "", "max_score": 100, "pass_score": 60, "max_attempts": 3, "required": "on", **extra}
        return self.client.post(reverse("assessments:quiz_create", args=[self.course.slug]) + query, data)

    def test_topic_module_final_and_pretest_targets(self):
        self.course.quizzes.filter(kind="pretest").delete()
        self.create(f"?tur=topic&mavzu={self.t2.pk}", title="Mavzu testi")
        t = Quiz.objects.get(title="Mavzu testi")
        self.assertEqual((t.kind, t.topic, t.module), ("topic", self.t2, None))
        self.create(f"?tur=module&modul={self.ctx.m2.pk}", title="Modul testi")
        m = Quiz.objects.get(title="Modul testi")
        self.assertEqual((m.kind, m.module, m.topic), ("module", self.ctx.m2, None))
        self.create("?tur=final", title="Yakuniy")
        f = Quiz.objects.get(title="Yakuniy")
        self.assertEqual((f.kind, f.module, f.topic), ("final", None, None))
        self.create("?tur=pretest", title="Kirish", max_attempts=5)
        p = Quiz.objects.get(title="Kirish")
        self.assertEqual((p.kind, p.max_attempts), ("pretest", 1))   # kirish testi har doim bir urinish

    def test_only_one_final_quiz(self):
        self.create("?tur=final", title="Birinchi")
        self.create("?tur=final", title="Ikkinchi")
        self.assertEqual(Quiz.objects.filter(kind="final").count(), 1)

    def test_invalid_target_ids(self):
        resp = self.create("?tur=topic&mavzu=999999")
        self.assertEqual(resp.status_code, 404)


class FinalVariantsTests(BaseTest):
    def setUp(self):
        self.teacher, self.s1 = mk_user("t1", "teacher"), mk_user("s1")
        self.ctx = full_course(self.teacher)
        self.course = self.ctx.course
        self.ctx.final.delete()                                      # full_course yakuniy loyiha qo'shadi — variantlarni o'zimiz yig'amiz
        self.enr = enroll(self.course, self.s1)
        pass_pretest(self.ctx, self.s1)

    def finish_all_modules(self):
        """Barcha modullarni tugatilgan holatga keltiradi (progressiv rejimda yakuniy bosqichlar ochilishi uchun)."""
        from courses.models import Topic
        for t in Topic.objects.filter(module__course=self.course):
            TopicProgress.objects.get_or_create(student=self.s1, topic=t)
        grade = lambda: None  # noqa
        from assessments.grading import grade_quiz
        grade_quiz(self.ctx.quiz1, self.s1, FakePost(answers(self.ctx.q1_items, [True, True])), timezone.now())
        Submission.objects.create(assignment=self.ctx.a1, student=self.s1, passed=True, status="graded", total_score=90, percent=90)

    def add_final_quiz(self, **kw):
        return mk_quiz(self.course, None, "final", n=2, comps=list(self.ctx.comps), **kw)

    def add_final_project(self):
        return mk_assignment(self.course, None, "final")

    def submit_and_grade_project(self, project, scores):
        self.client.force_login(self.s1)
        self.client.post(project.get_absolute_url(), {"method": "zip", "zip_file": zip_upload({"main.py": "print(1)\n"})})
        sub = Submission.objects.get(assignment=project)
        self.client.force_login(self.teacher)
        self.client.post(reverse("assessments:submission_grade", args=[sub.pk]), {f"s_{c.pk}": m for c, m in zip(project.criteria.all(), scores)})

    def status(self):
        self.enr.refresh_from_db()
        return self.enr.status

    def test_test_only_completes_course(self):
        quiz, items = self.add_final_quiz()
        self.finish_all_modules()
        self.assertEqual(self.status(), "active")
        self.client.force_login(self.s1)
        take(self.client, quiz, answers(items, [True, False]))       # 50 < 60
        self.assertEqual(self.status(), "active")
        take(self.client, quiz, answers(items, [True, True]))
        self.assertEqual(self.status(), "completed")
        cert = Certificate.objects.get(enrollment=self.enr)
        self.assertEqual(cert.final_percent, 100.0)
        self.assertTrue(Notification.objects.filter(user=self.s1, text__contains="Sertifikatingiz").exists())

    def test_project_only_completes_course(self):
        project = self.add_final_project()
        self.finish_all_modules()
        self.submit_and_grade_project(project, [40, 20, 20])         # 80
        self.assertEqual(self.status(), "completed")
        self.assertEqual(Certificate.objects.get().final_percent, 80.0)

    def test_both_required_and_certificate_is_average(self):
        quiz, items = self.add_final_quiz(max_attempts=0)
        project = self.add_final_project()
        self.finish_all_modules()
        self.client.force_login(self.s1)
        take(self.client, quiz, answers(items, [True, True]))        # 100%
        self.assertEqual(self.status(), "active")                    # loyiha hali topshirilmagan
        self.submit_and_grade_project(project, [40, 10, 10])         # 60 -> o'tish bali 60
        self.assertEqual(self.status(), "completed")
        self.assertEqual(Certificate.objects.get().final_percent, 80.0)   # (100 + 60) / 2

    def test_both_project_first_then_test(self):
        quiz, items = self.add_final_quiz()
        project = self.add_final_project()
        self.finish_all_modules()
        self.submit_and_grade_project(project, [40, 30, 30])
        self.assertEqual(self.status(), "active")                    # test hali yo'q
        self.client.force_login(self.s1)
        take(self.client, quiz, answers(items, [True, True]))
        self.assertEqual(self.status(), "completed")

    def test_no_finals_completes_when_all_modules_passed(self):
        self.finish_all_modules()
        from courses.services import try_complete
        try_complete(self.enr)
        self.assertEqual(self.status(), "completed")
        self.assertTrue(Certificate.objects.exists())

    def test_no_finals_not_complete_before_modules_done(self):
        from courses.services import try_complete
        self.assertIsNone(try_complete(self.enr))
        self.assertEqual(self.status(), "active")

    def test_finals_wait_for_all_modules_when_progressive(self):
        quiz, _ = self.add_final_quiz()
        self.client.force_login(self.s1)
        self.assertEqual(self.client.get(quiz.get_absolute_url()).status_code, 302)
        self.assertEqual(self.client.get(reverse("assessments:quiz_take", args=[quiz.pk])).status_code, 302)
        s = PlatformSettings.get()
        s.progressive_learning = False
        s.save()
        self.assertEqual(self.client.get(reverse("assessments:quiz_take", args=[quiz.pk])).status_code, 200)

    def test_course_page_shows_both_final_cards(self):
        quiz, _ = self.add_final_quiz()
        project = self.add_final_project()
        self.client.force_login(self.s1)
        resp = self.client.get(self.course.get_absolute_url())
        self.assertEqual((resp.context["final_quiz"], resp.context["final_project"]), (quiz, project))
        self.assertContains(resp, "ikkala bosqichdan ham")
        self.assertContains(resp, "Yakuniy test")
        self.assertContains(resp, "Yakuniy loyiha")

    def test_completed_course_blocks_final_attempts(self):
        quiz, items = self.add_final_quiz()
        self.finish_all_modules()
        self.client.force_login(self.s1)
        take(self.client, quiz, answers(items, [True, True]))
        self.assertEqual(self.status(), "completed")
        before = Attempt.objects.filter(quiz=quiz).count()
        take(self.client, quiz, answers(items, [True, True]))
        self.assertEqual(Attempt.objects.filter(quiz=quiz).count(), before)

    def test_final_quiz_counts_in_competency_growth(self):
        from analytics import services as analytics
        quiz, items = self.add_final_quiz()
        from assessments.grading import grade_quiz
        grade_quiz(self.ctx.pre, self.s1, FakePost(answers(self.ctx.pre_items, [False] * 4)), timezone.now())
        grade_quiz(quiz, self.s1, FakePost(answers(items, [True, True])), timezone.now())
        g = analytics.competency_growth(self.s1, self.course)
        self.assertEqual(g["overall_final"], 100.0)
        self.assertTrue(all(r["final"] == 100.0 for r in g["rows"]))

    def test_final_quiz_in_leaderboard(self):
        quiz, items = self.add_final_quiz()
        from assessments.grading import grade_quiz
        grade_quiz(quiz, self.s1, FakePost(answers(items, [True, True])), timezone.now())
        row = next(r for r in gamification.leaderboard(self.course) if r["student"] == self.s1)
        self.assertEqual(row["points"], 100)


class OptionalDatesTests(BaseTest):
    def setUp(self):
        self.teacher, self.s1 = mk_user("t1", "teacher"), mk_user("s1")

    def undated_course(self):
        ctx = full_course(self.teacher, slug="sanasiz")
        Course.objects.filter(pk=ctx.course.pk).update(start_date=None, end_date=None)
        Module.objects.filter(course=ctx.course).update(start_date=None, end_date=None)
        ctx.course.refresh_from_db()
        return ctx

    def test_course_without_dates_is_always_open(self):
        ctx = self.undated_course()
        enroll(ctx.course, self.s1)
        pass_pretest(ctx, self.s1)
        state = CourseState(self.s1, ctx.course)
        self.assertFalse(state.read_only)
        self.assertTrue(state.module_access(ctx.m1))
        self.assertTrue(state.topic_access(ctx.t1))
        self.client.force_login(self.s1)
        self.assertEqual(self.client.get(ctx.t1.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(ctx.course.get_absolute_url()).status_code, 200)

    def test_modules_without_dates_open_in_non_progressive_mode(self):
        ctx = self.undated_course()
        s = PlatformSettings.get()
        s.progressive_learning = False
        s.save()
        enroll(ctx.course, self.s1)
        pass_pretest(ctx, self.s1)
        self.assertTrue(CourseState(self.s1, ctx.course).module_access(ctx.m2))

    def test_enroll_in_undated_course(self):
        ctx = self.undated_course()
        self.client.force_login(self.s1)
        self.client.post(reverse("courses:enroll", args=[ctx.course.slug]))
        self.assertTrue(Enrollment.objects.filter(course=ctx.course, student=self.s1).exists())

    def test_only_start_date_set(self):
        ctx = full_course(self.teacher, slug="faqat-boshlanish", start=10)
        Course.objects.filter(pk=ctx.course.pk).update(end_date=None)
        ctx.course.refresh_from_db()
        enroll(ctx.course, self.s1)
        state = CourseState(self.s1, ctx.course)
        self.assertIn("boshlanadi", state.module_access(ctx.m1).reason)
        self.assertFalse(state.read_only)

    def test_only_end_date_set_in_past_makes_read_only(self):
        ctx = full_course(self.teacher, slug="faqat-tugash", start=-50, end=-1)
        Course.objects.filter(pk=ctx.course.pk).update(start_date=None)
        ctx.course.refresh_from_db()
        enroll(ctx.course, self.s1)
        self.assertTrue(CourseState(self.s1, ctx.course).read_only)

    def test_create_course_and_module_without_dates(self):
        self.client.force_login(self.teacher)
        resp = self.client.post(reverse("courses:course_create"), {"title": "Sanasiz kurs", "description": "d", "is_published": "on"})
        course = Course.objects.get(title="Sanasiz kurs")
        self.assertRedirects(resp, course.get_absolute_url())
        self.assertEqual((course.start_date, course.end_date), (None, None))
        self.client.post(reverse("courses:module_create", args=[course.slug]), {"title": "M", "description": "", "order": ""})
        self.assertEqual(course.modules.get().start_date, None)
        self.assertEqual(self.client.get(course.get_absolute_url()).status_code, 200)

    def test_module_end_before_start_still_rejected(self):
        self.client.force_login(self.teacher)
        ctx = full_course(self.teacher, slug="m-sanalar")
        today = timezone.localdate()
        self.client.post(reverse("courses:module_create", args=[ctx.course.slug]), {
            "title": "X", "description": "", "order": "", "start_date": today, "end_date": today - timedelta(days=2)})
        self.assertEqual(ctx.course.modules.count(), 2)

    def test_course_list_hides_missing_dates(self):
        ctx = self.undated_course()
        self.client.force_login(self.s1)
        resp = self.client.get(reverse("courses:course_list"))
        self.assertContains(resp, "Kurs")
        self.assertNotContains(resp, "📅")

    def test_assignment_without_any_deadline_is_never_late(self):
        ctx = self.undated_course()
        Assignment.objects.filter(pk=ctx.a1.pk).update(due_date=None)
        a = Assignment.objects.get(pk=ctx.a1.pk)          # yangi nusxa: bog'langan modul/kurs ham yangi sanalar bilan
        self.assertIsNone(a.effective_due)
        enroll(ctx.course, self.s1)
        pass_pretest(ctx, self.s1)
        for t in (ctx.t1, ctx.t2):
            TopicProgress.objects.create(student=self.s1, topic=t)
        self.client.force_login(self.s1)
        self.client.post(a.get_absolute_url(), {"method": "zip", "zip_file": zip_upload({"main.py": "x=1\n"})})
        sub = Submission.objects.get()
        self.assertFalse(sub.is_late)
        from gamification.models import UserBadge
        self.assertFalse(UserBadge.objects.filter(user=self.s1, code="fast_coder").exists())


class StartedAtTests(BaseTest):
    def setUp(self):
        self.teacher, self.s1 = mk_user("t1", "teacher"), mk_user("s1")
        self.ctx = full_course(self.teacher)
        self.enr = enroll(self.ctx.course, self.s1)
        self.client.force_login(self.s1)

    def reload(self):
        self.enr.refresh_from_db()
        return self.enr

    def test_enrollment_alone_is_not_starting(self):
        e = self.reload()
        self.assertIsNone(e.started_at)
        self.assertIsNotNone(e.enrolled_at)

    def test_pretest_marks_start(self):
        take(self.client, self.ctx.pre, answers(self.ctx.pre_items, [True] * 4))
        e = self.reload()
        self.assertIsNotNone(e.started_at)
        self.assertGreaterEqual(e.last_activity_at, e.started_at)

    def test_first_activity_sets_start_and_later_ones_only_update_last_activity(self):
        pass_pretest(self.ctx, self.s1)
        self.client.get(self.ctx.t1.get_absolute_url())
        first = self.reload().started_at
        self.assertIsNotNone(first)
        Enrollment.objects.filter(pk=self.enr.pk).update(last_activity_at=first - timedelta(days=3))
        self.client.post(reverse("courses:topic_complete", args=[self.ctx.t1.pk]))
        e = self.reload()
        self.assertEqual(e.started_at, first)                        # boshlagan vaqti o'zgarmaydi
        self.assertGreater(e.last_activity_at, first - timedelta(days=3))

    def test_submission_marks_start(self):
        pass_pretest(self.ctx, self.s1)
        Enrollment.objects.filter(pk=self.enr.pk).update(started_at=None)
        for t in (self.ctx.t1, self.ctx.t2):
            TopicProgress.objects.create(student=self.s1, topic=t)
        self.client.post(self.ctx.a1.get_absolute_url(), {"method": "zip", "zip_file": zip_upload({"a.py": "x=1\n"})})
        self.assertIsNotNone(self.reload().started_at)

    def test_staff_viewing_does_not_start_anything(self):
        self.client.force_login(self.teacher)
        self.client.get(self.ctx.t1.get_absolute_url())
        self.assertIsNone(self.reload().started_at)

    def test_locked_topic_visit_is_not_activity(self):
        self.client.get(self.ctx.t1.get_absolute_url())              # kirish testi yo'q -> yopiq
        self.assertIsNone(self.reload().started_at)

    def test_analytics_state_progression(self):
        from analytics import services as analytics
        rows = lambda: analytics.overview(self.teacher)["rows"]
        self.assertEqual(rows()[0]["state"], "not_started")
        pass_pretest(self.ctx, self.s1)
        self.client.get(self.ctx.t1.get_absolute_url())
        self.assertEqual(rows()[0]["state"], "learning")
        Enrollment.objects.filter(pk=self.enr.pk).update(status="completed", completed_at=timezone.now())
        self.assertEqual(rows()[0]["state"], "completed")

    def test_student_stats_shows_days_to_start(self):
        from analytics import services as analytics
        Enrollment.objects.filter(pk=self.enr.pk).update(enrolled_at=timezone.now() - timedelta(days=5))
        pass_pretest(self.ctx, self.s1)
        self.client.get(self.ctx.t1.get_absolute_url())
        s = analytics.student_stats(self.s1, self.ctx.course)
        self.assertEqual(s["days_to_start"], 5)
        self.assertEqual(s["enrollment"].pk, self.enr.pk)


class BackfillMigrationTests(BaseTest):
    """Eski (started_at yo'q) yozuvlar mavjud faoliyatdan tiklanadi."""

    def setUp(self):
        from importlib import import_module
        self.backfill = import_module("courses.migrations.0003_backfill_started_at").backfill_started_at
        self.teacher, self.s1, self.s2 = mk_user("t1", "teacher"), mk_user("s1"), mk_user("s2")
        self.ctx = full_course(self.teacher)
        self.e1, self.e2 = enroll(self.ctx.course, self.s1), enroll(self.ctx.course, self.s2)

    def run_backfill(self):
        from django.apps import apps
        self.backfill(apps, None)

    def test_started_from_earliest_and_last_from_latest_activity(self):
        old, new = timezone.now() - timedelta(days=9), timezone.now() - timedelta(days=2)
        tp = TopicProgress.objects.create(student=self.s1, topic=self.ctx.t1)
        TopicProgress.objects.filter(pk=tp.pk).update(completed_at=old)
        grade_quiz = __import__("assessments.grading", fromlist=["grade_quiz"]).grade_quiz
        att = grade_quiz(self.ctx.quiz1, self.s1, FakePost(answers(self.ctx.q1_items, [True, True])), new)
        Attempt.objects.filter(pk=att.pk).update(submitted_at=new)
        Enrollment.objects.filter(pk=self.e1.pk).update(started_at=None, last_activity_at=None)
        self.run_backfill()
        e = Enrollment.objects.get(pk=self.e1.pk)
        self.assertEqual((e.started_at, e.last_activity_at), (old, new))

    def test_students_without_activity_stay_not_started(self):
        self.run_backfill()
        self.assertIsNone(Enrollment.objects.get(pk=self.e2.pk).started_at)

    def test_existing_values_are_not_overwritten(self):
        mark = timezone.now() - timedelta(days=30)
        TopicProgress.objects.create(student=self.s1, topic=self.ctx.t1)
        Enrollment.objects.filter(pk=self.e1.pk).update(started_at=mark, last_activity_at=mark)
        self.run_backfill()
        self.assertEqual(Enrollment.objects.get(pk=self.e1.pk).started_at, mark)

    def test_other_courses_activity_is_ignored(self):
        other = full_course(self.teacher, slug="boshqa")
        enroll(other.course, self.s1)
        TopicProgress.objects.create(student=self.s1, topic=other.t1)
        self.run_backfill()
        self.assertIsNone(Enrollment.objects.get(pk=self.e1.pk).started_at)      # faoliyat boshqa kursda edi
        self.assertIsNotNone(Enrollment.objects.get(course=other.course, student=self.s1).started_at)


class DefaultReviewFileTests(BaseTest):
    def test_prefers_source_over_docs(self):
        from assessments.views import _default_review_file
        self.assertEqual(_default_review_file(["README.md", "docs/a.txt", "src/main.py", "z.py"]), "src/main.py")
        self.assertEqual(_default_review_file(["README.md", "config.json"]), "README.md")
        self.assertEqual(_default_review_file([]), "")
