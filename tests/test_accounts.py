import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from accounts.models import PlatformSettings, User
from community.models import Notification

from .helpers import PW, BaseTest, mk_user


class RegistrationTests(BaseTest):
    def reg(self, **extra):
        data = {"role": "student", "username": "yangi", "first_name": "Ali", "last_name": "Vali", "email": "a@b.uz",
                "password1": "Str0ng-pass-77", "password2": "Str0ng-pass-77"}
        data.update(extra)
        return self.client.post(reverse("accounts:register"), data)

    def test_student_registers_and_is_logged_in(self):
        resp = self.reg()
        self.assertRedirects(resp, reverse("home"))
        u = User.objects.get(username="yangi")
        self.assertEqual((u.role, u.approval_status), ("student", "approved"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), u.pk)

    def test_cannot_register_as_admin(self):
        resp = self.reg(role="admin", is_superuser="on", is_staff="on")
        self.assertEqual(resp.status_code, 200)  # forma xato bilan qayta ko'rsatiladi
        self.assertFalse(User.objects.filter(username="yangi").exists())

    def test_teacher_registration_is_pending_and_cannot_login(self):
        admin = mk_user("boss", "admin")
        resp = self.reg(role="teacher", username="ustoz")
        self.assertRedirects(resp, reverse("accounts:login"))
        u = User.objects.get(username="ustoz")
        self.assertEqual((u.role, u.approval_status), ("teacher", "pending"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(Notification.objects.filter(user=admin, text__contains="ustoz").exists())
        resp = self.client.post(reverse("accounts:login"), {"username": "ustoz", "password": "Str0ng-pass-77"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "tasdiqlanishi kutilmoqda")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_teacher_can_login_after_approval(self):
        admin = mk_user("boss", "admin")
        self.reg(role="teacher", username="ustoz")
        u = User.objects.get(username="ustoz")
        self.login(admin)
        self.client.post(reverse("accounts:user_action", args=[u.pk, "approve"]))
        self.client.logout()
        resp = self.client.post(reverse("accounts:login"), {"username": "ustoz", "password": "Str0ng-pass-77"})
        self.assertRedirects(resp, reverse("home"))
        self.assertTrue(Notification.objects.filter(user=u, text__contains="tasdiqlandi").exists())

    def test_rejected_teacher_cannot_login(self):
        mk_user("rad", "teacher", approval="rejected")
        resp = self.client.post(reverse("accounts:login"), {"username": "rad", "password": PW})
        self.assertContains(resp, "rad etilgan")

    def test_blocked_user_gets_clear_message(self):
        u = mk_user("blok")
        u.is_active = False
        u.save()
        resp = self.client.post(reverse("accounts:login"), {"username": "blok", "password": PW})
        self.assertContains(resp, "bloklangan")

    def test_wrong_password_generic_error(self):
        mk_user("a1")
        resp = self.client.post(reverse("accounts:login"), {"username": "a1", "password": "bad"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "bloklangan")

    def test_pending_session_is_terminated(self):
        u = mk_user("p1", "teacher")
        self.login(u)
        User.objects.filter(pk=u.pk).update(approval_status="pending")
        resp = self.client.get(reverse("courses:course_list"))
        self.assertEqual(resp.status_code, 302)  # sessiya tugatildi -> login'ga

    def test_superuser_becomes_admin(self):
        su = User.objects.create_superuser("root", "r@r.uz", PW)
        self.assertEqual(su.role, "admin")
        self.assertTrue(su.is_platform_admin and su.is_staff)


class LandingAndProfileTests(BaseTest):
    def test_landing_has_login_form(self):
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, "Tizimga kirish")
        self.assertContains(resp, 'name="password"')

    def test_profile_edit_with_avatar(self):
        u = mk_user("s1")
        self.login(u)
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(buf, "PNG")
        resp = self.client.post(reverse("accounts:profile"), {
            "first_name": "Yangi", "last_name": "Ism", "email": "x@y.uz", "phone": "+998901234567",
            "github_username": "octo", "bio": "salom", "avatar": SimpleUploadedFile("a.png", buf.getvalue(), "image/png"),
        })
        self.assertRedirects(resp, reverse("accounts:profile"))
        u.refresh_from_db()
        self.assertEqual((u.display_name, u.github_username), ("Yangi Ism", "octo"))
        self.assertTrue(u.avatar.name.startswith("avatars/"))
        self.assertContains(self.client.get(reverse("accounts:profile_public", args=["s1"])), "Yangi Ism")

    def test_non_image_avatar_rejected(self):
        u = mk_user("s1")
        self.login(u)
        resp = self.client.post(reverse("accounts:profile"), {
            "first_name": "A", "last_name": "B", "email": "x@y.uz", "avatar": SimpleUploadedFile("a.png", b"not an image", "image/png")})
        self.assertEqual(resp.status_code, 200)
        u.refresh_from_db()
        self.assertFalse(u.avatar)


class AdminPanelTests(BaseTest):
    def setUp(self):
        self.admin = mk_user("boss", "admin")
        self.teacher = mk_user("t1", "teacher")
        self.student = mk_user("s1")

    def test_only_admin_can_open_panel(self):
        for u in (self.teacher, self.student):
            self.login(u)
            self.assertEqual(self.client.get(reverse("accounts:admin_panel")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("accounts:admin_panel")).status_code, 302)
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("accounts:admin_panel")).status_code, 200)

    def test_toggle_progressive_learning(self):
        self.login(self.admin)
        self.assertTrue(PlatformSettings.get().progressive_learning)
        self.client.post(reverse("accounts:settings_update"), {"plagiarism_threshold": 70})  # checkbox yo'q -> o'chiriladi
        self.assertFalse(PlatformSettings.get().progressive_learning)
        self.client.post(reverse("accounts:settings_update"), {"progressive_learning": "on", "plagiarism_threshold": 55})
        s = PlatformSettings.get()
        self.assertTrue(s.progressive_learning)
        self.assertEqual(s.plagiarism_threshold, 55)

    def test_invalid_threshold_rejected(self):
        self.login(self.admin)
        self.client.post(reverse("accounts:settings_update"), {"progressive_learning": "on", "plagiarism_threshold": 500})
        self.assertEqual(PlatformSettings.get().plagiarism_threshold, 70)

    def test_settings_singleton(self):
        PlatformSettings.get()
        PlatformSettings.objects.create(progressive_learning=False)  # pk=1 ga majburlanadi
        self.assertEqual(PlatformSettings.objects.count(), 1)
        PlatformSettings.get().delete()
        self.assertEqual(PlatformSettings.objects.count(), 1)

    def test_user_actions(self):
        self.login(self.admin)
        act = lambda u, a: self.client.post(reverse("accounts:user_action", args=[u.pk, a]))
        act(self.student, "block")
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_active)
        act(self.student, "unblock")
        self.student.refresh_from_db()
        self.assertTrue(self.student.is_active)
        act(self.teacher, "reject")
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.approval_status, "rejected")
        act(self.student, "delete")
        self.assertFalse(User.objects.filter(pk=self.student.pk).exists())

    def test_admin_cannot_act_on_self_and_others_cannot_act(self):
        self.login(self.admin)
        self.client.post(reverse("accounts:user_action", args=[self.admin.pk, "delete"]))
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.login(self.teacher)
        self.assertEqual(self.client.post(reverse("accounts:user_action", args=[self.student.pk, "delete"])).status_code, 403)
        self.assertTrue(User.objects.filter(pk=self.student.pk).exists())

    def test_blocked_user_session_ends(self):
        self.login(self.student)
        self.login(self.admin)
        self.client.post(reverse("accounts:user_action", args=[self.student.pk, "block"]))
        self.login(self.student)  # force_login inactive uchun ham sessiya yaratadi, lekin keyingi so'rovda chiqariladi
        self.assertEqual(self.client.get(reverse("courses:course_list")).status_code, 302)

    def test_delete_teacher_keeps_course(self):
        from .helpers import full_course
        ctx = full_course(self.teacher)
        self.login(self.admin)
        self.client.post(reverse("accounts:user_action", args=[self.teacher.pk, "delete"]))
        ctx.course.refresh_from_db()
        self.assertIsNone(ctx.course.teacher)
