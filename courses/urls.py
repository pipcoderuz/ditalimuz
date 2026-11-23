from django.urls import path

from . import views

app_name = "courses"

urlpatterns = [
    path("", views.course_list, name="course_list"),
    path("yangi/", views.course_create, name="course_create"),
    path("talabalarim/", views.my_students, name="my_students"),
    path("sertifikat/<str:code>/", views.certificate, name="certificate"),
    path("modul/<int:pk>/tahrirlash/", views.module_edit, name="module_edit"),
    path("modul/<int:pk>/ochirish/", views.module_delete, name="module_delete"),
    path("modul/<int:pk>/mavzu/yangi/", views.topic_create, name="topic_create"),
    path("mavzu/<int:pk>/", views.topic_detail, name="topic_detail"),
    path("mavzu/<int:pk>/tahrirlash/", views.topic_edit, name="topic_edit"),
    path("mavzu/<int:pk>/ochirish/", views.topic_delete, name="topic_delete"),
    path("mavzu/<int:pk>/tugatish/", views.topic_complete, name="topic_complete"),
    path("kompetensiya/<int:pk>/ochirish/", views.competency_delete, name="competency_delete"),
    path("<slug:slug>/", views.course_detail, name="course_detail"),
    path("<slug:slug>/tahrirlash/", views.course_edit, name="course_edit"),
    path("<slug:slug>/ochirish/", views.course_delete, name="course_delete"),
    path("<slug:slug>/yozilish/", views.enroll, name="enroll"),
    path("<slug:slug>/modul/yangi/", views.module_create, name="module_create"),
    path("<slug:slug>/kompetensiyalar/", views.competencies, name="competencies"),
]
