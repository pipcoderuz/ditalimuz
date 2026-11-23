import io
import zipfile
from datetime import timedelta
from unittest import mock

from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from accounts.models import PlatformSettings
from assessments import codeutils, plagiarism
from assessments.grading import grade_quiz
from assessments.models import Assignment, PlagiarismFlag, ReviewComment, Submission
from community.models import Notification
from gamification import services as gamification
from gamification.models import UserBadge

from .helpers import (
    BaseTest, FakePost, answers, enroll, full_course, make_zip, mk_assignment, mk_quiz, mk_user, pass_pretest, zip_upload,
)
from courses.models import TopicProgress

CODE_A = '''class BankAccount:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance
        self.history = []

    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("bad")
        self.balance += amount
        self.history.append(("deposit", amount))

    def withdraw(self, amount):
        if amount > self.balance:
            raise ValueError("low")
        self.balance -= amount
        self.history.append(("withdraw", amount))

    def report(self):
        for kind, value in self.history:
            print(kind, value)
        return self.balance
'''
CODE_A_RENAMED = (CODE_A.replace("BankAccount", "Hisob").replace("owner", "egasi").replace("balance", "qoldiq")
                  .replace("history", "tarix").replace("amount", "summa").replace("kind", "tur").replace("value", "qiymat"))
CODE_B = '''import random

def guess_game(limit):
    secret = random.randint(1, limit)
    attempts = 0
    while True:
        attempts += 1
        guess = int(input("Taxmin: "))
        if guess == secret:
            return attempts
        elif guess < secret:
            print("Kattaroq")
        else:
            print("Kichikroq")
'''


class SubmissionBase(BaseTest):
    def setUp(self):
        self.teacher = mk_user("t1", "teacher")
        self.s1, self.s2, self.s3 = mk_user("s1"), mk_user("s2"), mk_user("s3")
        self.ctx = full_course(self.teacher)
        PlatformSettings.get()
        for s in (self.s1, self.s2, self.s3):
            enroll(self.ctx.course, s)
            pass_pretest(self.ctx, s)
            for t in (self.ctx.t1, self.ctx.t2):
                TopicProgress.objects.create(student=s, topic=t)
        self.a = self.ctx.a1

    def submit(self, student, files, **extra):
        self.login(student)
        data = {"method": "zip", "zip_file": zip_upload(files), "comment": "", **extra}
        resp = self.client.post(self.a.get_absolute_url(), data)
        return resp

    def raw_submission(self, student, code, minutes=0):
        data = make_zip({"main.py": code})
        sub = Submission(assignment=self.a, student=student, method="zip")
        import hashlib
        sub.zip_file.save("p.zip", ContentFile(data), save=False)
        sub.zip_size, sub.zip_sha256 = len(data), hashlib.sha256(data).hexdigest()
        sub.save()
        sub.fingerprint = plagiarism.make_fingerprint(codeutils.submission_sources(sub))
        sub.save()
        return sub

    def grade(self, sub, scores, as_user=None):
        self.login(as_user or self.teacher)
        data = {f"s_{c.pk}": sc for c, sc in zip(sub.assignment.criteria.all(), scores)}
        return self.client.post(reverse("assessments:submission_grade", args=[sub.pk]), {**data, "teacher_comment": "xulosa"})


class AssignmentManagementTests(SubmissionBase):
    def formset(self, rows, **extra):
        data = {"title": "Yangi", "description": "Shart", "pass_score": 60, "due_date": "", "required": "on",
                "criteria-TOTAL_FORMS": len(rows), "criteria-INITIAL_FORMS": 0, "criteria-MIN_NUM_FORMS": 0, "criteria-MAX_NUM_FORMS": 1000}
        for i, (name, mx) in enumerate(rows):
            data[f"criteria-{i}-name"], data[f"criteria-{i}-max_score"] = name, mx
        data.update(extra)
        return data

    def test_create_with_rubric_sums_max_score(self):
        self.login(self.teacher)
        url = reverse("assessments:assignment_create", args=[self.ctx.course.slug]) + f"?modul={self.ctx.m2.pk}"
        self.client.post(url, self.formset([("To'g'ri ishlashi", 40), ("Kod tozaligi", 30), ("Xatolarni ushlash", 30)]))
        a = Assignment.objects.get(title="Yangi")
        self.assertEqual((a.max_score, a.kind, a.module), (100, "module", self.ctx.m2))
        self.assertEqual(a.criteria.count(), 3)

    def test_pass_score_cannot_exceed_rubric_total(self):
        self.login(self.teacher)
        url = reverse("assessments:assignment_create", args=[self.ctx.course.slug]) + f"?modul={self.ctx.m2.pk}"
        resp = self.client.post(url, self.formset([("A", 20)], pass_score=60))
        self.assertFalse(Assignment.objects.filter(title="Yangi").exists())
        self.assertContains(resp, "rubrika yig")

    def test_rubric_required(self):
        self.login(self.teacher)
        url = reverse("assessments:assignment_create", args=[self.ctx.course.slug]) + f"?modul={self.ctx.m2.pk}"
        self.client.post(url, self.formset([]))
        self.assertFalse(Assignment.objects.filter(title="Yangi").exists())

    def test_single_final_project(self):
        self.login(self.teacher)
        resp = self.client.get(reverse("assessments:assignment_create", args=[self.ctx.course.slug]) + "?final=1")
        self.assertRedirects(resp, self.ctx.final.get_absolute_url())  # allaqachon bor

    def test_edit_recomputes_max_score(self):
        self.login(self.teacher)
        crit = list(self.a.criteria.all())
        data = {"title": self.a.title, "description": "s", "pass_score": 50, "required": "on",
                "criteria-TOTAL_FORMS": 3, "criteria-INITIAL_FORMS": 3, "criteria-MIN_NUM_FORMS": 0, "criteria-MAX_NUM_FORMS": 1000}
        for i, c in enumerate(crit):
            data.update({f"criteria-{i}-id": c.pk, f"criteria-{i}-assignment": self.a.pk, f"criteria-{i}-name": c.name, f"criteria-{i}-max_score": 20})
        self.client.post(reverse("assessments:assignment_edit", args=[self.a.pk]), data)
        self.a.refresh_from_db()
        self.assertEqual(self.a.max_score, 60)


class SubmissionTests(SubmissionBase):
    def test_zip_submission(self):
        resp = self.submit(self.s1, {"main.py": "print(1)\n"})
        sub = Submission.objects.get()
        self.assertRedirects(resp, sub.get_absolute_url())
        self.assertEqual((sub.method, sub.status, sub.student), ("zip", "submitted", self.s1))
        self.assertTrue(sub.zip_sha256 and sub.zip_size > 0)
        self.assertFalse(sub.is_late)
        self.assertTrue(Notification.objects.filter(user=self.teacher, text__contains="S1 Test").exists())

    def test_non_zip_rejected(self):
        self.login(self.s1)
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.client.post(self.a.get_absolute_url(), {"method": "zip", "zip_file": SimpleUploadedFile("x.zip", b"no zip", "application/zip")})
        self.assertContains(resp, "ZIP arxiv emas")
        self.assertEqual(Submission.objects.count(), 0)

    def test_missing_file_rejected(self):
        self.login(self.s1)
        resp = self.client.post(self.a.get_absolute_url(), {"method": "zip"})
        self.assertContains(resp, "ZIP faylni yuklang")

    @mock.patch("assessments.views.fetch_snapshot")
    def test_github_submission_with_snapshot(self, fetch):
        fetch.return_value = (make_zip({"repo-HEAD/main.py": CODE_B}), "")
        self.login(self.s1)
        self.client.post(self.a.get_absolute_url(), {"method": "github", "github_url": "https://github.com/ali/proj"})
        sub = Submission.objects.get()
        self.assertEqual((sub.method, sub.github_url, sub.snapshot_error), ("github", "https://github.com/ali/proj", ""))
        self.assertTrue(sub.zip_file)
        self.assertEqual([p for p, _ in codeutils.submission_sources(sub)], ["main.py"])  # umumiy papka olib tashlanadi
        self.assertTrue(sub.fingerprint["shingles"])

    @mock.patch("assessments.views.fetch_snapshot")
    def test_github_submission_private_repo_keeps_link(self, fetch):
        fetch.return_value = (None, "Repozitoriy topilmadi yoki yopiq (private) — havola saqlandi.")
        self.login(self.s1)
        resp = self.client.post(self.a.get_absolute_url(), {"method": "github", "github_url": "https://github.com/ali/secret"}, follow=True)
        sub = Submission.objects.get()
        self.assertFalse(sub.zip_file)
        self.assertIn("yopiq", sub.snapshot_error)
        self.assertContains(resp, "yopiq")

    def test_bad_github_url_rejected(self):
        self.login(self.s1)
        for url in ("https://gitlab.com/a/b", "https://github.com/onlyuser", ""):
            self.client.post(self.a.get_absolute_url(), {"method": "github", "github_url": url})
        self.assertEqual(Submission.objects.count(), 0)

    def test_resubmission_rules(self):
        self.submit(self.s1, {"main.py": "a=1\n"})
        sub = Submission.objects.get()
        resp = self.client.get(self.a.get_absolute_url())
        self.assertContains(resp, "tekshirilmoqda")                       # baholanguncha qayta yuborib bo'lmaydi
        self.submit(self.s1, {"main.py": "b=2\n"})
        self.assertEqual(Submission.objects.count(), 1)
        self.grade(sub, [5, 5, 5])                                        # 15 < 60 -> o'tmadi
        self.submit(self.s1, {"main.py": "c=3\n"})
        self.assertEqual(Submission.objects.count(), 2)                   # endi mumkin
        sub2 = Submission.objects.order_by("-id").first()
        self.grade(sub2, [40, 30, 30])
        self.submit(self.s1, {"main.py": "d=4\n"})
        self.assertEqual(Submission.objects.count(), 2)                   # o'tgandan keyin yo'q

    def test_late_flag(self):
        self.a.due_date = timezone.localdate() - timedelta(days=1)
        self.a.save()
        self.submit(self.s1, {"main.py": "x=1\n"})
        self.assertTrue(Submission.objects.get().is_late)

    def test_locked_assignment_not_accessible(self):
        s4 = mk_user("s4")
        enroll(self.ctx.course, s4)
        pass_pretest(self.ctx, s4)  # mavzular tugatilmagan
        self.login(s4)
        self.assertEqual(self.client.get(self.a.get_absolute_url()).status_code, 302)
        self.client.post(self.a.get_absolute_url(), {"method": "zip", "zip_file": zip_upload({"a.py": "x"})})
        self.assertEqual(Submission.objects.count(), 0)

    def test_privacy_between_students(self):
        self.submit(self.s1, {"main.py": "x=1\n"})
        sub = Submission.objects.get()
        self.login(self.s2)
        self.assertEqual(self.client.get(sub.get_absolute_url()).status_code, 403)
        self.login(self.s1)
        self.assertEqual(self.client.get(sub.get_absolute_url()).status_code, 200)


class GradingTests(SubmissionBase):
    def setUp(self):
        super().setUp()
        self.submit(self.s1, {"main.py": CODE_A})
        self.sub = Submission.objects.get()

    def test_rubric_grading_and_pass(self):
        self.grade(self.sub, [36, 20, 30])
        self.sub.refresh_from_db()
        self.assertEqual((self.sub.total_score, self.sub.percent, self.sub.passed, self.sub.status), (86, 86.0, True, "graded"))
        self.assertEqual(self.sub.scores.count(), 3)
        self.assertEqual(self.sub.graded_by, self.teacher)
        self.assertTrue(Notification.objects.filter(user=self.s1, text__contains="86/100").exists())

    def test_fail_below_pass_score(self):
        self.grade(self.sub, [20, 10, 10])
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.passed)
        self.assertTrue(Notification.objects.filter(user=self.s1, text__contains="ololmadingiz").exists())

    def test_student_sees_lost_points_per_criterion(self):
        self.grade(self.sub, [40, 20, 30])  # kod tozaligidan 10 ball yo'qotilgan
        self.login(self.s1)
        resp = self.client.get(self.sub.get_absolute_url())
        scores = {s.criterion.name: s.lost for s in resp.context["scores"]}
        self.assertEqual(scores, {"To'g'ri ishlashi": 0, "Kod tozaligi": 10, "Xatoliklar": 0})
        self.assertContains(resp, "−10")
        self.assertContains(resp, "Kod tozaligi")

    def test_score_above_criterion_max_rejected(self):
        self.grade(self.sub, [41, 0, 0])
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, "submitted")

    def test_regrade_updates_scores(self):
        self.grade(self.sub, [10, 10, 10])
        self.grade(self.sub, [40, 30, 30])
        self.sub.refresh_from_db()
        self.assertEqual((self.sub.total_score, self.sub.passed), (100, True))
        self.assertEqual(self.sub.scores.count(), 3)

    def test_permissions(self):
        self.assertEqual(self.grade(self.sub, [1, 1, 1], as_user=self.s1).status_code, 403)
        other_teacher = mk_user("t2", "teacher")
        self.assertEqual(self.grade(self.sub, [1, 1, 1], as_user=other_teacher).status_code, 403)
        admin = mk_user("boss", "admin")
        self.assertEqual(self.grade(self.sub, [30, 20, 20], as_user=admin).status_code, 302)

    def test_module_unlock_notification_after_assignment_pass(self):
        from assessments.models import Attempt
        grade_quiz(self.ctx.quiz1, self.s1, FakePost(answers(self.ctx.q1_items, [True, True])), timezone.now())
        self.grade(self.sub, [40, 30, 30])
        self.assertTrue(Notification.objects.filter(user=self.s1, text__contains="Yangi modul ochildi").exists())


class CodeReviewTests(SubmissionBase):
    def setUp(self):
        super().setUp()
        self.submit(self.s1, {"src/main.py": CODE_A, "src/util.py": "def f():\n    return 1\n", "node_modules/x/index.js": "x", "logo.png": "binary"})
        self.sub = Submission.objects.get()

    def comment(self, user, **kw):
        self.login(user)
        data = {"file_path": "src/main.py", "line_start": 8, "line_end": "", "text": "Bu funksiyani optimalroq yozish mumkin edi"}
        data.update(kw)
        return self.client.post(reverse("assessments:review_comment_add", args=[self.sub.pk]), data)

    def test_viewer_lists_only_source_files(self):
        self.login(self.teacher)
        resp = self.client.get(self.sub.get_absolute_url())
        self.assertEqual([p for p, _ in resp.context["files"]], ["src/main.py", "src/util.py"])
        html = resp.context["rows"][0]["html"]
        self.assertIn("BankAccount", html)
        self.assertIn('<span class="', html)  # Pygments ranglagan
        resp = self.client.get(self.sub.get_absolute_url() + "?path=src/util.py")
        self.assertEqual(len(resp.context["rows"]), 2)

    def test_teacher_comment_on_specific_line_visible_to_student(self):
        self.comment(self.teacher, line_start=8, line_end=12)
        c = ReviewComment.objects.get()
        self.assertEqual((c.file_path, c.line_start, c.line_end, c.author), ("src/main.py", 8, 12, self.teacher))
        self.login(self.s1)
        resp = self.client.get(self.sub.get_absolute_url() + "?path=src/main.py")
        row8 = resp.context["rows"][7]
        self.assertEqual(row8["n"], 8)
        self.assertEqual(len(row8["comments"]), 1)
        self.assertContains(resp, "optimalroq yozish")
        self.assertContains(resp, "qatorlar 8–12")
        self.assertTrue(Notification.objects.filter(user=self.s1, text__contains="izoh").exists())

    def test_student_cannot_comment_or_delete(self):
        self.assertEqual(self.comment(self.s1).status_code, 403)
        self.comment(self.teacher)
        c = ReviewComment.objects.get()
        self.login(self.s1)
        self.assertEqual(self.client.post(reverse("assessments:review_comment_delete", args=[c.pk])).status_code, 403)
        self.assertEqual(ReviewComment.objects.count(), 1)

    def test_other_teacher_cannot_comment(self):
        self.assertEqual(self.comment(mk_user("t2", "teacher")).status_code, 403)

    def test_comment_validation(self):
        self.comment(self.teacher, line_start=10, line_end=5)
        self.comment(self.teacher, line_start=0)
        self.comment(self.teacher, text="")
        self.assertEqual(ReviewComment.objects.count(), 0)

    def test_delete_comment(self):
        self.comment(self.teacher)
        c = ReviewComment.objects.get()
        self.login(self.teacher)
        self.client.post(reverse("assessments:review_comment_delete", args=[c.pk]))
        self.assertEqual(ReviewComment.objects.count(), 0)

    def test_comment_on_submission_without_archive(self):
        self.sub.zip_file.delete(save=True)
        self.comment(self.teacher, file_path="app/models.py", line_start=3)
        self.login(self.s1)
        resp = self.client.get(self.sub.get_absolute_url())
        self.assertContains(resp, "app/models.py:3")

    def test_prefill_from_line_link(self):
        self.login(self.teacher)
        resp = self.client.get(self.sub.get_absolute_url() + "?path=src/main.py&line=15")
        self.assertEqual(resp.context["comment_form"].initial, {"file_path": "src/main.py", "line_start": "15"})


class CodeUtilsTests(BaseTest):
    def test_read_sources_filters(self):
        data = make_zip({"p/a.py": "x=1", "p/.git/config": "g", "p/node_modules/m.js": "m", "p/img.png": "b", "p/dir/b.java": "class B{}",
                         "p/big.py": "x" * 300_000})
        items = codeutils.read_sources(io.BytesIO(data))
        self.assertEqual([p for p, _ in items], ["p/a.py", "p/dir/b.java"])            # foydalanuvchi papkasi saqlanadi
        items = codeutils.read_sources(io.BytesIO(data), strip_root=True)              # GitHub arxivi uchun
        self.assertEqual([p for p, _ in items], ["a.py", "dir/b.java"])

    def test_path_traversal_entries_ignored(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.py", "x")
            zf.writestr("/abs.py", "x")
            zf.writestr("ok.py", "y")
        self.assertEqual([p for p, _ in codeutils.read_sources(io.BytesIO(buf.getvalue()))], ["ok.py"])

    def test_bad_zip_returns_empty(self):
        self.assertEqual(codeutils.read_sources(io.BytesIO(b"garbage")), [])

    def test_decoding_errors_do_not_crash(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.py", b"print('\xff\xfe')")
        self.assertEqual(len(codeutils.read_sources(io.BytesIO(buf.getvalue()))), 1)

    def test_github_url_parsing(self):
        from assessments.github import parse_repo
        self.assertEqual(parse_repo("https://github.com/o/r"), ("o", "r"))
        self.assertEqual(parse_repo("https://github.com/o/r.git"), ("o", "r"))
        self.assertEqual(parse_repo("https://github.com/o/r/tree/main/src"), ("o", "r"))
        self.assertIsNone(parse_repo("https://evil.com/github.com/o/r"))
        self.assertIsNone(parse_repo("https://github.com/o"))

    @mock.patch("assessments.github.requests.get")
    def test_fetch_snapshot_statuses(self, get):
        from assessments.github import fetch_snapshot
        get.return_value = mock.Mock(status_code=404)
        self.assertIn("yopiq", fetch_snapshot("https://github.com/o/r")[1])
        get.return_value = mock.Mock(status_code=200, iter_content=lambda n: iter([b"a" * 10, b"b" * 10]))
        self.assertEqual(fetch_snapshot("https://github.com/o/r")[0], b"a" * 10 + b"b" * 10)
        self.assertIn("katta", fetch_snapshot("https://github.com/o/r", max_bytes=15)[1])
        import requests
        get.side_effect = requests.ConnectionError()
        self.assertIn("bog'lanib bo'lmadi", fetch_snapshot("https://github.com/o/r")[1])
        self.assertIn("formatida emas", fetch_snapshot("https://example.com/x")[1])


class PlagiarismTests(SubmissionBase):
    def test_identical_zip_is_100_percent(self):
        self.raw_submission(self.s1, CODE_A)
        sub2 = self.raw_submission(self.s2, CODE_A)
        flags = plagiarism.check_submission(sub2)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].score, 100.0)
        self.assertTrue(flags[0].details["same_hash"])

    def test_renamed_variables_still_flagged(self):
        s1 = self.raw_submission(self.s1, CODE_A)
        s2 = self.raw_submission(self.s2, CODE_A_RENAMED)
        score, details = plagiarism.compare(s2, s1)
        self.assertGreaterEqual(score, 70)
        self.assertGreater(details["structure"], 90)       # tuzilma bir xil
        self.assertLess(details["identifiers"], 60)        # nomlar farq qiladi
        self.assertEqual(len(PlagiarismFlag.objects.all()) + len(plagiarism.check_submission(s2)), 1)

    def test_independent_work_not_flagged(self):
        self.raw_submission(self.s1, CODE_A)
        sub2 = self.raw_submission(self.s2, CODE_B)
        self.assertEqual(plagiarism.check_submission(sub2), [])
        self.assertFalse(PlagiarismFlag.objects.exists())

    def test_tiny_submissions_not_compared(self):
        self.raw_submission(self.s1, "print(1)\n")
        sub2 = self.raw_submission(self.s2, "print(1)\n.\n")
        self.assertEqual(plagiarism.check_submission(sub2), [])

    def test_threshold_setting_respected(self):
        self.raw_submission(self.s1, CODE_A)
        s2 = self.raw_submission(self.s2, CODE_A_RENAMED)
        PlagiarismFlag.objects.all().delete()
        cfg = PlatformSettings.get()
        cfg.plagiarism_threshold = 99
        cfg.save()
        self.assertEqual(plagiarism.check_submission(s2), [])

    def test_own_resubmissions_not_compared(self):
        self.raw_submission(self.s1, CODE_A)
        again = self.raw_submission(self.s1, CODE_A)
        self.assertEqual(plagiarism.check_submission(again), [])

    def test_flag_via_upload_notifies_teacher_and_shows_in_list(self):
        self.submit(self.s1, {"main.py": CODE_A})
        self.submit(self.s2, {"main.py": CODE_A_RENAMED})
        flag = PlagiarismFlag.objects.get()
        self.assertEqual({flag.submission_a.student, flag.submission_b.student}, {self.s1, self.s2})
        self.assertTrue(Notification.objects.filter(user=self.teacher, text__contains="Plagiat ogohlantirishi").exists())
        self.login(self.teacher)
        resp = self.client.get(reverse("assessments:plagiarism_list"))
        self.assertContains(resp, "S1 Test")
        self.assertContains(resp, "S2 Test")
        # topshiriq tafsiloti sahifasida ham ko'rinadi
        self.assertContains(self.client.get(flag.submission_b.get_absolute_url()), "o'xshash")

    def test_flag_status_update_and_visibility(self):
        self.submit(self.s1, {"main.py": CODE_A})
        self.submit(self.s2, {"main.py": CODE_A})
        flag = PlagiarismFlag.objects.get()
        self.login(self.teacher)
        self.client.post(reverse("assessments:plagiarism_update", args=[flag.pk]), {"status": "dismissed"})
        flag.refresh_from_db()
        self.assertEqual(flag.status, "dismissed")
        self.assertEqual(len(self.client.get(reverse("assessments:plagiarism_list")).context["flags"]), 0)
        self.assertEqual(len(self.client.get(reverse("assessments:plagiarism_list") + "?holat=dismissed").context["flags"]), 1)
        # begona o'qituvchi ko'rmaydi/o'zgartira olmaydi, talaba kira olmaydi
        self.login(mk_user("t2", "teacher"))
        self.assertEqual(len(self.client.get(reverse("assessments:plagiarism_list") + "?holat=dismissed").context["flags"]), 0)
        self.assertEqual(self.client.post(reverse("assessments:plagiarism_update", args=[flag.pk]), {"status": "open"}).status_code, 403)
        self.login(self.s1)
        self.assertEqual(self.client.get(reverse("assessments:plagiarism_list")).status_code, 403)

    def test_students_never_see_flags(self):
        self.submit(self.s1, {"main.py": CODE_A})
        self.submit(self.s2, {"main.py": CODE_A})
        sub = Submission.objects.get(student=self.s2)
        self.assertNotContains(self.client.get(sub.get_absolute_url()), "Plagiat")


class GamificationTests(SubmissionBase):
    def badges(self, user):
        return set(UserBadge.objects.filter(user=user).values_list("code", flat=True))

    def test_perfect_score_badge(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1)
        a = grade_quiz(quiz, self.s1, FakePost(answers(items, [True, True])), timezone.now())
        gamification.after_attempt(a)
        self.assertIn("perfect_score", self.badges(self.s1))
        quiz2, items2 = mk_quiz(self.ctx.course, self.ctx.m1)
        gamification.after_attempt(grade_quiz(quiz2, self.s2, FakePost(answers(items2, [True, False])), timezone.now()))
        self.assertNotIn("perfect_score", self.badges(self.s2))

    def test_badges_are_unique_per_course(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1)
        for _ in range(3):
            gamification.after_attempt(grade_quiz(quiz, self.s1, FakePost(answers(items, [True, True])), timezone.now()))
        self.assertEqual(UserBadge.objects.filter(user=self.s1, code="perfect_score").count(), 1)

    def test_bug_hunter_requires_correct_and_fast(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1, n=3, bug=True)
        slow = grade_quiz(quiz, self.s1, FakePost(answers(items, [True] * 3)), timezone.now() - timedelta(minutes=30))
        gamification.after_attempt(slow)
        self.assertNotIn("bug_hunter", self.badges(self.s1))   # to'g'ri, lekin sekin
        wrong = grade_quiz(quiz, self.s2, FakePost(answers(items, [True, True, False])), timezone.now() - timedelta(minutes=1))
        gamification.after_attempt(wrong)
        self.assertNotIn("bug_hunter", self.badges(self.s2))   # tez, lekin xato
        fast = grade_quiz(quiz, self.s3, FakePost(answers(items, [True] * 3)), timezone.now() - timedelta(minutes=2))
        gamification.after_attempt(fast)
        self.assertIn("bug_hunter", self.badges(self.s3))

    def test_bug_hunter_needs_enough_bug_questions(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1, n=1, bug=True)
        gamification.after_attempt(grade_quiz(quiz, self.s1, FakePost(answers(items, [True])), timezone.now()))
        self.assertNotIn("bug_hunter", self.badges(self.s1))

    def test_fast_coder_early_submission(self):
        self.a.due_date = timezone.localdate() + timedelta(days=10)
        self.a.save()
        self.submit(self.s1, {"main.py": "a=1\n"})
        self.assertIn("fast_coder", self.badges(self.s1))
        self.a.due_date = timezone.localdate()   # muddat bugun -> "oldin" emas
        self.a.save()
        self.submit(self.s2, {"main.py": "a=2\n"})
        self.assertNotIn("fast_coder", self.badges(self.s2))

    def test_first_step_badge_on_first_topic(self):
        s4 = mk_user("s4")
        enroll(self.ctx.course, s4)
        pass_pretest(self.ctx, s4)
        self.login(s4)
        self.client.post(reverse("courses:topic_complete", args=[self.ctx.t1.pk]))
        self.assertIn("first_step", self.badges(s4))
        self.assertTrue(Notification.objects.filter(user=s4, text__contains="Yangi yutuq").exists())

    def test_leaderboard_ranking_and_ties(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1)
        grade_quiz(quiz, self.s1, FakePost(answers(items, [True, True])), timezone.now())     # 100
        grade_quiz(quiz, self.s2, FakePost(answers(items, [True, False])), timezone.now())    # 50
        grade_quiz(quiz, self.s3, FakePost(answers(items, [True, False])), timezone.now())    # 50
        # kirish testi va 2 mavzu (setUp) -> mavzu uchun 2*2=4 ball har biriga; pre-test hisobga kirmaydi
        rows = gamification.leaderboard(self.ctx.course)
        self.assertEqual([r["student"].username for r in rows][0], "s1")
        self.assertEqual([r["points"] for r in rows], [104.0, 54.0, 54.0])
        self.assertEqual([r["rank"] for r in rows], [1, 2, 2])

    def test_leaderboard_counts_best_attempt_and_graded_assignments(self):
        quiz, items = mk_quiz(self.ctx.course, self.ctx.m1)
        grade_quiz(quiz, self.s1, FakePost(answers(items, [False, False])), timezone.now())
        grade_quiz(quiz, self.s1, FakePost(answers(items, [True, True])), timezone.now())
        self.submit(self.s1, {"main.py": "a=1\n"})
        self.grade(Submission.objects.get(student=self.s1), [30, 20, 10])
        row = next(r for r in gamification.leaderboard(self.ctx.course) if r["student"] == self.s1)
        self.assertEqual(row["points"], 100 + 60 + 4)

    def test_leaderboard_page_access(self):
        self.login(self.s1)
        self.assertContains(self.client.get(reverse("gamification:leaderboard", args=[self.ctx.course.slug])), "Reyting")
        outsider = mk_user("out")
        self.login(outsider)
        self.assertEqual(self.client.get(reverse("gamification:leaderboard", args=[self.ctx.course.slug])).status_code, 403)
