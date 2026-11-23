from django.urls import path

from . import views

app_name = "design"

urlpatterns = [path("forma/<slug:slug>/", views.public_form, name="public_form")]
