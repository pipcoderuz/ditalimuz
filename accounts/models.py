from django.contrib.auth.models import AbstractUser
from django.db import models


class PlatformSettings(models.Model):
    """Platformaning umumiy sozlamalari (yagona yozuv). Admin boshqaradi."""

    progressive_learning = models.BooleanField(
        "Progressiv o'qitish (qat'iy ketma-ketlik)",
        default=True,
        help_text="Yoqilsa: mavzu → mavzu, modul → modul ketma-ketligi majburiy bo'ladi.",
    )
    plagiarism_threshold = models.PositiveSmallIntegerField(
        "Plagiat ogohlantirish chegarasi (%)", default=70, help_text="Shu foizdan yuqori o'xshashlik 'flag' qilinadi."
    )

    chat_enabled = models.BooleanField("Chat yoqilgan", default=True, help_text="O'chirilsa, hech kim xabar yoza olmaydi.")

    class Meta:
        verbose_name = "Platforma sozlamalari"
        verbose_name_plural = "Platforma sozlamalari"

    def __str__(self):
        return "Platforma sozlamalari"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        kwargs.pop("force_insert", None)  # create() ham mavjud yozuvni yangilasin, unique xatosi chiqmasin
        super().save(**kwargs)

    def delete(self, *args, **kwargs):  # yagona yozuvni o'chirib bo'lmaydi
        return


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = "student", "Talaba"
        TEACHER = "teacher", "O'qituvchi"
        ADMIN = "admin", "Administrator"

    class Approval(models.TextChoices):
        APPROVED = "approved", "Tasdiqlangan"
        PENDING = "pending", "Tasdiq kutilmoqda"
        REJECTED = "rejected", "Rad etilgan"

    role = models.CharField("Rol", max_length=10, choices=Role.choices, default=Role.STUDENT)
    approval_status = models.CharField("Tasdiq holati", max_length=10, choices=Approval.choices, default=Approval.APPROVED)
    avatar = models.ImageField("Rasm (avatar)", upload_to="avatars/", blank=True)
    bio = models.TextField("O'zi haqida", blank=True)
    phone = models.CharField("Telefon", max_length=30, blank=True)
    github_username = models.CharField("GitHub username", max_length=60, blank=True)
    extra_data = models.JSONField("Qo'shimcha ma'lumotlar", default=dict, blank=True,
                                  help_text="Admin qo'shgan forma maydonlari qiymatlari")

    class Meta:
        verbose_name = "Foydalanuvchi"
        verbose_name_plural = "Foydalanuvchilar"

    def save(self, *args, **kwargs):
        if self.is_superuser:  # createsuperuser orqali yaratilganlar Administrator bo'ladi
            self.role = self.Role.ADMIN
        if self.role == self.Role.ADMIN:
            self.is_staff = True
            self.is_superuser = True
            self.approval_status = self.Approval.APPROVED
        super().save(*args, **kwargs)

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_teacher(self):
        return self.role == self.Role.TEACHER

    @property
    def is_platform_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def can_teach(self):
        return self.role in (self.Role.TEACHER, self.Role.ADMIN)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = (self.get_full_name() or self.username).split()
        return "".join(p[0] for p in parts[:2]).upper()
