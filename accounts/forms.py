from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError

from .models import PlatformSettings, User


class StyledMixin:
    """Barcha maydonlarga Tailwind/Flowbite sinflarini qo'shadi."""

    def style_fields(self):
        for field in self.fields.values():
            w = field.widget
            if getattr(w, "attrs", None) is None or "data-rich" in w.attrs:
                continue
            if isinstance(w, forms.CheckboxInput):
                css = "checkbox"
            elif isinstance(w, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
                css = "checkbox"
            elif isinstance(w, forms.FileInput):
                css = "file-input"
            else:
                css = "input"
            w.attrs["class"] = f"{w.attrs.get('class', '')} {css}".replace(" input input", " input").strip()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.style_fields()


BootstrapMixin = StyledMixin  # eski nom (boshqa ilovalardagi importlar uchun)


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        kwargs.setdefault("format", "%Y-%m-%d")
        super().__init__(**kwargs)


class LoginForm(StyledMixin, AuthenticationForm):
    def clean(self):
        try:
            return super().clean()
        except ValidationError:
            username, password = self.cleaned_data.get("username"), self.cleaned_data.get("password")
            user = User.objects.filter(username=username).first() if username else None
            if user and not user.is_active and password and user.check_password(password):
                raise ValidationError("Hisobingiz bloklangan. Administrator bilan bog'laning.", code="blocked")
            raise

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.approval_status == User.Approval.PENDING:
            raise ValidationError(
                "Profilingiz administrator tomonidan tasdiqlanishi kutilmoqda. Tasdiqlangach tizimga kira olasiz.", code="pending"
            )
        if user.approval_status == User.Approval.REJECTED:
            raise ValidationError("Arizangiz administrator tomonidan rad etilgan.", code="rejected")


def _dynamic_mixin():
    from design.dynamic import DynamicFormMixin

    return DynamicFormMixin


class RegistrationForm(StyledMixin, UserCreationForm):
    ROLE_CHOICES = [(User.Role.STUDENT, "Talaba"), (User.Role.TEACHER, "O'qituvchi (admin tasdig'i kerak)")]
    role = forms.ChoiceField(label="Men —", choices=ROLE_CHOICES, initial=User.Role.STUDENT)
    first_name = forms.CharField(label="Ism", max_length=60)
    last_name = forms.CharField(label="Familiya", max_length=60)
    email = forms.EmailField(label="Email")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("role", "username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dyn = _dynamic_mixin()
        self._dyn_obj = type("Dyn", (self._dyn,), {"dynamic_purpose": "register"})()
        self._dyn_obj.fields = self.fields
        self._dyn_obj.style_fields = self.style_fields
        self._dyn_obj._load_dynamic(role=None)
        self.style_fields()

    def clean(self):
        data = super().clean()
        if data.get("role"):
            self._dyn_obj.cleaned_data = data
            self._dyn_obj.add_error = self.add_error
            self._dyn_obj.clean_dynamic_required(data["role"])
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        role = self.cleaned_data["role"]
        # Faqat talaba yoki o'qituvchi tanlash mumkin; admin rolini ro'yxatdan olib bo'lmaydi
        user.role = User.Role.TEACHER if role == User.Role.TEACHER else User.Role.STUDENT
        user.approval_status = User.Approval.PENDING if user.role == User.Role.TEACHER else User.Approval.APPROVED
        user.is_staff = user.is_superuser = False
        self._dyn_obj.cleaned_data = self.cleaned_data
        user.extra_data = self._dyn_obj.dynamic_values(user.role)
        if commit:
            user.save()
        return user


class ProfileForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "avatar", "email", "phone", "github_username", "bio")
        widgets = {"bio": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dyn_obj = type("Dyn", (_dynamic_mixin(),), {"dynamic_purpose": "profile"})()
        self._dyn_obj.fields = self.fields
        self._dyn_obj.style_fields = self.style_fields
        self._dyn_obj._load_dynamic(role=self.instance.role, stored=self.instance.extra_data or {})
        self.style_fields()

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and hasattr(avatar, "size") and avatar.size > 2 * 1024 * 1024:
            raise ValidationError("Rasm hajmi 2 MB dan oshmasligi kerak.")
        return avatar

    def clean(self):
        data = super().clean()
        self._dyn_obj.cleaned_data = data
        self._dyn_obj.add_error = self.add_error
        self._dyn_obj.clean_dynamic_required(self.instance.role)
        return data

    def save(self, commit=True):
        user = super().save(commit=False)
        self._dyn_obj.cleaned_data = self.cleaned_data
        stored = dict(user.extra_data or {})
        stored.update(self._dyn_obj.dynamic_values(user.role))
        user.extra_data = stored
        if commit:
            user.save()
        return user


class PlatformSettingsForm(StyledMixin, forms.ModelForm):
    class Meta:
        model = PlatformSettings
        fields = ("progressive_learning", "plagiarism_threshold", "chat_enabled")

    def clean_plagiarism_threshold(self):
        value = self.cleaned_data["plagiarism_threshold"]
        if not 1 <= value <= 100:
            raise ValidationError("1 dan 100 gacha bo'lishi kerak.")
        return value
