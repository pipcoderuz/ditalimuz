from django.urls import path

from . import views

app_name = "community"

urlpatterns = [
    path("forum/", views.thread_list, name="thread_list"),
    path("forum/yangi/", views.thread_create, name="thread_create"),
    path("forum/<int:pk>/", views.thread_detail, name="thread_detail"),
    path("forum/<int:pk>/ochirish/", views.thread_delete, name="thread_delete"),
    path("forum/javob/<int:pk>/ochirish/", views.post_delete, name="post_delete"),
    path("bildirishnomalar/", views.notifications, name="notifications"),
    path("bildirishnomalar/hammasi/", views.notifications_read_all, name="notifications_read_all"),
    path("bildirishnomalar/<int:pk>/", views.notification_open, name="notification_open"),
    path("xabarlar/", views.inbox, name="inbox"),
    path("xabarlar/yozish/<int:user_id>/", views.start_chat, name="start_chat"),
    path("xabarlar/<int:room_id>/", views.chat_room, name="chat_room"),
    path("chat/<int:room_id>/tarix/", views.chat_history, name="chat_history"),
    path("chat/<int:room_id>/yuborish/", views.chat_send, name="chat_send"),
]
