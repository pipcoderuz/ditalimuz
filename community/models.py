from django.conf import settings
from django.db import models
from django.urls import reverse


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    text = models.CharField(max_length=255)
    url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class ChatRoom(models.Model):
    """Chat xonasi: ikki kishi o'rtasida (direct) yoki mavzu doirasida talaba ↔ javobgarlar (topic)."""

    class Kind(models.TextChoices):
        DIRECT = "direct", "Shaxsiy"
        TOPIC = "topic", "Mavzu bo'yicha"

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.DIRECT)
    user_a = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    user_b = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    topic = models.ForeignKey("courses.Topic", null=True, blank=True, on_delete=models.CASCADE, related_name="chat_rooms")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="topic_chat_rooms")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_a", "user_b"], condition=models.Q(kind="direct"), name="unique_direct_room"),
            models.UniqueConstraint(fields=["topic", "student"], condition=models.Q(kind="topic"), name="unique_topic_room"),
        ]

    @property
    def course(self):
        return self.topic.module.course if self.topic_id else None


class ChatMessage(models.Model):
    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class ChatReadState(models.Model):
    """Foydalanuvchi xonada qaysi xabargacha o'qiganini eslab qoladi (o'qilmaganlar hisobi uchun)."""

    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="read_states")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    last_message_id = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["room", "user"], name="one_read_state_per_user_room")]


class Thread(models.Model):
    course = models.ForeignKey("courses.Course", null=True, blank=True, on_delete=models.CASCADE, related_name="threads")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="threads")
    title = models.CharField("Mavzu", max_length=200)
    body = models.TextField("Savol / xabar")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def get_absolute_url(self):
        return reverse("community:thread_detail", args=[self.pk])


class Post(models.Model):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="posts")
    body = models.TextField("Javob")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
