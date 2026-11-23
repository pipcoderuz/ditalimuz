import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from accounts.richtext import RichTextFormField  # noqa: F401  (admin formalarida ishlatiladi)

from .routes import ROUTE_CHOICES

HEX_VALIDATOR = RegexValidator(r"^#[0-9a-fA-F]{6}$", "To'liq HEX rang kiriting, masalan #4f46e5")
ROLE_KEYS = ("anonymous", "student", "teacher", "admin")


class AudienceMixin(models.Model):
    """Kimga ko'rinishi: mehmon / talaba / o'qituvchi / administrator (kodsiz, belgilash orqali)."""

    show_anonymous = models.BooleanField("Mehmonlarga", default=True)
    show_student = models.BooleanField("Talabalarga", default=True)
    show_teacher = models.BooleanField("O'qituvchilarga", default=True)
    show_admin = models.BooleanField("Administratorlarga", default=True)

    class Meta:
        abstract = True

    def visible_to(self, user):
        key = "anonymous" if not user.is_authenticated else user.role
        return getattr(self, f"show_{key}", False)


class SiteTheme(models.Model):
    """Sayt dizayni sozlamalari (yagona yozuv)."""

    class Mode(models.TextChoices):
        AUTO = "auto", "Qurilma sozlamasiga qarab"
        LIGHT = "light", "Doim yorug'"
        DARK = "dark", "Doim qorong'i"

    site_name = models.CharField("Sayt nomi", max_length=60, default="di-talim.uz")
    tagline = models.CharField("Shior", max_length=160, blank=True, default="Dasturlashni zamonaviy usulda o'rganing")
    logo = models.ImageField("Logotip", upload_to="design/", blank=True)
    favicon = models.ImageField("Favicon", upload_to="design/", blank=True)
    primary_color = models.CharField("Asosiy rang", max_length=7, default="#4f46e5", validators=[HEX_VALIDATOR],
                                     help_text="Tugmalar, havolalar, urg'u ranglari shu rangdan hosil bo'ladi")
    default_mode = models.CharField("Standart rejim", max_length=6, choices=Mode.choices, default=Mode.AUTO)
    footer_text = models.CharField("Pastki qism matni", max_length=250, blank=True,
                                   default="Dasturlashni o'rgatish va kompetensiyalarni rivojlantirish platformasi")

    class Meta:
        verbose_name = "Sayt dizayni"
        verbose_name_plural = "Sayt dizayni"

    def __str__(self):
        return "Sayt dizayni"

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        kwargs.pop("force_insert", None)
        super().save(**kwargs)

    def delete(self, *args, **kwargs):
        return

    def palette(self):
        """Asosiy rangdan 50…950 ranglar palitrasi ("r g b" ko'rinishida, Tailwind CSS o'zgaruvchilari uchun)."""
        h = self.primary_color.lstrip("#")
        base = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

        def mix(color, target, t):
            return tuple(round(c + (target - c) * t) for c in color)

        steps = {50: ((255,) * 3, .92), 100: ((255,) * 3, .84), 200: ((255,) * 3, .68), 300: ((255,) * 3, .5),
                 400: ((255,) * 3, .28), 500: ((255,) * 3, .12), 600: (base, 0), 700: ((0,) * 3, .15),
                 800: ((0,) * 3, .3), 900: ((0,) * 3, .45), 950: ((0,) * 3, .62)}
        out = {}
        for shade, (target, t) in steps.items():
            out[shade] = " ".join(map(str, mix(base, target[0], t) if t else base))
        return out


class NavItem(AudienceMixin):
    """Navbar elementi. Admin qo'shadi, o'chiradi, tartiblaydi va kimga ko'rinishini belgilaydi."""

    class Badge(models.TextChoices):
        NONE = "", "Yo'q"
        MESSAGES = "messages", "O'qilmagan xabarlar soni"

    label = models.CharField("Nomi", max_length=40)
    route = models.CharField("Ichki sahifa", max_length=60, choices=ROUTE_CHOICES, blank=True,
                             help_text="Ro'yxatdan tanlang YOKI quyida tashqi/ixtiyoriy havola kiriting")
    url = models.CharField("Havola (URL)", max_length=300, blank=True, help_text="Masalan /forma/aloqa/ yoki https://t.me/kanal")
    icon = models.CharField("Belgi (emoji)", max_length=8, blank=True)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children",
                               verbose_name="Ota element (ochiladigan menyu)", limit_choices_to={"parent__isnull": True})
    order = models.PositiveSmallIntegerField("Tartib", default=0)
    new_tab = models.BooleanField("Yangi oynada ochilsin", default=False)
    badge = models.CharField("Hisoblagich", max_length=10, choices=Badge.choices, blank=True, default="")
    is_active = models.BooleanField("Faol", default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Navbar elementi"
        verbose_name_plural = "Navbar elementlari"

    def __str__(self):
        return self.label

    def clean(self):
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError("Element o'ziga ota bo'la olmaydi.")

    @property
    def href(self):
        if self.route:
            try:
                return reverse(self.route)
            except NoReverseMatch:
                return "#"
        return self.url or "#"


class FormDefinition(models.Model):
    """Admin tuzadigan forma. purpose=register/profile bo'lsa — ro'yxatdan o'tish/profil formasiga qo'shimcha maydonlar."""

    class Purpose(models.TextChoices):
        CUSTOM = "custom", "Mustaqil forma (/forma/<slug>/)"
        REGISTER = "register", "Ro'yxatdan o'tish formasiga qo'shimcha maydonlar"
        PROFILE = "profile", "Profil sozlamalariga qo'shimcha maydonlar"

    title = models.CharField("Sarlavha", max_length=120)
    slug = models.SlugField("Slug", unique=True)
    purpose = models.CharField("Maqsadi", max_length=10, choices=Purpose.choices, default=Purpose.CUSTOM)
    description = models.TextField("Tavsif", blank=True)
    submit_label = models.CharField("Tugma matni", max_length=40, default="Yuborish")
    success_message = models.CharField("Muvaffaqiyat xabari", max_length=200, default="Rahmat! Ma'lumotlaringiz qabul qilindi.")
    notify_admins = models.BooleanField("Yangi javob kelganda adminlarga xabar berilsin", default=True)
    is_active = models.BooleanField("Faol", default=True)

    class Meta:
        verbose_name = "Forma"
        verbose_name_plural = "Formalar"

    def __str__(self):
        return self.title


class FormFieldDef(models.Model):
    class Type(models.TextChoices):
        TEXT = "text", "Qisqa matn"
        TEXTAREA = "textarea", "Uzun matn"
        NUMBER = "number", "Son"
        EMAIL = "email", "Email"
        URL = "url", "Havola"
        PHONE = "phone", "Telefon"
        DATE = "date", "Sana"
        SELECT = "select", "Ro'yxatdan tanlash"
        MULTISELECT = "multiselect", "Bir nechtasini tanlash"
        CHECKBOX = "checkbox", "Belgilash (ha/yo'q)"

    form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name="fields")
    label = models.CharField("Maydon nomi", max_length=120)
    key = models.SlugField("Kalit", max_length=40, help_text="Lotin harflarida, bo'shliqsiz (masalan: universitet)")
    field_type = models.CharField("Turi", max_length=12, choices=Type.choices, default=Type.TEXT)
    required = models.BooleanField("Majburiy", default=False)
    choices_text = models.TextField("Variantlar", blank=True, help_text="«Ro'yxatdan tanlash» turlari uchun: har qatorga bittadan variant")
    placeholder = models.CharField("Maslahat matni", max_length=120, blank=True)
    help_text = models.CharField("Izoh", max_length=200, blank=True)
    for_student = models.BooleanField("Talabalar uchun", default=True)
    for_teacher = models.BooleanField("O'qituvchilar uchun", default=True)
    order = models.PositiveSmallIntegerField("Tartib", default=0)
    is_active = models.BooleanField("Faol", default=True)

    class Meta:
        ordering = ["form", "order", "id"]
        constraints = [models.UniqueConstraint(fields=["form", "key"], name="unique_field_key_per_form")]
        verbose_name = "Forma maydoni"
        verbose_name_plural = "Forma maydonlari"

    def __str__(self):
        return f"{self.label} ({self.get_field_type_display()})"

    @property
    def choices(self):
        return [c.strip() for c in self.choices_text.splitlines() if c.strip()]

    def applies_to(self, role):
        return (role == "teacher" and self.for_teacher) or (role != "teacher" and self.for_student)


class FormSubmission(models.Model):
    form = models.ForeignKey(FormDefinition, on_delete=models.CASCADE, related_name="submissions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Forma javobi"
        verbose_name_plural = "Forma javoblari"

    def __str__(self):
        return f"{self.form.title} — {self.created_at:%d.%m.%Y %H:%M}"


class SiteBlock(AudienceMixin):
    """Sahifa komponenti (blok). Admin qo'shadi, tahrirlaydi, tartiblaydi, vaqtincha yashiradi."""

    class Placement(models.TextChoices):
        LANDING = "landing", "Bosh sahifa (kirmaganlar uchun)"
        DASHBOARD = "dashboard", "Panel (kirgan foydalanuvchilar uchun)"
        BANNER = "banner", "Sayt tepasidagi e'lon"
        FOOTER = "footer", "Sayt pastki qismi"

    class Type(models.TextChoices):
        HERO = "hero", "Katta bosh blok (Hero)"
        FEATURES = "features", "Kartalar to'plami (imkoniyatlar)"
        RICHTEXT = "richtext", "Matn (rich text)"
        STEPS = "steps", "Bosqichlar"
        FAQ = "faq", "Savol-javoblar"
        STATS = "stats", "Sayt statistikasi"
        CTA = "cta", "Chaqiruv (tugmali)"
        BANNER = "banner", "E'lon / ogohlantirish"
        FORM = "form", "Forma"

    class Style(models.TextChoices):
        PRIMARY = "primary", "Asosiy rang"
        SOFT = "soft", "Yumshoq"
        DARK = "dark", "Qorong'i"
        PLAIN = "plain", "Oddiy"
        WARNING = "warning", "Ogohlantirish (sariq)"

    placement = models.CharField("Joylashuvi", max_length=10, choices=Placement.choices, default=Placement.LANDING)
    block_type = models.CharField("Komponent turi", max_length=10, choices=Type.choices, default=Type.RICHTEXT)
    title = models.CharField("Sarlavha", max_length=160, blank=True)
    subtitle = models.CharField("Qisqa tavsif", max_length=300, blank=True)
    body = models.TextField("Matn", blank=True)
    image = models.ImageField("Rasm", upload_to="design/", blank=True)
    button_label = models.CharField("Tugma matni", max_length=40, blank=True)
    button_url = models.CharField("Tugma havolasi", max_length=300, blank=True)
    form = models.ForeignKey(FormDefinition, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                             verbose_name="Forma", help_text="Faqat «Forma» turi uchun")
    style = models.CharField("Ko'rinishi", max_length=10, choices=Style.choices, default=Style.PLAIN)
    order = models.PositiveSmallIntegerField("Tartib", default=0)
    is_active = models.BooleanField("Faol", default=True)
    show_from = models.DateTimeField("Ko'rsatish boshlanishi", null=True, blank=True)
    show_until = models.DateTimeField("Ko'rsatish tugashi", null=True, blank=True)

    class Meta:
        ordering = ["placement", "order", "id"]
        verbose_name = "Sahifa bloki"
        verbose_name_plural = "Sahifa bloklari"

    def __str__(self):
        return f"{self.get_block_type_display()}: {self.title or '—'}"

    def is_live(self, now=None):
        now = now or timezone.now()
        return self.is_active and (not self.show_from or self.show_from <= now) and (not self.show_until or now <= self.show_until)


class BlockItem(models.Model):
    """Blok ichidagi element: karta, savol-javob, bosqich."""

    block = models.ForeignKey(SiteBlock, on_delete=models.CASCADE, related_name="items")
    icon = models.CharField("Belgi (emoji)", max_length=8, blank=True)
    title = models.CharField("Sarlavha", max_length=160)
    text = models.TextField("Matn", blank=True)
    url = models.CharField("Havola", max_length=300, blank=True)
    order = models.PositiveSmallIntegerField("Tartib", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Blok elementi"
        verbose_name_plural = "Blok elementlari"

    def __str__(self):
        return self.title
