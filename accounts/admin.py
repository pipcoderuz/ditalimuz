from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from .models import PlatformSettings, User


@admin.register(User)
class CustomUserAdmin(UserAdmin, ModelAdmin):
    form, add_form, change_password_form = UserChangeForm, UserCreationForm, AdminPasswordChangeForm
    list_display = ("username", "get_full_name", "role", "approval_status", "is_active", "date_joined")
    list_filter = ("role", "approval_status", "is_active")
    list_filter_submit = True
    search_fields = ("username", "first_name", "last_name", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("di-talim.uz", {"fields": ("role", "approval_status", "avatar", "phone", "github_username", "bio", "extra_data")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (("di-talim.uz", {"fields": ("role", "first_name", "last_name")}),)


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(ModelAdmin):
    list_display = ("__str__", "progressive_learning", "plagiarism_threshold", "chat_enabled")

    def has_add_permission(self, request):
        return not PlatformSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
