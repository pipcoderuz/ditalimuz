from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline, TabularInline

from accounts.richtext import RichAdminMixin

from .models import BlockItem, FormDefinition, FormFieldDef, FormSubmission, NavItem, SiteBlock, SiteTheme

AUDIENCE = ("show_anonymous", "show_student", "show_teacher", "show_admin")


@admin.register(SiteTheme)
class SiteThemeAdmin(ModelAdmin):
    """Sayt nomi, logotip, favicon, asosiy rang, qorong'i rejim — kodsiz."""

    list_display = ("site_name", "primary_swatch", "default_mode")
    fieldsets = (
        ("Brend", {"fields": ("site_name", "tagline", "logo", "favicon")}),
        ("Ranglar va rejim", {"fields": ("primary_color", "default_mode"),
                              "description": "Asosiy rangni o'zgartirsangiz, barcha tugma va urg'ular avtomatik yangilanadi."}),
        ("Pastki qism", {"fields": ("footer_text",)}),
    )

    @admin.display(description="Asosiy rang")
    def primary_swatch(self, obj):
        return format_html('<span style="display:inline-block;width:1.4rem;height:1.4rem;border-radius:.4rem;background:{}"></span> {}',
                           obj.primary_color, obj.primary_color)

    def has_add_permission(self, request):
        return not SiteTheme.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NavItem)
class NavItemAdmin(ModelAdmin):
    list_display = ("label", "icon", "route", "url", "parent", "order", "is_active", *AUDIENCE)
    list_editable = ("order", "is_active")
    list_filter = ("is_active", "parent")
    fieldsets = (
        (None, {"fields": ("label", "icon", "route", "url", "parent", "new_tab", "badge", "order", "is_active")}),
        ("Kimga ko'rinadi", {"fields": AUDIENCE}),
    )


class BlockItemInline(TabularInline):
    model = BlockItem
    extra = 1
    fields = ("icon", "title", "text", "url", "order")


@admin.register(SiteBlock)
class SiteBlockAdmin(RichAdminMixin, ModelAdmin):
    list_display = ("__str__", "placement", "block_type", "style", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("placement", "block_type", "is_active")
    rich_fields = ("body",)
    inlines = [BlockItemInline]
    fieldsets = (
        ("Komponent", {"fields": ("placement", "block_type", "style", "order", "is_active")}),
        ("Mazmun", {"fields": ("title", "subtitle", "body", "image", "button_label", "button_url", "form")}),
        ("Kimga va qachon ko'rinadi", {"fields": (*AUDIENCE, "show_from", "show_until")}),
    )


class FormFieldInline(TabularInline):
    model = FormFieldDef
    extra = 1
    fields = ("label", "key", "field_type", "required", "choices_text", "placeholder", "for_student", "for_teacher", "order", "is_active")
    prepopulated_fields = {"key": ("label",)}


@admin.register(FormDefinition)
class FormDefinitionAdmin(RichAdminMixin, ModelAdmin):
    list_display = ("title", "slug", "purpose", "is_active", "form_link")
    list_filter = ("purpose", "is_active")
    prepopulated_fields = {"slug": ("title",)}
    rich_fields = ("description",)
    inlines = [FormFieldInline]

    @admin.display(description="Havola")
    def form_link(self, obj):
        return format_html('<a href="/forma/{}/" target="_blank">/forma/{}/</a>', obj.slug, obj.slug) if obj.purpose == "custom" else "—"


@admin.register(FormSubmission)
class FormSubmissionAdmin(ModelAdmin):
    list_display = ("form", "user", "created_at", "preview")
    list_filter = ("form",)
    readonly_fields = ("form", "user", "data", "created_at")

    @admin.display(description="Javob")
    def preview(self, obj):
        return "; ".join(f"{k}: {v}" for k, v in list(obj.data.items())[:3])

    def has_add_permission(self, request):
        return False
