from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import ChatMessage, ChatRoom, Notification, Post, Thread


class ChatMessageInline(TabularInline):
    model = ChatMessage
    extra = 0
    fields = ("sender", "body", "created_at")
    readonly_fields = ("created_at",)


@admin.register(ChatRoom)
class ChatRoomAdmin(ModelAdmin):
    list_display = ("id", "kind", "user_a", "user_b", "student", "topic", "created_at")
    list_filter = ("kind",)
    inlines = [ChatMessageInline]


@admin.register(Thread)
class ThreadAdmin(ModelAdmin):
    list_display = ("title", "author", "course", "created_at")


admin.site.register(Post, type("PostAdmin", (ModelAdmin,), {"list_display": ("thread", "author", "created_at")}))
admin.site.register(Notification, type("NotificationAdmin", (ModelAdmin,), {"list_display": ("user", "text", "is_read", "created_at")}))
