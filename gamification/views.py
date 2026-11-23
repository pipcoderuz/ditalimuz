from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from courses.models import Course, Enrollment

from . import services


@login_required
def leaderboard(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not (course.can_manage(request.user) or Enrollment.objects.filter(course=course, student=request.user).exists()):
        raise PermissionDenied
    return render(request, "gamification/leaderboard.html", {"course": course, "rows": services.leaderboard(course)})
