from django import forms

from accounts.forms import StyledMixin
from accounts.richtext import RichTextFormField
from courses.models import Course

from .models import Post, Thread


class ThreadForm(StyledMixin, forms.ModelForm):
    body = RichTextFormField(label="Savol / xabar")

    class Meta:
        model = Thread
        fields = ("course", "title", "body")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["course"].queryset = Course.objects.filter(is_published=True)
        self.fields["course"].required = False
        self.fields["course"].empty_label = "Umumiy savol (kursga bog'lanmagan)"


class PostForm(StyledMixin, forms.ModelForm):
    body = RichTextFormField(label="Javobingiz")

    class Meta:
        model = Post
        fields = ("body",)
