from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import User


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return login_required(wrapper)

    return decorator


teacher_required = role_required(User.Role.TEACHER, User.Role.ADMIN)
student_required = role_required(User.Role.STUDENT)
admin_required = role_required(User.Role.ADMIN)
