from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from analytics import services as analytics
from assessments.grading import grade_quiz
from assessments.models import Submission
from community.models import Notification, Post, Thread
from courses.models import TopicProgress

from .helpers import BaseTest, FakePost, answers, enroll, full_course, mk_quiz, mk_user, pass_pretest


class ForumTests(BaseTest):
    def setUp(self):
        self.teacher, self.s1, self.s2 = mk_user("t1", "teacher"), mk_user("s1"), mk_user("s2")
        self.ctx = full_course(self.teacher)

    def test_create_thread_and_reply_notifications(self):
        self.login(self.s1)
        self.client.post(reverse("community:thread_create"), {"course": self.ctx.course.pk, "title": "Sikl haqida", "body": "Qanday ishlaydi?"})
        thread = Thread.objects.get()
        self.assertTrue(Notification.objects.filter(user=self.teacher, text__contains="yangi savol").exists())
        self.login(self.teacher)
        self.client.post(thread.get_absolute_url(), {"body": "Mana javob"})
        self.assertTrue(Notification.objects.filter(user=self.s1, text__contains="javob yozdi").exists())
        self.login(self.s2)
        self.client.post(thread.get_absolute_url(), {"body": "Menda ham shu savol"})
        # savol egasi va avval javob yozgan o'qituvchi xabardor qilinadi, javob yozuvchining o'ziga bildirishnoma yo'q
        self.assertEqual(Notification.objects.filter(user=self.s1, text__contains="S2 Test").count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.teacher, text__contains="S2 Test").count(), 1)
        self.assertFalse(Notification.objects.filter(user=self.s2, text__contains="S2 Test").exists())
        self.assertEqual(thread.posts.count(), 2)

    def test_search_and_filter(self):
        Thread.objects.create(author=self.s1, title="Python sikllar", body="x", course=self.ctx.course)
        Thread.objects.create(author=self.s1, title="Boshqa mavzu", body="y")
        self.login(self.s2)
        self.assertEqual(len(self.client.get(reverse("community:thread_list") + "?q=sikllar").context["threads"]), 1)
        self.assertEqual(len(self.client.get(reverse("community:thread_list") + f"?kurs={self.ctx.course.pk}").context["threads"]), 1)

    def test_moderation_only_teacher_or_admin(self):
        thread = Thread.objects.create(author=self.s1, title="Nomaqbul", body="x")
        post = Post.objects.create(thread=thread, author=self.s2, body="haqorat")
        self.login(self.s1)  # muallifning o'zi ham o'chira olmaydi (moderatsiya — o'qituvchi/admin)
        self.assertEqual(self.client.post(reverse("community:post_delete", args=[post.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("community:thread_delete", args=[thread.pk])).status_code, 403)
        self.login(self.teacher)
        self.client.post(reverse("community:post_delete", args=[post.pk]))
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        self.login(mk_user("boss", "admin"))
        self.client.post(reverse("community:thread_delete", args=[thread.pk]))
        self.assertFalse(Thread.objects.filter(pk=thread.pk).exists())

    def test_delete_requires_post_method(self):
        thread = Thread.objects.create(author=self.s1, title="T", body="x")
        self.login(self.teacher)
        self.assertEqual(self.client.get(reverse("community:thread_delete", args=[thread.pk])).status_code, 405)

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(reverse("community:thread_list")).status_code, 302)


class NotificationTests(BaseTest):
    def setUp(self):
        self.s1, self.s2 = mk_user("s1"), mk_user("s2")
        self.n = Notification.objects.create(user=self.s1, text="Salom", url="/forum/")

    def test_counter_open_and_read_all(self):
        self.login(self.s1)
        resp = self.client.get(reverse("community:thread_list"))
        self.assertContains(resp, "data-notif-badge")
        self.assertContains(resp, ">1</span>")
        resp = self.client.get(reverse("community:notification_open", args=[self.n.pk]))
        self.assertRedirects(resp, "/forum/", fetch_redirect_response=False)
        self.n.refresh_from_db()
        self.assertTrue(self.n.is_read)
        Notification.objects.create(user=self.s1, text="A")
        Notification.objects.create(user=self.s1, text="B")
        self.client.post(reverse("community:notifications_read_all"))
        self.assertFalse(Notification.objects.filter(user=self.s1, is_read=False).exists())

    def test_cannot_open_others_notification(self):
        self.login(self.s2)
        self.assertEqual(self.client.get(reverse("community:notification_open", args=[self.n.pk])).status_code, 404)

    def test_external_url_never_redirected(self):
        bad = Notification.objects.create(user=self.s1, text="x", url="https://evil.com")
        self.login(self.s1)
        resp = self.client.get(reverse("community:notification_open", args=[bad.pk]))
        self.assertRedirects(resp, reverse("community:notifications"))


class AnalyticsTests(BaseTest):
    def setUp(self):
        self.teacher, self.s1, self.s2, self.s3 = mk_user("t1", "teacher"), mk_user("s1"), mk_user("s2"), mk_user("s3")
        self.ctx = full_course(self.teacher)
        for s in (self.s1, self.s2, self.s3):
            enroll(self.ctx.course, s)

    def test_competency_growth_pre_vs_final(self):
        ctx, a_comp, b_comp = self.ctx, *self.ctx.comps
        # kirish testi: 4 savol (A, B, A, B). s1: A ikkalasi xato, B ikkalasi to'g'ri
        grade_quiz(ctx.pre, self.s1, FakePost(answers(ctx.pre_items, [False, True, False, True])), timezone.now())
        # yakuniy: 1-modul testi 2 savol (A, B): A to'g'ri, B xato; qo'shimcha test: A,B ikkalasi to'g'ri (eng yaxshisi hisoblanadi)
        grade_quiz(ctx.quiz1, self.s1, FakePost(answers(ctx.q1_items, [True, False])), timezone.now())
        grade_quiz(ctx.quiz1, self.s1, FakePost(answers(ctx.q1_items, [True, False])), timezone.now())
        g = analytics.competency_growth(self.s1, ctx.course)
        rows = {r["name"]: r for r in g["rows"]}
        self.assertEqual((rows["A"]["pre"], rows["A"]["final"], rows["A"]["delta"]), (0.0, 100.0, 100.0))
        self.assertEqual((rows["B"]["pre"], rows["B"]["final"], rows["B"]["delta"]), (100.0, 0.0, -100.0))
        self.assertEqual((g["overall_pre"], g["overall_final"], g["overall_delta"]), (50.0, 50.0, 0.0))

    def test_growth_uses_best_attempt(self):
        ctx = self.ctx
        grade_quiz(ctx.pre, self.s1, FakePost(answers(ctx.pre_items, [False] * 4)), timezone.now())
        grade_quiz(ctx.quiz1, self.s1, FakePost(answers(ctx.q1_items, [False, False])), timezone.now())
        grade_quiz(ctx.quiz1, self.s1, FakePost(answers(ctx.q1_items, [True, True])), timezone.now())
        g = analytics.competency_growth(self.s1, ctx.course)
        self.assertEqual(g["overall_final"], 100.0)
        self.assertTrue(all(r["final"] == 100.0 and r["delta"] == 100.0 for r in g["rows"]))

    def test_growth_without_pretest_attempt(self):
        g = analytics.competency_growth(self.s1, self.ctx.course)
        self.assertIsNone(g["pre_attempt"])
        self.login(self.s1)
        self.assertContains(self.client.get(reverse("analytics:growth", args=[self.ctx.course.slug])), "hali topshirilmagan")

    def test_growth_page_permissions(self):
        pass_pretest(self.ctx, self.s1)
        url = reverse("analytics:growth", args=[self.ctx.course.slug])
        self.login(self.s1)
        self.assertEqual(self.client.get(url).status_code, 200)
        # talaba boshqa talabaning o'sishini ko'ra olmaydi (URL'dagi student_id e'tiborga olinmaydi)
        resp = self.client.get(reverse("analytics:growth_student", args=[self.ctx.course.slug, self.s2.pk]))
        self.assertEqual(resp.context["student"], self.s1)
        self.login(self.teacher)
        resp = self.client.get(reverse("analytics:growth_student", args=[self.ctx.course.slug, self.s1.pk]))
        self.assertEqual(resp.context["student"], self.s1)
        self.login(mk_user("t2", "teacher"))
        self.assertEqual(self.client.get(reverse("analytics:growth_student", args=[self.ctx.course.slug, self.s1.pk])).status_code, 403)
        self.login(mk_user("outsider"))
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_dropoff_fail_rates_and_hardest_questions(self):
        ctx = self.ctx
        # 3 talabadan 2 tasi 1-modul testidan o'ta olmadi, 1 tasi o'tdi
        grade_quiz(ctx.quiz1, self.s1, FakePost(answers(ctx.q1_items, [False, False])), timezone.now())
        grade_quiz(ctx.quiz1, self.s2, FakePost(answers(ctx.q1_items, [False, True])), timezone.now())
        grade_quiz(ctx.quiz1, self.s3, FakePost(answers(ctx.q1_items, [True, True])), timezone.now())
        # s1 qayta urinib, o'tdi -> "o'ta olmagan" hisobiga kirmaydi
        grade_quiz(ctx.quiz1, self.s1, FakePost(answers(ctx.q1_items, [True, True])), timezone.now())
        d = analytics.dropoff(ctx.course)
        q = next(x for x in d["quizzes"] if x["quiz"] == ctx.quiz1)
        self.assertEqual((q["tried"], q["passed"], q["failed"], q["fail_rate"]), (3, 2, 1, 33))
        first_q = ctx.q1_items[0][0]
        hardest = next(h for h in d["hardest"] if h["question"] == first_q.pk)
        self.assertEqual((hardest["total"], hardest["wrong"], hardest["wrong_rate"]), (4, 2, 50))
        self.assertEqual(d["total"], 3)

    def test_topic_funnel(self):
        for s in (self.s1, self.s2):
            TopicProgress.objects.create(student=s, topic=self.ctx.t1)
        TopicProgress.objects.create(student=self.s1, topic=self.ctx.t2)
        d = analytics.dropoff(self.ctx.course)
        funnel = {f["topic"].title: (f["done"], f["percent"]) for f in d["funnel"]}
        self.assertEqual(funnel, {"T1": (2, 67), "T2": (1, 33), "T3": (0, 0)})

    def test_assignment_stats(self):
        Submission.objects.create(assignment=self.ctx.a1, student=self.s1, status="graded", passed=True, percent=90, total_score=90)
        Submission.objects.create(assignment=self.ctx.a1, student=self.s2, status="graded", passed=False, percent=30, total_score=30)
        Submission.objects.create(assignment=self.ctx.a1, student=self.s3, status="submitted")
        a = next(x for x in analytics.dropoff(self.ctx.course)["assignments"] if x["assignment"] == self.ctx.a1)
        self.assertEqual((a["students"], a["passed"], a["pending"], a["avg"]), (3, 1, 1, 60.0))

    def test_course_analytics_only_for_course_owner(self):
        url = reverse("analytics:course_analytics", args=[self.ctx.course.slug])
        self.login(self.s1)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(mk_user("t2", "teacher"))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.login(mk_user("boss", "admin"))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_empty_course_analytics_does_not_crash(self):
        from courses.models import Enrollment
        Enrollment.objects.all().delete()
        self.login(self.teacher)
        self.assertEqual(self.client.get(reverse("analytics:course_analytics", args=[self.ctx.course.slug])).status_code, 200)
