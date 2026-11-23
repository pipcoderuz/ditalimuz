from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts import views as accounts_views

admin.site.site_header = "di-talim.uz — boshqaruv"
admin.site.site_title = "di-talim.uz"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", accounts_views.home, name="home"),
    path("", include("accounts.urls")),
    path("kurslar/", include("courses.urls")),
    path("", include("assessments.urls")),
    path("", include("gamification.urls")),
    path("", include("community.urls")),
    path("", include("analytics.urls")),
    path("", include("design.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
