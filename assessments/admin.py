from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from accounts.richtext import RichAdminMixin

from .models import Assignment, Attempt, OpenAnswer, OpenQuestion, PlagiarismFlag, Question, Quiz, RubricCriterion, Submission


class QuestionInline(TabularInline):
    model = Question
    extra = 0
    show_change_link = True
    fields = ("text", "kind", "points", "competency")


@admin.register(Quiz)
class QuizAdmin(RichAdminMixin, ModelAdmin):
    list_display = ("title", "course", "kind", "max_score", "pass_score")
    list_filter = ("course", "kind")
    rich_fields = ("description",)
    inlines = [QuestionInline]


class CriterionInline(TabularInline):
    model = RubricCriterion
    extra = 0


@admin.register(Assignment)
class AssignmentAdmin(RichAdminMixin, ModelAdmin):
    list_display = ("title", "course", "kind", "max_score", "pass_score")
    list_filter = ("course", "kind")
    rich_fields = ("description",)
    inlines = [CriterionInline]


@admin.register(Submission)
class SubmissionAdmin(ModelAdmin):
    list_display = ("student", "assignment", "status", "total_score", "submitted_at")
    list_filter = ("status", "assignment__course")


@admin.register(PlagiarismFlag)
class PlagiarismFlagAdmin(ModelAdmin):
    list_display = ("assignment", "submission_a", "submission_b", "score", "status")
    list_filter = ("status",)


@admin.register(OpenQuestion)
class OpenQuestionAdmin(ModelAdmin):
    list_display = ("text", "course", "topic", "max_score")


admin.site.register(Attempt, type("AttemptAdmin", (ModelAdmin,), {"list_display": ("student", "quiz", "score", "passed", "submitted_at")}))
admin.site.register(OpenAnswer, type("OpenAnswerAdmin", (ModelAdmin,), {"list_display": ("student", "question", "status", "score")}))
