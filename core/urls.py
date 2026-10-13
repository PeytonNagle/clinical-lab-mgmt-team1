from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("home/<str:role>/", views.role_home, name="role_home"),
]
