from django.conf import settings
from django.db import models

BADGES = {
    "perfect_score": {"title": "Perfect score", "icon": "🏆", "desc": "Testni 100% to'g'ri yechdi"},
    "fast_coder": {"title": "Fast coder", "icon": "⚡", "desc": "Loyihani muddatidan oldin topshirdi"},
    "bug_hunter": {"title": "Bug hunter", "icon": "🐞", "desc": "Xatolarni tez va aniq topdi"},
    "first_step": {"title": "Birinchi qadam", "icon": "👣", "desc": "Birinchi mavzuni tugatdi"},
    "graduate": {"title": "Kurs bitiruvchisi", "icon": "🎓", "desc": "Kursni muvaffaqiyatli yakunladi"},
}


class UserBadge(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="badges")
    code = models.CharField(max_length=30)
    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="+")
    awarded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "code", "course"], name="one_badge_per_course")]
        ordering = ["-awarded_at"]

    @property
    def info(self):
        return BADGES.get(self.code, {"title": self.code, "icon": "⭐", "desc": ""})
