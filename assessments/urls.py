from django.urls import path

from . import views

app_name = "assessments"

urlpatterns = [
    # testlar
    path("kurslar/<slug:slug>/test/yangi/", views.quiz_create, name="quiz_create"),
    path("test/<int:pk>/", views.quiz_detail, name="quiz_detail"),
    path("test/<int:pk>/tahrirlash/", views.quiz_edit, name="quiz_edit"),
    path("test/<int:pk>/ochirish/", views.quiz_delete, name="quiz_delete"),
    path("test/<int:pk>/savol/yangi/", views.question_create, name="question_create"),
    path("savol/<int:pk>/tahrirlash/", views.question_edit, name="question_edit"),
    path("savol/<int:pk>/ochirish/", views.question_delete, name="question_delete"),
    path("test/<int:pk>/topshirish/", views.quiz_take, name="quiz_take"),
    path("natija/<int:pk>/", views.attempt_result, name="attempt_result"),
    # topshiriqlar
    path("kurslar/<slug:slug>/topshiriq/yangi/", views.assignment_create, name="assignment_create"),
    path("topshiriq/<int:pk>/", views.assignment_detail, name="assignment_detail"),
    path("topshiriq/<int:pk>/tahrirlash/", views.assignment_edit, name="assignment_edit"),
    path("topshiriq/<int:pk>/ochirish/", views.assignment_delete, name="assignment_delete"),
    # tekshirish va code review
    path("ishlar/<int:pk>/", views.submission_detail, name="submission_detail"),
    path("ishlar/<int:pk>/baholash/", views.submission_grade, name="submission_grade"),
    path("ishlar/<int:pk>/izoh/", views.review_comment_add, name="review_comment_add"),
    path("izoh/<int:pk>/ochirish/", views.review_comment_delete, name="review_comment_delete"),
    # ochiq savollar (mavzu ichida)
    path("mavzu/<int:pk>/ochiq-savol/yangi/", views.open_question_create, name="open_question_create"),
    path("ochiq-savol/<int:pk>/tahrirlash/", views.open_question_edit, name="open_question_edit"),
    path("ochiq-savol/<int:pk>/ochirish/", views.open_question_delete, name="open_question_delete"),
    path("ochiq-savol/<int:pk>/javob/", views.open_answer_submit, name="open_answer_submit"),
    path("ochiq-savol/<int:pk>/javoblar/", views.open_question_answers, name="open_question_answers"),
    path("ochiq-javob/<int:pk>/baholash/", views.open_answer_grade, name="open_answer_grade"),
    # plagiat
    path("plagiat/", views.plagiarism_list, name="plagiarism_list"),
    path("plagiat/<int:pk>/holat/", views.plagiarism_update, name="plagiarism_update"),
]
