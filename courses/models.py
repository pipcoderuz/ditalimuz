import uuid
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse


class Course(models.Model):
    title = models.CharField("Nomi", max_length=200)
    slug = models.SlugField("Slug", unique=True)
    description = models.TextField("Tavsif")
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="courses_taught", verbose_name="O'qituvchi"
    )
    start_date = models.DateField("Boshlanish sanasi (ixtiyoriy)", null=True, blank=True)
    end_date = models.DateField("Tugash sanasi (ixtiyoriy)", null=True, blank=True)
    is_published = models.BooleanField("Talabalarga ko'rinsin", default=True)
    chat_responders = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="chat_courses", verbose_name="Chat javobgarlari",
        limit_choices_to={"role__in": ["teacher", "admin"]},
        help_text="Talabalarning shu kurs bo'yicha xabarlari kimga borishini admin belgilaydi. Bo'sh qolsa — kurs o'qituvchisiga.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Kurs"
        verbose_name_plural = "Kurslar"

    def __str__(self):
        return self.title

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("Tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas.")

    def get_absolute_url(self):
        return reverse("courses:course_detail", args=[self.slug])

    def can_manage(self, user):
        return user.is_authenticated and (user.is_platform_admin or (user.is_teacher and self.teacher_id == user.id))

    @property
    def pretest(self):
        return self.quizzes.filter(kind="pretest").first()

    @property
    def final_assignment(self):
        return self.assignments.filter(kind="final").first()


class Competency(models.Model):
    """Kurs kompetensiyasi — test savollari shu kompetensiyaga bog'lanadi (o'sishni o'lchash uchun)."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="competencies")
    name = models.CharField("Kompetensiya", max_length=120)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["course", "name"], name="unique_competency_per_course")]
        verbose_name = "Kompetensiya"
        verbose_name_plural = "Kompetensiyalar"

    def __str__(self):
        return self.name


class Module(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField("Nomi", max_length=200)
    description = models.TextField("Tavsif", blank=True)
    order = models.PositiveSmallIntegerField("Tartib raqami", default=0, help_text="0 — oxiriga qo'shiladi")
    start_date = models.DateField("Boshlanish sanasi (ixtiyoriy)", null=True, blank=True)
    end_date = models.DateField("Tugash sanasi (ixtiyoriy)", null=True, blank=True)

    class Meta:
        ordering = ["course", "order", "id"]
        verbose_name = "Modul"
        verbose_name_plural = "Modullar"

    def __str__(self):
        return f"{self.course.title} — {self.title}"

    def get_absolute_url(self):
        return self.course.get_absolute_url() + f"#modul-{self.pk}"


class Topic(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="topics")
    title = models.CharField("Sarlavha", max_length=200)
    order = models.PositiveSmallIntegerField("Tartib raqami", default=0, help_text="0 — oxiriga qo'shiladi")
    content = models.TextField("Matn", blank=True)
    attachment = models.FileField("Yuklab olinadigan fayl", upload_to="topics/", blank=True)
    video_url = models.URLField("Video havola (YouTube)", blank=True)
    video_file = models.FileField("Video fayl (mp4)", upload_to="topic_videos/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["module", "order", "id"]
        verbose_name = "Mavzu"
        verbose_name_plural = "Mavzular"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("courses:topic_detail", args=[self.pk])

    @property
    def embed_url(self):
        """YouTube havolasini platforma ichida ochiladigan (iframe) ko'rinishga o'tkazadi."""
        if not self.video_url:
            return ""
        parsed = urlparse(self.video_url)
        host, video_id = parsed.netloc.lower(), ""
        if "youtu.be" in host:
            video_id = parsed.path.strip("/")
        elif "youtube.com" in host:
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if not video_id and parsed.path.startswith("/embed/"):
                video_id = parsed.path.split("/embed/")[1]
        return f"https://www.youtube.com/embed/{video_id}" if video_id else ""


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "O'qimoqda"
        COMPLETED = "completed", "Yakunlagan"

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    enrolled_at = models.DateTimeField("Yozilgan vaqti", auto_now_add=True)
    started_at = models.DateTimeField("O'qishni boshlagan vaqti", null=True, blank=True,
                                      help_text="Talaba birinchi marta biror faoliyat (mavzu, test, topshiriq) qilgan payt")
    last_activity_at = models.DateTimeField("Oxirgi faoliyat", null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def touch(self):
        """Talaba faoliyatini qayd etadi: birinchi faoliyat — kursni boshlagan payt."""
        from django.utils import timezone

        now = timezone.now()
        fields = ["last_activity_at"]
        self.last_activity_at = now
        if self.started_at is None:
            self.started_at = now
            fields.append("started_at")
        self.save(update_fields=fields)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "student"], name="one_enrollment_per_course")]
        ordering = ["-enrolled_at"]

    def __str__(self):
        return f"{self.student} → {self.course}"


class TopicProgress(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="topic_progress")
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="progress")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "topic"], name="one_progress_per_topic")]


def _certificate_code():
    return uuid.uuid4().hex[:10].upper()


class Certificate(models.Model):
    enrollment = models.OneToOneField(Enrollment, on_delete=models.CASCADE, related_name="certificate")
    code = models.CharField(max_length=12, unique=True, default=_certificate_code)
    final_percent = models.FloatField(default=0)
    issued_at = models.DateTimeField(auto_now_add=True)

    def get_absolute_url(self):
        return reverse("courses:certificate", args=[self.code])
