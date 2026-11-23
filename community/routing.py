from django.urls import re_path

from .consumers import ChatConsumer, UserConsumer

websocket_urlpatterns = [
    re_path(r"^ws/chat/(?P<room_id>\d+)/$", ChatConsumer.as_asgi()),
    re_path(r"^ws/me/$", UserConsumer.as_asgi()),
]
