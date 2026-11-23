from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("statistika/", views.overview, name="overview"),
    path("statistika/eksport/", views.overview_csv, name="overview_csv"),
    path("kurslar/<slug:slug>/analitika/", views.course_analytics, name="course_analytics"),
    path("kurslar/<slug:slug>/osish/", views.growth, name="growth"),
    path("kurslar/<slug:slug>/osish/<int:student_id>/", views.growth, name="growth_student"),
    path("kurslar/<slug:slug>/statistika/", views.student_stats, name="student_stats_me"),
    path("kurslar/<slug:slug>/talaba/<int:student_id>/statistika/", views.student_stats, name="student_stats"),
]
