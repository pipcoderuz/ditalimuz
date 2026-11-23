from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import UserBadge

admin.site.register(UserBadge, type("UserBadgeAdmin", (ModelAdmin,), {"list_display": ("user", "code", "course", "awarded_at")}))
