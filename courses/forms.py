from django import forms
from django.core.exceptions import ValidationError

from accounts.forms import DateInput, StyledMixin
from accounts.richtext import RichTextFormField

from .models import Competency, Course, Module, Topic


class CourseForm(StyledMixin, forms.ModelForm):
    description = RichTextFormField(label="Tavsif")

    class Meta:
        model = Course
        fields = ("title", "description", "start_date", "end_date", "is_published")
        widgets = {"start_date": DateInput(), "end_date": DateInput()}

    def clean(self):
        data = super().clean()
        s, e = data.get("start_date"), data.get("end_date")
        if s and e and e < s:
            raise ValidationError("Tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas.")
        return data


class ModuleForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Module
        fields = ("title", "description", "order", "start_date", "end_date")
        widgets = {"description": forms.Textarea(attrs={"rows": 2}), "start_date": DateInput(), "end_date": DateInput()}

    def __init__(self, *args, course=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.course = course
        self.fields["order"].required = False
        self.style_fields()

    def clean(self):
        data = super().clean()
        s, e, c = data.get("start_date"), data.get("end_date"), self.course
        if s and e and e < s:
            raise ValidationError("Modul tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas.")
        if c.start_date and ((s and s < c.start_date) or (e and e < c.start_date)):
            raise ValidationError(f"Modul sanalari kurs boshlanishidan ({c.start_date:%d.%m.%Y}) oldin bo'lmasligi kerak.")
        if c.end_date and ((e and e > c.end_date) or (s and s > c.end_date)):
            raise ValidationError(f"Modul sanalari kurs tugashidan ({c.end_date:%d.%m.%Y}) keyin bo'lmasligi kerak.")
        return data


class TopicForm(StyledMixin, forms.ModelForm):
    content = RichTextFormField(label="Mavzu matni", required=False)

    class Meta:
        model = Topic
        fields = ("title", "order", "content", "attachment", "video_url", "video_file")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].required = False
        self.style_fields()


class CompetencyForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = Competency
        fields = ("name",)
