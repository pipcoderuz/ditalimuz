from django.contrib.auth import logout


class ApprovalMiddleware:
    """Tasdiqlanmagan (yoki rad etilgan) foydalanuvchi sessiyasini darhol tugatadi."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and user.approval_status != "approved":
            logout(request)
        return self.get_response(request)
