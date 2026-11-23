"""Real-time chat: javobgarlarni admin belgilashi, ruxsatlar, HTTP zaxira yo'li va WebSocket (Channels)."""
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.test import TransactionTestCase
from django.urls import reverse

from accounts.models import PlatformSettings
from community import chat
from community.models import ChatMessage, ChatRoom, Notification
from community.notify import notify
from community.routing import websocket_urlpatterns

from .helpers import BaseTest, enroll, full_course, mk_user


class ChatBase(BaseTest):
    def setUp(self):
        self.teacher, self.teacher2 = mk_user("t1", "teacher"), mk_user("t2", "teacher")
        self.s1, self.s2, self.admin = mk_user("s1"), mk_user("s2"), mk_user("boss", "admin")
        self.ctx = full_course(self.teacher)
        enroll(self.ctx.course, self.s1)
        self.course = self.ctx.course
        self.topic = self.ctx.t1

    def disable_chat(self):
        s = PlatformSettings.get()
        s.chat_enabled = False
        s.save()


class ResponderRoutingTests(ChatBase):
    def test_default_responder_is_course_teacher(self):
        self.assertEqual([u.username for u in chat.responders(self.course)], ["t1"])

    def test_admin_chosen_responders_replace_teacher(self):
        self.course.chat_responders.set([self.teacher2])
        self.assertEqual([u.username for u in chat.responders(self.course)], ["t2"])

    def test_inactive_responders_ignored_then_fallback(self):
        self.course.chat_responders.set([self.teacher2])
        self.teacher2.is_active = False
        self.teacher2.save()
        self.assertEqual([u.username for u in chat.responders(self.course)], ["t1"])

    def test_fallback_to_admins_without_teacher(self):
        self.course.teacher = None
        self.course.save()
        self.assertEqual([u.username for u in chat.responders(self.course)], ["boss"])

    def test_topic_room_access_follows_admin_routing(self):
        room = chat.topic_room(self.topic, self.s1)
        self.assertTrue(chat.can_access_room(self.teacher, room))
        self.assertFalse(chat.can_access_room(self.teacher2, room))
        self.course.chat_responders.set([self.teacher2])           # admin yo'naltirishni o'zgartirdi
        self.assertFalse(chat.can_access_room(self.teacher, room))  # endi kurs o'qituvchisi ham ko'rmaydi
        self.assertTrue(chat.can_access_room(self.teacher2, room))
        self.assertTrue(chat.can_access_room(self.s1, room))
        self.assertFalse(chat.can_access_room(self.s2, room))
        self.assertTrue(chat.can_access_room(self.admin, room))     # admin hammasini ko'radi

    def test_can_message_rules(self):
        self.assertTrue(chat.can_message(self.teacher, self.s1))
        self.assertTrue(chat.can_message(self.s1, self.teacher))
        self.assertFalse(chat.can_message(self.teacher2, self.s1))   # javobgar emas
        self.assertFalse(chat.can_message(self.teacher, self.s2))    # yozilmagan
        self.assertFalse(chat.can_message(self.s1, self.s2))         # talabalar o'zaro yozolmaydi
        self.assertFalse(chat.can_message(self.teacher, self.teacher2))
        self.assertFalse(chat.can_message(self.s1, self.s1))
        self.assertTrue(chat.can_message(self.admin, self.s2))
        self.assertTrue(chat.can_message(self.s2, self.admin))
        self.course.chat_responders.set([self.teacher2])
        self.assertTrue(chat.can_message(self.s1, self.teacher2))
        self.assertFalse(chat.can_message(self.s1, self.teacher))

    def test_chat_disabled_blocks_everything(self):
        room = chat.topic_room(self.topic, self.s1)
        self.disable_chat()
        self.assertFalse(chat.can_message(self.teacher, self.s1))
        self.assertFalse(chat.can_access_room(self.s1, room))
        self.assertFalse(chat.can_access_room(self.admin, room))

    def test_admin_routing_page(self):
        url = reverse("accounts:chat_routing")
        self.login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.login(self.admin)
        self.assertContains(self.client.get(url), self.course.title)
        self.client.post(reverse("accounts:chat_routing_update", args=[self.course.pk]),
                         {"responders": [self.teacher2.pk, self.s1.pk]})  # talaba javobgar bo'la olmaydi
        self.assertEqual(list(self.course.chat_responders.values_list("username", flat=True)), ["t2"])
        self.client.post(reverse("accounts:chat_routing_update", args=[self.course.pk]), {})
        self.assertEqual(self.course.chat_responders.count(), 0)    # bo'sh -> kurs o'qituvchisiga qaytadi
        self.login(self.teacher)
        self.assertEqual(self.client.post(reverse("accounts:chat_routing_update", args=[self.course.pk]), {"responders": [self.teacher2.pk]}).status_code, 403)


class RoomTests(ChatBase):
    def test_direct_room_is_canonical(self):
        a, b = chat.direct_room(self.teacher, self.s1), chat.direct_room(self.s1, self.teacher)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(ChatRoom.objects.filter(kind="direct").count(), 1)
        self.assertLess(a.user_a_id, a.user_b_id)

    def test_topic_room_per_student(self):
        enroll(self.course, self.s2)
        r1, r1b, r2 = chat.topic_room(self.topic, self.s1), chat.topic_room(self.topic, self.s1), chat.topic_room(self.topic, self.s2)
        self.assertEqual(r1.pk, r1b.pk)
        self.assertNotEqual(r1.pk, r2.pk)
        self.assertEqual(r1.course, self.course)

    def test_participants(self):
        room = chat.topic_room(self.topic, self.s1)
        self.assertEqual(chat.participant_ids(room), {self.s1.id, self.teacher.id})
        self.course.chat_responders.set([self.teacher2, self.admin])
        self.assertEqual(chat.participant_ids(room), {self.s1.id, self.teacher2.id, self.admin.id})

    def test_unread_counting_and_mark_read(self):
        room = chat.topic_room(self.topic, self.s1)
        chat.send_message(room, self.s1, "Birinchi")
        chat.send_message(room, self.s1, "Ikkinchi")
        self.assertEqual((chat.unread_count(self.teacher), chat.unread_count(self.s1)), (2, 0))
        chat.send_message(room, self.teacher, "Javob")
        self.assertEqual((chat.unread_count(self.teacher), chat.unread_count(self.s1)), (0, 1))
        chat.mark_read(self.s1, room)
        self.assertEqual(chat.unread_count(self.s1), 0)
        self.assertEqual(chat.room_unread(self.teacher, room), 0)

    def test_send_validation(self):
        from django.core.exceptions import PermissionDenied, ValidationError
        room = chat.topic_room(self.topic, self.s1)
        with self.assertRaises(ValidationError):
            chat.send_message(room, self.s1, "   ")
        with self.assertRaises(ValidationError):
            chat.send_message(room, self.s1, "x" * (chat.MAX_LEN + 1))
        with self.assertRaises(PermissionDenied):
            chat.send_message(room, self.s2, "salom")
        self.assertEqual(ChatMessage.objects.count(), 0)
        self.assertEqual(chat.send_message(room, self.s1, "  salom  ").body, "salom")  # bo'shliqlar kesiladi


class ChatHTTPTests(ChatBase):
    def room(self):
        return chat.topic_room(self.topic, self.s1)

    def test_start_chat_redirects_to_direct_room(self):
        self.login(self.s1)
        resp = self.client.get(reverse("community:start_chat", args=[self.teacher.pk]))
        room = ChatRoom.objects.get(kind="direct")
        self.assertRedirects(resp, reverse("community:chat_room", args=[room.pk]))
        self.assertEqual(self.client.get(reverse("community:start_chat", args=[self.teacher2.pk])).status_code, 403)

    def test_room_page_permissions(self):
        room = self.room()
        url = reverse("community:chat_room", args=[room.pk])
        for user, code in [(self.s1, 200), (self.teacher, 200), (self.admin, 200), (self.s2, 403), (self.teacher2, 403)]:
            self.login(user)
            self.assertEqual(self.client.get(url).status_code, code, user.username)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_send_and_history_api(self):
        room = self.room()
        send, hist = reverse("community:chat_send", args=[room.pk]), reverse("community:chat_history", args=[room.pk])
        self.login(self.s1)
        resp = self.client.post(send, {"body": "Salom, ustoz"})
        self.assertEqual(resp.status_code, 200)
        msg = resp.json()["message"]
        self.assertEqual((msg["body"], msg["sender_id"], msg["sender_role"]), ("Salom, ustoz", self.s1.id, "student"))
        self.login(self.teacher)
        self.client.post(send, {"body": "Eshitaman"})
        first_id = msg["id"]
        data = self.client.get(hist).json()["messages"]
        self.assertEqual([m["body"] for m in data], ["Salom, ustoz", "Eshitaman"])
        data = self.client.get(hist + f"?after={first_id}").json()["messages"]
        self.assertEqual([m["body"] for m in data], ["Eshitaman"])           # faqat yangilari

    def test_send_errors(self):
        room = self.room()
        send = reverse("community:chat_send", args=[room.pk])
        self.login(self.s1)
        self.assertEqual(self.client.post(send, {"body": "  "}).status_code, 400)
        self.assertEqual(self.client.post(send, {"body": "x" * 2001}).status_code, 400)
        self.assertIn("error", self.client.post(send, {"body": ""}).json())
        self.assertEqual(self.client.get(send).status_code, 405)
        self.login(self.s2)
        self.assertEqual(self.client.post(send, {"body": "kirib olaman"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("community:chat_history", args=[room.pk])).status_code, 403)
        self.assertEqual(ChatMessage.objects.count(), 0)

    def test_chat_disabled_over_http(self):
        room = self.room()
        self.disable_chat()
        self.login(self.s1)
        self.assertEqual(self.client.post(reverse("community:chat_send", args=[room.pk]), {"body": "salom"}).status_code, 403)

    def test_message_is_plain_text_not_html(self):
        room = self.room()
        self.login(self.s1)
        self.client.post(reverse("community:chat_send", args=[room.pk]), {"body": "<script>alert(1)</script>"})
        self.login(self.teacher)
        page = self.client.get(reverse("community:chat_room", args=[room.pk]))
        self.assertNotContains(page, "<script>alert(1)</script>")   # sahifaga HTML sifatida chiqmaydi (JS textContent ishlatadi)

    def test_topic_page_embeds_chat_for_student(self):
        from courses.models import TopicProgress
        from .helpers import pass_pretest
        pass_pretest(self.ctx, self.s1)
        self.login(self.s1)
        resp = self.client.get(self.topic.get_absolute_url())
        room = ChatRoom.objects.get(kind="topic", student=self.s1, topic=self.topic)
        self.assertContains(resp, f'data-room="{room.pk}"')
        self.assertContains(resp, "data-chat")
        self.assertContains(resp, "Javob beruvchilar: T1 Test")

    def test_topic_page_lists_rooms_for_responder(self):
        room = self.room()
        chat.send_message(room, self.s1, "Savolim bor")
        self.login(self.teacher)
        resp = self.client.get(self.topic.get_absolute_url())
        self.assertEqual([(r.pk, u) for r, u in resp.context["rooms"]], [(room.pk, 1)])
        self.assertContains(resp, "S1 Test")

    def test_inbox_and_admin_oversight(self):
        room = self.room()
        chat.send_message(room, self.s1, "Salom")
        self.login(self.teacher)
        self.assertEqual([r["room"].pk for r in self.client.get(reverse("community:inbox")).context["rows"]], [room.pk])
        self.login(self.teacher2)
        self.assertEqual(self.client.get(reverse("community:inbox")).context["rows"], [])
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("community:inbox")).context["rows"], [])
        self.assertEqual(len(self.client.get(reverse("community:inbox") + "?hammasi=1").context["rows"]), 1)

    def test_unread_badge_in_navbar(self):
        room = self.room()
        chat.send_message(room, self.teacher, "Savolga javob")
        self.login(self.s1)
        resp = self.client.get(reverse("courses:course_list"))
        self.assertEqual(resp.context["unread_messages"], 1)
        self.client.get(reverse("community:chat_room", args=[room.pk]))    # xonani ochish o'qilgan qiladi
        self.assertEqual(self.client.get(reverse("courses:course_list")).context["unread_messages"], 0)


class WSBase(TransactionTestCase):
    """WebSocket testlari: haqiqiy commit kerak (consumer boshqa oqimda bazaga murojaat qiladi)."""

    def setUp(self):
        self.teacher, self.teacher2 = mk_user("t1", "teacher"), mk_user("t2", "teacher")
        self.s1, self.s2 = mk_user("s1"), mk_user("s2")
        self.ctx = full_course(self.teacher)
        enroll(self.ctx.course, self.s1)
        self.room = chat.topic_room(self.ctx.t1, self.s1)

    def comm(self, path, user):
        c = WebsocketCommunicator(URLRouter(websocket_urlpatterns), path)
        c.scope["user"] = user
        return c

    def chat_comm(self, user):
        return self.comm(f"/ws/chat/{self.room.pk}/", user)


class ChatWebSocketTests(WSBase):
    async def test_message_reaches_all_participants_and_is_saved(self):
        student, teacher = self.chat_comm(self.s1), self.chat_comm(self.teacher)
        self.assertTrue((await student.connect())[0])
        self.assertTrue((await teacher.connect())[0])
        await student.send_json_to({"body": "Salom, ustoz!"})
        got_student = await student.receive_json_from(timeout=3)
        got_teacher = await teacher.receive_json_from(timeout=3)
        for got in (got_student, got_teacher):
            self.assertEqual((got["type"], got["body"], got["sender_id"], got["room"]), ("message", "Salom, ustoz!", self.s1.id, self.room.pk))
        self.assertEqual(await database_sync_to_async(ChatMessage.objects.count)(), 1)
        await teacher.send_json_to({"body": "Eshitaman"})                      # javob qaytadi, sahifa yangilanmasdan
        self.assertEqual((await student.receive_json_from(timeout=3))["body"], "Eshitaman")
        await teacher.receive_json_from(timeout=3)
        await student.disconnect()
        await teacher.disconnect()

    async def test_connection_denied_for_outsiders(self):
        for user in (self.s2, self.teacher2, AnonymousUser()):
            comm = self.chat_comm(user)
            connected, _ = await comm.connect()
            self.assertFalse(connected, getattr(user, "username", "anonim"))

    async def test_admin_can_join_any_room(self):
        admin = await database_sync_to_async(mk_user)("boss", "admin")
        comm = self.chat_comm(admin)
        self.assertTrue((await comm.connect())[0])
        await comm.disconnect()

    async def test_routing_change_takes_effect_on_new_connections(self):
        def reroute():
            self.ctx.course.chat_responders.set([self.teacher2])
        await database_sync_to_async(reroute)()
        self.assertFalse((await self.chat_comm(self.teacher).connect())[0])    # eski o'qituvchi endi kira olmaydi
        t2 = self.chat_comm(self.teacher2)
        self.assertTrue((await t2.connect())[0])
        await t2.disconnect()

    async def test_chat_disabled_denies_connection(self):
        def off():
            s = PlatformSettings.get()
            s.chat_enabled = False
            s.save()
        await database_sync_to_async(off)()
        self.assertFalse((await self.chat_comm(self.s1).connect())[0])

    async def test_invalid_messages_return_error_and_are_not_saved(self):
        comm = self.chat_comm(self.s1)
        await comm.connect()
        await comm.send_json_to({"body": "   "})
        err = await comm.receive_json_from(timeout=3)
        self.assertEqual(err["type"], "error")
        await comm.send_json_to({"body": "x" * 2500})
        self.assertEqual((await comm.receive_json_from(timeout=3))["type"], "error")
        self.assertEqual(await database_sync_to_async(ChatMessage.objects.count)(), 0)
        await comm.disconnect()

    async def test_http_sent_message_appears_on_websocket(self):
        """Zaxira HTTP yo'li bilan yuborilgan xabar ham ochiq WebSocket'larda real-time ko'rinadi."""
        comm = self.chat_comm(self.teacher)
        await comm.connect()
        await database_sync_to_async(chat.send_message)(self.room, self.s1, "HTTP orqali")
        got = await comm.receive_json_from(timeout=3)
        self.assertEqual((got["type"], got["body"]), ("message", "HTTP orqali"))
        await comm.disconnect()


class UserChannelTests(WSBase):
    async def test_new_chat_message_pushes_to_other_participant_only(self):
        teacher, student = self.comm("/ws/me/", self.teacher), self.comm("/ws/me/", self.s1)
        await teacher.connect()
        await student.connect()
        await database_sync_to_async(chat.send_message)(self.room, self.s1, "Yangi savol")
        push = await teacher.receive_json_from(timeout=3)
        self.assertEqual((push["kind"], push["room"], push["sender"], push["preview"]), ("chat", self.room.pk, "S1 Test", "Yangi savol"))
        self.assertTrue(await student.receive_nothing(timeout=0.3))             # yuboruvchining o'ziga push yo'q
        await teacher.disconnect()
        await student.disconnect()

    async def test_notification_is_pushed_in_real_time(self):
        comm = self.comm("/ws/me/", self.s1)
        await comm.connect()
        await database_sync_to_async(notify)(self.s1, "Baholandi: 90/100", "/x/")
        got = await comm.receive_json_from(timeout=3)
        self.assertEqual((got["kind"], got["text"], got["url"]), ("notification", "Baholandi: 90/100", "/x/"))
        self.assertEqual(await database_sync_to_async(Notification.objects.filter(user=self.s1).count)(), 1)
        await comm.disconnect()

    async def test_user_channel_rejects_anonymous(self):
        self.assertFalse((await self.comm("/ws/me/", AnonymousUser()).connect())[0])
