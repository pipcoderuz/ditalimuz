from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import PermissionDenied, ValidationError

from . import chat
from .models import ChatRoom


@database_sync_to_async
def _allowed(user, room_id):
    room = ChatRoom.objects.select_related("topic__module__course__teacher", "student").filter(pk=room_id).first()
    return bool(room and chat.can_access_room(user, room))


@database_sync_to_async
def _send(user, room_id, body):
    room = ChatRoom.objects.select_related("topic__module__course__teacher", "student").get(pk=room_id)
    return chat.send_message(room, user, body)


@database_sync_to_async
def _mark_read(user, room_id):
    room = ChatRoom.objects.filter(pk=room_id).first()
    if room:
        chat.mark_read(user, room)


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """ws/chat/<room_id>/ — xonadagi xabarlarni real-time uzatadi."""

    async def connect(self):
        user = self.scope.get("user")
        self.room_id = int(self.scope["url_route"]["kwargs"]["room_id"])
        if not user or not user.is_authenticated or not await _allowed(user, self.room_id):
            await self.close(code=4403)
            return
        self.group = f"chat_{self.room_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        await _mark_read(user, self.room_id)

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        user = self.scope["user"]
        if content.get("action") == "read":
            await _mark_read(user, self.room_id)
            return
        try:
            await _send(user, self.room_id, content.get("body", ""))
        except (PermissionDenied, ValidationError) as exc:
            await self.send_json({"type": "error", "error": "; ".join(getattr(exc, "messages", [str(exc)]))})

    async def chat_message(self, event):
        message = event["message"]
        await self.send_json({"type": "message", **message})
        if message["sender_id"] != self.scope["user"].id:
            await _mark_read(self.scope["user"], self.room_id)


class UserConsumer(AsyncJsonWebsocketConsumer):
    """ws/me/ — foydalanuvchining shaxsiy kanali: yangi bildirishnoma va xabar haqida darhol xabar beradi."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group = f"user_{user.id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def user_push(self, event):
        await self.send_json(event["payload"])
