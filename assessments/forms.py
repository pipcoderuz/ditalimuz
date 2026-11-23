import zipfile

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from accounts.forms import DateInput, StyledMixin
from accounts.richtext import RichTextFormField

from .github import parse_repo
from .models import Assignment, Choice, OpenAnswer, OpenQuestion, Question, Quiz, RubricCriterion, Submission

CODE_LANGUAGES = [
    ("python", "Python"), ("javascript", "JavaScript"), ("typescript", "TypeScript"), ("java", "Java"), ("cpp", "C++"),
    ("c", "C"), ("csharp", "C#"), ("go", "Go"), ("rust", "Rust"), ("php", "PHP"), ("kotlin", "Kotlin"), ("swift", "Swift"),
    ("sql", "SQL"), ("html", "HTML"), ("css", "CSS"), ("json", "JSON"), ("bash", "Bash"), ("text", "Oddiy matn"),
]


class QuizForm(StyledMixin, forms.ModelForm):
    """Test turi (kirish / mavzu / modul / yakuniy) va qaysi mavzu/modulga tegishli ekani yaratilayotganda belgilanadi."""

    description = RichTextFormField(label="Tavsif", required=False)

    class Meta:
        model = Quiz
        fields = ("title", "description", "max_score", "pass_score", "max_attempts", "time_limit_minutes", "required", "order")

    def __init__(self, *args, course, kind=None, module=None, topic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course
        self.kind = self.instance.kind if self.instance.pk else kind
        self.module = self.instance.module if self.instance.pk else module
        self.topic = self.instance.topic if self.instance.pk else topic
        self.fields["order"].required = False
        if self.kind in (Quiz.Kind.PRETEST, Quiz.Kind.FINAL):
            del self.fields["required"], self.fields["order"]
        if self.kind == Quiz.Kind.PRETEST:
            del self.fields["max_attempts"]
        self.style_fields()

    def clean(self):
        data = super().clean()
        if self.kind in (Quiz.Kind.PRETEST, Quiz.Kind.FINAL):
            others = self.course.quizzes.filter(kind=self.kind).exclude(pk=self.instance.pk)
            if others.exists():
                raise ValidationError("Bu kursda bunday test allaqachon mavjud (faqat bitta bo'lishi mumkin).")
        if data.get("pass_score") is not None and data.get("max_score") is not None and data["pass_score"] > data["max_score"]:
            raise ValidationError("O'tish bali maksimal baldan katta bo'lishi mumkin emas.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.course, obj.kind, obj.module, obj.topic = self.course, self.kind, self.module, self.topic
        if self.kind == Quiz.Kind.PRETEST:
            obj.max_attempts = 1
        if self.kind in (Quiz.Kind.PRETEST, Quiz.Kind.FINAL):
            obj.required = True
        if commit:
            obj.save()
        return obj


class QuestionForm(StyledMixin, forms.ModelForm):
    code_language = forms.ChoiceField(label="Kod tili", choices=CODE_LANGUAGES, initial="python", required=False)

    class Meta:
        model = Question
        fields = ("text", "code_snippet", "code_language", "kind", "points", "competency", "is_bug_hunt", "explanation")
        widgets = {
            "text": forms.Textarea(attrs={"rows": 2}),
            "code_snippet": forms.Textarea(attrs={"rows": 5, "style": "font-family:monospace"}),
            "explanation": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, course=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["competency"].queryset = course.competencies.all()
        self.fields["competency"].required = False
        self.style_fields()


class ChoiceForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Choice
        fields = ("text", "is_correct")


class BaseChoiceFormSet(BaseInlineFormSet):
    def alive_forms(self):
        return [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("text")]

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        alive = self.alive_forms()
        if len(alive) < 2:
            raise ValidationError("Kamida 2 ta javob varianti kiriting.")
        if not any(f.cleaned_data.get("is_correct") for f in alive):
            raise ValidationError("Kamida bitta to'g'ri javobni belgilang.")

    def correct_count(self):
        return sum(1 for f in self.alive_forms() if f.cleaned_data.get("is_correct"))


ChoiceFormSet = inlineformset_factory(Question, Choice, form=ChoiceForm, formset=BaseChoiceFormSet, extra=4, can_delete=True)


class AssignmentForm(StyledMixin, forms.ModelForm):
    description = RichTextFormField(label="Topshiriq sharti")

    class Meta:
        model = Assignment
        fields = ("title", "description", "pass_score", "due_date", "required")
        widgets = {"due_date": DateInput()}

    def __init__(self, *args, kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        kind = self.instance.kind if self.instance.pk else kind
        if kind == Assignment.Kind.FINAL:
            del self.fields["required"]
        self.fields["due_date"].help_text = "Ixtiyoriy. Bo'sh qoldirilsa, muddat modul/kurs sanasiga qarab belgilanadi (yoki muddatsiz)."
        self.style_fields()


class CriterionForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = RubricCriterion
        fields = ("name", "description", "max_score")


class BaseCriteriaFormSet(BaseInlineFormSet):
    def total(self):
        return sum(
            f.cleaned_data["max_score"] for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE") and f.cleaned_data.get("max_score")
        )

    def clean(self):
        super().clean()
        if not any(self.errors) and self.total() <= 0:
            raise ValidationError("Rubrikada kamida bitta mezon (ball > 0) bo'lishi kerak.")


CriteriaFormSet = inlineformset_factory(Assignment, RubricCriterion, form=CriterionForm, formset=BaseCriteriaFormSet, extra=1, can_delete=True)


class SubmissionForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Submission
        fields = ("method", "zip_file", "github_url", "comment")
        widgets = {
            "method": forms.RadioSelect,
            "comment": forms.Textarea(attrs={"rows": 2}),
            "github_url": forms.URLInput(attrs={"placeholder": "https://github.com/foydalanuvchi/repozitoriy"}),
        }

    def clean(self):
        data = super().clean()
        method = data.get("method")
        if method == Submission.Method.ZIP:
            f = data.get("zip_file")
            if not f:
                self.add_error("zip_file", "ZIP faylni yuklang.")
            elif f.size > settings.MAX_ZIP_MB * 1024 * 1024:
                self.add_error("zip_file", f"Fayl hajmi {settings.MAX_ZIP_MB} MB dan oshmasligi kerak.")
            elif not zipfile.is_zipfile(f):
                self.add_error("zip_file", "Bu ZIP arxiv emas.")
            else:
                f.seek(0)
            data["github_url"] = ""
        elif method == Submission.Method.GITHUB:
            url = data.get("github_url", "")
            if not url or not parse_repo(url):
                self.add_error("github_url", "To'g'ri GitHub repozitori havolasini kiriting.")
            data["zip_file"] = None
        return data


class GradeForm(StyledMixin, forms.Form):
    teacher_comment = forms.CharField(label="Umumiy xulosa", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, criteria=(), initial_scores=None, **kwargs):
        super().__init__(*args, **kwargs)
        initial_scores = initial_scores or {}
        self.criteria = list(criteria)
        comment_field = self.fields.pop("teacher_comment")
        for c in self.criteria:
            score, note = initial_scores.get(c.pk, (0, ""))
            self.fields[f"s_{c.pk}"] = forms.IntegerField(
                label=f"{c.name} (0–{c.max_score})", min_value=0, max_value=c.max_score, initial=score, help_text=c.description
            )
            self.fields[f"n_{c.pk}"] = forms.CharField(label=f"{c.name}: izoh", required=False, initial=note, max_length=300)
        self.fields["teacher_comment"] = comment_field
        self.style_fields()

    def scores(self):
        return [(c, self.cleaned_data[f"s_{c.pk}"], self.cleaned_data.get(f"n_{c.pk}", "")) for c in self.criteria]


class ReviewCommentForm(StyledMixin, forms.Form):
    file_path = forms.CharField(label="Fayl", max_length=300)
    line_start = forms.IntegerField(label="Qator (dan)", min_value=1)
    line_end = forms.IntegerField(label="Qator (gacha)", min_value=1, required=False)
    text = forms.CharField(label="Izoh", widget=forms.Textarea(attrs={"rows": 2}))

    def clean(self):
        data = super().clean()
        s, e = data.get("line_start"), data.get("line_end")
        if s and e and e < s:
            self.add_error("line_end", "Oxirgi qator boshlanish qatoridan kichik bo'lishi mumkin emas.")
        return data


class OpenQuestionForm(StyledMixin, forms.ModelForm):
    text = RichTextFormField(label="Savol")

    class Meta:
        model = OpenQuestion
        fields = ("text", "max_score", "pass_score", "required", "order")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].required = False
        self.style_fields()

    def clean(self):
        data = super().clean()
        if data.get("pass_score") is not None and data.get("max_score") is not None and data["pass_score"] > data["max_score"]:
            raise ValidationError("O'tish bali maksimal baldan katta bo'lishi mumkin emas.")
        return data


class OpenAnswerForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = OpenAnswer
        fields = ("text",)
        widgets = {"text": forms.Textarea(attrs={"rows": 5, "placeholder": "Javobingizni yozing..."})}
        labels = {"text": "Javobingiz"}


class OpenGradeForm(StyledMixin, forms.Form):
    score = forms.IntegerField(label="Ball", min_value=0)
    feedback = forms.CharField(label="Izoh", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, question, **kwargs):
        super().__init__(*args, **kwargs)
        self.question = question
        self.fields["score"].max_value = question.max_score
        self.fields["score"].label = f"Ball (0–{question.max_score})"
        self.style_fields()

    def clean_score(self):
        score = self.cleaned_data["score"]
        if score > self.question.max_score:
            raise ValidationError(f"Ball {self.question.max_score} dan oshmasligi kerak.")
        return score
