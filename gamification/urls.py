from django.urls import path

from . import views

app_name = "gamification"

urlpatterns = [path("kurslar/<slug:slug>/reyting/", views.leaderboard, name="leaderboard")]
