from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

app_name = "accounts"

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(template_name="accounts/login.html", authentication_form=LoginForm), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/profile/", views.profile_edit, name="profile"),
    path("profil/<str:username>/", views.profile_public, name="profile_public"),
    path("boshqaruv/", views.admin_panel, name="admin_panel"),
    path("boshqaruv/sozlamalar/", views.settings_update, name="settings_update"),
    path("boshqaruv/chat/", views.chat_routing, name="chat_routing"),
    path("boshqaruv/chat/<int:course_id>/", views.chat_routing_update, name="chat_routing_update"),
    path("boshqaruv/dizayn/", views.design_center, name="design_center"),
    path("yuklash/rasm/", views.upload_image, name="upload_image"),
    path("boshqaruv/foydalanuvchi/<int:pk>/<str:action>/", views.user_action, name="user_action"),
]
