from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Quiz(models.Model):
    class Kind(models.TextChoices):
        PRETEST = "pretest", "Kirish testi (pre-test)"
        TOPIC = "topic", "Mavzu testi"
        MODULE = "module", "Modul testi"
        FINAL = "final", "Yakuniy test"

    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="quizzes")
    module = models.ForeignKey("courses.Module", null=True, blank=True, on_delete=models.CASCADE, related_name="quizzes")
    topic = models.ForeignKey("courses.Topic", null=True, blank=True, on_delete=models.CASCADE, related_name="quizzes")
    kind = models.CharField("Turi", max_length=10, choices=Kind.choices, default=Kind.MODULE)
    title = models.CharField("Nomi", max_length=200)
    description = models.TextField("Tavsif", blank=True)
    max_score = models.PositiveSmallIntegerField("Maksimal ball", default=100)
    pass_score = models.PositiveSmallIntegerField("O'tish uchun minimal ball", default=60)
    max_attempts = models.PositiveSmallIntegerField("Urinishlar soni", default=3, help_text="0 — cheksiz")
    time_limit_minutes = models.PositiveSmallIntegerField("Vaqt chegarasi (daqiqa)", null=True, blank=True)
    required = models.BooleanField("Modulni tugatish uchun majburiy", default=True)
    order = models.PositiveSmallIntegerField("Tartib raqami", default=0, help_text="0 — oxiriga qo'shiladi")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["course", "order", "id"]
        verbose_name = "Test"
        verbose_name_plural = "Testlar"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("assessments:quiz_detail", args=[self.pk])

    @property
    def total_points(self):
        return sum(q.points for q in self.questions.all())


class Question(models.Model):
    class Kind(models.TextChoices):
        SINGLE = "single", "Bitta to'g'ri javob"
        MULTIPLE = "multiple", "Bir nechta to'g'ri javob"

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField("Savol")
    code_snippet = models.TextField("Kod parchasi (ixtiyoriy)", blank=True)
    code_language = models.CharField("Kod tili", max_length=20, default="python", blank=True)
    kind = models.CharField("Turi", max_length=10, choices=Kind.choices, default=Kind.SINGLE)
    points = models.PositiveSmallIntegerField("Savol vazni", default=1)
    competency = models.ForeignKey(
        "courses.Competency", null=True, blank=True, on_delete=models.SET_NULL, related_name="questions", verbose_name="Kompetensiya"
    )
    is_bug_hunt = models.BooleanField("«Xatoni top» savoli", default=False, help_text="«Bug hunter» yutug'i uchun")
    explanation = models.TextField("Tushuntirish", blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["quiz", "order", "id"]

    def __str__(self):
        return self.text[:60]


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField("Variant", max_length=300)
    is_correct = models.BooleanField("To'g'ri", default=False)

    class Meta:
        ordering = ["id"]


class Attempt(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    score = models.FloatField(default=0)
    percent = models.FloatField(default=0)
    passed = models.BooleanField(default=False)
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(auto_now_add=True)
    duration_seconds = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-submitted_at", "-id"]

    def get_absolute_url(self):
        return reverse("assessments:attempt_result", args=[self.pk])


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="answers")
    selected_ids = models.JSONField(default=list)
    is_correct = models.BooleanField(default=False)
    points_earned = models.FloatField(default=0)


class Assignment(models.Model):
    class Kind(models.TextChoices):
        TOPIC = "topic", "Mavzu topshirig'i"
        MODULE = "module", "Modul topshirig'i"
        FINAL = "final", "Yakuniy loyiha"

    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="assignments")
    module = models.ForeignKey("courses.Module", null=True, blank=True, on_delete=models.CASCADE, related_name="assignments")
    topic = models.ForeignKey("courses.Topic", null=True, blank=True, on_delete=models.CASCADE, related_name="assignments")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.MODULE)
    title = models.CharField("Nomi", max_length=200)
    description = models.TextField("Topshiriq sharti")
    max_score = models.PositiveSmallIntegerField("Maksimal ball", default=100, help_text="Rubrika mezonlari yig'indisidan avtomatik hisoblanadi")
    pass_score = models.PositiveSmallIntegerField("O'tish uchun minimal ball", default=60)
    due_date = models.DateField("Topshirish muddati", null=True, blank=True)
    required = models.BooleanField("Modulni tugatish uchun majburiy", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["course", "id"]
        verbose_name = "Topshiriq"
        verbose_name_plural = "Topshiriqlar"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("assessments:assignment_detail", args=[self.pk])

    @property
    def effective_due(self):
        """Topshirish muddati: o'zining sanasi, bo'lmasa modul, bo'lmasa kurs tugash sanasi. Hech biri bo'lmasa — None (muddatsiz)."""
        if self.due_date:
            return self.due_date
        module = self.module or (self.topic.module if self.topic_id else None)
        return (module.end_date if module and module.end_date else None) or self.course.end_date

    def recalc_max_score(self):
        self.max_score = sum(c.max_score for c in self.criteria.all())
        self.save(update_fields=["max_score"])


class RubricCriterion(models.Model):
    """Rubrika mezoni: masalan «To'g'ri ishlashi» — 40 ball."""

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="criteria")
    name = models.CharField("Mezon", max_length=150)
    description = models.CharField("Izoh", max_length=300, blank=True)
    max_score = models.PositiveSmallIntegerField("Maksimal ball")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} ({self.max_score})"


class Submission(models.Model):
    class Method(models.TextChoices):
        ZIP = "zip", "ZIP fayl yuklash"
        GITHUB = "github", "GitHub repozitori havolasi"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Tekshirilmoqda"
        GRADED = "graded", "Baholangan"

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="submissions")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions")
    method = models.CharField("Usul", max_length=10, choices=Method.choices, default=Method.ZIP)
    zip_file = models.FileField("ZIP fayl", upload_to="submissions/%Y/%m/", blank=True)
    github_url = models.URLField("GitHub havolasi", blank=True)
    comment = models.TextField("Izoh", blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    is_late = models.BooleanField(default=False)
    snapshot_error = models.CharField(max_length=300, blank=True)

    # plagiat nazorati uchun
    zip_size = models.PositiveBigIntegerField(default=0)
    zip_sha256 = models.CharField(max_length=64, blank=True)
    fingerprint = models.JSONField(default=dict, blank=True)

    # baholash
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    total_score = models.FloatField(null=True, blank=True)
    percent = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    graded_at = models.DateTimeField(null=True, blank=True)
    teacher_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at", "-id"]

    def __str__(self):
        return f"{self.student} — {self.assignment}"

    def get_absolute_url(self):
        return reverse("assessments:submission_detail", args=[self.pk])


class SubmissionScore(models.Model):
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="scores")
    criterion = models.ForeignKey(RubricCriterion, on_delete=models.CASCADE, related_name="+")
    score = models.PositiveSmallIntegerField(default=0)
    comment = models.CharField(max_length=300, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["submission", "criterion"], name="one_score_per_criterion")]
        ordering = ["criterion_id"]

    @property
    def lost(self):
        """Shu mezondan yo'qotilgan ball."""
        return self.criterion.max_score - self.score


class ReviewComment(models.Model):
    """Code review: aniq fayl va qatorlarga izoh."""

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="review_comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    file_path = models.CharField("Fayl", max_length=300)
    line_start = models.PositiveIntegerField("Qator (dan)")
    line_end = models.PositiveIntegerField("Qator (gacha)", null=True, blank=True)
    text = models.TextField("Izoh")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["file_path", "line_start", "id"]


class PlagiarismFlag(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ko'rib chiqilmagan"
        DISMISSED = "dismissed", "Asossiz (yopildi)"
        CONFIRMED = "confirmed", "Tasdiqlandi"

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="plagiarism_flags")
    submission_a = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="+")
    submission_b = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="+")
    score = models.FloatField()
    details = models.JSONField(default=dict)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["submission_a", "submission_b"], name="unique_plagiarism_pair")]
        ordering = ["-score", "-created_at"]


class OpenQuestion(models.Model):
    """Mavzudagi ochiq savol: talaba matn bilan javob beradi, o'qituvchi qo'lda baholaydi."""

    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="open_questions")
    topic = models.ForeignKey("courses.Topic", on_delete=models.CASCADE, related_name="open_questions")
    text = models.TextField("Savol")
    max_score = models.PositiveSmallIntegerField("Maksimal ball", default=10)
    pass_score = models.PositiveSmallIntegerField("O'tish uchun minimal ball", default=6)
    required = models.BooleanField("Mavzuni tugatish uchun majburiy", default=True)
    order = models.PositiveSmallIntegerField("Tartib raqami", default=0, help_text="0 — oxiriga qo'shiladi")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["topic", "order", "id"]
        verbose_name = "Ochiq savol"
        verbose_name_plural = "Ochiq savollar"

    def __str__(self):
        return self.text[:60]


class OpenAnswer(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Tekshirilmoqda"
        GRADED = "graded", "Baholangan"

    question = models.ForeignKey(OpenQuestion, on_delete=models.CASCADE, related_name="answers")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="open_answers")
    text = models.TextField("Javob")
    submitted_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUBMITTED)
    score = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    graded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["question", "student"], name="one_answer_per_student")]
        ordering = ["-submitted_at"]
