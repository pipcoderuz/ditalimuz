"""Admin tuzgan formalarni (FormFieldDef) Django form maydonlariga aylantirish."""
import datetime
import re

from django import forms
from django.core.exceptions import ValidationError

from .models import FormDefinition, FormFieldDef

PHONE_RE = re.compile(r"^\+?[0-9\s()-]{7,20}$")
PREFIX = "x_"


def build_field(fd):
    kw = {"label": fd.label, "required": fd.required, "help_text": fd.help_text}
    attrs = {"placeholder": fd.placeholder} if fd.placeholder else {}
    t = FormFieldDef.Type
    if fd.field_type == t.TEXTAREA:
        return forms.CharField(widget=forms.Textarea(attrs={"rows": 3, **attrs}), **kw)
    if fd.field_type == t.NUMBER:
        return forms.DecimalField(widget=forms.NumberInput(attrs=attrs), **kw)
    if fd.field_type == t.EMAIL:
        return forms.EmailField(widget=forms.EmailInput(attrs=attrs), **kw)
    if fd.field_type == t.URL:
        return forms.URLField(widget=forms.URLInput(attrs=attrs), **kw)
    if fd.field_type == t.PHONE:
        return forms.RegexField(PHONE_RE, error_messages={"invalid": "Telefon raqami noto'g'ri."}, widget=forms.TextInput(attrs=attrs), **kw)
    if fd.field_type == t.DATE:
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"), **kw)
    if fd.field_type == t.SELECT:
        return forms.ChoiceField(choices=[("", "— tanlang —")] + [(c, c) for c in fd.choices], **kw)
    if fd.field_type == t.MULTISELECT:
        return forms.MultipleChoiceField(choices=[(c, c) for c in fd.choices], widget=forms.CheckboxSelectMultiple, **kw)
    if fd.field_type == t.CHECKBOX:
        return forms.BooleanField(**kw)
    return forms.CharField(max_length=500, widget=forms.TextInput(attrs=attrs), **kw)


def serialize(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if hasattr(value, "quantize"):  # Decimal
        return float(value)
    return value


class DynamicFormMixin:
    """ModelForm/Form'ga admin belgilagan qo'shimcha maydonlarni qo'shadi. Qiymatlar user.extra_data da saqlanadi."""

    dynamic_purpose = None  # "register" | "profile"

    def _load_dynamic(self, role=None, stored=None):
        self.dynamic_defs = []
        qs = FormFieldDef.objects.filter(form__purpose=self.dynamic_purpose, form__is_active=True, is_active=True).select_related("form")
        for fd in qs:
            if role is not None and not fd.applies_to(role):
                continue
            field = build_field(fd)
            name = PREFIX + fd.key
            if stored and fd.key in stored:
                field.initial = stored[fd.key]
            if role is None:       # ro'yxatdan o'tish: rol keyin ma'lum bo'ladi — requiredni clean() da tekshiramiz
                field.required, field._really_required = False, fd.required
            self.fields[name] = field
            self.dynamic_defs.append((fd, name))
        return self.dynamic_defs

    def dynamic_values(self, role):
        return {fd.key: serialize(self.cleaned_data.get(name)) for fd, name in self.dynamic_defs
                if fd.applies_to(role) and self.cleaned_data.get(name) not in (None, "", [])}

    def clean_dynamic_required(self, role):
        for fd, name in self.dynamic_defs:
            if fd.required and fd.applies_to(role) and self.cleaned_data.get(name) in (None, "", [], False):
                self.add_error(name, "Bu maydon majburiy.")


def build_standalone_form(form_def, data=None, files=None):
    """/forma/<slug>/ uchun mustaqil forma sinfi."""
    from accounts.forms import BootstrapMixin

    attrs = {PREFIX + fd.key: build_field(fd) for fd in form_def.fields.filter(is_active=True)}
    cls = type("DynamicForm", (BootstrapMixin, forms.Form), attrs)
    # maydonlar tartibi — fields.order bo'yicha (attrs dict tartibi saqlanadi)
    return cls(data, files)
