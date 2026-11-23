from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from accounts.richtext import RichAdminMixin

from .models import Certificate, Competency, Course, Enrollment, Module, Topic


class ModuleInline(TabularInline):
    model = Module
    extra = 0
    show_change_link = True


@admin.register(Course)
class CourseAdmin(RichAdminMixin, ModelAdmin):
    list_display = ("title", "teacher", "start_date", "end_date", "is_published")
    list_filter = ("is_published", "teacher")
    search_fields = ("title",)
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("chat_responders",)
    rich_fields = ("description",)
    inlines = [ModuleInline]
    fieldsets = (
        (None, {"fields": ("title", "slug", "description", "teacher", "is_published")}),
        ("Sanalar (ixtiyoriy)", {"fields": ("start_date", "end_date")}),
        ("Chat yo'naltirish", {"fields": ("chat_responders",),
                               "description": "Talabalarning shu kurs bo'yicha chat xabarlari kimga borishini shu yerda belgilang."}),
    )


class TopicInline(TabularInline):
    model = Topic
    extra = 0
    show_change_link = True
    fields = ("title", "order")


@admin.register(Module)
class ModuleAdmin(ModelAdmin):
    list_display = ("title", "course", "order", "start_date", "end_date")
    list_filter = ("course",)
    inlines = [TopicInline]


@admin.register(Topic)
class TopicAdmin(RichAdminMixin, ModelAdmin):
    list_display = ("title", "module", "order")
    list_filter = ("module__course",)
    search_fields = ("title",)
    rich_fields = ("content",)


@admin.register(Enrollment)
class EnrollmentAdmin(ModelAdmin):
    list_display = ("student", "course", "status", "enrolled_at", "started_at", "last_activity_at", "completed_at")
    list_filter = ("status", "course")
    search_fields = ("student__username", "student__first_name", "student__last_name")


admin.site.register(Competency, type("CompetencyAdmin", (ModelAdmin,), {"list_display": ("name", "course")}))
admin.site.register(Certificate, type("CertificateAdmin", (ModelAdmin,), {"list_display": ("code", "enrollment", "final_percent", "issued_at")}))
