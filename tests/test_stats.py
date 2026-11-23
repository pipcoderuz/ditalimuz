"""Umumiy statistika menyusi: rollar bo'yicha ko'lam, filtrlar (kursni BOSHLAGAN sana), CSV va talaba statistikasi."""
import csv
import io
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from analytics import services as analytics
from assessments.grading import grade_quiz
from assessments.models import Submission
from courses.models import Certificate, Enrollment, Topic, TopicProgress

from .helpers import BaseTest, FakePost, answers, enroll, full_course, mk_user, pass_pretest


class StatsBase(BaseTest):
    """A kursi (t1): s1 — boshlamagan, s2 — o'qimoqda (10 kun oldin boshlagan), s3 — yakunlagan (20 kun oldin boshlagan).
    B kursi (t2): s4."""

    def setUp(self):
        self.now = timezone.now()
        self.admin, self.t1, self.t2 = mk_user("boss", "admin"), mk_user("t1", "teacher"), mk_user("t2", "teacher")
        self.s1, self.s2, self.s3, self.s4 = (mk_user(f"s{i}") for i in range(1, 5))
        self.a = full_course(self.t1, slug="kurs-a")
        self.b = full_course(self.t2, slug="kurs-b")
        self.e1, self.e2, self.e3 = (enroll(self.a.course, s) for s in (self.s1, self.s2, self.s3))
        self.e4 = enroll(self.b.course, self.s4)
        topics = list(Topic.objects.filter(module__course=self.a.course).order_by("id"))     # 3 ta mavzu
        # s2: 1/3 mavzu, 10 kun oldin boshlagan, kecha faol
        TopicProgress.objects.create(student=self.s2, topic=topics[0])
        Enrollment.objects.filter(pk=self.e2.pk).update(started_at=self.now - timedelta(days=10), last_activity_at=self.now - timedelta(days=1))
        # s3: 3/3 mavzu, 20 kun oldin boshlagan, 5 kun oldin yakunlagan; test 100%, loyiha 80%
        for t in topics:
            TopicProgress.objects.create(student=self.s3, topic=t)
        grade_quiz(self.a.quiz1, self.s3, FakePost(answers(self.a.q1_items, [True, True])), self.now)
        Submission.objects.create(assignment=self.a.final, student=self.s3, status="graded", passed=True, total_score=80, percent=80.0)
        Enrollment.objects.filter(pk=self.e3.pk).update(started_at=self.now - timedelta(days=20), last_activity_at=self.now - timedelta(days=5),
                                                        status="completed", completed_at=self.now - timedelta(days=5))
        Certificate.objects.create(enrollment=Enrollment.objects.get(pk=self.e3.pk), final_percent=90)

    def ov(self, user, **kw):
        return analytics.overview(user, **kw)


class OverviewServiceTests(StatsBase):
    def test_scope_by_role(self):
        self.assertEqual({r["e"].student.username for r in self.ov(self.admin)["rows"]}, {"s1", "s2", "s3", "s4"})
        self.assertEqual({r["e"].student.username for r in self.ov(self.t1)["rows"]}, {"s1", "s2", "s3"})
        self.assertEqual({r["e"].student.username for r in self.ov(self.t2)["rows"]}, {"s4"})
        rows = self.ov(self.s2)["rows"]
        self.assertEqual([r["e"].student.username for r in rows], ["s2"])        # talaba faqat o'zini ko'radi

    def test_totals(self):
        t = self.ov(self.t1)["totals"]
        self.assertEqual((t["enrollments"], t["students"], t["started"], t["completed"], t["courses"]), (3, 3, 2, 1, 1))
        self.assertEqual(t["completion_rate"], 33)
        self.assertEqual(t["avg_progress"], 44)                                   # (0 + 33 + 100) / 3
        self.assertEqual(t["avg_days_to_finish"], 15.0)                           # 20 -> 5 kun oldin
        self.assertEqual(t["certificates"], 1)
        self.assertEqual(t["active_7d"], 2)                                       # s2 (1 kun), s3 (5 kun)
        self.assertEqual(t["avg_score"], 90.0)                                    # s3: (100 + 80) / 2; boshqalarda ball yo'q
        self.assertGreaterEqual(t["attempts"], 1)
        self.assertEqual(t["submissions"], 1)

    def test_states(self):
        rows = {r["e"].student.username: r for r in self.ov(self.t1)["rows"]}
        self.assertEqual([rows[u]["state"] for u in ("s1", "s2", "s3")], ["not_started", "learning", "completed"])
        self.assertIsNone(rows["s1"]["days"])
        self.assertEqual(rows["s2"]["days"], 10)
        self.assertEqual(rows["s3"]["days"], 15)
        self.assertEqual(rows["s2"]["idle_days"], 1)

    def test_filters(self):
        names = lambda **kw: {r["e"].student.username for r in self.ov(self.admin, **kw)["rows"]}
        self.assertEqual(names(course_id=self.b.course.pk), {"s4"})
        self.assertEqual(names(state="completed"), {"s3"})
        self.assertEqual(names(state="not_started"), {"s1", "s4"})
        today = timezone.localdate()
        self.assertEqual(names(date_from=today - timedelta(days=12)), {"s2"})     # kursni BOSHLAGAN sana: faqat s2
        self.assertEqual(names(date_to=today - timedelta(days=15)), {"s3"})
        self.assertEqual(names(date_from=today - timedelta(days=25), date_to=today - timedelta(days=5)), {"s2", "s3"})
        self.assertEqual(names(date_from=today + timedelta(days=1)), set())
        self.assertEqual(names(course_id=self.a.course.pk, state="learning"), {"s2"})

    def test_per_course_table(self):
        pc = {c["course"].slug: c for c in self.ov(self.admin)["per_course"]}
        a = pc["kurs-a"]
        self.assertEqual((a["enrolled"], a["started"], a["completed"], a["rate"], a["avg_progress"], a["avg_days"]), (3, 2, 1, 33, 44, 15.0))
        self.assertEqual((pc["kurs-b"]["enrolled"], pc["kurs-b"]["avg_days"]), (1, None))
        self.assertEqual(self.ov(self.admin)["per_course"][0]["course"].slug, "kurs-a")    # ko'proq yozilgan kurs birinchi

    def test_monthly_series(self):
        s = self.ov(self.admin)["series"]
        self.assertEqual(len(s["months"]), 12)
        self.assertEqual(s["months"][-1], self.now.strftime("%Y-%m"))
        cur = lambda key: s[key][-1] + (s[key][-2] if self.now.day <= 20 else 0)       # 20 kun oldingi sana o'tgan oyga tushishi mumkin
        self.assertEqual(sum(s["enrolled"]), 4)
        self.assertEqual(sum(s["started"]), 2)
        self.assertEqual(sum(s["completed"]), 1)
        self.assertEqual(sum(s["registered"]), 7)                                       # admin + 2 o'qituvchi + 4 talaba

    def test_admin_only_extras(self):
        self.assertIn("registered", self.ov(self.admin)["series"])
        self.assertNotIn("registered", self.ov(self.t1)["series"])
        self.assertEqual(self.ov(self.admin)["users_by_role"], {"admin": 1, "teacher": 2, "student": 4})
        self.assertEqual(self.ov(self.t1)["users_by_role"], {})

    def test_empty_scope_is_safe(self):
        lonely = mk_user("t3", "teacher")
        data = self.ov(lonely)
        self.assertEqual((data["totals"]["enrollments"], data["totals"]["completion_rate"], data["totals"]["avg_progress"], data["rows"]), (0, 0, 0, []))
        self.assertIsNone(data["totals"]["avg_score"])
        self.assertEqual(self.ov(mk_user("newbie"))["rows"], [])


class OverviewViewTests(StatsBase):
    url = reverse("analytics:overview")

    def test_every_role_can_open(self):
        for user in (self.admin, self.t1, self.s2):
            self.login(user)
            resp = self.client.get(self.url)
            self.assertEqual(resp.status_code, 200, user.username)
            self.assertContains(resp, "Umumiy statistika")
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_navbar_has_statistics_menu_for_all_roles(self):
        for user in (self.s1, self.t1, self.admin):
            self.login(user)
            self.assertContains(self.client.get(reverse("courses:course_list")), 'href="/statistika/"')

    def test_student_sees_only_own_rows_and_no_filters(self):
        self.login(self.s2)
        resp = self.client.get(self.url)
        self.assertEqual([r["e"].student.username for r in resp.context["rows"]], ["s2"])
        self.assertNotContains(resp, 'name="dan"')
        resp = self.client.get(self.url + f"?kurs={self.b.course.pk}")          # begona kurs filtri baribir faqat o'zinikini beradi
        self.assertEqual(resp.context["rows"], [])

    def test_teacher_scope_and_filters(self):
        self.login(self.t1)
        resp = self.client.get(self.url)
        self.assertEqual(len(resp.context["rows"]), 3)
        self.assertContains(resp, 'name="dan"')
        self.assertContains(resp, "boshlamagan")
        today = timezone.localdate()
        resp = self.client.get(self.url + f"?dan={today - timedelta(days=12)}")
        self.assertEqual([r["e"].student.username for r in resp.context["rows"]], ["s2"])
        resp = self.client.get(self.url + "?holat=completed")
        self.assertEqual([r["e"].student.username for r in resp.context["rows"]], ["s3"])
        resp = self.client.get(self.url + f"?kurs={self.b.course.pk}")            # boshqa o'qituvchining kursi — bo'sh
        self.assertEqual(resp.context["rows"], [])

    def test_bad_filter_values_are_ignored(self):
        self.login(self.admin)
        resp = self.client.get(self.url + "?kurs=abc&dan=2020-99-99&gacha=bad&holat=zzz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["rows"]), 4)

    def test_chart_payload_present(self):
        self.login(self.admin)
        chart = self.client.get(self.url).context["chart"]
        self.assertEqual(len(chart["months"]), 12)
        self.assertIn("registered", chart)
        self.assertEqual(sorted(chart["courses"]["labels"]), ["Kurs", "Kurs"])


class CsvExportTests(StatsBase):
    url = reverse("analytics:overview_csv")

    def rows(self, user, query=""):
        self.login(user)
        resp = self.client.get(self.url + query)
        self.assertEqual(resp.status_code, 200)
        text = resp.content.decode("utf-8-sig")
        return resp, list(csv.reader(io.StringIO(text)))

    def test_csv_content_and_encoding(self):
        resp, rows = self.rows(self.t1)
        self.assertTrue(resp["Content-Type"].startswith("text/csv"))
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertTrue(resp.content.startswith(b"\xef\xbb\xbf"))                  # Excel uchun UTF-8 BOM
        self.assertEqual(rows[0][:4], ["Talaba", "Kurs", "Yozilgan sana", "Boshlagan sana"])
        body = {r[0]: r for r in rows[1:]}
        self.assertEqual(set(body), {"S1 Test", "S2 Test", "S3 Test"})
        self.assertEqual(body["S1 Test"][3], "")                                    # boshlamagan — sana bo'sh
        self.assertEqual(body["S1 Test"][-1], "Boshlamagan")
        self.assertEqual(body["S3 Test"][-1], "Yakunlagan")
        self.assertEqual(body["S3 Test"][6], "90.0")
        self.assertEqual(body["S2 Test"][7], "10")

    def test_csv_respects_filters_and_scope(self):
        _, rows = self.rows(self.t1, "?holat=learning")
        self.assertEqual([r[0] for r in rows[1:]], ["S2 Test"])
        _, rows = self.rows(self.admin)
        self.assertEqual(len(rows) - 1, 4)
        _, rows = self.rows(self.t2)
        self.assertEqual([r[0] for r in rows[1:]], ["S4 Test"])

    def test_students_cannot_export(self):
        self.login(self.s1)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_formula_injection_is_neutralized(self):
        from accounts.models import User
        User.objects.filter(pk=self.s1.pk).update(first_name="=HYPERLINK(\"http://evil\")", last_name="x")
        _, rows = self.rows(self.t1)
        names = [r[0] for r in rows[1:]]
        self.assertFalse(any(n.startswith(("=", "+", "-", "@")) for n in names), names)
        self.assertIn("'=HYPERLINK", " ".join(names))                              # matn saqlanadi, faqat zararsizlantiriladi


class StudentStatsViewTests(StatsBase):
    def stats(self, user, student=None, course=None):
        self.login(user)
        course = course or self.a.course
        url = reverse("analytics:student_stats", args=[course.slug, student.pk]) if student else reverse("analytics:student_stats_me", args=[course.slug])
        return self.client.get(url)

    def test_teacher_sees_student_timeline(self):
        resp = self.stats(self.t1, self.s2)
        self.assertEqual(resp.status_code, 200)
        s = resp.context["s"]
        self.assertEqual((s["row"]["state"], s["row"]["progress"], s["row"]["days"]), ("learning", 33, 10))
        self.assertEqual(s["course_avg_progress"], 50)       # boshqa talabalar: s1 (0%) va s3 (100%)
        self.assertEqual(s["enrollment"].student, self.s2)
        self.assertContains(resp, "O'qishni boshlagan")

    def test_not_started_student(self):
        resp = self.stats(self.t1, self.s1)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hali boshlamagan")
        self.assertIsNone(resp.context["s"]["row"]["days"])

    def test_completed_student_has_certificate_and_finished_modules(self):
        resp = self.stats(self.t1, self.s3)
        s = resp.context["s"]
        self.assertEqual(s["certificate"].final_percent, 90)
        self.assertContains(resp, "Sertifikat")
        self.assertEqual(s["row"]["state"], "completed")
        self.assertEqual(len(s["modules"]), 2)

    def test_days_between_enrollment_and_start(self):
        Enrollment.objects.filter(pk=self.e2.pk).update(enrolled_at=self.now - timedelta(days=14))
        self.assertEqual(self.stats(self.t1, self.s2).context["s"]["days_to_start"], 4)

    def test_permissions(self):
        self.assertEqual(self.stats(self.t2, self.s2).status_code, 403)               # boshqa o'qituvchi
        self.assertEqual(self.stats(self.admin, self.s2).status_code, 200)
        self.assertEqual(self.stats(self.s2).status_code, 200)                         # talaba o'zinikini
        resp = self.stats(self.s2, self.s3)                                            # boshqa talabaning ID'si e'tiborga olinmaydi
        self.assertEqual(resp.context["student"], self.s2)
        self.assertEqual(self.stats(self.s4, course=self.a.course).status_code, 403)   # kursga yozilmagan
        self.assertEqual(self.stats(self.t1).status_code, 403)                         # o'qituvchi uchun "mening" statistikam yo'q
        self.assertEqual(self.stats(self.t1, self.s4).status_code, 403)                # s4 bu kursda emas
        self.client.logout()
        self.assertEqual(self.client.get(reverse("analytics:student_stats_me", args=[self.a.course.slug])).status_code, 302)

    def test_module_finish_dates_follow_progress(self):
        from courses.models import Topic
        t1, t2 = self.a.t1, self.a.t2
        for t in (t1, t2):
            TopicProgress.objects.get_or_create(student=self.s2, topic=t)
        grade_quiz(self.a.quiz1, self.s2, FakePost(answers(self.a.q1_items, [True, True])), self.now)
        Submission.objects.create(assignment=self.a.a1, student=self.s2, status="graded", passed=True, total_score=90, percent=90)
        mods = self.stats(self.t1, self.s2).context["s"]["modules"]
        self.assertIsNotNone(mods[0]["finished_at"])                                    # 1-modul tugagan
        self.assertIsNone(mods[1]["finished_at"])                                       # 2-modul hali yo'q
